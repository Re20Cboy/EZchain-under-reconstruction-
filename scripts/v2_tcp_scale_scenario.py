#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import LocalValueStatus, ValueRange


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class ConsensusNodeRuntime:
    peer: PeerInfo
    network: TransportPeerNetwork
    host: V2ConsensusHost


@dataclass(frozen=True)
class AccountNodeRuntime:
    peer: PeerInfo
    network: TransportPeerNetwork
    host: V2AccountHost


def _wait_for_consensus_height(
    consensus_nodes: tuple[ConsensusNodeRuntime, ...],
    expected_height: int,
    *,
    timeout_sec: float = 5.0,
) -> int:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        heights = tuple(node.host.consensus.chain.current_height for node in consensus_nodes)
        if all(height >= expected_height for height in heights):
            return min(heights)
        time.sleep(0.02)
    return min(node.host.consensus.chain.current_height for node in consensus_nodes)


def _rotate_consensus_order(
    account: AccountNodeRuntime,
    consensus_ids: tuple[str, ...],
    primary_peer_id: str,
) -> None:
    ordered = (primary_peer_id, *tuple(peer_id for peer_id in consensus_ids if peer_id != primary_peer_id))
    account.host.set_consensus_peer_ids(ordered)


def _record_summary(account: AccountNodeRuntime) -> dict[str, Any]:
    wallet = account.host.wallet
    return {
        "node_id": account.peer.node_id,
        "address": account.host.address,
        "available_balance": wallet.available_balance(),
        "total_balance": wallet.total_balance(),
        "pending_balance": wallet.pending_balance(),
        "pending_bundle_count": len(wallet.list_pending_bundles()),
        "receipt_count": len(wallet.list_receipts()),
        "checkpoint_count": len(wallet.list_checkpoints()),
        "confirmed_record_count": len(
            [
                record
                for record in wallet.list_records(LocalValueStatus.VERIFIED_SPENDABLE)
                if record.witness_v2.confirmed_bundle_chain
            ]
        ),
    }


def _maybe_create_checkpoints(
    accounts: tuple[AccountNodeRuntime, ...],
    *,
    created_record_ids: set[tuple[str, str]],
) -> int:
    created = 0
    for account in accounts:
        for record in account.host.wallet.list_records(LocalValueStatus.VERIFIED_SPENDABLE):
            if not record.witness_v2.confirmed_bundle_chain:
                continue
            key = (account.host.address, record.record_id)
            if key in created_record_ids:
                continue
            account.host.wallet.create_exact_checkpoint(record.record_id)
            created_record_ids.add(key)
            created += 1
    return created


