from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from EZ_V2.chain import compute_bundle_hash, confirmed_ref
from EZ_V2.crypto import keccak256
from EZ_V2.storage import LocalWalletDB
from EZ_V2.types import (
    BundleEnvelope,
    BundleSidecar,
    Checkpoint,
    ConfirmedBundleUnit,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PendingBundleContext,
    Receipt,
    SparseMerkleProof,
    WitnessV2,
)
from EZ_V2.values import LocalValueRecord, LocalValueStatus, ValueRange


def _make_sidecar(sender_addr: str, recipient_addr: str, value: ValueRange, tx_time: int = 1) -> BundleSidecar:
    return BundleSidecar(
        sender_addr=sender_addr,
        tx_list=(
            OffChainTx(
                sender_addr=sender_addr,
                recipient_addr=recipient_addr,
                value_list=(value,),
                tx_local_index=0,
                tx_time=tx_time,
            ),
        ),
    )


def _make_envelope(bundle_hash: bytes, seq: int) -> BundleEnvelope:
    return BundleEnvelope(
        version=2,
        chain_id=301,
        seq=seq,
        expiry_height=100,
        fee=1,
        anti_spam_nonce=seq,
        bundle_hash=bundle_hash,
    )


class EZV2StorageRestartTests(unittest.TestCase):
    def test_pending_receipts_and_confirmed_units_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            sender_addr = "alice"
            recipient_addr = "bob"
            sidecar = _make_sidecar(sender_addr, recipient_addr, ValueRange(0, 9))
            bundle_hash = compute_bundle_hash(sidecar)
            envelope = _make_envelope(bundle_hash, seq=2)

            db = LocalWalletDB(db_path)
            db.save_sidecar(sidecar)
            db.save_pending_bundle(
                PendingBundleContext(
                    sender_addr=sender_addr,
                    bundle_hash=bundle_hash,
                    seq=2,
                    envelope=envelope,
                    sidecar=sidecar,
                    sender_public_key_pem=b"sender-pub",
                    pending_record_ids=("pending-1",),
                    outgoing_record_ids=("out-1",),
                    outgoing_values=(ValueRange(0, 9),),
                    created_at=10,
                )
            )
            receipt = Receipt(
                header_lite=HeaderLite(
                    height=1,
                    block_hash=b"\x11" * 32,
                    state_root=b"\x22" * 32,
                ),
                seq=1,
                prev_ref=None,
                account_state_proof=SparseMerkleProof(siblings=(b"\x33" * 32,), existence=True),
            )
            db.save_receipt(sender_addr, receipt, bundle_hash)
            db.save_confirmed_unit(ConfirmedBundleUnit(receipt=receipt, bundle_sidecar=sidecar))
            self.assertEqual(db.next_sequence(sender_addr), 3)
            db.close()

            reopened = LocalWalletDB(db_path)
            self.assertEqual(reopened.next_sequence(sender_addr), 3)
            self.assertEqual(reopened.get_pending_bundle(sender_addr, 2).bundle_hash, bundle_hash)
            self.assertEqual(reopened.get_receipt(sender_addr, 1).seq, 1)
            self.assertEqual(reopened.get_receipt_by_ref(confirmed_ref(reopened.get_confirmed_unit(sender_addr, 1))).seq, 1)
            reopened.close()

    def test_recompute_sidecar_ref_counts_only_keeps_referenced_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LocalWalletDB(str(Path(tmpdir) / "wallet.sqlite3"))
            sender_addr = "alice"

            kept_sidecar = _make_sidecar(sender_addr, "bob", ValueRange(10, 19))
            dropped_sidecar = _make_sidecar(sender_addr, "carol", ValueRange(20, 29))
            kept_hash = db.save_sidecar(kept_sidecar)
            dropped_hash = db.save_sidecar(dropped_sidecar)
            db.save_pending_bundle(
                PendingBundleContext(
                    sender_addr=sender_addr,
                    bundle_hash=kept_hash,
                    seq=1,
                    envelope=_make_envelope(kept_hash, seq=1),
                    sidecar=kept_sidecar,
                    sender_public_key_pem=b"sender-pub",
                    pending_record_ids=("pending-1",),
                    outgoing_record_ids=("out-1",),
                    outgoing_values=(ValueRange(10, 19),),
                    created_at=20,
                )
            )

            db.recompute_sidecar_ref_counts()
            removed = db.gc_unused_sidecars()

            self.assertEqual(removed, 1)
            self.assertIsNotNone(db.get_sidecar(kept_hash))
            self.assertIsNone(db.get_sidecar(dropped_hash))
            db.close()

    def test_checkpoint_and_accepted_transfer_package_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            owner_addr = "alice"
            checkpoint = Checkpoint(
                value_begin=100,
                value_end=149,
                owner_addr=owner_addr,
                checkpoint_height=5,
                checkpoint_block_hash=b"\xaa" * 32,
                checkpoint_bundle_hash=b"\xbb" * 32,
            )
            witness = WitnessV2(
                value=ValueRange(100, 149),
                current_owner_addr=owner_addr,
                confirmed_bundle_chain=(),
                anchor=GenesisAnchor(
                    genesis_block_hash=b"\xcc" * 32,
                    first_owner_addr=owner_addr,
                    value_begin=100,
                    value_end=199,
                ),
            )

            db = LocalWalletDB(db_path)
            db.save_checkpoint(checkpoint)
            db.replace_value_records(
                owner_addr,
                [
                    LocalValueRecord(
                        record_id="record-1",
                        value=ValueRange(100, 149),
                        witness_v2=witness,
                        local_status=LocalValueStatus.VERIFIED_SPENDABLE,
                        acquisition_height=0,
                    )
                ],
            )
            package_hash = keccak256(b"package-1")
            db.save_accepted_transfer_package(owner_addr, package_hash, accepted_at=99)
            db.save_accepted_transfer_package(owner_addr, package_hash, accepted_at=100)
            db.close()

            reopened = LocalWalletDB(db_path)
            self.assertEqual(reopened.list_checkpoints(owner_addr), [checkpoint])
            self.assertTrue(reopened.has_accepted_transfer_package(owner_addr, package_hash))
            self.assertEqual(reopened.list_value_records(owner_addr)[0].record_id, "record-1")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
