from __future__ import annotations

from scripts.canary_gate import evaluate_canary
from scripts.canary_monitor import summarize_samples


def test_summarize_samples_builds_expected_aggregates():
    samples = [
        {
            "transactions": {"success_rate": 0.99, "avg_confirmation_latency_ms": 1200.0},
            "node_online_rate": 1.0,
            "error_code_distribution": {"duplicate_transaction": 1},
        },
        {
            "transactions": {"success_rate": 0.97, "avg_confirmation_latency_ms": 1800.0},
            "node_online_rate": 0.98,
            "error_code_distribution": {"replay_detected": 2},
        },
    ]

    summary = summarize_samples(samples=samples, total_probes=5, failed_probes=1)
    assert summary["sample_count"] == 2
    assert summary["probes_total"] == 5
    assert summary["probes_failed"] == 1
    assert summary["crash_rate"] == 0.2
    assert summary["transaction_success_rate_avg"] == 0.98
    assert summary["sync_latency_ms_p95"] == 1800.0
    assert summary["node_online_rate_avg"] == 0.99
    assert summary["error_code_totals"]["duplicate_transaction"] == 1
    assert summary["error_code_totals"]["replay_detected"] == 2


def test_evaluate_canary_passes_on_healthy_report():
    report = {
        "crash_rate": 0.01,
        "transaction_success_rate_avg": 0.98,
        "sync_latency_ms_p95": 5000.0,
        "node_online_rate_avg": 0.99,
    }
    failures = evaluate_canary(
        report=report,
        max_crash_rate=0.05,
        min_tx_success_rate=0.95,
        max_sync_latency_ms_p95=30000.0,
        min_node_online_rate=0.95,
        allow_missing_latency=False,
    )
    assert failures == []


def test_evaluate_canary_detects_threshold_violations():
    report = {
        "crash_rate": 0.2,
        "transaction_success_rate_avg": 0.8,
        "sync_latency_ms_p95": 60000.0,
        "node_online_rate_avg": 0.5,
    }
    failures = evaluate_canary(
        report=report,
        max_crash_rate=0.05,
        min_tx_success_rate=0.95,
        max_sync_latency_ms_p95=30000.0,
        min_node_online_rate=0.95,
        allow_missing_latency=False,
    )
    assert len(failures) == 4


def test_evaluate_canary_allows_missing_latency_when_opted_in():
    report = {
        "crash_rate": 0.0,
        "transaction_success_rate_avg": 0.99,
        "sync_latency_ms_p95": None,
        "node_online_rate_avg": 1.0,
    }
    failures = evaluate_canary(
        report=report,
        max_crash_rate=0.05,
        min_tx_success_rate=0.95,
        max_sync_latency_ms_p95=30000.0,
        min_node_online_rate=0.95,
        allow_missing_latency=True,
    )
    assert failures == []
