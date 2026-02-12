from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

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


class TxEngine:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pool = TxPool(db_path=str(self.data_dir / "app_tx_pool.db"))

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
        # Mint in denomination chunks so transaction creation can assemble exact amounts.
        denominations = [100, 50, 20, 10, 5, 1]
        remainder = amount
        minted_chunks = []
        for d in denominations:
            while remainder >= d:
                minted_chunks.append(d)
                remainder -= d

        if remainder != 0:
            raise RuntimeError("faucet_split_failed")

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

    def send(self, wallet_store: WalletStore, password: str, recipient: str, amount: int) -> TxResult:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")
        if not recipient:
            raise ValueError("recipient_required")

        account = self._build_account(wallet_store, password)

        multi_txn_result = account.create_batch_transactions([
            {
                "recipient": recipient,
                "amount": amount,
            }
        ])
        if not multi_txn_result:
            raise RuntimeError("create_batch_transactions_failed")

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

        return TxResult(
            tx_hash=submit_tx_info.multi_transactions_hash,
            submit_hash=submit_tx_info.get_hash(),
            amount=amount,
            recipient=recipient,
            status="submitted",
        )

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
