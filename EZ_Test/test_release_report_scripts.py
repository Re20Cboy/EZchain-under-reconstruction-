from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.release_report import (
    _consensus_tcp_step_notes,
    _external_trial_contact_card,
    _external_trial_network_environment,
    _external_trial_progress,
    _external_trial_tx_send_readiness,
    _merge_consensus_summary,
    should_run_v2_account_recovery as report_should_run_v2_account_recovery,
    to_markdown,
)
from scripts.consensus_gate import build_summary, run_step_with_retry
from scripts.release_gate import should_run_v2_account_recovery as gate_should_run_v2_account_recovery
from scripts.release_candidate import should_with_v2_account_recovery
from scripts.v2_readiness import _evaluate
from argparse import Namespace


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
            },
            "tx_send_readiness": {
                "captured": True,
                "capability": "remote_send",
                "ready": True,
                "blockers": [],
                "remote_account_status": "running",
                "wallet_address_matches": True,
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
                        "consensus_gate_status": "passed",
                        "consensus_core_status": "passed",
                        "consensus_sync_status": "passed",
                        "consensus_catchup_status": "passed",
                        "consensus_network_status": "passed",
                        "consensus_recovery_status": "passed",
                        "consensus_tcp_evidence_status": "not_executed_bind_restricted",
                        "consensus_formal_tcp_evidence_ready": False,
                        "consensus_tcp_step_notes": [
                            "consensus_tcp_catchup_suite: all skipped after 3 attempt(s); SKIPPED [1] foo: bind_not_permitted:[Errno 1] Operation not permitted"
                        ],
                        "stability_gate_status": "passed",
                        "stability_failures": 0,
                        "stability_failure_rate": 0.0,
                        "stability_restarts": 2,
                        "stability_burst_checks": 6,
                        "stability_blocking_reasons": [],
                        "v2_account_recovery_gate_status": "passed",
                        "v2_account_recovery_final_sync_health": "healthy",
                        "v2_account_recovery_final_sync_health_reason": "stable_after_recovery",
                        "v2_account_recovery_flaps_requested": 2,
                        "v2_account_recovery_flaps_completed": 2,
                        "v2_account_recovery_blocking_reasons": [],
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        report_path.with_suffix(".md").write_text("# report\n", encoding="utf-8")
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
        readiness_path.with_suffix(".md").write_text("# readiness\n", encoding="utf-8")

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
        notes_text = (tmp / "notes" / "v0.1.0-rc-test.md").read_text(encoding="utf-8")
        assert manifest["external_trial_remaining_steps"] == ["workflow.send"]
        assert manifest["external_trial_failed_steps"] == []
        assert manifest["consensus_gate_status"] == "passed"
        assert manifest["consensus_core_status"] == "passed"
        assert manifest["consensus_tcp_evidence_status"] == "not_executed_bind_restricted"
        assert manifest["consensus_formal_tcp_evidence_ready"] is False
        assert manifest["consensus_tcp_step_notes"] == [
            "consensus_tcp_catchup_suite: all skipped after 3 attempt(s); SKIPPED [1] foo: bind_not_permitted:[Errno 1] Operation not permitted"
        ]
        assert manifest["release_report_md"] == str(report_path.with_suffix(".md"))
        assert manifest["v2_readiness_md"] == str(readiness_path.with_suffix(".md"))
        assert manifest["stability_gate_status"] == "passed"
        assert manifest["stability_restarts"] == 2
        assert manifest["stability_burst_checks"] == 6
        assert manifest["stability_blocking_reasons"] == []
        assert manifest["v2_account_recovery_gate_status"] == "passed"
        assert manifest["v2_account_recovery_final_sync_health"] == "healthy"
        assert manifest["v2_account_recovery_final_sync_health_reason"] == "stable_after_recovery"
        assert manifest["v2_account_recovery_flaps_requested"] == 2
        assert manifest["v2_account_recovery_flaps_completed"] == 2
        assert manifest["v2_account_recovery_blocking_reasons"] == []
        assert manifest["artifacts"]["release_report_json"]["exists"] is True
        assert manifest["artifacts"]["release_report_md"]["exists"] is True
        assert manifest["artifacts"]["v2_readiness_json"]["exists"] is True
        assert manifest["artifacts"]["v2_readiness_md"]["exists"] is True
        assert "consensus_tcp_evidence_status" in notes_text
        assert "consensus_tcp_step_notes" in notes_text
        assert "bind-restricted" in notes_text


def test_release_candidate_dry_run_always_carries_consensus_gate():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "release_candidate_manifest.json"

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/release_candidate.py",
                "--version",
                "v0.1.0-rc-test",
                "--dry-run",
                "--manifest-out",
                str(manifest_path),
            ],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        report_step = next(step for step in payload["steps"] if step["name"] == "release_report")

        assert "--with-consensus" in report_step["command"]
        assert payload["status"] == "planned"
        assert payload["artifacts_ready"] is False
        assert payload["artifacts"]["release_report_json"]["path"] == "dist/release_report.json"
        assert payload["artifacts"]["release_report_json"]["exists"] is False
        assert payload["artifacts"]["v2_readiness_json"]["path"] == "dist/v2_readiness.json"
        assert payload["artifacts"]["rc_manifest"]["path"] == "dist/rc_manifest.json"
        assert payload["artifacts"]["release_notes"]["path"] == "doc/releases/v0.1.0-rc-test.md"
        assert "[release-candidate] wrote" in proc.stdout


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


