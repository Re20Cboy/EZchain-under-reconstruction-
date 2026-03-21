from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.external_trial_gate import validate_trial_record


def _base_record() -> dict:
    return {
        "trial_id": "official-testnet-20260321-01",
        "executed_at": "2026-03-21T00:00:00Z",
        "executor": "tester",
        "environment": {
            "os": "macos",
            "install_path": "source",
            "config_path": "ezchain.yaml",
        },
        "profile": {
            "name": "official-testnet",
            "connectivity_checked": True,
            "connectivity_result": "passed",
        },
        "workflow": {
            "install": "passed",
            "wallet_create_or_import": "passed",
            "network_check": "passed",
            "faucet": "passed",
            "send": "passed",
            "history_receipts_balance_match": "passed",
        },
        "status": "passed",
        "issues": [],
        "notes": ["trial completed"],
    }


def test_validate_trial_record_accepts_complete_passed_record():
    failures = validate_trial_record(_base_record(), require_passed=True)
    assert failures == []


def test_validate_trial_record_rejects_bad_environment_and_timestamp():
    record = _base_record()
    record["executed_at"] = "not-a-time"
    record["environment"]["os"] = "linux"
    record["environment"]["install_path"] = "manual"
    record["environment"]["config_path"] = ""

    failures = validate_trial_record(record, require_passed=False)

    assert "executed_at must be a valid ISO-8601 timestamp" in failures
    assert "environment.os must be 'macos' or 'windows'" in failures
    assert "environment.install_path must be 'source' or 'binary'" in failures
    assert "environment.config_path must be a non-empty string" in failures


def test_validate_trial_record_rejects_passed_record_without_connectivity_evidence():
    record = _base_record()
    record["profile"]["connectivity_checked"] = False
    record["profile"]["connectivity_result"] = "pending"

    failures = validate_trial_record(record, require_passed=True)

    assert "profile.connectivity_checked must be true for a passed trial record" in failures
    assert "profile.connectivity_result must be 'passed' for a passed trial record" in failures


def test_validate_trial_record_rejects_unknown_workflow_status():
    record = _base_record()
    record["workflow"]["send"] = "done"

    failures = validate_trial_record(record, require_passed=False)

    assert "workflow.send must be one of pending/passed/failed" in failures


def test_update_external_trial_auto_status_and_remaining_steps():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        record_path.write_text(json.dumps(_base_record(), indent=2), encoding="utf-8")

        payload = json.loads(record_path.read_text(encoding="utf-8"))
        payload["status"] = "pending"
        payload["profile"]["connectivity_checked"] = False
        payload["profile"]["connectivity_result"] = "pending"
        payload["workflow"]["send"] = "pending"
        record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["status"] == "pending"
        assert output["suggested_status"] == "pending"
        assert "profile.connectivity_checked" in output["remaining_steps"]
        assert "profile.connectivity_result" in output["remaining_steps"]
        assert "workflow.send" in output["remaining_steps"]


def test_update_external_trial_auto_status_marks_failed_on_failed_step():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        payload = _base_record()
        payload["status"] = "pending"
        payload["workflow"]["faucet"] = "failed"
        record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["status"] == "failed"
        assert output["suggested_status"] == "failed"
