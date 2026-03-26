from __future__ import annotations

import tempfile
import time
import unittest

from EZ_V2.chain import ReceiptCache
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessRecoveryTests(unittest.TestCase):
    @staticmethod
    def _wait_for_consensus_height(consensus: V2ConsensusHost, expected_height: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if consensus.consensus.chain.current_height >= expected_height:
                return consensus.consensus.chain.current_height
            time.sleep(0.01)
        return consensus.consensus.chain.current_height

    @staticmethod
    def _assign_cluster_order(
        accounts: tuple[V2AccountHost, ...],
        primary_peer_id: str,
        consensus_ids: tuple[str, ...],
    ) -> None:
        ordered = (primary_peer_id, *tuple(peer_id for peer_id in consensus_ids if peer_id != primary_peer_id))
        for account in accounts:
            account.set_consensus_peer_ids(ordered)

    def test_flow_offline_sender_recovers_pending_receipt_and_missing_blocks_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5101)
            consensus.auto_dispatch_receipts = False
            alice_private, alice_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5101,
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
                chain_id=5101,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=501)
                self.assertIsNone(first.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                alice.close()
                alice = V2AccountHost(
                    node_id="alice",
                    endpoint="mem://alice",
                    wallet_db_path=f"{td}/alice.sqlite3",
                    chain_id=5101,
                    network=network,
                    consensus_peer_id=consensus.peer.node_id,
                    address=alice_addr,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    state_path=f"{td}/alice.network.json",
                )

                recovery = alice.recover_network_state()
                self.assertEqual(recovery.applied_receipts, 1)
                self.assertEqual([block.header.height for block in recovery.fetched_blocks], [1])
                self.assertEqual(recovery.chain_cursor.height if recovery.chain_cursor else None, 1)
                self.assertEqual(alice.wallet.available_balance(), 160)
                self.assertEqual(bob.wallet.available_balance(), 40)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_flow_recipient_rejects_duplicate_transfer_package_after_first_accept(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5102)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5102,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5102,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                auto_accept_receipts=False,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=601)
                self.assertEqual(payment.receipt_height, 1)
                archived_record = next(
                    record for record in alice.wallet.list_records() if record.local_status.value == "archived"
                )
                confirmed_unit = archived_record.witness_v2.confirmed_bundle_chain[0]
                target_tx = confirmed_unit.bundle_sidecar.tx_list[0]
                package = alice.wallet.export_transfer_package(target_tx, archived_record.value)
                offline_bob = WalletAccountV2(
                    address=bob.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-bob.sqlite3",
                )
                accepted = offline_bob.receive_transfer(package, validator=bob._build_validator_for_package(package))
                self.assertEqual(accepted.value, ValueRange(0, 49))
                with self.assertRaisesRegex(ValueError, "transfer package already accepted"):
                    offline_bob.receive_transfer(package, validator=bob._build_validator_for_package(package))
                offline_bob.close()
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_receipt_missing_recovery_reenables_value_selection_for_next_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=5104)
            consensus.auto_dispatch_receipts = False
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5104,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5104,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5104,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                primary = ValueRange(0, 199)
                alt_left = ValueRange(200, 249)
                alt_right = ValueRange(250, 299)
                for minted in (primary, alt_left, alt_right):
                    consensus.register_genesis_value(alice.address, minted)
                    alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=75, tx_time=1, anti_spam_nonce=801)
                self.assertIsNone(first.receipt_height)
                pending = alice.wallet.list_pending_bundles()
                self.assertEqual(len(pending), 1)
                self.assertEqual(
                    sorted((record.value.begin, record.value.end, record.local_status.value) for record in alice.wallet.list_records()),
                    [
                        (0, 74, LocalValueStatus.PENDING_BUNDLE.value),
                        (75, 199, LocalValueStatus.PENDING_BUNDLE.value),
                        (200, 249, LocalValueStatus.VERIFIED_SPENDABLE.value),
                        (250, 299, LocalValueStatus.VERIFIED_SPENDABLE.value),
                    ],
                )

                block = consensus.consensus.store.get_block_by_height(1)
                assert block is not None
                alice_receipt = consensus.consensus.get_receipt(alice.address, 1).receipt
                assert alice_receipt is not None
                bundle_ref = block.diff_package.diff_entries[0].new_leaf.head_ref
                consensus.consensus.chain.receipt_cache = ReceiptCache(max_blocks=32)
                with consensus.consensus.store._conn:
                    consensus.consensus.store._conn.execute(
                        "DELETE FROM receipt_window_v2 WHERE sender_addr = ? AND seq = ?",
                        (alice.address, 1),
                    )

                self.assertEqual(alice.sync_pending_receipts(), 0)
                self.assertEqual(
                    sorted((record.value.begin, record.value.end, record.local_status.value) for record in alice.wallet.list_records()),
                    [
                        (0, 74, LocalValueStatus.RECEIPT_MISSING.value),
                        (75, 199, LocalValueStatus.RECEIPT_MISSING.value),
                        (200, 249, LocalValueStatus.VERIFIED_SPENDABLE.value),
                        (250, 299, LocalValueStatus.VERIFIED_SPENDABLE.value),
                    ],
                )

                consensus.consensus.chain.receipt_cache.add(alice.address, alice_receipt, bundle_ref)
                recovery = alice.recover_network_state()
                self.assertEqual(recovery.applied_receipts, 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertEqual(
                    sorted((record.value.begin, record.value.end, record.local_status.value) for record in alice.wallet.list_records()),
                    [
                        (0, 74, LocalValueStatus.ARCHIVED.value),
                        (75, 199, LocalValueStatus.VERIFIED_SPENDABLE.value),
                        (200, 249, LocalValueStatus.VERIFIED_SPENDABLE.value),
                        (250, 299, LocalValueStatus.VERIFIED_SPENDABLE.value),
                    ],
                )

                second = alice.submit_payment("carol", amount=100, tx_time=2, anti_spam_nonce=802)
                self.assertIsNone(second.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)
                pending_ranges = sorted(
                    (record.value.begin, record.value.end, record.local_status.value)
                    for record in alice.wallet.list_records()
                )
                self.assertIn((75, 174, LocalValueStatus.PENDING_BUNDLE.value), pending_ranges)
                self.assertNotIn((200, 249, LocalValueStatus.PENDING_BUNDLE.value), pending_ranges)
                self.assertNotIn((250, 299, LocalValueStatus.PENDING_BUNDLE.value), pending_ranges)

                self.assertEqual(alice.sync_pending_receipts(), 1)
                self.assertEqual(bob.wallet.available_balance(), 75)
                self.assertEqual(carol.wallet.available_balance(), 100)
            finally:
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_consensus_follower_restart_catches_up_before_later_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus0.sqlite3",
                network=network,
                chain_id=5103,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/consensus1.sqlite3",
                network=network,
                chain_id=5103,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint="mem://consensus-2",
                store_path=f"{td}/consensus2.sqlite3",
                network=network,
                chain_id=5103,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5103,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5103,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5103,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                allocations = (
                    (alice.address, ValueRange(0, 199)),
                    (bob.address, ValueRange(200, 399)),
                )
                for consensus in (consensus0, consensus1, consensus2):
                    for owner_addr, value in allocations:
                        consensus.register_genesis_value(owner_addr, value)
                alice.register_genesis_value(allocations[0][1])
                bob.register_genesis_value(allocations[1][1])

                accounts = (alice, bob, carol)
                consensus_ids = ("consensus-0", "consensus-1", "consensus-2")
                self._assign_cluster_order(accounts, "consensus-0", consensus_ids)
                first = alice.submit_payment("carol", amount=50, tx_time=1, anti_spam_nonce=701)
                self._assign_cluster_order(accounts, "consensus-2", consensus_ids)
                second = bob.submit_payment("carol", amount=40, tx_time=2, anti_spam_nonce=702)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 2), 2)

                consensus1.close()
                consensus1 = V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint="mem://consensus-1",
                    store_path=f"{td}/consensus1.sqlite3",
                    network=network,
                    chain_id=5103,
                )
                self.assertEqual(consensus1.consensus.chain.current_height, 2)

                self._assign_cluster_order(accounts, "consensus-1", consensus_ids)
                third = carol.submit_payment("alice", amount=30, tx_time=3, anti_spam_nonce=703)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 3), 3)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus2.consensus.chain.current_block_hash)
            finally:
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()


if __name__ == "__main__":
    unittest.main()
