from __future__ import annotations

import time
from dataclasses import dataclass

from .chain import ChainStateV2, compute_bundle_hash
from .types import BlockV2, BundleSubmission, ConfirmedBundleUnit, GenesisAnchor, Receipt, TransferPackage
from .validator import V2TransferValidator, ValidationContext
from .values import LocalValueRecord, ValueRange
from .wallet import WalletAccountV2


@dataclass(frozen=True, slots=True)
class BundleSubmitResult:
    sender_addr: str
    seq: int
    bundle_hash: bytes


@dataclass(frozen=True, slots=True)
class ReceiptDeliveryResult:
    sender_addr: str
    seq: int
    receipt: Receipt | None
    applied: bool
    confirmed_unit: ConfirmedBundleUnit | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProduceBlockResult:
    block: BlockV2
    receipts: dict[str, Receipt]
    deliveries: dict[str, ReceiptDeliveryResult]


@dataclass(frozen=True, slots=True)
class ApplyBlockResult:
    block: BlockV2
    receipts: dict[str, Receipt]
    deliveries: dict[str, ReceiptDeliveryResult]


@dataclass(frozen=True, slots=True)
class TransferDeliveryResult:
    recipient_addr: str
    package: TransferPackage
    accepted: bool
    record: LocalValueRecord | None = None
    error: str | None = None


