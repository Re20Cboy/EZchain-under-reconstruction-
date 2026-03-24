from dataclasses import replace
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from EZ_V2.localnet import V2AccountNode, V2ConsensusNode
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2AppRuntimeTest(unittest.TestCase):
    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_wallet_store_derives_stable_v2_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WalletStore(td)
            created = store.create_wallet(password="pw123", name="alice")

            v1_summary = store.summary(protocol_version="v1")
            v2_summary = store.summary(protocol_version="v2")
            loaded_v2 = store.load_v2_wallet(password="pw123")

            self.assertEqual(v1_summary.address, created["address"])
            self.assertEqual(v2_summary.address, loaded_v2["address"])
            self.assertNotEqual(v1_summary.address, v2_summary.address)
            self.assertTrue(v2_summary.address.startswith("0x"))
            self.assertEqual(len(v2_summary.address), 42)

            other_store = WalletStore(str(Path(td) / "other"))
            other_store.import_wallet(mnemonic=created["mnemonic"], password="pw123", name="alice")
            self.assertEqual(
                v2_summary.address,
                other_store.summary(protocol_version="v2").address,
            )

    def test_v2_tx_engine_confirms_through_local_backend(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / ".ezv2"
            store = WalletStore(str(data_dir))
            store.create_wallet(password="pw123", name="demo")

            engine = TxEngine(str(data_dir), max_tx_amount=1000, protocol_version="v2")
            faucet = engine.faucet(store, password="pw123", amount=500)
            self.assertEqual(faucet["protocol_version"], "v2")
            self.assertEqual(faucet["available_balance"], 500)
            self.assertEqual(faucet["minted_values"], 1)
            self.assertEqual(faucet["chain_height"], 0)

            balance = engine.balance(store, password="pw123")
            sender_address = store.summary(protocol_version="v2").address
            self.assertEqual(balance["address"], sender_address)
            self.assertEqual(balance["available_balance"], 500)
            self.assertEqual(balance["pending_bundle_count"], 0)
            self.assertEqual(balance["chain_height"], 0)

            result = engine.send(
                store,
                password="pw123",
                recipient="0xabc123",
                amount=120,
                client_tx_id="cid-v2-001",
            )
            self.assertEqual(result.status, "confirmed")
            self.assertTrue(result.tx_hash)
            self.assertTrue(result.submit_hash)
            self.assertEqual(result.receipt_height, 1)
            self.assertTrue(result.receipt_block_hash)

            confirmed_balance = engine.balance(store, password="pw123")
            self.assertEqual(confirmed_balance["available_balance"], 380)
            self.assertEqual(confirmed_balance["pending_balance"], 0)
            self.assertEqual(confirmed_balance["pending_bundle_count"], 0)
            self.assertEqual(confirmed_balance["v2_status_breakdown"]["archived"], 120)
            self.assertEqual(confirmed_balance["v2_status_breakdown"]["verified_spendable"], 380)
            self.assertEqual(confirmed_balance["chain_height"], 1)
            self.assertEqual(engine.pending(store, password="pw123")["items"], [])
            receipts = engine.receipts(store, password="pw123")
            self.assertEqual(receipts["chain_height"], 1)
            self.assertEqual(len(receipts["items"]), 1)
            self.assertEqual(receipts["items"][0]["seq"], 1)
            self.assertIsNone(receipts["items"][0]["prev_ref"])

            restarted = TxEngine(str(data_dir), max_tx_amount=1000, protocol_version="v2")
            recovered = restarted.balance(store, password="pw123")
            self.assertEqual(recovered["address"], sender_address)
            self.assertEqual(recovered["available_balance"], 380)
            self.assertEqual(recovered["pending_balance"], 0)
            self.assertEqual(recovered["pending_bundle_count"], 0)
            self.assertEqual(recovered["chain_height"], 1)

            next_result = restarted.send(
                store,
                password="pw123",
                recipient="0xdef456",
                amount=10,
                client_tx_id="cid-v2-002",
            )
            self.assertEqual(next_result.status, "confirmed")
            self.assertEqual(next_result.receipt_height, 2)
            next_receipts = restarted.receipts(store, password="pw123")
            self.assertEqual(next_receipts["chain_height"], 2)
            self.assertEqual(len(next_receipts["items"]), 2)
            self.assertEqual(next_receipts["items"][1]["seq"], 2)
            self.assertIsNotNone(next_receipts["items"][1]["prev_ref"])

    def test_v2_tx_engine_balance_recovers_stale_pending_bundle_from_backend_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / ".ezv2"
            store = WalletStore(str(data_dir))
            store.create_wallet(password="pw123", name="demo")
            engine = TxEngine(str(data_dir), max_tx_amount=1000, protocol_version="v2")
            engine.faucet(store, password="pw123", amount=200)

            wallet_identity, account, consensus, _ = engine._open_v2_backend(  # type: ignore[attr-defined]
                store,
                "pw123",
                auto_confirm_receipts=False,
            )
            try:
                account_node = V2AccountNode(
                    name=wallet_identity.get("name", "demo"),
                    private_key_pem=wallet_identity["private_key_pem"].encode("utf-8"),
                    public_key_pem=wallet_identity["public_key_pem"].encode("utf-8"),
                    wallet=account,
                    chain_id=engine.v2_chain_id,
                    consensus=consensus,
                )
                account_node.submit_payment(
                    "0xabc123",
                    amount=50,
                    fee=0,
                    expiry_height=engine.v2_expiry_height,
                    anti_spam_nonce=77,
                    tx_time=1,
                )
                produced = consensus.produce_block(timestamp=2)
                self.assertFalse(produced.deliveries[account.address].applied)
                self.assertEqual(len(account.list_pending_bundles()), 1)
            finally:
                engine._close_v2_backend(account, consensus)  # type: ignore[attr-defined]

            restarted = TxEngine(str(data_dir), max_tx_amount=1000, protocol_version="v2")
            recovered = restarted.balance(store, password="pw123")
            self.assertEqual(recovered["available_balance"], 150)
            self.assertEqual(recovered["pending_balance"], 0)
            self.assertEqual(recovered["pending_bundle_count"], 0)
            self.assertEqual(recovered["chain_height"], 1)

    def test_remote_send_uses_configured_v2_network_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / ".ezv2"
            store = WalletStore(str(data_dir))
            store.create_wallet(password="pw123", name="alice")
            address = store.summary(protocol_version="v2").address
            wallet_db_path = str(data_dir / "wallet_state_v2" / address / "wallet_v2.db")
            state = {
                "address": address,
                "consensus_endpoint": "127.0.0.1:19500",
                "wallet_db_path": wallet_db_path,
            }
            captured: dict[str, float] = {}

            class FakeNetwork:
                def __init__(self, transport, peers=(), *, timeout_sec=5.0):
                    captured["timeout_sec"] = float(timeout_sec)

                def start(self):
                    return None

                def stop(self):
                    return None

            class FakeAccountHost:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def recover_network_state(self):
                    return None

                def submit_payment(self, recipient_peer_id, *, amount, expiry_height, fee, anti_spam_nonce):
                    return type(
                        "Payment",
                        (),
                        {
                            "tx_hash_hex": "tx",
                            "submit_hash_hex": "submit",
                            "receipt_height": 1,
                            "receipt_block_hash_hex": "block",
                        },
                    )()

                def close(self):
                    return None

            engine = TxEngine(
                str(data_dir),
                max_tx_amount=1000,
                protocol_version="v2",
                v2_network_timeout_sec=12.5,
            )

            with patch("EZ_App.runtime.TransportPeerNetwork", FakeNetwork), patch("EZ_App.runtime.V2AccountHost", FakeAccountHost):
                result = engine.remote_send(
                    store,
                    password="pw123",
                    recipient="0x456cb34a89d06b34904eca5b0f27c9fbfddde2b2",
                    amount=50,
                    recipient_endpoint="127.0.0.1:19600",
                    state=state,
                    client_tx_id="cid-timeout",
                )

            self.assertEqual(captured["timeout_sec"], 12.5)
            self.assertEqual(result.status, "confirmed")

    def test_v2_local_app_session_recover_wallet_state_summarizes_incoming_and_receipt_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            alice_addr = alice_store.summary(protocol_version="v2").address
            bob_addr = bob_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=200)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=50,
                client_tx_id="cid-session-recover-1",
            )

            _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                first_recovery = bob_session.recover_wallet_state()
                self.assertEqual(len(first_recovery.receipt_results), 0)
                self.assertEqual(len(first_recovery.received_events), 1)
                self.assertEqual(first_recovery.received_events[0].recipient_addr, bob_addr)
                self.assertEqual(first_recovery.chain_height, 1)
                self.assertEqual(first_recovery.pending_bundle_count, 0)
                self.assertEqual(first_recovery.pending_incoming_transfer_count, 0)
                self.assertEqual(first_recovery.receipt_count, 0)
                self.assertEqual(bob_session.wallet.available_balance(), 50)
            finally:
                bob_session.close()

            wallet_identity, account, consensus, _ = bob_engine._open_v2_backend(  # type: ignore[attr-defined]
                bob_store,
                "pw123",
                auto_confirm_receipts=False,
            )
            try:
                account_node = V2AccountNode(
                    name=wallet_identity.get("name", "bob"),
                    private_key_pem=wallet_identity["private_key_pem"].encode("utf-8"),
                    public_key_pem=wallet_identity["public_key_pem"].encode("utf-8"),
                    wallet=account,
                    chain_id=bob_engine.v2_chain_id,
                    consensus=consensus,
                )
                account_node.submit_payment(
                    alice_addr,
                    amount=20,
                    fee=0,
                    expiry_height=bob_engine.v2_expiry_height,
                    anti_spam_nonce=78,
                    tx_time=2,
                )
                produced = consensus.produce_block(timestamp=3)
                self.assertFalse(produced.deliveries[account.address].applied)
                self.assertEqual(len(account.list_pending_bundles()), 1)
            finally:
                bob_engine._close_v2_backend(account, consensus)  # type: ignore[attr-defined]

            _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                second_recovery = bob_session.recover_wallet_state()
                self.assertEqual(len(second_recovery.receipt_results), 1)
                self.assertTrue(second_recovery.receipt_results[0].applied)
                self.assertEqual(len(second_recovery.received_events), 0)
                self.assertEqual(second_recovery.chain_height, 2)
                self.assertEqual(second_recovery.pending_bundle_count, 0)
                self.assertEqual(second_recovery.pending_incoming_transfer_count, 0)
                self.assertEqual(second_recovery.receipt_count, 1)
                self.assertEqual(bob_session.wallet.available_balance(), 30)
            finally:
                bob_session.close()

    def test_v2_multi_wallet_mailbox_sync_supports_receive_then_respend_without_manual_steps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"
            carol_dir = Path(td) / "carol"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            carol_store = WalletStore(str(carol_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")
            carol_store.create_wallet(password="pw123", name="carol")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            carol_engine = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))

            alice_addr = alice_store.summary(protocol_version="v2").address
            bob_addr = bob_store.summary(protocol_version="v2").address
            carol_addr = carol_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=400)

            alice_send = alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=140,
                client_tx_id="cid-alice-1",
            )
            self.assertEqual(alice_send.receipt_height, 1)

            bob_send = bob_engine.send(
                bob_store,
                password="pw123",
                recipient=carol_addr,
                amount=60,
                client_tx_id="cid-bob-1",
            )
            self.assertEqual(bob_send.receipt_height, 2)

            carol_send = carol_engine.send(
                carol_store,
                password="pw123",
                recipient=alice_addr,
                amount=10,
                client_tx_id="cid-carol-1",
            )
            self.assertEqual(carol_send.receipt_height, 3)

            alice_balance = alice_engine.balance(alice_store, password="pw123")
            bob_balance = bob_engine.balance(bob_store, password="pw123")
            carol_balance = carol_engine.balance(carol_store, password="pw123")

            self.assertEqual(alice_balance["available_balance"], 270)
            self.assertEqual(bob_balance["available_balance"], 80)
            self.assertEqual(carol_balance["available_balance"], 50)
            self.assertEqual(alice_balance["pending_bundle_count"], 0)
            self.assertEqual(bob_balance["pending_bundle_count"], 0)
            self.assertEqual(carol_balance["pending_bundle_count"], 0)
            self.assertEqual(alice_balance["pending_incoming_transfer_count"], 0)
            self.assertEqual(bob_balance["pending_incoming_transfer_count"], 0)
            self.assertEqual(carol_balance["pending_incoming_transfer_count"], 0)
            self.assertEqual(alice_balance["chain_height"], 3)
            self.assertEqual(bob_balance["chain_height"], 3)
            self.assertEqual(carol_balance["chain_height"], 3)

            self.assertEqual(len(alice_engine.receipts(alice_store, password="pw123")["items"]), 1)
            self.assertEqual(len(bob_engine.receipts(bob_store, password="pw123")["items"]), 1)
            self.assertEqual(len(carol_engine.receipts(carol_store, password="pw123")["items"]), 1)

            alice_history = alice_store.get_history()
            bob_history = bob_store.get_history()
            carol_history = carol_store.get_history()
            self.assertEqual([item["status"] for item in alice_history], ["received"])
            self.assertEqual([item["amount"] for item in alice_history], [10])
            self.assertEqual([item["status"] for item in bob_history], ["received"])
            self.assertEqual([item["amount"] for item in bob_history], [140])
            self.assertEqual([item["status"] for item in carol_history], ["received"])
            self.assertEqual([item["amount"] for item in carol_history], [60])

            alice_restarted = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_restarted = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            carol_restarted = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            self.assertEqual(alice_restarted.balance(alice_store, password="pw123")["available_balance"], 270)
            self.assertEqual(bob_restarted.balance(bob_store, password="pw123")["available_balance"], 80)
            self.assertEqual(carol_restarted.balance(carol_store, password="pw123")["available_balance"], 50)
            self.assertEqual(len(alice_store.get_history()), 1)
            self.assertEqual(len(bob_store.get_history()), 1)
            self.assertEqual(len(carol_store.get_history()), 1)

    def test_v2_checkpoint_query_reads_persisted_wallet_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            alice_addr = alice_store.summary(protocol_version="v2").address
            bob_addr = bob_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=120)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=40,
                client_tx_id="cid-alice-bob-1",
            )

            synced_balance = bob_engine.balance(bob_store, password="pw123")
            self.assertEqual(synced_balance["available_balance"], 40)
            bob_send = bob_engine.send(
                bob_store,
                password="pw123",
                recipient=alice_addr,
                amount=10,
                client_tx_id="cid-bob-back-1",
            )
            self.assertEqual(bob_send.receipt_height, 2)

            _, bob_account, bob_consensus, _ = bob_engine._open_v2_backend(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                spendable = next(record for record in bob_account.list_records() if record.local_status.value == "verified_spendable")
                checkpoint = bob_account.create_exact_checkpoint(spendable.record_id)
            finally:
                bob_engine._close_v2_backend(bob_account, bob_consensus)  # type: ignore[attr-defined]

            checkpoint_view = bob_engine.checkpoints(bob_store, password="pw123")
            self.assertEqual(checkpoint_view["chain_height"], 2)
            self.assertEqual(checkpoint_view["pending_incoming_transfer_count"], 0)
            self.assertEqual(len(checkpoint_view["items"]), 1)
            self.assertEqual(checkpoint_view["items"][0]["value_begin"], checkpoint.value_begin)
            self.assertEqual(checkpoint_view["items"][0]["value_end"], checkpoint.value_end)
            self.assertEqual(checkpoint_view["items"][0]["checkpoint_height"], checkpoint.checkpoint_height)

            restarted = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            self.assertEqual(restarted.checkpoints(bob_store, password="pw123")["items"], checkpoint_view["items"])

    def test_v2_history_includes_derived_confirmed_and_received_items(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_addr = bob_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=120)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=35,
                client_tx_id="cid-history-1",
            )
            bob_engine.balance(bob_store, password="pw123")

            alice_history = alice_engine.history(alice_store)
            self.assertEqual(alice_history["protocol_version"], "v2")
            self.assertEqual(alice_history["chain_height"], 1)
            self.assertEqual(len(alice_history["items"]), 1)
            self.assertEqual(alice_history["items"][0]["status"], "confirmed")
            self.assertEqual(alice_history["items"][0]["amount"], 35)

            remote_state = {
                "address": bob_addr,
                "wallet_db_path": str(bob_dir / "wallet_state_v2" / bob_addr / "wallet_v2.db"),
                "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            }
            bob_history = bob_engine.remote_history(bob_store, state=remote_state)
            self.assertEqual(bob_history["protocol_version"], "v2")
            self.assertEqual(bob_history["chain_height"], 1)
            self.assertEqual(len(bob_history["items"]), 1)
            self.assertEqual(bob_history["items"][0]["status"], "received")
            self.assertEqual(bob_history["items"][0]["amount"], 35)
            self.assertEqual(bob_history["items"][0]["recipient"], bob_addr)

    def test_v2_tx_engine_remote_send_confirms_when_recipient_endpoint_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")

            alice_wallet = alice_store.load_v2_wallet(password="pw123")
            bob_wallet = bob_store.load_v2_wallet(password="pw123")
            alice_address = alice_wallet["address"]
            bob_address = bob_wallet["address"]
            alice_wallet_db_path = alice_dir / "wallet_state_v2" / alice_address / "wallet_v2.db"
            bob_wallet_db_path = bob_dir / "wallet_state_v2" / bob_address / "wallet_v2.db"
            alice_wallet_db_path.parent.mkdir(parents=True, exist_ok=True)
            bob_wallet_db_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                consensus_port = self._reserve_port()
                bob_port = self._reserve_port()
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc

            peers = (
                PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{consensus_port}"),
                PeerInfo(node_id="alice", role="account", endpoint="127.0.0.1:0", metadata={"address": alice_address}),
                PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{bob_port}", metadata={"address": bob_address}),
            )
            consensus_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", consensus_port),
                peers,
            )
            bob_network = TransportPeerNetwork(
                TCPNetworkTransport("127.0.0.1", bob_port),
                peers,
            )
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint=f"127.0.0.1:{consensus_port}",
                store_path=f"{td}/consensus.sqlite3",
                network=consensus_network,
                chain_id=909,
            )
            bob_account = V2AccountHost(
                node_id="bob",
                endpoint=f"127.0.0.1:{bob_port}",
                wallet_db_path=str(bob_wallet_db_path),
                chain_id=909,
                network=bob_network,
                consensus_peer_id="consensus-0",
                address=bob_address,
                private_key_pem=bob_wallet["private_key_pem"].encode("utf-8"),
                public_key_pem=bob_wallet["public_key_pem"].encode("utf-8"),
            )
            try:
                try:
                    consensus_network.start()
                    bob_network.start()
                except PermissionError as exc:
                    raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, PermissionError):
                        raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                    raise

                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice_address, minted)
                sender_wallet = WalletAccountV2(
                    address=alice_address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=str(alice_wallet_db_path),
                )
                try:
                    sender_wallet.add_genesis_value(minted)
                finally:
                    sender_wallet.close()

                engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2")
                remote_state = {
                    "address": alice_address,
                    "consensus_endpoint": f"127.0.0.1:{consensus_port}",
                    "wallet_db_path": str(alice_wallet_db_path),
                    "chain_cursor": {"height": 0, "block_hash_hex": "00" * 32},
                    "pending_incoming_transfer_count": 0,
                }

                result = engine.send(
                    alice_store,
                    password="pw123",
                    recipient=bob_address,
                    amount=70,
                    client_tx_id="cid-remote-runtime-1",
                    state=remote_state,
                    recipient_endpoint=f"127.0.0.1:{bob_port}",
                )

                self.assertEqual(result.status, "confirmed")
                self.assertEqual(result.receipt_height, 1)
                self.assertTrue(result.tx_hash)
                self.assertTrue(result.submit_hash)

                sender_wallet = WalletAccountV2(
                    address=alice_address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=str(alice_wallet_db_path),
                )
                recipient_wallet = WalletAccountV2(
                    address=bob_address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=str(bob_wallet_db_path),
                )
                try:
                    self.assertEqual(sender_wallet.available_balance(), 130)
                    self.assertEqual(recipient_wallet.available_balance(), 70)
                    self.assertEqual(len(sender_wallet.list_receipts()), 1)
                finally:
                    sender_wallet.close()
                    recipient_wallet.close()
            finally:
                bob_network.stop()
                consensus_network.stop()
                bob_account.close()
                consensus.close()

    def test_invalid_mailbox_package_is_not_claimed_and_valid_package_still_syncs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_addr = bob_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=120)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=40,
                client_tx_id="cid-alice-bob-valid",
            )

            _, alice_session = alice_engine._open_v2_session(alice_store, "pw123")  # type: ignore[attr-defined]
            _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                pending_packages = bob_session.mailbox.list_pending_packages(bob_session.address)
                self.assertEqual(len(pending_packages), 1)
                package_hash, sender_addr, created_at, package = pending_packages[0]

                tampered_package = replace(package, target_value=replace(package.target_value, end=package.target_value.end + 10))
                bob_session.mailbox.enqueue_package(
                    sender_addr=sender_addr,
                    recipient_addr=bob_session.address,
                    package=tampered_package,
                    created_at=created_at - 1,
                )

                events = bob_session.sync_wallet_state()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].target_value, package.target_value)
                self.assertEqual(bob_session.mailbox.pending_count(bob_session.address), 1)
            finally:
                alice_session.close()
                bob_session.close()

    def test_conflicting_mailbox_packages_only_accept_valid_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"
            carol_dir = Path(td) / "carol"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            carol_store = WalletStore(str(carol_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")
            carol_store.create_wallet(password="pw123", name="carol")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            carol_addr = carol_store.summary(protocol_version="v2").address
            bob_addr = bob_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=150)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=40,
                client_tx_id="cid-branching-1",
            )

            _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                pending_packages = bob_session.mailbox.list_pending_packages(bob_session.address)
                self.assertEqual(len(pending_packages), 1)
                _, sender_addr, created_at, package = pending_packages[0]

                wrong_recipient_package = replace(
                    package,
                    target_tx=replace(package.target_tx, recipient_addr=carol_addr),
                )
                expanded_value_package = replace(
                    package,
                    target_value=replace(package.target_value, end=package.target_value.end + 5),
                )
                bob_session.mailbox.enqueue_package(
                    sender_addr=sender_addr,
                    recipient_addr=bob_session.address,
                    package=wrong_recipient_package,
                    created_at=created_at - 2,
                )
                bob_session.mailbox.enqueue_package(
                    sender_addr=sender_addr,
                    recipient_addr=bob_session.address,
                    package=expanded_value_package,
                    created_at=created_at - 1,
                )

                events = bob_session.sync_wallet_state()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].recipient_addr, bob_addr)
                self.assertEqual(events[0].target_value, package.target_value)
                self.assertEqual(bob_session.mailbox.pending_count(bob_session.address), 2)
                self.assertEqual(bob_session.wallet.available_balance(), 40)
            finally:
                bob_session.close()

    def test_multi_round_mailbox_attack_does_not_break_honest_balances(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shared_backend = Path(td) / "shared_backend"
            alice_dir = Path(td) / "alice"
            bob_dir = Path(td) / "bob"
            carol_dir = Path(td) / "carol"

            alice_store = WalletStore(str(alice_dir))
            bob_store = WalletStore(str(bob_dir))
            carol_store = WalletStore(str(carol_dir))
            alice_store.create_wallet(password="pw123", name="alice")
            bob_store.create_wallet(password="pw123", name="bob")
            carol_store.create_wallet(password="pw123", name="carol")

            alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
            carol_engine = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))

            bob_addr = bob_store.summary(protocol_version="v2").address
            carol_addr = carol_store.summary(protocol_version="v2").address

            alice_engine.faucet(alice_store, password="pw123", amount=180)
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=50,
                client_tx_id="cid-attack-round-1",
            )
            alice_engine.send(
                alice_store,
                password="pw123",
                recipient=bob_addr,
                amount=30,
                client_tx_id="cid-attack-round-2",
            )

            _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
            try:
                pending_packages = bob_session.mailbox.list_pending_packages(bob_session.address)
                self.assertEqual(len(pending_packages), 2)
                for package_hash, sender_addr, created_at, package in pending_packages:
                    wrong_recipient_package = replace(
                        package,
                        target_tx=replace(package.target_tx, recipient_addr=carol_addr),
                    )
                    expanded_value_package = replace(
                        package,
                        target_value=replace(package.target_value, end=package.target_value.end + 9),
                    )
                    bob_session.mailbox.enqueue_package(
                        sender_addr=sender_addr,
                        recipient_addr=bob_session.address,
                        package=wrong_recipient_package,
                        created_at=created_at - 2,
                    )
                    bob_session.mailbox.enqueue_package(
                        sender_addr=sender_addr,
                        recipient_addr=bob_session.address,
                        package=expanded_value_package,
                        created_at=created_at - 1,
                    )

                events = bob_session.sync_wallet_state()
                self.assertEqual(len(events), 2)
                self.assertEqual(sorted(event.target_value.size for event in events), [30, 50])
                self.assertEqual(bob_session.wallet.available_balance(), 80)
                self.assertEqual(bob_session.mailbox.pending_count(bob_session.address), 4)
            finally:
                bob_session.close()

            bob_send = bob_engine.send(
                bob_store,
                password="pw123",
                recipient=carol_addr,
                amount=60,
                client_tx_id="cid-bob-honest-respend",
            )
            self.assertEqual(bob_send.receipt_height, 3)

            bob_balance = bob_engine.balance(bob_store, password="pw123")
            carol_balance = carol_engine.balance(carol_store, password="pw123")
            alice_balance = alice_engine.balance(alice_store, password="pw123")

            self.assertEqual(alice_balance["available_balance"], 100)
            self.assertEqual(bob_balance["available_balance"], 20)
            self.assertEqual(carol_balance["available_balance"], 60)
            self.assertEqual(bob_balance["pending_incoming_transfer_count"], 4)
            self.assertEqual(carol_balance["pending_incoming_transfer_count"], 0)
            self.assertEqual(alice_balance["pending_bundle_count"], 0)
            self.assertEqual(bob_balance["pending_bundle_count"], 0)
            self.assertEqual(carol_balance["pending_bundle_count"], 0)


if __name__ == "__main__":
    unittest.main()
