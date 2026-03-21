#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def get_json(url: str, headers: dict[str, str] | None = None, timeout_sec: float = 5.0) -> dict:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compute_probe_sleep(interval_sec: float, jitter_ratio: float) -> float:
    if interval_sec <= 0:
        return 0.0
    if jitter_ratio <= 0:
        return interval_sec
    low = max(0.0, interval_sec * (1.0 - jitter_ratio))
    high = max(low, interval_sec * (1.0 + jitter_ratio))
    return random.uniform(low, high)


def build_summary(
    *,
    cycles: int,
    checks: int,
    failures: int,
    max_failures: int,
    max_failure_rate: float,
    burst_every: int,
    burst_size: int,
    burst_checks: int,
    jitter: float,
    restarts: int,
    max_consecutive_failures: int,
    max_consecutive_failures_allowed: int,
    restart_probe_failures: int,
    max_restart_probe_failures: int,
    duration_seconds: float,
    failure_cycles: list[int] | None = None,
    restart_failure_cycles: list[int] | None = None,
    max_failed_cycle_streak: int = 0,
    max_failed_cycle_streak_start: int = 0,
    max_failed_cycle_streak_end: int = 0,
    skipped_bind_restricted: bool = False,
) -> dict[str, float | int | bool | list[str]]:
    total = max(1, checks)
    failure_rate = failures / total
    failure_cycles = list(failure_cycles or [])
    restart_failure_cycles = list(restart_failure_cycles or [])
    blocking_reasons: list[str] = []
    if failures > int(max_failures):
        blocking_reasons.append(f"failures>{int(max_failures)}")
    if failure_rate > float(max_failure_rate):
        blocking_reasons.append(f"failure_rate>{float(max_failure_rate)}")
    if max_consecutive_failures > int(max_consecutive_failures_allowed):
        blocking_reasons.append(f"max_consecutive_failures>{int(max_consecutive_failures_allowed)}")
    if restart_probe_failures > int(max_restart_probe_failures):
        blocking_reasons.append(f"restart_probe_failures>{int(max_restart_probe_failures)}")
    return {
        "ok": not blocking_reasons,
        "skipped_bind_restricted": bool(skipped_bind_restricted),
        "cycles": int(cycles),
        "checks": total,
        "failures": int(failures),
        "failure_rate": round(failure_rate, 6),
        "max_failures": int(max_failures),
        "max_failure_rate": float(max_failure_rate),
        "burst_every": int(burst_every),
        "burst_size": int(burst_size),
        "burst_checks": int(burst_checks),
        "jitter": float(jitter),
        "restarts": int(restarts),
        "failure_cycles": failure_cycles,
        "first_failure_cycle": (failure_cycles[0] if failure_cycles else 0),
        "last_failure_cycle": (failure_cycles[-1] if failure_cycles else 0),
        "max_consecutive_failures": int(max_consecutive_failures),
        "max_consecutive_failures_allowed": int(max_consecutive_failures_allowed),
        "max_failed_cycle_streak": int(max_failed_cycle_streak),
        "max_failed_cycle_streak_start": int(max_failed_cycle_streak_start),
        "max_failed_cycle_streak_end": int(max_failed_cycle_streak_end),
        "restart_probe_failures": int(restart_probe_failures),
        "max_restart_probe_failures": int(max_restart_probe_failures),
        "restart_failure_cycles": restart_failure_cycles,
        "blocking_reasons": blocking_reasons,
        "duration_seconds": round(duration_seconds, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="EZchain local stability smoke")
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--restart-every", type=int, default=0, help="Restart service every N cycles; 0 disables restart")
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=0)
    parser.add_argument("--max-restart-probe-failures", type=int, default=0)
    parser.add_argument("--startup-wait", type=float, default=1.5)
    parser.add_argument("--restart-cooldown", type=float, default=1.2)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    parser.add_argument("--jitter", type=float, default=0.0, help="Probe interval jitter ratio, e.g. 0.2 => +/-20%%")
    parser.add_argument("--burst-every", type=int, default=0, help="Run burst probes every N cycles; 0 disables")
    parser.add_argument("--burst-size", type=int, default=1, help="Probe count during burst cycle")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    args = parser.parse_args()
    jitter_ratio = max(0.0, min(1.0, float(args.jitter)))
    burst_every = max(0, int(args.burst_every))
    burst_size = max(1, int(args.burst_size))

    root = Path(__file__).resolve().parent.parent
    serve_cmd = [sys.executable, "ezchain_cli.py", "--config", args.config, "serve"]

    def start_proc() -> subprocess.Popen:
        return subprocess.Popen(
            serve_cmd,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop_proc(p: subprocess.Popen) -> None:
        if p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()

    def read_err(p: subprocess.Popen) -> str:
        if p.stderr is None:
            return ""
        try:
            return p.stderr.read() or ""
        except Exception:
            return ""

    proc = start_proc()

    failures = 0
    checks = 0
    burst_checks = 0
    restarts = 0
    consecutive_failures = 0
    max_seen_consecutive_failures = 0
    restart_probe_failures = 0
    failure_cycles: list[int] = []
    restart_failure_cycles: list[int] = []
    failed_cycle_streak = 0
    failed_cycle_streak_start = 0
    max_failed_cycle_streak = 0
    max_failed_cycle_streak_start = 0
    max_failed_cycle_streak_end = 0
    awaiting_restart_probe = False
    started_at = time.time()
    try:
        time.sleep(max(0.1, args.startup_wait))
        if proc.poll() is not None:
            err = read_err(proc)
            bind_restricted = "PermissionError" in err and "Operation not permitted" in err
            summary = build_summary(
                cycles=int(args.cycles),
                checks=int(args.cycles),
                failures=int(args.cycles),
                max_failures=int(args.max_failures),
                max_failure_rate=float(args.max_failure_rate),
                burst_every=burst_every,
                burst_size=burst_size,
                burst_checks=0,
                jitter=jitter_ratio,
                restarts=0,
                max_consecutive_failures=int(args.cycles),
                max_consecutive_failures_allowed=int(args.max_consecutive_failures),
                restart_probe_failures=0,
                max_restart_probe_failures=int(args.max_restart_probe_failures),
                duration_seconds=time.time() - started_at,
                failure_cycles=list(range(1, int(args.cycles) + 1)),
                restart_failure_cycles=[],
                max_failed_cycle_streak=int(args.cycles),
                max_failed_cycle_streak_start=1 if int(args.cycles) > 0 else 0,
                max_failed_cycle_streak_end=int(args.cycles),
                skipped_bind_restricted=bool(args.allow_bind_restricted_skip and bind_restricted),
            )
            if args.json_out:
                Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary, indent=2))
            if summary["ok"]:
                print("[stability-smoke] SKIPPED (bind restricted environment)")
                return 0
            print("[stability-smoke] FAILED to start local service")
            return 1

        for i in range(args.cycles):
            cycle_is_burst = burst_every > 0 and (i + 1) % burst_every == 0
            cycle_probe_count = burst_size if cycle_is_burst else 1
            if cycle_is_burst:
                burst_checks += cycle_probe_count

            cycle_failures = 0
            for _ in range(cycle_probe_count):
                checks += 1
                probe_failed = False
                try:
                    health = get_json("http://127.0.0.1:8787/health", timeout_sec=float(args.request_timeout))
                    if not health.get("ok"):
                        probe_failed = True
                except (URLError, TimeoutError, json.JSONDecodeError):
                    probe_failed = True

                if probe_failed:
                    failures += 1
                    cycle_failures += 1
                    consecutive_failures += 1
                    max_seen_consecutive_failures = max(max_seen_consecutive_failures, consecutive_failures)
                else:
                    consecutive_failures = 0

                if awaiting_restart_probe:
                    if probe_failed:
                        restart_probe_failures += 1
                        restart_failure_cycles.append(i + 1)
                    awaiting_restart_probe = False
            if cycle_failures > 0:
                failure_cycles.append(i + 1)
                if failed_cycle_streak == 0:
                    failed_cycle_streak_start = i + 1
                failed_cycle_streak += 1
                if failed_cycle_streak > max_failed_cycle_streak:
                    max_failed_cycle_streak = failed_cycle_streak
                    max_failed_cycle_streak_start = failed_cycle_streak_start
                    max_failed_cycle_streak_end = i + 1
            else:
                failed_cycle_streak = 0
                failed_cycle_streak_start = 0
            print(
                f"cycle={i + 1}/{args.cycles} probes={cycle_probe_count} "
                f"cycle_failures={cycle_failures} total_failures={failures}"
            )

            if args.restart_every > 0 and (i + 1) % args.restart_every == 0 and (i + 1) < args.cycles:
                stop_proc(proc)
                proc = start_proc()
                restarts += 1
                awaiting_restart_probe = True
                time.sleep(max(0.1, args.restart_cooldown))

            time.sleep(compute_probe_sleep(float(args.interval), jitter_ratio))
    finally:
        stop_proc(proc)

    summary = build_summary(
        cycles=int(args.cycles),
        checks=int(checks),
        failures=int(failures),
        max_failures=int(args.max_failures),
        max_failure_rate=float(args.max_failure_rate),
        burst_every=burst_every,
        burst_size=burst_size,
        burst_checks=int(burst_checks),
        jitter=jitter_ratio,
        restarts=int(restarts),
        max_consecutive_failures=int(max_seen_consecutive_failures),
        max_consecutive_failures_allowed=int(args.max_consecutive_failures),
        restart_probe_failures=int(restart_probe_failures),
        max_restart_probe_failures=int(args.max_restart_probe_failures),
        duration_seconds=time.time() - started_at,
        failure_cycles=failure_cycles,
        restart_failure_cycles=restart_failure_cycles,
        max_failed_cycle_streak=max_failed_cycle_streak,
        max_failed_cycle_streak_start=max_failed_cycle_streak_start,
        max_failed_cycle_streak_end=max_failed_cycle_streak_end,
    )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if not summary["ok"]:
        print(
            "[stability-smoke] FAILED with "
            f"{summary['failures']} failed checks ({float(summary['failure_rate']):.4f} rate), "
            f"max_consecutive_failures={summary['max_consecutive_failures']}, "
            f"restart_probe_failures={summary['restart_probe_failures']}"
        )
        return 1

    print("[stability-smoke] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
