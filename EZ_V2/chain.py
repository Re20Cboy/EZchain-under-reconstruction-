from __future__ import annotations

from typing import Iterable

from .claim_set import claim_range_set_from_sidecar, claim_range_set_hash
from .crypto import address_from_public_key_pem, keccak256, sign_digest_secp256k1, verify_digest_secp256k1
from .encoding import canonical_encode
from .smt import SparseMerkleTree, build_multiproof, verify_proof
from .types import (
    AccountLeaf,
    BlockHeaderV2,
    BlockV2,
    BundleEnvelope,
    BundleRef,
    BundleSidecar,
    BundleSubmission,
    ConfirmedBundleUnit,
    DiffEntry,
    DiffPackage,
    HeaderLite,
    Receipt,
    ReceiptProofBatch,
    ReceiptProofRef,
    ReceiptResponse,
)


ZERO_HASH32 = b"\x00" * 32
EMPTY_DIFF_ROOT = keccak256(b"EZCHAIN_EMPTY_DIFF_ROOT_V2")
MERKLE_EMPTY = keccak256(b"EZCHAIN_EMPTY_MERKLE_V2")


def merkle_root(leaf_hashes: Iterable[bytes], domain: bytes = b"EZCHAIN_MERKLE_NODE_V2") -> bytes:
    level = list(leaf_hashes)
    if not level:
        return MERKLE_EMPTY
    for item in level:
        if len(item) != 32:
            raise ValueError("leaf hash must be 32 bytes")
    while len(level) > 1:
        next_level = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(keccak256(domain + left + right))
        level = next_level
    return level[0]


def compute_addr_key(addr: str) -> bytes:
    return keccak256(b"EZCHAIN_ADDR_KEY_V2" + addr.encode("utf-8"))


def compute_bundle_hash(sidecar: BundleSidecar) -> bytes:
    return keccak256(b"EZCHAIN_BUNDLE_BODY_V2" + canonical_encode(sidecar))


def compute_bundle_sighash(envelope: BundleEnvelope) -> bytes:
    return keccak256(b"EZCHAIN_BUNDLE_V2" + canonical_encode(envelope.signing_payload()))


def sign_bundle_envelope(envelope: BundleEnvelope, private_key_pem: bytes) -> BundleEnvelope:
    signature = sign_digest_secp256k1(private_key_pem, compute_bundle_sighash(envelope))
    return envelope.with_signature(signature)


def verify_bundle_envelope(envelope: BundleEnvelope, public_key_pem: bytes) -> bool:
    if not envelope.sig:
        return False
    return verify_digest_secp256k1(public_key_pem, compute_bundle_sighash(envelope), envelope.sig)


def _account_leaf_payload(leaf: AccountLeaf) -> dict:
    payload = {
        "addr": leaf.addr,
        "head_ref": leaf.head_ref,
        "prev_ref": leaf.prev_ref,
    }
    if leaf.claim_set_hash is not None:
        payload["claim_set_hash"] = leaf.claim_set_hash
    return payload


def hash_account_leaf(leaf: AccountLeaf) -> bytes:
    return keccak256(b"EZCHAIN_ACCOUNT_LEAF_V2" + canonical_encode(_account_leaf_payload(leaf)))


def compute_diff_leaf_hash(entry: DiffEntry) -> bytes:
    envelope_hash = keccak256(canonical_encode(entry.bundle_envelope))
    leaf_hash = keccak256(canonical_encode(entry.new_leaf))
    return keccak256(
        b"EZCHAIN_DIFF_LEAF_V2"
        + canonical_encode(
            {
                "addr_key": entry.addr_key,
                "new_leaf_hash": leaf_hash,
                "bundle_envelope_hash": envelope_hash,
                "bundle_hash": entry.bundle_hash,
            }
        )
    )


def compute_diff_root(entries: Iterable[DiffEntry]) -> bytes:
    entry_list = list(entries)
    if not entry_list:
        return EMPTY_DIFF_ROOT
    return merkle_root([compute_diff_leaf_hash(entry) for entry in entry_list], domain=b"EZCHAIN_DIFF_NODE_V2")


