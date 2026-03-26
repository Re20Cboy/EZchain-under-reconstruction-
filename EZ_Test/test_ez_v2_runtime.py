from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from EZ_V2.chain import ChainStateV2, confirmed_ref
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2RuntimeTests(unittest.TestCase):
    def test_runtime_auto_confirms_registered_sender_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            wallet = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\x88" * 32,
                db_path=str(Path(tmpdir) / "alice.sqlite3"),
            )
            wallet.add_genesis_value(ValueRange(0, 199))

            runtime = V2Runtime(chain=ChainStateV2(chain_id=71))
            runtime.register_wallet(wallet)

            submission, _, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=71,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=9,
                tx_time=1,
            )
            submit_result = runtime.submit_bundle(submission)
            self.assertEqual(submit_result.sender_addr, alice_addr)
            self.assertEqual(submit_result.seq, 1)

            block_result = runtime.produce_block(timestamp=2)
            self.assertEqual(block_result.block.header.height, 1)
            self.assertIn(alice_addr, block_result.receipts)
            self.assertTrue(block_result.deliveries[alice_addr].applied)
            self.assertIsNotNone(wallet.db.get_receipt(alice_addr, 1))
            self.assertEqual(runtime.get_receipt(alice_addr, 1).status, "ok")
            self.assertEqual(
                runtime.get_receipt_by_ref(confirmed_ref(block_result.deliveries[alice_addr].confirmed_unit)).status,
                "ok",
            )

            records = sorted(
                (record.value.begin, record.value.end, record.local_status.value)
                for record in wallet.list_records()
            )
            self.assertEqual(
                records,
                [
                    (0, 49, LocalValueStatus.ARCHIVED.value),
                    (50, 199, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )
            wallet.close()

    def test_runtime_delivers_transfer_package_and_recipient_can_respend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)
            carol_priv, carol_pub = generate_secp256k1_keypair()
            carol_addr = address_from_public_key_pem(carol_pub)

            alice_wallet = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\xaa" * 32,
                db_path=str(Path(tmpdir) / "alice.sqlite3"),
            )
            bob_wallet = WalletAccountV2(
                address=bob_addr,
                genesis_block_hash=b"\xaa" * 32,
                db_path=str(Path(tmpdir) / "bob.sqlite3"),
            )
            alice_wallet.add_genesis_value(ValueRange(0, 199))

            runtime = V2Runtime(chain=ChainStateV2(chain_id=91))
            runtime.register_wallet(alice_wallet)
            runtime.register_wallet(bob_wallet)

            submission, _, tx = alice_wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=91,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=11,
                tx_time=1,
            )
            runtime.submit_bundle(submission)
            produced = runtime.produce_block(timestamp=2)
            self.assertTrue(produced.deliveries[alice_addr].applied)

            package = alice_wallet.export_transfer_package(tx, ValueRange(0, 49))
            delivery = runtime.deliver_transfer_package(package)
            self.assertTrue(delivery.accepted, delivery.error)
            self.assertEqual(delivery.recipient_addr, bob_addr)
            self.assertIsNotNone(delivery.record)
            self.assertEqual(delivery.record.value, ValueRange(0, 49))
            self.assertEqual(delivery.record.witness_v2.current_owner_addr, bob_addr)
            self.assertEqual(delivery.record.local_status, LocalValueStatus.VERIFIED_SPENDABLE)

            bob_records = sorted(
                (record.value.begin, record.value.end, record.local_status.value)
                for record in bob_wallet.list_records()
            )
            self.assertEqual(
                bob_records,
                [
                    (0, 49, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )

            bob_submission, _, bob_tx = bob_wallet.build_payment_bundle(
                recipient_addr=carol_addr,
                amount=20,
                private_key_pem=bob_priv,
                public_key_pem=bob_pub,
                chain_id=91,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=12,
                tx_time=3,
            )
            self.assertEqual(bob_tx.value_list, (ValueRange(0, 19),))
            runtime.submit_bundle(bob_submission)
            bob_block = runtime.produce_block(timestamp=4)
            self.assertTrue(bob_block.deliveries[bob_addr].applied)
            alice_wallet.close()
            bob_wallet.close()


if __name__ == "__main__":
    unittest.main()
