from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.types import Checkpoint
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessValueSelectionTests(unittest.TestCase):
    def test_flow_value_selection_prefers_exact_single_value_over_combination_or_split(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5501)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5501,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5501,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                exact_value = ValueRange(0, 99)
                half_1 = ValueRange(100, 149)
                half_2 = ValueRange(150, 199)
                splittable = ValueRange(200, 399)
                for minted in (exact_value, half_1, half_2, splittable):
                    consensus.register_genesis_value(alice.address, minted)
                    alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=1201)
                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(len(bob.received_transfers), 1)
                self.assertEqual(
                    (bob.received_transfers[0].value_begin, bob.received_transfers[0].value_end),
                    (exact_value.begin, exact_value.end),
                )

                archived = [
                    record
                    for record in alice.wallet.list_records()
                    if record.local_status == LocalValueStatus.ARCHIVED
                ]
                self.assertEqual([record.value for record in archived], [exact_value])
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_value_selection_prefers_exact_checkpoint_matched_value_over_non_checkpoint_peer_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5502,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5502,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5502,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5502,
                network=network,
                consensus_peer_id="consensus-0",
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=5502,
                network=network,
                consensus_peer_id="consensus-0",
            )
            erin = V2AccountHost(
                node_id="erin",
                endpoint="mem://erin",
                wallet_db_path=f"{td}/erin.sqlite3",
                chain_id=5502,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                checkpoint_value = ValueRange(0, 99)
                plain_peer_value = ValueRange(100, 199)
                consensus.register_genesis_value(alice.address, checkpoint_value)
                consensus.register_genesis_value(bob.address, plain_peer_value)
                alice.register_genesis_value(checkpoint_value)
                bob.register_genesis_value(plain_peer_value)

                a1 = alice.submit_payment("carol", amount=100, tx_time=1, anti_spam_nonce=1301)
                c1 = carol.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=1302)
                a2 = alice.submit_payment("dave", amount=100, tx_time=3, anti_spam_nonce=1303)
                self.assertEqual([a1.receipt_height, c1.receipt_height, a2.receipt_height], [1, 2, 3])

                archived_checkpoint_value = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == checkpoint_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                checkpoint = alice.wallet.create_exact_checkpoint(archived_checkpoint_value.record_id)
                self.assertTrue(checkpoint.matches(checkpoint_value, alice.address))

                d1 = dave.submit_payment("alice", amount=100, tx_time=4, anti_spam_nonce=1304)
                b1 = bob.submit_payment("alice", amount=100, tx_time=5, anti_spam_nonce=1305)
                self.assertEqual([d1.receipt_height, b1.receipt_height], [4, 5])

                outgoing = alice.submit_payment("erin", amount=100, tx_time=6, anti_spam_nonce=1306)
                self.assertEqual(outgoing.receipt_height, 6)
                self.assertEqual(len(erin.received_transfers), 1)
                self.assertEqual(
                    (erin.received_transfers[0].value_begin, erin.received_transfers[0].value_end),
                    (checkpoint_value.begin, checkpoint_value.end),
                )
            finally:
                erin.close()
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_value_selection_excludes_receipt_missing_and_locked_for_verification_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wallet_path = f"{td}/wallet.sqlite3"
            sender_priv, sender_pub = generate_secp256k1_keypair()
            sender_addr = address_from_public_key_pem(sender_pub)
            _, recipient_pub = generate_secp256k1_keypair()
            recipient_addr = address_from_public_key_pem(recipient_pub)

            wallet = WalletAccountV2(address=sender_addr, genesis_block_hash=b"\x55" * 32, db_path=wallet_path)
            blocked_exact = wallet.add_genesis_value(ValueRange(0, 99))
            combo_left = wallet.add_genesis_value(ValueRange(100, 149))
            combo_right = wallet.add_genesis_value(ValueRange(150, 199))
            locked_large = wallet.add_genesis_value(ValueRange(200, 399))
            wallet._persist_records(
                [
                    replace(blocked_exact, local_status=LocalValueStatus.RECEIPT_MISSING),
                    combo_left,
                    combo_right,
                    replace(locked_large, local_status=LocalValueStatus.LOCKED_FOR_VERIFICATION),
                ]
            )

            submission, _, tx = wallet.build_payment_bundle(
                recipient_addr=recipient_addr,
                amount=100,
                private_key_pem=sender_priv,
                public_key_pem=sender_pub,
                chain_id=5503,
                expiry_height=100,
                anti_spam_nonce=1401,
                tx_time=1,
            )
            self.assertEqual(submission.sidecar.tx_list[0], tx)
            self.assertEqual(tx.value_list, (ValueRange(100, 149), ValueRange(150, 199)))
            wallet.close()

    def test_value_selection_with_multiple_checkpoints_is_stable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wallet_path = f"{td}/wallet.sqlite3"
            sender_priv, sender_pub = generate_secp256k1_keypair()
            sender_addr = address_from_public_key_pem(sender_pub)
            _, recipient_pub = generate_secp256k1_keypair()
            recipient_addr = address_from_public_key_pem(recipient_pub)

            wallet = WalletAccountV2(address=sender_addr, genesis_block_hash=b"\x66" * 32, db_path=wallet_path)
            first = wallet.add_genesis_value(ValueRange(0, 49))
            second = wallet.add_genesis_value(ValueRange(50, 99))
            large = wallet.add_genesis_value(ValueRange(100, 199))

            for record in (first, second):
                wallet.db.save_checkpoint(
                    Checkpoint(
                        value_begin=record.value.begin,
                        value_end=record.value.end,
                        owner_addr=sender_addr,
                        checkpoint_height=1,
                        checkpoint_block_hash=b"\x01" * 32,
                        checkpoint_bundle_hash=(bytes([record.value.begin + 1]) * 32),
                    )
                )
            wallet._reload_state()

            first_pick = wallet.select_payment_ranges(50)
            wallet.close()

            reopened = WalletAccountV2(address=sender_addr, genesis_block_hash=b"\x66" * 32, db_path=wallet_path)
            second_pick = reopened.select_payment_ranges(50)
            submission, _, tx = reopened.build_payment_bundle(
                recipient_addr=recipient_addr,
                amount=50,
                private_key_pem=sender_priv,
                public_key_pem=sender_pub,
                chain_id=5504,
                expiry_height=100,
                anti_spam_nonce=1501,
                tx_time=1,
            )
            self.assertEqual(first_pick, (ValueRange(0, 49),))
            self.assertEqual(second_pick, (ValueRange(0, 49),))
            self.assertEqual(submission.sidecar.tx_list[0], tx)
            self.assertEqual(tx.value_list, (ValueRange(0, 49),))
            reopened.close()

    def test_value_selection_prefers_single_split_over_multi_input_combination_when_no_exact_match_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wallet_path = f"{td}/wallet.sqlite3"
            sender_priv, sender_pub = generate_secp256k1_keypair()
            sender_addr = address_from_public_key_pem(sender_pub)
            _, recipient_pub = generate_secp256k1_keypair()
            recipient_addr = address_from_public_key_pem(recipient_pub)

            wallet = WalletAccountV2(address=sender_addr, genesis_block_hash=b"\x77" * 32, db_path=wallet_path)
            wallet.add_genesis_value(ValueRange(0, 199))
            wallet.add_genesis_value(ValueRange(200, 249))
            wallet.add_genesis_value(ValueRange(250, 299))

            submission, _, tx = wallet.build_payment_bundle(
                recipient_addr=recipient_addr,
                amount=100,
                private_key_pem=sender_priv,
                public_key_pem=sender_pub,
                chain_id=5505,
                expiry_height=100,
                anti_spam_nonce=1601,
                tx_time=1,
            )
            self.assertEqual(submission.sidecar.tx_list[0], tx)
            self.assertEqual(tx.value_list, (ValueRange(0, 99),))
            pending = sorted((record.value.begin, record.value.end) for record in wallet.list_records())
            self.assertIn((0, 99), pending)
            self.assertNotIn((200, 249), tx.value_list)
            wallet.close()

    def test_value_selection_does_not_sacrifice_recipient_segment_count_only_to_use_checkpoint_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wallet_path = f"{td}/wallet.sqlite3"
            sender_priv, sender_pub = generate_secp256k1_keypair()
            sender_addr = address_from_public_key_pem(sender_pub)
            _, recipient_pub = generate_secp256k1_keypair()
            recipient_addr = address_from_public_key_pem(recipient_pub)

            wallet = WalletAccountV2(address=sender_addr, genesis_block_hash=b"\x88" * 32, db_path=wallet_path)
            cp_left = wallet.add_genesis_value(ValueRange(0, 49))
            cp_right = wallet.add_genesis_value(ValueRange(50, 99))
            large_plain = wallet.add_genesis_value(ValueRange(100, 299))
            wallet.db.save_checkpoint(
                Checkpoint(
                    value_begin=cp_left.value.begin,
                    value_end=cp_left.value.end,
                    owner_addr=sender_addr,
                    checkpoint_height=1,
                    checkpoint_block_hash=b"\x02" * 32,
                    checkpoint_bundle_hash=b"\x12" * 32,
                )
            )
            wallet.db.save_checkpoint(
                Checkpoint(
                    value_begin=cp_right.value.begin,
                    value_end=cp_right.value.end,
                    owner_addr=sender_addr,
                    checkpoint_height=1,
                    checkpoint_block_hash=b"\x03" * 32,
                    checkpoint_bundle_hash=b"\x13" * 32,
                )
            )
            wallet._reload_state()

            selection = wallet.select_payment_ranges(100)
            submission, _, tx = wallet.build_payment_bundle(
                recipient_addr=recipient_addr,
                amount=100,
                private_key_pem=sender_priv,
                public_key_pem=sender_pub,
                chain_id=5506,
                expiry_height=100,
                anti_spam_nonce=1701,
                tx_time=1,
            )
            self.assertEqual(selection, (ValueRange(100, 199),))
            self.assertEqual(submission.sidecar.tx_list[0], tx)
            self.assertEqual(tx.value_list, (ValueRange(100, 199),))
            wallet.close()


if __name__ == "__main__":
    unittest.main()
