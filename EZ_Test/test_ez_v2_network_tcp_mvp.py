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


class EZV2NetworkTCPMVPTests(unittest.TestCase):
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
    def _wait_for_receipt_count(account: V2AccountHost, expected_count: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            count = len(account.wallet.list_receipts())
            if count >= expected_count:
                return count
            time.sleep(0.01)
        return len(account.wallet.list_receipts())

    def test_tcp_mvp_consensus_round_commits_block_across_four_consensus_hosts(self) -> None:
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

            consensus0 = V2ConsensusHost(node_id="consensus-0", endpoint=peer_map["consensus-0"].endpoint, store_path=f"{td}/consensus0.sqlite3", network=consensus0_network, chain_id=918, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus1 = V2ConsensusHost(node_id="consensus-1", endpoint=peer_map["consensus-1"].endpoint, store_path=f"{td}/consensus1.sqlite3", network=consensus1_network, chain_id=918, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus2 = V2ConsensusHost(node_id="consensus-2", endpoint=peer_map["consensus-2"].endpoint, store_path=f"{td}/consensus2.sqlite3", network=consensus2_network, chain_id=918, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus3 = V2ConsensusHost(node_id="consensus-3", endpoint=peer_map["consensus-3"].endpoint, store_path=f"{td}/consensus3.sqlite3", network=consensus3_network, chain_id=918, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            alice = V2AccountHost(node_id="alice", endpoint=peer_map["alice"].endpoint, wallet_db_path=f"{td}/alice.sqlite3", chain_id=918, network=alice_network, consensus_peer_id="consensus-0", address=alice_addr, private_key_pem=alice_private, public_key_pem=alice_public)
            bob = V2AccountHost(node_id="bob", endpoint=peer_map["bob"].endpoint, wallet_db_path=f"{td}/bob.sqlite3", chain_id=918, network=bob_network, consensus_peer_id="consensus-0", address=bob_addr, private_key_pem=bob_private, public_key_pem=bob_public)
            try:
                try:
                    consensus0_network.start(); consensus1_network.start(); consensus2_network.start(); consensus3_network.start(); alice_network.start(); bob_network.start()
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

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=111)
                self.assertIsNone(payment.receipt_height)
                self.assertEqual(consensus0.consensus.chain.current_height, 0)

                result = consensus0.run_mvp_consensus_round(consensus_peer_ids=validator_ids)

                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(self._wait_for_chain_height(bob, 1), 1)
            finally:
                bob_network.stop(); alice_network.stop(); consensus3_network.stop(); consensus2_network.stop(); consensus1_network.stop(); consensus0_network.stop()
                bob.close(); alice.close(); consensus3.close(); consensus2.close(); consensus1.close(); consensus0.close()

    def test_tcp_mvp_auto_round_commits_payment_from_account_submit(self) -> None:
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
                return TransportPeerNetwork(TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])), peers)

            consensus0_network = _network_for("consensus-0"); consensus1_network = _network_for("consensus-1"); consensus2_network = _network_for("consensus-2"); consensus3_network = _network_for("consensus-3"); alice_network = _network_for("alice"); bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(node_id=validator_id, endpoint=peer_map[validator_id].endpoint, store_path=f"{td}/{validator_id}.sqlite3", network={"consensus-0": consensus0_network, "consensus-1": consensus1_network, "consensus-2": consensus2_network, "consensus-3": consensus3_network}[validator_id], chain_id=919, consensus_mode="mvp", consensus_validator_ids=validator_ids, auto_run_mvp_consensus=True)
                for validator_id in validator_ids
            }
            alice = V2AccountHost(node_id="alice", endpoint=peer_map["alice"].endpoint, wallet_db_path=f"{td}/alice.sqlite3", chain_id=919, network=alice_network, consensus_peer_id="consensus-0", address=alice_addr, private_key_pem=alice_private, public_key_pem=alice_public)
            bob = V2AccountHost(node_id="bob", endpoint=peer_map["bob"].endpoint, wallet_db_path=f"{td}/bob.sqlite3", chain_id=919, network=bob_network, consensus_peer_id="consensus-0", address=bob_addr, private_key_pem=bob_private, public_key_pem=bob_public)
            try:
                try:
                    consensus0_network.start(); consensus1_network.start(); consensus2_network.start(); consensus3_network.start(); alice_network.start(); bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                first_recovery = alice.recover_network_state()
                self.assertEqual(first_recovery.applied_genesis_values, 1)
                bob.recover_network_state()

                consensus_hosts["consensus-0"].select_mvp_proposer = lambda **_: {"selected_proposer_id": "consensus-0", "ordered_consensus_peer_ids": ("consensus-0", "consensus-1", "consensus-2", "consensus-3"), "height": 1, "round": 1, "seed_hex": "", "claims_total": 4}

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=191)

                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertIn(payment.receipt_height, (None, 1))
                recovery = alice.recover_network_state()
                self.assertIn(recovery.applied_receipts, (0, 1))
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(self._wait_for_chain_height(bob, 1), 1)
            finally:
                bob_network.stop(); alice_network.stop(); consensus3_network.stop(); consensus2_network.stop(); consensus1_network.stop(); consensus0_network.stop()
                bob.close(); alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_auto_round_forwards_bundle_to_selected_proposer_and_commits(self) -> None:
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
                return TransportPeerNetwork(TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])), peers)
            consensus0_network = _network_for("consensus-0"); consensus1_network = _network_for("consensus-1"); consensus2_network = _network_for("consensus-2"); consensus3_network = _network_for("consensus-3"); alice_network = _network_for("alice"); bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(node_id=validator_id, endpoint=peer_map[validator_id].endpoint, store_path=f"{td}/{validator_id}.sqlite3", network={"consensus-0": consensus0_network, "consensus-1": consensus1_network, "consensus-2": consensus2_network, "consensus-3": consensus3_network}[validator_id], chain_id=926, consensus_mode="mvp", consensus_validator_ids=validator_ids, auto_run_mvp_consensus=True)
                for validator_id in validator_ids
            }
            alice = V2AccountHost(node_id="alice", endpoint=peer_map["alice"].endpoint, wallet_db_path=f"{td}/alice.sqlite3", chain_id=926, network=alice_network, consensus_peer_id="consensus-0", address=alice_addr, private_key_pem=alice_private, public_key_pem=alice_public)
            bob = V2AccountHost(node_id="bob", endpoint=peer_map["bob"].endpoint, wallet_db_path=f"{td}/bob.sqlite3", chain_id=926, network=bob_network, consensus_peer_id="consensus-0", address=bob_addr, private_key_pem=bob_private, public_key_pem=bob_public)
            try:
                try:
                    consensus0_network.start(); consensus1_network.start(); consensus2_network.start(); consensus3_network.start(); alice_network.start(); bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.recover_network_state(); bob.recover_network_state()
                consensus_hosts["consensus-0"].select_mvp_proposer = lambda **_: {"selected_proposer_id": "consensus-1", "ordered_consensus_peer_ids": ("consensus-1", "consensus-0", "consensus-2", "consensus-3"), "height": 1, "round": 1, "seed_hex": "", "claims_total": 4}
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=291)
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertIn(payment.receipt_height, (None, 1))
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(self._wait_for_chain_height(bob, 1), 1)
            finally:
                bob_network.stop(); alice_network.stop(); consensus3_network.stop(); consensus2_network.stop(); consensus1_network.stop(); consensus0_network.stop()
                bob.close(); alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_commit_succeeds_without_account_peers_registered_on_consensus_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_private, alice_public = generate_secp256k1_keypair()
            bob_private, bob_public = generate_secp256k1_keypair()
            alice_addr = address_from_public_key_pem(alice_public)
            bob_addr = address_from_public_key_pem(bob_public)
            try:
                consensus_peers = (
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-3", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                )
                account_peers = (
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            consensus_peer_map = {peer.node_id: peer for peer in consensus_peers}
            account_peer_map = {peer.node_id: peer for peer in account_peers}
            def _network_for_consensus(peer_id: str) -> TransportPeerNetwork:
                return TransportPeerNetwork(TCPNetworkTransport("127.0.0.1", int(consensus_peer_map[peer_id].endpoint.rsplit(":", 1)[1])), consensus_peers)
            def _network_for_account(peer_id: str) -> TransportPeerNetwork:
                all_peers = (*consensus_peers, *account_peers)
                endpoint = account_peer_map[peer_id].endpoint
                return TransportPeerNetwork(TCPNetworkTransport("127.0.0.1", int(endpoint.rsplit(":", 1)[1])), all_peers)
            consensus0_network = _network_for_consensus("consensus-0"); consensus1_network = _network_for_consensus("consensus-1"); consensus2_network = _network_for_consensus("consensus-2"); consensus3_network = _network_for_consensus("consensus-3"); alice_network = _network_for_account("alice"); bob_network = _network_for_account("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(node_id=validator_id, endpoint=consensus_peer_map[validator_id].endpoint, store_path=f"{td}/{validator_id}.sqlite3", network={"consensus-0": consensus0_network, "consensus-1": consensus1_network, "consensus-2": consensus2_network, "consensus-3": consensus3_network}[validator_id], chain_id=927, consensus_mode="mvp", consensus_validator_ids=validator_ids, auto_run_mvp_consensus=True)
                for validator_id in validator_ids
            }
            alice = V2AccountHost(node_id="alice", endpoint=account_peer_map["alice"].endpoint, wallet_db_path=f"{td}/alice.sqlite3", chain_id=927, network=alice_network, consensus_peer_id="consensus-0", address=alice_addr, private_key_pem=alice_private, public_key_pem=alice_public)
            bob = V2AccountHost(node_id="bob", endpoint=account_peer_map["bob"].endpoint, wallet_db_path=f"{td}/bob.sqlite3", chain_id=927, network=bob_network, consensus_peer_id="consensus-0", address=bob_addr, private_key_pem=bob_private, public_key_pem=bob_public)
            try:
                for network in (consensus0_network, consensus1_network, consensus2_network, consensus3_network, alice_network, bob_network):
                    network.start()
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.recover_network_state(); bob.recover_network_state()
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=391)
                self.assertIn(payment.receipt_height, (None, 1))
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                recovery = alice.recover_network_state()
                self.assertIn(recovery.applied_receipts, (0, 1))
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
            finally:
                bob_network.stop(); alice_network.stop(); consensus3_network.stop(); consensus2_network.stop(); consensus1_network.stop(); consensus0_network.stop()
                bob.close(); alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_timeout_allows_next_proposer_to_commit(self) -> None:
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
                return TransportPeerNetwork(TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])), peers)
            consensus0_network = _network_for("consensus-0"); consensus1_network = _network_for("consensus-1"); consensus2_network = _network_for("consensus-2"); consensus3_network = _network_for("consensus-3"); alice_network = _network_for("alice"); bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus0 = V2ConsensusHost(node_id="consensus-0", endpoint=peer_map["consensus-0"].endpoint, store_path=f"{td}/consensus0.sqlite3", network=consensus0_network, chain_id=919, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus1 = V2ConsensusHost(node_id="consensus-1", endpoint=peer_map["consensus-1"].endpoint, store_path=f"{td}/consensus1.sqlite3", network=consensus1_network, chain_id=919, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus2 = V2ConsensusHost(node_id="consensus-2", endpoint=peer_map["consensus-2"].endpoint, store_path=f"{td}/consensus2.sqlite3", network=consensus2_network, chain_id=919, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            consensus3 = V2ConsensusHost(node_id="consensus-3", endpoint=peer_map["consensus-3"].endpoint, store_path=f"{td}/consensus3.sqlite3", network=consensus3_network, chain_id=919, consensus_mode="mvp", consensus_validator_ids=validator_ids)
            alice = V2AccountHost(node_id="alice", endpoint=peer_map["alice"].endpoint, wallet_db_path=f"{td}/alice.sqlite3", chain_id=919, network=alice_network, consensus_peer_id="consensus-1", address=alice_addr, private_key_pem=alice_private, public_key_pem=alice_public)
            bob = V2AccountHost(node_id="bob", endpoint=peer_map["bob"].endpoint, wallet_db_path=f"{td}/bob.sqlite3", chain_id=919, network=bob_network, consensus_peer_id="consensus-1", address=bob_addr, private_key_pem=bob_private, public_key_pem=bob_public)
            try:
                try:
                    consensus0_network.start(); consensus1_network.start(); consensus2_network.start(); consensus3_network.start(); alice_network.start(); bob_network.start()
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
                self.assertEqual(timeout_result["status"], "timed_out")
                self.assertEqual(timeout_result["next_round"], 2)
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=121)
                self.assertIsNone(payment.receipt_height)
                result = consensus1.run_mvp_consensus_round(consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3"))
                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                    self.assertEqual(consensus._consensus_core.pacemaker.last_decided_round, 2)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob_network.stop(); alice_network.stop(); consensus3_network.stop(); consensus2_network.stop(); consensus1_network.stop(); consensus0_network.stop()
                bob.close(); alice.close(); consensus3.close(); consensus2.close(); consensus1.close(); consensus0.close()


if __name__ == "__main__":
    unittest.main()
