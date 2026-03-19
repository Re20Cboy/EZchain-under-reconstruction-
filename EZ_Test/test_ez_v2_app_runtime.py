import tempfile
import unittest
from pathlib import Path

from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from EZ_V2.localnet import V2AccountNode, V2ConsensusNode


class EZV2AppRuntimeTest(unittest.TestCase):
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
            self.assertEqual(restarted.pending(store, password="pw123")["items"], [])
            self.assertEqual(len(restarted.receipts(store, password="pw123")["items"]), 1)

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


if __name__ == "__main__":
    unittest.main()
