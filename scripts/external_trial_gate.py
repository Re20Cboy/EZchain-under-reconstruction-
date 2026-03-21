#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
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

VALID_STEP_STATUSES = {"pending", "passed", "failed"}
VALID_TOP_STATUSES = {"pending", "passed", "failed"}
VALID_OS_VALUES = {"macos", "windows"}
VALID_INSTALL_PATHS = {"source", "binary"}
VALID_CONNECTIVITY_RESULTS = {"pending", "passed", "failed"}


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_iso8601(value: object) -> bool:
    if not _is_non_empty_string(value):
        return False
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_trial_record(record: dict, require_passed: bool) -> list[str]:
    failures: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in record:
            failures.append(f"missing top-level field: {key}")

    if "trial_id" in record and not _is_non_empty_string(record.get("trial_id")):
        failures.append("trial_id must be a non-empty string")
    if "executor" in record and not _is_non_empty_string(record.get("executor")):
        failures.append("executor must be a non-empty string")
    if "executed_at" in record and not _is_valid_iso8601(record.get("executed_at")):
        failures.append("executed_at must be a valid ISO-8601 timestamp")

    workflow = record.get("workflow")
    if not isinstance(workflow, dict):
        failures.append("workflow must be an object")
    else:
        for key in REQUIRED_WORKFLOW_KEYS:
            if key not in workflow:
                failures.append(f"missing workflow field: {key}")
                continue
            step_status = str(workflow.get(key, "")).lower()
            if step_status not in VALID_STEP_STATUSES:
                failures.append(f"workflow.{key} must be one of pending/passed/failed")

    profile = record.get("profile")
    if not isinstance(profile, dict):
        failures.append("profile must be an object")
    else:
        if profile.get("name") != "official-testnet":
            failures.append("profile.name must be 'official-testnet'")
        connectivity_checked = profile.get("connectivity_checked")
        if not isinstance(connectivity_checked, bool):
            failures.append("profile.connectivity_checked must be true or false")
        connectivity_result = str(profile.get("connectivity_result", "")).lower()
        if connectivity_result not in VALID_CONNECTIVITY_RESULTS:
            failures.append("profile.connectivity_result must be one of pending/passed/failed")
        if connectivity_result == "passed" and connectivity_checked is not True:
            failures.append("profile.connectivity_checked must be true when connectivity_result is 'passed'")
        if connectivity_checked is True and connectivity_result == "pending":
            failures.append("profile.connectivity_result cannot be 'pending' after connectivity_checked=true")

    environment = record.get("environment")
    if not isinstance(environment, dict):
        failures.append("environment must be an object")
    else:
        os_name = str(environment.get("os", "")).lower()
        if os_name not in VALID_OS_VALUES:
            failures.append("environment.os must be 'macos' or 'windows'")
        install_path = str(environment.get("install_path", "")).lower()
        if install_path not in VALID_INSTALL_PATHS:
            failures.append("environment.install_path must be 'source' or 'binary'")
        if not _is_non_empty_string(environment.get("config_path")):
            failures.append("environment.config_path must be a non-empty string")

    issues = record.get("issues")
    if not isinstance(issues, list):
        failures.append("issues must be a list")

    notes = record.get("notes")
    if not isinstance(notes, list):
        failures.append("notes must be a list")

    status = str(record.get("status", "")).lower()
    if status not in VALID_TOP_STATUSES:
        failures.append("status must be one of pending/passed/failed")
    if require_passed and status != "passed":
        failures.append(f"status must be 'passed', got '{record.get('status', '')}'")

    if require_passed and isinstance(workflow, dict):
        for key in REQUIRED_WORKFLOW_KEYS:
            step_status = str(workflow.get(key, "")).lower()
            if step_status != "passed":
                failures.append(f"workflow.{key} must be 'passed', got '{workflow.get(key, '')}'")
    if require_passed and isinstance(profile, dict):
        if profile.get("connectivity_checked") is not True:
            failures.append("profile.connectivity_checked must be true for a passed trial record")
        if str(profile.get("connectivity_result", "")).lower() != "passed":
            failures.append("profile.connectivity_result must be 'passed' for a passed trial record")

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
