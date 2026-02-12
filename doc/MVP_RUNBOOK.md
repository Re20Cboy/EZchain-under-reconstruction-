# EZchain MVP Runbook

## 1. Scope
This runbook covers EZchain MVP operations on the hosted public testnet topology:
- 3 consensus nodes
- 1 bootstrap node
- local user wallet service (CLI/API)

## 2. Preflight
1. Check current release candidate and changelog.
2. Snapshot runtime state before any upgrade:
   - `python scripts/ops_backup.py --config ezchain.yaml --out-dir backups --label pre-rc`
3. Run release gate:
   - `python scripts/release_gate.py --skip-slow`
   - `python scripts/release_gate.py --skip-slow --with-stability`
4. Verify security gate:
   - `python scripts/security_gate.py`

## 3. Service Start
1. Start local API:
   - `python ezchain_cli.py serve`
2. Health check:
   - `curl http://127.0.0.1:8787/health`
   - `curl http://127.0.0.1:8787/metrics`
3. Check node status:
   - `python ezchain_cli.py node status`

## 4. Incident Handling
### API unavailable
1. Check process:
   - `python ezchain_cli.py node status`
2. Restart:
   - `python ezchain_cli.py node stop`
   - `python ezchain_cli.py node start --consensus 1 --accounts 1 --start-port 19500`
3. Verify audit logs:
   - `.ezchain/logs/service_audit.log`

### High tx failure rate
1. Inspect API error codes in logs.
2. Check duplicate and replay rejects:
   - error code `duplicate_transaction`
   - error code `replay_detected`
3. If failures are client-side nonce/idempotency reuse, regenerate `X-EZ-Nonce` and `client_tx_id`.

## 5. Rollback
1. Stop running node/service.
2. Restore previous tagged release.
3. Restore backup snapshot:
   - `python scripts/ops_restore.py --backup-dir backups/<snapshot-dir> --config ezchain.yaml --force`
4. Re-run health checks and one send/receive smoke transaction.

## 6. Backup
- Backup directories:
  - `.ezchain/wallet.json`
  - `.ezchain/tx_history.json`
  - `.ezchain/wallet_state/`
  - `.ezchain/logs/`
- Frequency:
  - before release
  - after 72h post-release observation window

## 7. Post-release 72h Checks
Every 4 hours:
1. Node online status
2. Transaction success ratio
3. Median confirmation delay
4. Top 3 error codes
5. Run `python scripts/metrics_probe.py --url http://127.0.0.1:8787/metrics`

## 8. Canary (Week 6 Release)
1. Start canary sampling for release candidate:
   - `python scripts/canary_monitor.py --url http://127.0.0.1:8787/metrics --duration-sec 1800 --interval-sec 15 --out-json dist/canary_report.json`
2. Gate release by canary thresholds:
   - `python scripts/canary_gate.py --report dist/canary_report.json --max-crash-rate 0.05 --min-tx-success-rate 0.95 --max-sync-latency-ms-p95 30000 --min-node-online-rate 0.95 --allow-missing-latency`
3. If gate fails:
   - Pause rollout.
   - Review `error_code_totals` and audit logs.
   - Rollback to previous snapshot with `ops_restore.py`.
4. If gate passes:
   - Proceed to broader beta rollout.
