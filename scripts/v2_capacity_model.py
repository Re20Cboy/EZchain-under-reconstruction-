#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from EZ_V2.chain import compute_addr_key, compute_bundle_hash, sign_bundle_envelope
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.encoding import canonical_encode
from EZ_V2.localnet import V2LocalNetwork
from EZ_V2.serde import dumps_json
from EZ_V2.types import (
    AccountLeaf,
    BlockHeaderV2,
    BlockV2,
    BundleEnvelope,
    BundleRef,
    BundleSidecar,
    Checkpoint,
    ConfirmedBundleUnit,
    DiffEntry,
    DiffPackage,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PriorWitnessLink,
    Receipt,
    SparseMerkleProof,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.values import LocalValueStatus, ValueRange


SECONDS_PER_DAY = 86_400
SECONDS_PER_YEAR = 365 * SECONDS_PER_DAY


def human_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PiB"


def json_size(value: object) -> int:
    return len(dumps_json(value).encode("utf-8"))


def binary_size(value: object) -> int:
    return len(canonical_encode(value))


@dataclass(frozen=True)
class SizePair:
    binary: int
    json: int

    @property
    def inflation_ratio(self) -> float:
        if self.binary <= 0:
            return 0.0
        return self.json / self.binary


@dataclass(frozen=True)
class SampleSet:
    tx: SizePair
    sidecar: SizePair
    envelope: SizePair
    bundle_submission_wire: SizePair
    receipt: SizePair
    confirmed_unit: SizePair
    transfer_package_1hop: SizePair
    transfer_package_effective: SizePair
    block_empty: SizePair
    block_with_1_entry: SizePair
    block_with_8_entries: SizePair
    per_block_entry_delta: SizePair
    checkpoint_record: SizePair
    sender_public_key_bytes: int
    smt_depth: int


@dataclass(frozen=True)
class Projection:
    active_users: int
    transfers_total: float
    blocks_total: float
    bundles_total: float
    actual_bundles_per_block: float
    transfers_per_active_user_per_day: float
    effective_witness_hops: int
    user_storage_binary: float
    user_storage_json: float
    user_ingress_binary: float
    user_ingress_json: float
    user_egress_binary: float
    user_egress_json: float
    user_verify_hash_ops_per_incoming: int
    user_verify_hash_ops_per_day: float
    consensus_chain_storage_binary: float
    consensus_chain_storage_json: float
    consensus_receipt_window_binary: float
    consensus_receipt_window_json: float
    consensus_ingress_binary_per_day: float
    consensus_ingress_json_per_day: float
    consensus_egress_binary_per_day: float
    consensus_egress_json_per_day: float
    consensus_hash_ops_per_bundle: int
    consensus_hash_ops_per_day: float


def build_sample_transfer_package(
    *,
    hops: int,
    chain_length_per_hop: int,
    checkpoint_interval: int,
) -> TransferPackage:
    if hops <= 0:
        raise ValueError("hops must be positive")
    if chain_length_per_hop <= 0:
        raise ValueError("chain_length_per_hop must be positive")
    private_keys = []
    addresses = []
    for _ in range(hops + 1):
        private_key, public_key = generate_secp256k1_keypair()
        private_keys.append(private_key)
        addresses.append(address_from_public_key_pem(public_key))

    proof = SparseMerkleProof(
        siblings=tuple(bytes([index % 251]) * 32 for index in range(256)),
        existence=True,
    )

    def make_unit(owner_index: int, seq: int, tx: OffChainTx) -> ConfirmedBundleUnit:
        sender_addr = addresses[owner_index]
        sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=(tx,))
        bundle_hash = compute_bundle_hash(sidecar)
        envelope = BundleEnvelope(
            version=1,
            chain_id=1,
            seq=seq,
            expiry_height=1_000_000,
            fee=1,
            anti_spam_nonce=seq,
            bundle_hash=bundle_hash,
        )
        signed_envelope = sign_bundle_envelope(envelope, private_keys[owner_index])
        block_hash = bytes([(owner_index + 1) % 255 + 1]) * 32
        receipt = Receipt(
            header_lite=HeaderLite(
                height=seq,
                block_hash=block_hash,
                state_root=bytes([(owner_index + 17) % 255 + 1]) * 32,
            ),
            seq=seq,
            prev_ref=None,
            account_state_proof=proof,
        )
        _ = signed_envelope
        return ConfirmedBundleUnit(receipt=receipt, bundle_sidecar=sidecar)

    def build_witness(owner_index: int) -> WitnessV2:
        sender_addr = addresses[owner_index]
        recipient_addr = addresses[owner_index + 1]
        tx = OffChainTx(
            sender_addr=sender_addr,
            recipient_addr=recipient_addr,
            value_list=(ValueRange(0, 99),),
            tx_local_index=0,
            tx_time=owner_index + 1,
        )
        chain = tuple(make_unit(owner_index, owner_index * 1_000 + seq + 1, tx) for seq in range(chain_length_per_hop))
        if owner_index == 0:
            anchor = GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr=sender_addr,
                value_begin=0,
                value_end=999,
            )
        elif checkpoint_interval > 0 and owner_index % checkpoint_interval == 0:
            latest = chain[0]
            anchor = GenesisAnchor(
                genesis_block_hash=latest.receipt.header_lite.block_hash,
                first_owner_addr=sender_addr,
                value_begin=0,
                value_end=999,
            )
        else:
            previous_tx = OffChainTx(
                sender_addr=addresses[owner_index - 1],
                recipient_addr=sender_addr,
                value_list=(ValueRange(0, 99),),
                tx_local_index=0,
                tx_time=owner_index,
            )
            anchor = PriorWitnessLink(
                acquire_tx=previous_tx,
                prior_witness=build_witness(owner_index - 1),
            )
        return WitnessV2(
            value=ValueRange(0, 99),
            current_owner_addr=sender_addr,
            confirmed_bundle_chain=chain,
            anchor=anchor,
        )

    target_tx = OffChainTx(
        sender_addr=addresses[hops - 1],
        recipient_addr=addresses[hops],
        value_list=(ValueRange(0, 99),),
        tx_local_index=0,
        tx_time=hops,
    )
    return TransferPackage(
        target_tx=target_tx,
        target_value=ValueRange(0, 99),
        witness_v2=build_witness(hops - 1),
    )


