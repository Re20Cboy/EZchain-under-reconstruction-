from __future__ import annotations

import time
import uuid
from math import inf
from dataclasses import replace

from .chain import (
    compute_addr_key,
    compute_bundle_hash,
    confirmed_ref,
    hash_account_leaf,
    reconstructed_leaf,
    sign_bundle_envelope,
)
from .crypto import address_from_public_key_pem
from .smt import verify_proof
from .storage import LocalWalletDB
from .transport import transfer_package_hash
from .types import (
    BlockV2,
    BundleEnvelope,
    BundleSidecar,
    BundleSubmission,
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PendingBundleContext,
    PriorWitnessLink,
    TransferPackage,
    WitnessV2,
)
from .validator import V2TransferValidator
from .values import LocalValueRecord, LocalValueStatus, ValueRange


def _append_confirmed_unit(witness: WitnessV2, value: ValueRange, unit: ConfirmedBundleUnit) -> WitnessV2:
    return WitnessV2(
        value=value,
        current_owner_addr=witness.current_owner_addr,
        confirmed_bundle_chain=(unit, *witness.confirmed_bundle_chain),
        anchor=witness.anchor,
    )


def _clone_witness_for_value(witness: WitnessV2, value: ValueRange) -> WitnessV2:
    return WitnessV2(
        value=value,
        current_owner_addr=witness.current_owner_addr,
        confirmed_bundle_chain=witness.confirmed_bundle_chain,
        anchor=witness.anchor,
    )


def _partition_range(source: ValueRange, targets: tuple[ValueRange, ...]) -> list[tuple[ValueRange, bool]]:
    if not targets:
        return [(source, False)]
    ordered_targets = tuple(sorted(targets, key=lambda item: (item.begin, item.end)))
    for target in ordered_targets:
        if not source.contains_range(target):
            raise ValueError("outgoing range must be contained in source value")
    for index in range(len(ordered_targets) - 1):
        if ordered_targets[index].intersects(ordered_targets[index + 1]):
            raise ValueError("outgoing ranges cannot overlap inside one source value")
    segments: list[tuple[ValueRange, bool]] = []
    cursor = source.begin
    for target in ordered_targets:
        if cursor < target.begin:
            segments.append((ValueRange(cursor, target.begin - 1), False))
        segments.append((target, True))
        cursor = target.end + 1
    if cursor <= source.end:
        segments.append((ValueRange(cursor, source.end), False))
    return segments


def _ensure_non_overlapping_targets(targets: tuple[ValueRange, ...]) -> tuple[ValueRange, ...]:
    ordered = tuple(sorted(targets, key=lambda item: (item.begin, item.end)))
    for index in range(len(ordered) - 1):
        if ordered[index].intersects(ordered[index + 1]):
            raise ValueError("bundle contains overlapping outgoing value ranges")
    return ordered


def _iter_witness_sidecars(witness: WitnessV2):
    for unit in witness.confirmed_bundle_chain:
        yield unit.bundle_sidecar
    anchor = witness.anchor
    if isinstance(anchor, PriorWitnessLink):
        yield from _iter_witness_sidecars(anchor.prior_witness)


