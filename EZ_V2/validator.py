from __future__ import annotations

from dataclasses import dataclass, field

from .claim_set import claim_range_set_from_sidecar, claim_range_set_intersects, claim_range_set_hash
from .chain import compute_addr_key, confirmed_ref, hash_account_leaf, reconstructed_leaf
from .smt import verify_proof
from .types import (
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    PriorWitnessLink,
    TransferPackage,
    WitnessV2,
)
from .values import ValueRange


@dataclass(slots=True)
class ValidationContext:
    genesis_allocations: dict[str, tuple[ValueRange, ...]] = field(default_factory=dict)
    trusted_checkpoints: tuple[Checkpoint, ...] = ()

    def is_trusted_checkpoint(self, checkpoint: Checkpoint, value: ValueRange, owner_addr: str) -> bool:
        return any(
            item == checkpoint and item.matches(value, owner_addr)
            for item in self.trusted_checkpoints
        )

    def matches_genesis_anchor(self, anchor: GenesisAnchor, value: ValueRange, owner_addr: str) -> bool:
        if anchor.first_owner_addr != owner_addr:
            return False
        expected_ranges = self.genesis_allocations.get(owner_addr, ())
        anchor_range = ValueRange(anchor.value_begin, anchor.value_end)
        if not anchor_range.contains_range(value):
            return False
        return any(allocation.contains_range(value) and allocation == anchor_range for allocation in expected_ranges)


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    error: str | None = None
    accepted_witness: WitnessV2 | None = None


class V2TransferValidator:
    def __init__(self, context: ValidationContext):
        self.context = context

    @staticmethod
    def _tx_contains_target_value(target_tx, target_value: ValueRange) -> bool:
        return any(tx_value.contains_range(target_value) for tx_value in target_tx.value_list)

    def validate_transfer_package(self, package: TransferPackage, recipient_addr: str | None = None) -> ValidationResult:
        recipient = recipient_addr or package.target_tx.recipient_addr
        error = self._validate_transfer(
            target_tx=package.target_tx,
            target_value=package.target_value,
            witness=package.witness_v2,
            expected_recipient=recipient,
        )
        if error:
            return ValidationResult(ok=False, error=error)
        accepted_witness = WitnessV2(
            value=package.target_value,
            current_owner_addr=recipient,
            confirmed_bundle_chain=(),
            anchor=PriorWitnessLink(
                acquire_tx=package.target_tx,
                prior_witness=package.witness_v2,
            ),
        )
        return ValidationResult(ok=True, accepted_witness=accepted_witness)

    def _validate_transfer(
        self,
        target_tx,
        target_value: ValueRange,
        witness: WitnessV2,
        expected_recipient: str,
    ) -> str | None:
        if witness.current_owner_addr != target_tx.sender_addr:
            return "witness owner does not match target tx sender"
        if target_tx.recipient_addr != expected_recipient:
            return "target recipient mismatch"
        if not self._tx_contains_target_value(target_tx, target_value):
            return "target value is not covered by target tx"
        if not witness.confirmed_bundle_chain:
            return "current sender witness segment cannot be empty"

        latest_unit = witness.confirmed_bundle_chain[0]
        latest_matches = [tx for tx in latest_unit.bundle_sidecar.tx_list if tx == target_tx]
        if len(latest_matches) != 1:
            return "target tx must exist exactly once in latest bundle"

        continuity_error = self._validate_current_sender_chain(target_value, witness.confirmed_bundle_chain, target_tx)
        if continuity_error:
            return continuity_error

        return self._validate_anchor(target_value, witness)

    def _validate_current_sender_chain(
        self,
        target_value: ValueRange,
        chain: tuple[ConfirmedBundleUnit, ...],
        target_tx,
    ) -> str | None:
        for index, unit in enumerate(chain):
            if unit.receipt.claim_set_hash is not None:
                expected_claim_set_hash = claim_range_set_hash(claim_range_set_from_sidecar(unit.bundle_sidecar))
                if unit.receipt.claim_set_hash != expected_claim_set_hash:
                    return "claim_set_hash does not match bundle sidecar"
            leaf_hash = hash_account_leaf(reconstructed_leaf(unit))
            addr_key = compute_addr_key(unit.bundle_sidecar.sender_addr)
            proof = unit.receipt.account_state_proof
            if proof is None:
                return "current sender receipt missing single proof"
            if not verify_proof(
                unit.receipt.header_lite.state_root,
                addr_key,
                leaf_hash,
                proof,
            ):
                return "account state proof does not verify"
            if index + 1 < len(chain):
                if unit.receipt.prev_ref != confirmed_ref(chain[index + 1]):
                    return "prev_ref chain is discontinuous"
            if index > 0:
                claim_ranges = claim_range_set_from_sidecar(unit.bundle_sidecar)
                if not claim_range_set_intersects(claim_ranges, target_value):
                    continue
                return "value conflict detected inside current sender history"
            for tx in unit.bundle_sidecar.tx_list:
                for tx_value in tx.value_list:
                    if not tx_value.intersects(target_value):
                        continue
                    is_latest = index == 0
                    if is_latest and tx == target_tx and tx_value.contains_range(target_value):
                        continue
                    return "value conflict detected inside current sender history"
        return None

    def _validate_anchor(self, target_value: ValueRange, witness: WitnessV2) -> str | None:
        anchor = witness.anchor
        if isinstance(anchor, GenesisAnchor):
            if not self.context.matches_genesis_anchor(anchor, target_value, witness.current_owner_addr):
                return "genesis anchor mismatch"
            return None
        if isinstance(anchor, CheckpointAnchor):
            if not self.context.is_trusted_checkpoint(anchor.checkpoint, target_value, witness.current_owner_addr):
                return "checkpoint anchor is not trusted"
            return None
        if isinstance(anchor, PriorWitnessLink):
            recursive_error = self._validate_transfer(
                target_tx=anchor.acquire_tx,
                target_value=target_value,
                witness=anchor.prior_witness,
                expected_recipient=witness.current_owner_addr,
            )
            if recursive_error:
                return recursive_error
            acquire_height = anchor.prior_witness.confirmed_bundle_chain[0].receipt.header_lite.height
            if witness.confirmed_bundle_chain:
                earliest_current_height = witness.confirmed_bundle_chain[-1].receipt.header_lite.height
                if earliest_current_height <= acquire_height:
                    return "current sender history starts before acquisition boundary"
            return None
        return "unsupported witness anchor"
