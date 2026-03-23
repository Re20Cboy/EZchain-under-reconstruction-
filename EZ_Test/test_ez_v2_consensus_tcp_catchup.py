import random
import socket
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


class EZV2ConsensusTCPCatchupTest(unittest.TestCase):
    @staticmethod
    def _reserve_port() -> int:
        last_exc: Exception | None = None
        for _ in range(20):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(("127.0.0.1", 0))
                    return int(sock.getsockname()[1])
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.01)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("failed_to_reserve_port")

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

    def test_tcp_mvp_timeout_then_restarted_next_proposer_still_commits(self) -> None:
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
                    PeerInfo(node_id="consensus-3", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            consensus3_network = _network_for("consensus-3")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/consensus0.sqlite3",
                network=consensus0_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus3 = V2ConsensusHost(
                node_id="consensus-3",
                endpoint=peer_map["consensus-3"].endpoint,
                store_path=f"{td}/consensus3.sqlite3",
                network=consensus3_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=920,
                network=alice_network,
                consensus_peer_id="consensus-1",
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=920,
                network=bob_network,
                consensus_peer_id="consensus-1",
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    consensus3_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                allocation = ValueRange(0, 199)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    consensus.register_genesis_value(alice.address, allocation)
                alice.register_genesis_value(allocation)

                timeout_result = consensus0.run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["next_round"], 2)

                consensus1_network.stop()
                consensus1.close()
                consensus1_network = _network_for("consensus-1")
                consensus1 = V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint=peer_map["consensus-1"].endpoint,
                    store_path=f"{td}/consensus1.sqlite3",
                    network=consensus1_network,
                    chain_id=920,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                consensus1.register_genesis_value(alice.address, allocation)
                consensus1_network.start()
                restarted_snapshot = consensus1.validate_runtime_state()
                self.assertEqual(restarted_snapshot.current_round, 2)
                self.assertEqual(restarted_snapshot.highest_tc_round, 1)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=131)
                self.assertIsNone(payment.receipt_height)

                result = consensus1.run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )

                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus3_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus3.close()
                consensus2.close()
                consensus1.close()
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
                time.sleep(0.1)

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
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1, timeout_sec=3.0), 1)

                consensus1_network.stop()
                self._assign_cluster_order(accounts, rng.choice(("consensus-0", "consensus-2")), ("consensus-0", "consensus-2"))
                second = bob.submit_payment("dave", amount=70, tx_time=2, anti_spam_nonce=72)
                self._assign_cluster_order(accounts, rng.choice(("consensus-0", "consensus-2")), ("consensus-0", "consensus-2"))
                third = carol.submit_payment("alice", amount=20, tx_time=3, anti_spam_nonce=73)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(third.receipt_height, 3)

                consensus1_network = _network_for("consensus-1")
                consensus1 = V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint=peer_map["consensus-1"].endpoint,
                    store_path=f"{td}/consensus1.sqlite3",
                    network=consensus1_network,
                    chain_id=917,
                )
                consensus1_network.start()
                self.assertEqual(consensus1.recover_chain_from_consensus_peers(), (2, 3))
                self.assertEqual(self._wait_for_consensus_height(consensus1, 3, timeout_sec=3.0), 3)

                self._assign_cluster_order(accounts, rng.choice(consensus_ids), consensus_ids)
                fourth = dave.submit_payment("bob", amount=30, tx_time=4, anti_spam_nonce=74)
                self.assertEqual(fourth.receipt_height, 4)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 4, timeout_sec=3.0), 4)
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
