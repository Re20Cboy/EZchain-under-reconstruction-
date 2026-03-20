# EZ_Transaction

Legacy V1 transaction compatibility surface.

The physical V1 transaction implementation now lives under:

- `EZ_V1/EZ_Transaction/`

This top-level package remains so existing imports such as:

- `from EZ_Transaction.SingleTransaction import Transaction`

continue to work during phased cleanup.

## Historical material

- `EZ_V1/EZ_Transaction/legacy_docs/SubmitTxInfo_design`
  - archived SubmitTxInfo design note

Prefer package-level imports from `EZ_Transaction` for legacy maintenance
touches when practical, but do not add new feature work here.