class V2Runtime:
    def __init__(
        self,
        chain: ChainStateV2 | None = None,
        auto_confirm_registered_wallets: bool = True,
    ):
        self.chain = chain or ChainStateV2()
        self.auto_confirm_registered_wallets = auto_confirm_registered_wallets
        self._wallets: dict[str, WalletAccountV2] = {}
        self._wallet_auto_confirm: dict[str, bool] = {}
        self._genesis_allocations: dict[str, tuple[ValueRange, ...]] = {}

    def register_wallet(
        self,
        wallet: WalletAccountV2,
        auto_confirm_receipts: bool | None = None,
    ) -> None:
        self._wallets[wallet.address] = wallet
        self._wallet_auto_confirm[wallet.address] = (
            self.auto_confirm_registered_wallets
            if auto_confirm_receipts is None
            else bool(auto_confirm_receipts)
        )
        self._ingest_wallet_genesis_allocations(wallet)
        self._share_canonical_chain_headers(wallet)

    def unregister_wallet(self, sender_addr: str) -> None:
        self._wallets.pop(sender_addr, None)
        self._wallet_auto_confirm.pop(sender_addr, None)

    def register_genesis_allocation(self, owner_addr: str, value: ValueRange) -> None:
        existing = list(self._genesis_allocations.get(owner_addr, ()))
        if value not in existing:
            existing.append(value)
            existing.sort(key=lambda item: (item.begin, item.end))
            self._genesis_allocations[owner_addr] = tuple(existing)

    def build_validation_context(self, trusted_checkpoints=()) -> ValidationContext:
        return ValidationContext(
            genesis_allocations=dict(self._genesis_allocations),
            trusted_checkpoints=tuple(trusted_checkpoints),
        )

    def build_validator(self, trusted_checkpoints=()) -> V2TransferValidator:
        return V2TransferValidator(self.build_validation_context(trusted_checkpoints=trusted_checkpoints))

    def submit_bundle(self, submission: BundleSubmission) -> BundleSubmitResult:
        sender_addr = self.chain.submit_bundle(submission)
        return BundleSubmitResult(
            sender_addr=sender_addr,
            seq=submission.envelope.seq,
            bundle_hash=compute_bundle_hash(submission.sidecar),
        )

    def produce_block(
        self,
        timestamp: int | None = None,
        proposer_sig: bytes = b"",
        consensus_extra: bytes = b"",
        limit: int | None = None,
    ) -> ProduceBlockResult:
        if not self.chain.bundle_pool.snapshot(limit=limit):
            raise ValueError("no pending bundles to package")
        block, receipts = self.chain.build_block(
            timestamp=int(time.time()) if timestamp is None else timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
            limit=limit,
        )
        self._share_block_with_wallets(block)
        deliveries = self.deliver_receipts(receipts)
        return ProduceBlockResult(
            block=block,
            receipts=receipts,
            deliveries=deliveries,
        )

    def apply_block(self, block: BlockV2) -> ApplyBlockResult:
        receipts = self.chain.apply_block(block)
        self._share_block_with_wallets(block)
        deliveries = self.deliver_receipts(receipts)
        return ApplyBlockResult(
            block=block,
            receipts=receipts,
            deliveries=deliveries,
        )

    def get_receipt(self, sender_addr: str, seq: int):
        return self.chain.receipt_cache.get_receipt(sender_addr, seq)

    def get_receipt_by_ref(self, bundle_ref):
        return self.chain.receipt_cache.get_receipt_by_ref(bundle_ref)

    def sync_wallet_receipts(self, sender_addr: str) -> tuple[ReceiptDeliveryResult, ...]:
        wallet = self._wallets.get(sender_addr)
        if wallet is None:
            raise ValueError("wallet_not_registered")
        results: list[ReceiptDeliveryResult] = []
        for context in wallet.list_pending_bundles():
            response = self.get_receipt(sender_addr, context.seq)
            if response.receipt is None:
                wallet.mark_receipt_missing(context.seq)
                results.append(
                    ReceiptDeliveryResult(
                        sender_addr=sender_addr,
                        seq=context.seq,
                        receipt=None,
                        applied=False,
                        error="missing_receipt",
                    )
                )
                continue
            results.append(self._apply_receipt_to_wallet(wallet, response.receipt))
        return tuple(results)

    def deliver_receipts(self, receipts: dict[str, Receipt]) -> dict[str, ReceiptDeliveryResult]:
        return self._deliver_receipts(receipts)

    def deliver_transfer_package(
        self,
        package: TransferPackage,
        recipient_addr: str | None = None,
        trusted_checkpoints=(),
    ) -> TransferDeliveryResult:
        resolved_recipient = recipient_addr or package.target_tx.recipient_addr
        wallet = self._wallets.get(resolved_recipient)
        if wallet is None:
            return TransferDeliveryResult(
                recipient_addr=resolved_recipient,
                package=package,
                accepted=False,
                error="wallet_not_registered",
            )
        try:
            record = wallet.receive_transfer(
                package=package,
                validator=self.build_validator(trusted_checkpoints=trusted_checkpoints),
            )
        except Exception as exc:
            return TransferDeliveryResult(
                recipient_addr=resolved_recipient,
                package=package,
                accepted=False,
                error=str(exc),
            )
        return TransferDeliveryResult(
            recipient_addr=resolved_recipient,
            package=package,
            accepted=True,
            record=record,
        )

    def _deliver_receipts(self, receipts: dict[str, Receipt]) -> dict[str, ReceiptDeliveryResult]:
        return {
            sender_addr: self._deliver_receipt(sender_addr, receipt)
            for sender_addr, receipt in receipts.items()
        }

    def _share_canonical_chain_headers(self, wallet: WalletAccountV2) -> None:
        for block in self.chain.blocks:
            wallet.observe_canonical_block(block)

    def _share_block_with_wallets(self, block: BlockV2) -> None:
        for wallet in self._wallets.values():
            wallet.observe_canonical_block(block)

    def _ingest_wallet_genesis_allocations(self, wallet: WalletAccountV2) -> None:
        for record in wallet.list_records():
            anchor = getattr(record.witness_v2, "anchor", None)
            if not isinstance(anchor, GenesisAnchor):
                continue
            self.register_genesis_allocation(
                anchor.first_owner_addr,
                ValueRange(anchor.value_begin, anchor.value_end),
            )

    def _deliver_receipt(self, sender_addr: str, receipt: Receipt) -> ReceiptDeliveryResult:
        wallet = self._wallets.get(sender_addr)
        if wallet is None:
            return ReceiptDeliveryResult(
                sender_addr=sender_addr,
                seq=receipt.seq,
                receipt=receipt,
                applied=False,
                error="wallet_not_registered",
            )
        if not self._wallet_auto_confirm.get(sender_addr, self.auto_confirm_registered_wallets):
            return ReceiptDeliveryResult(
                sender_addr=sender_addr,
                seq=receipt.seq,
                receipt=receipt,
                applied=False,
                error="auto_confirm_disabled",
            )
        return self._apply_receipt_to_wallet(wallet, receipt)

    def _apply_receipt_to_wallet(self, wallet: WalletAccountV2, receipt: Receipt) -> ReceiptDeliveryResult:
        try:
            confirmed_unit = wallet.on_receipt_confirmed(receipt)
        except Exception as exc:
            return ReceiptDeliveryResult(
                sender_addr=wallet.address,
                seq=receipt.seq,
                receipt=receipt,
                applied=False,
                error=str(exc),
            )
        return ReceiptDeliveryResult(
            sender_addr=wallet.address,
            seq=receipt.seq,
            receipt=receipt,
            applied=True,
            confirmed_unit=confirmed_unit,
        )


__all__ = [
    "ApplyBlockResult",
    "BundleSubmitResult",
    "ProduceBlockResult",
    "ReceiptDeliveryResult",
    "TransferDeliveryResult",
    "V2Runtime",
]
