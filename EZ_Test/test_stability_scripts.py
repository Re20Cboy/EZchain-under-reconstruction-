from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts.stability_gate import build_smoke_command
from scripts.stability_smoke import compute_probe_sleep


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
        request_timeout=2.5,
        jitter=0.2,
        burst_every=5,
        burst_size=3,
        allow_bind_restricted_skip=True,
    )

    cmd = build_smoke_command(args, Path("/tmp/stability.json"))
    joined = " ".join(cmd)

    assert "scripts/stability_smoke.py" in joined
    assert "--request-timeout 2.5" in joined
    assert "--jitter 0.2" in joined
    assert "--burst-every 5" in joined
    assert "--burst-size 3" in joined
    assert "--allow-bind-restricted-skip" in joined
