from __future__ import annotations

from pathlib import Path
from typing import Any

from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from EZ_V2.values import LocalValueStatus


def run_stage4_acceptance(root_dir: str, project_root: str) -> dict[str, Any]:
    root = Path(root_dir)
    manager_dir = root / "manager"
    shared_backend = manager_dir / "v2_runtime"
    alice_dir = root / "alice"
    bob_dir = root / "bob"
    carol_dir = root / "carol"

    alice_store = WalletStore(str(alice_dir))
    bob_store = WalletStore(str(bob_dir))
    carol_store = WalletStore(str(carol_dir))
    alice_store.create_wallet(password="pw123", name="alice")
    bob_store.create_wallet(password="pw123", name="bob")
    carol_store.create_wallet(password="pw123", name="carol")

    manager = NodeManager(data_dir=str(manager_dir), project_root=project_root)
    alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
    bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
    carol_engine = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))

    alice_addr = alice_store.summary(protocol_version="v2").address
    bob_addr = bob_store.summary(protocol_version="v2").address
    carol_addr = carol_store.summary(protocol_version="v2").address

    try:
        started = manager.start(mode="v2-localnet", network_name="testnet")
        already_running = manager.start(mode="v2-localnet", network_name="testnet")

        faucet = alice_engine.faucet(alice_store, password="pw123", amount=500)
        alice_send = alice_engine.send(
            alice_store,
            password="pw123",
            recipient=bob_addr,
            amount=180,
            client_tx_id="cid-acceptance-alice-1",
        )
        bob_after_receive = bob_engine.balance(bob_store, password="pw123")

        bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
        bob_send = bob_engine.send(
            bob_store,
            password="pw123",
            recipient=carol_addr,
            amount=70,
            client_tx_id="cid-acceptance-bob-1",
        )
        carol_after_receive = carol_engine.balance(carol_store, password="pw123")

        carol_engine = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
        carol_send = carol_engine.send(
            carol_store,
            password="pw123",
            recipient=alice_addr,
            amount=15,
            client_tx_id="cid-acceptance-carol-1",
        )

        alice_after_roundtrip = alice_engine.balance(alice_store, password="pw123")
        bob_after_roundtrip = bob_engine.balance(bob_store, password="pw123")
        carol_after_roundtrip = carol_engine.balance(carol_store, password="pw123")

        initial_history_lengths = {
            "alice": len(alice_store.get_history()),
            "bob": len(bob_store.get_history()),
            "carol": len(carol_store.get_history()),
        }
        alice_engine.balance(alice_store, password="pw123")
        bob_engine.balance(bob_store, password="pw123")
        carol_engine.balance(carol_store, password="pw123")
        repeated_history_lengths = {
            "alice": len(alice_store.get_history()),
            "bob": len(bob_store.get_history()),
            "carol": len(carol_store.get_history()),
        }

        _, bob_session = bob_engine._open_v2_session(bob_store, "pw123")  # type: ignore[attr-defined]
        try:
            spendable = next(
                record
                for record in bob_session.wallet.list_records()
                if record.local_status == LocalValueStatus.VERIFIED_SPENDABLE
            )
            checkpoint = bob_session.wallet.create_exact_checkpoint(spendable.record_id)
            bob_checkpoint_count = len(bob_session.wallet.list_checkpoints())
        finally:
            bob_session.close()

        stopped = manager.stop()
        stopped_status = manager.status()
        restarted = manager.start(mode="v2-localnet", network_name="testnet")
        restarted_status = manager.status()

        alice_engine = TxEngine(str(alice_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
        bob_engine = TxEngine(str(bob_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))
        carol_engine = TxEngine(str(carol_dir), max_tx_amount=1000, protocol_version="v2", v2_backend_dir=str(shared_backend))

        final_balances = {
            "alice": alice_engine.balance(alice_store, password="pw123"),
            "bob": bob_engine.balance(bob_store, password="pw123"),
            "carol": carol_engine.balance(carol_store, password="pw123"),
        }
        final_receipt_counts = {
            "alice": len(alice_engine.receipts(alice_store, password="pw123")["items"]),
            "bob": len(bob_engine.receipts(bob_store, password="pw123")["items"]),
            "carol": len(carol_engine.receipts(carol_store, password="pw123")["items"]),
        }
        final_checkpoint_count = len(bob_engine.checkpoints(bob_store, password="pw123")["items"])
        backend_metadata = alice_engine.v2_client.backend_metadata()

        return {
            "addresses": {
                "alice": alice_addr,
                "bob": bob_addr,
                "carol": carol_addr,
            },
            "node": {
                "started_status": started["status"],
                "already_running_status": already_running["status"],
                "stopped_status": stopped["status"],
                "status_after_stop": stopped_status["status"],
                "restarted_status": restarted["status"],
                "status_after_restart": restarted_status["status"],
            },
            "heights": {
                "faucet": faucet["chain_height"],
                "alice_receipt": alice_send.receipt_height,
                "bob_receipt": bob_send.receipt_height,
                "carol_receipt": carol_send.receipt_height,
                "backend": None if backend_metadata is None else backend_metadata["height"],
                "status_backend": None if restarted_status.get("backend") is None else restarted_status["backend"]["height"],
            },
            "balances": {
                "bob_after_receive": bob_after_receive["available_balance"],
                "carol_after_receive": carol_after_receive["available_balance"],
                "alice": final_balances["alice"]["available_balance"],
                "bob": final_balances["bob"]["available_balance"],
                "carol": final_balances["carol"]["available_balance"],
            },
            "history_lengths": {
                "initial": initial_history_lengths,
                "repeated": repeated_history_lengths,
            },
            "receipts": final_receipt_counts,
            "checkpoints": {
                "created_height": checkpoint.checkpoint_height,
                "count": final_checkpoint_count,
                "during_creation_count": bob_checkpoint_count,
            },
        }
    finally:
        manager.stop()
