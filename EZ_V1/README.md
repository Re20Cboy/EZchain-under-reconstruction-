# EZ_V1

This directory is the logical umbrella for the frozen V1 lane.

## Why it exists

The repository still keeps the original V1 source trees at top level because
their import paths are referenced broadly across:

- legacy tests
- P2P adapters
- compatibility code
- historical scripts

Moving all V1 directories under `EZ_V1/` in one step would currently be a
high-regression refactor.

## Current policy

`EZ_V1/` is the governance and documentation root for the V1 lane.

The actual V1 source directories still remain at repository top level:

- `EZ_Account/`
- `EZ_CheckPoint/`
- `EZ_GENESIS/`
- `EZ_Main_Chain/`
- `EZ_Miner/`
- `EZ_Msg/`
- `EZ_Transaction/`
- `EZ_Tx_Pool/`
- `EZ_Units/`
- `EZ_VPB/`
- `EZ_VPB_Validator/`

## Migration rule

If the project later decides to physically move V1 under `EZ_V1/`, do it in
phases:

1. eliminate direct top-level imports from compatibility code and tests
2. introduce stable compatibility shims
3. move one V1 subsystem at a time with full regression
4. only then collapse the remaining top-level V1 directories

Until those conditions are met, treat `EZ_V1/` as the logical home of the V1
lane, not the physical source root.
