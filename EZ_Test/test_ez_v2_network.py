import tempfile
import unittest
import socket
import time

from EZ_V2.network_host import V2AccountHost, open_static_network
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import ChainSyncCursor
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