class WalletAccountV2:
    def __init__(self, address: str, genesis_block_hash: bytes, db_path: str = ":memory:"):
        self.address = address
        self.genesis_block_hash = genesis_block_hash
        self.db = LocalWalletDB(db_path)
        self.records: list[LocalValueRecord] = []
        self.checkpoints: list[Checkpoint] = []
        self._reload_state()

    def close(self) -> None:
        self.db.close()

    def _reload_state(self) -> None:
        self.records = self.db.list_value_records(self.address)
        self.checkpoints = self.db.list_checkpoints(self.address)

    def reload_state(self) -> None:
        self._reload_state()

    def _persist_records(self, records: list[LocalValueRecord]) -> None:
        self.db.replace_value_records_and_recompute_sidecar_refs(self.address, records)
        self._reload_state()

    def observe_canonical_header(self, header: HeaderLite) -> None:
        self.db.save_canonical_header(self.address, header)

    def observe_canonical_block(self, block: BlockV2) -> None:
        self.observe_canonical_header(
            HeaderLite(
                height=block.header.height,
                block_hash=block.block_hash,
                state_root=block.header.state_root,
            )
        )

    def knows_canonical_header(self, header: HeaderLite) -> bool:
        return self.db.has_canonical_header(self.address, header)

    def balance_breakdown(self) -> dict[LocalValueStatus, int]:
        totals = {status: 0 for status in LocalValueStatus}
        for record in self.records:
            totals[record.local_status] += record.value.size
        return totals

    def get_balance(self, status: LocalValueStatus | None = None) -> int:
        breakdown = self.balance_breakdown()
        if status is not None:
            return breakdown.get(status, 0)
        return sum(
            amount
            for value_status, amount in breakdown.items()
            if value_status != LocalValueStatus.ARCHIVED
        )

    def available_balance(self) -> int:
        return self.get_balance(LocalValueStatus.VERIFIED_SPENDABLE)

    def pending_balance(self) -> int:
        return sum(
            self.get_balance(status)
            for status in (
                LocalValueStatus.PENDING_BUNDLE,
                LocalValueStatus.PENDING_CONFIRMATION,
                LocalValueStatus.RECEIPT_PENDING,
                LocalValueStatus.RECEIPT_MISSING,
                LocalValueStatus.LOCKED_FOR_VERIFICATION,
            )
        )

    def total_balance(self) -> int:
        return self.get_balance()

    def next_sequence(self) -> int:
        return self.db.next_sequence(self.address)

    def _sorted_spendable_records(self) -> list[LocalValueRecord]:
        return sorted(
            (
                record
                for record in self.records
                if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
            ),
            key=lambda record: (
                len(record.witness_v2.confirmed_bundle_chain),
                -record.acquisition_height,
                record.value.size,
                record.value.begin,
            ),
        )

    def _has_exact_local_checkpoint(self, record: LocalValueRecord) -> bool:
        return any(checkpoint.matches(record.value, self.address) for checkpoint in self.checkpoints)

    def _witness_total_units(self, witness: WitnessV2) -> int:
        total = len(witness.confirmed_bundle_chain)
        anchor = witness.anchor
        if isinstance(anchor, PriorWitnessLink):
            return total + self._witness_total_units(anchor.prior_witness)
        return total

    def _witness_units_to_checkpoint(self, witness: WitnessV2) -> int:
        total = len(witness.confirmed_bundle_chain)
        anchor = witness.anchor
        if isinstance(anchor, CheckpointAnchor):
            return total
        if isinstance(anchor, PriorWitnessLink):
            child = self._witness_units_to_checkpoint(anchor.prior_witness)
            if child == inf:
                return inf
            return total + child
        return inf

    def _checkpoint_matches_witness(self, checkpoint: Checkpoint, witness: WitnessV2) -> bool:
        if not checkpoint.matches(witness.value, witness.current_owner_addr):
            return False
        return any(
            unit.receipt.header_lite.height == checkpoint.checkpoint_height
            and unit.receipt.header_lite.block_hash == checkpoint.checkpoint_block_hash
            and compute_bundle_hash(unit.bundle_sidecar) == checkpoint.checkpoint_bundle_hash
            for unit in witness.confirmed_bundle_chain
        )

    def _trim_witness_to_known_checkpoint(
        self,
        witness: WitnessV2,
        trusted_checkpoints: tuple[Checkpoint, ...],
    ) -> WitnessV2:
        for checkpoint in trusted_checkpoints:
            if self._checkpoint_matches_witness(checkpoint, witness):
                return replace(witness, anchor=CheckpointAnchor(checkpoint=checkpoint))
        anchor = witness.anchor
        if not isinstance(anchor, PriorWitnessLink):
            return witness
        trimmed_prior = self._trim_witness_to_known_checkpoint(anchor.prior_witness, trusted_checkpoints)
        if trimmed_prior == anchor.prior_witness:
            return witness
        return replace(
            witness,
            anchor=PriorWitnessLink(
                acquire_tx=anchor.acquire_tx,
                prior_witness=trimmed_prior,
            ),
        )

    def _checkpoint_from_witness(self, witness: WitnessV2) -> Checkpoint | None:
        if not witness.confirmed_bundle_chain:
            return None
        latest = witness.confirmed_bundle_chain[0]
        return Checkpoint(
            value_begin=witness.value.begin,
            value_end=witness.value.end,
            owner_addr=witness.current_owner_addr,
            checkpoint_height=latest.receipt.header_lite.height,
            checkpoint_block_hash=latest.receipt.header_lite.block_hash,
            checkpoint_bundle_hash=compute_bundle_hash(latest.bundle_sidecar),
        )

    def _trim_witness_for_recipient(
        self,
        witness: WitnessV2,
        recipient_addr: str,
        target_value: ValueRange,
    ) -> WitnessV2:
        if witness.current_owner_addr == recipient_addr and witness.value == target_value:
            checkpoint = self._checkpoint_from_witness(witness)
            if checkpoint is not None:
                return replace(witness, anchor=CheckpointAnchor(checkpoint=checkpoint))
        anchor = witness.anchor
        if not isinstance(anchor, PriorWitnessLink):
            return witness
        trimmed_prior = self._trim_witness_for_recipient(anchor.prior_witness, recipient_addr, target_value)
        if trimmed_prior == anchor.prior_witness:
            return witness
        return replace(
            witness,
            anchor=PriorWitnessLink(
                acquire_tx=anchor.acquire_tx,
                prior_witness=trimmed_prior,
            ),
        )

    def has_local_checkpoint(self, checkpoint: Checkpoint) -> bool:
        return self._local_witness_for_checkpoint(checkpoint) is not None

    def _local_witness_for_checkpoint(self, checkpoint: Checkpoint) -> WitnessV2 | None:
        if checkpoint.owner_addr != self.address:
            return None
        if checkpoint in self.checkpoints:
            target_value = ValueRange(checkpoint.value_begin, checkpoint.value_end)
            for record in self.records:
                if record.value == target_value and self._checkpoint_matches_witness(checkpoint, record.witness_v2):
                    return record.witness_v2
            return None
        target_value = ValueRange(checkpoint.value_begin, checkpoint.value_end)
        for record in self.records:
            if record.value == target_value and self._checkpoint_matches_witness(checkpoint, record.witness_v2):
                return record.witness_v2
        return None

    def trusted_checkpoints_for_witness(self, witness: WitnessV2) -> tuple[Checkpoint, ...]:
        matched: list[Checkpoint] = []
        seen: set[Checkpoint] = set()

        def _walk(node: WitnessV2) -> None:
            anchor = node.anchor
            if isinstance(anchor, CheckpointAnchor):
                checkpoint = anchor.checkpoint
                if checkpoint not in seen and self.has_local_checkpoint(checkpoint):
                    matched.append(checkpoint)
                    seen.add(checkpoint)
                return
            if isinstance(anchor, PriorWitnessLink):
                _walk(anchor.prior_witness)

        _walk(witness)
        return tuple(matched)

    def _rehydrate_local_checkpoint_anchors(self, witness: WitnessV2) -> WitnessV2:
        anchor = witness.anchor
        if isinstance(anchor, CheckpointAnchor):
            return self._local_witness_for_checkpoint(anchor.checkpoint) or witness
        if not isinstance(anchor, PriorWitnessLink):
            return witness
        rehydrated_prior = self._rehydrate_local_checkpoint_anchors(anchor.prior_witness)
        if rehydrated_prior == anchor.prior_witness:
            return witness
        return replace(
            witness,
            anchor=PriorWitnessLink(
                acquire_tx=anchor.acquire_tx,
                prior_witness=rehydrated_prior,
            ),
        )

    def _selection_plan_cost(
        self,
        spendable_records: tuple[LocalValueRecord, ...],
        plan: tuple[tuple[int, int], ...],
    ) -> tuple:
        split_count = 0
        effective_anchor_cost = 0
        total_witness_units = 0
        checkpoint_miss_count = 0
        freshness_penalty = 0
        range_order: list[tuple[int, int]] = []
        for record_index, take_size in plan:
            record = spendable_records[record_index]
            if take_size < record.value.size:
                split_count += 1
            has_checkpoint = self._has_exact_local_checkpoint(record)
            checkpoint_miss_count += 0 if has_checkpoint else 1
            distance_to_checkpoint = self._witness_units_to_checkpoint(record.witness_v2)
            effective_anchor_cost += 0 if has_checkpoint else distance_to_checkpoint
            total_witness_units += self._witness_total_units(record.witness_v2)
            freshness_penalty -= record.acquisition_height
            range_order.append((record.value.begin, take_size))
        return (
            len(plan),
            split_count,
            checkpoint_miss_count,
            effective_anchor_cost,
            total_witness_units,
            freshness_penalty,
            tuple(sorted(range_order)),
        )

    def select_payment_ranges(self, amount: int) -> tuple[ValueRange, ...]:
        if amount <= 0:
            raise ValueError("amount must be positive")
        spendable_records = tuple(self._sorted_spendable_records())
        exact_plans: dict[int, tuple[tuple[int, int], ...]] = {0: ()}
        best_plan: tuple[tuple[int, int], ...] | None = None

        for record_index, record in enumerate(spendable_records):
            record_size = record.value.size
            prior_plans = dict(exact_plans)

            for subtotal, plan in prior_plans.items():
                remaining = amount - subtotal
                if 0 < remaining < record_size:
                    candidate = plan + ((record_index, remaining),)
                    if (
                        best_plan is None
                        or self._selection_plan_cost(spendable_records, candidate)
                        < self._selection_plan_cost(spendable_records, best_plan)
                    ):
                        best_plan = candidate

            for subtotal, plan in prior_plans.items():
                new_total = subtotal + record_size
                if new_total > amount:
                    continue
                candidate = plan + ((record_index, record_size),)
                existing = exact_plans.get(new_total)
                if (
                    existing is None
                    or self._selection_plan_cost(spendable_records, candidate)
                    < self._selection_plan_cost(spendable_records, existing)
                ):
                    exact_plans[new_total] = candidate

            exact_match = exact_plans.get(amount)
            if (
                exact_match is not None
                and (
                    best_plan is None
                    or self._selection_plan_cost(spendable_records, exact_match)
                    < self._selection_plan_cost(spendable_records, best_plan)
                )
            ):
                best_plan = exact_match

        if best_plan is None:
            raise ValueError("insufficient_balance")
        selected = tuple(
            ValueRange(
                spendable_records[record_index].value.begin,
                spendable_records[record_index].value.begin + take_size - 1,
            )
            for record_index, take_size in best_plan
        )
        return tuple(sorted(selected, key=lambda item: (item.begin, item.end)))

    def _apply_confirmed_unit_to_records(
        self,
        confirmed_unit: ConfirmedBundleUnit,
        outgoing_values: tuple[ValueRange, ...] = (),
        pending_record_ids: tuple[str, ...] = (),
        outgoing_record_ids: tuple[str, ...] = (),
    ) -> list[LocalValueRecord]:
        outgoing_values = tuple(sorted(outgoing_values, key=lambda item: (item.begin, item.end)))
        pending_ids = set(pending_record_ids)
        outgoing_ids = set(outgoing_record_ids)
        confirmed_height = confirmed_unit.receipt.header_lite.height
        updated_records: list[LocalValueRecord] = []
        for record in self.records:
            if record.local_status == LocalValueStatus.ARCHIVED:
                updated_records.append(record)
                continue
            if record.record_id in pending_ids:
                new_status = (
                    LocalValueStatus.ARCHIVED
                    if record.record_id in outgoing_ids
                    else LocalValueStatus.VERIFIED_SPENDABLE
                )
                updated_records.append(
                    replace(
                        record,
                        witness_v2=_append_confirmed_unit(record.witness_v2, record.value, confirmed_unit),
                        local_status=new_status,
                    )
                )
                continue
            if record.local_status == LocalValueStatus.PENDING_BUNDLE:
                updated_records.append(record)
                continue
            if record.acquisition_height >= confirmed_height:
                updated_records.append(record)
                continue
            contained_targets = tuple(target for target in outgoing_values if record.value.contains_range(target))
            if not contained_targets:
                updated_records.append(
                    replace(
                        record,
                        witness_v2=_append_confirmed_unit(record.witness_v2, record.value, confirmed_unit),
                        local_status=LocalValueStatus.VERIFIED_SPENDABLE,
                    )
                )
                continue
            appended_template = _append_confirmed_unit(record.witness_v2, record.value, confirmed_unit)
            for segment, is_outgoing in _partition_range(record.value, contained_targets):
                updated_records.append(
                    LocalValueRecord(
                        record_id=uuid.uuid4().hex,
                        value=segment,
                        witness_v2=WitnessV2(
                            value=segment,
                            current_owner_addr=self.address,
                            confirmed_bundle_chain=appended_template.confirmed_bundle_chain,
                            anchor=appended_template.anchor,
                        ),
                        local_status=LocalValueStatus.ARCHIVED if is_outgoing else LocalValueStatus.VERIFIED_SPENDABLE,
                        acquisition_height=record.acquisition_height,
                    )
                )
        return updated_records

    def list_records(self, status: LocalValueStatus | None = None) -> list[LocalValueRecord]:
        if status is None:
            return list(self.records)
        return [record for record in self.records if record.local_status == status]

    def list_pending_bundles(self) -> list[PendingBundleContext]:
        return self.db.list_pending_bundles(self.address)

    def list_receipts(self):
        return self.db.list_receipts(self.address)

    def list_checkpoints(self) -> list[Checkpoint]:
        return list(self.checkpoints)

    def add_genesis_value(self, value: ValueRange) -> LocalValueRecord:
        witness = WitnessV2(
            value=value,
            current_owner_addr=self.address,
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=self.genesis_block_hash,
                first_owner_addr=self.address,
                value_begin=value.begin,
                value_end=value.end,
            ),
        )
        record = LocalValueRecord(
            record_id=uuid.uuid4().hex,
            value=value,
            witness_v2=witness,
            local_status=LocalValueStatus.VERIFIED_SPENDABLE,
            acquisition_height=0,
        )
        self._persist_records(self.records + [record])
        return next(item for item in self.records if item.record_id == record.record_id)

    def has_genesis_value(self, value: ValueRange) -> bool:
        for record in self.records:
            anchor = getattr(record.witness_v2, "anchor", None)
            if not isinstance(anchor, GenesisAnchor):
                continue
            if anchor.first_owner_addr != self.address:
                continue
            anchor_range = ValueRange(anchor.value_begin, anchor.value_end)
            if anchor_range == value:
                return True
        return False

    def _assign_targets_to_records(self, targets: tuple[ValueRange, ...]) -> dict[str, list[ValueRange]]:
        assignments: dict[str, list[ValueRange]] = {}
        eligible = [
            record
            for record in self.records
            if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
        ]
        for target in targets:
            selected = None
            for record in eligible:
                assigned = assignments.get(record.record_id, [])
                if not record.value.contains_range(target):
                    continue
                if any(existing.intersects(target) for existing in assigned):
                    continue
                selected = record
                break
            if selected is None:
                raise ValueError(f"no spendable record covers target range {target}")
            assignments.setdefault(selected.record_id, []).append(target)
        return assignments

    def build_bundle(
        self,
        tx_list: tuple[OffChainTx, ...],
        private_key_pem: bytes,
        public_key_pem: bytes,
        chain_id: int,
        seq: int,
        expiry_height: int,
        fee: int,
        anti_spam_nonce: int,
        created_at: int | None = None,
    ) -> tuple[BundleSubmission, PendingBundleContext]:
        sender_addr = address_from_public_key_pem(public_key_pem)
        if sender_addr != self.address:
            raise ValueError("public key does not match wallet address")
        if self.list_pending_bundles():
            raise ValueError("wallet already has a pending bundle")
        if not tx_list:
            raise ValueError("tx_list cannot be empty")

        outgoing_values = _ensure_non_overlapping_targets(
            tuple(
                value
                for tx in tx_list
                for value in tx.value_list
            )
        )
        assignments = self._assign_targets_to_records(outgoing_values)

        updated_records: list[LocalValueRecord] = []
        pending_record_ids: list[str] = []
        outgoing_record_ids: list[str] = []
        for record in self.records:
            assigned_targets = tuple(sorted(assignments.get(record.record_id, []), key=lambda item: (item.begin, item.end)))
            if not assigned_targets:
                updated_records.append(record)
                continue
            for segment, is_outgoing in _partition_range(record.value, assigned_targets):
                new_record_id = uuid.uuid4().hex
                pending_record_ids.append(new_record_id)
                if is_outgoing:
                    outgoing_record_ids.append(new_record_id)
                updated_records.append(
                    LocalValueRecord(
                        record_id=new_record_id,
                        value=segment,
                        witness_v2=_clone_witness_for_value(record.witness_v2, segment),
                        local_status=LocalValueStatus.PENDING_BUNDLE,
                        acquisition_height=record.acquisition_height,
                    )
                )

        sidecar = BundleSidecar(sender_addr=self.address, tx_list=tx_list)
        envelope = BundleEnvelope(
            version=2,
            chain_id=chain_id,
            seq=seq,
            expiry_height=expiry_height,
            fee=fee,
            anti_spam_nonce=anti_spam_nonce,
            bundle_hash=compute_bundle_hash(sidecar),
        )
        envelope = sign_bundle_envelope(envelope, private_key_pem)
        submission = BundleSubmission(
            envelope=envelope,
            sidecar=sidecar,
            sender_public_key_pem=public_key_pem,
        )
        context = PendingBundleContext(
            sender_addr=self.address,
            bundle_hash=envelope.bundle_hash,
            seq=seq,
            envelope=envelope,
            sidecar=sidecar,
            sender_public_key_pem=public_key_pem,
            pending_record_ids=tuple(pending_record_ids),
            outgoing_record_ids=tuple(outgoing_record_ids),
            outgoing_values=outgoing_values,
            created_at=created_at if created_at is not None else int(time.time()),
        )
        self.db.save_sidecar(sidecar)
        self.db.save_pending_bundle(context)
        self._persist_records(updated_records)
        return submission, context

    def build_payment_bundle(
        self,
        recipient_addr: str,
        amount: int,
        private_key_pem: bytes,
        public_key_pem: bytes,
        chain_id: int,
        expiry_height: int,
        fee: int = 0,
        anti_spam_nonce: int | None = None,
        created_at: int | None = None,
        tx_time: int | None = None,
        seq: int | None = None,
        extra_data: bytes = b"",
    ) -> tuple[BundleSubmission, PendingBundleContext, OffChainTx]:
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self.list_pending_bundles():
            raise ValueError("wallet already has a pending bundle")
        now = int(time.time()) if tx_time is None else tx_time
        payment_values = self.select_payment_ranges(amount)
        tx = OffChainTx(
            sender_addr=self.address,
            recipient_addr=recipient_addr,
            value_list=payment_values,
            tx_local_index=0,
            tx_time=now,
            extra_data=extra_data,
        )
        submission, context = self.build_bundle(
            tx_list=(tx,),
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            chain_id=chain_id,
            seq=self.next_sequence() if seq is None else seq,
            expiry_height=expiry_height,
            fee=fee,
            anti_spam_nonce=(uuid.uuid4().int & ((1 << 63) - 1)) if anti_spam_nonce is None else anti_spam_nonce,
            created_at=now if created_at is None else created_at,
        )
        return submission, context, tx

    def on_receipt_confirmed(self, receipt) -> ConfirmedBundleUnit:
        context = self.db.get_pending_bundle(self.address, receipt.seq)
        if context is None:
            raise ValueError("no pending bundle matches receipt seq")
        if not self.knows_canonical_header(receipt.header_lite):
            raise ValueError("receipt header is not known canonical")
        confirmed_unit = ConfirmedBundleUnit(
            receipt=receipt,
            bundle_sidecar=context.sidecar,
        )
        if receipt.seq == 1:
            if receipt.prev_ref is not None:
                raise ValueError("receipt prev_ref mismatch")
        else:
            previous_unit = self.db.get_confirmed_unit(self.address, receipt.seq - 1)
            if previous_unit is None:
                raise ValueError("missing previous confirmed unit for receipt")
            if confirmed_ref(previous_unit) != receipt.prev_ref:
                raise ValueError("receipt prev_ref mismatch")
        reconstructed = reconstructed_leaf(confirmed_unit)
        if not verify_proof(
            receipt.header_lite.state_root,
            compute_addr_key(self.address),
            hash_account_leaf(reconstructed),
            receipt.account_state_proof,
        ):
            raise ValueError("receipt account state proof does not verify")
        updated_records = self._apply_confirmed_unit_to_records(
            confirmed_unit=confirmed_unit,
            pending_record_ids=context.pending_record_ids,
            outgoing_record_ids=context.outgoing_record_ids,
        )

        self.db.save_receipt(self.address, receipt, context.bundle_hash)
        self.db.save_confirmed_unit(confirmed_unit)
        self.db.delete_pending_bundle(self.address, receipt.seq)
        self._persist_records(updated_records)
        return confirmed_unit

    def mark_receipt_missing(self, seq: int) -> PendingBundleContext:
        context = self.db.get_pending_bundle(self.address, seq)
        if context is None:
            raise ValueError("no pending bundle matches seq")
        pending_ids = set(context.pending_record_ids)
        updated_records: list[LocalValueRecord] = []
        for record in self.records:
            if record.record_id in pending_ids and record.local_status == LocalValueStatus.PENDING_BUNDLE:
                updated_records.append(replace(record, local_status=LocalValueStatus.RECEIPT_MISSING))
            else:
                updated_records.append(record)
        self._persist_records(updated_records)
        return context

    def apply_sender_confirmed_unit(
        self,
        confirmed_unit: ConfirmedBundleUnit,
        outgoing_values: tuple[ValueRange, ...] = (),
    ) -> list[LocalValueRecord]:
        updated_records = self._apply_confirmed_unit_to_records(
            confirmed_unit=confirmed_unit,
            outgoing_values=outgoing_values,
        )
        self._persist_records(updated_records)
        return self.records

    def rollback_pending_bundle(self, seq: int) -> PendingBundleContext:
        context = self.db.get_pending_bundle(self.address, seq)
        if context is None:
            raise ValueError("no pending bundle matches seq")
        updated_records: list[LocalValueRecord] = []
        pending_ids = set(context.pending_record_ids)
        for record in self.records:
            if record.record_id in pending_ids:
                updated_records.append(replace(record, local_status=LocalValueStatus.VERIFIED_SPENDABLE))
            else:
                updated_records.append(record)
        self.db.delete_pending_bundle(self.address, seq)
        self._persist_records(updated_records)
        return context

    def clear_pending_bundles(self) -> int:
        pending = list(self.list_pending_bundles())
        cleared = 0
        for context in pending:
            self.rollback_pending_bundle(context.seq)
            cleared += 1
        return cleared

    def export_transfer_package(self, target_tx: OffChainTx, target_value: ValueRange) -> TransferPackage:
        for record in self.records:
            if (
                record.local_status == LocalValueStatus.ARCHIVED
                and record.value == target_value
                and record.witness_v2.current_owner_addr == self.address
            ):
                if target_tx.sender_addr != self.address:
                    raise ValueError("target tx sender does not match wallet address")
                latest_unit = record.witness_v2.confirmed_bundle_chain[0] if record.witness_v2.confirmed_bundle_chain else None
                if latest_unit is None:
                    continue
                matching_txs = [tx for tx in latest_unit.bundle_sidecar.tx_list if tx == target_tx]
                if len(matching_txs) != 1:
                    continue
                return TransferPackage(
                    target_tx=target_tx,
                    target_value=target_value,
                    witness_v2=self._trim_witness_for_recipient(
                        record.witness_v2,
                        target_tx.recipient_addr,
                        target_value,
                    ),
                )
        raise ValueError("no archived outgoing record matches target value")

    def receive_transfer(self, package: TransferPackage, validator: V2TransferValidator) -> LocalValueRecord:
        package_hash = transfer_package_hash(package)
        if self.db.has_accepted_transfer_package(self.address, package_hash):
            raise ValueError("transfer package already accepted")
        result = validator.validate_transfer_package(package, recipient_addr=self.address)
        if not result.ok or result.accepted_witness is None:
            raise ValueError(result.error or "transfer validation failed")
        accepted_witness = self._rehydrate_local_checkpoint_anchors(result.accepted_witness)
        for sidecar in _iter_witness_sidecars(package.witness_v2):
            self.db.save_sidecar(sidecar)
        acquisition_height = package.witness_v2.confirmed_bundle_chain[0].receipt.header_lite.height
        record = LocalValueRecord(
            record_id=uuid.uuid4().hex,
            value=package.target_value,
            witness_v2=accepted_witness,
            local_status=LocalValueStatus.VERIFIED_SPENDABLE,
            acquisition_height=acquisition_height,
        )
        self._persist_records(self.records + [record])
        self.db.save_accepted_transfer_package(
            self.address,
            package_hash,
            accepted_at=int(time.time()),
        )
        return next(item for item in self.records if item.record_id == record.record_id)

    def create_exact_checkpoint(self, record_id: str) -> Checkpoint:
        record = next(item for item in self.records if item.record_id == record_id)
        if not record.witness_v2.confirmed_bundle_chain:
            raise ValueError("checkpoint requires at least one confirmed unit")
        latest = record.witness_v2.confirmed_bundle_chain[0]
        checkpoint = Checkpoint(
            value_begin=record.value.begin,
            value_end=record.value.end,
            owner_addr=self.address,
            checkpoint_height=latest.receipt.header_lite.height,
            checkpoint_block_hash=latest.receipt.header_lite.block_hash,
            checkpoint_bundle_hash=compute_bundle_hash(latest.bundle_sidecar),
        )
        self.db.save_checkpoint(checkpoint)
        self._reload_state()
        return checkpoint

    def checkpoint_anchor(self, checkpoint: Checkpoint) -> CheckpointAnchor:
        return CheckpointAnchor(checkpoint=checkpoint)

    def gc_unused_sidecars(self) -> int:
        self.db.recompute_sidecar_ref_counts()
        return self.db.gc_unused_sidecars()
