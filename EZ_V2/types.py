from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from .values import ValueRange


def _require_hash32(name: str, value: bytes) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{name} must be 32 bytes")


@dataclass(frozen=True, slots=True)
class BundleRef:
    height: int
    block_hash: bytes
    bundle_hash: bytes
    seq: int

    def __post_init__(self) -> None:
        _require_hash32("block_hash", self.block_hash)
        _require_hash32("bundle_hash", self.bundle_hash)
        if self.height < 0 or self.seq <= 0:
            raise ValueError("bundle ref height/seq must be positive")


@dataclass(frozen=True, slots=True)
class OffChainTx:
    sender_addr: str
    recipient_addr: str
    value_list: Tuple[ValueRange, ...]
    tx_local_index: int
    tx_time: int
    extra_data: bytes = b""

    def __post_init__(self) -> None:
        if not self.sender_addr or not self.recipient_addr:
            raise ValueError("sender and recipient must be set")
        if self.tx_local_index < 0:
            raise ValueError("tx_local_index must be non-negative")
        if not self.value_list:
            raise ValueError("value_list cannot be empty")
        ordered = sorted(self.value_list, key=lambda item: (item.begin, item.end))
        if tuple(ordered) != self.value_list:
            raise ValueError("value_list must be sorted by begin/end")
        for index in range(len(self.value_list) - 1):
            if self.value_list[index].intersects(self.value_list[index + 1]):
                raise ValueError("value_list cannot contain overlapping ranges")


@dataclass(frozen=True, slots=True)
class BundleEnvelope:
    version: int
    chain_id: int
    seq: int
    expiry_height: int
    fee: int
    anti_spam_nonce: int
    bundle_hash: bytes
    claim_set_hash: bytes | None = None
    sig: bytes = b""

    def __post_init__(self) -> None:
        _require_hash32("bundle_hash", self.bundle_hash)
        if self.claim_set_hash is not None:
            _require_hash32("claim_set_hash", self.claim_set_hash)
        if self.version < 0 or self.chain_id < 0 or self.seq <= 0:
            raise ValueError("invalid envelope numeric field")
        if self.expiry_height < 0 or self.fee < 0 or self.anti_spam_nonce < 0:
            raise ValueError("invalid envelope numeric field")

    def signing_payload(self) -> dict:
        payload = {
            "version": self.version,
            "chain_id": self.chain_id,
            "seq": self.seq,
            "expiry_height": self.expiry_height,
            "fee": self.fee,
            "anti_spam_nonce": self.anti_spam_nonce,
            "bundle_hash": self.bundle_hash,
        }
        if self.claim_set_hash is not None:
            payload["claim_set_hash"] = self.claim_set_hash
        return payload

    def with_signature(self, signature: bytes) -> "BundleEnvelope":
        return BundleEnvelope(
            version=self.version,
            chain_id=self.chain_id,
            seq=self.seq,
            expiry_height=self.expiry_height,
            fee=self.fee,
            anti_spam_nonce=self.anti_spam_nonce,
            bundle_hash=self.bundle_hash,
            claim_set_hash=self.claim_set_hash,
            sig=signature,
        )


@dataclass(frozen=True, slots=True)
class BundleSidecar:
    sender_addr: str
    tx_list: Tuple[OffChainTx, ...]
    tx_count: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.sender_addr:
            raise ValueError("sender_addr must be set")
        if self.tx_count == 0:
            object.__setattr__(self, "tx_count", len(self.tx_list))
        if self.tx_count != len(self.tx_list):
            raise ValueError("tx_count mismatch")
        for tx in self.tx_list:
            if tx.sender_addr != self.sender_addr:
                raise ValueError("bundle sidecar sender mismatch")


@dataclass(frozen=True, slots=True)
class BundleSubmission:
    envelope: BundleEnvelope
    sidecar: BundleSidecar
    sender_public_key_pem: bytes


