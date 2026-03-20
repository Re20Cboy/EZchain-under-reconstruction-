# EZ_Tx_Pool

Legacy V1 transaction-pool compatibility shim.

The physical V1 transaction-pool implementation now lives under:

- `EZ_V1/EZ_Tx_Pool/`

This top-level package remains in place so existing imports such as
`from EZ_Tx_Pool.TXPool import TxPool` continue to work during phased
migration.
