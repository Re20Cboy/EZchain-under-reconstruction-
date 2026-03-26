from __future__ import annotations

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


class EZV2NetworkTCPClusterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