@dataclass(frozen=True, slots=True)
class PendingBundleContext:
    sender_addr: str
    bundle_hash: bytes
    seq: int
    envelope: BundleEnvelope
    sidecar: BundleSidecar
    sender_public_key_pem: bytes
    pending_record_ids: Tuple[str, ...]
    outgoing_record_ids: Tuple[str, ...]
    outgoing_values: Tuple[ValueRange, ...]
    created_at: int

    def __post_init__(self) -> None:
        if not self.sender_addr:
            raise ValueError("sender_addr must be set")
        _require_hash32("bundle_hash", self.bundle_hash)
        if self.seq <= 0:
            raise ValueError("seq must be positive")


@dataclass(frozen=True, slots=True)
class AccountLeaf:
    addr: str
    head_ref: BundleRef | None
    prev_ref: BundleRef | None
    claim_set_hash: bytes | None = None

    def __post_init__(self) -> None:
        if not self.addr:
            raise ValueError("addr must be set")
        if self.claim_set_hash is not None:
            _require_hash32("claim_set_hash", self.claim_set_hash)


@dataclass(frozen=True, slots=True)
class DiffEntry:
    addr_key: bytes
    new_leaf: AccountLeaf
    bundle_envelope: BundleEnvelope
    bundle_hash: bytes

    def __post_init__(self) -> None:
        _require_hash32("addr_key", self.addr_key)
        _require_hash32("bundle_hash", self.bundle_hash)


@dataclass(frozen=True, slots=True)
class SparseMerkleProof:
    siblings: Tuple[bytes, ...]
    existence: bool

    def __post_init__(self) -> None:
        for sibling in self.siblings:
            _require_hash32("sibling", sibling)


@dataclass(frozen=True, slots=True)
class ClaimRangeSet:
    ranges: Tuple[ValueRange, ...]

    def __post_init__(self) -> None:
        previous = None
        for item in self.ranges:
            if previous is not None and item.begin <= previous.end + 1:
                raise ValueError("claim ranges must be normalized and non-adjacent")
            previous = item


@dataclass(frozen=True, slots=True)
class SparseMerkleMultiProofNode:
    prefix_bits: str
    node_hash: bytes

    def __post_init__(self) -> None:
        if any(bit not in {"0", "1"} for bit in self.prefix_bits):
            raise ValueError("prefix_bits must be a binary string")
        _require_hash32("node_hash", self.node_hash)


@dataclass(frozen=True, slots=True)
class SparseMerkleMultiProof:
    depth: int
    keys: Tuple[bytes, ...]
    nodes: Tuple[SparseMerkleMultiProofNode, ...]

    def __post_init__(self) -> None:
        if self.depth <= 0:
            raise ValueError("depth must be positive")
        for key in self.keys:
            if len(key) * 8 != self.depth:
                raise ValueError("key length does not match multiproof depth")


@dataclass(frozen=True, slots=True)
class ReceiptProofBatch:
    batch_id: str
    state_root: bytes
    multi_proof: SparseMerkleMultiProof

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise ValueError("batch_id must be set")
        _require_hash32("state_root", self.state_root)


@dataclass(frozen=True, slots=True)
class ReceiptProofRef:
    batch_id: str
    key: bytes

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise ValueError("batch_id must be set")
        _require_hash32("key", self.key)


@dataclass(frozen=True, slots=True)
class HeaderLite:
    height: int
    block_hash: bytes
    state_root: bytes

    def __post_init__(self) -> None:
        if self.height < 0:
            raise ValueError("height must be non-negative")
        _require_hash32("block_hash", self.block_hash)
        _require_hash32("state_root", self.state_root)


@dataclass(frozen=True, slots=True)
class Receipt:
    header_lite: HeaderLite
    seq: int
    prev_ref: BundleRef | None
    claim_set_hash: bytes | None = None
    account_state_proof: SparseMerkleProof | None = None
    proof_batch_ref: ReceiptProofRef | None = None

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise ValueError("seq must be positive")
        if self.claim_set_hash is not None:
            _require_hash32("claim_set_hash", self.claim_set_hash)
        if (self.account_state_proof is None) == (self.proof_batch_ref is None):
            raise ValueError("receipt must carry exactly one proof form")


