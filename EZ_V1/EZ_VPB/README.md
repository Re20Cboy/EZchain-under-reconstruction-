# EZ_V1/EZ_VPB

This directory is the staged physical home for high-stability EZ_VPB modules.

Current migrated slices:
- `values/Value.py`
- `values/AccountValueCollection.py`
- `values/AccountPickValues.py`
- `block_index/BlockIndexList.py`
- `block_index/AccountBlockIndexManager.py`
- `proofs/ProofUnit.py`
- `proofs/Proofs.py`
- `proofs/AccountProofManager.py`
- `VPBManager.py`
- `VPBPairs.py`
- `migration/VPBDataMigration.py`

The staged migration now includes the main VPB coordination layer.
Top-level `EZ_VPB/` imports remain available through compatibility shims.