def test_external_trial_tx_send_readiness_summary_reads_structured_evidence():
    record = _trial_record()
    record["evidence"]["tx_send_readiness"] = {
        "captured": True,
        "capability": "remote_send",
        "ready": False,
        "blockers": ["remote_account_not_running"],
        "remote_account_status": "stopped",
        "wallet_address_matches": True,
    }

    summary = _external_trial_tx_send_readiness(record)

    assert summary["captured"] is True
    assert summary["capability"] == "remote_send"
    assert summary["ready"] is False
    assert summary["blockers"] == ["remote_account_not_running"]
    assert summary["remote_account_status"] == "stopped"
    assert summary["wallet_address_matches"] is True


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


def test_consensus_gate_summary_marks_tcp_bind_restricted_skip_as_not_executed():
    summary = build_summary(
        [
            {"name": "consensus_core_suite", "status": "passed", "layer": "core", "transport": "none", "all_skipped": False, "skipped_bind_restricted": False},
            {"name": "consensus_sync_suite", "status": "passed", "layer": "sync", "transport": "static", "all_skipped": False, "skipped_bind_restricted": False},
            {"name": "consensus_catchup_suite", "status": "passed", "layer": "catchup", "transport": "static", "all_skipped": False, "skipped_bind_restricted": False},
            {"name": "consensus_recovery_suite", "status": "passed", "layer": "recovery", "transport": "static", "all_skipped": False, "skipped_bind_restricted": False},
            {"name": "consensus_static_network_suite", "status": "passed", "layer": "network", "transport": "static", "all_skipped": False, "skipped_bind_restricted": False},
            {"name": "consensus_tcp_catchup_suite", "status": "passed", "layer": "catchup", "transport": "tcp", "all_skipped": True, "skipped_bind_restricted": True},
            {"name": "consensus_tcp_network_suite", "status": "passed", "layer": "network", "transport": "tcp", "all_skipped": True, "skipped_bind_restricted": True},
        ]
    )

    assert summary["layers"]["core"] == "passed"
    assert summary["layers"]["catchup"] == "passed"
    assert summary["tcp_steps_total"] == 2
    assert summary["tcp_steps_executed"] == 0
    assert summary["tcp_bind_restricted_skips"] == 2
    assert summary["tcp_evidence_status"] == "not_executed_bind_restricted"
    assert summary["formal_tcp_evidence_ready"] is False


