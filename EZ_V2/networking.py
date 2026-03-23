from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .types import BlockV2, BundleSubmission, Receipt, TransferPackage

NodeRole = Literal["consensus", "account", "observer"]

MSG_BUNDLE_SUBMIT = "bundle_submit"
MSG_BUNDLE_ACK = "bundle_ack"
MSG_BUNDLE_REJECT = "bundle_reject"
MSG_BLOCK_ANNOUNCE = "block_announce"
MSG_BLOCK_FETCH_REQ = "block_fetch_req"
MSG_BLOCK_FETCH_RESP = "block_fetch_resp"
MSG_CONSENSUS_BUNDLE_FORWARD = "consensus_bundle_forward"
MSG_CONSENSUS_FINALIZE = "consensus_finalize"
MSG_CONSENSUS_PROPOSAL = "consensus_proposal"
MSG_CONSENSUS_SORTITION_CLAIM = "consensus_sortition_claim"
MSG_CONSENSUS_TIMEOUT_CERT = "consensus_timeout_cert"
MSG_CONSENSUS_TIMEOUT_VOTE = "consensus_timeout_vote"
MSG_CONSENSUS_VOTE = "consensus_vote"
MSG_RECEIPT_DELIVER = "receipt_deliver"
MSG_RECEIPT_REQ = "receipt_req"
MSG_RECEIPT_RESP = "receipt_resp"
MSG_TRANSFER_PACKAGE_DELIVER = "transfer_package_deliver"
MSG_CHECKPOINT_REQ = "checkpoint_req"
MSG_CHECKPOINT_RESP = "checkpoint_resp"
MSG_CHAIN_STATE_REQ = "chain_state_req"
MSG_CHAIN_STATE_RESP = "chain_state_resp"
MSG_PEER_INFO = "peer_info"
MSG_PEER_HEALTH = "peer_health"


@dataclass(frozen=True, slots=True)
class PeerInfo:
    node_id: str
    role: NodeRole
    endpoint: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NetworkEnvelope:
    msg_type: str
    sender_id: str
    recipient_id: str | None
    payload: dict[str, Any]
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass(frozen=True, slots=True)
class ChainSyncCursor:
    height: int
    block_hash_hex: str = ""


@dataclass(frozen=True, slots=True)
class ReceiptSyncCursor:
    sender_addr: str
    next_seq: int


@dataclass(frozen=True, slots=True)
class TransferMailboxEvent:
    package_hash_hex: str
    sender_addr: str
    recipient_addr: str
    tx_hash_hex: str
    value_begin: int
    value_end: int


class ConsensusAdapter(Protocol):
    def propose_block(self, limit: int | None = None) -> BlockV2 | None:
        ...

    def validate_proposal(self, block: BlockV2) -> None:
        ...

    def commit_block(self, block: BlockV2):
        ...

    def finality_event(self, block: BlockV2) -> dict[str, Any]:
        ...


class EnvelopeHandler(Protocol):
    def __call__(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        ...


__all__ = [
    "ChainSyncCursor",
    "ConsensusAdapter",
    "EnvelopeHandler",
    "MSG_BLOCK_ANNOUNCE",
    "MSG_BLOCK_FETCH_REQ",
    "MSG_BLOCK_FETCH_RESP",
    "MSG_BUNDLE_ACK",
    "MSG_BUNDLE_REJECT",
    "MSG_BUNDLE_SUBMIT",
    "MSG_CONSENSUS_BUNDLE_FORWARD",
    "MSG_CONSENSUS_FINALIZE",
    "MSG_CONSENSUS_PROPOSAL",
    "MSG_CONSENSUS_SORTITION_CLAIM",
    "MSG_CONSENSUS_TIMEOUT_CERT",
    "MSG_CONSENSUS_TIMEOUT_VOTE",
    "MSG_CONSENSUS_VOTE",
    "MSG_CHAIN_STATE_REQ",
    "MSG_CHAIN_STATE_RESP",
    "MSG_CHECKPOINT_REQ",
    "MSG_CHECKPOINT_RESP",
    "MSG_PEER_HEALTH",
    "MSG_PEER_INFO",
    "MSG_RECEIPT_DELIVER",
    "MSG_RECEIPT_REQ",
    "MSG_RECEIPT_RESP",
    "MSG_TRANSFER_PACKAGE_DELIVER",
    "NetworkEnvelope",
    "NodeRole",
    "PeerInfo",
    "ReceiptSyncCursor",
    "TransferMailboxEvent",
]
