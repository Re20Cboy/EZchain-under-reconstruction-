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

## Documentation

- Docs hub: `doc/README.md`
- Project structure: `doc/PROJECT_STRUCTURE.md`
- User quickstart: `doc/USER_QUICKSTART.md`
- Developer testing: `doc/DEV_TESTING.md`
- Release checklist: `doc/RELEASE_CHECKLIST.md`
- Official testnet trial runbook: `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

## Status

- V2 is the default development and validation path
- V1 remains for compatibility and historical reference
- This repository is not yet a finished public-network V2 node stack
