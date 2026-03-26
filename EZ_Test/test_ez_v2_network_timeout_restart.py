from __future__ import annotations

import socket
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


class EZV2NetworkTimeoutRestartTests(unittest.TestCase):
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

    def test_static_network_mvp_proposer_restart_recovers_consensus_state_and_commits_next_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = [
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=906,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=(validator_id == "consensus-0"),
                )
                for validator_id in validator_ids
            ]
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 299)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=21)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(consensus_hosts[0]._consensus_core.pacemaker.last_decided_round, 1)
                initial_snapshot = consensus_hosts[0].validate_runtime_state()
                self.assertEqual(initial_snapshot.chain_height, 1)
                self.assertEqual(initial_snapshot.current_round, 2)
                self.assertEqual(initial_snapshot.last_decided_round, 1)

                consensus_hosts[0].close()
                consensus_hosts[0] = V2ConsensusHost(
                    node_id="consensus-0",
                    endpoint="mem://consensus-0",
                    store_path=f"{td}/consensus-0.sqlite3",
                    network=network,
                    chain_id=906,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                )
                consensus_hosts[0].register_genesis_value(alice.address, minted)
                restarted_snapshot = consensus_hosts[0].validate_runtime_state()
                self.assertEqual(restarted_snapshot.chain_height, 1)
                self.assertEqual(restarted_snapshot.last_decided_round, 1)
                self.assertEqual(restarted_snapshot.current_round, 2)

                second = alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=22)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(consensus_hosts[0].consensus.chain.current_height, 2)
                self.assertEqual(consensus_hosts[0]._consensus_core.pacemaker.last_decided_round, 2)
                final_snapshot = consensus_hosts[0].validate_runtime_state()
                self.assertEqual(final_snapshot.chain_height, 2)
                self.assertEqual(final_snapshot.current_round, 3)
                self.assertEqual(final_snapshot.last_decided_round, 2)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()

    def test_static_network_mvp_timeout_round_advances_all_consensus_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=907,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            )
            try:
                result = consensus_hosts[0].run_mvp_timeout_round(consensus_peer_ids=validator_ids)

                self.assertEqual(result["status"], "timed_out")
                self.assertEqual(result["round"], 1)
                self.assertEqual(result["next_round"], 2)
                self.assertEqual(result["tc_signers"], validator_ids)
                timeout_snapshot = result["runtime_snapshot"]
                self.assertEqual(timeout_snapshot.current_round, 2)
                self.assertEqual(timeout_snapshot.highest_tc_round, 1)
                for consensus in consensus_hosts:
                    snapshot = consensus.validate_runtime_state()
                    self.assertEqual(snapshot.current_round, 2)
                    self.assertEqual(snapshot.last_decided_round, 0)
                    self.assertEqual(snapshot.highest_tc_round, 1)
            finally:
                for consensus in reversed(consensus_hosts):
                    consensus.close()

    def test_static_network_mvp_timeout_allows_next_proposer_to_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=908,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=908,
                network=network,
                consensus_peer_id="consensus-1",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=908,
                network=network,
                consensus_peer_id="consensus-1",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                first_recovery = alice.recover_network_state()
                self.assertEqual(first_recovery.applied_genesis_values, 1)
                bob.recover_network_state()

                timeout_result = consensus_hosts["consensus-0"].run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["next_round"], 2)
                self.assertEqual(timeout_result["runtime_snapshot"].highest_tc_round, 1)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=31)
                self.assertIsNone(payment.receipt_height)

                commit_result = consensus_hosts["consensus-1"].run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )

                self.assertEqual(commit_result["status"], "committed")
                self.assertEqual(commit_result["height"], 1)
                commit_snapshot = commit_result["runtime_snapshot"]
                self.assertEqual(commit_snapshot.chain_height, 1)
                self.assertEqual(commit_snapshot.current_round, 3)
                self.assertEqual(commit_snapshot.last_decided_round, 2)
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                    self.assertEqual(consensus._consensus_core.pacemaker.last_decided_round, 2)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_static_network_mvp_timeout_state_survives_restart_and_commits_next_round(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=911,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=911,
                network=network,
                consensus_peer_id="consensus-1",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=911,
                network=network,
                consensus_peer_id="consensus-1",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                first_recovery = alice.recover_network_state()
                self.assertEqual(first_recovery.applied_genesis_values, 1)
                bob.recover_network_state()

                timeout_result = consensus_hosts["consensus-0"].run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["next_round"], 2)
                self.assertEqual(consensus_hosts["consensus-2"]._consensus_core.pacemaker.current_round, 2)

                consensus_hosts["consensus-2"].close()
                consensus_hosts["consensus-2"] = V2ConsensusHost(
                    node_id="consensus-2",
                    endpoint="mem://consensus-2",
                    store_path=f"{td}/consensus-2.sqlite3",
                    network=network,
                    chain_id=911,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                consensus_hosts["consensus-2"].register_genesis_value(alice.address, minted)
                self.assertEqual(consensus_hosts["consensus-2"]._consensus_core.pacemaker.current_round, 2)
                self.assertEqual(consensus_hosts["consensus-2"]._consensus_core.pacemaker.highest_tc_round, 1)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=61)
                self.assertIsNone(payment.receipt_height)
                commit_result = consensus_hosts["consensus-1"].run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )

                self.assertEqual(commit_result["status"], "committed")
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(consensus_hosts["consensus-2"]._consensus_core.pacemaker.last_decided_round, 2)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob.close()
                alice.close()
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
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus3 = V2ConsensusHost(
                node_id="consensus-3",
                endpoint=peer_map["consensus-3"].endpoint,
                store_path=f"{td}/consensus3.sqlite3",
                network=consensus3_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=919,
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
                chain_id=919,
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
                alice.recover_network_state()
                bob.recover_network_state()

                timeout_result = consensus0.run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["status"], "timed_out")
                self.assertEqual(timeout_result["next_round"], 2)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=121)
                self.assertIsNone(payment.receipt_height)

                result = consensus1.run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )

                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                    self.assertEqual(consensus._consensus_core.pacemaker.last_decided_round, 2)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
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


if __name__ == "__main__":
    unittest.main()
