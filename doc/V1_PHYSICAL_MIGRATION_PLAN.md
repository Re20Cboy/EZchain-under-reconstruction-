# V1 Physical Migration Plan

This document defines how V1 could eventually move under `EZ_V1/` without
breaking the current repository.

## Current Position

The repository now treats `EZ_V1/` as the logical umbrella for the frozen V1
lane, but the actual V1 source trees still remain at top level.

That is intentional. Direct imports to V1 top-level packages are still spread
across tests, compatibility code, P2P adapters, and historical scripts.

The first low-risk staged move has now been piloted for:

- `EZ_Msg`
- `EZ_Miner`
- `EZ_CheckPoint`
- `EZ_GENESIS`
- `EZ_Main_Chain`
- `EZ_Tx_Pool`
- `EZ_Units`
- `EZ_VPB_Validator`
- `EZ_Account`
- `EZ_Transaction`
- `EZ_VPB.values.Value`
- `EZ_VPB.values.AccountValueCollection`
- `EZ_VPB.values.AccountPickValues`
- `EZ_VPB.block_index.BlockIndexList`
- `EZ_VPB.block_index.AccountBlockIndexManager`
- `EZ_VPB.proofs.ProofUnit`
- `EZ_VPB.proofs.Proofs`
- `EZ_VPB.proofs.AccountProofManager`
- `EZ_VPB.VPBManager`
- `EZ_VPB.VPBPairs`
- `EZ_VPB.migration.VPBDataMigration`

Their physical implementations live under `EZ_V1/`, while top-level
compatibility shims preserve existing imports.

`EZ_VPB_Validator` required an extra compatibility pass after the physical move:

- legacy `Proofs` wrappers and `BlockIndexList` mocks are normalized before validation
- historical mock transaction fields (`receiver`, `input_values`, `output_values`) are still accepted
- placeholder merkle roots used by old comprehensive tests are only tolerated in a narrow compatibility path

That keeps the migration safe without weakening the normal hash-root validation path.

## Required Rule

Do not physically move V1 directories into `EZ_V1/` until a direct-import audit
shows the package is ready for phased migration.

Use:

```bash
python3 scripts/v1_import_audit.py
```

Optional artifacts:

```bash
python3 scripts/v1_import_audit.py --out-json dist/v1_import_audit.json --out-md dist/v1_import_audit.md
```

## Migration Phases

### Phase 0: Logical Consolidation

- add package-level exports
- add per-directory READMEs
- maintain `EZ_V1/` as the governance root
- keep source trees at top level

### Phase 1: Low-Risk Physical Candidates

Move only low-risk or near-unused directories after confirming the audit output.

Typical candidates:

- `EZ_Msg`
- `EZ_Miner`
- any package with `clear` or `low` import risk

### Phase 2: Medium-Risk Subsystems

Move packages only after compatibility shims or import rewrites are prepared.

Typical candidates:

- `EZ_CheckPoint`
- `EZ_GENESIS`
- `EZ_Main_Chain`
- `EZ_Tx_Pool`
- `EZ_Units`

### Phase 3: High-Risk Core

Move last, after broad dependency reduction and full regression.

Typical candidates:

- `EZ_Transaction`
- `EZ_VPB`

## Exit Criteria For A Package Move

Before physically moving one V1 package:

1. the audit shows the package at an acceptable risk level for its phase
2. compatibility code has been checked
3. relevant legacy tests have been identified
4. import-path shims or rewrites are ready
5. the move is done for one subsystem at a time, not the whole V1 lane at once

## What This Plan Prevents

This plan exists to avoid a repo-wide regression caused by:

- broken top-level imports
- broken historical tests
- broken P2P adapters
- broken V1 compatibility paths inside current V2 app code
