from __future__ import annotations

import socket
import tempfile
import time
import unittest

from EZ_V2.consensus import Proposal, QC, VotePhase, qc_hash
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import MSG_CONSENSUS_PROPOSAL, NetworkEnvelope, PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


class EZV2NetworkProposalValidationTests(unittest.TestCase):
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

    def test_static_network_mvp_rejects_proposal_with_block_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=909,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=909,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                first_recovery = alice.recover_network_state()
                self.assertEqual(first_recovery.applied_genesis_values, 1)
                bob.recover_network_state()

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=41)
                self.assertIsNone(payment.receipt_height)

                block, _ = consensus_hosts["consensus-0"].consensus.preview_block()
                validator_set_hash = consensus_hosts["consensus-1"]._consensus_core.validator_set.validator_set_hash
                proposal = Proposal(
                    chain_id=909,
                    epoch_id=0,
                    height=block.header.height,
                    round=1,
                    proposer_id="consensus-0",
                    validator_set_hash=validator_set_hash,
                    block_hash=b"\xaa" * 32,
                )

                response = network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CONSENSUS_PROPOSAL,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "proposal": proposal,
                            "block": block,
                            "phase": VotePhase.PREPARE,
                            "justify_qc": None,
                        },
                    )
                )

                assert response is not None
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "proposal_block_hash_mismatch")
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_static_network_mvp_rejects_locked_branch_conflict_over_network(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=910,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-1",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=910,
                network=network,
                consensus_peer_id="consensus-1",
            )
            try:
                minted = ValueRange(0, 299)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                timeout_result = consensus_hosts["consensus-0"].run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["next_round"], 2)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=51)
                self.assertIsNone(first.receipt_height)
                commit_result = consensus_hosts["consensus-1"].run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )
                self.assertEqual(commit_result["status"], "committed")
                self.assertEqual(consensus_hosts["consensus-1"]._consensus_core.locked_qc.round, 2)

                alice.set_consensus_peer_id("consensus-0")
                second = alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=52)
                self.assertIsNone(second.receipt_height)
                block, _ = consensus_hosts["consensus-0"].consensus.preview_block()

                validator_set_hash = consensus_hosts["consensus-1"]._consensus_core.validator_set.validator_set_hash
                lower_qc = QC(
                    chain_id=910,
                    epoch_id=0,
                    height=1,
                    round=1,
                    phase=VotePhase.PREPARE,
                    validator_set_hash=validator_set_hash,
                    block_hash=b"\xbb" * 32,
                    signers=("consensus-0", "consensus-1", "consensus-2"),
                )
                proposal = Proposal(
                    chain_id=910,
                    epoch_id=0,
                    height=block.header.height,
                    round=2,
                    proposer_id="consensus-0",
                    validator_set_hash=validator_set_hash,
                    block_hash=block.block_hash,
                    justify_qc_hash=qc_hash(lower_qc),
                )

                response = network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CONSENSUS_PROPOSAL,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "proposal": proposal,
                            "block": block,
                            "phase": VotePhase.PREPARE,
                            "justify_qc": lower_qc,
                        },
                    )
                )

                assert response is not None
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "proposal justify_qc is below locked qc")
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_rejects_proposal_with_block_hash_mismatch(self) -> None:
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
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus3 = V2ConsensusHost(
                node_id="consensus-3",
                endpoint=peer_map["consensus-3"].endpoint,
                store_path=f"{td}/consensus3.sqlite3",
                network=consensus3_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=921,
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
                chain_id=921,
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
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    consensus.register_genesis_value(alice.address, allocation)
                alice.register_genesis_value(allocation)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=141)
                self.assertIsNone(payment.receipt_height)

                block, _ = consensus0.consensus.preview_block()
                validator_set_hash = consensus1._consensus_core.validator_set.validator_set_hash
                proposal = Proposal(
                    chain_id=921,
                    epoch_id=0,
                    height=block.header.height,
                    round=1,
                    proposer_id="consensus-0",
                    validator_set_hash=validator_set_hash,
                    block_hash=b"\xaa" * 32,
                )

                response = consensus0_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CONSENSUS_PROPOSAL,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "proposal": proposal,
                            "block": block,
                            "phase": VotePhase.PREPARE,
                            "justify_qc": None,
                        },
                    )
                )

                assert response is not None
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "proposal_block_hash_mismatch")
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

    def test_tcp_mvp_rejects_locked_branch_conflict_over_network(self) -> None:
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
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/consensus1.sqlite3",
                network=consensus1_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/consensus2.sqlite3",
                network=consensus2_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            consensus3 = V2ConsensusHost(
                node_id="consensus-3",
                endpoint=peer_map["consensus-3"].endpoint,
                store_path=f"{td}/consensus3.sqlite3",
                network=consensus3_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=922,
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
                chain_id=922,
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

                allocation = ValueRange(0, 299)
                for consensus in (consensus0, consensus1, consensus2, consensus3):
                    consensus.register_genesis_value(alice.address, allocation)
                alice.register_genesis_value(allocation)

                timeout_result = consensus0.run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["next_round"], 2)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=151)
                self.assertIsNone(first.receipt_height)
                commit_result = consensus1.run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )
                self.assertEqual(commit_result["status"], "committed")
                self.assertEqual(consensus1._consensus_core.locked_qc.round, 2)

                alice.set_consensus_peer_id("consensus-0")
                second = alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=152)
                self.assertIsNone(second.receipt_height)
                block, _ = consensus0.consensus.preview_block()

                validator_set_hash = consensus1._consensus_core.validator_set.validator_set_hash
                lower_qc = QC(
                    chain_id=922,
                    epoch_id=0,
                    height=1,
                    round=1,
                    phase=VotePhase.PREPARE,
                    validator_set_hash=validator_set_hash,
                    block_hash=b"\xbb" * 32,
                    signers=("consensus-0", "consensus-1", "consensus-2"),
                )
                proposal = Proposal(
                    chain_id=922,
                    epoch_id=0,
                    height=block.header.height,
                    round=2,
                    proposer_id="consensus-0",
                    validator_set_hash=validator_set_hash,
                    block_hash=block.block_hash,
                    justify_qc_hash=qc_hash(lower_qc),
                )

                response = consensus0_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CONSENSUS_PROPOSAL,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "proposal": proposal,
                            "block": block,
                            "phase": VotePhase.PREPARE,
                            "justify_qc": lower_qc,
                        },
                    )
                )

                assert response is not None
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "proposal justify_qc is below locked qc")
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
