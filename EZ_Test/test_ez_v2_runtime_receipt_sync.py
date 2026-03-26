from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from EZ_V2.chain import ChainStateV2, ReceiptCache
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2RuntimeReceiptSyncTests(unittest.TestCase):
    def test_runtime_sync_wallet_receipts_recovers_offline_sender(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            _, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            db_path = str(Path(tmpdir) / "alice.sqlite3")

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x99" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(300, 499))
            submission, context, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=75,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=81,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=5,
                tx_time=1,
            )

            runtime = V2Runtime(chain=ChainStateV2(chain_id=81))
            runtime.submit_bundle(submission)
            produced = runtime.produce_block(timestamp=2)
            self.assertEqual(produced.deliveries[alice_addr].error, "wallet_not_registered")
            self.assertEqual(len(wallet.list_pending_bundles()), 1)
            wallet.close()

            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x99" * 32, db_path=db_path)
            runtime.register_wallet(reopened, auto_confirm_receipts=False)
            sync_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(sync_results), 1)
            self.assertTrue(sync_results[0].applied)
            self.assertEqual(sync_results[0].seq, context.seq)
            self.assertEqual(runtime.get_receipt(alice_addr, 1).status, "ok")
            self.assertEqual(len(reopened.list_pending_bundles()), 0)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in reopened.list_records()),
                [
                    (300, 374, LocalValueStatus.ARCHIVED.value),
                    (375, 499, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )
            reopened.close()

    def test_runtime_sync_marks_pending_values_receipt_missing_until_receipt_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            _, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            db_path = str(Path(tmpdir) / "alice.sqlite3")

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xaa" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(300, 499))
            submission, context, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=75,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=82,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=15,
                tx_time=1,
            )

            runtime = V2Runtime(chain=ChainStateV2(chain_id=82))
            runtime.submit_bundle(submission)
            produced = runtime.produce_block(timestamp=2)
            self.assertEqual(produced.deliveries[alice_addr].error, "wallet_not_registered")
            runtime.chain.receipt_cache = ReceiptCache(max_blocks=32)
            wallet.close()

            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xaa" * 32, db_path=db_path)
            runtime.register_wallet(reopened, auto_confirm_receipts=False)
            missing_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(missing_results), 1)
            self.assertFalse(missing_results[0].applied)
            self.assertEqual(missing_results[0].error, "missing_receipt")
            self.assertEqual(missing_results[0].seq, context.seq)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in reopened.list_records()),
                [
                    (300, 374, LocalValueStatus.RECEIPT_MISSING.value),
                    (375, 499, LocalValueStatus.RECEIPT_MISSING.value),
                ],
            )

            bundle_ref = produced.block.diff_package.diff_entries[0].new_leaf.head_ref
            runtime.chain.receipt_cache.add(alice_addr, produced.receipts[alice_addr], bundle_ref)
            recovered_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(recovered_results), 1)
            self.assertTrue(recovered_results[0].applied)
            self.assertEqual(
                sorted((record.value.begin, record.value.end, record.local_status.value) for record in reopened.list_records()),
                [
                    (300, 374, LocalValueStatus.ARCHIVED.value),
                    (375, 499, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
