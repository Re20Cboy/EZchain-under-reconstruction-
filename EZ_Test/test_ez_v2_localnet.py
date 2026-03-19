from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from EZ_V2.chain import compute_bundle_hash
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.localnet import V2ConsensusNode, V2LocalNetwork
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2LocalnetTests(unittest.TestCase):
    def test_consensus_node_restores_receipt_queries_and_offline_sync_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            genesis_block_hash = b"\xcc" * 32
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=genesis_block_hash,
                db_path=str(Path(tmpdir) / "alice.sqlite3"),
            )
            wallet.add_genesis_value(ValueRange(0, 119))

            node = V2ConsensusNode(
                store_path=str(Path(tmpdir) / "consensus.sqlite3"),
                chain_id=131,
                genesis_block_hash=genesis_block_hash,
            )
            node.register_wallet(wallet, auto_confirm_receipts=False)

            submission, context, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=30,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=131,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=21,
                tx_time=1,
            )
            node.submit_bundle(submission)
            produced = node.produce_block(timestamp=2)
            bundle_ref = produced.block.diff_package.diff_entries[0].new_leaf.head_ref

            self.assertEqual(produced.deliveries[alice_addr].error, "auto_confirm_disabled")
            self.assertEqual(node.get_receipt(alice_addr, 1).status, "ok")
            self.assertEqual(node.get_receipt_by_ref(bundle_ref).status, "ok")
            self.assertEqual(len(wallet.list_pending_bundles()), 1)
            node.close()

            reopened = V2ConsensusNode(
                store_path=str(Path(tmpdir) / "consensus.sqlite3"),
                chain_id=131,
                genesis_block_hash=genesis_block_hash,
            )
            reopened.register_wallet(wallet, auto_confirm_receipts=False)

            self.assertEqual(reopened.chain.current_height, 1)
            self.assertEqual(reopened.chain.current_block_hash, produced.block.block_hash)
            self.assertEqual(reopened.get_receipt(alice_addr, context.seq).status, "ok")
            self.assertEqual(reopened.get_receipt_by_ref(bundle_ref).status, "ok")

            sync_results = reopened.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(sync_results), 1)
            self.assertTrue(sync_results[0].applied)
            self.assertEqual(len(wallet.list_pending_bundles()), 0)

            records = sorted(
                (record.value.begin, record.value.end, record.local_status.value)
                for record in wallet.list_records()
            )
            self.assertEqual(
                records,
                [
                    (0, 29, LocalValueStatus.ARCHIVED.value),
                    (30, 119, LocalValueStatus.VERIFIED_SPENDABLE.value),
                ],
            )
            reopened.close()
            wallet.close()

    def test_localnet_supports_restart_and_continuous_respend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=141,
                genesis_block_hash=b"\xdd" * 32,
            )
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                carol = net.add_account("carol")

                net.allocate_genesis_value("alice", ValueRange(0, 199))

                alice_payment = alice.submit_payment(
                    bob.address,
                    amount=50,
                    fee=1,
                    tx_time=1,
                )
                alice_block = net.produce_block(timestamp=2)
                self.assertTrue(alice_block.deliveries[alice.address].applied)

                bob_receive = alice.deliver_outgoing_transfer(
                    alice_payment.target_tx,
                    ValueRange(0, 49),
                    recipient_addr=bob.address,
                )
                self.assertTrue(bob_receive.accepted, bob_receive.error)

                net.restart_consensus()
                self.assertEqual(net.consensus.chain.current_height, 1)

                bob_payment = bob.submit_payment(
                    carol.address,
                    amount=20,
                    fee=1,
                    tx_time=3,
                )
                bob_block = net.produce_block(timestamp=4)
                self.assertTrue(bob_block.deliveries[bob.address].applied)

                carol_receive = bob.deliver_outgoing_transfer(
                    bob_payment.target_tx,
                    ValueRange(0, 19),
                    recipient_addr=carol.address,
                )
                self.assertTrue(carol_receive.accepted, carol_receive.error)
                self.assertEqual(carol_receive.record.value, ValueRange(0, 19))

                receipt = net.consensus.get_receipt(bob.address, 1)
                self.assertEqual(receipt.status, "ok")
                carol_records = sorted(
                    (record.value.begin, record.value.end, record.local_status.value)
                    for record in carol.wallet.list_records()
                )
                self.assertEqual(
                    carol_records,
                    [(0, 19, LocalValueStatus.VERIFIED_SPENDABLE.value)],
                )
            finally:
                net.close()

    def test_duplicate_transfer_delivery_is_rejected_without_double_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=151,
                genesis_block_hash=b"\xee" * 32,
            )
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                net.allocate_genesis_value("alice", ValueRange(0, 99))

                payment = alice.submit_payment(
                    bob.address,
                    amount=30,
                    fee=1,
                    tx_time=1,
                )
                net.produce_block(timestamp=2)

                first_delivery = alice.deliver_outgoing_transfer(
                    payment.target_tx,
                    ValueRange(0, 29),
                    recipient_addr=bob.address,
                )
                self.assertTrue(first_delivery.accepted, first_delivery.error)

                incoming_bundle_hash = compute_bundle_hash(payment.submission.sidecar)
                self.assertIsNotNone(bob.wallet.db.get_sidecar(incoming_bundle_hash))

                second_delivery = alice.deliver_outgoing_transfer(
                    payment.target_tx,
                    ValueRange(0, 29),
                    recipient_addr=bob.address,
                )
                self.assertFalse(second_delivery.accepted)
                self.assertEqual(second_delivery.error, "transfer package already accepted")

                bob_records = sorted(
                    (record.value.begin, record.value.end, record.local_status.value)
                    for record in bob.wallet.list_records()
                )
                self.assertEqual(
                    bob_records,
                    [(0, 29, LocalValueStatus.VERIFIED_SPENDABLE.value)],
                )
            finally:
                net.close()

    def test_receipt_window_prunes_old_receipts_and_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=161,
                receipt_cache_blocks=2,
                genesis_block_hash=b"\xef" * 32,
            )
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                carol = net.add_account("carol")
                dave = net.add_account("dave")
                net.allocate_genesis_value("alice", ValueRange(0, 199))

                alice.submit_payment(bob.address, amount=20, fee=1, tx_time=1)
                net.produce_block(timestamp=2)
                alice.submit_payment(carol.address, amount=20, fee=1, tx_time=3)
                net.produce_block(timestamp=4)
                alice.submit_payment(dave.address, amount=20, fee=1, tx_time=5)
                net.produce_block(timestamp=6)

                self.assertEqual(net.consensus.chain.current_height, 3)
                self.assertEqual(net.consensus.get_receipt(alice.address, 1).status, "missing")
                self.assertEqual(net.consensus.get_receipt(alice.address, 2).status, "ok")
                self.assertEqual(net.consensus.get_receipt(alice.address, 3).status, "ok")

                net.restart_consensus()
                self.assertEqual(net.consensus.chain.current_height, 3)
                self.assertEqual(net.consensus.get_receipt(alice.address, 1).status, "missing")
                self.assertEqual(net.consensus.get_receipt(alice.address, 2).status, "ok")
                self.assertEqual(net.consensus.get_receipt(alice.address, 3).status, "ok")
            finally:
                net.close()


if __name__ == "__main__":
    unittest.main()
