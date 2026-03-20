# V1 Legacy Structure

This document gives the frozen V1 lane a readable architectural map without
moving the historical source directories.

## Summary

The V1 code is still import-path sensitive and widely referenced by:

- legacy tests in `EZ_Test/`
- P2P adapters in `modules/ez_p2p/`
- compatibility code in `EZ_App/runtime.py`
- research and comparison flows

Because of that, the repository should treat V1 cleanup as **logical
consolidation**, not physical relocation.

`EZ_V1/` now exists as the logical umbrella for this lane, but the actual V1
source trees intentionally remain at top level until the import graph is made
safe for a phased move.

For the phased physical move strategy, see:

- `doc/V1_PHYSICAL_MIGRATION_PLAN.md`

## V1 Functional Groups

### Ledger And State

- `EZ_Main_Chain/`
  - block and blockchain objects
- `EZ_CheckPoint/`
  - checkpoint records, storage, checkpoint manager
- `EZ_GENESIS/`
  - genesis block and genesis account bootstrapping

### Account And Transaction Flow

- `EZ_Account/`
  - account object and account-side transaction orchestration
- `EZ_Transaction/`
  - single transaction, batch transaction, submission envelope, creation helpers
- `EZ_Tx_Pool/`
  - transaction pool, validation, packaging helpers
- `EZ_Miner/`
  - mining-side packaging helper

### Value / Proof / Verification

- `EZ_VPB/`
  - value model, proof units, block-index data, VPB manager
- `EZ_VPB_Validator/`
  - staged validators, types, slice generation, proof checks

### Shared Units

- `EZ_Units/`
  - bloom filter, Merkle tree, Merkle proof, utilities
- `EZ_Tool_Box/`
  - hashing and signature helpers used by many V1 modules
- `EZ_Msg/`
  - legacy message placeholder / historical stub

## Directory Hygiene

Several V1 source directories still contain a mix of live code and historical
material. Treat them with these boundaries:

- `EZ_Account/test/`
  - maintained V1 account test tree
- `EZ_Account/backup_test_files/`
  - top-level pointer only; archived exploratory tests now live in `EZ_V1/EZ_Account/legacy_tests_backup/`
- `EZ_V1/EZ_GENESIS/legacy_docs/`
  - archived genesis design material
- `EZ_V1/EZ_Transaction/legacy_docs/`
  - archived transaction design material
- `EZ_VPB/test/`
  - top-level pointer only; archived VPB reference tests now live in `EZ_V1/EZ_VPB/legacy_tests/`
- `EZ_VPB/migration/`
  - migration helper retained for legacy use
- `EZ_V1/EZ_VPB/legacy_docs/`
  - archived VPB design notes, proof notes, value notes, and demo material
- `EZ_VPB_Validator/Test/`
  - validator-focused legacy tests

The cleanup goal is to keep runtime compatibility visible while moving obvious
historical material out of the top-level execution trees.

## Practical Import Boundaries

For readability, treat the following as the package-level entry points of the
legacy lane:

- `EZ_Account`
- `EZ_CheckPoint`
- `EZ_Transaction`
- `EZ_Tx_Pool`
- `EZ_Main_Chain`
- `EZ_VPB`
- `EZ_VPB_Validator`
- `EZ_Miner`

Where package exports now exist, prefer package-level imports for new legacy
maintenance work. Do not rewrite existing historical imports unless you are
already changing the touched code for another reason.

## What Not To Do

To avoid regressions in frozen V1 code, do not:

- move V1 directories under a new parent folder
- rename V1 directories
- rewrite the whole V1 import graph
- merge V1 and V2 protocol modules into one namespace

## Recommended Ongoing Rule

When V1 needs maintenance:

1. Keep the existing directory names.
2. Add package-level exports or docs before considering any deeper move.
3. Treat V1 as compatibility/reference architecture, not as the main extension path.
