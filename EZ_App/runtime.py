from __future__ import annotations

import secrets
import json
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from EZ_V2.app_client import V2LocalAppClient, V2LocalAppSession
from EZ_V2.crypto import keccak256
from EZ_V2.encoding import canonical_encode
from EZ_V2.network_host import V2AccountHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo, with_v2_features
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2

from EZ_App.wallet_store import WalletStore

if TYPE_CHECKING:
    from EZ_Account.Account import Account


@dataclass
class TxResult:
    tx_hash: str
    submit_hash: str
    amount: int
    recipient: str
    status: str
    client_tx_id: Optional[str] = None
    receipt_height: Optional[int] = None
    receipt_block_hash: Optional[str] = None


class TxEngine:
    def __init__(
        self,
        data_dir: str,
        max_tx_amount: int = 100000000,
        protocol_version: str = "v1",
        v2_chain_id: int = 1,
        v2_expiry_height: int = 1000000,
        v2_backend_dir: str | None = None,
        v2_network_timeout_sec: float = 20.0,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.protocol_version = str(protocol_version or "v1").lower()
        if self.protocol_version not in {"v1", "v2"}:
            raise ValueError("unsupported protocol_version")
        if self.protocol_version == "v1":
            from EZ_Tx_Pool.TXPool import TxPool

            self.pool = TxPool(db_path=str(self.data_dir / "app_tx_pool.db"))
        else:
            self.pool = None
        self.max_tx_amount = max_tx_amount
        self.v2_chain_id = v2_chain_id
        self.v2_expiry_height = v2_expiry_height
        self.v2_network_timeout_sec = max(0.5, float(v2_network_timeout_sec))
        self.v2_genesis_block_hash = b"\x00" * 32
        self.v2_backend_dir = Path(v2_backend_dir) if v2_backend_dir else (self.data_dir / "v2_runtime")
        self.v2_backend_dir.mkdir(parents=True, exist_ok=True)
        self.v2_client = V2LocalAppClient(
            backend_dir=str(self.v2_backend_dir),
            chain_id=self.v2_chain_id,
            genesis_block_hash=self.v2_genesis_block_hash,
        )
        self.v2_backend_lock = threading.Lock()
        self._v2_session_registry: dict[int, V2LocalAppSession] = {}
        self.v2_faucet_state_file = self.data_dir / "v2_faucet_state.json"
        self.idempotency_file = self.data_dir / "tx_idempotency.json"
        self.idempotency_lock = threading.Lock()

    def _build_account(self, wallet_store: WalletStore, password: str) -> Account:
        from EZ_Account.Account import Account

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

    def _build_v2_wallet(self, wallet_store: WalletStore, password: str) -> tuple[Dict[str, Any], str]:
        wallet = wallet_store.load_v2_wallet(password=password)
        wallet_dir = self.data_dir / "wallet_state_v2" / wallet["address"]
        wallet_dir.mkdir(parents=True, exist_ok=True)
        return wallet, str(wallet_dir / "wallet_v2.db")

    def _open_v2_session(
        self,
        wallet_store: WalletStore,
        password: str,
        *,
        auto_confirm_receipts: bool = True,
    ) -> tuple[Dict[str, Any], V2LocalAppSession]:
        wallet_identity, wallet_db_path = self._build_v2_wallet(wallet_store, password)
        session = self.v2_client.open_session(
            wallet_identity=wallet_identity,
            wallet_db_path=wallet_db_path,
            auto_confirm_receipts=auto_confirm_receipts,
        )
        return wallet_identity, session

    def _open_v2_backend(
        self,
        wallet_store: WalletStore,
        password: str,
        *,
        auto_confirm_receipts: bool = True,
    ):
        wallet_identity, session = self._open_v2_session(
            wallet_store,
            password,
            auto_confirm_receipts=auto_confirm_receipts,
        )
        self._v2_session_registry[id(session.wallet)] = session
        self._v2_session_registry[id(session.consensus)] = session
        return wallet_identity, session.wallet, session.consensus, session.account_node

    def _close_v2_backend(self, account, consensus) -> None:
        session = self._v2_session_registry.pop(id(account), None)
        if session is None:
            session = self._v2_session_registry.pop(id(consensus), None)
        else:
            self._v2_session_registry.pop(id(session.consensus), None)
        if session is not None:
            session.close()

    def _record_v2_received_events(self, wallet_store: WalletStore, session: V2LocalAppSession) -> None:
        recovery = session.recover_wallet_state()
        for event in recovery.received_events:
            wallet_store.append_history(
                {
                    "tx_id": self._v2_tx_hash(event.target_tx),
                    "transfer_package_hash": event.package_hash.hex(),
                    "sender": event.sender_addr,
                    "recipient": event.recipient_addr,
                    "amount": event.target_value.size,
                    "status": "received",
                    "direction": "inbound",
                    "value_begin": event.target_value.begin,
                    "value_end": event.target_value.end,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    def _load_v2_faucet_state(self) -> Dict[str, int]:
        if not self.v2_faucet_state_file.exists():
            return {"next_begin": 0}
        try:
            parsed = json.loads(self.v2_faucet_state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"next_begin": 0}
        if not isinstance(parsed, dict):
            return {"next_begin": 0}
        next_begin = int(parsed.get("next_begin", 0))
        return {"next_begin": max(0, next_begin)}

    def _save_v2_faucet_state(self, state: Dict[str, int]) -> None:
        self.v2_faucet_state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _next_v2_faucet_range(self, amount: int) -> ValueRange:
        state = self._load_v2_faucet_state()
        begin = int(state.get("next_begin", 0))
        value = ValueRange(begin=begin, end=begin + amount - 1)
        self._save_v2_faucet_state({"next_begin": value.end + 1})
        return value

    def _v2_tx_hash(self, tx: Any) -> str:
        return keccak256(b"EZCHAIN_APP_V2_TX" + canonical_encode(tx)).hex()

    def _v2_submit_hash(self, envelope: Any) -> str:
        return keccak256(b"EZCHAIN_APP_V2_SUBMISSION" + canonical_encode(envelope)).hex()

    def _remote_v2_wallet_db_path(self, wallet_address: str, state: Dict[str, Any]) -> str:
        path = str(state.get("wallet_db_path", "")).strip()
        if path:
            return path
        return str(self.data_dir / "wallet_state_v2" / wallet_address / "wallet_v2.db")

    def _local_v2_wallet_db_path(self, wallet_address: str) -> str:
        return str(self.data_dir / "wallet_state_v2" / wallet_address / "wallet_v2.db")

    @staticmethod
    def _remote_v2_chain_height(state: Dict[str, Any]) -> int:
        cursor = state.get("chain_cursor")
        if isinstance(cursor, dict):
            try:
                return int(cursor.get("height", 0))
            except Exception:
                return 0
        return 0

    @staticmethod
    def _parse_endpoint(endpoint: str) -> tuple[str, int]:
        host, port_s = endpoint.rsplit(":", 1)
        return host.strip(), int(port_s)

    @staticmethod
    def _peer_id_for_address(address: str) -> str:
        return f"account-{str(address).lower()[-8:]}"

    def _open_remote_v2_wallet(self, wallet_store: WalletStore, password: str, state: Dict[str, Any]) -> WalletAccountV2:
        wallet = wallet_store.load_v2_wallet(password=password)
        remote_address = str(state.get("address", "")).strip()
        if remote_address and remote_address != wallet["address"]:
            raise ValueError("wallet_address_mismatch_with_account_node")
        db_path = self._remote_v2_wallet_db_path(wallet["address"], state)
        return WalletAccountV2(
            address=wallet["address"],
            genesis_block_hash=self.v2_genesis_block_hash,
            db_path=db_path,
        )

    @staticmethod
    def _v2_balance_payload(account: WalletAccountV2, *, chain_height: int, pending_incoming_transfer_count: int) -> Dict[str, Any]:
        breakdown = {
            status.value: amount
            for status, amount in account.balance_breakdown().items()
        }
        return {
            "address": account.address,
            "protocol_version": "v2",
            "available_balance": account.available_balance(),
            "total_balance": account.total_balance(),
            "unspent_balance": account.get_balance(LocalValueStatus.VERIFIED_SPENDABLE),
            "pending_balance": account.pending_balance(),
            "onchain_balance": 0,
            "confirmed_balance": account.get_balance(LocalValueStatus.VERIFIED_SPENDABLE),
            "pending_bundle_count": len(account.list_pending_bundles()),
            "pending_incoming_transfer_count": pending_incoming_transfer_count,
            "v2_status_breakdown": breakdown,
            "chain_height": chain_height,
        }

    @staticmethod
    def _v2_pending_payload(account: WalletAccountV2, *, chain_height: int) -> Dict[str, Any]:
        items = [
            {
                "seq": context.seq,
                "bundle_hash": context.bundle_hash.hex(),
                "created_at": context.created_at,
                "outgoing_values": [
                    {"begin": value.begin, "end": value.end}
                    for value in context.outgoing_values
                ],
            }
            for context in account.list_pending_bundles()
        ]
        return {
            "address": account.address,
            "protocol_version": "v2",
            "chain_height": chain_height,
            "items": items,
        }

    def _v2_history_key(self, item: Dict[str, Any]) -> tuple[Any, ...] | None:
        transfer_package_hash = str(item.get("transfer_package_hash", "")).strip()
        if transfer_package_hash:
            return ("transfer", transfer_package_hash)
        tx_id = str(item.get("tx_id", "")).strip()
        if not tx_id:
            return None
        status = str(item.get("status", "")).strip()
        if status == "received":
            begin = item.get("value_begin")
            end = item.get("value_end")
            if begin is not None and end is not None:
                return ("received", tx_id, int(begin), int(end))
        return ("tx", tx_id, status)

    def _merge_v2_history_items(
        self,
        stored_items: list[Dict[str, Any]],
        derived_items: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        merged = [dict(item) for item in stored_items]
        seen = {key for item in merged if (key := self._v2_history_key(item)) is not None}
        for item in derived_items:
            key = self._v2_history_key(item)
            if key is not None and key in seen:
                continue
            merged.append(dict(item))
            if key is not None:
                seen.add(key)
        return merged

    def _derive_v2_history_items(self, account: WalletAccountV2) -> list[Dict[str, Any]]:
        items: list[Dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for record in sorted(
            account.list_records(),
            key=lambda item: (
                item.acquisition_height,
                item.value.begin,
                item.value.end,
                item.record_id,
            ),
        ):
            chain = getattr(record.witness_v2, "confirmed_bundle_chain", ())
            if not chain:
                continue
            latest_unit = chain[0]
            receipt = latest_unit.receipt
            receipt_height = int(receipt.header_lite.height)
            receipt_block_hash = receipt.header_lite.block_hash.hex()
            for tx in latest_unit.bundle_sidecar.tx_list:
                matching_value = next((value for value in tx.value_list if value == record.value), None)
                if matching_value is None:
                    continue
                tx_id = self._v2_tx_hash(tx)
                if tx.sender_addr == account.address:
                    item = {
                        "tx_id": tx_id,
                        "sender": tx.sender_addr,
                        "recipient": tx.recipient_addr,
                        "amount": sum(value.size for value in tx.value_list),
                        "status": "confirmed",
                        "direction": "outbound",
                        "receipt_height": receipt_height,
                        "receipt_block_hash": receipt_block_hash,
                    }
                elif tx.recipient_addr == account.address:
                    item = {
                        "tx_id": tx_id,
                        "sender": tx.sender_addr,
                        "recipient": tx.recipient_addr,
                        "amount": matching_value.size,
                        "status": "received",
                        "direction": "inbound",
                        "value_begin": matching_value.begin,
                        "value_end": matching_value.end,
                        "receipt_height": receipt_height,
                        "receipt_block_hash": receipt_block_hash,
                    }
                else:
                    continue
                key = self._v2_history_key(item)
                if key is not None and key in seen:
                    continue
                items.append(item)
                if key is not None:
                    seen.add(key)
        return items

    def _v2_history_payload(
        self,
        wallet_store: WalletStore,
        account: WalletAccountV2 | None,
        *,
        chain_height: int,
    ) -> Dict[str, Any]:
        stored_items = wallet_store.get_history()
        derived_items = self._derive_v2_history_items(account) if account is not None else []
        address = account.address if account is not None else wallet_store.summary(protocol_version="v2").address
        return {
            "address": address,
            "protocol_version": "v2",
            "chain_height": chain_height,
            "items": self._merge_v2_history_items(stored_items, derived_items),
        }

    @staticmethod
    def _v2_receipts_payload(account: WalletAccountV2, *, chain_height: int) -> Dict[str, Any]:
        items = [
            {
                "seq": receipt.seq,
                "height": receipt.header_lite.height,
                "block_hash": receipt.header_lite.block_hash.hex(),
                "state_root": receipt.header_lite.state_root.hex(),
                "prev_ref": (
                    None
                    if receipt.prev_ref is None
                    else {
                        "height": receipt.prev_ref.height,
                        "block_hash": receipt.prev_ref.block_hash.hex(),
                        "bundle_hash": receipt.prev_ref.bundle_hash.hex(),
                        "seq": receipt.prev_ref.seq,
                    }
                ),
            }
            for receipt in account.list_receipts()
        ]
        return {
            "address": account.address,
            "protocol_version": "v2",
            "chain_height": chain_height,
            "items": items,
        }

    @staticmethod
    def _v2_checkpoints_payload(
        account: WalletAccountV2,
        *,
        chain_height: int,
        pending_incoming_transfer_count: int,
    ) -> Dict[str, Any]:
        items = [
            {
                "value_begin": checkpoint.value_begin,
                "value_end": checkpoint.value_end,
                "owner_addr": checkpoint.owner_addr,
                "checkpoint_height": checkpoint.checkpoint_height,
                "checkpoint_block_hash": checkpoint.checkpoint_block_hash.hex(),
                "checkpoint_bundle_hash": checkpoint.checkpoint_bundle_hash.hex(),
            }
            for checkpoint in account.list_checkpoints()
        ]
        return {
            "address": account.address,
            "protocol_version": "v2",
            "chain_height": chain_height,
            "items": items,
            "pending_incoming_transfer_count": pending_incoming_transfer_count,
        }

    def _submit_transaction_v2(
        self,
        wallet_store: WalletStore,
        password: str,
        recipient: str,
        amount: int,
        client_tx_id: Optional[str],
    ) -> TxResult:
        with self.v2_backend_lock:
            _, session = self._open_v2_session(wallet_store, password)
            try:
                self._record_v2_received_events(wallet_store, session)
                account = session.wallet
                if account.list_pending_bundles():
                    raise ValueError("pending_bundle_exists")
                if account.total_balance() < amount:
                    raise ValueError("insufficient_balance")
                if account.available_balance() < amount:
                    raise ValueError("insufficient_spendable_values")

                confirmed = session.submit_confirmed_payment(
                    recipient_addr=recipient,
                    amount=amount,
                    fee=0,
                    expiry_height=self.v2_expiry_height,
                    anti_spam_nonce=secrets.randbelow(1 << 63),
                )
                receipt = confirmed.receipt
                return TxResult(
                    tx_hash=self._v2_tx_hash(confirmed.submitted.target_tx),
                    submit_hash=self._v2_submit_hash(confirmed.submitted.submission.envelope),
                    amount=amount,
                    recipient=recipient,
                    status="confirmed",
                    client_tx_id=client_tx_id,
                    receipt_height=receipt.header_lite.height if receipt else None,
                    receipt_block_hash=receipt.header_lite.block_hash.hex() if receipt else None,
                )
            except ValueError as exc:
                if str(exc) == "wallet already has a pending bundle":
                    raise ValueError("pending_bundle_exists") from exc
                raise
            finally:
                session.close()

    def faucet(self, wallet_store: WalletStore, password: str, amount: int) -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")

        if self.protocol_version == "v2":
            with self.v2_backend_lock:
                _, session = self._open_v2_session(wallet_store, password)
                try:
                    minted_value = self._next_v2_faucet_range(amount)
                    session.register_genesis_value(minted_value)
                    self._record_v2_received_events(wallet_store, session)
                    account = session.wallet
                    consensus = session.consensus
                    return {
                        "address": account.address,
                        "protocol_version": "v2",
                        "faucet_amount": amount,
                        "minted_values": 1,
                        "available_balance": account.available_balance(),
                        "total_balance": account.total_balance(),
                        "chain_height": consensus.chain.current_height,
                    }
                finally:
                    session.close()

        account = self._build_account(wallet_store, password)
        # Build chunks that guarantee full subset coverage for [1..amount].
        # If the current cover is [0..cover], adding chunk <= cover+1 extends it
        # to [0..cover+chunk], which avoids "cannot compose exact amount" failures.
        from EZ_VPB.values.Value import Value, ValueState

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
        *,
        state: Optional[Dict[str, Any]] = None,
        recipient_endpoint: Optional[str] = None,
    ) -> TxResult:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")
        if amount > self.max_tx_amount:
            raise ValueError("amount_exceeds_limit")
        if not recipient:
            raise ValueError("recipient_required")

        sender_address = wallet_store.summary(protocol_version=self.protocol_version).address
        idem_key = ""
        if client_tx_id:
            with self.idempotency_lock:
                idempotency = self._load_idempotency()
                idem_key = f"{sender_address}:{client_tx_id}"
                if idem_key in idempotency:
                    raise ValueError("duplicate_transaction")
                if self.protocol_version == "v2":
                    if state is not None:
                        result = self.remote_send(
                            wallet_store=wallet_store,
                            password=password,
                            recipient=recipient,
                            amount=amount,
                            recipient_endpoint=recipient_endpoint or "",
                            state=state,
                            client_tx_id=client_tx_id,
                        )
                    else:
                        result = self._submit_transaction_v2(
                            wallet_store=wallet_store,
                            password=password,
                            recipient=recipient,
                            amount=amount,
                            client_tx_id=client_tx_id,
                        )
                else:
                    account = self._build_account(wallet_store, password)
                    result = self._submit_transaction(
                        account=account,
                        recipient=recipient,
                        amount=amount,
                        client_tx_id=client_tx_id,
                    )
                idempotency[idem_key] = {
                    "tx_hash": result.tx_hash,
                    "submit_hash": result.submit_hash,
                    "amount": amount,
                    "recipient": recipient,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                self._save_idempotency(idempotency)
                return result

        if self.protocol_version == "v2":
            if state is not None:
                return self.remote_send(
                    wallet_store=wallet_store,
                    password=password,
                    recipient=recipient,
                    amount=amount,
                    recipient_endpoint=recipient_endpoint or "",
                    state=state,
                    client_tx_id=client_tx_id,
                )
            return self._submit_transaction_v2(
                wallet_store=wallet_store,
                password=password,
                recipient=recipient,
                amount=amount,
                client_tx_id=client_tx_id,
            )
        account = self._build_account(wallet_store, password)
        return self._submit_transaction(account=account, recipient=recipient, amount=amount, client_tx_id=client_tx_id)

    def _submit_transaction(self, account: Account, recipient: str, amount: int, client_tx_id: Optional[str]) -> TxResult:
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

        return TxResult(
            tx_hash=submit_tx_info.multi_transactions_hash,
            submit_hash=submit_tx_info.get_hash(),
            amount=amount,
            recipient=recipient,
            status="submitted",
            client_tx_id=client_tx_id,
        )

    def balance(self, wallet_store: WalletStore, password: str) -> Dict[str, Any]:
        if self.protocol_version == "v2":
            with self.v2_backend_lock:
                _, session = self._open_v2_session(wallet_store, password)
                try:
                    self._record_v2_received_events(wallet_store, session)
                    return self._v2_balance_payload(
                        session.wallet,
                        chain_height=session.consensus.chain.current_height,
                        pending_incoming_transfer_count=session.pending_incoming_transfer_count(),
                    )
                finally:
                    session.close()
        from EZ_VPB.values.Value import ValueState

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

    def pending(self, wallet_store: WalletStore, password: str) -> Dict[str, Any]:
        if self.protocol_version != "v2":
            raise ValueError("pending query is only supported in v2")
        with self.v2_backend_lock:
            _, session = self._open_v2_session(wallet_store, password)
            try:
                self._record_v2_received_events(wallet_store, session)
                return self._v2_pending_payload(
                    session.wallet,
                    chain_height=session.consensus.chain.current_height,
                )
            finally:
                session.close()

    def receipts(self, wallet_store: WalletStore, password: str) -> Dict[str, Any]:
        if self.protocol_version != "v2":
            raise ValueError("receipt query is only supported in v2")
        with self.v2_backend_lock:
            _, session = self._open_v2_session(wallet_store, password)
            try:
                self._record_v2_received_events(wallet_store, session)
                return self._v2_receipts_payload(
                    session.wallet,
                    chain_height=session.consensus.chain.current_height,
                )
            finally:
                session.close()

    def checkpoints(self, wallet_store: WalletStore, password: str) -> Dict[str, Any]:
        if self.protocol_version != "v2":
            raise ValueError("checkpoint query is only supported in v2")
        with self.v2_backend_lock:
            _, session = self._open_v2_session(wallet_store, password)
            try:
                self._record_v2_received_events(wallet_store, session)
                return self._v2_checkpoints_payload(
                    session.wallet,
                    chain_height=session.consensus.chain.current_height,
                    pending_incoming_transfer_count=session.pending_incoming_transfer_count(),
                )
            finally:
                session.close()

    def history(self, wallet_store: WalletStore) -> Dict[str, Any]:
        if self.protocol_version != "v2":
            return {"items": wallet_store.get_history()}
        account = None
        try:
            address = wallet_store.summary(protocol_version="v2").address
            db_path = Path(self._local_v2_wallet_db_path(address))
            if db_path.exists():
                account = WalletAccountV2(
                    address=address,
                    genesis_block_hash=self.v2_genesis_block_hash,
                    db_path=str(db_path),
                )
            chain_height = 0
            metadata = self.v2_client.backend_metadata()
            if isinstance(metadata, dict):
                try:
                    chain_height = int(metadata.get("height", 0))
                except Exception:
                    chain_height = 0
            return self._v2_history_payload(
                wallet_store,
                account,
                chain_height=chain_height,
            )
        finally:
            if account is not None:
                account.close()

    def remote_balance(self, wallet_store: WalletStore, password: str, state: Dict[str, Any]) -> Dict[str, Any]:
        account = self._open_remote_v2_wallet(wallet_store, password, state)
        try:
            return self._v2_balance_payload(
                account,
                chain_height=self._remote_v2_chain_height(state),
                pending_incoming_transfer_count=int(state.get("pending_incoming_transfer_count", 0)),
            )
        finally:
            account.close()

    def remote_pending(self, wallet_store: WalletStore, password: str, state: Dict[str, Any]) -> Dict[str, Any]:
        account = self._open_remote_v2_wallet(wallet_store, password, state)
        try:
            return self._v2_pending_payload(
                account,
                chain_height=self._remote_v2_chain_height(state),
            )
        finally:
            account.close()

    def remote_receipts(self, wallet_store: WalletStore, password: str, state: Dict[str, Any]) -> Dict[str, Any]:
        account = self._open_remote_v2_wallet(wallet_store, password, state)
        try:
            return self._v2_receipts_payload(
                account,
                chain_height=self._remote_v2_chain_height(state),
            )
        finally:
            account.close()

    def remote_checkpoints(self, wallet_store: WalletStore, password: str, state: Dict[str, Any]) -> Dict[str, Any]:
        account = self._open_remote_v2_wallet(wallet_store, password, state)
        try:
            return self._v2_checkpoints_payload(
                account,
                chain_height=self._remote_v2_chain_height(state),
                pending_incoming_transfer_count=int(state.get("pending_incoming_transfer_count", 0)),
            )
        finally:
            account.close()

    def remote_history(self, wallet_store: WalletStore, state: Dict[str, Any]) -> Dict[str, Any]:
        address = wallet_store.summary(protocol_version="v2").address
        remote_address = str(state.get("address", "")).strip()
        if remote_address and remote_address != address:
            raise ValueError("wallet_address_mismatch_with_account_node")
        db_path = Path(self._remote_v2_wallet_db_path(address, state))
        account = None
        try:
            if db_path.exists():
                account = WalletAccountV2(
                    address=address,
                    genesis_block_hash=self.v2_genesis_block_hash,
                    db_path=str(db_path),
                )
            return self._v2_history_payload(
                wallet_store,
                account,
                chain_height=self._remote_v2_chain_height(state),
            )
        finally:
            if account is not None:
                account.close()

    def remote_send(
        self,
        wallet_store: WalletStore,
        password: str,
        *,
        recipient: str,
        amount: int,
        recipient_endpoint: str,
        state: Dict[str, Any],
        client_tx_id: Optional[str],
    ) -> TxResult:
        wallet = wallet_store.load_v2_wallet(password=password)
        remote_address = str(state.get("address", "")).strip()
        if remote_address and remote_address != wallet["address"]:
            raise ValueError("wallet_address_mismatch_with_account_node")
        consensus_endpoint = str(state.get("consensus_endpoint", "")).strip()
        consensus_peer_id = str(state.get("consensus_peer_id", "consensus-0")).strip() or "consensus-0"
        if not consensus_endpoint:
            raise ValueError("consensus_endpoint_missing")
        if not recipient_endpoint.strip():
            raise ValueError("recipient_endpoint_required")
        self._parse_endpoint(consensus_endpoint)
        self._parse_endpoint(recipient_endpoint)

        sender_peer = with_v2_features(
            PeerInfo(
                node_id=self._peer_id_for_address(wallet["address"]),
                role="account",
                endpoint="127.0.0.1:0",
                metadata={"address": wallet["address"]},
            )
        )
        consensus_peer = with_v2_features(
            PeerInfo(node_id=consensus_peer_id, role="consensus", endpoint=consensus_endpoint)
        )
        account_peers: list[PeerInfo] = []
        seen_account_peer_ids: set[str] = {sender_peer.node_id}
        account_peer_id_by_address: dict[str, str] = {}
        for item in tuple(state.get("account_peers", ())):
            if not isinstance(item, dict):
                continue
            address = str(item.get("address", "")).strip()
            endpoint = str(item.get("endpoint", "")).strip()
            if not address or not endpoint or address == wallet["address"]:
                continue
            self._parse_endpoint(endpoint)
            node_id = str(item.get("node_id", "")).strip() or self._peer_id_for_address(address)
            if node_id in seen_account_peer_ids or address in account_peer_id_by_address:
                continue
            account_peers.append(
                with_v2_features(
                    PeerInfo(
                        node_id=node_id,
                        role="account",
                        endpoint=endpoint,
                        metadata={"address": address},
                    )
                )
            )
            seen_account_peer_ids.add(node_id)
            account_peer_id_by_address[address] = node_id
        recipient_peer_id = account_peer_id_by_address.get(recipient, self._peer_id_for_address(recipient))
        if recipient not in account_peer_id_by_address:
            account_peers.append(
                with_v2_features(
                    PeerInfo(
                        node_id=recipient_peer_id,
                        role="account",
                        endpoint=recipient_endpoint,
                        metadata={"address": recipient},
                    )
                )
            )
        host, port = self._parse_endpoint(sender_peer.endpoint)
        network = TransportPeerNetwork(
            TCPNetworkTransport(host, port),
            peers=(sender_peer, consensus_peer, *account_peers),
            timeout_sec=self.v2_network_timeout_sec,
        )
        account_host = V2AccountHost(
            node_id=sender_peer.node_id,
            endpoint=sender_peer.endpoint,
            wallet_db_path=self._remote_v2_wallet_db_path(wallet["address"], state),
            chain_id=self.v2_chain_id,
            network=network,
            consensus_peer_id=consensus_peer.node_id,
            address=wallet["address"],
            private_key_pem=wallet["private_key_pem"].encode("utf-8"),
            public_key_pem=wallet["public_key_pem"].encode("utf-8"),
        )
        try:
            network.start()
            account_host.recover_network_state()
            payment = account_host.submit_payment(
                recipient_peer_id,
                amount=amount,
                expiry_height=self.v2_expiry_height,
                fee=0,
                anti_spam_nonce=secrets.randbelow(1 << 63),
            )
            return TxResult(
                tx_hash=payment.tx_hash_hex,
                submit_hash=payment.submit_hash_hex,
                amount=amount,
                recipient=recipient,
                status="confirmed" if payment.receipt_height is not None else "submitted",
                client_tx_id=client_tx_id,
                receipt_height=payment.receipt_height,
                receipt_block_hash=payment.receipt_block_hash_hex,
            )
        finally:
            try:
                account_host.close()
            finally:
                network.stop()
