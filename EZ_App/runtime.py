from __future__ import annotations

import secrets
import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from EZ_Account.Account import Account
from EZ_Tx_Pool.TXPool import TxPool
from EZ_VPB.values.Value import Value, ValueState

from EZ_App.wallet_store import WalletStore


@dataclass
class TxResult:
    tx_hash: str
    submit_hash: str
    amount: int
    recipient: str
    status: str
    client_tx_id: Optional[str] = None


class TxEngine:
    def __init__(self, data_dir: str, max_tx_amount: int = 100000000):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pool = TxPool(db_path=str(self.data_dir / "app_tx_pool.db"))
        self.max_tx_amount = max_tx_amount
        self.idempotency_file = self.data_dir / "tx_idempotency.json"

    def _build_account(self, wallet_store: WalletStore, password: str) -> Account:
        wallet = wallet_store.load_wallet(password=password)
        wallet_dir = self.data_dir / "wallet_state" / wallet["address"]
        wallet_dir.mkdir(parents=True, exist_ok=True)
        return Account(
            address=wallet["address"],
            private_key_pem=wallet["private_key_pem"].encode("utf-8"),
            public_key_pem=wallet["public_key_pem"].encode("utf-8"),
            name=wallet.get("name", "default"),
            data_directory=str(wallet_dir),
        )

    def faucet(self, wallet_store: WalletStore, password: str, amount: int) -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")

        account = self._build_account(wallet_store, password)
        # Build chunks that guarantee full subset coverage for [1..amount].
        # If the current cover is [0..cover], adding chunk <= cover+1 extends it
        # to [0..cover+chunk], which avoids "cannot compose exact amount" failures.
        remainder = amount
        cover = 0
        minted_chunks = []
        while remainder > 0:
            chunk = min(cover + 1, remainder)
            minted_chunks.append(int(chunk))
            remainder -= int(chunk)
            cover += int(chunk)

        for chunk in minted_chunks:
            begin = "0x" + secrets.token_hex(16)
            value = Value(begin, chunk, ValueState.UNSPENT)
            ok = account.vpb_manager.value_collection.add_value(value)
            if not ok:
                raise RuntimeError("faucet_add_value_failed")

        return {
            "address": account.address,
            "faucet_amount": amount,
            "minted_values": len(minted_chunks),
            "available_balance": account.get_available_balance(),
            "total_balance": account.get_total_balance(),
        }

    def _load_idempotency(self) -> Dict[str, Dict[str, Any]]:
        if not self.idempotency_file.exists():
            return {}
        try:
            data = self.idempotency_file.read_text(encoding="utf-8")
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
        return {}

    def _save_idempotency(self, data: Dict[str, Dict[str, Any]]) -> None:
        self.idempotency_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def send(
        self,
        wallet_store: WalletStore,
        password: str,
        recipient: str,
        amount: int,
        client_tx_id: Optional[str] = None,
    ) -> TxResult:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")
        if amount > self.max_tx_amount:
            raise ValueError("amount_exceeds_limit")
        if not recipient:
            raise ValueError("recipient_required")

        account = self._build_account(wallet_store, password)
        idem_key = ""
        idempotency = self._load_idempotency()
        if client_tx_id:
            idem_key = f"{account.address}:{client_tx_id}"
            if idem_key in idempotency:
                raise ValueError("duplicate_transaction")

        multi_txn_result = account.create_batch_transactions([
            {
                "recipient": recipient,
                "amount": amount,
            }
        ])
        if not multi_txn_result:
            if account.get_available_balance() < amount:
                raise ValueError("insufficient_balance")
            raise ValueError("insufficient_spendable_values")

        confirmed = account.confirm_multi_transaction(multi_txn_result)
        if not confirmed:
            raise RuntimeError("confirm_transaction_failed")

        submit_tx_info = account.create_submit_tx_info(multi_txn_result)
        if not submit_tx_info:
            raise RuntimeError("create_submit_tx_info_failed")

        success, message = self.pool.add_submit_tx_info(
            submit_tx_info,
            multi_transactions=multi_txn_result.get("multi_transactions"),
        )
        if not success:
            raise RuntimeError(f"submit_to_pool_failed:{message}")

        result = TxResult(
            tx_hash=submit_tx_info.multi_transactions_hash,
            submit_hash=submit_tx_info.get_hash(),
            amount=amount,
            recipient=recipient,
            status="submitted",
            client_tx_id=client_tx_id,
        )
        if idem_key:
            idempotency[idem_key] = {
                "tx_hash": result.tx_hash,
                "submit_hash": result.submit_hash,
                "amount": amount,
                "recipient": recipient,
                "recorded_at": datetime.utcnow().isoformat(),
            }
            self._save_idempotency(idempotency)
        return result

    def balance(self, wallet_store: WalletStore, password: str) -> Dict[str, Any]:
        account = self._build_account(wallet_store, password)
        return {
            "address": account.address,
            "available_balance": account.get_available_balance(),
            "total_balance": account.get_total_balance(),
            "unspent_balance": account.get_balance(ValueState.UNSPENT),
            "pending_balance": account.get_balance(ValueState.PENDING),
            "onchain_balance": account.get_balance(ValueState.ONCHAIN),
            "confirmed_balance": account.get_balance(ValueState.CONFIRMED),
        }
