# EZchain MVP Release Checklist

## Required checks
1. `python scripts/release_gate.py --skip-slow`
   - includes `run_ezchain_tests.py --groups core transactions v2 --skip-slow`
   - includes `python scripts/app_gate.py`
   - includes `python run_ez_v2_acceptance.py`
   - includes `python scripts/security_gate.py`
2. `python run_ezchain_tests.py --groups v2-adversarial --skip-slow`
   - forged proof / forged receipt / conflicting package / withheld receipt / long-round value-preservation coverage
   - RC/nightly recommended stronger form: `python scripts/release_gate.py --skip-slow --with-v2-adversarial`
3. `python scripts/security_gate.py`
4. `python scripts/stability_gate.py --cycles 30 --interval 1 --restart-every 10 --max-failures 0 --max-failure-rate 0.0`
5. `python scripts/metrics_probe.py --url http://127.0.0.1:8787/metrics`
6. `python scripts/release_report.py --run-gates --with-stability --with-v2-adversarial --allow-bind-restricted-skip --run-metrics`
   - recommended: `--require-official-testnet --official-config configs/ezchain.official-testnet.yaml --official-check-connectivity --external-trial-record <trial-record.json>`
   - initialize trial record: `python scripts/init_external_trial.py --executor <name> --os macos --install-path source`
   - optional precheck: `python scripts/external_trial_gate.py --record <trial-record.json> --require-passed`
7. `python scripts/prepare_rc.py --version v0.1.0-rc1`
8. `python scripts/rc_gate.py`
9. `python scripts/release_candidate.py --version v0.1.0-rc1 --with-stability --with-v2-adversarial --allow-bind-restricted-skip --target none`
   - recommended: `--require-official-testnet --official-config configs/ezchain.official-testnet.yaml --official-check-connectivity --external-trial-record <trial-record.json>`
10. `python3 scripts/v2_readiness.py`
   - used to decide whether V2 can be treated as the default project path instead of only the default local/dev path
   - `release_candidate.py` now runs this automatically and carries the result into the RC manifest
11. `python scripts/canary_monitor.py --url http://127.0.0.1:8787/metrics --duration-sec 1800 --interval-sec 15 --out-json dist/canary_report.json`
12. `python scripts/canary_gate.py --report dist/canary_report.json --max-crash-rate 0.05 --min-tx-success-rate 0.95 --max-sync-latency-ms-p95 30000 --min-node-online-rate 0.95 --allow-missing-latency`

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
5. Official testnet external trial record attached (copy from `doc/OFFICIAL_TESTNET_TRIAL_TEMPLATE.json` and fill with a real rehearsal result).
