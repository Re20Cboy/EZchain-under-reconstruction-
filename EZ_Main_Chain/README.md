# EZ_Main_Chain

Legacy V1 main-chain compatibility shim.

The physical V1 main-chain implementation now lives under:

- `EZ_V1/EZ_Main_Chain/`

This top-level package remains in place so existing imports such as
`from EZ_Main_Chain.Blockchain import Blockchain` continue to work during
phased migration.
