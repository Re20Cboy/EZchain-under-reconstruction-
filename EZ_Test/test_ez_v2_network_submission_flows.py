from __future__ import annotations

import socket
import tempfile
import time
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost, open_static_network
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import ChainSyncCursor, PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


class EZV2NetworkSubmissionFlowTests(unittest.TestCase):
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

    @staticmethod
    def _wait_for_consensus_height(consensus: V2ConsensusHost, expected_height: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if consensus.consensus.chain.current_height >= expected_height:
                return consensus.consensus.chain.current_height
            time.sleep(0.01)
        return consensus.consensus.chain.current_height

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
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_static_network_mvp_auto_round_commits_two_sequential_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=905,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=(validator_id == "consensus-0"),
                )
                for validator_id in validator_ids
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=905,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=905,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 299)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=11)
                second = alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=12)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                for consensus in consensus_hosts:
                    self.assertEqual(consensus.consensus.chain.current_height, 2)
                self.assertEqual(bob.wallet.available_balance(), 75)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()

    def test_static_network_mvp_windowed_auto_round_batches_two_senders_into_one_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=931,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                    auto_run_mvp_consensus_window_sec=0.2,
                )
                for validator_id in validator_ids
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=931,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=931,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=931,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted_alice = ValueRange(0, 199)
                minted_carol = ValueRange(200, 399)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted_alice)
                    consensus.register_genesis_value(carol.address, minted_carol)
                alice.register_genesis_value(minted_alice)
                carol.register_genesis_value(minted_carol)
                for consensus in consensus_hosts:
                    if consensus.peer.node_id == "consensus-0":
                        consensus.select_mvp_proposer = lambda **_: {
                            "selected_proposer_id": "consensus-0",
                            "ordered_consensus_peer_ids": ("consensus-0", "consensus-1", "consensus-2", "consensus-3"),
                            "height": 1,
                            "round": 1,
                            "seed_hex": "",
                            "claims_total": 4,
                        }
                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=301)
                second = carol.submit_payment("bob", amount=30, tx_time=2, anti_spam_nonce=302)
                self.assertIsNone(first.receipt_height)
                self.assertIsNone(second.receipt_height)
                tick = consensus_hosts[0].drive_auto_mvp_consensus_tick(force=True)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(tick["height"], 1)
                for consensus in consensus_hosts:
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                block = consensus_hosts[0].consensus.store.get_block_by_height(1)
                assert block is not None
                self.assertEqual(len(block.diff_package.sidecars), 2)
                self.assertEqual(len(block.diff_package.diff_entries), 2)
                alice.recover_network_state()
                carol.recover_network_state()
                bob.recover_network_state()
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(carol, 1), 1)
                self.assertEqual(alice.wallet.available_balance(), 150)
                self.assertEqual(carol.wallet.available_balance(), 170)
                self.assertEqual(bob.wallet.available_balance(), 80)
            finally:
                bob.close()
                carol.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()

    def test_static_network_mvp_auto_round_forwards_bundle_to_selected_proposer_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=925,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=(validator_id == "consensus-0"),
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=925,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=925,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 299)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                consensus_hosts["consensus-0"].select_mvp_proposer = lambda **_: {
                    "selected_proposer_id": "consensus-1",
                    "ordered_consensus_peer_ids": ("consensus-1", "consensus-0", "consensus-2", "consensus-3"),
                    "height": 1,
                    "round": 1,
                    "seed_hex": "",
                    "claims_total": 4,
                }
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=211)
                self.assertEqual(payment.receipt_height, 1)
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
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
                bob.close()
                alice.close()
                consensus.close()


if __name__ == "__main__":
    unittest.main()
