# EZchain

Chinese README: `README.zh-CN.md`

EZchain is a research-to-product blockchain codebase.  
Current default path: **V2**.

This repository now has a simple split:

- `EZ_V2/`: protocol core, runtime, localnet, wallet/storage
- `EZ_App/`: CLI, local service API, node lifecycle
- `EZ_V1/`: frozen V1 implementation and legacy archive

Top-level V1 directories such as `EZ_VPB/`, `EZ_Account/`, and `EZ_Transaction/`
still exist mainly as compatibility import surfaces during the transition.

## Quick Start

Use the default local V2 config:

```bash
cp configs/ezchain.v2-localnet.yaml ezchain.yaml
```

Create a wallet, mint local test value, and send a transaction:

```bash
python3 ezchain_cli.py --config ezchain.yaml wallet create --password your_password --name default
python3 ezchain_cli.py --config ezchain.yaml tx faucet --amount 1000 --password your_password
python3 ezchain_cli.py --config ezchain.yaml tx send --recipient 0xabc123 --amount 100 --password your_password --client-tx-id cid-001
```

Start the local service:

```bash
python3 ezchain_cli.py --config ezchain.yaml serve
```

Optional: start the smallest real TCP-backed V2 node mode:

```bash
python3 ezchain_cli.py --config ezchain.yaml node start --mode v2-consensus
python3 ezchain_cli.py --config ezchain.yaml node status
python3 ezchain_cli.py --config ezchain.yaml node stop
```

This mode starts a single lightweight V2 consensus daemon bound to
`network.bootstrap_nodes[0]`, or `127.0.0.1:<start_port>` when no bootstrap
endpoint is configured. It is an optional developer/node path; the default
wallet and service flow still uses the local V2 runtime.

There is also a minimal `v2-account` developer mode for bringing up an
account-role daemon against an existing V2 consensus endpoint. It is currently
intended as a role-separation skeleton, not yet the default wallet flow.
`node status` now reports the mode family, roles, connected consensus endpoint,
account address, a few basic sync counters, and whether the last account sync
round succeeded for that developer path. If one of these V2 node modes exits
immediately during startup, the data directory now keeps a matching
`*_startup.log` file to show the early error.
For `v2-account`, the status view also keeps the recovery side of the story:
how many sync failures are currently in a row, the worst streak seen so far,
when the last successful sync happened, and how many times the daemon has
recovered after losing the consensus endpoint.
To make that easier to read at a glance, the account status now also derives
`sync_health` and `sync_health_reason`, for example `healthy`, `degraded`, or
`recovered`.
If a local wallet already exists before `v2-account` starts, the account daemon
now reuses that wallet's V2 address instead of generating a separate one.
When that wallet file is present, the account daemon also reuses the matching
`wallet_state_v2/<address>/wallet_v2.db` path so later remote-path work can
build on the same persisted V2 wallet state.
When `v2-account` is the active mode, you can also inspect the dedicated
account-node view directly:

```bash
python3 ezchain_cli.py --config ezchain.yaml node account-status
```

For `official-testnet + v2`, the current state is more limited and more honest:

- read-only queries such as `wallet balance`, `wallet checkpoints`,
  `tx pending`, `tx receipts`, and `tx history` can read from the shared
  account wallet DB and local history state
- `tx send` can now use the remote account path when you explicitly pass the
  recipient account-node endpoint, or when you saved that endpoint locally in advance
- `tx faucet` is still not wired for the remote path

Example:

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts set \
  --address 0xabc123 \
  --endpoint 192.168.1.20:19500

python3 ezchain_cli.py --config ezchain.yaml tx send \
  --recipient 0xabc123 \
  --amount 100 \
  --password your_password \
  --client-tx-id cid-remote-001
```

If the other side already has a running `v2-account`, they can export a contact
card instead of sending the address and endpoint by hand:

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts export-self --out bob-contact.json
python3 ezchain_cli.py --config ezchain.yaml contacts import-card --file bob-contact.json
```

If they already expose the local service, you can also fetch the card directly
from the service URL and import it in one step:

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts fetch-card \
  --url http://192.168.1.20:8787 \
  --out bob-contact.json \
  --import-to-contacts
```

To inspect which recipient nodes are already saved locally, the service now
also exposes two read-only endpoints:

- `GET /contacts`
- `GET /contacts/<address>`

The address-book path is now a full small loop:

- manual add: `contacts set`
- show one: `contacts show`
- list all: `contacts list` or `GET /contacts`
- export self: `contacts export-self`
- import from file: `contacts import-card`
- fetch from service: `contacts fetch-card`
- service-side write/import/fetch/delete: `POST /contacts`, `POST /contacts/import-card`, `POST /contacts/fetch-card`, `DELETE /contacts/<address>`

## Main Entry Points

- CLI: `ezchain_cli.py`
- Local service: `EZ_App/service.py`
- Local V2 runtime: `EZ_V2/runtime_v2.py`
- Local V2 network: `run_ez_v2_localnet.py`
- Lightweight V2 TCP consensus node: `run_ez_v2_tcp_consensus.py`
- Acceptance gate: `run_ez_v2_acceptance.py`

## Verify

Recommended local checks:

```bash
python3 run_ezchain_tests.py --groups v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
python3 run_ez_v2_acceptance.py
```

Release-level gate:

```bash
python3 scripts/release_gate.py --skip-slow --with-stability --with-v2-adversarial
```

Readiness-level reporting:

```bash
python3 scripts/release_report.py --run-gates --with-stability --with-consensus --with-v2-adversarial --allow-bind-restricted-skip
python3 scripts/v2_readiness.py
```

The report now separates:

- layered consensus validation passed
- whether formal TCP consensus evidence was actually executed in the current environment

## Documentation

- Docs hub: `doc/README.md`
- Project structure: `doc/PROJECT_STRUCTURE.md`
- User quickstart: `doc/USER_QUICKSTART.md`
- Developer testing: `doc/DEV_TESTING.md`
- Release checklist: `doc/RELEASE_CHECKLIST.md`
- Official testnet trial runbook: `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

## Status

- V2 is the default development and validation path
- Whether V2 is ready for default formal delivery is still gated by readiness
  and final confirmation on a reachable official testnet
- `consensus_gate` passing now means the layered consensus suites passed; it does
  not by itself mean TCP multi-node evidence was formed
- `release_report` and `v2_readiness` now expose the TCP evidence side
  explicitly, including bind-restricted local environments where TCP suites were
  not executed
- V1 remains for compatibility and historical reference
- This repository is not yet a finished public-network V2 node stack
