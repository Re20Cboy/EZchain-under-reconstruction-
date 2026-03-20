"""
Legacy V1 transaction-pool compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_Tx_Pool`.
"""

from EZ_V1.EZ_Tx_Pool.PickTx import (
    PackagedBlockData,
    TransactionPicker,
    pick_transactions_from_pool,
    pick_transactions_from_pool_with_proofs,
)
from EZ_V1.EZ_Tx_Pool.TXPool import TxPool, ValidationResult

__all__ = [
    "PackagedBlockData",
    "TransactionPicker",
    "pick_transactions_from_pool",
    "pick_transactions_from_pool_with_proofs",
    "TxPool",
    "ValidationResult",
]
