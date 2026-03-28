from __future__ import annotations

import socket
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair, keccak256
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


class EZV2NetworkSortitionTests(unittest.TestCase):
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

    def test_mvp_validator_keys_depend_on_persisted_cluster_secret(self) -> None:
        validator_ids = ("consensus-0", "consensus-1", "consensus-2")
        with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
            network_a = StaticPeerNetwork()
            host_a = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td_a}/consensus-0.sqlite3",
                network=network_a,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            first_vrf_pubkey = host_a._consensus_core.validator_set.get("consensus-0").vrf_pubkey
            first_vote_pubkey = host_a._consensus_core.validator_set.get("consensus-0").consensus_vote_pubkey
            host_a.close()

            network_a_restart = StaticPeerNetwork()
            host_a_restart = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td_a}/consensus-0.sqlite3",
                network=network_a_restart,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            restart_vrf_pubkey = host_a_restart._consensus_core.validator_set.get("consensus-0").vrf_pubkey
            restart_vote_pubkey = host_a_restart._consensus_core.validator_set.get("consensus-0").consensus_vote_pubkey

            network_b = StaticPeerNetwork()
            host_b = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td_b}/consensus-0.sqlite3",
                network=network_b,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            other_vrf_pubkey = host_b._consensus_core.validator_set.get("consensus-0").vrf_pubkey
            other_vote_pubkey = host_b._consensus_core.validator_set.get("consensus-0").consensus_vote_pubkey
            try:
                self.assertEqual(restart_vrf_pubkey, first_vrf_pubkey)
                self.assertEqual(restart_vote_pubkey, first_vote_pubkey)
                self.assertNotEqual(other_vrf_pubkey, first_vrf_pubkey)
                self.assertNotEqual(other_vote_pubkey, first_vote_pubkey)
            finally:
                host_b.close()
                host_a_restart.close()

    def test_static_network_mvp_sortition_selects_consistent_proposer_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=923,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=923,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=923,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.recover_network_state()
                bob.recover_network_state()

                seed = keccak256(b"static-mvp-sortition-923")
                winner_from_0 = consensus_hosts["consensus-0"].select_mvp_proposer(
                    consensus_peer_ids=validator_ids,
                    seed=seed,
                )
                winner_from_2 = consensus_hosts["consensus-2"].select_mvp_proposer(
                    consensus_peer_ids=validator_ids,
                    seed=seed,
                )
                self.assertEqual(winner_from_0["selected_proposer_id"], winner_from_2["selected_proposer_id"])
                winner_id = winner_from_0["selected_proposer_id"]

                alice.set_consensus_peer_id(winner_id)
                bob.set_consensus_peer_id(winner_id)
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=161)
                self.assertIsNone(payment.receipt_height)

                ordered_ids = tuple(winner_from_0["ordered_consensus_peer_ids"])
                self.assertEqual(ordered_ids[0], winner_id)
                result = consensus_hosts[winner_id].run_mvp_consensus_round(consensus_peer_ids=ordered_ids)

                self.assertEqual(result["status"], "committed")
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_sortition_selects_consistent_proposer_and_commits(self) -> None:
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

            consensus_hosts = {
                "consensus-0": V2ConsensusHost(
                    node_id="consensus-0",
                    endpoint=peer_map["consensus-0"].endpoint,
                    store_path=f"{td}/consensus0.sqlite3",
                    network=consensus0_network,
                    chain_id=924,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                ),
                "consensus-1": V2ConsensusHost(
                    node_id="consensus-1",
                    endpoint=peer_map["consensus-1"].endpoint,
                    store_path=f"{td}/consensus1.sqlite3",
                    network=consensus1_network,
                    chain_id=924,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                ),
                "consensus-2": V2ConsensusHost(
                    node_id="consensus-2",
                    endpoint=peer_map["consensus-2"].endpoint,
                    store_path=f"{td}/consensus2.sqlite3",
                    network=consensus2_network,
                    chain_id=924,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                ),
                "consensus-3": V2ConsensusHost(
                    node_id="consensus-3",
                    endpoint=peer_map["consensus-3"].endpoint,
                    store_path=f"{td}/consensus3.sqlite3",
                    network=consensus3_network,
                    chain_id=924,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                ),
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=924,
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
                chain_id=924,
                network=bob_network,
                consensus_peer_id="consensus-0",
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
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, allocation)
                alice.register_genesis_value(allocation)

                seed = keccak256(b"tcp-mvp-sortition-924")
                winner_from_0 = consensus_hosts["consensus-0"].select_mvp_proposer(
                    consensus_peer_ids=validator_ids,
                    seed=seed,
                )
                winner_from_2 = consensus_hosts["consensus-2"].select_mvp_proposer(
                    consensus_peer_ids=validator_ids,
                    seed=seed,
                )
                self.assertEqual(winner_from_0["selected_proposer_id"], winner_from_2["selected_proposer_id"])
                winner_id = winner_from_0["selected_proposer_id"]
                ordered_ids = tuple(winner_from_0["ordered_consensus_peer_ids"])
                self.assertEqual(ordered_ids[0], winner_id)

                alice.set_consensus_peer_id(winner_id)
                bob.set_consensus_peer_id(winner_id)
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=171)
                self.assertIsNone(payment.receipt_height)

                result = consensus_hosts[winner_id].run_mvp_consensus_round(consensus_peer_ids=ordered_ids)

                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(self._wait_for_chain_height(bob, 1), 1)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus3_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()


if __name__ == "__main__":
    unittest.main()
