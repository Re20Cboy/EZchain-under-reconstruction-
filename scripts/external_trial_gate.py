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
    "evidence",
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
VALID_NETWORK_ENVIRONMENTS = {"real-external", "single-host-rehearsal"}


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


def trial_network_environment(record: dict) -> str:
    environment = record.get("environment")
    if not isinstance(environment, dict):
        return "unknown"
    raw = str(environment.get("network_environment", "")).strip().lower()
    if raw in VALID_NETWORK_ENVIRONMENTS:
        return raw
    return "unknown"


def validate_trial_record(record: dict, require_passed: bool, require_real_external: bool = False) -> list[str]:
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
        if "network_environment" in environment and trial_network_environment(record) == "unknown":
            failures.append(
                "environment.network_environment must be 'real-external' or 'single-host-rehearsal'"
            )
        if not _is_non_empty_string(environment.get("config_path")):
            failures.append("environment.config_path must be a non-empty string")

    issues = record.get("issues")
    if not isinstance(issues, list):
        failures.append("issues must be a list")

    notes = record.get("notes")
    if not isinstance(notes, list):
        failures.append("notes must be a list")

    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        failures.append("evidence must be an object")
    else:
        contact_card = evidence.get("contact_card")
        if not isinstance(contact_card, dict):
            failures.append("evidence.contact_card must be an object")
        else:
            path = contact_card.get("path", "")
            address = contact_card.get("address", "")
            endpoint = contact_card.get("endpoint", "")
            imported = contact_card.get("imported", False)
            used_for_send = contact_card.get("used_for_send", False)
            if path != "" and not _is_non_empty_string(path):
                failures.append("evidence.contact_card.path must be an empty string or a non-empty string")
            if address != "" and not _is_non_empty_string(address):
                failures.append("evidence.contact_card.address must be an empty string or a non-empty string")
            if endpoint != "" and not _is_non_empty_string(endpoint):
                failures.append("evidence.contact_card.endpoint must be an empty string or a non-empty string")
            if not isinstance(imported, bool):
                failures.append("evidence.contact_card.imported must be true or false")
            if not isinstance(used_for_send, bool):
                failures.append("evidence.contact_card.used_for_send must be true or false")
            if used_for_send and imported is not True:
                failures.append("evidence.contact_card.imported must be true when used_for_send is true")
            if used_for_send and not _is_non_empty_string(address):
                failures.append("evidence.contact_card.address must be set when used_for_send is true")
            if used_for_send and not _is_non_empty_string(endpoint):
                failures.append("evidence.contact_card.endpoint must be set when used_for_send is true")

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
    if require_real_external and trial_network_environment(record) != "real-external":
        failures.append("environment.network_environment must be 'real-external' for a formal passed trial record")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external official-testnet trial record")
    parser.add_argument("--record", required=True)
    parser.add_argument("--require-passed", action="store_true")
    parser.add_argument("--require-real-external", action="store_true")
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

    failures = validate_trial_record(
        record,
        require_passed=bool(args.require_passed),
        require_real_external=bool(args.require_real_external),
    )
    payload = {
        "ok": len(failures) == 0,
        "record": str(record_path),
        "status": record.get("status", "unknown"),
        "trial_id": record.get("trial_id", ""),
        "network_environment": trial_network_environment(record),
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