def derive_block_hash(
    version: int,
    chain_id: int,
    height: int,
    prev_block_hash: bytes,
    timestamp: int,
    proposer_sig: bytes,
    consensus_extra: bytes,
    ordered_entries: Iterable[DiffEntry],
) -> bytes:
    ordered_entries = list(ordered_entries)
    return keccak256(
        b"EZCHAIN_BLOCK_ID_V2"
        + canonical_encode(
            {
                "version": version,
                "chain_id": chain_id,
                "height": height,
                "prev_block_hash": prev_block_hash,
                "timestamp": timestamp,
                "proposer_sig": proposer_sig,
                "consensus_extra": consensus_extra,
                "addr_keys": [entry.addr_key for entry in ordered_entries],
                "bundle_hashes": [entry.bundle_hash for entry in ordered_entries],
            }
        )
    )


def confirmed_ref(unit: ConfirmedBundleUnit) -> BundleRef:
    return BundleRef(
        height=unit.receipt.header_lite.height,
        block_hash=unit.receipt.header_lite.block_hash,
        bundle_hash=compute_bundle_hash(unit.bundle_sidecar),
        seq=unit.receipt.seq,
    )


def reconstructed_leaf(unit: ConfirmedBundleUnit) -> AccountLeaf:
    return AccountLeaf(
        addr=unit.bundle_sidecar.sender_addr,
        head_ref=confirmed_ref(unit),
        prev_ref=unit.receipt.prev_ref,
        claim_set_hash=unit.receipt.claim_set_hash,
    )


class ReceiptCache:
    def __init__(self, max_blocks: int = 32):
        self.max_blocks = max(1, max_blocks)
        self._by_height: dict[int, list[tuple[str, Receipt, BundleRef]]] = {}
        self._by_addr_seq: dict[tuple[str, int], Receipt] = {}
        self._by_ref: dict[tuple[int, bytes, bytes, int], Receipt] = {}
        self._proof_batches_by_height: dict[int, list[str]] = {}
        self._proof_batches: dict[str, ReceiptProofBatch] = {}

    def add(self, sender_addr: str, receipt: Receipt, bundle_ref: BundleRef) -> None:
        key = (sender_addr, receipt.seq)
        self._by_addr_seq[key] = receipt
        self._by_ref[(bundle_ref.height, bundle_ref.block_hash, bundle_ref.bundle_hash, bundle_ref.seq)] = receipt
        self._by_height.setdefault(receipt.header_lite.height, []).append((sender_addr, receipt, bundle_ref))
        self._prune()

    def _prune(self) -> None:
        if not self._by_height:
            return
        heights = sorted(self._by_height.keys())
        while len(heights) > self.max_blocks:
            height = heights.pop(0)
            for sender_addr, receipt, bundle_ref in self._by_height.pop(height, []):
                self._by_addr_seq.pop((sender_addr, receipt.seq), None)
                self._by_ref.pop(
                    (
                        bundle_ref.height,
                        bundle_ref.block_hash,
                        bundle_ref.bundle_hash,
                        bundle_ref.seq,
                    ),
                    None,
                )
            for batch_id in self._proof_batches_by_height.pop(height, []):
                self._proof_batches.pop(batch_id, None)

    def add_proof_batch(self, height: int, batch: ReceiptProofBatch) -> None:
        self._proof_batches[batch.batch_id] = batch
        height_batches = self._proof_batches_by_height.setdefault(height, [])
        if batch.batch_id not in height_batches:
            height_batches.append(batch.batch_id)
        self._prune()

    def get_proof_batch(self, batch_id: str) -> ReceiptProofBatch | None:
        return self._proof_batches.get(batch_id)

    def get_receipt(self, sender_addr: str, seq: int) -> ReceiptResponse:
        receipt = self._by_addr_seq.get((sender_addr, seq))
        return ReceiptResponse(status="ok" if receipt else "missing", receipt=receipt)

    def get_receipt_by_ref(self, bundle_ref: BundleRef) -> ReceiptResponse:
        receipt = self._by_ref.get((bundle_ref.height, bundle_ref.block_hash, bundle_ref.bundle_hash, bundle_ref.seq))
        return ReceiptResponse(status="ok" if receipt else "missing", receipt=receipt)