def run_scenario(
    *,
    root_dir: str,
    chain_id: int,
    consensus_count: int,
    account_count: int,
    tx_count: int,
    genesis_amount: int,
    min_amount: int,
    max_amount: int,
    checkpoint_every: int,
    seed: int,
    network_timeout_sec: float,
    reset_root: bool,
) -> dict[str, Any]:
    if consensus_count < 3:
        raise ValueError("consensus_count must be at least 3 for mvp")
    if account_count < 2:
        raise ValueError("account_count must be at least 2")
    if tx_count < 0:
        raise ValueError("tx_count must be non-negative")
    if genesis_amount <= 0:
        raise ValueError("genesis_amount must be positive")
    if min_amount <= 0:
        raise ValueError("min_amount must be positive")
    if max_amount < min_amount:
        raise ValueError("max_amount must be >= min_amount")

    root = Path(root_dir)
    if reset_root and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    consensus_peers = tuple(
        PeerInfo(node_id=f"consensus-{index}", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}")
        for index in range(consensus_count)
    )

    account_identities: list[tuple[bytes, bytes, str]] = []
    for _ in range(account_count):
        private_key_pem, public_key_pem = generate_secp256k1_keypair()
        account_identities.append(
            (
                private_key_pem,
                public_key_pem,
                address_from_public_key_pem(public_key_pem),
            )
        )
    account_peers = tuple(
        PeerInfo(
            node_id=f"account-{index:02d}",
            role="account",
            endpoint=f"127.0.0.1:{_reserve_port()}",
            metadata={"address": identity[2]},
        )
        for index, identity in enumerate(account_identities)
    )
    all_peers = (*consensus_peers, *account_peers)
    peer_map = {peer.node_id: peer for peer in all_peers}
    consensus_ids = tuple(peer.node_id for peer in consensus_peers)

    def _network_for(peer_id: str) -> TransportPeerNetwork:
        endpoint = peer_map[peer_id].endpoint
        _, port_s = endpoint.rsplit(":", 1)
        return TransportPeerNetwork(
            TCPNetworkTransport("127.0.0.1", int(port_s)),
            all_peers,
            timeout_sec=network_timeout_sec,
        )

    consensus_nodes: list[ConsensusNodeRuntime] = []
    account_nodes: list[AccountNodeRuntime] = []
    for peer in consensus_peers:
        network = _network_for(peer.node_id)
        host = V2ConsensusHost(
            node_id=peer.node_id,
            endpoint=peer.endpoint,
            store_path=str(root / f"{peer.node_id}.sqlite3"),
            network=network,
            chain_id=chain_id,
            consensus_mode="mvp",
            consensus_validator_ids=consensus_ids,
            auto_run_mvp_consensus=True,
        )
        consensus_nodes.append(ConsensusNodeRuntime(peer=peer, network=network, host=host))
    for index, peer in enumerate(account_peers):
        network = _network_for(peer.node_id)
        private_key_pem, public_key_pem, address = account_identities[index]
        initial_primary = consensus_ids[index % len(consensus_ids)]
        host = V2AccountHost(
            node_id=peer.node_id,
            endpoint=peer.endpoint,
            wallet_db_path=str(root / f"{peer.node_id}.sqlite3"),
            chain_id=chain_id,
            network=network,
            consensus_peer_id=initial_primary,
            consensus_peer_ids=consensus_ids,
            address=address,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            state_path=str(root / f"{peer.node_id}-network-state.json"),
        )
        account_nodes.append(AccountNodeRuntime(peer=peer, network=network, host=host))

    allocations: dict[str, ValueRange] = {}
    cursor = 0
    for account in account_nodes:
        allocations[account.host.address] = ValueRange(cursor, cursor + genesis_amount - 1)
        cursor += genesis_amount

    confirmed_txs: list[dict[str, Any]] = []
    failed_txs: list[dict[str, Any]] = []
    created_checkpoint_record_ids: set[tuple[str, str]] = set()
    started_at = time.time()

    try:
        for node in (*consensus_nodes, *account_nodes):
            node.network.start()

        for consensus in consensus_nodes:
            for owner_addr, value in allocations.items():
                consensus.host.register_genesis_value(owner_addr, value)
        for account in account_nodes:
            account.host.register_genesis_value(allocations[account.host.address])

        for tx_index in range(1, tx_count + 1):
            spendable_accounts = [
                account
                for account in account_nodes
                if account.host.wallet.available_balance() >= min_amount
            ]
            if not spendable_accounts:
                failed_txs.append(
                    {
                        "tx_index": tx_index,
                        "status": "stopped",
                        "error": "no_spendable_sender_remaining",
                    }
                )
                break
            sender = rng.choice(spendable_accounts)
            recipient_candidates = [account for account in account_nodes if account.peer.node_id != sender.peer.node_id]
            recipient = rng.choice(recipient_candidates)
            available = sender.host.wallet.available_balance()
            amount = rng.randint(min_amount, min(max_amount, available))
            selected_primary = rng.choice(consensus_ids)
            _rotate_consensus_order(sender, consensus_ids, selected_primary)

            expected_seq = sender.host.wallet.next_sequence()
            tx_started_at = time.time()
            try:
                payment = sender.host.submit_payment(
                    recipient.peer.node_id,
                    amount=amount,
                    tx_time=tx_index,
                    anti_spam_nonce=rng.randrange(1, 1 << 31),
                )
            except Exception as exc:
                failed_txs.append(
                    {
                        "tx_index": tx_index,
                        "status": "failed_submit",
                        "error": str(exc),
                        "sender_node_id": sender.peer.node_id,
                        "recipient_node_id": recipient.peer.node_id,
                        "selected_primary": selected_primary,
                        "amount": amount,
                    }
                )
                continue

            _wait_for_consensus_height(tuple(consensus_nodes), tx_index, timeout_sec=max(3.0, network_timeout_sec))
            for account in account_nodes:
                account.host.recover_network_state()

            receipt = next((item for item in sender.host.wallet.list_receipts() if item.seq == expected_seq), None)
            if receipt is None:
                failed_txs.append(
                    {
                        "tx_index": tx_index,
                        "status": "missing_receipt",
                        "sender_node_id": sender.peer.node_id,
                        "recipient_node_id": recipient.peer.node_id,
                        "selected_primary": selected_primary,
                        "amount": amount,
                        "tx_hash": payment.tx_hash_hex,
                        "submit_hash": payment.submit_hash_hex,
                    }
                )
                continue

            created_checkpoints = 0
            if checkpoint_every > 0 and tx_index % checkpoint_every == 0:
                created_checkpoints = _maybe_create_checkpoints(
                    tuple(account_nodes),
                    created_record_ids=created_checkpoint_record_ids,
                )

            confirmed_txs.append(
                {
                    "tx_index": tx_index,
                    "status": "confirmed",
                    "sender_node_id": sender.peer.node_id,
                    "recipient_node_id": recipient.peer.node_id,
                    "sender_addr": sender.host.address,
                    "recipient_addr": recipient.host.address,
                    "selected_primary": selected_primary,
                    "amount": amount,
                    "tx_hash": payment.tx_hash_hex,
                    "submit_hash": payment.submit_hash_hex,
                    "receipt_height": receipt.header_lite.height,
                    "receipt_block_hash": receipt.header_lite.block_hash.hex(),
                    "elapsed_ms": int((time.time() - tx_started_at) * 1000),
                    "created_checkpoints": created_checkpoints,
                }
            )

        duration_sec = time.time() - started_at
        total_supply = sum(account.host.wallet.total_balance() for account in account_nodes)
        return {
            "mode": "v2_tcp_scale_scenario",
            "root_dir": str(root),
            "chain_id": chain_id,
            "seed": seed,
            "consensus_count": consensus_count,
            "account_count": account_count,
            "tx_requested": tx_count,
            "tx_confirmed": len(confirmed_txs),
            "tx_failed": len(failed_txs),
            "duration_sec": round(duration_sec, 3),
            "throughput_tps": round((len(confirmed_txs) / duration_sec), 3) if duration_sec > 0 else None,
            "total_supply": total_supply,
            "consensus_heights": {
                node.peer.node_id: node.host.consensus.chain.current_height
                for node in consensus_nodes
            },
            "accounts": {
                account.peer.node_id: _record_summary(account)
                for account in account_nodes
            },
            "transactions": confirmed_txs,
            "failures": failed_txs,
        }
    finally:
        for node in reversed(account_nodes):
            node.network.stop()
            node.host.close()
        for node in reversed(consensus_nodes):
            node.network.stop()
            node.host.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a configurable EZchain V2 TCP local scale scenario")
    parser.add_argument("--root-dir", default="", help="Output directory for sqlite state; defaults to a temporary directory")
    parser.add_argument("--chain-id", type=int, default=821, help="V2 chain id")
    parser.add_argument("--consensus-count", type=int, default=4, help="Number of consensus nodes to launch")
    parser.add_argument("--account-count", type=int, default=8, help="Number of account nodes to launch")
    parser.add_argument("--tx-count", type=int, default=25, help="Number of random transactions to execute")
    parser.add_argument("--genesis-amount", type=int, default=1000, help="Initial balance per account")
    parser.add_argument("--min-amount", type=int, default=1, help="Minimum transfer amount")
    parser.add_argument("--max-amount", type=int, default=50, help="Maximum transfer amount")
    parser.add_argument("--checkpoint-every", type=int, default=0, help="Create checkpoints after every N confirmed tx; 0 disables")
    parser.add_argument("--seed", type=int, default=821, help="Random seed")
    parser.add_argument("--network-timeout-sec", type=float, default=10.0, help="TCP transport timeout")
    parser.add_argument("--reset-root", action="store_true", help="Delete root-dir before running")
    parser.add_argument("--out-json", default="", help="Optional path to write the JSON summary")
    args = parser.parse_args()

    root_dir = args.root_dir.strip() or tempfile.mkdtemp(prefix="ezchain-v2-scale-")
    summary = run_scenario(
        root_dir=root_dir,
        chain_id=int(args.chain_id),
        consensus_count=int(args.consensus_count),
        account_count=int(args.account_count),
        tx_count=int(args.tx_count),
        genesis_amount=int(args.genesis_amount),
        min_amount=int(args.min_amount),
        max_amount=int(args.max_amount),
        checkpoint_every=int(args.checkpoint_every),
        seed=int(args.seed),
        network_timeout_sec=float(args.network_timeout_sec),
        reset_root=bool(args.reset_root),
    )
    payload = json.dumps(summary, indent=2)
    if args.out_json:
        output_path = Path(args.out_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
