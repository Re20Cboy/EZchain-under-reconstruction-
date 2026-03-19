from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .chain import ZERO_HASH32
from .consensus_store import ConsensusStateStore
from .crypto import address_from_public_key_pem, generate_secp256k1_keypair
from .runtime_v2 import (
    ApplyBlockResult,
    BundleSubmitResult,
    ProduceBlockResult,
    ReceiptDeliveryResult,
    TransferDeliveryResult,
    V2Runtime,
)
from .types import BlockV2, BundleSubmission, OffChainTx, TransferPackage
from .values import ValueRange
from .wallet import WalletAccountV2


@dataclass(frozen=True, slots=True)
class SubmittedPayment:
    sender_name: str
    recipient_addr: str
    submission: BundleSubmission
    target_tx: OffChainTx


class V2AccountNode:
    def __init__(
        self,
        *,
        name: str,
        private_key_pem: bytes,
        public_key_pem: bytes,
        wallet: WalletAccountV2,
        chain_id: int,
        consensus: "V2ConsensusNode | None" = None,
    ):
        self.name = name
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem
        self.wallet = wallet
        self.chain_id = chain_id
        self.consensus = consensus

    @property
    def address(self) -> str:
        return self.wallet.address

    def attach_consensus(self, consensus: "V2ConsensusNode") -> None:
        self.consensus = consensus

    def submit_payment(
        self,
        recipient_addr: str,
        *,
        amount: int,
        fee: int = 0,
        expiry_height: int = 1_000_000,
        anti_spam_nonce: int | None = None,
        tx_time: int | None = None,
    ) -> SubmittedPayment:
        if self.consensus is None:
            raise ValueError("consensus_not_attached")
        submission, _, tx = self.wallet.build_payment_bundle(
            recipient_addr=recipient_addr,
            amount=amount,
            private_key_pem=self.private_key_pem,
            public_key_pem=self.public_key_pem,
            chain_id=self.chain_id,
            expiry_height=expiry_height,
            fee=fee,
            anti_spam_nonce=anti_spam_nonce,
            tx_time=tx_time,
        )
        self.consensus.submit_bundle(submission)
        return SubmittedPayment(
            sender_name=self.name,
            recipient_addr=recipient_addr,
            submission=submission,
            target_tx=tx,
        )

    def sync_receipts(self) -> tuple[ReceiptDeliveryResult, ...]:
        if self.consensus is None:
            raise ValueError("consensus_not_attached")
        return self.consensus.sync_wallet_receipts(self.address)

    def export_transfer_package(self, target_tx: OffChainTx, target_value: ValueRange) -> TransferPackage:
        return self.wallet.export_transfer_package(target_tx, target_value)

    def deliver_outgoing_transfer(
        self,
        target_tx: OffChainTx,
        target_value: ValueRange,
        *,
        recipient_addr: str | None = None,
        trusted_checkpoints=(),
    ) -> TransferDeliveryResult:
        if self.consensus is None:
            raise ValueError("consensus_not_attached")
        package = self.export_transfer_package(target_tx, target_value)
        return self.consensus.deliver_transfer_package(
            package,
            recipient_addr=recipient_addr,
            trusted_checkpoints=trusted_checkpoints,
        )

    def receive_transfer_package(
        self,
        package: TransferPackage,
        *,
        trusted_checkpoints=(),
    ) -> TransferDeliveryResult:
        if self.consensus is None:
            raise ValueError("consensus_not_attached")
        return self.consensus.deliver_transfer_package(
            package,
            recipient_addr=self.address,
            trusted_checkpoints=trusted_checkpoints,
        )

    def close(self) -> None:
        self.wallet.close()


LocalParticipant = V2AccountNode


