#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _capture_balance(*, wallet_dir: str, password: str, chain_id: int, state: dict[str, Any]) -> dict[str, Any]:
    store = WalletStore(wallet_dir)
    engine = TxEngine(
        wallet_dir,
        max_tx_amount=100000000,
        protocol_version="v2",
        v2_chain_id=int(chain_id),
    )
    return engine.remote_balance(store, password=password, state=state)


def _capture_consensus_states(paths: list[str]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for path in paths:
        item = _load_json(path)
        item["_state_file"] = path
        states.append(item)
    return states


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a distributed EZchain V2 trial snapshot")
    parser.add_argument("--role", required=True, help="Logical role label, e.g. mac or ecs")
    parser.add_argument("--chain-id", type=int, required=True, help="V2 chain id")
    parser.add_argument("--account-state-file", required=True, help="Path to local account node state.json")
    parser.add_argument("--wallet-dir", required=True, help="Wallet store directory used by the account node")
    parser.add_argument("--password", required=True, help="Wallet password for balance snapshot")
    parser.add_argument(
        "--consensus-state-file",
        action="append",
        default=[],
        help="Repeatable path to local consensus state.json files",
    )
    parser.add_argument("--out-json", default="", help="Optional output path")
    args = parser.parse_args()

    account_state = _load_json(args.account_state_file)
    balance = _capture_balance(
        wallet_dir=args.wallet_dir,
        password=args.password,
        chain_id=args.chain_id,
        state=account_state,
    )
    consensus_states = _capture_consensus_states(list(args.consensus_state_file))

    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "role": str(args.role),
        "chain_id": int(args.chain_id),
        "account": {
            "state_file": args.account_state_file,
            "state": account_state,
            "balance": balance,
        },
        "consensus": consensus_states,
    }

    wire = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(wire, encoding="utf-8")
    print(wire)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
