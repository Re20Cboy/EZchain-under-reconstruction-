#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import tempfile
from typing import Any


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Update an official-testnet external trial record safely")
    parser.add_argument("--record", required=True)
    parser.add_argument("--step", choices=WORKFLOW_KEYS)
    parser.add_argument("--step-status", choices=STEP_STATUSES)
    parser.add_argument("--status", choices=TOP_STATUSES)
    parser.add_argument("--connectivity-checked", choices=("true", "false"))
    parser.add_argument("--connectivity-result", choices=CONNECTIVITY_RESULTS)
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--clear-default-notes", action="store_true")
    parser.add_argument("--auto-status", action="store_true")
    args = parser.parse_args()

    record_path = Path(args.record)
    if not record_path.exists():
        raise SystemExit(f"record file not found: {record_path}")

    with _RecordLock(record_path.with_suffix(record_path.suffix + ".lock")):
        payload = _load_record(record_path)
        workflow = payload.setdefault("workflow", {})
        if not isinstance(workflow, dict):
            raise SystemExit("workflow must be a JSON object")
        profile = payload.setdefault("profile", {})
        if not isinstance(profile, dict):
            raise SystemExit("profile must be a JSON object")
        issues = payload.setdefault("issues", [])
        if not isinstance(issues, list):
            raise SystemExit("issues must be a JSON array")
        notes = payload.setdefault("notes", [])
        if not isinstance(notes, list):
            raise SystemExit("notes must be a JSON array")

        if args.step and args.step_status:
            workflow[args.step] = args.step_status
        elif args.step or args.step_status:
            raise SystemExit("--step and --step-status must be provided together")

        if args.status:
            payload["status"] = args.status

        if args.connectivity_checked is not None:
            profile["connectivity_checked"] = args.connectivity_checked == "true"
        if args.connectivity_result:
            profile["connectivity_result"] = args.connectivity_result

        if args.clear_default_notes:
            notes[:] = [item for item in notes if item != "Record any operator-facing problems here."]

        for item in args.issue:
            _append_unique(issues, item)
        for item in args.note:
            _append_unique(notes, item)

        if args.auto_status:
            payload["status"] = _derive_status(payload)

        remaining_steps = _remaining_steps(payload)
        suggested_status = _derive_status(payload)

        _atomic_write_json(record_path, payload)
    print(
        json.dumps(
            {
                "record": str(record_path),
                "status": payload.get("status", "unknown"),
                "suggested_status": suggested_status,
                "updated_step": args.step,
                "updated_step_status": args.step_status,
                "connectivity_checked": profile.get("connectivity_checked"),
                "connectivity_result": profile.get("connectivity_result"),
                "remaining_steps": remaining_steps,
                "issues_count": len(issues),
                "notes_count": len(notes),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
