from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .crypto import generate_secp256k1_keypair, keccak256
from .localnet import V2ConsensusNode
from .networking import (
    MSG_BLOCK_ANNOUNCE,
    MSG_BLOCK_FETCH_REQ,
    MSG_BLOCK_FETCH_RESP,
    MSG_BUNDLE_ACK,
    MSG_BUNDLE_REJECT,
    MSG_BUNDLE_SUBMIT,
    MSG_CHAIN_STATE_REQ,
    MSG_CHAIN_STATE_RESP,
    MSG_RECEIPT_DELIVER,
    MSG_RECEIPT_REQ,
    MSG_RECEIPT_RESP,
    MSG_TRANSFER_PACKAGE_DELIVER,
    ChainSyncCursor,
    ConsensusAdapter,
    NetworkEnvelope,
    PeerInfo,
    TransferMailboxEvent,
)
from .runtime_v2 import V2Runtime
from .serde import dumps_json, loads_json
from .transport import transfer_package_hash
from .types import BlockV2, CheckpointAnchor, GenesisAnchor, OffChainTx, PriorWitnessLink
from .values import ValueRange
from .wallet import WalletAccountV2


class StaticPeerNetwork:
    def __init__(self):
        self._peers: dict[str, PeerInfo] = {}
        self._handlers: dict[str, Callable[[NetworkEnvelope], dict[str, Any] | None]] = {}

    def register(self, peer: PeerInfo, handler: Callable[[NetworkEnvelope], dict[str, Any] | None]) -> None:
        self._peers[peer.node_id] = peer
        self._handlers[peer.node_id] = handler

    def peer_info(self, node_id: str) -> PeerInfo:
        peer = self._peers.get(node_id)
        if peer is None:
            raise ValueError(f"unknown_peer:{node_id}")
        return peer

    def list_peers(self, role: str | None = None) -> tuple[PeerInfo, ...]:
        peers = tuple(self._peers.values())
        if role is None:
            return peers
        return tuple(peer for peer in peers if peer.role == role)

    def send(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        if envelope.recipient_id is None:
            raise ValueError("recipient_id required for direct send")
        handler = self._handlers.get(envelope.recipient_id)
        if handler is None:
            raise ValueError(f"missing_handler:{envelope.recipient_id}")
        return handler(envelope)

    def broadcast(self, sender_id: str, msg_type: str, payload: dict[str, Any], *, role: str | None = None) -> list[dict[str, Any] | None]:
        results: list[dict[str, Any] | None] = []
        for peer in self.list_peers(role=role):
            if peer.node_id == sender_id:
                continue
            results.append(
                self.send(
                    NetworkEnvelope(
                        msg_type=msg_type,
                        sender_id=sender_id,
                        recipient_id=peer.node_id,
                        payload=payload,
                    )
                )
            )
        return results


class LocalCommitAdapter:
    def __init__(self, consensus: V2ConsensusNode):
        self.consensus = consensus

    def propose_block(self, limit: int | None = None) -> BlockV2 | None:
        if not self.consensus.chain.bundle_pool.snapshot(limit=limit):
            return None
        produced = self.consensus.produce_block(limit=limit)
        return produced.block

    def validate_proposal(self, block: BlockV2) -> None:
        if block.header.chain_id != self.consensus.chain.chain_id:
            raise ValueError("unexpected_chain_id")

    def commit_block(self, block: BlockV2):
        if block.header.height <= self.consensus.chain.current_height:
            return None
        return self.consensus.apply_block(block)

    def finality_event(self, block: BlockV2) -> dict[str, Any]:
        return {
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
            "state_root": block.header.state_root.hex(),
        }


@dataclass(frozen=True, slots=True)
class V2NetworkPayment:
    tx_hash_hex: str
    submit_hash_hex: str
    sender_addr: str
    recipient_addr: str
    amount: int
    receipt_height: int | None
    receipt_block_hash_hex: str | None


@dataclass(frozen=True, slots=True)
class V2NetworkRecovery:
    chain_cursor: ChainSyncCursor | None
    applied_receipts: int
    fetched_blocks: tuple[BlockV2, ...]
    pending_bundle_count: int
    receipt_count: int


class V2ConsensusHost:
    def __init__(
        self,
        *,
        node_id: str,
        endpoint: str,
        store_path: str,
        network: StaticPeerNetwork,
        chain_id: int = 1,
        auto_dispatch_receipts: bool = True,
        auto_announce_blocks: bool = True,
        adapter: ConsensusAdapter | None = None,
    ):
        self.network = network
        self.peer = PeerInfo(node_id=node_id, role="consensus", endpoint=endpoint)
        self.consensus = V2ConsensusNode(store_path=store_path, chain_id=chain_id)
        self.auto_dispatch_receipts = auto_dispatch_receipts
        self.auto_announce_blocks = auto_announce_blocks
        self.adapter = adapter or LocalCommitAdapter(self.consensus)
        self.network.register(self.peer, self.handle_envelope)

    def close(self) -> None:
        self.consensus.close()

    def register_genesis_value(self, owner_addr: str, value: ValueRange) -> None:
        self.consensus.register_genesis_allocation(owner_addr, value)

    def chain_cursor(self) -> ChainSyncCursor:
        return ChainSyncCursor(
            height=self.consensus.chain.current_height,
            block_hash_hex=self.consensus.chain.current_block_hash.hex(),
        )

    def produce_pending_block(self) -> BlockV2 | None:
        block = self.adapter.propose_block()
        if block is None:
            return None
        if self.auto_announce_blocks:
            self.network.broadcast(
                self.peer.node_id,
                MSG_BLOCK_ANNOUNCE,
                self._encode_block(block),
                role="account",
            )
        return block

    def handle_envelope(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        if envelope.msg_type == MSG_BUNDLE_SUBMIT:
            return self._on_bundle_submit(envelope)
        if envelope.msg_type == MSG_RECEIPT_REQ:
            return self._on_receipt_request(envelope)
        if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
            return self._on_block_fetch_request(envelope)
        if envelope.msg_type == MSG_CHAIN_STATE_REQ:
            return self._on_chain_state_request(envelope)
        return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

    def _on_bundle_submit(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        submission = envelope.payload["submission"]
        result = self.consensus.submit_bundle(submission)
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BUNDLE_ACK,
                sender_id=self.peer.node_id,
                recipient_id=envelope.sender_id,
                request_id=envelope.request_id,
                payload={
                    "sender_addr": result.sender_addr,
                    "seq": result.seq,
                    "bundle_hash": result.bundle_hash.hex(),
                },
            )
        )
        block = self.produce_pending_block()
        if block is None:
            return {"ok": True, "status": "accepted_no_block"}
        if self.auto_dispatch_receipts:
            receipt = self.consensus.get_receipt(result.sender_addr, result.seq).receipt
            if receipt is not None:
                self.network.send(
                    NetworkEnvelope(
                        msg_type=MSG_RECEIPT_DELIVER,
                        sender_id=self.peer.node_id,
                        recipient_id=envelope.sender_id,
                        payload={"receipt": receipt},
                    )
                )
        return {
            "ok": True,
            "status": "accepted",
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
        }

    def _on_receipt_request(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        sender_addr = str(envelope.payload["sender_addr"])
        seq = int(envelope.payload["seq"])
        response = self.consensus.get_receipt(sender_addr, seq)
        receipt = response.receipt
        payload: dict[str, Any] = {"status": response.status, "sender_addr": sender_addr, "seq": seq}
        if receipt is not None:
            payload["receipt"] = receipt
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_RECEIPT_RESP,
                sender_id=self.peer.node_id,
                recipient_id=envelope.sender_id,
                request_id=envelope.request_id,
                payload=payload,
            )
        )
        return {"ok": True, "status": response.status}

    def _on_chain_state_request(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        cursor = self.chain_cursor()
        payload = {
            "height": cursor.height,
            "block_hash_hex": cursor.block_hash_hex,
        }
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_CHAIN_STATE_RESP,
                sender_id=self.peer.node_id,
                recipient_id=envelope.sender_id,
                request_id=envelope.request_id,
                payload=payload,
            )
        )
        return {"ok": True}

    def _on_block_fetch_request(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        payload = envelope.payload
        block = None
        if "height" in payload:
            block = self.consensus.store.get_block_by_height(int(payload["height"]))
        elif "block_hash_hex" in payload:
            block = self.consensus.store.get_block_by_hash(bytes.fromhex(str(payload["block_hash_hex"])))
        else:
            self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_BLOCK_FETCH_RESP,
                    sender_id=self.peer.node_id,
                    recipient_id=envelope.sender_id,
                    request_id=envelope.request_id,
                    payload={"status": "error", "error": "missing_block_selector"},
                )
            )
            return {"ok": False, "error": "missing_block_selector"}

        response_payload: dict[str, Any] = {"status": "ok" if block is not None else "missing"}
        if block is not None:
            response_payload["block"] = block
            response_payload["height"] = block.header.height
            response_payload["block_hash_hex"] = block.block_hash.hex()
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BLOCK_FETCH_RESP,
                sender_id=self.peer.node_id,
                recipient_id=envelope.sender_id,
                request_id=envelope.request_id,
                payload=response_payload,
            )
        )
        return {"ok": True, "status": response_payload["status"]}

    @staticmethod
    def _encode_block(block: BlockV2) -> dict[str, Any]:
        return {
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
            "state_root": block.header.state_root.hex(),
        }


