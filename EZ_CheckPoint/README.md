# EZ_CheckPoint

Legacy V1 checkpoint compatibility shim.

The physical V1 checkpoint implementation now lives under:

- `EZ_V1/EZ_CheckPoint/`

This top-level package remains in place so existing imports such as
`from EZ_CheckPoint.CheckPoint import CheckPointRecord` continue to work during
phased migration.
