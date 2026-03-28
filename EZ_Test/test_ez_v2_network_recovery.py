from __future__ import annotations

from pathlib import Path
import random
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.networking import ChainSyncCursor, MSG_BLOCK_ANNOUNCE, NetworkEnvelope
from EZ_V2.values import ValueRange


class EZV2NetworkRecoveryTests(unittest.TestCase):
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

    def test_static_network_restart_recovers_cached_blocks_and_fetches_only_missing_heights(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=907)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=907,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=907,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=907,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                state_path=f"{td}/carol.network.json",
            )
            try:
                minted = ValueRange(0, 399)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=31)
                second = alice.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=32)

                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                fetched = carol.sync_chain_blocks()
                self.assertIn([block.header.height for block in fetched], ([], [1, 2]))
                self.assertEqual(sorted(carol.fetched_blocks), [1, 2])
                self.assertEqual(carol.last_seen_chain.height if carol.last_seen_chain else None, 2)

                carol.close()
                carol = V2AccountHost(
                    node_id="carol",
                    endpoint="mem://carol",
                    wallet_db_path=f"{td}/carol.sqlite3",
                    chain_id=907,
                    network=network,
                    consensus_peer_id=consensus.peer.node_id,
                    state_path=f"{td}/carol.network.json",
                )
                self.assertEqual(carol.last_seen_chain.height if carol.last_seen_chain else None, 2)
                self.assertEqual(sorted(carol.fetched_blocks), [1, 2])

                third = alice.submit_payment("bob", amount=20, tx_time=3, anti_spam_nonce=33)
                self.assertEqual(third.receipt_height, 3)

                recovered = carol.sync_chain_blocks()
                self.assertIn([block.header.height for block in recovered], ([], [3]))
                self.assertEqual(sorted(carol.fetched_blocks), [1, 2, 3])
                self.assertEqual(carol.fetch_block(height=2).header.height, 2)
            finally:
                alice.close()
                bob.close()
                carol.close()
                consensus.close()

    def test_account_reset_ephemeral_state_clears_pending_and_cached_network_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=928)
            consensus.auto_dispatch_receipts = False
            alice_private, alice_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            state_path = f"{td}/alice.network.json"
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=928,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
                state_path=state_path,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=928,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=51)
                self.assertIsNone(payment.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                alice.last_seen_chain = ChainSyncCursor(height=99, block_hash_hex="ab" * 32)
                alice.fetched_blocks[99] = consensus.consensus.store.get_block_by_height(0)
                alice.fetched_blocks_by_hash[consensus.consensus.genesis_block_hash.hex()] = consensus.consensus.store.get_block_by_height(0)
                alice._persist_network_state()
                self.assertTrue(Path(state_path).exists())

                cleared = alice.reset_ephemeral_state()

                self.assertEqual(cleared["cleared_pending_bundles"], 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertIsNone(alice.last_seen_chain)
                self.assertEqual(alice.fetched_blocks, {})
                self.assertEqual(alice.fetched_blocks_by_hash, {})
                self.assertFalse(Path(state_path).exists())
                self.assertEqual(alice.wallet.available_balance(), 200)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_restart_discards_stale_cached_blocks_when_remote_chain_is_shorter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_state_path = f"{td}/carol.network.json"

            old_network, old_consensus = open_static_network(f"{td}/old", chain_id=929)
            old_alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/old-alice.sqlite3",
                chain_id=929,
                network=old_network,
                consensus_peer_id=old_consensus.peer.node_id,
            )
            old_bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/old-bob.sqlite3",
                chain_id=929,
                network=old_network,
                consensus_peer_id=old_consensus.peer.node_id,
            )
            old_carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/old-carol.sqlite3",
                chain_id=929,
                network=old_network,
                consensus_peer_id=old_consensus.peer.node_id,
                state_path=old_state_path,
            )
            try:
                minted = ValueRange(0, 299)
                old_consensus.register_genesis_value(old_alice.address, minted)
                old_alice.register_genesis_value(minted)
                first = old_alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=61)
                second = old_alice.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=62)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                fetched = old_carol.sync_chain_blocks()
                self.assertIn([block.header.height for block in fetched], ([], [1, 2]))
                self.assertEqual(sorted(old_carol.fetched_blocks), [1, 2])
            finally:
                old_carol.close()
                old_bob.close()
                old_alice.close()
                old_consensus.close()

            new_network, new_consensus = open_static_network(f"{td}/new", chain_id=929)
            new_alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/new-alice.sqlite3",
                chain_id=929,
                network=new_network,
                consensus_peer_id=new_consensus.peer.node_id,
            )
            new_bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/new-bob.sqlite3",
                chain_id=929,
                network=new_network,
                consensus_peer_id=new_consensus.peer.node_id,
            )
            new_carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/new-carol.sqlite3",
                chain_id=929,
                network=new_network,
                consensus_peer_id=new_consensus.peer.node_id,
                state_path=old_state_path,
            )
            try:
                self.assertEqual(sorted(new_carol.fetched_blocks), [1, 2])
                minted = ValueRange(300, 499)
                new_consensus.register_genesis_value(new_alice.address, minted)
                new_alice.register_genesis_value(minted)
                payment = new_alice.submit_payment("bob", amount=50, tx_time=10, anti_spam_nonce=63)
                self.assertEqual(payment.receipt_height, 1)

                recovered = new_carol.sync_chain_blocks()
                self.assertIn([block.header.height for block in recovered], ([], [1]))
                self.assertEqual(sorted(new_carol.fetched_blocks), [1])
                self.assertEqual(new_carol.last_seen_chain.height if new_carol.last_seen_chain else None, 1)
                self.assertEqual(
                    new_carol.fetched_blocks[1].block_hash.hex(),
                    new_consensus.consensus.chain.current_block_hash.hex(),
                )
            finally:
                new_carol.close()
                new_bob.close()
                new_alice.close()
                new_consensus.close()

    def test_recovery_clears_stale_pending_bundle_after_detected_chain_reset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = f"{td}/alice.network.json"
            alice_private, alice_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)

            old_network, old_consensus = open_static_network(f"{td}/old", chain_id=930)
            old_consensus.auto_dispatch_receipts = False
            old_alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=930,
                network=old_network,
                consensus_peer_id=old_consensus.peer.node_id,
                state_path=state_path,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            old_bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/old-bob.sqlite3",
                chain_id=930,
                network=old_network,
                consensus_peer_id=old_consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                old_consensus.register_genesis_value(old_alice.address, minted)
                old_alice.register_genesis_value(minted)
                first = old_alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=71)
                self.assertIsNone(first.receipt_height)
                self.assertEqual(len(old_alice.wallet.list_pending_bundles()), 1)
                self.assertEqual(sorted(old_alice.fetched_blocks), [1])
            finally:
                old_bob.close()
                old_alice.close()
                old_consensus.close()

            new_network, new_consensus = open_static_network(f"{td}/new", chain_id=930)
            new_consensus.auto_dispatch_receipts = False
            new_alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=930,
                network=new_network,
                consensus_peer_id=new_consensus.peer.node_id,
                state_path=state_path,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            new_bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/new-bob.sqlite3",
                chain_id=930,
                network=new_network,
                consensus_peer_id=new_consensus.peer.node_id,
            )
            try:
                self.assertEqual(len(new_alice.wallet.list_pending_bundles()), 1)
                minted = ValueRange(200, 399)
                new_consensus.register_genesis_value(new_alice.address, minted)
                new_alice.register_genesis_value(minted)

                recovery = new_alice.recover_network_state()
                self.assertEqual(recovery.chain_cursor.height if recovery.chain_cursor else None, 0)
                self.assertEqual(len(new_alice.wallet.list_pending_bundles()), 0)
                self.assertEqual(new_alice.wallet.available_balance(), 400)

                second = new_alice.submit_payment("bob", amount=50, tx_time=2, anti_spam_nonce=72)
                self.assertIsNone(second.receipt_height)
                self.assertEqual(len(new_alice.wallet.list_pending_bundles()), 1)
            finally:
                new_bob.close()
                new_alice.close()
                new_consensus.close()

    def test_static_three_consensus_four_account_late_joining_follower_catches_up_multiple_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus0.sqlite3",
                network=network,
                chain_id=910,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint="mem://consensus-2",
                store_path=f"{td}/consensus2.sqlite3",
                network=network,
                chain_id=910,
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
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-2"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-2",
                consensus_peer_ids=("consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-2"),
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-2",
                consensus_peer_ids=("consensus-2", "consensus-0"),
                address=dave_addr,
                private_key_pem=dave_private,
                public_key_pem=dave_public,
            )
            consensus1: V2ConsensusHost | None = None
            try:
                allocations = (
                    (alice.address, ValueRange(0, 199)),
                    (bob.address, ValueRange(200, 399)),
                )
                for consensus in (consensus0, consensus2):
                    for owner_addr, value in allocations:
                        consensus.register_genesis_value(owner_addr, value)
                alice.register_genesis_value(allocations[0][1])
                bob.register_genesis_value(allocations[1][1])

                accounts = (alice, bob, carol, dave)
                consensus_ids = ("consensus-0", "consensus-2")
                rng = random.Random(910)

                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                first = alice.submit_payment("carol", amount=50, tx_time=1, anti_spam_nonce=61)
                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                second = bob.submit_payment("dave", amount=70, tx_time=2, anti_spam_nonce=62)
                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                third = carol.submit_payment("alice", amount=20, tx_time=3, anti_spam_nonce=63)

                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(consensus0.consensus.chain.current_height, 3)
                self.assertEqual(consensus2.consensus.chain.current_height, 3)

                consensus1 = V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint="mem://consensus-1",
                    store_path=f"{td}/consensus1.sqlite3",
                    network=network,
                    chain_id=910,
                )
                for owner_addr, value in allocations:
                    consensus1.register_genesis_value(owner_addr, value)
                network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BLOCK_ANNOUNCE,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "height": consensus0.consensus.chain.current_height,
                            "block_hash": consensus0.consensus.chain.current_block_hash.hex(),
                        },
                    )
                )
                self.assertEqual(consensus1.consensus.chain.current_height, 3)

                self._assign_cluster_order(accounts, "consensus-1", ("consensus-1", "consensus-0", "consensus-2"))
                fourth = dave.submit_payment("bob", amount=30, tx_time=4, anti_spam_nonce=64)

                self.assertEqual(fourth.receipt_height, 4)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 4), 4)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus2.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus1.consensus.get_receipt(alice.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(bob.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(carol.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(dave.address, 1).status, "ok")
                self.assertEqual(alice.wallet.available_balance(), 170)
                self.assertEqual(bob.wallet.available_balance(), 160)
                self.assertEqual(carol.wallet.available_balance(), 30)
                self.assertEqual(dave.wallet.available_balance(), 40)
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                if consensus1 is not None:
                    consensus1.close()
                consensus2.close()
                consensus0.close()


if __name__ == "__main__":
    unittest.main()
