from typing import Dict, Any, Optional, Tuple

from EZ_Tx_Pool.TXPool import TxPool
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo


class TxPoolAdapter:
    """Minimal adapter to bridge ACCTXN_SUBMIT to EZ_Tx_Pool.TxPool.

    For MVP, MultiTransactions is optional (None). Validation will
    perform structural checks and accept any non-empty signature bytes
    with matching version.
    """

    def __init__(self, db_path: str = "tx_pool.db"):
        self.pool = TxPool(db_path=db_path)

    def add_submit_tx_info(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Create SubmitTxInfo from dict payload and add to pool.

        The payload must match SubmitTxInfo.to_dict() schema, with
        signature/public_key as hex strings.
        """
        try:
            sti = SubmitTxInfo.from_dict(payload)
        except Exception as e:
            return False, f"Bad SubmitTxInfo payload: {e}"

        ok, msg = self.pool.add_submit_tx_info(sti, multi_transactions=None)
        return ok, msg

