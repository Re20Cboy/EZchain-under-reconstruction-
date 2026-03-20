# EZchain Project Structure

This document explains the current repository layout without changing import paths or moving source directories.

The project is currently organized as a **dual-lane repository**:

- `EZ_V2` is the active implementation lane for local development and acceptance.
- `V1` modules remain in place as a legacy/reference lane while the transition is completed.

## 1. Top-Level Layout

### Active V2 Path

- `EZ_V2/`
  - V2 protocol core, wallet storage, local runtime, localnet, validator, control plane
- `EZ_App/`
  - CLI, local service API, runtime bridge, node lifecycle manager
- `configs/`
  - runnable config templates
- `scripts/`
  - quickstart, gates, release utilities, backup/restore tools
- `EZ_Test/`
  - V1 + V2 tests; V2 acceptance and runtime tests live here
- `doc/`
  - current user/developer/release documentation
- `EZchain-V2-design/`
  - V2 protocol design, roadmap, transition/freeze documents

### Legacy / Frozen V1 Path

- `EZ_V1/`
  - logical umbrella and governance root for the frozen V1 lane
- `EZ_VPB/`
- `EZ_VPB_Validator/`
- `EZ_Tx_Pool/`
- `EZ_Main_Chain/`
- `EZ_Account/`
- `EZ_Transaction/`
- `EZ_CheckPoint/`
- `EZ_GENESIS/`
- `EZ_Miner/`
- `EZ_Msg/`
- `EZ_Units/`

These top-level names remain in the repository for:

- historical comparison
- compatibility reference
- legacy tests
- phased cleanup before any future physical consolidation under `EZ_V1/`

Most frozen V1 runtime implementations now physically live under `EZ_V1/`.
Several top-level V1 directories are increasingly acting as compatibility shim
surfaces plus lightweight signposts for archived material.

They are **not** the preferred path for new features.

For the functional grouping inside the legacy lane, see:

- `doc/V1_LEGACY_STRUCTURE.md`
- `doc/V1_PHYSICAL_MIGRATION_PLAN.md`

For historical VPB/account artifacts that were moved out of top-level runtime
trees, see:

- `EZ_V1/EZ_VPB/legacy_docs/`
- `EZ_V1/EZ_VPB/legacy_tests/`
- `EZ_V1/EZ_Account/legacy_tests_backup/`
- `EZ_V1/EZ_GENESIS/legacy_docs/`
- `EZ_V1/EZ_Transaction/legacy_docs/`

## 2. Current Runtime Entry Points

### Recommended V2 Local Flow

- CLI entry: `ezchain_cli.py`
- App runtime: `EZ_App/runtime.py`
- Local service: `EZ_App/service.py`
- Local node manager: `EZ_App/node_manager.py`
- V2 app client boundary: `EZ_V2/app_client.py`
- V2 local runtime/localnet:
  - `EZ_V2/runtime_v2.py`
  - `EZ_V2/localnet.py`
  - `run_ez_v2_localnet.py`

### Recommended Config

- `configs/ezchain.v2-localnet.yaml`

### Recommended Acceptance Gate

- `run_ez_v2_acceptance.py`

## 3. V2 Internal Structure

### Protocol Core

- `EZ_V2/types.py`
- `EZ_V2/encoding.py`
- `EZ_V2/crypto.py`
- `EZ_V2/chain.py`
- `EZ_V2/validator.py`
- `EZ_V2/smt.py`
- `EZ_V2/values.py`

### Wallet / Persistence

- `EZ_V2/wallet.py`
- `EZ_V2/storage.py`
- `EZ_V2/serde.py`

### Runtime / Node / Control Plane

- `EZ_V2/runtime_v2.py`
- `EZ_V2/localnet.py`
- `EZ_V2/consensus_store.py`
- `EZ_V2/transport.py`
- `EZ_V2/control.py`
- `EZ_V2/app_client.py`

## 4. Application Layer Structure

- `EZ_App/cli.py`
  - command-line entry logic
- `EZ_App/config.py`
  - config parsing and defaults
- `EZ_App/runtime.py`
  - wallet-facing transaction engine
- `EZ_App/service.py`
  - local HTTP API, auth, audit, metrics, route handling
- `EZ_App/ui_panel.py`
  - embedded local Web console HTML/JS, separated from service backend logic
- `EZ_App/node_manager.py`
  - local process lifecycle for node/localnet modes
- `EZ_App/wallet_store.py`
  - encrypted wallet file handling

## 5. Testing Layout

### V2 Test Set

- `EZ_Test/test_ez_v2_protocol.py`
- `EZ_Test/test_ez_v2_wallet_storage.py`
- `EZ_Test/test_ez_v2_runtime.py`
- `EZ_Test/test_ez_v2_localnet.py`
- `EZ_Test/test_ez_v2_app_runtime.py`
- `EZ_Test/test_ez_v2_node_manager.py`
- `EZ_Test/test_ez_v2_acceptance.py`

### Unified Test Entry

- `run_ezchain_tests.py`
  - includes `v2` test group

### Release Gate

- `scripts/release_gate.py`
  - now includes the V2 acceptance path by default

## 6. Structure Rules Going Forward

To keep imports and runtime behavior stable, follow these rules:

1. Do not move existing V1 directories during the freeze stage.
2. Put new protocol work into `EZ_V2/`.
3. Put new user-facing local runtime/service work into `EZ_App/`.
4. Put migration/transition rules into `EZchain-V2-design/`.
5. Keep `doc/` as the source of current operational documentation.
6. Treat V1 protocol modules as legacy unless a blocking compatibility fix is required.
7. Clean up V1 logically through package exports and structure docs before any physical move is considered.

## 7. What Is Explicitly Not Being Done

To avoid breaking imports and historical tests, this repository is **not** currently doing:

- large-scale directory renames
- in-place relocation of V1 modules
- replacing all old scripts at once
- deleting V1 source trees before V2 becomes the stable default

The structure is being cleaned up logically first, then operationally.
