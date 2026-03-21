from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .control import read_backend_metadata
from .localnet import SubmittedPayment, V2AccountNode, V2ConsensusNode
from .runtime_v2 import ReceiptDeliveryResult
from .transport import TransferMailboxStore
from .types import OffChainTx, Receipt
from .values import ValueRange
from .wallet import WalletAccountV2


@dataclass(frozen=True, slots=True)
class V2ReceivedTransferEvent:
    package_hash: bytes
    sender_addr: str
    recipient_addr: str
    target_tx: OffChainTx
    target_value: ValueRange


@dataclass(frozen=True, slots=True)
class V2ConfirmedPayment:
    submitted: SubmittedPayment
    receipt: Receipt | None


@dataclass(frozen=True, slots=True)
class V2WalletRecovery:
    receipt_results: tuple[ReceiptDeliveryResult, ...]
    received_events: tuple[V2ReceivedTransferEvent, ...]
    chain_height: int
    pending_bundle_count: int
    pending_incoming_transfer_count: int
    receipt_count: int


class V2LocalAppSession:
    def __init__(
        self,
        *,
        wallet_identity: Mapping[str, Any],
        wallet_db_path: str,
        backend_dir: str,
        chain_id: int,
        genesis_block_hash: bytes,
        auto_confirm_receipts: bool = True,
    ):
        self.wallet_identity = dict(wallet_identity)
        self.backend_dir = Path(backend_dir)
        self.backend_dir.mkdir(parents=True, exist_ok=True)
        self.chain_id = chain_id
        self.genesis_block_hash = genesis_block_hash
        self.wallet = WalletAccountV2(
            address=str(self.wallet_identity["address"]),
            genesis_block_hash=genesis_block_hash,
            db_path=wallet_db_path,
        )
        self.consensus = V2ConsensusNode(
            store_path=str(self.backend_dir / "consensus.sqlite3"),
            chain_id=chain_id,
            genesis_block_hash=genesis_block_hash,
            auto_confirm_registered_wallets=auto_confirm_receipts,
        )
        self.consensus.register_wallet(self.wallet, auto_confirm_receipts=auto_confirm_receipts)
        self.account_node = V2AccountNode(
            name=str(self.wallet_identity.get("name", "default")),
            private_key_pem=str(self.wallet_identity["private_key_pem"]).encode("utf-8"),
            public_key_pem=str(self.wallet_identity["public_key_pem"]).encode("utf-8"),
            wallet=self.wallet,
            chain_id=chain_id,
            consensus=self.consensus,
        )
        self.mailbox = TransferMailboxStore(str(self.backend_dir / "transfer_mailbox.sqlite3"))

    @property
    def address(self) -> str:
        return self.wallet.address

    def close(self) -> None:
        try:
            self.mailbox.close()
        finally:
            try:
                self.wallet.close()
            finally:
                self.consensus.close()

    def sync_receipts(self) -> tuple[ReceiptDeliveryResult, ...]:
        if self.wallet.list_pending_bundles():
            return self.account_node.sync_receipts()
        return ()

    def sync_incoming_transfers(self) -> tuple[V2ReceivedTransferEvent, ...]:
        pending_packages = list(self.mailbox.list_pending_packages(self.address))
        pending_packages.sort(
            key=lambda item: (
                item[3].witness_v2.confirmed_bundle_chain[0].receipt.header_lite.height
                if item[3].witness_v2.confirmed_bundle_chain else -1,
                item[2],
                item[0],
            )
        )
        accepted_events: list[V2ReceivedTransferEvent] = []
        for package_hash, sender_addr, _, package in pending_packages:
            result = self.account_node.receive_transfer_package(package)
            if result.accepted and result.record is not None:
                accepted_events.append(
                    V2ReceivedTransferEvent(
                        package_hash=package_hash,
                        sender_addr=sender_addr,
                        recipient_addr=self.address,
                        target_tx=package.target_tx,
                        target_value=package.target_value,
                    )
                )
                self.mailbox.mark_claimed(package_hash, claimed_at=int(time.time()))
                continue
            if result.error == "transfer package already accepted":
                self.mailbox.mark_claimed(package_hash, claimed_at=int(time.time()))
        return tuple(accepted_events)

    def recover_wallet_state(self) -> V2WalletRecovery:
        receipt_results = self.sync_receipts()
        received_events = self.sync_incoming_transfers()
        return V2WalletRecovery(
            receipt_results=receipt_results,
            received_events=received_events,
            chain_height=self.consensus.chain.current_height,
            pending_bundle_count=len(self.wallet.list_pending_bundles()),
            pending_incoming_transfer_count=self.pending_incoming_transfer_count(),
            receipt_count=len(self.wallet.list_receipts()),
        )

    def sync_wallet_state(self) -> tuple[V2ReceivedTransferEvent, ...]:
        return self.recover_wallet_state().received_events

    def queue_outgoing_transfer_packages(self, target_tx: OffChainTx) -> None:
        for value in target_tx.value_list:
            package = self.account_node.export_transfer_package(target_tx, value)
            self.mailbox.enqueue_package(
                sender_addr=self.address,
                recipient_addr=target_tx.recipient_addr,
                package=package,
                created_at=int(target_tx.tx_time),
            )

    def submit_confirmed_payment(
        self,
        *,
        recipient_addr: str,
        amount: int,
        expiry_height: int,
        fee: int = 0,
        anti_spam_nonce: int | None = None,
    ) -> V2ConfirmedPayment:
        submitted = self.account_node.submit_payment(
            recipient_addr,
            amount=amount,
            fee=fee,
            expiry_height=expiry_height,
            anti_spam_nonce=anti_spam_nonce,
        )
        produced = self.consensus.produce_block()
        delivery = produced.deliveries.get(self.address)
        if delivery is None:
            raise RuntimeError("sender_receipt_delivery_missing")
        if not delivery.applied:
            self.sync_receipts()
            if self.wallet.list_pending_bundles():
                raise RuntimeError(f"sender_receipt_not_applied:{delivery.error or 'unknown'}")
        receipt = delivery.receipt or self.consensus.get_receipt(self.address, submitted.submission.envelope.seq).receipt
        self.queue_outgoing_transfer_packages(submitted.target_tx)
        return V2ConfirmedPayment(submitted=submitted, receipt=receipt)

    def register_genesis_value(self, value: ValueRange) -> None:
        self.wallet.add_genesis_value(value)
        self.consensus.register_genesis_allocation(self.address, value)

    def pending_incoming_transfer_count(self) -> int:
        return self.mailbox.pending_count(self.address)


class V2LocalAppClient:
    def __init__(
        self,
        *,
        backend_dir: str,
        chain_id: int,
        genesis_block_hash: bytes,
    ):
        self.backend_dir = Path(backend_dir)
        self.backend_dir.mkdir(parents=True, exist_ok=True)
        self.chain_id = chain_id
        self.genesis_block_hash = genesis_block_hash

    def backend_metadata(self) -> dict[str, Any] | None:
        return read_backend_metadata(str(self.backend_dir))

    def open_session(
        self,
        *,
        wallet_identity: Mapping[str, Any],
        wallet_db_path: str,
        auto_confirm_receipts: bool = True,
    ) -> V2LocalAppSession:
        return V2LocalAppSession(
            wallet_identity=wallet_identity,
            wallet_db_path=wallet_db_path,
            backend_dir=str(self.backend_dir),
            chain_id=self.chain_id,
            genesis_block_hash=self.genesis_block_hash,
            auto_confirm_receipts=auto_confirm_receipts,
        )