class V2ConsensusNode:
    def __init__(
        self,
        *,
        store_path: str,
        chain_id: int = 1,
        receipt_cache_blocks: int = 32,
        auto_confirm_registered_wallets: bool = True,
        genesis_block_hash: bytes = ZERO_HASH32,
    ):
        self.store = ConsensusStateStore(store_path)
        metadata = self.store.load_metadata()
        self.runtime = V2Runtime(
            chain=self.store.load_chain_state(
                version=2,
                chain_id=chain_id,
                receipt_cache_blocks=receipt_cache_blocks,
                genesis_block_hash=genesis_block_hash,
            ),
            auto_confirm_registered_wallets=auto_confirm_registered_wallets,
        )
        for owner_addr, values in self.store.list_genesis_allocations().items():
            for value in values:
                self.runtime.register_genesis_allocation(owner_addr, value)
        self.genesis_block_hash = metadata.genesis_block_hash if metadata is not None else genesis_block_hash

    @property
    def chain(self):
        return self.runtime.chain

    def close(self) -> None:
        self.store.close()

    def register_wallet(
        self,
        wallet: WalletAccountV2,
        auto_confirm_receipts: bool | None = None,
    ) -> None:
        self.runtime.register_wallet(wallet, auto_confirm_receipts=auto_confirm_receipts)

    def unregister_wallet(self, sender_addr: str) -> None:
        self.runtime.unregister_wallet(sender_addr)

    def register_genesis_allocation(self, owner_addr: str, value: ValueRange) -> None:
        self.store.save_genesis_allocation(owner_addr, value)
        self.runtime.register_genesis_allocation(owner_addr, value)

    def submit_bundle(self, submission: BundleSubmission) -> BundleSubmitResult:
        return self.runtime.submit_bundle(submission)

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
        self.store.save_applied_block(
            block,
            receipts,
            version=self.chain.version,
            chain_id=self.chain.chain_id,
            receipt_cache_blocks=self.chain.receipt_cache.max_blocks,
            genesis_block_hash=self.genesis_block_hash,
        )
        deliveries = self.runtime.deliver_receipts(receipts)
        return ProduceBlockResult(block=block, receipts=receipts, deliveries=deliveries)

    def apply_block(self, block: BlockV2) -> ApplyBlockResult:
        receipts = self.chain.apply_block(block)
        self.store.save_applied_block(
            block,
            receipts,
            version=self.chain.version,
            chain_id=self.chain.chain_id,
            receipt_cache_blocks=self.chain.receipt_cache.max_blocks,
            genesis_block_hash=self.genesis_block_hash,
        )
        deliveries = self.runtime.deliver_receipts(receipts)
        return ApplyBlockResult(block=block, receipts=receipts, deliveries=deliveries)

    def get_receipt(self, sender_addr: str, seq: int):
        response = self.runtime.get_receipt(sender_addr, seq)
        if response.receipt is not None:
            return response
        return self.store.get_receipt(sender_addr, seq)

    def get_receipt_by_ref(self, bundle_ref):
        response = self.runtime.get_receipt_by_ref(bundle_ref)
        if response.receipt is not None:
            return response
        return self.store.get_receipt_by_ref(bundle_ref)

    def sync_wallet_receipts(self, sender_addr: str) -> tuple[ReceiptDeliveryResult, ...]:
        return self.runtime.sync_wallet_receipts(sender_addr)

    def deliver_transfer_package(
        self,
        package: TransferPackage,
        recipient_addr: str | None = None,
        trusted_checkpoints=(),
    ) -> TransferDeliveryResult:
        return self.runtime.deliver_transfer_package(
            package,
            recipient_addr=recipient_addr,
            trusted_checkpoints=trusted_checkpoints,
        )


