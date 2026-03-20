# EZ_Miner

Legacy V1 miner compatibility shim.

The physical V1 miner code now lives under:

- `EZ_V1/EZ_Miner/`

This top-level package remains in place so existing imports such as
`from EZ_Miner.miner import Miner` do not break during phased migration.
