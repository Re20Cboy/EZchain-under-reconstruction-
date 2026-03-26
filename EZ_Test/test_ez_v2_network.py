from dataclasses import replace
import tempfile
import unittest
import socket
import time
import random
from pathlib import Path

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, open_static_network
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import ChainSyncCursor
from EZ_V2.networking import MSG_BLOCK_ANNOUNCE, MSG_BLOCK_FETCH_REQ, MSG_BLOCK_FETCH_RESP, MSG_CONSENSUS_PROPOSAL, NetworkEnvelope
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.consensus import Proposal, QC, VotePhase, qc_hash
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair, keccak256
from EZ_V2.network_host import V2ConsensusHost
from EZ_V2.values import ValueRange


class EZV2NetworkSmokeTest(unittest.TestCase):
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
    def _wait_for_receipt_count(account: V2AccountHost, expected_count: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            count = len(account.wallet.list_receipts())
            if count >= expected_count:
                return count
            time.sleep(0.01)
        return len(account.wallet.list_receipts())

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

    def test_static_network_mvp_consensus_round_commits_block_across_four_consensus_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=904,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=904,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=904,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=10)
                self.assertIsNone(payment.receipt_height)
                self.assertEqual(consensus_hosts[0].consensus.chain.current_height, 0)

                result = consensus_hosts[0].run_mvp_consensus_round(consensus_peer_ids=validator_ids)

                self.assertEqual(result["status"], "committed")
                self.assertEqual(result["height"], 1)
                for consensus in consensus_hosts:
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertIsNotNone(alice.refresh_chain_state())
                assert alice.last_seen_chain is not None
                self.assertEqual(alice.last_seen_chain.height, 1)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()