class V2LocalNetwork:
    def __init__(
        self,
        *,
        root_dir: str,
        chain_id: int = 1,
        receipt_cache_blocks: int = 32,
        auto_confirm_registered_wallets: bool = True,
        genesis_block_hash: bytes = ZERO_HASH32,
    ):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.chain_id = chain_id
        self.receipt_cache_blocks = receipt_cache_blocks
        self.auto_confirm_registered_wallets = auto_confirm_registered_wallets
        self.genesis_block_hash = genesis_block_hash
        self.consensus_store_path = str(self.root_dir / "consensus.sqlite3")
        self.consensus = V2ConsensusNode(
            store_path=self.consensus_store_path,
            chain_id=chain_id,
            receipt_cache_blocks=receipt_cache_blocks,
            auto_confirm_registered_wallets=auto_confirm_registered_wallets,
            genesis_block_hash=genesis_block_hash,
        )
        self.participants: dict[str, V2AccountNode] = {}

    def close(self) -> None:
        for participant in self.participants.values():
            participant.close()
        self.consensus.close()

    def restart_consensus(self) -> None:
        self.consensus.close()
        self.consensus = V2ConsensusNode(
            store_path=self.consensus_store_path,
            chain_id=self.chain_id,
            receipt_cache_blocks=self.receipt_cache_blocks,
            auto_confirm_registered_wallets=self.auto_confirm_registered_wallets,
            genesis_block_hash=self.genesis_block_hash,
        )
        for participant in self.participants.values():
            participant.attach_consensus(self.consensus)
            self.consensus.register_wallet(participant.wallet)

    def add_account(
        self,
        name: str,
        *,
        private_key_pem: bytes | None = None,
        public_key_pem: bytes | None = None,
        auto_confirm_receipts: bool | None = None,
    ) -> V2AccountNode:
        if name in self.participants:
            raise ValueError("participant already exists")
        if private_key_pem is None or public_key_pem is None:
            private_key_pem, public_key_pem = generate_secp256k1_keypair()
        address = address_from_public_key_pem(public_key_pem)
        wallet = WalletAccountV2(
            address=address,
            genesis_block_hash=self.genesis_block_hash,
            db_path=str(self.root_dir / f"{name}.sqlite3"),
        )
        participant = V2AccountNode(
            name=name,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            wallet=wallet,
            chain_id=self.chain_id,
            consensus=self.consensus,
        )
        self.participants[name] = participant
        self.consensus.register_wallet(wallet, auto_confirm_receipts=auto_confirm_receipts)
        return participant

    def participant(self, name: str) -> V2AccountNode:
        try:
            return self.participants[name]
        except KeyError as exc:
            raise ValueError("unknown participant") from exc

    def allocate_genesis_value(self, name: str, value: ValueRange):
        participant = self.participant(name)
        record = participant.wallet.add_genesis_value(value)
        self.consensus.register_genesis_allocation(participant.address, value)
        return record

    def submit_payment(
        self,
        sender_name: str,
        recipient: str,
        *,
        amount: int,
        fee: int = 0,
        expiry_height: int = 1_000_000,
        anti_spam_nonce: int | None = None,
        tx_time: int | None = None,
    ) -> SubmittedPayment:
        sender = self.participant(sender_name)
        recipient_addr = self.resolve_address(recipient)
        return sender.submit_payment(
            recipient_addr,
            amount=amount,
            fee=fee,
            expiry_height=expiry_height,
            anti_spam_nonce=anti_spam_nonce,
            tx_time=tx_time,
        )

    def produce_block(
        self,
        *,
        timestamp: int | None = None,
        proposer_sig: bytes = b"",
        consensus_extra: bytes = b"",
        limit: int | None = None,
    ) -> ProduceBlockResult:
        return self.consensus.produce_block(
            timestamp=timestamp,
            proposer_sig=proposer_sig,
            consensus_extra=consensus_extra,
            limit=limit,
        )

    def resolve_address(self, participant_or_addr: str) -> str:
        participant = self.participants.get(participant_or_addr)
        if participant is not None:
            return participant.address
        return participant_or_addr

    def deliver_payment(
        self,
        sender_name: str,
        target_tx: OffChainTx,
        target_value: ValueRange,
        *,
        recipient: str | None = None,
        trusted_checkpoints=(),
    ) -> TransferDeliveryResult:
        sender = self.participant(sender_name)
        return sender.deliver_outgoing_transfer(
            target_tx,
            target_value,
            recipient_addr=None if recipient is None else self.resolve_address(recipient),
            trusted_checkpoints=trusted_checkpoints,
        )


__all__ = [
    "LocalParticipant",
    "SubmittedPayment",
    "V2AccountNode",
    "V2ConsensusNode",
    "V2LocalNetwork",
]
