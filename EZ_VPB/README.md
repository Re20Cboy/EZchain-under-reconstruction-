# EZ_VPB

Legacy V1 Value-Proof-BlockIndex compatibility surface.

The physical V1 VPB implementation now lives under:

- `EZ_V1/EZ_VPB/`

This top-level package remains so existing imports such as:

- `from EZ_VPB.VPBManager import VPBManager`
- `from EZ_VPB.values.Value import Value`

continue to work during phased cleanup.

## Live code

- `values/`
  - compatibility shims for value objects and account-side value collections
- `proofs/`
  - compatibility shims for proof units and proof managers
- `block_index/`
  - compatibility shims for block-index helpers
- `VPBManager.py`
  - compatibility shim for the top-level VPB manager
- `VPBPairs.py`
  - compatibility shim for VPB pair structures and storage helpers

## Historical material

Historical VPB notes and archived tests have been moved under:

- `EZ_V1/EZ_VPB/legacy_docs/`
- `EZ_V1/EZ_VPB/legacy_tests/`

The top-level `EZ_VPB/` tree is now intended to stay visually focused on:

- compatibility shims
- legacy runtime-facing code entry points
- the remaining `migration/` shim

This directory should be treated as compatibility architecture rather than a
target for new feature growth.
