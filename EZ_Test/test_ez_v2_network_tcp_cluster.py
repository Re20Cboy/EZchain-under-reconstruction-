from __future__ import annotations

from dataclasses import replace
import socket
import tempfile
import time
import unittest

from EZ_V2.chain import sign_bundle_envelope
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import MSG_BUNDLE_SUBMIT, NetworkEnvelope, PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange
from EZ_V2.wallet import WalletAccountV2


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
    def _wait_for_receipt_count(account: V2AccountHost, expected_count: int, timeout_sec: float = 1.0) -> int:
        deadline = time.time() + max(timeout_sec, 4.0)
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
    def _force_selected_proposer(
        consensus_hosts: tuple[V2ConsensusHost, ...],
        *,
        winner_id: str,
        ordered_ids: tuple[str, ...],
    ) -> None:
        for consensus in consensus_hosts:
            consensus.select_mvp_proposer = lambda **_: {
                "selected_proposer_id": winner_id,
                "ordered_consensus_peer_ids": ordered_ids,
                "height": 1,
                "round": 1,
                "seed_hex": "",
                "claims_total": len(ordered_ids),
            }

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
                self.assertIn(len(fetched), (0, 1))
                if fetched:
                    self.assertEqual(fetched[0].header.height, 1)
                    self.assertEqual(fetched[0].block_hash.hex(), consensus.consensus.chain.current_block_hash.hex())
                cached_block = bob.fetched_blocks.get(1)
                self.assertIsNotNone(cached_block)
                assert cached_block is not None
                self.assertEqual(cached_block.block_hash.hex(), consensus.consensus.chain.current_block_hash.hex())
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

    def test_tcp_windowed_multi_sender_burst_converges_across_consensus_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sender_specs = []
            for index in range(6):
                private_key, public_key = generate_secp256k1_keypair()
                sender_specs.append(
                    {
                        "node_id": f"sender-{index}",
                        "private_key": private_key,
                        "public_key": public_key,
                        "address": address_from_public_key_pem(public_key),
                    }
                )
            recipient_private, recipient_public = generate_secp256k1_keypair()
            recipient_addr = address_from_public_key_pem(recipient_public)

            try:
                peers = [
                    PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="recipient", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": recipient_addr}),
                ]
                for spec in sender_specs:
                    peers.append(
                        PeerInfo(
                            node_id=spec["node_id"],
                            role="account",
                            endpoint=f"127.0.0.1:{self._reserve_port()}",
                            metadata={"address": spec["address"]},
                        )
                    )
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            peer_tuple = tuple(peers)
            peer_map = {peer.node_id: peer for peer in peer_tuple}

            def _network_for(peer_id: str) -> TransportPeerNetwork:
                return TransportPeerNetwork(
                    TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])),
                    peer_tuple,
                )

            consensus_networks = {
                consensus_id: _network_for(consensus_id)
                for consensus_id in ("consensus-0", "consensus-1", "consensus-2")
            }
            account_networks = {
                peer.node_id: _network_for(peer.node_id)
                for peer in peer_tuple
                if peer.role == "account"
            }
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus_hosts = {
                consensus_id: V2ConsensusHost(
                    node_id=consensus_id,
                    endpoint=peer_map[consensus_id].endpoint,
                    store_path=f"{td}/{consensus_id}.sqlite3",
                    network=consensus_networks[consensus_id],
                    chain_id=923,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                    auto_run_mvp_consensus_window_sec=0.2,
                )
                for consensus_id in validator_ids
            }
            recipient = V2AccountHost(
                node_id="recipient",
                endpoint=peer_map["recipient"].endpoint,
                wallet_db_path=f"{td}/recipient.sqlite3",
                chain_id=923,
                network=account_networks["recipient"],
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=recipient_addr,
                private_key_pem=recipient_private,
                public_key_pem=recipient_public,
            )
            sender_accounts = []
            for spec in sender_specs:
                sender_accounts.append(
                    V2AccountHost(
                        node_id=spec["node_id"],
                        endpoint=peer_map[spec["node_id"]].endpoint,
                        wallet_db_path=f"{td}/{spec['node_id']}.sqlite3",
                        chain_id=923,
                        network=account_networks[spec["node_id"]],
                        consensus_peer_id="consensus-1",
                        consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                        address=spec["address"],
                        private_key_pem=spec["private_key"],
                        public_key_pem=spec["public_key"],
                    )
                )
            try:
                try:
                    for network in consensus_networks.values():
                        network.start()
                    for network in account_networks.values():
                        network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                self._force_selected_proposer(
                    tuple(consensus_hosts.values()),
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                amount_per_sender = 25
                for index, sender in enumerate(sender_accounts):
                    minted = ValueRange(index * 1000, index * 1000 + 499)
                    for consensus in consensus_hosts.values():
                        consensus.register_genesis_value(sender.address, minted)
                    sender.register_genesis_value(minted)

                pending_payments = []
                for index, sender in enumerate(sender_accounts):
                    payment = sender.submit_payment(
                        "recipient",
                        amount=amount_per_sender,
                        tx_time=index + 1,
                        anti_spam_nonce=98000 + index,
                    )
                    self.assertIsNone(payment.receipt_height)
                    pending_payments.append(payment)

                pending = consensus_hosts["consensus-0"].consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), len(sender_accounts))

                tick = consensus_hosts["consensus-0"].drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(tick["height"], 1)

                for consensus in consensus_hosts.values():
                    self.assertEqual(self._wait_for_consensus_height(consensus, 1), 1)
                    self.assertEqual(consensus.consensus.chain.bundle_pool.snapshot(), [])

                block = consensus_hosts["consensus-0"].consensus.store.get_block_by_height(1)
                self.assertIsNotNone(block)
                assert block is not None
                self.assertEqual(len(block.diff_package.sidecars), len(sender_accounts))
                self.assertEqual(len(block.diff_package.diff_entries), len(sender_accounts))

                for sender in sender_accounts:
                    self.assertEqual(self._wait_for_receipt_count(sender, 1, timeout_sec=2.0), 1)
                    self.assertEqual(len(sender.wallet.list_receipts()), 1)

                self.assertEqual(recipient.wallet.available_balance(), len(sender_accounts) * amount_per_sender)
                self.assertEqual(len(recipient.received_transfers), len(sender_accounts))
                self.assertEqual(
                    consensus_hosts["consensus-0"].consensus.chain.current_block_hash,
                    consensus_hosts["consensus-1"].consensus.chain.current_block_hash,
                )
                self.assertEqual(
                    consensus_hosts["consensus-0"].consensus.chain.current_block_hash,
                    consensus_hosts["consensus-2"].consensus.chain.current_block_hash,
                )
            finally:
                for network in reversed(tuple(account_networks.values())):
                    network.stop()
                for network in reversed(tuple(consensus_networks.values())):
                    network.stop()
                for sender in reversed(sender_accounts):
                    sender.close()
                recipient.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tcp_mvp_window_accepts_same_bundle_fee_bump_forwarded_from_non_winners(self) -> None:
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/fee-bump-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/fee-bump-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/fee-bump-consensus2.sqlite3",
                network=consensus2_network,
                chain_id=920,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/fee-bump-alice.sqlite3",
                chain_id=920,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/fee-bump-bob.sqlite3",
                chain_id=920,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                alice_value = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, alice_value)
                alice.register_genesis_value(alice_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=920,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=95001,
                    tx_time=1,
                )
                bumped_envelope = replace(
                    original_submission.envelope,
                    fee=1,
                    anti_spam_nonce=95002,
                    sig=b"",
                )
                bumped_submission = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(bumped_envelope, alice_private),
                )

                first_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(first_response, dict)
                assert isinstance(first_response, dict)
                self.assertTrue(first_response.get("ok", False))
                self.assertEqual(first_response.get("status"), "accepted_pending_consensus")

                second_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-2",
                        payload={"submission": bumped_submission},
                    )
                )
                self.assertIsInstance(second_response, dict)
                assert isinstance(second_response, dict)
                self.assertTrue(second_response.get("ok", False))
                self.assertEqual(second_response.get("status"), "accepted_pending_consensus")

                pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].envelope.bundle_hash, original_submission.envelope.bundle_hash)
                self.assertEqual(pending[0].envelope.fee, 1)
                self.assertEqual(pending[0].sidecar.tx_list[0].recipient_addr, bob.address)

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)

                block = consensus0.consensus.store.get_block_by_height(1)
                self.assertIsNotNone(block)
                assert block is not None
                self.assertEqual(block.diff_package.diff_entries[0].bundle_envelope.fee, 1)
                self.assertEqual(block.diff_package.sidecars[0].tx_list[0].recipient_addr, bob.address)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(consensus0.consensus.chain.bundle_pool.snapshot(), [])
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_mvp_window_rejects_old_fee_replay_after_forwarded_fee_bump(self) -> None:
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/replay-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/replay-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/replay-consensus2.sqlite3",
                network=consensus2_network,
                chain_id=921,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/replay-alice.sqlite3",
                chain_id=921,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/replay-bob.sqlite3",
                chain_id=921,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                alice_value = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, alice_value)
                alice.register_genesis_value(alice_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=921,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=96001,
                    tx_time=1,
                )
                bumped_envelope = replace(
                    original_submission.envelope,
                    fee=2,
                    anti_spam_nonce=96002,
                    sig=b"",
                )
                bumped_submission = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(bumped_envelope, alice_private),
                )

                initial_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(initial_response, dict)
                assert isinstance(initial_response, dict)
                self.assertTrue(initial_response.get("ok", False))

                bump_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-2",
                        payload={"submission": bumped_submission},
                    )
                )
                self.assertIsInstance(bump_response, dict)
                assert isinstance(bump_response, dict)
                self.assertTrue(bump_response.get("ok", False))

                replay_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(replay_response, dict)
                assert isinstance(replay_response, dict)
                self.assertFalse(replay_response.get("ok", True))
                self.assertIn("replacement bundle fee too low", str(replay_response.get("error", "")))

                pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].envelope.bundle_hash, original_submission.envelope.bundle_hash)
                self.assertEqual(pending[0].envelope.fee, 2)

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)

                block = consensus0.consensus.store.get_block_by_height(1)
                self.assertIsNotNone(block)
                assert block is not None
                self.assertEqual(block.diff_package.diff_entries[0].bundle_envelope.fee, 2)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_mvp_window_keeps_highest_fee_after_multiple_forwarded_bumps(self) -> None:
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/multi-bump-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/multi-bump-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/multi-bump-consensus2.sqlite3",
                network=consensus2_network,
                chain_id=922,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/multi-bump-alice.sqlite3",
                chain_id=922,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/multi-bump-bob.sqlite3",
                chain_id=922,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                alice_value = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, alice_value)
                alice.register_genesis_value(alice_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=922,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=97001,
                    tx_time=1,
                )
                bump_fee_2 = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(
                        replace(original_submission.envelope, fee=2, anti_spam_nonce=97002, sig=b""),
                        alice_private,
                    ),
                )
                bump_fee_4 = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(
                        replace(original_submission.envelope, fee=4, anti_spam_nonce=97003, sig=b""),
                        alice_private,
                    ),
                )
                stale_fee_1 = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(
                        replace(original_submission.envelope, fee=1, anti_spam_nonce=97004, sig=b""),
                        alice_private,
                    ),
                )

                for recipient_id, submission in (
                    ("consensus-1", original_submission),
                    ("consensus-2", bump_fee_2),
                    ("consensus-1", bump_fee_4),
                ):
                    response = alice_network.send(
                        NetworkEnvelope(
                            msg_type=MSG_BUNDLE_SUBMIT,
                            sender_id="alice",
                            recipient_id=recipient_id,
                            payload={"submission": submission},
                        )
                    )
                    self.assertIsInstance(response, dict)
                    assert isinstance(response, dict)
                    self.assertTrue(response.get("ok", False))
                    self.assertEqual(response.get("status"), "accepted_pending_consensus")

                stale_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-2",
                        payload={"submission": stale_fee_1},
                    )
                )
                self.assertIsInstance(stale_response, dict)
                assert isinstance(stale_response, dict)
                self.assertFalse(stale_response.get("ok", True))
                self.assertIn("replacement bundle fee too low", str(stale_response.get("error", "")))

                pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].envelope.bundle_hash, original_submission.envelope.bundle_hash)
                self.assertEqual(pending[0].envelope.fee, 4)

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)

                block = consensus0.consensus.store.get_block_by_height(1)
                self.assertIsNotNone(block)
                assert block is not None
                self.assertEqual(block.diff_package.diff_entries[0].bundle_envelope.fee, 4)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_mvp_window_deduplicates_identical_submission_replays_before_commit(self) -> None:
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/same-replay-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=924,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/same-replay-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=924,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/same-replay-consensus2.sqlite3",
                network=consensus2_network,
                chain_id=924,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/same-replay-alice.sqlite3",
                chain_id=924,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/same-replay-bob.sqlite3",
                chain_id=924,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                minted = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=924,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=97101,
                    tx_time=1,
                )

                for target_peer_id in ("consensus-0", "consensus-1", "consensus-2", "consensus-0"):
                    response = alice_network.send(
                        NetworkEnvelope(
                            msg_type=MSG_BUNDLE_SUBMIT,
                            sender_id="alice",
                            recipient_id=target_peer_id,
                            payload={"submission": original_submission},
                        )
                    )
                    self.assertIsInstance(response, dict)
                    assert isinstance(response, dict)
                    self.assertTrue(response.get("ok", False))
                    self.assertEqual(response.get("status"), "accepted_pending_consensus")

                winner_pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(winner_pending), 1)
                self.assertEqual(winner_pending[0].envelope.bundle_hash, original_submission.envelope.bundle_hash)
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(consensus2.consensus.chain.bundle_pool.snapshot(), [])

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                for consensus in consensus_hosts:
                    self.assertEqual(self._wait_for_consensus_height(consensus, 1), 1)
                    self.assertEqual(consensus.consensus.chain.bundle_pool.snapshot(), [])

                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(bob.received_transfers), 1)

                replay_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(replay_response, dict)
                assert isinstance(replay_response, dict)
                self.assertFalse(replay_response.get("ok", True))
                self.assertIn("bundle seq is not currently executable", str(replay_response.get("error", "")))
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_mvp_window_keeps_highest_fee_after_commit_replay_and_follower_restart(self) -> None:
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
            consensus1_network = _network_for("consensus-1")
            consensus2_network = _network_for("consensus-2")
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")
            consensus2_store_path = f"{td}/post-commit-restart-consensus2.sqlite3"

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/post-commit-restart-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/post-commit-restart-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=consensus2_store_path,
                network=consensus2_network,
                chain_id=925,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/post-commit-restart-alice.sqlite3",
                chain_id=925,
                network=alice_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/post-commit-restart-bob.sqlite3",
                chain_id=925,
                network=bob_network,
                consensus_peer_id="consensus-1",
                consensus_peer_ids=("consensus-1", "consensus-2", "consensus-0"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                minted = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=925,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=97201,
                    tx_time=1,
                )
                bump_fee_2 = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(
                        replace(original_submission.envelope, fee=2, anti_spam_nonce=97202, sig=b""),
                        alice_private,
                    ),
                )
                bump_fee_4 = replace(
                    original_submission,
                    envelope=sign_bundle_envelope(
                        replace(original_submission.envelope, fee=4, anti_spam_nonce=97203, sig=b""),
                        alice_private,
                    ),
                )

                for recipient_id, submission in (
                    ("consensus-1", original_submission),
                    ("consensus-2", bump_fee_2),
                    ("consensus-1", bump_fee_4),
                ):
                    response = alice_network.send(
                        NetworkEnvelope(
                            msg_type=MSG_BUNDLE_SUBMIT,
                            sender_id="alice",
                            recipient_id=recipient_id,
                            payload={"submission": submission},
                        )
                    )
                    self.assertIsInstance(response, dict)
                    assert isinstance(response, dict)
                    self.assertTrue(response.get("ok", False))
                    self.assertEqual(response.get("status"), "accepted_pending_consensus")

                pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].envelope.bundle_hash, original_submission.envelope.bundle_hash)
                self.assertEqual(pending[0].envelope.fee, 4)

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                for consensus in consensus_hosts:
                    self.assertEqual(self._wait_for_consensus_height(consensus, 1), 1)
                    self.assertEqual(consensus.consensus.chain.bundle_pool.snapshot(), [])

                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)
                first_block = consensus0.consensus.store.get_block_by_height(1)
                self.assertIsNotNone(first_block)
                assert first_block is not None
                self.assertEqual(first_block.diff_package.diff_entries[0].bundle_envelope.fee, 4)
                self.assertEqual(bob.wallet.available_balance(), 50)

                consensus2.close()
                consensus2 = V2ConsensusHost(
                    node_id="consensus-2",
                    endpoint=peer_map["consensus-2"].endpoint,
                    store_path=consensus2_store_path,
                    network=consensus2_network,
                    chain_id=925,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                    auto_run_mvp_consensus_window_sec=0.2,
                )
                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(consensus2.consensus.chain.bundle_pool.snapshot(), [])

                replay_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-2",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(replay_response, dict)
                assert isinstance(replay_response, dict)
                self.assertFalse(replay_response.get("ok", True))
                self.assertIn("bundle seq is not currently executable", str(replay_response.get("error", "")))
                self.assertEqual(consensus2.consensus.chain.bundle_pool.snapshot(), [])

                second_payment = alice.submit_payment("bob", amount=20, tx_time=2, anti_spam_nonce=97204)
                self.assertIsNone(second_payment.receipt_height)

                tick2 = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick2)
                assert tick2 is not None
                self.assertEqual(tick2["status"], "committed")
                for consensus in consensus_hosts:
                    self.assertEqual(self._wait_for_consensus_height(consensus, 2), 2)
                    self.assertEqual(consensus.consensus.chain.bundle_pool.snapshot(), [])

                self.assertEqual(self._wait_for_receipt_count(alice, 2, timeout_sec=2.0), 2)
                self.assertEqual(bob.wallet.available_balance(), 70)
            finally:
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
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

    def test_tcp_cluster_rejects_replayed_committed_bundle_after_follower_catchup(self) -> None:
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
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
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
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            carol_network = _network_for("carol")

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
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=917,
                network=alice_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
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
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
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
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                alice_value = ValueRange(0, 199)
                carol_value = ValueRange(200, 399)
                for consensus in (consensus0, consensus1):
                    consensus.register_genesis_value(alice.address, alice_value)
                    consensus.register_genesis_value(carol.address, carol_value)
                alice.register_genesis_value(alice_value)
                carol.register_genesis_value(carol_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=917,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=92001,
                    tx_time=1,
                )
                first_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-0",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(first_response, dict)
                assert isinstance(first_response, dict)
                self.assertTrue(first_response.get("ok", False))
                self.assertEqual(self._wait_for_receipt_count(alice, 1, timeout_sec=2.0), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)

                second_payment = carol.submit_payment("bob", amount=20, tx_time=2, anti_spam_nonce=92002)
                third_payment = carol.submit_payment("bob", amount=10, tx_time=3, anti_spam_nonce=92003)
                self.assertEqual(second_payment.receipt_height, 2)
                self.assertEqual(third_payment.receipt_height, 3)
                self.assertEqual(self._wait_for_consensus_height(consensus0, 3), 3)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 3), 3)
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])

                replay_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(replay_response, dict)
                assert isinstance(replay_response, dict)
                self.assertFalse(replay_response.get("ok", True))
                self.assertIn("bundle seq is not currently executable", str(replay_response.get("error", "")))

                self.assertEqual(consensus0.consensus.chain.current_height, 3)
                self.assertEqual(consensus1.consensus.chain.current_height, 3)
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 80)
            finally:
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                carol.close()
                bob.close()
                alice.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_cluster_rejects_conflicting_same_seq_bundle_after_follower_catchup(self) -> None:
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
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
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
            alice_network = _network_for("alice")
            bob_network = _network_for("bob")
            carol_network = _network_for("carol")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/conflict-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=918,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/conflict-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=918,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/conflict-alice.sqlite3",
                chain_id=918,
                network=alice_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/conflict-bob.sqlite3",
                chain_id=918,
                network=bob_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint=peer_map["carol"].endpoint,
                wallet_db_path=f"{td}/conflict-carol.sqlite3",
                chain_id=918,
                network=carol_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=("consensus-0", "consensus-1"),
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            offline_alice = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\x00" * 32,
                db_path=f"{td}/offline-alice.sqlite3",
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                alice_value = ValueRange(0, 199)
                carol_value = ValueRange(200, 399)
                for consensus in (consensus0, consensus1):
                    consensus.register_genesis_value(alice.address, alice_value)
                    consensus.register_genesis_value(carol.address, carol_value)
                alice.register_genesis_value(alice_value)
                carol.register_genesis_value(carol_value)
                offline_alice.add_genesis_value(alice_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=918,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=93001,
                    tx_time=1,
                )
                conflicting_submission, _, _ = offline_alice.build_payment_bundle(
                    recipient_addr=carol.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=918,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=93002,
                    tx_time=1,
                    seq=1,
                )

                first_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-0",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(first_response, dict)
                assert isinstance(first_response, dict)
                self.assertTrue(first_response.get("ok", False))
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)

                second_payment = carol.submit_payment("bob", amount=20, tx_time=2, anti_spam_nonce=93003)
                self.assertEqual(second_payment.receipt_height, 2)
                self.assertEqual(self._wait_for_consensus_height(consensus0, 2), 2)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 2), 2)

                conflict_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": conflicting_submission},
                    )
                )
                self.assertIsInstance(conflict_response, dict)
                assert isinstance(conflict_response, dict)
                self.assertFalse(conflict_response.get("ok", True))
                self.assertIn("bundle seq is not currently executable", str(conflict_response.get("error", "")))

                self.assertEqual(consensus0.consensus.chain.current_height, 2)
                self.assertEqual(consensus1.consensus.chain.current_height, 2)
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(bob.wallet.available_balance(), 70)
                self.assertEqual(carol.wallet.available_balance(), 180)
            finally:
                offline_alice.close()
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                carol.close()
                bob.close()
                alice.close()
                consensus1.close()
                consensus0.close()

    def test_tcp_mvp_window_rejects_conflicting_cross_endpoint_replacement_with_higher_fee(self) -> None:
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
                    PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{self._reserve_port()}"),
                    PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": alice_addr}),
                    PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": bob_addr}),
                    PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{self._reserve_port()}", metadata={"address": carol_addr}),
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
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")

            consensus0 = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=peer_map["consensus-0"].endpoint,
                store_path=f"{td}/window-consensus0.sqlite3",
                network=consensus0_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus1 = V2ConsensusHost(
                node_id="consensus-1",
                endpoint=peer_map["consensus-1"].endpoint,
                store_path=f"{td}/window-consensus1.sqlite3",
                network=consensus1_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            consensus2 = V2ConsensusHost(
                node_id="consensus-2",
                endpoint=peer_map["consensus-2"].endpoint,
                store_path=f"{td}/window-consensus2.sqlite3",
                network=consensus2_network,
                chain_id=919,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.2,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint=peer_map["alice"].endpoint,
                wallet_db_path=f"{td}/window-alice.sqlite3",
                chain_id=919,
                network=alice_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=validator_ids,
                address=alice_addr,
                private_key_pem=alice_private,
                public_key_pem=alice_public,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint=peer_map["bob"].endpoint,
                wallet_db_path=f"{td}/window-bob.sqlite3",
                chain_id=919,
                network=bob_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=validator_ids,
                address=bob_addr,
                private_key_pem=bob_private,
                public_key_pem=bob_public,
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint=peer_map["carol"].endpoint,
                wallet_db_path=f"{td}/window-carol.sqlite3",
                chain_id=919,
                network=carol_network,
                consensus_peer_id="consensus-0",
                consensus_peer_ids=validator_ids,
                address=carol_addr,
                private_key_pem=carol_private,
                public_key_pem=carol_public,
            )
            offline_alice = WalletAccountV2(
                address=alice_addr,
                genesis_block_hash=b"\x00" * 32,
                db_path=f"{td}/window-offline-alice.sqlite3",
            )
            try:
                try:
                    consensus0_network.start()
                    consensus1_network.start()
                    consensus2_network.start()
                    alice_network.start()
                    bob_network.start()
                    carol_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                consensus_hosts = (consensus0, consensus1, consensus2)
                self._force_selected_proposer(
                    consensus_hosts,
                    winner_id="consensus-0",
                    ordered_ids=validator_ids,
                )

                alice_value = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, alice_value)
                alice.register_genesis_value(alice_value)
                offline_alice.add_genesis_value(alice_value)

                original_submission, _, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=919,
                    expiry_height=1000,
                    fee=0,
                    anti_spam_nonce=94001,
                    tx_time=1,
                )
                conflicting_submission, _, _ = offline_alice.build_payment_bundle(
                    recipient_addr=carol.address,
                    amount=50,
                    private_key_pem=alice_private,
                    public_key_pem=alice_public,
                    chain_id=919,
                    expiry_height=1000,
                    fee=1,
                    anti_spam_nonce=94002,
                    tx_time=1,
                    seq=1,
                )

                first_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-0",
                        payload={"submission": original_submission},
                    )
                )
                self.assertIsInstance(first_response, dict)
                assert isinstance(first_response, dict)
                self.assertTrue(first_response.get("ok", False))
                self.assertEqual(first_response.get("status"), "accepted_pending_consensus")
                self.assertEqual(len(consensus0.consensus.chain.bundle_pool.snapshot()), 1)
                self.assertEqual(consensus0.consensus.chain.bundle_pool.snapshot()[0].sidecar.tx_list[0].recipient_addr, bob.address)

                conflict_response = alice_network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-1",
                        payload={"submission": conflicting_submission},
                    )
                )
                self.assertIsInstance(conflict_response, dict)
                assert isinstance(conflict_response, dict)
                self.assertFalse(conflict_response.get("ok", True))
                self.assertIn("sender already has a different pending bundle", str(conflict_response.get("error", "")))

                pending = consensus0.consensus.chain.bundle_pool.snapshot()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].sidecar.tx_list[0].recipient_addr, bob.address)
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(consensus2.consensus.chain.bundle_pool.snapshot(), [])

                tick = consensus0.drive_auto_mvp_consensus_tick(force=True)
                self.assertIsNotNone(tick)
                assert tick is not None
                self.assertEqual(tick["status"], "committed")
                self.assertEqual(self._wait_for_consensus_height(consensus0, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus1, 1), 1)
                self.assertEqual(self._wait_for_consensus_height(consensus2, 1), 1)
                self.assertEqual(self._wait_for_receipt_count(alice, 1), 1)
                self.assertEqual(consensus0.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(consensus1.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(consensus2.consensus.chain.bundle_pool.snapshot(), [])
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(carol.wallet.available_balance(), 0)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
            finally:
                offline_alice.close()
                carol_network.stop()
                bob_network.stop()
                alice_network.stop()
                consensus2_network.stop()
                consensus1_network.stop()
                consensus0_network.stop()
                carol.close()
                bob.close()
                alice.close()
                consensus2.close()
                consensus1.close()
                consensus0.close()


if __name__ == "__main__":
    unittest.main()
