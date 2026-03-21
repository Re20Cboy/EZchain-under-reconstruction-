#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.contact_card import load_contact_card


WORKFLOW_KEYS = (
    "install",
    "wallet_create_or_import",
    "network_check",
    "faucet",
    "send",
    "history_receipts_balance_match",
)

STEP_STATUSES = ("pending", "passed", "failed")
TOP_STATUSES = ("pending", "passed", "failed")
CONNECTIVITY_RESULTS = ("pending", "passed", "failed")
BOOLEAN_CHOICES = ("true", "false")
NETWORK_ENVIRONMENTS = ("real-external", "single-host-rehearsal")


def _derive_status(payload: dict[str, Any]) -> str:
    workflow = payload.get("workflow")
    profile = payload.get("profile")
    if not isinstance(workflow, dict) or not isinstance(profile, dict):
        return "pending"

    workflow_statuses = [str(workflow.get(key, "pending")).lower() for key in WORKFLOW_KEYS]
    connectivity_checked = profile.get("connectivity_checked") is True
    connectivity_result = str(profile.get("connectivity_result", "pending")).lower()

    if connectivity_result == "failed" or any(status == "failed" for status in workflow_statuses):
        return "failed"
    if (
        connectivity_checked
        and connectivity_result == "passed"
        and all(status == "passed" for status in workflow_statuses)
    ):
        return "passed"
    return "pending"


def _remaining_steps(payload: dict[str, Any]) -> list[str]:
    workflow = payload.get("workflow")
    profile = payload.get("profile")
    remaining: list[str] = []
    if not isinstance(profile, dict) or profile.get("connectivity_checked") is not True:
        remaining.append("profile.connectivity_checked")
    if not isinstance(profile, dict) or str(profile.get("connectivity_result", "pending")).lower() != "passed":
        remaining.append("profile.connectivity_result")
    if not isinstance(workflow, dict):
        return ["workflow"]
    for key in WORKFLOW_KEYS:
        if str(workflow.get(key, "pending")).lower() != "passed":
            remaining.append(f"workflow.{key}")
    return remaining