def test_consensus_gate_tcp_retry_stops_after_first_executed_attempt(monkeypatch, tmp_path):
    attempts = [
        {
            "name": "consensus_tcp_network_suite",
            "status": "passed",
            "transport": "tcp",
            "all_skipped": True,
            "skipped_bind_restricted": True,
        },
        {
            "name": "consensus_tcp_network_suite",
            "status": "passed",
            "transport": "tcp",
            "all_skipped": False,
            "skipped_bind_restricted": False,
        },
    ]

    def _fake_run_step(name, cmd, cwd):
        return dict(attempts.pop(0))

    monkeypatch.setattr("scripts.consensus_gate.run_step", _fake_run_step)

    step = run_step_with_retry("consensus_tcp_network_suite", ["pytest"], tmp_path)

    assert step["attempts"] == 2
    assert step["retried_after_all_skipped"] is True
    assert step["all_skipped"] is False
    assert attempts == []


def test_consensus_gate_tcp_retry_preserves_all_skipped_after_final_attempt(monkeypatch, tmp_path):
    attempts = [
        {
            "name": "consensus_tcp_catchup_suite",
            "status": "passed",
            "transport": "tcp",
            "all_skipped": True,
            "skipped_bind_restricted": True,
        },
        {
            "name": "consensus_tcp_catchup_suite",
            "status": "passed",
            "transport": "tcp",
            "all_skipped": True,
            "skipped_bind_restricted": True,
        },
        {
            "name": "consensus_tcp_catchup_suite",
            "status": "passed",
            "transport": "tcp",
            "all_skipped": True,
            "skipped_bind_restricted": True,
        },
    ]

    def _fake_run_step(name, cmd, cwd):
        return dict(attempts.pop(0))

    monkeypatch.setattr("scripts.consensus_gate.run_step", _fake_run_step)

    step = run_step_with_retry("consensus_tcp_catchup_suite", ["pytest"], tmp_path)

    assert step["attempts"] == 3
    assert step["retried_after_all_skipped"] is True
    assert step["all_skipped"] is True
    assert step["skipped_bind_restricted"] is True
    assert attempts == []


def test_release_report_merges_consensus_summary_and_marks_tcp_evidence_gap():
    summary = {}
    risks: list[str] = []

    _merge_consensus_summary(
        summary,
        {
            "layers": {
                "core": "passed",
                "sync": "passed",
                "catchup": "passed",
                "network": "passed",
                "recovery": "passed",
            },
            "static_steps_total": 4,
            "static_steps_passed": 4,
            "tcp_steps_total": 2,
            "tcp_steps_passed": 2,
            "tcp_steps_executed": 0,
            "tcp_steps_all_skipped": 2,
            "tcp_bind_restricted_skips": 2,
            "tcp_evidence_status": "not_executed_bind_restricted",
            "formal_tcp_evidence_ready": False,
        },
        risks,
    )

    assert summary["consensus_core_status"] == "passed"
    assert summary["consensus_sync_status"] == "passed"
    assert summary["consensus_catchup_status"] == "passed"
    assert summary["consensus_network_status"] == "passed"
    assert summary["consensus_recovery_status"] == "passed"
    assert summary["consensus_tcp_steps_executed"] == 0
    assert summary["consensus_tcp_evidence_status"] == "not_executed_bind_restricted"
    assert summary["consensus_formal_tcp_evidence_ready"] is False
    assert any("consensus TCP evidence not executed" in risk for risk in risks)


def test_release_report_markdown_explains_bind_restricted_tcp_evidence_gap():
    markdown = to_markdown(
        {
            "generated_at": "2026-03-23T00:00:00Z",
            "git_head": "abc123",
            "overall_status": "passed",
            "summary": {
                "consensus_gate_status": "passed",
                "consensus_tcp_evidence_status": "not_executed_bind_restricted",
                "consensus_formal_tcp_evidence_ready": False,
            },
            "risks": [],
            "steps": [],
        }
    )

    assert "## Consensus Evidence" in markdown
    assert "consensus_tcp_evidence_status: not_executed_bind_restricted" in markdown
    assert "layered consensus validation passed" in markdown
    assert "release judgement still follows the gate/report evidence chain" in markdown


