from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from EZ_V2.chain import ChainStateV2, compute_bundle_hash, confirmed_ref
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.types import OffChainTx
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.validator import V2TransferValidator, ValidationContext
from EZ_V2.wallet import WalletAccountV2


class EZV2WalletStorageTests(unittest.TestCase):
    def test_build_bundle_persists_pending_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x55" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(0, 199))

            tx = OffChainTx(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value_list=(ValueRange(0, 49),),
                tx_local_index=0,
                tx_time=1,
            )
            submission, context = wallet.build_bundle(
                tx_list=(tx,),
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=31,
                seq=1,
                expiry_height=10,
                fee=1,
                anti_spam_nonce=7,
            )
            self.assertEqual(context.bundle_hash, compute_bundle_hash(submission.sidecar))
            self.assertEqual(len(wallet.list_pending_bundles()), 1)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in wallet.list_records()),
                [
                    (0, 49, LocalValueStatus.PENDING_BUNDLE.value),
                    (50, 199, LocalValueStatus.PENDING_BUNDLE.value),
                ],
            )
            self.assertIsNotNone(wallet.db.get_sidecar(context.bundle_hash))
            wallet.close()

            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x55" * 32, db_path=db_path)
            self.assertEqual(len(reopened.list_pending_bundles()), 1)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in reopened.list_records()),
                [
                    (0, 49, LocalValueStatus.PENDING_BUNDLE.value),
                    (50, 199, LocalValueStatus.PENDING_BUNDLE.value),
                ],
            )
            reopened.close()

    def test_receipt_confirmation_persists_records_and_exports_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            chain = ChainStateV2(chain_id=41)
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x66" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(300, 599))
            wallet.add_genesis_value(ValueRange(600, 699))

            tx = OffChainTx(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value_list=(ValueRange(300, 349),),
                tx_local_index=0,
                tx_time=1,
            )
            submission, _ = wallet.build_bundle(
                tx_list=(tx,),
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=41,
                seq=1,
                expiry_height=10,
                fee=1,
                anti_spam_nonce=1,
            )
            chain.submit_bundle(submission)
            _, receipts = chain.build_block(timestamp=1)
            confirmed_unit = wallet.on_receipt_confirmed(receipts[alice_addr])

            archived = next(record for record in wallet.list_records() if record.value == ValueRange(300, 349))
            retained = next(record for record in wallet.list_records() if record.value == ValueRange(350, 599))
            untouched = next(record for record in wallet.list_records() if record.value == ValueRange(600, 699))
            self.assertEqual(archived.local_status, LocalValueStatus.ARCHIVED)
            self.assertEqual(retained.local_status, LocalValueStatus.VERIFIED_SPENDABLE)
            self.assertEqual(untouched.local_status, LocalValueStatus.VERIFIED_SPENDABLE)
            self.assertEqual([unit.receipt.seq for unit in archived.witness_v2.confirmed_bundle_chain], [1])
            self.assertEqual([unit.receipt.seq for unit in retained.witness_v2.confirmed_bundle_chain], [1])
            self.assertEqual([unit.receipt.seq for unit in untouched.witness_v2.confirmed_bundle_chain], [1])

            package = wallet.export_transfer_package(tx, ValueRange(300, 349))
            self.assertEqual(package.target_value, ValueRange(300, 349))
            self.assertEqual(package.witness_v2.current_owner_addr, alice_addr)
            self.assertEqual(wallet.db.get_receipt(alice_addr, 1).seq, 1)
            self.assertEqual(wallet.db.get_receipt_by_ref(confirmed_ref(confirmed_unit)).seq, 1)

            wallet.close()
            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x66" * 32, db_path=db_path)
            archived_reopened = next(record for record in reopened.list_records() if record.value == ValueRange(300, 349))
            self.assertEqual(archived_reopened.local_status, LocalValueStatus.ARCHIVED)
            self.assertEqual(reopened.db.get_receipt(alice_addr, 1).seq, 1)
            reopened.close()

    def test_rollback_and_sidecar_gc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x77" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(0, 99))

            tx = OffChainTx(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value_list=(ValueRange(0, 49),),
                tx_local_index=0,
                tx_time=1,
            )
            submission, context = wallet.build_bundle(
                tx_list=(tx,),
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=51,
                seq=1,
                expiry_height=10,
                fee=1,
                anti_spam_nonce=9,
            )
            self.assertEqual(wallet.gc_unused_sidecars(), 0)
            rolled_back = wallet.rollback_pending_bundle(1)
            self.assertEqual(rolled_back.bundle_hash, context.bundle_hash)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in wallet.list_records()),
                [
                    (0, 49, LocalValueStatus.VERIFIED_SPENDABLE.value),
                    (50, 99, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )
            removed = wallet.gc_unused_sidecars()
            self.assertGreaterEqual(removed, 1)
            self.assertIsNone(wallet.db.get_sidecar(compute_bundle_hash(submission.sidecar)))
            wallet.close()

    def test_receipt_confirmation_rejects_broken_prev_ref_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "wallet.sqlite3")
            chain = ChainStateV2(chain_id=61)
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x78" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(0, 199))

            tx1 = OffChainTx(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value_list=(ValueRange(0, 49),),
                tx_local_index=0,
                tx_time=1,
            )
            submission1, _ = wallet.build_bundle(
                tx_list=(tx1,),
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=61,
                seq=1,
                expiry_height=10,
                fee=1,
                anti_spam_nonce=1,
            )
            chain.submit_bundle(submission1)
            _, receipts1 = chain.build_block(timestamp=1)
            wallet.on_receipt_confirmed(receipts1[alice_addr])

            tx2 = OffChainTx(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value_list=(ValueRange(50, 99),),
                tx_local_index=0,
                tx_time=2,
            )
            submission2, _ = wallet.build_bundle(
                tx_list=(tx2,),
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=61,
                seq=2,
                expiry_height=20,
                fee=1,
                anti_spam_nonce=2,
            )
            chain.submit_bundle(submission2)
            _, receipts2 = chain.build_block(timestamp=2)
            forged_receipt = replace(receipts2[alice_addr], prev_ref=None)

            with self.assertRaisesRegex(ValueError, "receipt prev_ref mismatch"):
                wallet.on_receipt_confirmed(forged_receipt)

            self.assertEqual(len(wallet.list_pending_bundles()), 1)
            wallet.close()


if __name__ == "__main__":
    unittest.main()