def build_block(entry_count: int) -> tuple[BlockV2, int]:
    entries = []
    sidecars = []
    public_keys = []
    for index in range(entry_count):
        private_key, public_key = generate_secp256k1_keypair()
        sender_addr = address_from_public_key_pem(public_key)
        recipient_addr = sender_addr[::-1]
        tx = OffChainTx(
            sender_addr=sender_addr,
            recipient_addr=recipient_addr,
            value_list=(ValueRange(index * 100, index * 100 + 9),),
            tx_local_index=0,
            tx_time=index + 1,
        )
        sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=(tx,))
        bundle_hash = compute_bundle_hash(sidecar)
        envelope = sign_bundle_envelope(
            BundleEnvelope(
                version=1,
                chain_id=1,
                seq=index + 1,
                expiry_height=1_000_000,
                fee=1,
                anti_spam_nonce=index + 7,
                bundle_hash=bundle_hash,
            ),
            private_key,
        )
        leaf = AccountLeaf(
            addr=sender_addr,
            head_ref=BundleRef(
                height=1,
                block_hash=b"\x01" * 32,
                bundle_hash=bundle_hash,
                seq=index + 1,
            ),
            prev_ref=None,
        )
        entries.append(
            DiffEntry(
                addr_key=compute_addr_key(sender_addr),
                new_leaf=leaf,
                bundle_envelope=envelope,
                bundle_hash=bundle_hash,
            )
        )
        sidecars.append(sidecar)
        public_keys.append(public_key)
    block = BlockV2(
        block_hash=b"\x02" * 32,
        header=BlockHeaderV2(
            version=2,
            chain_id=1,
            height=1,
            prev_block_hash=b"\x00" * 32,
            state_root=b"\x03" * 32,
            diff_root=b"\x04" * 32,
            timestamp=1,
        ),
        diff_package=DiffPackage(
            diff_entries=tuple(entries),
            sidecars=tuple(sidecars),
            sender_public_keys=tuple(public_keys),
        ),
    )
    sender_public_key_bytes = len(public_keys[0]) if public_keys else 0
    return block, sender_public_key_bytes