def test_release_report_extracts_tcp_step_notes_from_consensus_gate_payload():
    notes = _consensus_tcp_step_notes(
        {
            "steps": [
                {
                    "name": "consensus_tcp_catchup_suite",
                    "transport": "tcp",
                    "attempts": 3,
                    "all_skipped": True,
                    "stdout_tail": (
                        "ss\n"
                        "SKIPPED [1] EZ_Test/test_ez_v2_network.py:2976: bind_not_permitted:[Errno 1] Operation not permitted\n"
                    ),
                },
                {
                    "name": "consensus_tcp_network_suite",
                    "transport": "tcp",
                    "attempts": 2,
                    "all_skipped": False,
                    "stdout_tail": ".....\n5 passed in 10.0s\n",
                },
            ]
        }
    )

    assert notes[0].startswith("consensus_tcp_catchup_suite: all skipped after 3 attempt(s);")
    assert "bind_not_permitted:[Errno 1] Operation not permitted" in notes[0]
    assert notes[1] == "consensus_tcp_network_suite: executed after 2 attempt(s)"


def test_release_report_markdown_includes_tcp_step_notes():
    markdown = to_markdown(
        {
            "generated_at": "2026-03-23T00:00:00Z",
            "git_head": "abc123",
            "overall_status": "passed",
            "summary": {
                "consensus_gate_status": "passed",
                "consensus_tcp_evidence_status": "not_executed_bind_restricted",
                "consensus_formal_tcp_evidence_ready": False,
                "consensus_tcp_step_notes": [
                    "consensus_tcp_catchup_suite: all skipped after 3 attempt(s); SKIPPED [1] foo: bind_not_permitted:[Errno 1] Operation not permitted"
                ],
            },
            "risks": [],
            "steps": [],
        }
    )

    assert "TCP step details:" in markdown
    assert "consensus_tcp_catchup_suite: all skipped after 3 attempt(s)" in markdown


def test_release_report_markdown_includes_stability_and_recovery_sections():
    markdown = to_markdown(
        {
            "generated_at": "2026-03-23T00:00:00Z",
            "git_head": "abc123",
            "overall_status": "passed",
            "summary": {
                "stability_gate_status": "passed",
                "stability_skipped_bind_restricted": False,
                "stability_failures": 0,
                "stability_failure_rate": 0.0,
                "stability_restarts": 2,
                "stability_burst_checks": 6,
                "stability_failure_cycles": [],
                "stability_restart_failure_cycles": [],
                "stability_max_failed_cycle_streak": 0,
                "stability_blocking_reasons": [],
                "v2_account_recovery_gate_status": "passed",
                "v2_account_recovery_skipped_bind_restricted": False,
                "v2_account_recovery_flaps_requested": 2,
                "v2_account_recovery_flaps_completed": 2,
                "v2_account_recovery_final_sync_health": "healthy",
                "v2_account_recovery_final_sync_health_reason": "stable_after_recovery",
                "v2_account_recovery_degraded_rounds": [1],
                "v2_account_recovery_recovered_rounds": [1],
                "v2_account_recovery_steady_rounds": [1],
                "v2_account_recovery_blocking_reasons": [],
            },
            "risks": [],
            "steps": [],
        }
    )

    assert "## Stability Evidence" in markdown
    assert "stability_restarts: 2" in markdown
    assert "## V2 Account Recovery" in markdown
    assert "v2_account_recovery_final_sync_health: healthy" in markdown


