from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts.stability_gate import build_smoke_command
from scripts.stability_smoke import build_summary, compute_probe_sleep


def test_compute_probe_sleep_without_jitter():
    assert compute_probe_sleep(1.0, 0.0) == 1.0
    assert compute_probe_sleep(0.0, 0.3) == 0.0


def test_compute_probe_sleep_with_jitter_bounds():
    for _ in range(20):
        value = compute_probe_sleep(2.0, 0.25)
        assert 1.5 <= value <= 2.5


def test_build_smoke_command_includes_new_stability_args():
    args = Namespace(
        config="ezchain.yaml",
        cycles=30,
        interval=1.0,
        restart_every=10,
        max_failures=0,
        max_failure_rate=0.0,
        max_consecutive_failures=0,
        max_restart_probe_failures=0,
        request_timeout=2.5,
        jitter=0.2,
        burst_every=5,
        burst_size=3,
        allow_bind_restricted_skip=True,
    )

    cmd = build_smoke_command(args, Path("/tmp/stability.json"))
    joined = " ".join(cmd)

    assert "scripts/stability_smoke.py" in joined
    assert "--max-consecutive-failures 0" in joined
    assert "--max-restart-probe-failures 0" in joined
    assert "--request-timeout 2.5" in joined
    assert "--jitter 0.2" in joined
    assert "--burst-every 5" in joined
    assert "--burst-size 3" in joined
    assert "--allow-bind-restricted-skip" in joined


def test_build_summary_fails_when_new_red_lines_are_crossed():
    summary = build_summary(
        cycles=10,
        checks=10,
        failures=1,
        max_failures=2,
        max_failure_rate=0.2,
        burst_every=5,
        burst_size=2,
        burst_checks=4,
        jitter=0.2,
        restarts=1,
        max_consecutive_failures=2,
        max_consecutive_failures_allowed=1,
        restart_probe_failures=1,
        max_restart_probe_failures=0,
        duration_seconds=12.5,
        failure_cycles=[4, 5],
        restart_failure_cycles=[5],
        max_failed_cycle_streak=2,
        max_failed_cycle_streak_start=4,
        max_failed_cycle_streak_end=5,
    )

    assert summary["ok"] is False
    assert summary["max_consecutive_failures"] == 2
    assert summary["restart_probe_failures"] == 1
    assert summary["failure_cycles"] == [4, 5]
    assert summary["restart_failure_cycles"] == [5]
    assert summary["first_failure_cycle"] == 4
    assert summary["last_failure_cycle"] == 5
    assert summary["max_failed_cycle_streak"] == 2
    assert summary["max_failed_cycle_streak_start"] == 4
    assert summary["max_failed_cycle_streak_end"] == 5
    assert "max_consecutive_failures>1" in summary["blocking_reasons"]
    assert "restart_probe_failures>0" in summary["blocking_reasons"]


def test_build_summary_passes_when_all_red_lines_hold():
    summary = build_summary(
        cycles=10,
        checks=10,
        failures=0,
        max_failures=0,
        max_failure_rate=0.0,
        burst_every=0,
        burst_size=1,
        burst_checks=0,
        jitter=0.0,
        restarts=1,
        max_consecutive_failures=0,
        max_consecutive_failures_allowed=0,
        restart_probe_failures=0,
        max_restart_probe_failures=0,
        duration_seconds=8.0,
        failure_cycles=[],
        restart_failure_cycles=[],
        max_failed_cycle_streak=0,
        max_failed_cycle_streak_start=0,
        max_failed_cycle_streak_end=0,
    )

    assert summary["ok"] is True
    assert summary["failure_rate"] == 0.0
    assert summary["failure_cycles"] == []
    assert summary["restart_failure_cycles"] == []
    assert summary["blocking_reasons"] == []
