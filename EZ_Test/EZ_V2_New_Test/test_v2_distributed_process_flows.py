from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.types import CheckpointAnchor, TransferPackage, WitnessV2
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessFlowTests(unittest.TestCase):
    @staticmethod
    def _wait_for_consensus_height(consensus: V2ConsensusHost, expected_height: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if consensus.consensus.chain.current_height >= expected_height:
                return consensus.consensus.chain.current_height
            time.sleep(0.01)
        return consensus.consensus.chain.current_height

    @staticmethod
    def _wait_for_receipt_count(account: V2AccountHost, expected_count: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            count = len(account.wallet.list_receipts())
            if count >= expected_count:
                return count
            time.sleep(0.01)
        return len(account.wallet.list_receipts())

    @staticmethod
    def _force_consensus_0_wins(consensus_hosts: tuple[V2ConsensusHost, ...]) -> None:
        ordered_ids = tuple(host.peer.node_id for host in consensus_hosts)
        for consensus in consensus_hosts:
            consensus.select_mvp_proposer = lambda **_: {
                "selected_proposer_id": "consensus-0",
                "ordered_consensus_peer_ids": ordered_ids,
                "height": 1,
                "round": 1,
                "seed_hex": "",
                "claims_total": len(ordered_ids),
            }

    def test_flow_bundle_to_mempool_to_mvp_commit_to_receipt_and_transfer_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=5001,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                    auto_run_mvp_consensus_window_sec=0.2,
                )
                for validator_id in validator_ids
            )
            self._force_consensus_0_wins(consensus_hosts)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5001,
                network=network,
                consensus_peer_id="consensus-1",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5001,
                network=network,
                consensus_peer_id="consensus-2",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5001,
                network=network,
                consensus_peer_id="consensus-3",
            )
            try:
                minted_alice = ValueRange(0, 199)
                minted_carol = ValueRange(200, 399)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted_alice)
                    consensus.register_genesis_value(carol.address, minted_carol)
                alice.register_genesis_value(minted_alice)
                carol.register_genesis_value(minted_carol)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=101)
                second = carol.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=102)

                self.assertIsNone(first.receipt_height)
                self.assertIsNone(second.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)
                self.assertEqual(len(carol.wallet.list_pending_bundles()), 1)
                self.assertEqual(len(bob.received_transfers), 0)
                self.assertEqual(len(consensus_hosts[0].consensus.chain.bundle_pool.snapshot()), 2)
                self.assertEqual(len(consensus_hosts[1].consensus.chain.bundle_pool.snapshot()), 0)
                self.assertEqual(len(consensus_hosts[2].consensus.chain.bundle_pool.snapshot()), 0)
                self.assertEqual(len(consensus_hosts[3].consensus.chain.bundle_pool.snapshot()), 0)

                tick = consensus_hosts[0].drive_auto_mvp_consensus_tick(force=True)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")

                for consensus in consensus_hosts:
                    self.assertEqual(self._wait_for_consensus_height(consensus, 1), 1)
                    self.assertEqual(len(consensus.consensus.chain.bundle_pool.snapshot()), 0)
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(carol, 1), 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertEqual(len(carol.wallet.list_pending_bundles()), 0)
                self.assertEqual(len(bob.received_transfers), 2)
                self.assertEqual(bob.wallet.available_balance(), 80)

                block = consensus_hosts[0].consensus.store.get_block_by_height(1)
                assert block is not None
                self.assertEqual(block.header.height, 1)
                self.assertEqual(len(block.diff_package.diff_entries), 2)
                self.assertEqual(
                    sorted(entry.new_leaf.addr for entry in block.diff_package.diff_entries),
                    sorted((alice.address, carol.address)),
                )
            finally:
                bob.close()
                carol.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()

    def test_flow_sender_cannot_start_next_bundle_before_receipt_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5002)
            consensus.auto_dispatch_receipts = False
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5002,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5002,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=201)
                self.assertIsNone(first.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                with self.assertRaisesRegex(ValueError, "wallet already has a pending bundle"):
                    alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=202)

                applied = alice.sync_pending_receipts()
                self.assertEqual(applied, 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)

                second = alice.submit_payment("bob", amount=25, tx_time=3, anti_spam_nonce=203)
                self.assertIsNone(second.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)
                self.assertEqual(alice.sync_pending_receipts(), 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 2)
                self.assertEqual(bob.wallet.available_balance(), 75)
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_recipient_rejects_tampered_transfer_package_using_only_witness_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5003)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5003,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5003,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=301)
                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(len(bob.received_transfers), 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)

                archived_record = next(
                    record for record in alice.wallet.list_records() if record.local_status == LocalValueStatus.ARCHIVED
                )
                confirmed_unit = archived_record.witness_v2.confirmed_bundle_chain[0]
                target_tx = confirmed_unit.bundle_sidecar.tx_list[0]
                package = alice.wallet.export_transfer_package(target_tx, archived_record.value)
                offline_bob = WalletAccountV2(
                    address=bob.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-bob.sqlite3",
                )

                tampered_value_package = replace(
                    package,
                    target_value=ValueRange(archived_record.value.begin, archived_record.value.end + 1),
                )
                with self.assertRaisesRegex(ValueError, "target value is not covered by target tx"):
                    offline_bob.receive_transfer(
                        tampered_value_package,
                        validator=bob._build_validator_for_package(tampered_value_package),
                    )

                wrong_recipient_package = replace(
                    package,
                    target_tx=replace(package.target_tx, recipient_addr="0x" + "12" * 20),
                )
                with self.assertRaisesRegex(ValueError, "target recipient mismatch"):
                    offline_bob.receive_transfer(
                        wrong_recipient_package,
                        validator=bob._build_validator_for_package(wrong_recipient_package),
                    )

                accepted = offline_bob.receive_transfer(package, validator=bob._build_validator_for_package(package))
                self.assertEqual(accepted.value, archived_record.value)
                self.assertEqual(accepted.witness_v2.current_owner_addr, bob.address)
                offline_bob.close()
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_checkpoint_shortcut_requires_trusted_checkpoint_and_preserves_p2p_validation_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5004)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5004,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5004,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5004,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                auto_accept_receipts=False,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=401)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(bob.wallet.available_balance(), 50)

                second = bob.submit_payment("carol", amount=20, tx_time=2, anti_spam_nonce=402)
                self.assertEqual(second.receipt_height, 2)

                bob_archived = [
                    record for record in bob.wallet.list_records() if record.local_status == LocalValueStatus.ARCHIVED
                ]
                target_record = next(record for record in bob_archived if record.value == ValueRange(0, 19))
                checkpoint = bob.wallet.create_exact_checkpoint(target_record.record_id)
                target_tx = target_record.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                checkpoint_package = TransferPackage(
                    target_tx=target_tx,
                    target_value=target_record.value,
                    witness_v2=WitnessV2(
                        value=target_record.value,
                        current_owner_addr=bob.address,
                        confirmed_bundle_chain=target_record.witness_v2.confirmed_bundle_chain,
                        anchor=CheckpointAnchor(checkpoint=checkpoint),
                    ),
                )
                offline_carol = WalletAccountV2(
                    address=carol.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-carol.sqlite3",
                )

                with self.assertRaisesRegex(ValueError, "checkpoint anchor is not trusted"):
                    offline_carol.receive_transfer(
                        checkpoint_package,
                        validator=carol._build_validator_for_package(checkpoint_package),
                    )

                trusted_runtime = V2Runtime()
                accepted = offline_carol.receive_transfer(
                    checkpoint_package,
                    validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint,)),
                )
                self.assertEqual(accepted.value, ValueRange(0, 19))
                self.assertEqual(accepted.witness_v2.current_owner_addr, carol.address)
                offline_carol.close()
            finally:
                carol.close()
                bob.close()
                alice.close()
                consensus.close()


if __name__ == "__main__":
    unittest.main()