class BundlePool:
    def __init__(
        self,
        chain_id: int,
        max_bundle_bytes: int = 32_768,
        max_tx_per_bundle: int = 128,
        max_value_entries_per_tx: int = 64,
    ):
        self.chain_id = chain_id
        self.max_bundle_bytes = max_bundle_bytes
        self.max_tx_per_bundle = max_tx_per_bundle
        self.max_value_entries_per_tx = max_value_entries_per_tx
        self._pending_by_sender: dict[str, BundleSubmission] = {}

    def submit(
        self,
        submission: BundleSubmission,
        current_height: int,
        confirmed_seq: int,
    ) -> str:
        sender_addr = address_from_public_key_pem(submission.sender_public_key_pem)
        if submission.envelope.chain_id != self.chain_id:
            raise ValueError("chain_id mismatch")
        if submission.sidecar.sender_addr != sender_addr:
            raise ValueError("sidecar sender does not match public key")
        if submission.envelope.expiry_height < current_height:
            raise ValueError("bundle expired")
        if compute_bundle_hash(submission.sidecar) != submission.envelope.bundle_hash:
            raise ValueError("bundle hash mismatch")
        computed_claim_set_hash = claim_range_set_hash(claim_range_set_from_sidecar(submission.sidecar))
        if submission.envelope.claim_set_hash is not None and submission.envelope.claim_set_hash != computed_claim_set_hash:
            raise ValueError("claim_set_hash mismatch")
        if not verify_bundle_envelope(submission.envelope, submission.sender_public_key_pem):
            raise ValueError("invalid bundle signature")
        if len(canonical_encode(submission.sidecar)) > self.max_bundle_bytes:
            raise ValueError("bundle exceeds size limit")
        if len(submission.sidecar.tx_list) > self.max_tx_per_bundle:
            raise ValueError("bundle exceeds tx count limit")
        for tx in submission.sidecar.tx_list:
            if len(tx.value_list) > self.max_value_entries_per_tx:
                raise ValueError("bundle exceeds tx value entry limit")
        expected_seq = confirmed_seq + 1
        if submission.envelope.seq != expected_seq:
            existing = self._pending_by_sender.get(sender_addr)
            if not existing or existing.envelope.seq != submission.envelope.seq:
                raise ValueError("bundle seq is not currently executable")
        existing = self._pending_by_sender.get(sender_addr)
        if existing:
            if existing.envelope.seq != submission.envelope.seq:
                raise ValueError("sender already has a different pending bundle")
            if existing.envelope.bundle_hash != submission.envelope.bundle_hash:
                raise ValueError("sender already has a different pending bundle")
            if (
                existing.envelope == submission.envelope
                and existing.sidecar == submission.sidecar
                and existing.sender_public_key_pem == submission.sender_public_key_pem
            ):
                return sender_addr
            if submission.envelope.fee <= existing.envelope.fee:
                raise ValueError("replacement bundle fee too low")
        self._pending_by_sender[sender_addr] = submission
        return sender_addr

    def snapshot(self, limit: int | None = None) -> list[BundleSubmission]:
        ordered = sorted(
            self._pending_by_sender.values(),
            key=lambda item: compute_addr_key(item.sidecar.sender_addr),
        )
        if limit is None:
            return ordered
        return ordered[:limit]

    def remove_sender(self, sender_addr: str) -> None:
        self._pending_by_sender.pop(sender_addr, None)

    def remove_finalized_bundle(self, sender_addr: str, seq: int, bundle_hash: bytes) -> bool:
        existing = self._pending_by_sender.get(sender_addr)
        if existing is None:
            return False
        existing_seq = existing.envelope.seq
        if existing_seq > seq:
            return False
        if existing_seq < seq or existing.envelope.bundle_hash == bundle_hash or existing_seq == seq:
            self._pending_by_sender.pop(sender_addr, None)
            return True
        return False


