#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def run_step(name: str, cmd: List[str], cwd: Path, dry_run: bool) -> Dict[str, Any]:
    if dry_run:
        return {"name": name, "command": " ".join(cmd), "status": "planned", "returncode": 0}

    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return {
        "name": name,
        "command": " ".join(cmd),
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate EZchain release candidate")
    parser.add_argument("--version", required=True, help="e.g. v0.1.0-rc1")
    parser.add_argument("--target", choices=["none", "macos", "windows", "both"], default="none")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--with-stability", action="store_true")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    parser.add_argument("--require-official-testnet", action="store_true")
    parser.add_argument("--official-config", default="ezchain.yaml")
    parser.add_argument("--official-check-connectivity", action="store_true")
    parser.add_argument("--official-allow-unreachable", action="store_true")
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
    parser.add_argument("--manifest-out", default="dist/release_candidate_manifest.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    steps: List[Dict[str, Any]] = []

    report_cmd = [
        sys.executable,
        "scripts/release_report.py",
        "--run-gates",
        "--out-json",
        "dist/release_report.json",
        "--out-md",
        "dist/release_report.md",
    ]
    if args.with_stability:
        report_cmd.append("--with-stability")
    if args.allow_bind_restricted_skip:
        report_cmd.append("--allow-bind-restricted-skip")
    if args.run_metrics:
        report_cmd.extend(["--run-metrics", "--metrics-url", args.metrics_url, "--metrics-min-success-rate", str(args.metrics_min_success_rate)])
    if args.run_canary:
        report_cmd.extend(
            [
                "--run-canary",
                "--canary-url",
                args.canary_url,
                "--canary-duration-sec",
                str(args.canary_duration_sec),
                "--canary-interval-sec",
                str(args.canary_interval_sec),
                "--canary-timeout-sec",
                str(args.canary_timeout_sec),
                "--canary-out",
                args.canary_out,
                "--canary-max-crash-rate",
                str(args.canary_max_crash_rate),
                "--canary-min-tx-success-rate",
                str(args.canary_min_tx_success_rate),
                "--canary-max-sync-latency-ms-p95",
                str(args.canary_max_sync_latency_ms_p95),
                "--canary-min-node-online-rate",
                str(args.canary_min_node_online_rate),
            ]
        )
        if args.canary_allow_missing_latency:
            report_cmd.append("--canary-allow-missing-latency")
    if args.require_official_testnet:
        report_cmd.extend(["--require-official-testnet", "--official-config", args.official_config])
        if args.official_check_connectivity:
            report_cmd.append("--official-check-connectivity")
        if args.official_allow_unreachable:
            report_cmd.append("--official-allow-unreachable")
    steps.append(run_step("release_report", report_cmd, cwd=root, dry_run=args.dry_run))

    prepare_cmd = [sys.executable, "scripts/prepare_rc.py", "--version", args.version]
    steps.append(run_step("prepare_rc", prepare_cmd, cwd=root, dry_run=args.dry_run))

    rc_gate_cmd = [sys.executable, "scripts/rc_gate.py"]
    steps.append(run_step("rc_gate", rc_gate_cmd, cwd=root, dry_run=args.dry_run))

    if args.target in {"macos", "windows"}:
        steps.append(
            run_step(
                "package_app",
                [sys.executable, "scripts/package_app.py", "--target", args.target, "--clean"],
                cwd=root,
                dry_run=args.dry_run,
            )
        )
    elif args.target == "both":
        steps.append(
            run_step(
                "package_app_macos",
                [sys.executable, "scripts/package_app.py", "--target", "macos", "--clean"],
                cwd=root,
                dry_run=args.dry_run,
            )
        )
        steps.append(
            run_step(
                "package_app_windows",
                [sys.executable, "scripts/package_app.py", "--target", "windows", "--clean"],
                cwd=root,
                dry_run=args.dry_run,
            )
        )

    failed = any(step["status"] == "failed" for step in steps)
    status = "failed" if failed else ("planned" if args.dry_run else "passed")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": args.version,
        "status": status,
        "dry_run": args.dry_run,
        "steps": steps,
    }

    out = root / args.manifest_out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"[release-candidate] wrote {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
