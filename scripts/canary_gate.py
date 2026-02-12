#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def evaluate_canary(
    *,
    report: Dict[str, Any],
    max_crash_rate: float,
    min_tx_success_rate: float,
    max_sync_latency_ms_p95: float,
    min_node_online_rate: float,
    allow_missing_latency: bool,
) -> List[str]:
    failures: List[str] = []

    crash_rate = report.get("crash_rate")
    if not isinstance(crash_rate, (int, float)) or float(crash_rate) > max_crash_rate:
        failures.append(f"crash_rate exceeds threshold: got={crash_rate} limit={max_crash_rate}")

    tx_success_rate = report.get("transaction_success_rate_avg")
    if not isinstance(tx_success_rate, (int, float)) or float(tx_success_rate) < min_tx_success_rate:
        failures.append(
            f"transaction_success_rate_avg below threshold: got={tx_success_rate} limit={min_tx_success_rate}"
        )

    sync_p95 = report.get("sync_latency_ms_p95")
    if sync_p95 is None and not allow_missing_latency:
        failures.append("sync_latency_ms_p95 missing")
    elif isinstance(sync_p95, (int, float)) and float(sync_p95) > max_sync_latency_ms_p95:
        failures.append(f"sync_latency_ms_p95 exceeds threshold: got={sync_p95} limit={max_sync_latency_ms_p95}")

    node_online_rate = report.get("node_online_rate_avg")
    if not isinstance(node_online_rate, (int, float)) or float(node_online_rate) < min_node_online_rate:
        failures.append(f"node_online_rate_avg below threshold: got={node_online_rate} limit={min_node_online_rate}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate canary metrics report against release thresholds")
    parser.add_argument("--report", default="dist/canary_report.json")
    parser.add_argument("--max-crash-rate", type=float, default=0.05)
    parser.add_argument("--min-tx-success-rate", type=float, default=0.95)
    parser.add_argument("--max-sync-latency-ms-p95", type=float, default=30000.0)
    parser.add_argument("--min-node-online-rate", type=float, default=0.95)
    parser.add_argument("--allow-missing-latency", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    failures = evaluate_canary(
        report=report,
        max_crash_rate=float(args.max_crash_rate),
        min_tx_success_rate=float(args.min_tx_success_rate),
        max_sync_latency_ms_p95=float(args.max_sync_latency_ms_p95),
        min_node_online_rate=float(args.min_node_online_rate),
        allow_missing_latency=bool(args.allow_missing_latency),
    )

    payload = {
        "ok": len(failures) == 0,
        "report": str(report_path),
        "thresholds": {
            "max_crash_rate": float(args.max_crash_rate),
            "min_tx_success_rate": float(args.min_tx_success_rate),
            "max_sync_latency_ms_p95": float(args.max_sync_latency_ms_p95),
            "min_node_online_rate": float(args.min_node_online_rate),
            "allow_missing_latency": bool(args.allow_missing_latency),
        },
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))

    if failures:
        print("[canary-gate] FAILED")
        return 1
    print("[canary-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
