# EZ_VPB_Validator

Legacy V1 VPB validator compatibility shim.

The physical V1 validator implementation now lives under:

- `EZ_V1/EZ_VPB_Validator/`

This top-level package remains in place so existing imports such as
`from EZ_VPB_Validator.vpb_validator import VPBValidator` continue to work
during phased migration.
