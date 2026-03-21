from __future__ import annotations

import tempfile
from unittest import mock
from pathlib import Path

from scripts.v2_account_recovery_smoke import build_summary, run_smoke


def test_build_summary_reports_round_outcomes_and_final_state():
    summary = build_summary(
        flaps_requested=2,
        rounds=[
            {"round": 1, "degraded": True, "recovered": True, "steady": True},
            {"round": 2, "degraded": True, "recovered": False, "steady": False},
        ],
        final_state={
            "sync_health": "degraded",
            "sync_health_reason": "consensus_sync_failed",
            "recovery_count": 1,
            "max_consecutive_sync_failures": 3,
        },
        blocking_reasons=["round_2_did_not_recover"],
    )

    assert summary["ok"] is False
    assert summary["flaps_requested"] == 2
    assert summary["flaps_completed"] == 1
    assert summary["degraded_rounds"] == [1, 2]
    assert summary["recovered_rounds"] == [1]
    assert summary["steady_rounds"] == [1]
    assert summary["final_sync_health"] == "degraded"
    assert summary["final_sync_health_reason"] == "consensus_sync_failed"
    assert summary["final_recovery_count"] == 1
    assert summary["final_max_consecutive_sync_failures"] == 3
    assert summary["blocking_reasons"] == ["round_2_did_not_recover"]


def test_run_smoke_handles_bind_restricted_skip():
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("scripts.v2_account_recovery_smoke._reserve_port", side_effect=PermissionError("Operation not permitted")):
            summary = run_smoke(
                project_root=Path(td),
                flaps=1,
                degraded_timeout_sec=1.0,
                recovered_timeout_sec=1.0,
                steady_timeout_sec=1.0,
                allow_bind_restricted_skip=True,
            )

    assert "ok" in summary
    assert summary["skipped_bind_restricted"] is True
