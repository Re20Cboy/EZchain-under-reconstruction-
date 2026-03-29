from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from EZ_Test.EZ_V2_New_Test.test_v2_distributed_process_checkpoint import (
    EZV2DistributedProcessCheckpointTests,
)
from EZ_V2.chain import compute_bundle_hash
from EZ_V2.localnet import V2LocalNetwork
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.types import Checkpoint, CheckpointAnchor, PriorWitnessLink, TransferPackage, WitnessV2
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessCheckpointRecoveryTests(unittest.TestCase):
    def test_flow_old_owner_can_rerespend_after_checkpoint_trim_and_sidecar_gc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            net = V2LocalNetwork(
                root_dir=td,
                chain_id=5304,
                genesis_block_hash=b"\x33" * 32,
            )
            helper = EZV2DistributedProcessCheckpointTests()
            try:
                alice = net.add_account("alice")
                bob = net.add_account("bob")
                carol = net.add_account("carol")
                dave = net.add_account("dave")
                exact_value = ValueRange(1500, 1599)
                net.allocate_genesis_value("alice", exact_value)

                first = alice.submit_payment(bob.address, amount=100, fee=1, tx_time=1)
                produced_first = net.produce_block(timestamp=2)
                self.assertTrue(produced_first.deliveries[alice.address].applied)
                delivered_to_bob = alice.deliver_outgoing_transfer(
                    first.target_tx,
                    exact_value,
                    recipient_addr=bob.address,
                )
                self.assertTrue(delivered_to_bob.accepted, delivered_to_bob.error)

                second = bob.submit_payment(carol.address, amount=100, fee=1, tx_time=3)
                produced_second = net.produce_block(timestamp=4)
                self.assertTrue(produced_second.deliveries[bob.address].applied)
                delivered_to_carol = bob.deliver_outgoing_transfer(
                    second.target_tx,
                    exact_value,
                    recipient_addr=carol.address,
                )
                self.assertTrue(delivered_to_carol.accepted, delivered_to_carol.error)

                bob_archived = next(
                    record
                    for record in bob.wallet.list_records()
                    if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
                )
                checkpoint = bob.wallet.create_exact_checkpoint(bob_archived.record_id)
                self.assertEqual(bob.wallet.list_checkpoints(), [checkpoint])

                prior_hash = compute_bundle_hash(
                    bob_archived.witness_v2.anchor.prior_witness.confirmed_bundle_chain[0].bundle_sidecar
                )
                self.assertIn(prior_hash, bob.wallet.db.list_sidecar_hashes())
                bob.wallet.gc_unused_sidecars()
                self.assertIn(prior_hash, bob.wallet.db.list_sidecar_hashes())

                third = carol.submit_payment(bob.address, amount=100, fee=1, tx_time=5)
                produced_third = net.produce_block(timestamp=6)
                self.assertTrue(produced_third.deliveries[carol.address].applied)
                returned_package = carol.export_transfer_package(third.target_tx, exact_value)
                self.assertTrue(helper._witness_contains_checkpoint_anchor(returned_package.witness_v2))

                bob_return = bob.receive_transfer_package(returned_package)
                self.assertTrue(bob_return.accepted, bob_return.error)

                fourth = bob.submit_payment(dave.address, amount=100, fee=1, tx_time=7)
                produced_fourth = net.produce_block(timestamp=8)
                self.assertTrue(produced_fourth.deliveries[bob.address].applied)
                downstream_package = bob.export_transfer_package(fourth.target_tx, exact_value)
                self.assertFalse(helper._witness_contains_checkpoint_anchor(downstream_package.witness_v2))

                dave_receive = dave.receive_transfer_package(downstream_package)
                self.assertTrue(dave_receive.accepted, dave_receive.error)
                self.assertEqual(dave_receive.record.value, exact_value)
            finally:
                net.close()

    def test_flow_checkpoint_persists_across_restart_and_can_be_reused_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            helper = EZV2DistributedProcessCheckpointTests()
            consensus, alice, bob, carol, dave, checkpoint, package, _ = helper._build_return_loop_with_checkpoint(td)
            alice_addr = alice.address
            try:
                alice.close()
                reopened_alice = WalletAccountV2(
                    address=alice_addr,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/alice.sqlite3",
                )
                persisted = reopened_alice.list_checkpoints()
                self.assertEqual(len(persisted), 1)
                self.assertEqual(persisted[0], checkpoint)

                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                accepted = offline_dave.receive_transfer(
                    package,
                    validator=trusted_runtime.build_validator(trusted_checkpoints=(persisted[0],)),
                )
                self.assertEqual(accepted.value, ValueRange(1500, 1599))
                offline_dave.close()
                reopened_alice.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                consensus.close()

    def test_flow_checkpoint_wrong_owner_range_or_height_is_not_trusted_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            helper = EZV2DistributedProcessCheckpointTests()
            consensus, alice, bob, carol, dave, checkpoint, package, _ = helper._build_return_loop_with_checkpoint(td)
            try:
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                forged_owner = Checkpoint(
                    value_begin=checkpoint.value_begin,
                    value_end=checkpoint.value_end,
                    owner_addr=bob.address,
                    checkpoint_height=checkpoint.checkpoint_height,
                    checkpoint_block_hash=checkpoint.checkpoint_block_hash,
                    checkpoint_bundle_hash=checkpoint.checkpoint_bundle_hash,
                )
                forged_range = Checkpoint(
                    value_begin=checkpoint.value_begin,
                    value_end=checkpoint.value_end - 1,
                    owner_addr=checkpoint.owner_addr,
                    checkpoint_height=checkpoint.checkpoint_height,
                    checkpoint_block_hash=checkpoint.checkpoint_block_hash,
                    checkpoint_bundle_hash=checkpoint.checkpoint_bundle_hash,
                )
                forged_height = Checkpoint(
                    value_begin=checkpoint.value_begin,
                    value_end=checkpoint.value_end,
                    owner_addr=checkpoint.owner_addr,
                    checkpoint_height=checkpoint.checkpoint_height + 1,
                    checkpoint_block_hash=checkpoint.checkpoint_block_hash,
                    checkpoint_bundle_hash=checkpoint.checkpoint_bundle_hash,
                )

                for fake in (forged_owner, forged_range, forged_height):
                    with self.assertRaisesRegex(ValueError, "checkpoint anchor is not trusted"):
                        offline_dave.receive_transfer(
                            package,
                            validator=trusted_runtime.build_validator(trusted_checkpoints=(fake,)),
                        )
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_checkpoint_can_be_created_after_receipt_recovery_and_then_reused_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
            from EZ_V2.network_host import open_static_network, V2AccountHost

            network, consensus = open_static_network(td, chain_id=5302)
            consensus.auto_dispatch_receipts = False
            alice_private, alice_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
                state_path=f"{td}/alice.network.json",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                auto_accept_receipts=False,
            )
            try:
                exact_value = ValueRange(1500, 1599)
                consensus.register_genesis_value(alice.address, exact_value)
                alice.register_genesis_value(exact_value)

                first = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=905)
                self.assertIsNone(first.receipt_height)
                self.assertEqual(alice.recover_network_state().applied_receipts, 1)

                second = bob.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=906)
                self.assertIsNone(second.receipt_height)
                self.assertEqual(bob.sync_pending_receipts(), 1)
                alice.close()
                alice = V2AccountHost(
                    node_id="alice",
                    endpoint="mem://alice",
                    wallet_db_path=f"{td}/alice.sqlite3",
                    chain_id=5302,
                    network=network,
                    consensus_peer_id=consensus.peer.node_id,
                    address=alice_addr,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    state_path=f"{td}/alice.network.json",
                )
                recovery = alice.recover_network_state()
                self.assertEqual(recovery.applied_receipts, 0)

                third = alice.submit_payment("carol", amount=100, tx_time=3, anti_spam_nonce=907)
                self.assertIsNone(third.receipt_height)
                self.assertEqual(alice.recover_network_state().applied_receipts, 1)
                archived = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status.value == "archived" and record.value == exact_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                checkpoint = alice.wallet.create_exact_checkpoint(archived.record_id)
                self.assertEqual(alice.wallet.list_checkpoints(), [checkpoint])
                target_tx = archived.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                package = alice.wallet.export_transfer_package(target_tx, exact_value)
                checkpointed_package = replace(
                    package,
                    witness_v2=replace(
                        package.witness_v2,
                        anchor=CheckpointAnchor(checkpoint=checkpoint),
                    ),
                )
                offline_carol = WalletAccountV2(
                    address=carol.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-carol.sqlite3",
                )
                trusted_runtime = V2Runtime()
                accepted = offline_carol.receive_transfer(
                    checkpointed_package,
                    validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint,)),
                )
                self.assertEqual(accepted.value, exact_value)
                offline_carol.close()
            finally:
                carol.close()
                bob.close()
                alice.close()
                consensus.close()


if __name__ == "__main__":
    unittest.main()
