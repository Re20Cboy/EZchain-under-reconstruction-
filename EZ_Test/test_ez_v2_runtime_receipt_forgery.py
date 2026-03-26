from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from EZ_V2.chain import ChainStateV2
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.types import BundleRef, SparseMerkleProof
from EZ_V2.values import ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2RuntimeReceiptForgeryTests(unittest.TestCase):
    def test_runtime_sync_rejects_forged_receipt_in_sender_recovery_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            _, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            db_path = str(Path(tmpdir) / "alice.sqlite3")

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xbb" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(0, 199))
            submission, context, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=101,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=17,
                tx_time=1,
            )

            runtime = V2Runtime(chain=ChainStateV2(chain_id=101))
            runtime.submit_bundle(submission)
            produced = runtime.produce_block(timestamp=2)
            self.assertEqual(produced.deliveries[alice_addr].error, "wallet_not_registered")
            self.assertEqual(len(wallet.list_pending_bundles()), 1)

            forged_receipt = replace(
                produced.receipts[alice_addr],
                prev_ref=BundleRef(height=99, block_hash=b"\x01" * 32, bundle_hash=b"\x02" * 32, seq=1),
            )
            bundle_ref = produced.block.diff_package.diff_entries[0].new_leaf.head_ref
            runtime.chain.receipt_cache.add(alice_addr, forged_receipt, bundle_ref)

            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xbb" * 32, db_path=db_path)
            runtime.register_wallet(reopened, auto_confirm_receipts=False)
            sync_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(sync_results), 1)
            self.assertFalse(sync_results[0].applied)
            self.assertEqual(sync_results[0].error, "receipt prev_ref mismatch")
            self.assertEqual(sync_results[0].seq, context.seq)
            self.assertEqual(len(reopened.list_pending_bundles()), 1)
            reopened.close()

    def test_runtime_sync_rejects_forged_receipt_with_tampered_state_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            _, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            db_path = str(Path(tmpdir) / "alice.sqlite3")

            wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xbc" * 32, db_path=db_path)
            wallet.add_genesis_value(ValueRange(0, 199))
            submission, context, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=102,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=18,
                tx_time=1,
            )

            runtime = V2Runtime(chain=ChainStateV2(chain_id=102))
            runtime.submit_bundle(submission)
            produced = runtime.produce_block(timestamp=2)
            self.assertEqual(produced.deliveries[alice_addr].error, "wallet_not_registered")
            self.assertEqual(len(wallet.list_pending_bundles()), 1)

            forged_receipt = replace(
                produced.receipts[alice_addr],
                account_state_proof=SparseMerkleProof(
                    siblings=tuple(b"\xff" * 32 for _ in produced.receipts[alice_addr].account_state_proof.siblings),
                    existence=produced.receipts[alice_addr].account_state_proof.existence,
                ),
            )
            bundle_ref = produced.block.diff_package.diff_entries[0].new_leaf.head_ref
            runtime.chain.receipt_cache.add(alice_addr, forged_receipt, bundle_ref)

            reopened = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\xbc" * 32, db_path=db_path)
            runtime.register_wallet(reopened, auto_confirm_receipts=False)
            sync_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(sync_results), 1)
            self.assertFalse(sync_results[0].applied)
            self.assertEqual(sync_results[0].error, "receipt account state proof does not verify")
            self.assertEqual(sync_results[0].seq, context.seq)
            self.assertEqual(len(reopened.list_pending_bundles()), 1)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