def build_samples(hops: int, chain_length_per_hop: int, checkpoint_interval: int) -> SampleSet:
    private_key, public_key = generate_secp256k1_keypair()
    sender_addr = address_from_public_key_pem(public_key)
    recipient_addr = sender_addr[::-1]
    tx = OffChainTx(
        sender_addr=sender_addr,
        recipient_addr=recipient_addr,
        value_list=(ValueRange(0, 99),),
        tx_local_index=0,
        tx_time=1,
    )
    sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=(tx,))
    envelope = sign_bundle_envelope(
        BundleEnvelope(
            version=1,
            chain_id=1,
            seq=1,
            expiry_height=1_000_000,
            fee=1,
            anti_spam_nonce=1,
            bundle_hash=compute_bundle_hash(sidecar),
        ),
        private_key,
    )
    receipt = Receipt(
        header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
        seq=1,
        prev_ref=None,
        account_state_proof=SparseMerkleProof(
            siblings=tuple(bytes([index % 251]) * 32 for index in range(256)),
            existence=True,
        ),
    )
    confirmed_unit = ConfirmedBundleUnit(receipt=receipt, bundle_sidecar=sidecar)
    checkpoint_record = Checkpoint(
        value_begin=0,
        value_end=999,
        owner_addr=sender_addr,
        checkpoint_height=1,
        checkpoint_block_hash=b"\x99" * 32,
        checkpoint_bundle_hash=b"\x88" * 32,
    )
    transfer_package_1hop = build_sample_transfer_package(hops=1, chain_length_per_hop=1, checkpoint_interval=0)
    transfer_package_effective = build_sample_transfer_package(
        hops=hops,
        chain_length_per_hop=chain_length_per_hop,
        checkpoint_interval=checkpoint_interval,
    )
    block_empty, _ = build_block(0)
    block_with_1_entry, sender_public_key_bytes = build_block(1)
    block_with_8_entries, _ = build_block(8)
    return SampleSet(
        tx=SizePair(binary=binary_size(tx), json=json_size(tx)),
        sidecar=SizePair(binary=binary_size(sidecar), json=json_size(sidecar)),
        envelope=SizePair(binary=binary_size(envelope), json=json_size(envelope)),
        bundle_submission_wire=SizePair(
            binary=binary_size(sidecar) + binary_size(envelope) + len(public_key),
            json=json_size(sidecar) + json_size(envelope) + len(public_key) * 2,
        ),
        receipt=SizePair(binary=binary_size(receipt), json=json_size(receipt)),
        confirmed_unit=SizePair(binary=binary_size(confirmed_unit), json=json_size(confirmed_unit)),
        transfer_package_1hop=SizePair(
            binary=binary_size(transfer_package_1hop),
            json=json_size(transfer_package_1hop),
        ),
        transfer_package_effective=SizePair(
            binary=binary_size(transfer_package_effective),
            json=json_size(transfer_package_effective),
        ),
        block_empty=SizePair(binary=binary_size(block_empty), json=json_size(block_empty)),
        block_with_1_entry=SizePair(binary=binary_size(block_with_1_entry), json=json_size(block_with_1_entry)),
        block_with_8_entries=SizePair(binary=binary_size(block_with_8_entries), json=json_size(block_with_8_entries)),
        per_block_entry_delta=SizePair(
            binary=(binary_size(block_with_8_entries) - binary_size(block_empty)) // 8,
            json=(json_size(block_with_8_entries) - json_size(block_empty)) // 8,
        ),
        checkpoint_record=SizePair(binary=binary_size(checkpoint_record), json=json_size(checkpoint_record)),
        sender_public_key_bytes=sender_public_key_bytes,
        smt_depth=256,
    )