@dataclass(frozen=True, slots=True)
class ConfirmedBundleUnit:
    receipt: Receipt
    bundle_sidecar: BundleSidecar


@dataclass(frozen=True, slots=True)
class Checkpoint:
    value_begin: int
    value_end: int
    owner_addr: str
    checkpoint_height: int
    checkpoint_block_hash: bytes
    checkpoint_bundle_hash: bytes

    def __post_init__(self) -> None:
        if self.value_begin < 0 or self.value_end < self.value_begin:
            raise ValueError("invalid checkpoint value range")
        if not self.owner_addr:
            raise ValueError("owner_addr must be set")
        if self.checkpoint_height < 0:
            raise ValueError("checkpoint_height must be non-negative")
        _require_hash32("checkpoint_block_hash", self.checkpoint_block_hash)
        _require_hash32("checkpoint_bundle_hash", self.checkpoint_bundle_hash)

    def matches(self, value: ValueRange, owner_addr: str) -> bool:
        return (
            self.owner_addr == owner_addr
            and self.value_begin == value.begin
            and self.value_end == value.end
        )


@dataclass(frozen=True, slots=True)
class GenesisAnchor:
    genesis_block_hash: bytes
    first_owner_addr: str
    value_begin: int
    value_end: int

    def __post_init__(self) -> None:
        _require_hash32("genesis_block_hash", self.genesis_block_hash)
        if not self.first_owner_addr:
            raise ValueError("first_owner_addr must be set")
        if self.value_end < self.value_begin:
            raise ValueError("invalid genesis anchor range")


@dataclass(frozen=True, slots=True)
class CheckpointAnchor:
    checkpoint: Checkpoint


@dataclass(frozen=True, slots=True)
class PriorWitnessLink:
    acquire_tx: OffChainTx
    prior_witness: "WitnessV2"


@dataclass(frozen=True, slots=True)
class WitnessV2:
    value: ValueRange
    current_owner_addr: str
    confirmed_bundle_chain: Tuple[ConfirmedBundleUnit, ...]
    anchor: GenesisAnchor | CheckpointAnchor | PriorWitnessLink

    def __post_init__(self) -> None:
        if not self.current_owner_addr:
            raise ValueError("current_owner_addr must be set")


@dataclass(frozen=True, slots=True)
class TransferPackage:
    target_tx: OffChainTx
    target_value: ValueRange
    witness_v2: WitnessV2


@dataclass(frozen=True, slots=True)
class ReceiptResponse:
    status: str
    receipt: Receipt | None
    proof_batch: ReceiptProofBatch | None = None


@dataclass(frozen=True, slots=True)
class BlockHeaderV2:
    version: int
    chain_id: int
    height: int
    prev_block_hash: bytes
    state_root: bytes
    diff_root: bytes
    timestamp: int
    proposer_sig: bytes = b""
    consensus_extra: bytes = b""

    def __post_init__(self) -> None:
        if self.version < 0 or self.chain_id < 0 or self.height < 0 or self.timestamp < 0:
            raise ValueError("invalid block header field")
        _require_hash32("prev_block_hash", self.prev_block_hash)
        _require_hash32("state_root", self.state_root)
        _require_hash32("diff_root", self.diff_root)


@dataclass(frozen=True, slots=True)
class DiffPackage:
    diff_entries: Tuple[DiffEntry, ...]
    sidecars: Tuple[BundleSidecar, ...]
    sender_public_keys: Tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        if len(self.diff_entries) != len(self.sidecars):
            raise ValueError("diff_entries and sidecars length mismatch")
        if self.sender_public_keys and len(self.sender_public_keys) != len(self.diff_entries):
            raise ValueError("sender_public_keys length mismatch")


@dataclass(frozen=True, slots=True)
class BlockV2:
    block_hash: bytes
    header: BlockHeaderV2
    diff_package: DiffPackage

    def __post_init__(self) -> None:
        _require_hash32("block_hash", self.block_hash)