class ChainStateV2:
    def __init__(
        self,
        version: int = 2,
        chain_id: int = 1,
        receipt_cache_blocks: int = 32,
        max_bundle_bytes: int = 32_768,
        max_tx_per_bundle: int = 128,
        max_value_entries_per_tx: int = 64,
        genesis_block_hash: bytes = ZERO_HASH32,
    ):
        self.version = version
        self.chain_id = chain_id
        self.current_height = 0
        self.current_block_hash = genesis_block_hash
        self.tree = SparseMerkleTree()
        self.account_leaves: dict[str, AccountLeaf] = {}
        self.blocks: list[BlockV2] = []
        self.receipt_cache = ReceiptCache(max_blocks=receipt_cache_blocks)
        self.bundle_pool = BundlePool(
            chain_id=chain_id,
            max_bundle_bytes=max_bundle_bytes,
            max_tx_per_bundle=max_tx_per_bundle,
            max_value_entries_per_tx=max_value_entries_per_tx,
        )

    def copy(self) -> "ChainStateV2":
        other = ChainStateV2(
            version=self.version,
            chain_id=self.chain_id,
            receipt_cache_blocks=self.receipt_cache.max_blocks,
            genesis_block_hash=self.current_block_hash,
        )
        other.current_height = self.current_height
        other.current_block_hash = self.current_block_hash
        other.tree = self.tree.copy()
        other.account_leaves = dict(self.account_leaves)
        return other

    def confirmed_seq(self, sender_addr: str) -> int:
        leaf = self.account_leaves.get(sender_addr)
        if leaf is None or leaf.head_ref is None:
            return 0
        return leaf.head_ref.seq

    def submit_bundle(self, submission: BundleSubmission) -> str:
        sender_addr = address_from_public_key_pem(submission.sender_public_key_pem)
        return self.bundle_pool.submit(
            submission=submission,
            current_height=self.current_height,
            confirmed_seq=self.confirmed_seq(sender_addr),
        )

    def build_block(
        self,
        timestamp: int,
        proposer_sig: bytes = b"",
        consensus_extra: bytes = b"",
        limit: int | None = None,
    ) -> tuple[BlockV2, dict[str, Receipt]]:
        submissions = self.bundle_pool.snapshot(limit=limit)
        return self._execute_submissions(
            submissions=submissions,
            timestamp=timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
            remove_from_pool=True,
        )

    def preview_block(
        self,
        timestamp: int,
        proposer_sig: bytes = b"",
        consensus_extra: bytes = b"",
        limit: int | None = None,
    ) -> tuple[BlockV2, dict[str, Receipt]]:
        preview = self.copy()
        preview.bundle_pool._pending_by_sender = dict(self.bundle_pool._pending_by_sender)
        return preview.build_block(
            timestamp=timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
            limit=limit,
        )

    def _prepare_entries(
        self,
        submissions: list[BundleSubmission],
        height: int,
        block_hash: bytes,
    ) -> tuple[list[DiffEntry], dict[str, BundleRef | None]]:
        entries = []
        prev_refs: dict[str, BundleRef | None] = {}
        for submission in submissions:
            sender_addr = submission.sidecar.sender_addr
            old_leaf = self.account_leaves.get(sender_addr)
            prev_refs[sender_addr] = old_leaf.head_ref if old_leaf else None
            current_ref = BundleRef(
                height=height,
                block_hash=block_hash,
                bundle_hash=submission.envelope.bundle_hash,
                seq=submission.envelope.seq,
            )
            new_leaf = AccountLeaf(
                addr=sender_addr,
                head_ref=current_ref,
                prev_ref=old_leaf.head_ref if old_leaf else None,
                claim_set_hash=submission.envelope.claim_set_hash,
            )
            entries.append(
                DiffEntry(
                    addr_key=compute_addr_key(sender_addr),
                    new_leaf=new_leaf,
                    bundle_envelope=submission.envelope,
                    bundle_hash=submission.envelope.bundle_hash,
                )
            )
        return entries, prev_refs

    def _execute_submissions(
        self,
        submissions: list[BundleSubmission],
        timestamp: int,
        proposer_sig: bytes,
        consensus_extra: bytes,
        remove_from_pool: bool,
    ) -> tuple[BlockV2, dict[str, Receipt]]:
        height = self.current_height + 1
        provisional_entries, prev_refs = self._prepare_entries(
            submissions=submissions,
            height=height,
            block_hash=ZERO_HASH32,
        )
        provisional_entries = sorted(provisional_entries, key=lambda item: item.addr_key)
        block_hash = derive_block_hash(
            version=self.version,
            chain_id=self.chain_id,
            height=height,
            prev_block_hash=self.current_block_hash,
            timestamp=timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
            ordered_entries=provisional_entries,
        )
        entries, prev_refs = self._prepare_entries(
            submissions=sorted(submissions, key=lambda item: compute_addr_key(item.sidecar.sender_addr)),
            height=height,
            block_hash=block_hash,
        )
        entries = sorted(entries, key=lambda item: item.addr_key)
        temp_tree = self.tree.copy()
        temp_account_leaves = dict(self.account_leaves)
        for entry in entries:
            temp_tree.set(entry.addr_key, hash_account_leaf(entry.new_leaf))
            temp_account_leaves[entry.new_leaf.addr] = entry.new_leaf
        state_root = temp_tree.root()
        diff_root = compute_diff_root(entries)
        header = BlockHeaderV2(
            version=self.version,
            chain_id=self.chain_id,
            height=height,
            prev_block_hash=self.current_block_hash,
            state_root=state_root,
            diff_root=diff_root,
            timestamp=timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
        )
        block = BlockV2(
            block_hash=block_hash,
            header=header,
            diff_package=DiffPackage(
                diff_entries=tuple(entries),
                sidecars=tuple(submission.sidecar for submission in sorted(submissions, key=lambda item: compute_addr_key(item.sidecar.sender_addr))),
                sender_public_keys=tuple(submission.sender_public_key_pem for submission in sorted(submissions, key=lambda item: compute_addr_key(item.sidecar.sender_addr))),
            ),
        )
        receipts: dict[str, Receipt] = {}
        proof_batch = None
        if entries:
            proof_batch = ReceiptProofBatch(
                batch_id=f"{height}:{block_hash.hex()}",
                state_root=state_root,
                multi_proof=build_multiproof(temp_tree, [entry.addr_key for entry in entries]),
            )
            self.receipt_cache.add_proof_batch(height, proof_batch)
        for entry in entries:
            proof = temp_tree.prove(entry.addr_key)
            receipt = Receipt(
                header_lite=HeaderLite(height=height, block_hash=block_hash, state_root=state_root),
                seq=entry.bundle_envelope.seq,
                prev_ref=prev_refs[entry.new_leaf.addr],
                claim_set_hash=entry.new_leaf.claim_set_hash,
                account_state_proof=proof,
            )
            receipts[entry.new_leaf.addr] = receipt
            self.receipt_cache.add(entry.new_leaf.addr, receipt, entry.new_leaf.head_ref)
        self.current_height = height
        self.current_block_hash = block_hash
        self.tree = temp_tree
        self.account_leaves = temp_account_leaves
        self.blocks.append(block)
        if remove_from_pool:
            for submission in submissions:
                self.bundle_pool.remove_finalized_bundle(
                    submission.sidecar.sender_addr,
                    submission.envelope.seq,
                    submission.envelope.bundle_hash,
                )
        return block, receipts

    def apply_block(self, block: BlockV2) -> dict[str, Receipt]:
        if block.header.version != self.version or block.header.chain_id != self.chain_id:
            raise ValueError("block version/chain mismatch")
        if block.header.height != self.current_height + 1:
            raise ValueError("unexpected block height")
        if block.header.prev_block_hash != self.current_block_hash:
            raise ValueError("prev_block_hash mismatch")
        entries = list(block.diff_package.diff_entries)
        if entries != sorted(entries, key=lambda item: item.addr_key):
            raise ValueError("diff entries not sorted")
        if len({entry.addr_key for entry in entries}) != len(entries):
            raise ValueError("duplicate addr_key in diff package")
        if len(entries) != len(block.diff_package.sidecars):
            raise ValueError("diff package sidecars length mismatch")
        if len(entries) != len(block.diff_package.sender_public_keys):
            raise ValueError("missing sender public keys for validation")
        expected_block_hash = derive_block_hash(
            version=block.header.version,
            chain_id=block.header.chain_id,
            height=block.header.height,
            prev_block_hash=block.header.prev_block_hash,
            timestamp=block.header.timestamp,
            proposer_sig=block.header.proposer_sig,
            consensus_extra=block.header.consensus_extra,
            ordered_entries=entries,
        )
        if expected_block_hash != block.block_hash:
            raise ValueError("block hash mismatch")
        temp_tree = self.tree.copy()
        temp_account_leaves = dict(self.account_leaves)
        receipts: dict[str, Receipt] = {}
        seen_senders: set[str] = set()
        for entry, sidecar, public_key in zip(entries, block.diff_package.sidecars, block.diff_package.sender_public_keys):
            sender_addr = address_from_public_key_pem(public_key)
            if sender_addr in seen_senders:
                raise ValueError("duplicate sender in block")
            seen_senders.add(sender_addr)
            if sender_addr != sidecar.sender_addr or sender_addr != entry.new_leaf.addr:
                raise ValueError("sender/public key mismatch")
            if compute_bundle_hash(sidecar) != entry.bundle_hash or entry.bundle_hash != entry.bundle_envelope.bundle_hash:
                raise ValueError("bundle hash mismatch")
            computed_claim_set_hash = claim_range_set_hash(claim_range_set_from_sidecar(sidecar))
            if entry.bundle_envelope.claim_set_hash is not None and entry.bundle_envelope.claim_set_hash != computed_claim_set_hash:
                raise ValueError("claim_set_hash mismatch")
            if entry.new_leaf.claim_set_hash != entry.bundle_envelope.claim_set_hash:
                raise ValueError("new leaf claim_set_hash mismatch")
            if not verify_bundle_envelope(entry.bundle_envelope, public_key):
                raise ValueError("bundle signature invalid")
            if entry.bundle_envelope.expiry_height < block.header.height:
                raise ValueError("bundle expired")
            old_leaf = self.account_leaves.get(sender_addr)
            expected_prev_ref = old_leaf.head_ref if old_leaf else None
            if entry.new_leaf.prev_ref != expected_prev_ref:
                raise ValueError("new leaf prev_ref mismatch")
            if old_leaf is None:
                if entry.bundle_envelope.seq != 1:
                    raise ValueError("first bundle seq must be 1")
            else:
                if entry.bundle_envelope.seq != old_leaf.head_ref.seq + 1:
                    raise ValueError("bundle seq discontinuity")
            if entry.new_leaf.head_ref.bundle_hash != entry.bundle_hash:
                raise ValueError("new leaf head_ref bundle hash mismatch")
            if entry.new_leaf.head_ref.block_hash != block.block_hash:
                raise ValueError("new leaf head_ref block hash mismatch")
            temp_tree.set(entry.addr_key, hash_account_leaf(entry.new_leaf))
            temp_account_leaves[sender_addr] = entry.new_leaf
        if compute_diff_root(entries) != block.header.diff_root:
            raise ValueError("diff_root mismatch")
        if temp_tree.root() != block.header.state_root:
            raise ValueError("state_root mismatch")
        if entries:
            proof_batch = ReceiptProofBatch(
                batch_id=f"{block.header.height}:{block.block_hash.hex()}",
                state_root=block.header.state_root,
                multi_proof=build_multiproof(temp_tree, [entry.addr_key for entry in entries]),
            )
            self.receipt_cache.add_proof_batch(block.header.height, proof_batch)
        for entry in entries:
            proof = temp_tree.prove(entry.addr_key)
            leaf_hash = hash_account_leaf(entry.new_leaf)
            if not verify_proof(block.header.state_root, entry.addr_key, leaf_hash, proof):
                raise ValueError("generated receipt proof does not verify")
            receipt = Receipt(
                header_lite=HeaderLite(
                    height=block.header.height,
                    block_hash=block.block_hash,
                    state_root=block.header.state_root,
                ),
                seq=entry.bundle_envelope.seq,
                prev_ref=self.account_leaves.get(entry.new_leaf.addr).head_ref if self.account_leaves.get(entry.new_leaf.addr) else None,
                claim_set_hash=entry.new_leaf.claim_set_hash,
                account_state_proof=proof,
            )
            receipts[entry.new_leaf.addr] = receipt
            self.receipt_cache.add(entry.new_leaf.addr, receipt, entry.new_leaf.head_ref)
        self.current_height = block.header.height
        self.current_block_hash = block.block_hash
        self.tree = temp_tree
        self.account_leaves = temp_account_leaves
        self.blocks.append(block)
        for entry in entries:
            self.bundle_pool.remove_finalized_bundle(
                entry.new_leaf.addr,
                entry.bundle_envelope.seq,
                entry.bundle_hash,
            )
        return receipts


__all__ = [
    "BundlePool",
    "ChainStateV2",
    "ReceiptCache",
    "compute_addr_key",
    "compute_bundle_hash",
    "compute_bundle_sighash",
    "compute_diff_root",
    "confirmed_ref",
    "hash_account_leaf",
    "reconstructed_leaf",
    "sign_bundle_envelope",
    "verify_bundle_envelope",
]