def _normalize_network_environment(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in NETWORK_ENVIRONMENTS:
        return normalized
    return "unknown"


def _load_record(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("trial record root must be a JSON object")
    return payload


def _append_unique(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class _RecordLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        assert self.handle is not None
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def update_trial_record(
    record_path: Path,
    *,
    step: str | None = None,
    step_status: str | None = None,
    status: str | None = None,
    connectivity_checked: bool | None = None,
    connectivity_result: str | None = None,
    network_environment: str | None = None,
    contact_card_file: str | None = None,
    contact_card_path: str | None = None,
    contact_card_address: str | None = None,
    contact_card_endpoint: str | None = None,
    contact_card_imported: bool | None = None,
    contact_card_used_for_send: bool | None = None,
    issues_to_add: list[str] | None = None,
    notes_to_add: list[str] | None = None,
    clear_default_notes: bool = False,
    auto_status: bool = False,
) -> dict[str, Any]:
    if not record_path.exists():
        raise SystemExit(f"record file not found: {record_path}")

    issues_to_add = issues_to_add or []
    notes_to_add = notes_to_add or []

    with _RecordLock(record_path.with_suffix(record_path.suffix + ".lock")):
        payload = _load_record(record_path)
        workflow = payload.setdefault("workflow", {})
        if not isinstance(workflow, dict):
            raise SystemExit("workflow must be a JSON object")
        profile = payload.setdefault("profile", {})
        if not isinstance(profile, dict):
            raise SystemExit("profile must be a JSON object")
        environment = payload.setdefault("environment", {})
        if not isinstance(environment, dict):
            raise SystemExit("environment must be a JSON object")
        evidence = payload.setdefault("evidence", {})
        if not isinstance(evidence, dict):
            raise SystemExit("evidence must be a JSON object")
        contact_card = evidence.setdefault("contact_card", {})
        if not isinstance(contact_card, dict):
            raise SystemExit("evidence.contact_card must be a JSON object")
        issues = payload.setdefault("issues", [])
        if not isinstance(issues, list):
            raise SystemExit("issues must be a JSON array")
        notes = payload.setdefault("notes", [])
        if not isinstance(notes, list):
            raise SystemExit("notes must be a JSON array")

        if step and step_status:
            workflow[step] = step_status
        elif step or step_status:
            raise SystemExit("--step and --step-status must be provided together")

        if status:
            payload["status"] = status

        if connectivity_checked is not None:
            profile["connectivity_checked"] = connectivity_checked
        if connectivity_result is not None:
            profile["connectivity_result"] = connectivity_result
        if network_environment is not None:
            environment["network_environment"] = network_environment
        if contact_card_file is not None:
            card = load_contact_card(contact_card_file)
            contact_card["path"] = str(contact_card_file)
            contact_card["address"] = card["address"]
            contact_card["endpoint"] = card["endpoint"]
        if contact_card_path is not None:
            contact_card["path"] = str(contact_card_path)
        if contact_card_address is not None:
            contact_card["address"] = str(contact_card_address)
        if contact_card_endpoint is not None:
            contact_card["endpoint"] = str(contact_card_endpoint)
        if contact_card_imported is not None:
            contact_card["imported"] = bool(contact_card_imported)
        if contact_card_used_for_send is not None:
            contact_card["used_for_send"] = bool(contact_card_used_for_send)

        if clear_default_notes:
            notes[:] = [item for item in notes if item != "Record any operator-facing problems here."]

        for item in issues_to_add:
            _append_unique(issues, item)
        for item in notes_to_add:
            _append_unique(notes, item)

        if auto_status:
            payload["status"] = _derive_status(payload)

        remaining_steps = _remaining_steps(payload)
        suggested_status = _derive_status(payload)

        _atomic_write_json(record_path, payload)

    return {
        "record": str(record_path),
        "status": payload.get("status", "unknown"),
        "suggested_status": suggested_status,
        "updated_step": step,
        "updated_step_status": step_status,
        "connectivity_checked": profile.get("connectivity_checked"),
        "connectivity_result": profile.get("connectivity_result"),
        "network_environment": _normalize_network_environment(environment.get("network_environment")),
        "contact_card": {
            "path": contact_card.get("path", ""),
            "address": contact_card.get("address", ""),
            "endpoint": contact_card.get("endpoint", ""),
            "imported": contact_card.get("imported", False),
            "used_for_send": contact_card.get("used_for_send", False),
        },
        "remaining_steps": remaining_steps,
        "issues_count": len(issues),
        "notes_count": len(notes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Update an official-testnet external trial record safely")
    parser.add_argument("--record", required=True)
    parser.add_argument("--step", choices=WORKFLOW_KEYS)
    parser.add_argument("--step-status", choices=STEP_STATUSES)
    parser.add_argument("--status", choices=TOP_STATUSES)
    parser.add_argument("--connectivity-checked", choices=("true", "false"))
    parser.add_argument("--connectivity-result", choices=CONNECTIVITY_RESULTS)
    parser.add_argument("--network-environment", choices=NETWORK_ENVIRONMENTS)
    parser.add_argument("--contact-card-file", default=None)
    parser.add_argument("--contact-card-path", default=None)
    parser.add_argument("--contact-card-address", default=None)
    parser.add_argument("--contact-card-endpoint", default=None)
    parser.add_argument("--contact-card-imported", choices=BOOLEAN_CHOICES)
    parser.add_argument("--contact-card-used-for-send", choices=BOOLEAN_CHOICES)
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--clear-default-notes", action="store_true")
    parser.add_argument("--auto-status", action="store_true")
    args = parser.parse_args()

    record_path = Path(args.record)
    result = update_trial_record(
        record_path,
        step=args.step,
        step_status=args.step_status,
        status=args.status,
        connectivity_checked=(None if args.connectivity_checked is None else args.connectivity_checked == "true"),
        connectivity_result=args.connectivity_result,
        network_environment=args.network_environment,
        contact_card_file=args.contact_card_file,
        contact_card_path=args.contact_card_path,
        contact_card_address=args.contact_card_address,
        contact_card_endpoint=args.contact_card_endpoint,
        contact_card_imported=(None if args.contact_card_imported is None else args.contact_card_imported == "true"),
        contact_card_used_for_send=(
            None if args.contact_card_used_for_send is None else args.contact_card_used_for_send == "true"
        ),
        issues_to_add=list(args.issue),
        notes_to_add=list(args.note),
        clear_default_notes=bool(args.clear_default_notes),
        auto_status=bool(args.auto_status),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
