#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_trial_id(executed_at: datetime) -> str:
    return f"official-testnet-{executed_at.strftime('%Y%m%d')}-01"


def _load_template(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("template root must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize an official-testnet external trial record")
    parser.add_argument("--template", default="doc/OFFICIAL_TESTNET_TRIAL_TEMPLATE.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--executor", required=True)
    parser.add_argument("--os", dest="os_name", choices=("macos", "windows"), required=True)
    parser.add_argument("--install-path", choices=("source", "binary"), required=True)
    parser.add_argument(
        "--network-environment",
        choices=("real-external", "single-host-rehearsal"),
        default="real-external",
    )
    parser.add_argument("--config-path", default="ezchain.yaml")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = root / template_path
    if not template_path.exists():
        raise SystemExit(f"template file not found: {template_path}")

    executed_at = _utc_now()
    payload = _load_template(template_path)
    payload["trial_id"] = _default_trial_id(executed_at)
    payload["executed_at"] = executed_at.isoformat()
    payload["executor"] = args.executor
    payload["status"] = "pending"

    environment = dict(payload.get("environment") or {})
    environment["os"] = args.os_name
    environment["install_path"] = args.install_path
    environment["network_environment"] = args.network_environment
    environment["config_path"] = args.config_path
    payload["environment"] = environment

    profile = dict(payload.get("profile") or {})
    profile["name"] = "official-testnet"
    profile["connectivity_checked"] = False
    profile["connectivity_result"] = "pending"
    payload["profile"] = profile

    workflow = dict(payload.get("workflow") or {})
    for key in (
        "install",
        "wallet_create_or_import",
        "network_check",
        "faucet",
        "send",
        "history_receipts_balance_match",
    ):
        workflow[key] = "pending"
    payload["workflow"] = workflow

    evidence = dict(payload.get("evidence") or {})
    contact_card = dict(evidence.get("contact_card") or {})
    contact_card.setdefault("path", "")
    contact_card.setdefault("address", "")
    contact_card.setdefault("endpoint", "")
    contact_card["imported"] = bool(contact_card.get("imported", False))
    contact_card["used_for_send"] = bool(contact_card.get("used_for_send", False))
    evidence["contact_card"] = contact_card
    payload["evidence"] = evidence

    out_path = Path(args.out) if args.out else (root / "doc" / "trials" / f"{payload['trial_id']}.json")
    if not out_path.is_absolute():
        out_path = root / out_path
    if out_path.exists() and not args.force:
        raise SystemExit(f"output file already exists: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "initialized",
                "trial_id": payload["trial_id"],
                "record": str(out_path),
                "executor": args.executor,
                "os": args.os_name,
                "install_path": args.install_path,
                "network_environment": args.network_environment,
                "config_path": args.config_path,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