def project_costs(
    args: argparse.Namespace,
    samples: SampleSet,
) -> Projection:
    active_users = max(1, math.ceil(args.node_count * args.active_user_ratio))
    transfers_total = args.tx_per_second * SECONDS_PER_YEAR * args.years
    blocks_total = math.ceil((SECONDS_PER_YEAR * args.years) / args.block_interval_seconds)
    bundles_total = transfers_total / max(1.0, args.avg_txs_per_bundle)
    arrival_bundles_per_block = args.tx_per_second * args.block_interval_seconds / max(1.0, args.avg_txs_per_bundle)
    actual_bundles_per_block = min(float(args.bundles_per_block_target), arrival_bundles_per_block)
    transfers_per_active_user_per_day = args.tx_per_second * SECONDS_PER_DAY / active_users

    effective_witness_hops = args.avg_transfer_hops
    if args.checkpoint_interval_hops > 0:
        effective_witness_hops = min(effective_witness_hops, args.checkpoint_interval_hops)
    effective_witness_hops = max(1, effective_witness_hops)

    incoming_transfer_binary = samples.transfer_package_effective.binary
    incoming_transfer_json = samples.transfer_package_effective.json
    outgoing_submission_binary = samples.bundle_submission_wire.binary
    outgoing_submission_json = samples.bundle_submission_wire.json
    incoming_receipt_binary = samples.receipt.binary
    incoming_receipt_json = samples.receipt.json

    sends_per_user = transfers_total / active_users
    receives_per_user = sends_per_user

    user_storage_binary = sends_per_user * incoming_receipt_binary + receives_per_user * incoming_transfer_binary
    user_storage_json = sends_per_user * incoming_receipt_json + receives_per_user * incoming_transfer_json
    user_ingress_binary = sends_per_user * incoming_receipt_binary + receives_per_user * incoming_transfer_binary
    user_ingress_json = sends_per_user * incoming_receipt_json + receives_per_user * incoming_transfer_json
    user_egress_binary = sends_per_user * (outgoing_submission_binary + incoming_transfer_binary)
    user_egress_json = sends_per_user * (outgoing_submission_json + incoming_transfer_json)

    consensus_per_block_binary = samples.block_empty.binary + actual_bundles_per_block * samples.per_block_entry_delta.binary
    consensus_per_block_json = samples.block_empty.json + actual_bundles_per_block * samples.per_block_entry_delta.json
    consensus_chain_storage_binary = blocks_total * consensus_per_block_binary
    consensus_chain_storage_json = blocks_total * consensus_per_block_json

    receipt_window_entries = args.receipt_cache_blocks * actual_bundles_per_block
    consensus_receipt_window_binary = receipt_window_entries * samples.receipt.binary
    consensus_receipt_window_json = receipt_window_entries * samples.receipt.json

    consensus_user_submission_binary_day = args.tx_per_second * SECONDS_PER_DAY * outgoing_submission_binary
    consensus_user_submission_json_day = args.tx_per_second * SECONDS_PER_DAY * outgoing_submission_json
    consensus_block_fanout_binary_day = (
        SECONDS_PER_DAY
        / args.block_interval_seconds
        * consensus_per_block_binary
        * args.consensus_network_overhead_factor
    )
    consensus_block_fanout_json_day = (
        SECONDS_PER_DAY
        / args.block_interval_seconds
        * consensus_per_block_json
        * args.consensus_network_overhead_factor
    )
    consensus_receipt_delivery_binary_day = args.tx_per_second * SECONDS_PER_DAY * incoming_receipt_binary
    consensus_receipt_delivery_json_day = args.tx_per_second * SECONDS_PER_DAY * incoming_receipt_json
    consensus_ingress_binary_per_day = (
        consensus_user_submission_binary_day / args.consensus_nodes + consensus_block_fanout_binary_day
    )
    consensus_ingress_json_per_day = (
        consensus_user_submission_json_day / args.consensus_nodes + consensus_block_fanout_json_day
    )
    consensus_egress_binary_per_day = (
        consensus_receipt_delivery_binary_day / args.consensus_nodes + consensus_block_fanout_binary_day
    )
    consensus_egress_json_per_day = (
        consensus_receipt_delivery_json_day / args.consensus_nodes + consensus_block_fanout_json_day
    )

    user_verify_hash_ops_per_incoming = samples.smt_depth * effective_witness_hops
    user_verify_hash_ops_per_day = user_verify_hash_ops_per_incoming * (
        args.tx_per_second * SECONDS_PER_DAY / active_users
    )
    consensus_hash_ops_per_bundle = samples.smt_depth * 2 + int(math.log2(max(1, math.ceil(actual_bundles_per_block)))) * 8
    consensus_hash_ops_per_day = consensus_hash_ops_per_bundle * bundles_total / max(args.years * 365.0, 1e-9)

    return Projection(
        active_users=active_users,
        transfers_total=transfers_total,
        blocks_total=blocks_total,
        bundles_total=bundles_total,
        actual_bundles_per_block=actual_bundles_per_block,
        transfers_per_active_user_per_day=transfers_per_active_user_per_day,
        effective_witness_hops=effective_witness_hops,
        user_storage_binary=user_storage_binary,
        user_storage_json=user_storage_json,
        user_ingress_binary=user_ingress_binary,
        user_ingress_json=user_ingress_json,
        user_egress_binary=user_egress_binary,
        user_egress_json=user_egress_json,
        user_verify_hash_ops_per_incoming=user_verify_hash_ops_per_incoming,
        user_verify_hash_ops_per_day=user_verify_hash_ops_per_day,
        consensus_chain_storage_binary=consensus_chain_storage_binary,
        consensus_chain_storage_json=consensus_chain_storage_json,
        consensus_receipt_window_binary=consensus_receipt_window_binary,
        consensus_receipt_window_json=consensus_receipt_window_json,
        consensus_ingress_binary_per_day=consensus_ingress_binary_per_day,
        consensus_ingress_json_per_day=consensus_ingress_json_per_day,
        consensus_egress_binary_per_day=consensus_egress_binary_per_day,
        consensus_egress_json_per_day=consensus_egress_json_per_day,
        consensus_hash_ops_per_bundle=consensus_hash_ops_per_bundle,
        consensus_hash_ops_per_day=consensus_hash_ops_per_day,
    )


