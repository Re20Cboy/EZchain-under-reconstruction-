# EZchain MVP Release Checklist

## Required checks
1. `python scripts/release_gate.py --skip-slow`
2. `python scripts/security_gate.py`
3. `python scripts/stability_smoke.py --cycles 30 --interval 1`
4. `python scripts/metrics_probe.py --url http://127.0.0.1:8787/metrics`

## Functional acceptance
1. Wallet create/import/show/balance pass.
2. Tx send history and balance updates pass.
3. Node start/status/stop pass.
4. Duplicate `client_tx_id` blocked.
5. Replay nonce blocked.
6. `/metrics` exposes tx success rate and error-code distribution.

## Security acceptance
1. API is loopback-only (`127.0.0.1`/`localhost`).
2. Oversized payload rejected (`413 payload_too_large`).
3. Audit logs exist and do not contain plaintext password/token.

## Release package
1. Version notes complete.
2. Known risks listed.
3. Rollback steps included.
4. Runbook link attached (`doc/MVP_RUNBOOK.md`).
