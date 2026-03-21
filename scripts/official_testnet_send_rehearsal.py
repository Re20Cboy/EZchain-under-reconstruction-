#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from _bootstrap import ensure_repo_root_on_path
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from EZ_App.config import ensure_directories, load_config
from EZ_App.contact_card import load_contact_card
from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from scripts.update_external_trial import update_trial_record


def _is_remote_official_profile(cfg) -> bool:
    if str(cfg.app.protocol_version or "v1").lower() != "v2":
        return False
    for endpoint in cfg.network.bootstrap_nodes or []:
        host = str(endpoint).split(":", 1)[0].strip().lower()
        if host not in {"127.0.0.1", "localhost"}:
            return True
    return False


def _remote_read_state(cfg, node_manager: NodeManager) -> Dict[str, Any]:
    state = node_manager.account_status(bootstrap_nodes=cfg.network.bootstrap_nodes)
    if not isinstance(state, dict):
        raise ValueError("account_status_missing")
    if state.get("status") != "running":
        raise ValueError("v2_account_not_running")
    if state.get("mode_family") != "v2-account":
        raise ValueError("account_role_not_running")
    if not str(state.get("wallet_db_path", "")).strip():
        raise ValueError("account_wallet_db_missing")
    return state


def run_rehearsal(
    *,
    config_path: Path,
    record_path: Path,
    password: str,
    contact_card_file: Path,
    amount: int,
    client_tx_id: str | None = None,
    recipient: str | None = None,
    note: list[str] | None = None,
) -> Dict[str, Any]:
    cfg = load_config(config_path)
    ensure_directories(cfg)
    if not _is_remote_official_profile(cfg):
        raise ValueError("config_is_not_remote_official_testnet_v2")

    wallet_store = WalletStore(cfg.app.data_dir)
    node_manager = NodeManager(data_dir=cfg.app.data_dir, project_root=str(Path(__file__).resolve().parent.parent))
    tx_engine = TxEngine(
        cfg.app.data_dir,
        max_tx_amount=cfg.security.max_tx_amount,
        protocol_version=cfg.app.protocol_version,
    )
    card = load_contact_card(contact_card_file)
    recipient_address = str(recipient or card["address"]).strip()
    if not recipient_address:
        raise ValueError("recipient_required")
    saved_contact = wallet_store.set_contact(address=recipient_address, endpoint=card["endpoint"])
    remote_state = _remote_read_state(cfg, node_manager)
    effective_client_tx_id = client_tx_id or f"trial-{secrets.token_hex(6)}"
    extra_notes = list(note or [])

    try:
        result = tx_engine.send(
            wallet_store=wallet_store,
            password=password,
            recipient=recipient_address,
            amount=amount,
            client_tx_id=effective_client_tx_id,
            state=remote_state,
            recipient_endpoint=saved_contact["endpoint"],
        )
        sender = wallet_store.summary(protocol_version=cfg.app.protocol_version).address
        history_item = {
            "tx_id": result.tx_hash,
            "submit_hash": result.submit_hash,
            "sender": sender,
            "recipient": result.recipient,
            "amount": result.amount,
            "status": result.status,
            "client_tx_id": result.client_tx_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if result.receipt_height is not None:
            history_item["receipt_height"] = result.receipt_height
        if result.receipt_block_hash is not None:
            history_item["receipt_block_hash"] = result.receipt_block_hash
        wallet_store.append_history(history_item)
        update = update_trial_record(
            record_path,
            step="send",
            step_status="passed",
            contact_card_file=str(contact_card_file),
            contact_card_imported=True,
            contact_card_used_for_send=True,
            notes_to_add=extra_notes + [f"send passed with contact card for {recipient_address}"],
            auto_status=True,
        )
        return {
            "ok": True,
            "config": str(config_path),
            "record": str(record_path),
            "contact_card": card,
            "saved_contact": saved_contact,
            "tx": history_item,
            "trial_update": update,
        }
    except Exception as exc:
        update = update_trial_record(
            record_path,
            step="send",
            step_status="failed",
            contact_card_file=str(contact_card_file),
            contact_card_imported=True,
            contact_card_used_for_send=True,
            issues_to_add=[f"send_failed:{exc}"],
            notes_to_add=extra_notes + [f"send failed with contact card for {recipient_address}: {exc}"],
            auto_status=True,
        )
        return {
            "ok": False,
            "config": str(config_path),
            "record": str(record_path),
            "contact_card": card,
            "saved_contact": saved_contact,
            "error": str(exc),
            "trial_update": update,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the official-testnet send rehearsal with a contact card")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--record", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--contact-card-file", required=True)
    parser.add_argument("--amount", type=int, required=True)
    parser.add_argument("--client-tx-id", default=None)
    parser.add_argument("--recipient", default=None)
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    result = run_rehearsal(
        config_path=Path(args.config),
        record_path=Path(args.record),
        password=args.password,
        contact_card_file=Path(args.contact_card_file),
        amount=int(args.amount),
        client_tx_id=args.client_tx_id,
        recipient=args.recipient,
        note=list(args.note),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
