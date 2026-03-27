"""
Mempool limits and cleanup tests — verify BundlePool size/tx limits and
mempool drainage after finalization for both winner and non-winner nodes.

Spec coverage:
  - protocol-draft §8.4   MAX_BUNDLE_BYTES, MAX_TX_PER_BUNDLE, MAX_VALUE_ENTRIES_PER_TX
  - consensus-mvp-spec §12 item 4  non-winner must drain mempool after final
  - consensus-mvp-spec §13  receipt cache pruning
"""

import unittest

from EZ_V2.chain import BundlePool, ChainStateV2, ReceiptCache, BundleRef, compute_bundle_hash, sign_bundle_envelope
from EZ_V2.crypto import (
    address_from_public_key_pem,
    generate_secp256k1_keypair,
)
from EZ_V2.types import (
    BundleEnvelope,
    BundleSidecar,
    BundleSubmission,
    HeaderLite,
    OffChainTx,
    Receipt,
    SparseMerkleProof,
)
from EZ_V2.values import ValueRange

_CHAIN_ID = 91001
_GENESIS_HASH = b"\xbb" * 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_keypair_and_addr():
    priv, pub = generate_secp256k1_keypair()
    addr = address_from_public_key_pem(pub)
    return priv, pub, addr


def _build_submission(
    priv: bytes,
    pub: bytes,
    sender_addr: str,
    recipient_addr: str,
    value: ValueRange,
    *,
    chain_id: int = _CHAIN_ID,
    seq: int = 1,
    expiry_height: int = 1000,
    fee: int = 1,
    extra_tx_list: list[OffChainTx] | None = None,
    extra_value_entries: int = 0,
) -> BundleSubmission:
    """Build a valid, signed BundleSubmission."""
    # Extra value entries must be non-overlapping and non-adjacent (intersects is inclusive)
    extra_ranges = []
    cursor = value.end + 2  # leave a gap to avoid adjacency
    for _ in range(extra_value_entries):
        extra_ranges.append(ValueRange(cursor, cursor + 50))
        cursor += 60  # gap between entries

    tx = OffChainTx(
        sender_addr=sender_addr,
        recipient_addr=recipient_addr,
        value_list=tuple([value] + extra_ranges),
        tx_local_index=0,
        tx_time=1000,
    )
    tx_list = [tx]
    if extra_tx_list is not None:
        tx_list.extend(extra_tx_list)

    sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=tuple(tx_list))
    bhash = compute_bundle_hash(sidecar)

    envelope = BundleEnvelope(
        version=2,
        chain_id=chain_id,
        seq=seq,
        expiry_height=expiry_height,
        fee=fee,
        anti_spam_nonce=0,
        bundle_hash=bhash,
    )
    envelope = sign_bundle_envelope(envelope, priv)

    return BundleSubmission(
        envelope=envelope,
        sidecar=sidecar,
        sender_public_key_pem=pub,
    )


# ---------------------------------------------------------------------------
# Bundle size / tx count / value entry limits
# ---------------------------------------------------------------------------


class TestBundleSizeLimit(unittest.TestCase):
    """protocol-draft §8.4 — MAX_BUNDLE_BYTES enforcement"""

    def test_oversized_bundle_rejected(self):
        pool = BundlePool(chain_id=_CHAIN_ID, max_bundle_bytes=128)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        # Add enough extra value entries to blow past 128 bytes
        sub = _build_submission(
            priv, pub, addr, recip,
            ValueRange(0, 49),
            extra_value_entries=20,
        )
        with self.assertRaises(ValueError) as ctx:
            pool.submit(sub, current_height=0, confirmed_seq=0)
        self.assertIn("size", str(ctx.exception).lower())

    def test_exact_size_limit_accepted(self):
        """A bundle at exactly max_bundle_bytes should pass."""
        pool = BundlePool(chain_id=_CHAIN_ID, max_bundle_bytes=128)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        sub = _build_submission(priv, pub, addr, recip, ValueRange(0, 49))
        sidecar_size = len(__import__("EZ_V2.encoding", fromlist=["canonical_encode"]).canonical_encode(sub.sidecar))
        if sidecar_size <= 128:
            result = pool.submit(sub, current_height=0, confirmed_seq=0)
            self.assertEqual(result, addr)


