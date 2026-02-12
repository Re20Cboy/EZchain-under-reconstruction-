#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def run_step(name: str, cmd: List[str], cwd: Path, timeout_sec: int = 1800) -> Dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    duration = round(time.time() - started, 3)
    return {
        "name": name,
        "command": " ".join(cmd),
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "duration_seconds": duration,
        "stdout_tail": (proc.stdout or "")[-3000:],
        "stderr_tail": (proc.stderr or "")[-3000:],
    }


def _git_head(cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    return "unknown"


def to_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# EZchain Release Report",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- git_head: {payload['git_head']}",
        f"- overall_status: {payload['overall_status']}",
        "",
        "## Steps",
    ]
    for step in payload["steps"]:
        lines.append(f"- [{step['status']}] {step['name']} ({step['duration_seconds']}s)")
        lines.append(f"  - command: `{step['command']}`")
        if step["status"] != "passed":
            lines.append(f"  - returncode: `{step['returncode']}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("- metrics check requires running local service (`ezchain_cli.py serve`).")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release checks and generate a report")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--out-json", default="dist/release_report.json")
    parser.add_argument("--out-md", default="dist/release_report.md")
    parser.add_argument("--run-gates", action="store_true")
    parser.add_argument("--with-stability", action="store_true")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    parser.add_argument("--run-metrics", action="store_true")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8787/metrics")
    parser.add_argument("--metrics-min-success-rate", type=float, default=0.0)
    parser.add_argument("--run-canary", action="store_true")
    parser.add_argument("--canary-url", default="http://127.0.0.1:8787/metrics")
    parser.add_argument("--canary-duration-sec", type=int, default=300)
    parser.add_argument("--canary-interval-sec", type=float, default=10.0)
    parser.add_argument("--canary-timeout-sec", type=float, default=5.0)
    parser.add_argument("--canary-out", default="dist/canary_report.json")
    parser.add_argument("--canary-max-crash-rate", type=float, default=0.05)
    parser.add_argument("--canary-min-tx-success-rate", type=float, default=0.95)
    parser.add_argument("--canary-max-sync-latency-ms-p95", type=float, default=30000.0)
    parser.add_argument("--canary-min-node-online-rate", type=float, default=0.95)
    parser.add_argument("--canary-allow-missing-latency", action="store_true")
    parser.add_argument("--require-official-testnet", action="store_true")
    parser.add_argument("--official-config", default="ezchain.yaml")
    parser.add_argument("--official-check-connectivity", action="store_true")
    parser.add_argument("--official-allow-unreachable", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    steps: List[Dict[str, Any]] = []

    if args.run_gates:
        gate_cmd = [sys.executable, "scripts/release_gate.py", "--skip-slow"]
        steps.append(run_step("release_gate", gate_cmd, cwd=root))

        sec_cmd = [sys.executable, "scripts/security_gate.py", "--config", args.config]
        steps.append(run_step("security_gate", sec_cmd, cwd=root))

        if args.with_stability:
            stability_cmd = [
                sys.executable,
                "scripts/stability_gate.py",
                "--config",
                args.config,
                "--cycles",
                "30",
                "--interval",
                "1",
                "--restart-every",
                "10",
                "--max-failures",
                "0",
                "--max-failure-rate",
                "0.0",
            ]
            if args.allow_bind_restricted_skip:
                stability_cmd.append("--allow-bind-restricted-skip")
            steps.append(run_step("stability_gate", stability_cmd, cwd=root))

    if args.run_metrics:
        metrics_cmd = [
            sys.executable,
            "scripts/metrics_probe.py",
            "--url",
            args.metrics_url,
            "--min-success-rate",
            str(args.metrics_min_success_rate),
        ]
        steps.append(run_step("metrics_probe", metrics_cmd, cwd=root))

    if args.run_canary:
        canary_monitor_cmd = [
            sys.executable,
            "scripts/canary_monitor.py",
            "--url",
            args.canary_url,
            "--duration-sec",
            str(args.canary_duration_sec),
            "--interval-sec",
            str(args.canary_interval_sec),
            "--timeout-sec",
            str(args.canary_timeout_sec),
            "--out-json",
            args.canary_out,
        ]
        steps.append(run_step("canary_monitor", canary_monitor_cmd, cwd=root))

        canary_gate_cmd = [
            sys.executable,
            "scripts/canary_gate.py",
            "--report",
            args.canary_out,
            "--max-crash-rate",
            str(args.canary_max_crash_rate),
            "--min-tx-success-rate",
            str(args.canary_min_tx_success_rate),
            "--max-sync-latency-ms-p95",
            str(args.canary_max_sync_latency_ms_p95),
            "--min-node-online-rate",
            str(args.canary_min_node_online_rate),
        ]
        if args.canary_allow_missing_latency:
            canary_gate_cmd.append("--allow-missing-latency")
        steps.append(run_step("canary_gate", canary_gate_cmd, cwd=root))

    if args.require_official_testnet:
        testnet_cmd = [
            sys.executable,
            "scripts/testnet_profile_gate.py",
            "--config",
            args.official_config,
        ]
        if args.official_check_connectivity:
            testnet_cmd.append("--check-connectivity")
        if args.official_allow_unreachable:
            testnet_cmd.append("--allow-unreachable")
        steps.append(run_step("official_testnet_gate", testnet_cmd, cwd=root))

    overall = "passed" if all(s["status"] == "passed" for s in steps) else "failed"
    if not steps:
        overall = "skipped"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(root),
        "overall_status": overall,
        "steps": steps,
    }

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(to_markdown(report), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"[release-report] wrote {out_json}")
    print(f"[release-report] wrote {out_md}")
    return 0 if overall in {"passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
