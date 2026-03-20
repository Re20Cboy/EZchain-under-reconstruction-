# EZ_Units

Legacy V1 shared-units compatibility shim.

The physical V1 shared-units implementation now lives under:

- `EZ_V1/EZ_Units/`

This top-level package remains in place so existing imports such as
`from EZ_Units.MerkleTree import MerkleTree` continue to work during phased
migration.
