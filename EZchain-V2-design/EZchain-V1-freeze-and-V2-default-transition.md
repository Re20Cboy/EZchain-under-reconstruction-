# EZchain V1 Freeze And V2 Default Transition

## Purpose

This document fixes the project-level rule for the next migration stage:

- `EZ_V2` becomes the default path for local development, local demos, and acceptance validation.
- `V1` remains in the repository as a legacy compatibility lane and reference baseline.
- `V1` is frozen before any large-scale deletion is attempted.

This is a migration control document, not a protocol design document.

## What "Freeze V1" Means

Freezing `V1` does **not** mean deleting it immediately.

It means:

1. No new product features are added to V1 protocol modules.
2. New local demos, quickstarts, and acceptance checks default to V2.
3. V1 remains available only for:
   - historical reference
   - compatibility comparison
   - minimal blocking bug fixes

## Frozen V1 Modules

The following V1 modules are now treated as legacy and should not receive new protocol work:

- `EZ_VPB`
- `EZ_VPB_Validator`
- `EZ_Tx_Pool`
- `EZ_Main_Chain`
- `EZ_Transaction` paths centered on `SubmitTxInfo`
- `Bloom`, `ProofUnit`, `BlockIndexList` based validation flows

## Allowed Changes In V1

The following V1 changes are still allowed:

- minimal bug fixes needed to keep old tests readable
- developer notes or comments
- migration adapters that help compare V1 and V2 behavior

The following are not allowed:

- adding new transaction semantics to V1
- extending V1 wallet state for new product features
- adding new validation logic to `VPBValidator`
- making V2 depend on V1 runtime code

## V2 Default Path

For local development and demonstrations, the recommended default is now:

- config template: `configs/ezchain.v2-localnet.yaml`
- quickstart doc: `doc/EZchain-V2-quickstart.md`
- quickstart script: `scripts/run_v2_service_quickstart.sh`
- acceptance gate: `run_ez_v2_acceptance.py`

This means the preferred local usage flow is:

1. use V2 config
2. run V2 CLI or V2 local service
3. validate with V2 acceptance gate

## What Does Not Change Yet

The following are intentionally **not** done in this step:

- deleting V1 source files
- changing every code default from `v1` to `v2`
- rewriting old P2P/V1 distributed node scripts in place
- removing V1 test files

These are deferred until V2 remains stable as the default local path.

## Recommended Immediate Workflow

For all new work:

1. implement in `EZ_V2`
2. expose through `EZ_App` only via V2-aware runtime/client boundaries
3. validate with:
   - V2 unit/integration tests
   - `run_ez_v2_acceptance.py`
4. avoid touching V1 unless a compatibility bug blocks comparison

## Exit Criteria For Actual V1 Retirement

V1 protocol deletion should only begin when all of the following are true:

1. V2 covers all core local transaction flows.
2. V2 acceptance gate is stable over repeated runs.
3. CLI and service documentation default to V2.
4. No active development feature depends on V1 protocol objects.
5. V1 is no longer needed as a debugging baseline for V2 behavior.

Until then, V1 stays in the tree as a frozen legacy lane.