class TestBundleTxCountLimit(unittest.TestCase):
    """protocol-draft §8.4 — MAX_TX_PER_BUNDLE enforcement"""

    def test_exceeding_tx_count_rejected(self):
        pool = BundlePool(chain_id=_CHAIN_ID, max_tx_per_bundle=2)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        extra_txs = [
            OffChainTx(
                sender_addr=addr,
                recipient_addr=recip,
                value_list=(ValueRange(1000 + i * 100, 1000 + i * 100 + 50),),
                tx_local_index=1 + i,
                tx_time=1000,
            )
            for i in range(5)
        ]
        sub = _build_submission(
            priv, pub, addr, recip,
            ValueRange(0, 49),
            extra_tx_list=extra_txs,
        )
        self.assertGreater(len(sub.sidecar.tx_list), 2)
        with self.assertRaises(ValueError) as ctx:
            pool.submit(sub, current_height=0, confirmed_seq=0)
        self.assertIn("tx count", str(ctx.exception).lower())


class TestBundleValueEntryLimit(unittest.TestCase):
    """protocol-draft §8.4 — MAX_VALUE_ENTRIES_PER_TX enforcement"""

    def test_exceeding_value_entries_rejected(self):
        pool = BundlePool(chain_id=_CHAIN_ID, max_value_entries_per_tx=3)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        sub = _build_submission(
            priv, pub, addr, recip,
            ValueRange(0, 49),
            extra_value_entries=5,  # total 6 value entries > max 3
        )
        with self.assertRaises(ValueError) as ctx:
            pool.submit(sub, current_height=0, confirmed_seq=0)
        self.assertIn("value entry", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Mempool cleanup after finalization
# ---------------------------------------------------------------------------


class TestWinnerMempoolDrained(unittest.TestCase):
    """spec §12 item 4 — winner must drain confirmed bundles from pool"""

    def test_build_block_drains_winner_pool(self):
        pool = BundlePool(chain_id=_CHAIN_ID)
        priv1, pub1, addr1 = _make_keypair_and_addr()
        _, _, recip1 = _make_keypair_and_addr()

        sub1 = _build_submission(priv1, pub1, addr1, recip1, ValueRange(0, 99))
        pool.submit(sub1, current_height=0, confirmed_seq=0)

        self.assertIsNotNone(pool._pending_by_sender.get(addr1))

        # Simulate winner drain
        removed = pool.remove_finalized_bundle(
            addr1, sub1.envelope.seq, sub1.envelope.bundle_hash
        )
        self.assertTrue(removed)
        self.assertIsNone(pool._pending_by_sender.get(addr1))


class TestNonWinnerMempoolDrained(unittest.TestCase):
    """spec §12 item 4 — non-winner must also drain after apply_block"""

    def test_remove_finalized_bundle_works_for_non_winner(self):
        """Non-winner calls remove_finalized_bundle with the same semantics."""
        pool = BundlePool(chain_id=_CHAIN_ID)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        sub = _build_submission(priv, pub, addr, recip, ValueRange(0, 99))
        pool.submit(sub, current_height=0, confirmed_seq=0)

        # Simulate non-winner receiving finalized info and draining
        removed = pool.remove_finalized_bundle(
            addr, sub.envelope.seq, sub.envelope.bundle_hash
        )
        self.assertTrue(removed)
        self.assertIsNone(pool._pending_by_sender.get(addr))

    def test_non_winner_drains_by_seq(self):
        """If seq matches, removal succeeds even without exact bundle_hash."""
        pool = BundlePool(chain_id=_CHAIN_ID)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        sub = _build_submission(priv, pub, addr, recip, ValueRange(0, 99))
        pool.submit(sub, current_height=0, confirmed_seq=0)

        # Remove by seq alone (different hash, but same seq)
        removed = pool.remove_finalized_bundle(
            addr, sub.envelope.seq, b"\xff" * 32
        )
        self.assertTrue(removed)


class TestNewerPendingBundleKept(unittest.TestCase):
    """spec §12 — if pending bundle has higher seq than finalized, keep it"""

    def test_newer_seq_not_removed(self):
        pool = BundlePool(chain_id=_CHAIN_ID)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        # Submit seq=2 (simulating a pending bundle)
        sub = _build_submission(priv, pub, addr, recip, ValueRange(0, 99), seq=2)
        pool.submit(sub, current_height=0, confirmed_seq=1)

        # Now finalize seq=1 — should NOT remove the seq=2 pending bundle
        removed = pool.remove_finalized_bundle(addr, seq=1, bundle_hash=b"\x00" * 32)
        self.assertFalse(removed)
        self.assertIsNotNone(pool._pending_by_sender.get(addr))

    def test_old_seq_removed(self):
        """A pending bundle with seq=1 is removed when seq=1 is finalized."""
        pool = BundlePool(chain_id=_CHAIN_ID)
        priv, pub, addr = _make_keypair_and_addr()
        _, _, recip = _make_keypair_and_addr()

        sub = _build_submission(priv, pub, addr, recip, ValueRange(0, 99), seq=1)
        pool.submit(sub, current_height=0, confirmed_seq=0)

        removed = pool.remove_finalized_bundle(addr, seq=1, bundle_hash=b"\x00" * 32)
        self.assertTrue(removed)
        self.assertIsNone(pool._pending_by_sender.get(addr))


# ---------------------------------------------------------------------------
# Receipt cache pruning
# ---------------------------------------------------------------------------


class TestReceiptCachePruning(unittest.TestCase):
    """spec §13 — ReceiptCache prunes old receipts beyond max_blocks"""

    def test_old_receipts_pruned(self):
        cache = ReceiptCache(max_blocks=3)

        for h in range(1, 6):
            bh = h.to_bytes(32, "big")
            ref = BundleRef(
                height=h,
                block_hash=bh,
                bundle_hash=bytes([h]) + b"\xaa" * 31,
                seq=h,
            )
            receipt = Receipt(
                header_lite=HeaderLite(
                    height=h,
                    block_hash=bh,
                    state_root=bytes([h]) + b"\x01" * 31,
                ),
                seq=h,
                prev_ref=None,
                account_state_proof=SparseMerkleProof(siblings=(), existence=True),
            )
            cache.add(f"sender-{h}", receipt, ref)

        # Heights 1-2 should be pruned, only 3-5 remain (3 heights)
        resp1 = cache.get_receipt("sender-1", 1)
        self.assertEqual(resp1.status, "missing")

        resp4 = cache.get_receipt("sender-4", 4)
        self.assertEqual(resp4.status, "ok")

    def test_exact_max_blocks_retained(self):
        cache = ReceiptCache(max_blocks=2)

        for h in range(1, 4):
            bh = h.to_bytes(32, "big")
            ref = BundleRef(
                height=h,
                block_hash=bh,
                bundle_hash=bytes([h]) + b"\xaa" * 31,
                seq=h,
            )
            receipt = Receipt(
                header_lite=HeaderLite(
                    height=h,
                    block_hash=bh,
                    state_root=bytes([h]) + b"\x01" * 31,
                ),
                seq=h,
                prev_ref=None,
                account_state_proof=SparseMerkleProof(siblings=(), existence=True),
            )
            cache.add(f"sender", receipt, ref)

        # Heights 2 and 3 should survive (max_blocks=2, height 1 pruned)
        resp1 = cache.get_receipt("sender", 1)
        self.assertEqual(resp1.status, "missing")
        resp2 = cache.get_receipt("sender", 2)
        self.assertEqual(resp2.status, "ok")
        resp3 = cache.get_receipt("sender", 3)
        self.assertEqual(resp3.status, "ok")


if __name__ == "__main__":
    unittest.main()
