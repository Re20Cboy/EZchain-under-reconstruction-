from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.release_report import (
    _external_trial_contact_card,
    _external_trial_network_environment,
    _external_trial_progress,
)
from scripts.v2_readiness import _evaluate


def _trial_record(*, status: str = "passed", send_status: str = "passed", connectivity_result: str = "passed", connectivity_checked: bool = True) -> dict:
    return {
        "trial_id": "official-testnet-20260321-01",
        "executed_at": "2026-03-21T00:00:00Z",
        "executor": "tester",
        "environment": {
            "os": "macos",
            "install_path": "source",
            "network_environment": "real-external",
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
        "evidence": {
            "contact_card": {
                "path": "",
                "address": "",
                "endpoint": "",
                "imported": False,
                "used_for_send": False,
            }
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
                        "v2_account_recovery_gate_status": "passed",
                        "v2_account_recovery_final_sync_health": "healthy",
                        "v2_account_recovery_blocking_reasons": [],
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
        assert manifest["v2_account_recovery_gate_status"] == "passed"
        assert manifest["v2_account_recovery_final_sync_health"] == "healthy"
        assert manifest["v2_account_recovery_blocking_reasons"] == []


def test_external_trial_contact_card_summary_reads_contact_card_evidence():
    record = _trial_record()
    record["evidence"]["contact_card"] = {
        "path": "bob-contact.json",
        "address": "0xb0b123",
        "endpoint": "192.168.1.20:19500",
        "imported": True,
        "used_for_send": True,
    }

    summary = _external_trial_contact_card(record)

    assert summary["present"] is True
    assert summary["path"] == "bob-contact.json"
    assert summary["address"] == "0xb0b123"
    assert summary["endpoint"] == "192.168.1.20:19500"
    assert summary["imported"] is True
    assert summary["used_for_send"] is True


def test_external_trial_network_environment_reads_environment_flag():
    record = _trial_record()
    assert _external_trial_network_environment(record) == "real-external"

    record["environment"]["network_environment"] = "single-host-rehearsal"
    assert _external_trial_network_environment(record) == "single-host-rehearsal"

    del record["environment"]["network_environment"]
    assert _external_trial_network_environment(record) == "unknown"


def test_release_report_summary_can_carry_stability_cycle_details():
    stability_summary = {
        "failure_cycles": [3, 4],
        "restart_failure_cycles": [4],
        "first_failure_cycle": 3,
        "last_failure_cycle": 4,
        "max_failed_cycle_streak": 2,
        "max_failed_cycle_streak_start": 3,
        "max_failed_cycle_streak_end": 4,
        "blocking_reasons": ["restart_probe_failures>0"],
    }

    assert stability_summary["failure_cycles"] == [3, 4]
    assert stability_summary["restart_failure_cycles"] == [4]
    assert stability_summary["max_failed_cycle_streak"] == 2
    assert stability_summary["max_failed_cycle_streak_start"] == 3
    assert stability_summary["max_failed_cycle_streak_end"] == 4
    assert stability_summary["blocking_reasons"] == ["restart_probe_failures>0"]


def test_release_report_summary_can_carry_v2_account_recovery_details():
    recovery_summary = {
        "flaps_requested": 2,
        "flaps_completed": 2,
        "degraded_rounds": [1, 2],
        "recovered_rounds": [1, 2],
        "steady_rounds": [1, 2],
        "final_sync_health": "healthy",
        "final_sync_health_reason": "stable_after_recovery",
        "final_recovery_count": 2,
        "blocking_reasons": [],
    }

    assert recovery_summary["flaps_requested"] == 2
    assert recovery_summary["flaps_completed"] == 2
    assert recovery_summary["degraded_rounds"] == [1, 2]
    assert recovery_summary["recovered_rounds"] == [1, 2]
    assert recovery_summary["steady_rounds"] == [1, 2]
    assert recovery_summary["final_sync_health"] == "healthy"
    assert recovery_summary["final_sync_health_reason"] == "stable_after_recovery"
    assert recovery_summary["final_recovery_count"] == 2
    assert recovery_summary["blocking_reasons"] == []


def test_v2_readiness_blocks_when_v2_account_recovery_gate_is_missing():
    payload = _evaluate(
        {
            "overall_status": "passed",
            "risks": [],
            "summary": {
                "v2_gate_status": "passed",
                "v2_adversarial_gate_status": "passed",
                "stability_gate_status": "passed",
                "official_testnet_gate_status": "passed",
                "external_trial_gate_status": "passed",
            },
        }
    )

    assert payload["ready_for_v2_default"] is False
    assert any(item["name"] == "v2_account_recovery_gate" for item in payload["blocking_items"])