def test_v2_readiness_main_records_source_report_metadata():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        report_path = tmp / "release_report.json"
        out_json = tmp / "v2_readiness.json"
        out_md = tmp / "v2_readiness.md"
        report_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-23T00:00:00Z",
                    "git_head": "abc123",
                    "overall_status": "passed",
                    "risks": [],
                    "summary": {
                        "v2_gate_status": "passed",
                        "v2_adversarial_gate_status": "passed",
                        "consensus_gate_status": "passed",
                        "v2_account_recovery_gate_status": "passed",
                        "stability_gate_status": "passed",
                        "official_testnet_gate_status": "passed",
                        "external_trial_gate_status": "passed",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        subprocess.run(
            [
                sys.executable,
                "scripts/v2_readiness.py",
                "--report-json",
                str(report_path),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(out_json.read_text(encoding="utf-8"))
        markdown = out_md.read_text(encoding="utf-8")
        assert payload["source_report_json"] == str(report_path)
        assert payload["source_report_git_head"] == "abc123"
        assert payload["source_report_generated_at"] == "2026-03-23T00:00:00Z"
        assert "source_report_json" in markdown
        assert "source_report_git_head: abc123" in markdown


def test_v2_readiness_blocks_when_consensus_gate_is_missing():
    payload = _evaluate(
        {
            "overall_status": "passed",
            "risks": [],
            "summary": {
                "v2_gate_status": "passed",
                "v2_adversarial_gate_status": "passed",
                "v2_account_recovery_gate_status": "passed",
                "stability_gate_status": "passed",
                "official_testnet_gate_status": "passed",
                "external_trial_gate_status": "passed",
            },
        }
    )

    assert payload["ready_for_v2_default"] is False
    assert any(item["name"] == "consensus_gate" for item in payload["blocking_items"])
    tcp_check = next(item for item in payload["checks"] if item["name"] == "consensus_tcp_evidence")
    assert tcp_check["required"] is False
    assert tcp_check["status"] == "failed"
    assert tcp_check["detail"] == "consensus_tcp_evidence_status=missing"


def test_v2_readiness_blocks_when_v2_account_recovery_gate_is_missing():
    payload = _evaluate(
        {
            "overall_status": "passed",
            "risks": [],
            "summary": {
                "v2_gate_status": "passed",
                "consensus_gate_status": "passed",
                "v2_adversarial_gate_status": "passed",
                "stability_gate_status": "passed",
                "official_testnet_gate_status": "passed",
                "external_trial_gate_status": "passed",
            },
        }
    )

    assert payload["ready_for_v2_default"] is False
    assert any(item["name"] == "v2_account_recovery_gate" for item in payload["blocking_items"])


def test_v2_readiness_reports_consensus_tcp_evidence_status_without_making_it_blocking():
    payload = _evaluate(
        {
            "overall_status": "passed",
            "risks": [],
            "summary": {
                "v2_gate_status": "passed",
                "consensus_gate_status": "passed",
                "consensus_tcp_evidence_status": "not_executed_bind_restricted",
                "consensus_formal_tcp_evidence_ready": False,
                "v2_adversarial_gate_status": "passed",
                "v2_account_recovery_gate_status": "passed",
                "stability_gate_status": "passed",
                "official_testnet_gate_status": "passed",
                "external_trial_gate_status": "passed",
            },
        }
    )

    tcp_check = next(item for item in payload["checks"] if item["name"] == "consensus_tcp_evidence")
    assert tcp_check["required"] is False
    assert tcp_check["status"] == "failed"
    assert tcp_check["detail"] == "consensus_tcp_evidence_status=not_executed_bind_restricted"
    assert all(item["name"] != "consensus_tcp_evidence" for item in payload["blocking_items"])


def test_release_flow_auto_enables_v2_account_recovery_when_stability_is_requested():
    args = Namespace(with_stability=True, with_v2_account_recovery=False)

    assert gate_should_run_v2_account_recovery(args) is True
    assert report_should_run_v2_account_recovery(args) is True
    assert should_with_v2_account_recovery(args) is True

    args = Namespace(with_stability=False, with_v2_account_recovery=False)

    assert gate_should_run_v2_account_recovery(args) is False
    assert report_should_run_v2_account_recovery(args) is False
    assert should_with_v2_account_recovery(args) is False