class V2AccountHost:
    def __init__(
        self,
        *,
        node_id: str,
        endpoint: str,
        wallet_db_path: str,
        chain_id: int,
        network: StaticPeerNetwork,
        consensus_peer_id: str,
        address: str | None = None,
        private_key_pem: bytes | None = None,
        public_key_pem: bytes | None = None,
        auto_accept_receipts: bool = True,
        state_path: str | None = None,
    ):
        if private_key_pem is None or public_key_pem is None:
            private_key_pem, public_key_pem = generate_secp256k1_keypair()
        if address is None:
            from .crypto import address_from_public_key_pem

            address = address_from_public_key_pem(public_key_pem)
        self.network = network
        self.consensus_peer_id = consensus_peer_id
        self.peer = PeerInfo(node_id=node_id, role="account", endpoint=endpoint, metadata={"address": address})
        self.wallet = WalletAccountV2(address=address, genesis_block_hash=b"\x00" * 32, db_path=wallet_db_path)
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem
        self.chain_id = chain_id
        self.auto_accept_receipts = auto_accept_receipts
        self.state_path = Path(state_path) if state_path else None
        self.last_seen_chain: ChainSyncCursor | None = None
        self.received_transfers: list[TransferMailboxEvent] = []
        self.fetched_blocks: dict[int, BlockV2] = {}
        self.fetched_blocks_by_hash: dict[str, BlockV2] = {}
        self._load_network_state()
        self.network.register(self.peer, self.handle_envelope)

    @property
    def address(self) -> str:
        return self.wallet.address

    def close(self) -> None:
        try:
            self._persist_network_state()
        finally:
            self.wallet.close()

    def register_genesis_value(self, value: ValueRange) -> None:
        self.wallet.add_genesis_value(value)

    def _load_network_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = loads_json(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        last_seen = payload.get("last_seen_chain")
        if isinstance(last_seen, ChainSyncCursor):
            self.last_seen_chain = last_seen
        fetched_blocks = payload.get("fetched_blocks", ())
        if not isinstance(fetched_blocks, (list, tuple)):
            fetched_blocks = ()
        for block in fetched_blocks:
            if isinstance(block, BlockV2):
                self.fetched_blocks[block.header.height] = block
                self.fetched_blocks_by_hash[block.block_hash.hex()] = block
        if self.last_seen_chain is None and self.fetched_blocks:
            latest_height = max(self.fetched_blocks)
            latest_block = self.fetched_blocks[latest_height]
            self.last_seen_chain = ChainSyncCursor(
                height=latest_height,
                block_hash_hex=latest_block.block_hash.hex(),
            )

    def _persist_network_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_seen_chain": self.last_seen_chain,
            "fetched_blocks": [self.fetched_blocks[height] for height in sorted(self.fetched_blocks)],
        }
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp_path.write_text(dumps_json(payload), encoding="utf-8")
        tmp_path.replace(self.state_path)

    def handle_envelope(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        if envelope.msg_type == MSG_BUNDLE_ACK:
            return {"ok": True}
        if envelope.msg_type == MSG_BUNDLE_REJECT:
            return {"ok": False, "error": envelope.payload.get("error", "bundle_rejected")}
        if envelope.msg_type in {MSG_RECEIPT_DELIVER, MSG_RECEIPT_RESP}:
            return self._on_receipt(envelope)
        if envelope.msg_type == MSG_TRANSFER_PACKAGE_DELIVER:
            return self._on_transfer_package(envelope)
        if envelope.msg_type == MSG_BLOCK_FETCH_RESP:
            return self._on_block_fetch_response(envelope)
        if envelope.msg_type == MSG_CHAIN_STATE_RESP:
            self.last_seen_chain = ChainSyncCursor(
                height=int(envelope.payload["height"]),
                block_hash_hex=str(envelope.payload.get("block_hash_hex", "")),
            )
            self._persist_network_state()
            return {"ok": True}
        if envelope.msg_type == MSG_BLOCK_ANNOUNCE:
            self.last_seen_chain = ChainSyncCursor(
                height=int(envelope.payload["height"]),
                block_hash_hex=str(envelope.payload.get("block_hash", "")),
            )
            self._persist_network_state()
            return {"ok": True}
        return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

    def submit_payment(
        self,
        recipient_peer_id: str,
        *,
        amount: int,
        expiry_height: int = 1_000_000,
        fee: int = 0,
        anti_spam_nonce: int | None = None,
        tx_time: int | None = None,
    ) -> V2NetworkPayment:
        recipient_peer = self.network.peer_info(recipient_peer_id)
        recipient_addr = str(recipient_peer.metadata["address"])
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
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BUNDLE_SUBMIT,
                sender_id=self.peer.node_id,
                recipient_id=self.consensus_peer_id,
                payload={"submission": submission},
            )
        )
        receipt = self._latest_receipt_for_seq(submission.envelope.seq)
        return V2NetworkPayment(
            tx_hash_hex=self._tx_hash_hex(tx),
            submit_hash_hex=submission.envelope.bundle_hash.hex(),
            sender_addr=self.address,
            recipient_addr=recipient_addr,
            amount=amount,
            receipt_height=receipt.header_lite.height if receipt is not None else None,
            receipt_block_hash_hex=receipt.header_lite.block_hash.hex() if receipt is not None else None,
        )

    def sync_pending_receipts(self) -> int:
        applied = 0
        for pending in self.wallet.list_pending_bundles():
            self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_RECEIPT_REQ,
                    sender_id=self.peer.node_id,
                    recipient_id=self.consensus_peer_id,
                    payload={"sender_addr": self.address, "seq": pending.seq},
                )
            )
            if self._latest_receipt_for_seq(pending.seq) is not None:
                applied += 1
        return applied

    def recover_network_state(
        self,
        *,
        start_height: int | None = None,
        end_height: int | None = None,
    ) -> V2NetworkRecovery:
        applied_receipts = self.sync_pending_receipts()
        fetched_blocks = self.sync_chain_blocks(start_height=start_height, end_height=end_height)
        return V2NetworkRecovery(
            chain_cursor=self.last_seen_chain,
            applied_receipts=applied_receipts,
            fetched_blocks=fetched_blocks,
            pending_bundle_count=len(self.wallet.list_pending_bundles()),
            receipt_count=len(self.wallet.list_receipts()),
        )

    def refresh_chain_state(self) -> ChainSyncCursor | None:
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_CHAIN_STATE_REQ,
                sender_id=self.peer.node_id,
                recipient_id=self.consensus_peer_id,
                payload={},
            )
        )
        return self.last_seen_chain

    def fetch_block(
        self,
        *,
        height: int | None = None,
        block_hash_hex: str | None = None,
    ) -> BlockV2 | None:
        if height is None and block_hash_hex is None:
            raise ValueError("height or block_hash_hex required")
        payload: dict[str, Any] = {}
        if height is not None:
            payload["height"] = int(height)
        if block_hash_hex is not None:
            payload["block_hash_hex"] = str(block_hash_hex)
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BLOCK_FETCH_REQ,
                sender_id=self.peer.node_id,
                recipient_id=self.consensus_peer_id,
                payload=payload,
            )
        )
        if height is not None:
            return self.fetched_blocks.get(int(height))
        return self.fetched_blocks_by_hash.get(str(block_hash_hex))

    def sync_chain_blocks(
        self,
        *,
        start_height: int | None = None,
        end_height: int | None = None,
    ) -> tuple[BlockV2, ...]:
        cursor = self.refresh_chain_state()
        remote_height = 0 if cursor is None else cursor.height
        target_height = remote_height if end_height is None else min(int(end_height), remote_height)
        if target_height <= 0:
            return ()
        next_height = max(self.fetched_blocks, default=0) + 1
        fetch_from = next_height if start_height is None else max(1, int(start_height))
        if fetch_from > target_height:
            return ()
        fetched: list[BlockV2] = []
        for height in range(fetch_from, target_height + 1):
            block = self.fetch_block(height=height)
            if block is not None:
                fetched.append(block)
        return tuple(fetched)

    def _on_receipt(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        receipt = envelope.payload.get("receipt")
        if receipt is None:
            return {"ok": False, "error": "missing_receipt"}
        if not self.auto_accept_receipts:
            return {"ok": True, "status": "receipt_seen_not_applied"}
        confirmed_unit = self.wallet.on_receipt_confirmed(receipt)
        for tx in confirmed_unit.bundle_sidecar.tx_list:
            for value in tx.value_list:
                package = self.wallet.export_transfer_package(tx, value)
                recipient_peer_id = self._find_peer_id_by_address(tx.recipient_addr)
                self.network.send(
                    NetworkEnvelope(
                        msg_type=MSG_TRANSFER_PACKAGE_DELIVER,
                        sender_id=self.peer.node_id,
                        recipient_id=recipient_peer_id,
                        payload={"package": package},
                    )
                )
        return {"ok": True, "seq": receipt.seq}

    def _on_transfer_package(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        package = envelope.payload["package"]
        try:
            validator = self._build_validator_for_package(package)
            record = self.wallet.receive_transfer(package, validator=validator)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        package_hash = transfer_package_hash(package)
        self.received_transfers.append(
            TransferMailboxEvent(
                package_hash_hex=package_hash.hex(),
                sender_addr=package.target_tx.sender_addr,
                recipient_addr=package.target_tx.recipient_addr,
                tx_hash_hex=self._tx_hash_hex(package.target_tx),
                value_begin=package.target_value.begin,
                value_end=package.target_value.end,
            )
        )
        return {"ok": True, "record_id": record.record_id}

    def _on_block_fetch_response(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if envelope.payload.get("status") != "ok":
            return {"ok": envelope.payload.get("status") == "missing", "status": envelope.payload.get("status", "missing")}
        block = envelope.payload.get("block")
        if not isinstance(block, BlockV2):
            return {"ok": False, "error": "missing_block"}
        self.fetched_blocks[block.header.height] = block
        self.fetched_blocks_by_hash[block.block_hash.hex()] = block
        if self.last_seen_chain is None or block.header.height >= self.last_seen_chain.height:
            self.last_seen_chain = ChainSyncCursor(
                height=block.header.height,
                block_hash_hex=block.block_hash.hex(),
            )
        self._persist_network_state()
        return {"ok": True, "height": block.header.height}

    def _latest_receipt_for_seq(self, seq: int):
        for receipt in self.wallet.list_receipts():
            if receipt.seq == seq:
                return receipt
        return None

    def _find_peer_id_by_address(self, address: str) -> str:
        for peer in self.network.list_peers(role="account"):
            if peer.metadata.get("address") == address:
                return peer.node_id
        raise ValueError(f"unknown_account_peer_for_address:{address}")

    def _build_validator_for_package(self, package) -> Any:
        runtime = V2Runtime()
        for owner_addr, value in self._extract_genesis_allocations(package.witness_v2.anchor):
            runtime.register_genesis_allocation(owner_addr, value)
        return runtime.build_validator()

    def _extract_genesis_allocations(self, anchor) -> tuple[tuple[str, ValueRange], ...]:
        allocations: list[tuple[str, ValueRange]] = []

        def _walk(node) -> None:
            if isinstance(node, GenesisAnchor):
                allocations.append(
                    (
                        node.first_owner_addr,
                        ValueRange(node.value_begin, node.value_end),
                    )
                )
                return
            if isinstance(node, PriorWitnessLink):
                _walk(node.prior_witness.anchor)
                return
            if isinstance(node, CheckpointAnchor):
                return

        _walk(anchor)
        return tuple(allocations)

    @staticmethod
    def _tx_hash_hex(tx: OffChainTx) -> str:
        return keccak256(repr(tx).encode("utf-8")).hex()


def open_static_network(root_dir: str, *, chain_id: int = 1):
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    network = StaticPeerNetwork()
    consensus = V2ConsensusHost(
        node_id="consensus-0",
        endpoint="mem://consensus-0",
        store_path=str(root / "consensus.sqlite3"),
        network=network,
        chain_id=chain_id,
    )
    return network, consensus


__all__ = [
    "LocalCommitAdapter",
    "StaticPeerNetwork",
    "V2AccountHost",
    "V2ConsensusHost",
    "V2NetworkRecovery",
    "V2NetworkPayment",
    "open_static_network",
]
