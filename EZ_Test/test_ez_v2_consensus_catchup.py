import random
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.values import ValueRange


class EZV2ConsensusCatchupTest(unittest.TestCase):
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

    def test_account_recover_network_state_applies_pending_receipts_and_fetches_only_missing_blocks_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=908)
            consensus.auto_dispatch_receipts = False
            alice_private, alice_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=908,
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
                chain_id=908,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=41)
                self.assertIsNone(first.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                alice.close()
                alice = V2AccountHost(
                    node_id="alice",
                    endpoint="mem://alice",
                    wallet_db_path=f"{td}/alice.sqlite3",
                    chain_id=908,
                    network=network,
                    consensus_peer_id=consensus.peer.node_id,
                    address=alice_addr,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    state_path=f"{td}/alice.network.json",
                )

                first_recovery = alice.recover_network_state()
                self.assertEqual(first_recovery.applied_receipts, 1)
                self.assertEqual([block.header.height for block in first_recovery.fetched_blocks], [1])
                self.assertEqual(first_recovery.chain_cursor.height if first_recovery.chain_cursor else None, 1)
                self.assertEqual(sorted(alice.fetched_blocks), [1])

                second = alice.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=42)
                self.assertIsNone(second.receipt_height)

                alice.close()
                alice = V2AccountHost(
                    node_id="alice",
                    endpoint="mem://alice",
                    wallet_db_path=f"{td}/alice.sqlite3",
                    chain_id=908,
                    network=network,
                    consensus_peer_id=consensus.peer.node_id,
                    address=alice_addr,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    state_path=f"{td}/alice.network.json",
                )

                second_recovery = alice.recover_network_state()
                self.assertEqual(second_recovery.applied_receipts, 1)
                self.assertEqual([block.header.height for block in second_recovery.fetched_blocks], [2])
                self.assertEqual(second_recovery.chain_cursor.height if second_recovery.chain_cursor else None, 2)
                self.assertEqual(sorted(alice.fetched_blocks), [1, 2])
                self.assertEqual(alice.wallet.available_balance(), 130)
                self.assertEqual(bob.wallet.available_balance(), 70)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_consensus_follower_restart_catches_up_before_later_cluster_payments(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus0.sqlite3",
                network=network,
                chain_id=909,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/consensus1.sqlite3",
                network=network,
                chain_id=909,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint="mem://consensus-2",
                store_path=f"{td}/consensus2.sqlite3",
                network=network,
                chain_id=909,
            )
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            carol_private, carol_public = generate_secp256k1_keypair()
            dave_private, dave_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)
            carol_addr = address_from_public_key_pem(carol_public)
            dave_addr = address_from_public_key_pem(dave_public)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
                address=dave_addr,
                private_key_pem=dave_private,
                public_key_pem=dave_public,
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

                accounts = (alice, bob, carol, dave)
                rng = random.Random(909)
                consensus_ids = ("consensus-0", "consensus-1", "consensus-2")

                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                first = alice.submit_payment("carol", amount=50, tx_time=1, anti_spam_nonce=51)
                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                second = bob.submit_payment("dave", amount=70, tx_time=2, anti_spam_nonce=52)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 2), 2)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 2), 2)

                consensus1.close()
                consensus1 = V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint="mem://consensus-1",
                    store_path=f"{td}/consensus1.sqlite3",
                    network=network,
                    chain_id=909,
                )
                self.assertEqual(consensus1.consensus.chain.current_height, 2)

                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                third = carol.submit_payment("alice", amount=20, tx_time=3, anti_spam_nonce=53)
                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                fourth = dave.submit_payment("bob", amount=30, tx_time=4, anti_spam_nonce=54)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(fourth.receipt_height, 4)

                self.assertEqual(self._wait_for_consensus_height(consensus1, 4), 4)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 4), 4)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus2.consensus.chain.current_block_hash)
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()
