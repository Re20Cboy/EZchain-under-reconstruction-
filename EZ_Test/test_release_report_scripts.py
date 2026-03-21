from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.release_report import _external_trial_progress


def _trial_record(*, status: str = "passed", send_status: str = "passed", connectivity_result: str = "passed", connectivity_checked: bool = True) -> dict:
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
            "connectivity_checked": connectivity_checked,
            "connectivity_result": connectivity_result,
        },
        "workflow": {
            "install": "passed",
            "wallet_create_or_import": "passed",
            "network_check": "passed",
            "faucet": "passed",
            "send": send_status,
            "history_receipts_balance_match": "passed",
        },
        "status": status,
        "issues": [],
        "notes": ["trial completed"],
    }


def test_external_trial_progress_marks_remaining_and_failed_steps():
    progress = _external_trial_progress(
        _trial_record(status="pending", send_status="pending", connectivity_result="pending", connectivity_checked=False)
    )

    assert "profile.connectivity_checked" in progress["remaining_steps"]
    assert "profile.connectivity_result" in progress["remaining_steps"]
    assert "workflow.send" in progress["remaining_steps"]
    assert progress["failed_steps"] == []

    progress = _external_trial_progress(
        _trial_record(status="failed", send_status="failed", connectivity_result="failed", connectivity_checked=True)
    )

    assert "profile.connectivity_result" in progress["failed_steps"]
    assert "workflow.send" in progress["failed_steps"]


def test_prepare_rc_carries_external_trial_progress_fields():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        report_path = tmp / "release_report.json"
        readiness_path = tmp / "v2_readiness.json"
        manifest_path = tmp / "rc_manifest.json"

        report_path.write_text(
            json.dumps(
                {
                    "git_head": "abc123",
                    "overall_status": "failed",
                    "risks": ["external trial record is still incomplete: workflow.send"],
                    "summary": {
                        "external_trial_status": "pending",
                        "external_trial_gate_status": "failed",
                        "external_trial_remaining_steps": ["workflow.send"],
                        "external_trial_failed_steps": [],
                        "official_testnet_gate_status": "passed",
                        "v2_adversarial_gate_status": "passed",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        readiness_path.write_text(
            json.dumps(
                {
                    "ready_for_v2_default": False,
                    "blocking_items": [{"name": "external_trial_gate", "detail": "pending"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        subprocess.run(
            [
                sys.executable,
                "scripts/prepare_rc.py",
                "--version",
                "v0.1.0-rc-test",
                "--report-json",
                str(report_path),
                "--readiness-json",
                str(readiness_path),
                "--notes-dir",
                str(tmp / "notes"),
                "--manifest-out",
                str(manifest_path),
            ],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["external_trial_remaining_steps"] == ["workflow.send"]
        assert manifest["external_trial_failed_steps"] == []
