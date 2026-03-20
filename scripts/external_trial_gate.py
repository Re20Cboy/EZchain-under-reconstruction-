#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_TOP_LEVEL_KEYS = (
    "trial_id",
    "executed_at",
    "executor",
    "environment",
    "profile",
    "workflow",
    "status",
    "issues",
    "notes",
)

REQUIRED_WORKFLOW_KEYS = (
    "install",
    "wallet_create_or_import",
    "network_check",
    "faucet",
    "send",
    "history_receipts_balance_match",
)


def validate_trial_record(record: dict, require_passed: bool) -> list[str]:
    failures: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in record:
            failures.append(f"missing top-level field: {key}")

    workflow = record.get("workflow")
    if not isinstance(workflow, dict):
        failures.append("workflow must be an object")
    else:
        for key in REQUIRED_WORKFLOW_KEYS:
            if key not in workflow:
                failures.append(f"missing workflow field: {key}")

    profile = record.get("profile")
    if not isinstance(profile, dict):
        failures.append("profile must be an object")
    else:
        if profile.get("name") != "official-testnet":
            failures.append("profile.name must be 'official-testnet'")

    environment = record.get("environment")
    if not isinstance(environment, dict):
        failures.append("environment must be an object")

    issues = record.get("issues")
    if not isinstance(issues, list):
        failures.append("issues must be a list")

    notes = record.get("notes")
    if not isinstance(notes, list):
        failures.append("notes must be a list")

    status = str(record.get("status", "")).lower()
    if require_passed and status != "passed":
        failures.append(f"status must be 'passed', got '{record.get('status', '')}'")

    if require_passed and isinstance(workflow, dict):
        for key in REQUIRED_WORKFLOW_KEYS:
            step_status = str(workflow.get(key, "")).lower()
            if step_status != "passed":
                failures.append(f"workflow.{key} must be 'passed', got '{workflow.get(key, '')}'")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external official-testnet trial record")
    parser.add_argument("--record", required=True)
    parser.add_argument("--require-passed", action="store_true")
    args = parser.parse_args()

    record_path = Path(args.record)
    if not record_path.exists():
        print(json.dumps({"ok": False, "record": str(record_path), "failures": ["record file missing"]}, indent=2))
        print("[external-trial-gate] FAILED")
        return 1

    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "record": str(record_path), "failures": [f"invalid JSON: {exc}"]},
                indent=2,
            )
        )
        print("[external-trial-gate] FAILED")
        return 1

    if not isinstance(record, dict):
        print(
            json.dumps(
                {"ok": False, "record": str(record_path), "failures": ["record root must be an object"]},
                indent=2,
            )
        )
        print("[external-trial-gate] FAILED")
        return 1

    failures = validate_trial_record(record, require_passed=bool(args.require_passed))
    payload = {
        "ok": len(failures) == 0,
        "record": str(record_path),
        "status": record.get("status", "unknown"),
        "trial_id": record.get("trial_id", ""),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    if failures:
        print("[external-trial-gate] FAILED")
        return 1
    print("[external-trial-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
