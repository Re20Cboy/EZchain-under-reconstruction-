from dataclasses import replace
import tempfile
import unittest
import socket
import time
import random

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, open_static_network
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import ChainSyncCursor
from EZ_V2.networking import MSG_BLOCK_ANNOUNCE, MSG_BLOCK_FETCH_REQ, MSG_BLOCK_FETCH_RESP, NetworkEnvelope
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2ConsensusHost
from EZ_V2.values import ValueRange


class EZV2NetworkSmokeTest(unittest.TestCase):
    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def _wait_for_chain_height(account: V2AccountHost, expected_height: int, timeout_sec: float = 1.0) -> int | None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if account.last_seen_chain is not None and account.last_seen_chain.height >= expected_height:
                return account.last_seen_chain.height
            time.sleep(0.01)
        if account.last_seen_chain is None:
            return None
        return account.last_seen_chain.height

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

    @staticmethod
    def _announce_block(network, sender_id: str, recipient_id: str, *, height: int, block_hash_hex: str) -> dict[str, object] | None:
        return network.send(
            NetworkEnvelope(
                msg_type=MSG_BLOCK_ANNOUNCE,
                sender_id=sender_id,
                recipient_id=recipient_id,
                payload={
                    "height": height,
                    "block_hash": block_hash_hex,
                },
            )
        )

    def test_static_network_cross_node_payment_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=903)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=903,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=903,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=9)
                chain_state = bob.refresh_chain_state()

                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(len(bob.received_transfers), 1)
                self.assertIsInstance(chain_state, ChainSyncCursor)
                assert chain_state is not None
                self.assertEqual(chain_state.height, 1)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_static_network_submit_payment_falls_back_to_next_consensus_peer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=902,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=902,
                network=network,
                consensus_peer_id="consensus-missing",
                consensus_peer_ids=("consensus-missing", "consensus-0"),
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=902,
                network=network,
                consensus_peer_id="consensus-missing",
                consensus_peer_ids=("consensus-missing", "consensus-0"),
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=8)

                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(alice.consensus_peer_id, "consensus-0")
                self.assertEqual(alice.consensus_peer_ids[0], "consensus-0")
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_static_consensus_rejects_announced_block_with_wrong_chain_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            source = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/source.sqlite3",
                network=network,
                chain_id=920,
                auto_announce_blocks=False,
            )
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=920,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=920,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=920,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                source.register_genesis_value(alice.address, minted)
                follower.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=301)
                valid_block = source.consensus.store.get_block_by_height(1)
                assert valid_block is not None
                bad_block = replace(
                    valid_block,
                    header=replace(valid_block.header, chain_id=921),
                )

                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={
                                    "status": "ok",
                                    "block": bad_block,
                                    "height": bad_block.header.height,
                                    "block_hash_hex": bad_block.block_hash.hex(),
                                },
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                with self.assertRaisesRegex(ValueError, "unexpected_chain_id"):
                    self._announce_block(
                        network,
                        "consensus-bad",
                        "consensus-1",
                        height=1,
                        block_hash_hex=bad_block.block_hash.hex(),
                    )
                self.assertEqual(follower.consensus.chain.current_height, 0)

                synced = self._announce_block(
                    network,
                    "consensus-0",
                    "consensus-1",
                    height=1,
                    block_hash_hex=valid_block.block_hash.hex(),
                )
                self.assertEqual(synced["status"], "synced")
                self.assertEqual(follower.consensus.chain.current_height, 1)
            finally:
                bob.close()
                alice.close()
                follower.close()
                source.close()

    def test_static_consensus_rejects_announced_block_with_bad_state_root_and_recovers_on_honest_announce(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            source = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/source.sqlite3",
                network=network,
                chain_id=922,
                auto_announce_blocks=False,
            )
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=922,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=922,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=922,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                source.register_genesis_value(alice.address, minted)
                follower.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=302)
                valid_block = source.consensus.store.get_block_by_height(1)
                assert valid_block is not None
                bad_block = replace(
                    valid_block,
                    header=replace(valid_block.header, state_root=b"\xff" * 32),
                )

                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={
                                    "status": "ok",
                                    "block": bad_block,
                                    "height": bad_block.header.height,
                                    "block_hash_hex": bad_block.block_hash.hex(),
                                },
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                with self.assertRaisesRegex(ValueError, "state_root mismatch"):
                    self._announce_block(
                        network,
                        "consensus-bad",
                        "consensus-1",
                        height=1,
                        block_hash_hex=bad_block.block_hash.hex(),
                    )
                self.assertEqual(follower.consensus.chain.current_height, 0)

                synced = self._announce_block(
                    network,
                    "consensus-0",
                    "consensus-1",
                    height=1,
                    block_hash_hex=valid_block.block_hash.hex(),
                )
                self.assertEqual(synced["status"], "synced")
                self.assertEqual(follower.consensus.chain.current_height, 1)
            finally:
                bob.close()
                alice.close()
                follower.close()
                source.close()

    def test_static_consensus_rejects_fake_height_when_announcer_cannot_supply_missing_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=923,
            )
            try:
                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={"status": "missing"},
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                result = self._announce_block(
                    network,
                    "consensus-bad",
                    "consensus-1",
                    height=3,
                    block_hash_hex="00" * 32,
                )
                self.assertEqual(result["ok"], False)
                self.assertEqual(result["error"], "missing_announced_block:1")
                self.assertEqual(follower.consensus.chain.current_height, 0)
            finally:
                follower.close()

    def test_static_network_bootstrap_fetches_missing_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=906)
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 299)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=21)
                second = alice.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=22)

                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(consensus.consensus.chain.current_height, 2)

                cursor = carol.refresh_chain_state()
                fetched = carol.sync_chain_blocks()

                self.assertIsNotNone(cursor)
                assert cursor is not None
                self.assertEqual(cursor.height, 2)
                self.assertEqual(len(fetched), 2)
                self.assertEqual([block.header.height for block in fetched], [1, 2])
                self.assertEqual(fetched[-1].block_hash.hex(), consensus.consensus.chain.current_block_hash.hex())
                self.assertEqual(carol.fetch_block(height=1), fetched[0])
                self.assertEqual(carol.fetch_block(block_hash_hex=fetched[1].block_hash.hex()), fetched[1])
                self.assertEqual(carol.sync_chain_blocks(), ())
            finally:
                alice.close()
                bob.close()
                carol.close()
                consensus.close()

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
                self.assertEqual([block.header.height for block in fetched], [1, 2])
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
                self.assertEqual([block.header.height for block in recovered], [3])
                self.assertEqual(sorted(carol.fetched_blocks), [1, 2, 3])
                self.assertEqual(carol.fetch_block(height=2).header.height, 2)
            finally:
                alice.close()
                bob.close()
                carol.close()
                consensus.close()

    def test_static_network_recover_network_state_applies_pending_receipts_and_fetches_only_missing_blocks_after_restart(self) -> None:
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
                self.assertEqual(first_recovery.pending_bundle_count, 0)
                self.assertEqual(first_recovery.receipt_count, 1)
                self.assertEqual(sorted(alice.fetched_blocks), [1])
                self.assertEqual(alice.wallet.available_balance(), 160)
                self.assertEqual(bob.wallet.available_balance(), 40)

                second = alice.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=42)
                self.assertIsNone(second.receipt_height)
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

                second_recovery = alice.recover_network_state()
                self.assertEqual(second_recovery.applied_receipts, 1)
                self.assertEqual([block.header.height for block in second_recovery.fetched_blocks], [2])
                self.assertEqual(second_recovery.chain_cursor.height if second_recovery.chain_cursor else None, 2)
                self.assertEqual(second_recovery.pending_bundle_count, 0)
                self.assertEqual(second_recovery.receipt_count, 2)
                self.assertEqual(sorted(alice.fetched_blocks), [1, 2])
                self.assertEqual(alice.wallet.available_balance(), 130)
                self.assertEqual(bob.wallet.available_balance(), 70)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_static_three_consensus_four_account_cluster_follower_restart_catches_up(self) -> None:
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

                self.assertEqual(alice.wallet.available_balance(), 170)
                self.assertEqual(bob.wallet.available_balance(), 160)
                self.assertEqual(carol.wallet.available_balance(), 30)
                self.assertEqual(dave.wallet.available_balance(), 40)

                self.assertEqual(consensus1.consensus.get_receipt(alice.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(bob.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(carol.address, 1).status, "ok")
                self.assertEqual(consensus1.consensus.get_receipt(dave.address, 1).status, "ok")
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

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

    def test_tcp_static_network_cross_node_payment_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            carol_private, carol_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)
            carol_addr = address_from_public_key_pem(carol_public)

            try:
                peers = (
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
                )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            peer_map = {peer.node_id: peer for peer in peers}

            consensus_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", int(peer_map["consensus-0"].endpoint.rsplit(":", 1)[1])),
                peers,
            )
            alice_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", int(peer_map["alice"].endpoint.rsplit(":", 1)[1])),
                peers,
            )
            bob_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", int(peer_map["bob"].endpoint.rsplit(":", 1)[1])),
                peers,
            )
            carol_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", int(peer_map["carol"].endpoint.rsplit(":", 1)[1])),
                peers,
            )

            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/consensus.sqlite3",
                network=consensus_network,
                chain_id=905,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=905,
                network=alice_network,
                consensus_peer_id=consensus.peer.node_id,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=905,
                network=bob_network,
                consensus_peer_id=consensus.peer.node_id,
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint=peer_map["carol"].endpoint,
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=905,
                network=carol_network,
                consensus_peer_id=consensus.peer.node_id,
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            try:
                try:
                    consensus_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=13)
                chain_state = bob.refresh_chain_state()
                fetched = bob.sync_chain_blocks()

                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(len(bob.received_transfers), 1)
                self.assertIsNotNone(chain_state)
                assert chain_state is not None
                self.assertEqual(chain_state.height, 1)
                self.assertEqual(self._wait_for_chain_height(carol, 1), 1)
                self.assertEqual(len(fetched), 1)
                self.assertEqual(fetched[0].header.height, 1)
                self.assertEqual(fetched[0].block_hash.hex(), consensus.consensus.chain.current_block_hash.hex())
            finally:
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus_network.stop()
                carol.close()
                alice.close()
                bob.close()
                consensus.close()

    def test_receipt_request_sync_applies_pending_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=904)
            consensus.auto_dispatch_receipts = False
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=904,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
                auto_accept_receipts=True,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=904,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=11)
                self.assertIsNone(payment.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)
                self.assertEqual(bob.wallet.available_balance(), 0)

                applied = alice.sync_pending_receipts()
                self.assertEqual(applied, 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 40)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_tcp_three_consensus_four_account_cluster_replicates_blocks_and_balances(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            carol_private, carol_public = generate_secp256k1_keypair()
            dave_private, dave_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)
            carol_addr = address_from_public_key_pem(carol_public)
            dave_addr = address_from_public_key_pem(dave_public)

            try:
                peers = (
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
                    PeerInfo(node_id="dave", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": dave_addr}),
                )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            peer_map = {peer.node_id: peer for peer in peers}

            def _network_for(peer_id: str) -> TransportPeerNetwork:
                return TransportPeerNetwork(
                    TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])),
                    peers,
                )

            consensus0_network = _network_for("consensus-0")
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            carol_network = _network_for("carol")
            dave_network = _network_for("dave")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/consensus0.sqlite3",
                network=consensus0_network,
                chain_id=915,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=915,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=915,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=915,
                network=alice_network,
                consensus_peer_id="consensus-0",
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=915,
                network=bob_network,
                consensus_peer_id="consensus-0",
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint=peer_map["carol"].endpoint,
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=915,
                network=carol_network,
                consensus_peer_id="consensus-0",
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint=peer_map["dave"].endpoint,
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=915,
                network=dave_network,
                consensus_peer_id="consensus-0",
                address=dave_addr,
                private_key_pem=dave_private,
                public_key_pem=dave_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                    dave_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                allocations = (
                    (alice_addr, ValueRange(0, 199)),
                    (bob_addr, ValueRange(200, 399)),
                )
                for consensus in (consensus0, consensus1, consensus2):
                    for owner_addr, value in allocations:
                        consensus.register_genesis_value(owner_addr, value)
                alice.register_genesis_value(allocations[0][1])
                bob.register_genesis_value(allocations[1][1])

                accounts = (alice, bob, carol, dave)
                winners = ("consensus-1", "consensus-0", "consensus-2", "consensus-1")

                self._assign_cluster_order(accounts, winners[0], ("consensus-0", "consensus-1", "consensus-2"))
                payment_1 = alice.submit_payment("carol", amount=50, tx_time=1, anti_spam_nonce=101)
                self._assign_cluster_order(accounts, winners[1], ("consensus-0", "consensus-1", "consensus-2"))
                payment_2 = bob.submit_payment("dave", amount=70, tx_time=2, anti_spam_nonce=102)
                self._assign_cluster_order(accounts, winners[2], ("consensus-0", "consensus-1", "consensus-2"))
                payment_3 = carol.submit_payment("alice", amount=20, tx_time=3, anti_spam_nonce=103)
                self._assign_cluster_order(accounts, winners[3], ("consensus-0", "consensus-1", "consensus-2"))
                payment_4 = dave.submit_payment("bob", amount=30, tx_time=4, anti_spam_nonce=104)

                self.assertEqual(payment_1.receipt_height, 1)
                self.assertEqual(payment_2.receipt_height, 2)
                self.assertEqual(payment_3.receipt_height, 3)
                self.assertEqual(payment_4.receipt_height, 4)

                self.assertEqual(self._wait_for_consensus_height(consensus1, 4), 4)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 4), 4)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus2.consensus.chain.current_block_hash)

                self.assertEqual(alice.wallet.available_balance(), 170)
                self.assertEqual(bob.wallet.available_balance(), 160)
                self.assertEqual(carol.wallet.available_balance(), 30)
                self.assertEqual(dave.wallet.available_balance(), 40)

                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(len(bob.wallet.list_receipts()), 1)
                self.assertEqual(len(carol.wallet.list_receipts()), 1)
                self.assertEqual(len(dave.wallet.list_receipts()), 1)
                self.assertEqual(len(carol.received_transfers), 1)
                self.assertEqual(len(dave.received_transfers), 1)
                self.assertEqual(len(alice.received_transfers), 1)
                self.assertEqual(len(bob.received_transfers), 1)

                self.assertEqual(consensus1.consensus.get_receipt(alice.address, 1).status, "ok")
                self.assertEqual(consensus2.consensus.get_receipt(bob.address, 1).status, "ok")
            finally:
                dave_network.stop()
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_cluster_falls_back_when_selected_winner_is_down(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)

            try:
                peers = (
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            peer_map = {peer.node_id: peer for peer in peers}

            def _network_for(peer_id: str) -> TransportPeerNetwork:
                return TransportPeerNetwork(
                    TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])),
                    peers,
                )

            consensus0_network = _network_for("consensus-0")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/consensus0.sqlite3",
                network=consensus0_network,
                chain_id=916,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=916,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=916,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=916,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                allocation = ValueRange(0, 199)
                for consensus in (consensus0, consensus2):
                    consensus.register_genesis_value(alice.address, allocation)
                alice.register_genesis_value(allocation)

                payment = alice.submit_payment("bob", amount=60, tx_time=1, anti_spam_nonce=91)

                self.assertEqual(payment.receipt_height, 1)
                self.assertEqual(alice.consensus_peer_id, "consensus-0")
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(alice.wallet.available_balance(), 140)
                self.assertEqual(bob.wallet.available_balance(), 60)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus2.close()
                consensus0.close()

    def test_tcp_cluster_follower_misses_multiple_rounds_then_catches_up_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            carol_private, carol_public = generate_secp256k1_keypair()
            dave_private, dave_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)
            carol_addr = address_from_public_key_pem(carol_public)
            dave_addr = address_from_public_key_pem(dave_public)

            try:
                peers = (
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
                    PeerInfo(node_id="dave", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": dave_addr}),
                )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            peer_map = {peer.node_id: peer for peer in peers}

            def _network_for(peer_id: str) -> TransportPeerNetwork:
                return TransportPeerNetwork(
                    TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])),
                    peers,
                )

            consensus0_network = _network_for("consensus-0")
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            carol_network = _network_for("carol")
            dave_network = _network_for("dave")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/consensus0.sqlite3",
                network=consensus0_network,
                chain_id=917,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=917,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=917,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=917,
                network=alice_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1", "consensus-2"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=917,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint=peer_map["carol"].endpoint,
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=917,
                network=carol_network,
                consensus_peer_id="consensus-2",
                consensus_peer_ids=("consensus-2", "consensus-0", "consensus-1"),
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint=peer_map["dave"].endpoint,
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=917,
                network=dave_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1", "consensus-2"),
                address=dave_addr,
                private_key_pem=dave_private,
                public_key_pem=dave_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                    dave_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

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
                consensus_ids = ("consensus-0", "consensus-1", "consensus-2")
                rng = random.Random(917)

                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                first = alice.submit_payment("carol", amount=50, tx_time=1, anti_spam_nonce=71)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)

                consensus1_network.stop()
                self._assign_cluster_order(accounts, rng.choice(("consensus-0", "consensus-2")), ("consensus-0", "consensus-2"))
                second = bob.submit_payment("dave", amount=70, tx_time=2, anti_spam_nonce=72)
                self._assign_cluster_order(accounts, rng.choice(("consensus-0", "consensus-2")), ("consensus-0", "consensus-2"))
                third = carol.submit_payment("alice", amount=20, tx_time=3, anti_spam_nonce=73)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(consensus1.consensus.chain.current_height, 1)

                consensus1_network.start()
                self._assign_cluster_order(accounts, "consensus-1", consensus_ids)
                fourth = dave.submit_payment("bob", amount=30, tx_time=4, anti_spam_nonce=74)

                self.assertEqual(fourth.receipt_height, 4)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 4), 4)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 4), 4)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus1.consensus.chain.current_block_hash)
                self.assertEqual(consensus0.consensus.chain.current_block_hash, consensus2.consensus.chain.current_block_hash)
            finally:
                dave_network.stop()
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()
