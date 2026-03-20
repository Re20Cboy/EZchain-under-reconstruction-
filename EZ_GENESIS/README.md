# EZ_GENESIS

Legacy V1 genesis compatibility shim.

The physical V1 genesis implementation now lives under:

- `EZ_V1/EZ_GENESIS/`

This top-level package remains in place so existing imports such as
`from EZ_GENESIS.genesis import create_genesis_block` continue to work during
phased migration.
