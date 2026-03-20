from __future__ import annotations

import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from EZ_V2.chain import ChainStateV2, sign_bundle_envelope
from EZ_V2.chain import compute_bundle_hash
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.localnet import V2ConsensusNode, V2LocalNetwork
from EZ_V2.types import SparseMerkleProof
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

    def test_multi_round_cyclic_transfers_preserve_total_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=171,
                genesis_block_hash=b"\xf1" * 32,
            )
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                carol = net.add_account("carol")

                net.allocate_genesis_value("alice", ValueRange(0, 119))
                net.allocate_genesis_value("bob", ValueRange(120, 239))
                net.allocate_genesis_value("carol", ValueRange(240, 359))

                initial_total = sum(node.wallet.total_balance() for node in (alice, bob, carol))
                self.assertEqual(initial_total, 360)

                participants = (alice, bob, carol)
                for round_index in range(6):
                    sender = participants[round_index % 3]
                    recipient = participants[(round_index + 1) % 3]
                    payment = sender.submit_payment(
                        recipient.address,
                        amount=20,
                        fee=1,
                        tx_time=round_index + 1,
                    )
                    produced = net.produce_block(timestamp=round_index + 100)
                    self.assertTrue(produced.deliveries[sender.address].applied)
                    delivered = sender.deliver_outgoing_transfer(
                        payment.target_tx,
                        payment.target_tx.value_list[0],
                        recipient_addr=recipient.address,
                    )
                    self.assertTrue(delivered.accepted, delivered.error)

                final_total = sum(node.wallet.total_balance() for node in (alice, bob, carol))
                self.assertEqual(final_total, initial_total)
                for node in (alice, bob, carol):
                    self.assertGreaterEqual(node.wallet.available_balance(), 100)
            finally:
                net.close()

    def test_conflicting_bundle_submission_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\xf2" * 32,
                db_path=str(Path(tmpdir) / "alice.sqlite3"),
            )
            wallet.add_genesis_value(ValueRange(0, 199))

            chain = ChainStateV2(chain_id=181)
            submission, _, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=181,
                expiry_height=100,
                fee=5,
                anti_spam_nonce=1,
                tx_time=1,
            )
            chain.submit_bundle(submission)

            lower_fee_envelope = replace(submission.envelope, fee=4, sig=b"")
            lower_fee_envelope = sign_bundle_envelope(lower_fee_envelope, alice_priv)
            lower_fee_submission = replace(submission, envelope=lower_fee_envelope)
            with self.assertRaisesRegex(ValueError, "replacement bundle fee too low"):
                chain.submit_bundle(lower_fee_submission)

            future_seq_envelope = replace(submission.envelope, seq=2, sig=b"")
            future_seq_envelope = sign_bundle_envelope(future_seq_envelope, alice_priv)
            future_seq_submission = replace(submission, envelope=future_seq_envelope)
            with self.assertRaisesRegex(ValueError, "bundle seq is not currently executable"):
                chain.submit_bundle(future_seq_submission)

            wallet.close()

    def test_apply_block_rejects_sender_public_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alice_priv, alice_pub = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_pub)
            bob_priv, bob_pub = generate_secp256k1_keypair()
            bob_addr = address_from_public_key_pem(bob_pub)

            wallet = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\xf3" * 32,
                db_path=str(Path(tmpdir) / "alice.sqlite3"),
            )
            wallet.add_genesis_value(ValueRange(0, 99))

            chain_a = ChainStateV2(chain_id=191)
            chain_b = ChainStateV2(chain_id=191)
            submission, _, _ = wallet.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=20,
                private_key_pem=alice_priv,
                public_key_pem=alice_pub,
                chain_id=191,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=8,
                tx_time=1,
            )
            chain_a.submit_bundle(submission)
            valid_block, _ = chain_a.build_block(timestamp=2)

            tampered_block = replace(
                valid_block,
                diff_package=replace(
                    valid_block.diff_package,
                    sender_public_keys=(bob_pub,),
                ),
            )
            with self.assertRaisesRegex(ValueError, "sender/public key mismatch"):
                chain_b.apply_block(tampered_block)

            wallet.close()

    def test_tampered_transfer_package_cannot_redirect_or_expand_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=201,
                genesis_block_hash=b"\xf4" * 32,
            )
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                carol = net.add_account("carol")
                net.allocate_genesis_value("alice", ValueRange(0, 99))

                payment = alice.submit_payment(
                    bob.address,
                    amount=30,
                    fee=1,
                    tx_time=1,
                )
                net.produce_block(timestamp=2)
                package = alice.export_transfer_package(payment.target_tx, ValueRange(0, 29))

                redirect_attempt = net.consensus.deliver_transfer_package(
                    package,
                    recipient_addr=carol.address,
                )
                self.assertFalse(redirect_attempt.accepted)
                self.assertEqual(redirect_attempt.error, "target recipient mismatch")

                oversized_package = replace(package, target_value=ValueRange(0, 39))
                forged_delivery = bob.receive_transfer_package(oversized_package)
                self.assertFalse(forged_delivery.accepted)
                self.assertEqual(forged_delivery.error, "target value is not covered by target tx")

                self.assertEqual(len(carol.wallet.list_records()), 0)
                self.assertEqual(len(bob.wallet.list_records()), 0)
            finally:
                net.close()

    def test_sender_cannot_respend_until_withheld_receipt_is_synced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=211,
                auto_confirm_registered_wallets=False,
                genesis_block_hash=b"\xf5" * 32,
            )
            try:
                alice = net.add_account("alice", auto_confirm_receipts=False)
                bob = net.add_account("bob")
                carol = net.add_account("carol")
                net.allocate_genesis_value("alice", ValueRange(0, 99))

                first_payment = alice.submit_payment(
                    bob.address,
                    amount=20,
                    fee=1,
                    tx_time=1,
                )
                produced = net.produce_block(timestamp=2)
                self.assertEqual(produced.deliveries[alice.address].error, "auto_confirm_disabled")
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                with self.assertRaisesRegex(ValueError, "wallet already has a pending bundle|insufficient_balance"):
                    alice.submit_payment(
                        carol.address,
                        amount=10,
                        fee=1,
                        tx_time=3,
                    )

                sync_results = alice.sync_receipts()
                self.assertEqual(len(sync_results), 1)
                self.assertTrue(sync_results[0].applied)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)

                delivered = alice.deliver_outgoing_transfer(
                    first_payment.target_tx,
                    first_payment.target_tx.value_list[0],
                    recipient_addr=bob.address,
                )
                self.assertTrue(delivered.accepted, delivered.error)

                second_payment = alice.submit_payment(
                    carol.address,
                    amount=10,
                    fee=1,
                    tx_time=4,
                )
                produced_second = net.produce_block(timestamp=5)
                self.assertEqual(produced_second.deliveries[alice.address].error, "auto_confirm_disabled")
                alice.sync_receipts()
                delivered_second = alice.deliver_outgoing_transfer(
                    second_payment.target_tx,
                    second_payment.target_tx.value_list[0],
                    recipient_addr=carol.address,
                )
                self.assertTrue(delivered_second.accepted, delivered_second.error)
            finally:
                net.close()

    def test_long_randomized_multi_account_flow_preserves_total_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=221,
                genesis_block_hash=b"\xf6" * 32,
            )
            try:
                names = ("alice", "bob", "carol", "dave")
                participants = {name: net.add_account(name) for name in names}
                for index, name in enumerate(names):
                    begin = index * 100
                    net.allocate_genesis_value(name, ValueRange(begin, begin + 99))

                rng = random.Random(221)
                initial_total = sum(node.wallet.total_balance() for node in participants.values())
                self.assertEqual(initial_total, 400)

                completed_transfers = 0
                for round_index in range(24):
                    senders = [node for node in participants.values() if node.wallet.available_balance() >= 5]
                    self.assertTrue(senders)
                    sender = rng.choice(senders)
                    recipients = [node for node in participants.values() if node.address != sender.address]
                    recipient = rng.choice(recipients)
                    max_amount = min(15, sender.wallet.available_balance())
                    amount = rng.randint(5, max_amount)

                    payment = sender.submit_payment(
                        recipient.address,
                        amount=amount,
                        fee=1,
                        tx_time=round_index + 1,
                    )
                    produced = net.produce_block(timestamp=round_index + 1000)
                    self.assertTrue(produced.deliveries[sender.address].applied)

                    for target_value in payment.target_tx.value_list:
                        delivered = sender.deliver_outgoing_transfer(
                            payment.target_tx,
                            target_value,
                            recipient_addr=recipient.address,
                        )
                        self.assertTrue(delivered.accepted, delivered.error)
                    completed_transfers += 1

                self.assertEqual(completed_transfers, 24)
                final_total = sum(node.wallet.total_balance() for node in participants.values())
                self.assertEqual(final_total, initial_total)
                for node in participants.values():
                    self.assertEqual(len(node.wallet.list_pending_bundles()), 0)
                    self.assertEqual(
                        node.wallet.total_balance(),
                        sum(record.value.size for record in node.wallet.list_records() if record.local_status != LocalValueStatus.ARCHIVED),
                    )
            finally:
                net.close()

    def test_honest_nodes_match_global_expected_balances_under_repeated_package_attacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=231,
                genesis_block_hash=b"\xf7" * 32,
            )
            try:
                honest_names = ("alice", "bob", "carol")
                participants = {name: net.add_account(name) for name in honest_names}
                for index, name in enumerate(honest_names):
                    begin = index * 100
                    net.allocate_genesis_value(name, ValueRange(begin, begin + 99))

                expected_balances = {name: 100 for name in honest_names}
                initial_honest_total = sum(expected_balances.values())
                rng = random.Random(231)

                for round_index in range(12):
                    senders = [
                        name for name, node in participants.items() if node.wallet.available_balance() >= 5
                    ]
                    self.assertTrue(senders)
                    sender_name = rng.choice(senders)
                    recipient_candidates = [name for name in honest_names if name != sender_name]
                    recipient_name = rng.choice(recipient_candidates)
                    attacker_name = next(
                        name for name in honest_names if name not in {sender_name, recipient_name}
                    )

                    sender = participants[sender_name]
                    recipient = participants[recipient_name]
                    attacker = participants[attacker_name]
                    max_amount = min(15, sender.wallet.available_balance())
                    amount = rng.randint(5, max_amount)

                    payment = sender.submit_payment(
                        recipient.address,
                        amount=amount,
                        fee=1,
                        tx_time=round_index + 1,
                    )
                    produced = net.produce_block(timestamp=round_index + 2000)
                    self.assertTrue(produced.deliveries[sender.address].applied)

                    for target_value in payment.target_tx.value_list:
                        package = sender.export_transfer_package(payment.target_tx, target_value)

                        redirect_attempt = attacker.receive_transfer_package(
                            replace(
                                package,
                                target_tx=replace(package.target_tx, recipient_addr=attacker.address),
                            )
                        )
                        self.assertFalse(redirect_attempt.accepted)
                        self.assertIn(
                            redirect_attempt.error,
                            {
                                "target tx must exist exactly once in latest bundle",
                                "prior witness current owner mismatch",
                            },
                        )

                        oversized_attempt = recipient.receive_transfer_package(
                            replace(
                                package,
                                target_value=ValueRange(target_value.begin, target_value.end + 7),
                            )
                        )
                        self.assertFalse(oversized_attempt.accepted)
                        self.assertEqual(oversized_attempt.error, "target value is not covered by target tx")

                        delivered = recipient.receive_transfer_package(package)
                        self.assertTrue(delivered.accepted, delivered.error)

                    expected_balances[sender_name] -= amount
                    expected_balances[recipient_name] += amount

                    honest_view = {
                        name: participants[name].wallet.available_balance()
                        for name in honest_names
                    }
                    self.assertEqual(honest_view, expected_balances)
                    self.assertEqual(sum(honest_view.values()), initial_honest_total)
                    for name, node in participants.items():
                        self.assertEqual(len(node.wallet.list_pending_bundles()), 0)
                        self.assertEqual(
                            node.wallet.available_balance(),
                            sum(
                                record.value.size
                                for record in node.wallet.list_records()
                                if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
                            ),
                        )
            finally:
                net.close()

    def test_long_mixed_attack_run_preserves_honest_global_ledger_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=241,
                genesis_block_hash=b"\xf8" * 32,
            )
            try:
                honest_names = ("alice", "bob", "carol")
                honest_nodes = {name: net.add_account(name) for name in honest_names}
                mallory = net.add_account("mallory")
                for index, name in enumerate(honest_names):
                    begin = index * 100
                    net.allocate_genesis_value(name, ValueRange(begin, begin + 99))

                expected_balances = {name: 100 for name in honest_names}
                initial_honest_total = sum(expected_balances.values())
                rng = random.Random(241)

                for round_index in range(20):
                    senders = [
                        name for name, node in honest_nodes.items() if node.wallet.available_balance() >= 5
                    ]
                    self.assertTrue(senders)
                    sender_name = rng.choice(senders)
                    recipient_name = rng.choice([name for name in honest_names if name != sender_name])
                    sender = honest_nodes[sender_name]
                    recipient = honest_nodes[recipient_name]
                    max_amount = min(15, sender.wallet.available_balance())
                    amount = rng.randint(5, max_amount)

                    payment = sender.submit_payment(
                        recipient.address,
                        amount=amount,
                        fee=1,
                        tx_time=round_index + 1,
                    )
                    produced = net.produce_block(timestamp=round_index + 3000)
                    self.assertTrue(produced.deliveries[sender.address].applied)

                    for target_value in payment.target_tx.value_list:
                        package = sender.export_transfer_package(payment.target_tx, target_value)

                        forged_redirect = mallory.receive_transfer_package(
                            replace(
                                package,
                                target_tx=replace(package.target_tx, recipient_addr=mallory.address),
                            )
                        )
                        self.assertFalse(forged_redirect.accepted)
                        self.assertIn(
                            forged_redirect.error,
                            {
                                "target tx must exist exactly once in latest bundle",
                                "prior witness current owner mismatch",
                            },
                        )

                        oversized_attempt = recipient.receive_transfer_package(
                            replace(
                                package,
                                target_value=ValueRange(target_value.begin, target_value.end + 3),
                            )
                        )
                        self.assertFalse(oversized_attempt.accepted)
                        self.assertEqual(oversized_attempt.error, "target value is not covered by target tx")

                        wrong_recipient_attempt = net.consensus.deliver_transfer_package(
                            package,
                            recipient_addr=mallory.address,
                        )
                        self.assertFalse(wrong_recipient_attempt.accepted)
                        self.assertEqual(wrong_recipient_attempt.error, "target recipient mismatch")

                        delivered = recipient.receive_transfer_package(package)
                        self.assertTrue(delivered.accepted, delivered.error)

                        duplicate = recipient.receive_transfer_package(package)
                        self.assertFalse(duplicate.accepted)
                        self.assertEqual(duplicate.error, "transfer package already accepted")

                    expected_balances[sender_name] -= amount
                    expected_balances[recipient_name] += amount

                    honest_view = {
                        name: honest_nodes[name].wallet.available_balance()
                        for name in honest_names
                    }
                    self.assertEqual(honest_view, expected_balances)
                    self.assertEqual(sum(honest_view.values()), initial_honest_total)
                    self.assertEqual(mallory.wallet.available_balance(), 0)

                    if (round_index + 1) % 5 == 0:
                        net.restart_consensus()
                        honest_view_after_restart = {
                            name: honest_nodes[name].wallet.available_balance()
                            for name in honest_names
                        }
                        self.assertEqual(honest_view_after_restart, expected_balances)
                        self.assertEqual(mallory.wallet.available_balance(), 0)

                    for node in (*honest_nodes.values(), mallory):
                        self.assertEqual(len(node.wallet.list_pending_bundles()), 0)
                        self.assertEqual(
                            node.wallet.available_balance(),
                            sum(
                                record.value.size
                                for record in node.wallet.list_records()
                                if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
                            ),
                        )
            finally:
                net.close()

    def test_long_mixed_attack_run_rejects_forged_receipts_and_preserves_honest_balances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            net = V2LocalNetwork(
                root_dir=tmpdir,
                chain_id=251,
                auto_confirm_registered_wallets=False,
                genesis_block_hash=b"\xf9" * 32,
            )
            try:
                honest_names = ("alice", "bob", "carol")
                honest_nodes = {
                    name: net.add_account(name, auto_confirm_receipts=False)
                    for name in honest_names
                }
                mallory = net.add_account("mallory")
                for index, name in enumerate(honest_names):
                    begin = index * 100
                    net.allocate_genesis_value(name, ValueRange(begin, begin + 99))

                expected_balances = {name: 100 for name in honest_names}
                initial_honest_total = sum(expected_balances.values())
                rng = random.Random(251)

                for round_index in range(12):
                    senders = [
                        name for name, node in honest_nodes.items() if node.wallet.available_balance() >= 5
                    ]
                    self.assertTrue(senders)
                    sender_name = rng.choice(senders)
                    recipient_name = rng.choice([name for name in honest_names if name != sender_name])
                    sender = honest_nodes[sender_name]
                    recipient = honest_nodes[recipient_name]
                    max_amount = min(15, sender.wallet.available_balance())
                    amount = rng.randint(5, max_amount)

                    payment = sender.submit_payment(
                        recipient.address,
                        amount=amount,
                        fee=1,
                        tx_time=round_index + 1,
                    )
                    produced = net.produce_block(timestamp=round_index + 4000)
                    self.assertEqual(produced.deliveries[sender.address].error, "auto_confirm_disabled")

                    genuine_receipt = produced.receipts[sender.address]
                    bundle_ref = produced.block.diff_package.diff_entries[0].new_leaf.head_ref
                    forged_receipt = replace(
                        genuine_receipt,
                        account_state_proof=SparseMerkleProof(
                            siblings=tuple(
                                b"\xee" * 32 for _ in genuine_receipt.account_state_proof.siblings
                            ),
                            existence=genuine_receipt.account_state_proof.existence,
                        ),
                    )
                    net.consensus.chain.receipt_cache.add(sender.address, forged_receipt, bundle_ref)
                    forged_sync = sender.sync_receipts()
                    self.assertEqual(len(forged_sync), 1)
                    self.assertFalse(forged_sync[0].applied)
                    self.assertEqual(
                        forged_sync[0].error,
                        "receipt account state proof does not verify",
                    )
                    self.assertEqual(len(sender.wallet.list_pending_bundles()), 1)

                    net.consensus.chain.receipt_cache.add(sender.address, genuine_receipt, bundle_ref)
                    recovered_sync = sender.sync_receipts()
                    self.assertEqual(len(recovered_sync), 1)
                    self.assertTrue(recovered_sync[0].applied)
                    self.assertEqual(len(sender.wallet.list_pending_bundles()), 0)

                    for target_value in payment.target_tx.value_list:
                        package = sender.export_transfer_package(payment.target_tx, target_value)

                        oversized_attempt = recipient.receive_transfer_package(
                            replace(
                                package,
                                target_value=ValueRange(target_value.begin, target_value.end + 4),
                            )
                        )
                        self.assertFalse(oversized_attempt.accepted)
                        self.assertEqual(oversized_attempt.error, "target value is not covered by target tx")

                        redirect_attempt = mallory.receive_transfer_package(
                            replace(
                                package,
                                target_tx=replace(package.target_tx, recipient_addr=mallory.address),
                            )
                        )
                        self.assertFalse(redirect_attempt.accepted)
                        self.assertIn(
                            redirect_attempt.error,
                            {
                                "target tx must exist exactly once in latest bundle",
                                "prior witness current owner mismatch",
                            },
                        )

                        delivered = recipient.receive_transfer_package(package)
                        self.assertTrue(delivered.accepted, delivered.error)

                    expected_balances[sender_name] -= amount
                    expected_balances[recipient_name] += amount

                    honest_view = {
                        name: honest_nodes[name].wallet.available_balance()
                        for name in honest_names
                    }
                    self.assertEqual(honest_view, expected_balances)
                    self.assertEqual(sum(honest_view.values()), initial_honest_total)
                    self.assertEqual(mallory.wallet.available_balance(), 0)

                    if (round_index + 1) % 4 == 0:
                        net.restart_consensus()
                        for name in honest_names:
                            net.consensus.unregister_wallet(honest_nodes[name].address)
                            net.consensus.register_wallet(
                                honest_nodes[name].wallet,
                                auto_confirm_receipts=False,
                            )
                        honest_view_after_restart = {
                            name: honest_nodes[name].wallet.available_balance()
                            for name in honest_names
                        }
                        self.assertEqual(honest_view_after_restart, expected_balances)

                for node in (*honest_nodes.values(), mallory):
                    self.assertEqual(len(node.wallet.list_pending_bundles()), 0)
                    self.assertEqual(
                        node.wallet.available_balance(),
                        sum(
                            record.value.size
                            for record in node.wallet.list_records()
                            if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
                        ),
                    )
            finally:
                net.close()


if __name__ == "__main__":
    unittest.main()
