# EZchain

Chinese README: `README.zh-CN.md`

EZchain is a research-to-product codebase for a scale-out blockchain design.  
This repository currently contains two lanes:

- `EZ_V2`: the default implementation and validation lane
- `V1` modules: frozen legacy/reference modules kept for comparison and compatibility

The repository has now crossed the default-path transition gate: **V2 is the default project path**.

## Current Status

- V2 local runtime, wallet flow, local service API, local acceptance gate, adversarial gate, and readiness gate are runnable
- V1 remains in the tree as a legacy lane and is being frozen instead of deleted immediately
- Default local config template: `configs/ezchain.v2-localnet.yaml`
- Recommended acceptance entry: `python3 run_ez_v2_acceptance.py`
- Default official-testnet profile template: `configs/ezchain.official-testnet.yaml`
- Project default-path readiness entry: `python3 scripts/v2_readiness.py`

For the migration rule itself, see:
- `EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`

## Recommended Quick Start

Use the V2 local config:

```bash
cp configs/ezchain.v2-localnet.yaml ezchain.yaml
```

Create wallet, mint local test value, and send a transaction:

```bash
python3 ezchain_cli.py --config ezchain.yaml wallet create --password your_password --name default
python3 ezchain_cli.py --config ezchain.yaml tx faucet --amount 1000 --password your_password
python3 ezchain_cli.py --config ezchain.yaml wallet balance --password your_password
python3 ezchain_cli.py --config ezchain.yaml tx send --recipient 0xabc123 --amount 100 --password your_password --client-tx-id cid-001
python3 ezchain_cli.py --config ezchain.yaml tx receipts --password your_password
```

Start the local API:

```bash
python3 ezchain_cli.py --config ezchain.yaml serve
```

Show the local API token:

```bash
python3 ezchain_cli.py --config ezchain.yaml auth show-token
```

One-command V2 service demo:

```bash
./scripts/run_v2_service_quickstart.sh
```

## Repository Map

### Active implementation

- `EZ_V2/`: V2 protocol core, wallet storage, runtime, localnet, validator, control plane
- `EZ_App/`: CLI, local HTTP service, runtime bridge, node lifecycle manager
- `configs/`: runnable config templates
- `scripts/`: release gates, quickstarts, operations utilities
- `EZ_Test/`: tests, including V2 acceptance and runtime coverage
- `doc/`: current user, developer, release, and operations docs
- `EZchain-V2-design/`: V2 protocol design, roadmap, transition documents

### Legacy / frozen path

- `EZ_V1/`
- `EZ_VPB/`
- `EZ_VPB_Validator/`
- `EZ_Tx_Pool/`
- `EZ_Main_Chain/`
- `EZ_Account/`
- `EZ_Transaction/`

These top-level V1 directories now primarily act as:

- compatibility import surfaces
- lightweight README signposts
- pointers toward archived legacy material now grouped under `EZ_V1/`

New protocol work should go to `EZ_V2/`.

For a cleaner structural view, see:
- `doc/PROJECT_STRUCTURE.md`
- `doc/V1_LEGACY_STRUCTURE.md`
- `doc/V1_PHYSICAL_MIGRATION_PLAN.md`

## Main Entry Points

- CLI: `ezchain_cli.py`
- App runtime: `EZ_App/runtime.py`
- Local service: `EZ_App/service.py`
- Node lifecycle manager: `EZ_App/node_manager.py`
- V2 local runtime/localnet:
  - `EZ_V2/runtime_v2.py`
  - `EZ_V2/localnet.py`
  - `run_ez_v2_localnet.py`
- V2 acceptance: `run_ez_v2_acceptance.py`

## Testing And Gates

List unified test groups:

```bash
python3 run_ezchain_tests.py --list
```

Run the current recommended local regression set:

```bash
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ez_v2_acceptance.py
```

Run the release gate:

```bash
python3 scripts/release_gate.py --skip-slow
python3 scripts/release_gate.py --skip-slow --with-stability --with-v2-adversarial
```

Initialize an official-testnet trial record before external rehearsal:

```bash
python3 scripts/init_external_trial.py --executor your_name --os macos --install-path source
python3 scripts/external_trial_gate.py --record doc/trials/official-testnet-YYYYMMDD-01.json --require-passed
```

Evaluate whether V2 is ready to remain the default path for the current RC:

```bash
python3 scripts/release_report.py --run-gates --with-stability --with-v2-adversarial --require-official-testnet --official-config configs/ezchain.official-testnet.yaml --official-check-connectivity --official-allow-unreachable --external-trial-record doc/trials/official-testnet-YYYYMMDD-01.json
python3 scripts/v2_readiness.py
```

## Documentation

- Docs hub: `doc/README.md`
- Project structure: `doc/PROJECT_STRUCTURE.md`
- V2 quickstart: `doc/EZchain-V2-quickstart.md`
- Official testnet trial runbook: `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`
- Developer testing: `doc/DEV_TESTING.md`
- Release checklist: `doc/RELEASE_CHECKLIST.md`
- Runbook: `doc/MVP_RUNBOOK.md`
- V1 freeze / V2 transition: `EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`
- V2 roadmap: `EZchain-V2-design/EZchain-V2-implementation-roadmap.md`

## Research Context

- Published paper (renamed as VWchain): https://www.sciencedirect.com/science/article/abs/pii/S1383762126000512
- Original whitepaper: https://arxiv.org/abs/2312.00281v1
- Prototype simulator: https://github.com/Re20Cboy/Ezchain-py

## Notes

- This repository is not yet a finished public-network V2 node stack.
- V2 is now the default project path for development, validation, RC evaluation, and local demonstrations.
- A real reachable official-testnet environment is still recommended before treating a candidate as operationally ready without `--official-allow-unreachable`.
- The repository is being cleaned up logically before any large-scale source deletion is attempted.
