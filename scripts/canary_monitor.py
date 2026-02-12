#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen


def fetch_metrics(url: str, timeout_sec: float) -> Dict[str, Any]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=max(0.5, timeout_sec)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("metrics_response_not_ok")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("metrics_response_missing_data")
    return data


def summarize_samples(
    *,
    samples: List[Dict[str, Any]],
    total_probes: int,
    failed_probes: int,
) -> Dict[str, Any]:
    tx_success_rates: List[float] = []
    tx_latencies_ms: List[float] = []
    node_online_rates: List[float] = []
    error_code_totals: Dict[str, int] = {}

    for item in samples:
        transactions = item.get("transactions", {})
        success_rate = transactions.get("success_rate")
        if isinstance(success_rate, (int, float)):
            tx_success_rates.append(float(success_rate))

        latency = transactions.get("avg_confirmation_latency_ms")
        if isinstance(latency, (int, float)):
            tx_latencies_ms.append(float(latency))

        node_online = item.get("node_online_rate")
        if isinstance(node_online, (int, float)):
            node_online_rates.append(float(node_online))

        errors = item.get("error_code_distribution", {})
        if isinstance(errors, dict):
            for key, value in errors.items():
                if isinstance(value, int):
                    error_code_totals[str(key)] = error_code_totals.get(str(key), 0) + value

    probes = max(1, int(total_probes))
    crash_rate = failed_probes / probes

    def _avg(vals: List[float]) -> float | None:
        return (sum(vals) / len(vals)) if vals else None

    def _p95(vals: List[float]) -> float | None:
        if not vals:
            return None
        sorted_vals = sorted(vals)
        idx = int(round(0.95 * (len(sorted_vals) - 1)))
        return float(sorted_vals[idx])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples),
        "probes_total": probes,
        "probes_failed": int(failed_probes),
        "crash_rate": round(crash_rate, 6),
        "transaction_success_rate_avg": round(_avg(tx_success_rates), 6) if tx_success_rates else None,
        "transaction_success_rate_min": round(min(tx_success_rates), 6) if tx_success_rates else None,
        "sync_latency_ms_avg": round(_avg(tx_latencies_ms), 3) if tx_latencies_ms else None,
        "sync_latency_ms_p95": round(_p95(tx_latencies_ms), 3) if tx_latencies_ms else None,
        "node_online_rate_avg": round(_avg(node_online_rates), 6) if node_online_rates else None,
        "error_code_totals": error_code_totals,
    }


def run_sampling(
    *,
    url: str,
    duration_sec: int,
    interval_sec: float,
    timeout_sec: float,
) -> Tuple[List[Dict[str, Any]], int, int]:
    samples: List[Dict[str, Any]] = []
    probes_total = 0
    probes_failed = 0
    deadline = time.time() + max(1, int(duration_sec))

    while time.time() < deadline:
        probes_total += 1
        try:
            samples.append(fetch_metrics(url=url, timeout_sec=timeout_sec))
        except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError):
            probes_failed += 1
        time.sleep(max(0.05, float(interval_sec)))

    return samples, probes_total, probes_failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect canary metrics over a rolling window")
    parser.add_argument("--url", default="http://127.0.0.1:8787/metrics")
    parser.add_argument("--duration-sec", type=int, default=300)
    parser.add_argument("--interval-sec", type=float, default=10.0)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--out-json", default="dist/canary_report.json")
    args = parser.parse_args()

    samples, probes_total, probes_failed = run_sampling(
        url=args.url,
        duration_sec=args.duration_sec,
        interval_sec=args.interval_sec,
        timeout_sec=args.timeout_sec,
    )
    summary = summarize_samples(samples=samples, total_probes=probes_total, failed_probes=probes_failed)

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"[canary-monitor] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