def run_microbench(args: argparse.Namespace) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ezchain-v2-capacity-") as tmpdir:
        network = V2LocalNetwork(root_dir=tmpdir, chain_id=91, receipt_cache_blocks=args.receipt_cache_blocks)
        try:
            for index in range(args.microbench_users):
                name = f"user{index}"
                network.add_account(name)
                network.allocate_genesis_value(name, ValueRange(index * 10_000, index * 10_000 + 999))

            transfers = 0
            submit_durations = []
            block_durations = []
            deliver_durations = []
            for round_index in range(args.microbench_rounds):
                batch = []
                for offset in range(args.microbench_senders_per_block):
                    sender_index = (round_index * args.microbench_senders_per_block + offset) % args.microbench_users
                    recipient_index = (sender_index + offset + 1) % args.microbench_users
                    sender_name = f"user{sender_index}"
                    recipient_name = f"user{recipient_index}"
                    start = time.perf_counter()
                    payment = network.submit_payment(
                        sender_name,
                        recipient_name,
                        amount=args.microbench_amount,
                        anti_spam_nonce=round_index * 100 + offset + 1,
                        tx_time=round_index + 1,
                    )
                    submit_durations.append(time.perf_counter() - start)
                    batch.append((sender_name, payment.target_tx, payment.target_tx.value_list[0], recipient_name))
                    transfers += 1
                start = time.perf_counter()
                network.produce_block(timestamp=round_index + 1)
                block_durations.append(time.perf_counter() - start)
                for sender_name, target_tx, target_value, recipient_name in batch:
                    start = time.perf_counter()
                    network.deliver_payment(sender_name, target_tx, target_value, recipient=recipient_name)
                    deliver_durations.append(time.perf_counter() - start)

            wallet_files = sorted(Path(tmpdir).glob("user*.sqlite3"))
            wallet_sizes = [item.stat().st_size for item in wallet_files]
            wallet_spendable_counts = []
            wallet_archived_counts = []
            for index in range(args.microbench_users):
                records = network.participant(f"user{index}").wallet.list_records()
                wallet_spendable_counts.append(
                    sum(1 for record in records if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE)
                )
                wallet_archived_counts.append(
                    sum(1 for record in records if record.local_status == LocalValueStatus.ARCHIVED)
                )
            return {
                "transfers": transfers,
                "blocks": args.microbench_rounds,
                "consensus_db_bytes": Path(tmpdir, "consensus.sqlite3").stat().st_size,
                "avg_wallet_db_bytes": statistics.mean(wallet_sizes) if wallet_sizes else 0.0,
                "max_wallet_db_bytes": max(wallet_sizes) if wallet_sizes else 0,
                "avg_submit_ms": statistics.mean(submit_durations) * 1000 if submit_durations else 0.0,
                "avg_block_ms": statistics.mean(block_durations) * 1000 if block_durations else 0.0,
                "avg_deliver_ms": statistics.mean(deliver_durations) * 1000 if deliver_durations else 0.0,
                "avg_spendable_records": statistics.mean(wallet_spendable_counts) if wallet_spendable_counts else 0.0,
                "avg_archived_records": statistics.mean(wallet_archived_counts) if wallet_archived_counts else 0.0,
            }
        finally:
            network.close()


