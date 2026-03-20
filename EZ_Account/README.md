# EZ_Account

Legacy V1 account compatibility surface.

The physical V1 account implementation now lives under:

- `EZ_V1/EZ_Account/`

This top-level package remains so existing imports such as:

- `from EZ_Account.Account import Account`

continue to work during phased cleanup.

## Historical / non-runtime material

- `test/`
  - maintained legacy account test tree
- `backup_test_files/`
  - top-level pointer only; archived exploratory tests now live in `EZ_V1/EZ_Account/legacy_tests_backup/`

## Maintenance rule

Treat this directory as a compatibility shell, not a place for new product work.
New user-facing work belongs in `EZ_V2/` or `EZ_App/`.
