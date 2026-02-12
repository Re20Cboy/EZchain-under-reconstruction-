# EZchain MVP Release Checklist

## Required checks
1. `python scripts/release_gate.py --skip-slow`
2. `python scripts/security_gate.py`
3. `python scripts/stability_gate.py --cycles 30 --interval 1 --restart-every 10 --max-failures 0 --max-failure-rate 0.0`
4. `python scripts/metrics_probe.py --url http://127.0.0.1:8787/metrics`
5. `python scripts/release_report.py --run-gates --with-stability --allow-bind-restricted-skip --run-metrics`
6. `python scripts/prepare_rc.py --version v0.1.0-rc1`
7. `python scripts/rc_gate.py`
8. `python scripts/release_candidate.py --version v0.1.0-rc1 --with-stability --allow-bind-restricted-skip --target none`
9. `python scripts/canary_monitor.py --url http://127.0.0.1:8787/metrics --duration-sec 1800 --interval-sec 15 --out-json dist/canary_report.json`
10. `python scripts/canary_gate.py --report dist/canary_report.json --max-crash-rate 0.05 --min-tx-success-rate 0.95 --max-sync-latency-ms-p95 30000 --min-node-online-rate 0.95 --allow-missing-latency`

## Functional acceptance
1. Wallet create/import/show/balance pass.
2. Tx send history and balance updates pass.
3. Node start/status/stop pass.
4. Duplicate `client_tx_id` blocked.
5. Replay nonce blocked.
6. `/metrics` exposes tx success rate and error-code distribution.
7. Canary report includes:
   - crash_rate
   - transaction_success_rate_avg
   - sync_latency_ms_p95
   - node_online_rate_avg

## Security acceptance
1. API is loopback-only (`127.0.0.1`/`localhost`).
2. Oversized payload rejected (`413 payload_too_large`).
3. Audit logs exist and do not contain plaintext password/token.

## Release package
1. Version notes complete.
2. Known risks listed.
3. Rollback steps included.
4. Runbook link attached (`doc/MVP_RUNBOOK.md`).