def serialize_samples(samples: SampleSet) -> dict[str, object]:
    payload = {}
    for key, value in asdict(samples).items():
        if isinstance(value, dict) and "binary" in value and "json" in value:
            payload[key] = {
                **value,
                "binary_human": human_bytes(value["binary"]),
                "json_human": human_bytes(value["json"]),
                "json_over_binary": round(value["json"] / max(value["binary"], 1), 3),
            }
        else:
            payload[key] = value
    return payload


def serialize_projection(projection: Projection) -> dict[str, object]:
    raw = asdict(projection)
    humanized = {}
    for key, value in raw.items():
        if "bytes" in key or key.endswith("_storage_binary") or key.endswith("_storage_json"):
            humanized[key] = {
                "bytes": value,
                "human": human_bytes(value),
            }
        else:
            humanized[key] = value
    return humanized


def print_human_report(
    args: argparse.Namespace,
    samples: SampleSet,
    projection: Projection,
    microbench: dict[str, object] | None,
) -> None:
    print("=== EZchain V2 Capacity Model ===")
    print(
        f"nodes={args.node_count}, consensus_nodes={args.consensus_nodes}, "
        f"years={args.years}, global_tps={args.tx_per_second}"
    )
    print(
        f"avg_transfer_hops={args.avg_transfer_hops}, checkpoint_interval_hops={args.checkpoint_interval_hops}, "
        f"avg_sender_chain_len={args.avg_sender_chain_len}"
    )
    print("")
    print("Object sizes")
    print(
        f"- receipt: binary {human_bytes(samples.receipt.binary)}, json {human_bytes(samples.receipt.json)}, "
        f"json/binary x{samples.receipt.inflation_ratio:.2f}"
    )
    print(
        f"- transfer_package(1 hop): binary {human_bytes(samples.transfer_package_1hop.binary)}, "
        f"json {human_bytes(samples.transfer_package_1hop.json)}"
    )
    print(
        f"- transfer_package(effective): binary {human_bytes(samples.transfer_package_effective.binary)}, "
        f"json {human_bytes(samples.transfer_package_effective.json)}"
    )
    print(
        f"- block per-entry delta: binary {human_bytes(samples.per_block_entry_delta.binary)}, "
        f"json {human_bytes(samples.per_block_entry_delta.json)}"
    )
    print("")
    print("Projected user-node cost")
    print(
        f"- active users: {projection.active_users}, tx/day/active-user: {projection.transfers_per_active_user_per_day:.4f}"
    )
    print(
        f"- storage over {args.years} years: binary {human_bytes(projection.user_storage_binary)}, "
        f"json {human_bytes(projection.user_storage_json)}"
    )
    print(
        f"- ingress over {args.years} years: binary {human_bytes(projection.user_ingress_binary)}, "
        f"json {human_bytes(projection.user_ingress_json)}"
    )
    print(
        f"- egress over {args.years} years: binary {human_bytes(projection.user_egress_binary)}, "
        f"json {human_bytes(projection.user_egress_json)}"
    )
    print(
        f"- verify hashes per incoming transfer: {projection.user_verify_hash_ops_per_incoming}, "
        f"per day: {projection.user_verify_hash_ops_per_day:.2f}"
    )
    print("")
    print("Projected consensus-node cost")
    print(f"- actual bundles per block: {projection.actual_bundles_per_block:.2f}")
    print(
        f"- chain storage over {args.years} years: binary {human_bytes(projection.consensus_chain_storage_binary)}, "
        f"json {human_bytes(projection.consensus_chain_storage_json)}"
    )
    print(
        f"- receipt window: binary {human_bytes(projection.consensus_receipt_window_binary)}, "
        f"json {human_bytes(projection.consensus_receipt_window_json)}"
    )
    print(
        f"- avg ingress/day/node: binary {human_bytes(projection.consensus_ingress_binary_per_day)}, "
        f"json {human_bytes(projection.consensus_ingress_json_per_day)}"
    )
    print(
        f"- avg egress/day/node: binary {human_bytes(projection.consensus_egress_binary_per_day)}, "
        f"json {human_bytes(projection.consensus_egress_json_per_day)}"
    )
    print(
        f"- estimated hash ops per bundle: {projection.consensus_hash_ops_per_bundle}, "
        f"per day: {projection.consensus_hash_ops_per_day:.2f}"
    )
    if microbench:
        print("")
        print("Local microbench")
        print(
            f"- transfers={microbench['transfers']}, blocks={microbench['blocks']}, "
            f"consensus_db={human_bytes(float(microbench['consensus_db_bytes']))}"
        )
        print(
            f"- avg wallet db={human_bytes(float(microbench['avg_wallet_db_bytes']))}, "
            f"max wallet db={human_bytes(float(microbench['max_wallet_db_bytes']))}"
        )
        print(
            f"- avg submit={microbench['avg_submit_ms']:.2f} ms, "
            f"avg block={microbench['avg_block_ms']:.2f} ms, "
            f"avg deliver={microbench['avg_deliver_ms']:.2f} ms"
        )
    print("")
    print("Notes")
    print("- This model measures current EZ_V2 object sizes directly, then scales them by traffic assumptions.")
    print("- JSON costs reflect current Python persistence/wire encoding; binary costs reflect the canonical protocol encoding.")
    print("- Consensus traffic includes a configurable overhead factor for HotStuff votes/QC/retries, not a full packet-level simulation.")
    print("- User storage is dominated by transfer-package witness growth and receipt retention; checkpoint frequency is the main compression lever.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate EZchain V2 user/consensus storage, communication, and hash-cost growth."
    )
    parser.add_argument("--node-count", type=int, default=10_000_000)
    parser.add_argument("--consensus-nodes", type=int, default=21)
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--tx-per-second", type=float, default=250.0)
    parser.add_argument("--block-interval-seconds", type=float, default=2.0)
    parser.add_argument("--avg-txs-per-bundle", type=float, default=1.0)
    parser.add_argument("--bundles-per-block-target", type=int, default=500)
    parser.add_argument("--active-user-ratio", type=float, default=0.02)
    parser.add_argument("--avg-transfer-hops", type=int, default=8)
    parser.add_argument("--avg-sender-chain-len", type=int, default=1)
    parser.add_argument("--checkpoint-interval-hops", type=int, default=4)
    parser.add_argument("--receipt-cache-blocks", type=int, default=32)
    parser.add_argument("--consensus-network-overhead-factor", type=float, default=3.0)
    parser.add_argument("--run-microbench", action="store_true")
    parser.add_argument("--microbench-users", type=int, default=8)
    parser.add_argument("--microbench-rounds", type=int, default=16)
    parser.add_argument("--microbench-senders-per-block", type=int, default=4)
    parser.add_argument("--microbench-amount", type=int, default=1)
    parser.add_argument("--json-output", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = build_samples(
        hops=max(1, min(args.avg_transfer_hops, 32)),
        chain_length_per_hop=max(1, min(args.avg_sender_chain_len, 8)),
        checkpoint_interval=max(0, min(args.checkpoint_interval_hops, 32)),
    )
    projection = project_costs(args, samples)
    microbench = run_microbench(args) if args.run_microbench else None
    payload = {
        "inputs": vars(args),
        "samples": serialize_samples(samples),
        "projection": serialize_projection(projection),
        "microbench": microbench,
    }
    if args.json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_human_report(args, samples, projection, microbench)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
