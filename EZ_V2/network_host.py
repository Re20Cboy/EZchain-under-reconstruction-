from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .consensus import (
    ConsensusCore,
    ConsensusValidator,
    Proposal,
    QC,
    ValidatorSet,
    Vote,
    VotePhase,
    build_signed_proposer_claim,
    qc_hash,
    select_best_proposer,
    verify_signed_proposer_claim,
)
from .consensus.store import SQLiteConsensusStore
from .crypto import derive_secp256k1_keypair_from_mnemonic, generate_secp256k1_keypair, keccak256
from .localnet import V2ConsensusNode
from .networking import (
    MSG_BLOCK_ANNOUNCE,
    MSG_BLOCK_FETCH_REQ,
    MSG_BLOCK_FETCH_RESP,
    MSG_BUNDLE_ACK,
    MSG_BUNDLE_REJECT,
    MSG_BUNDLE_SUBMIT,
    MSG_CONSENSUS_BUNDLE_FORWARD,
    MSG_CHAIN_STATE_REQ,
    MSG_CHAIN_STATE_RESP,
    MSG_GENESIS_ALLOCATIONS_REQ,
    MSG_CONSENSUS_FINALIZE,
    MSG_CONSENSUS_PROPOSAL,
    MSG_CONSENSUS_SORTITION_CLAIM,
    MSG_CONSENSUS_TIMEOUT_CERT,
    MSG_CONSENSUS_TIMEOUT_VOTE,
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
from .types import BlockV2, BundleSubmission, CheckpointAnchor, GenesisAnchor, OffChainTx, PriorWitnessLink
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
    applied_genesis_values: int
    applied_receipts: int
    fetched_blocks: tuple[BlockV2, ...]
    pending_bundle_count: int
    receipt_count: int


@dataclass(frozen=True, slots=True)
class ConsensusRuntimeSnapshot:
    node_id: str
    consensus_mode: str
    chain_height: int
    chain_block_hash_hex: str
    current_round: int | None
    highest_qc_round: int | None
    highest_qc_phase: str | None
    locked_qc_round: int | None
    highest_tc_round: int | None
    last_decided_round: int | None
    pending_preview_count: int


@dataclass(frozen=True, slots=True)
class BlockSyncResult:
    applied_heights: tuple[int, ...]
    latest_height: int
    latest_block_hash_hex: str


@dataclass(slots=True)
class PendingConsensusPreview:
    block: BlockV2
    sender_peer_ids: dict[str, str]


def _mvp_consensus_keypair(*, validator_id: str, chain_id: int, epoch_id: int, purpose: str) -> tuple[bytes, bytes]:
    return derive_secp256k1_keypair_from_mnemonic(
        f"ezchain-v2-{purpose}-{validator_id}",
        passphrase=f"chain:{chain_id}:epoch:{epoch_id}",
    )


def _build_mvp_validator_set(*, validator_ids: tuple[str, ...], chain_id: int, epoch_id: int) -> ValidatorSet:
    return ValidatorSet.from_validators(
        tuple(
            ConsensusValidator(
                validator_id=validator_id,
                consensus_vote_pubkey=_mvp_consensus_keypair(
                    validator_id=validator_id,
                    chain_id=chain_id,
                    epoch_id=epoch_id,
                    purpose="consensus-vote",
                )[1],
                vrf_pubkey=_mvp_consensus_keypair(
                    validator_id=validator_id,
                    chain_id=chain_id,
                    epoch_id=epoch_id,
                    purpose="consensus-vrf",
                )[1],
            )
            for validator_id in validator_ids
        )
    )


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
        consensus_mode: str = "legacy",
        consensus_validator_ids: tuple[str, ...] | None = None,
        auto_run_mvp_consensus: bool = False,
    ):
        self.network = network
        self.peer = PeerInfo(node_id=node_id, role="consensus", endpoint=endpoint)
        self.consensus = V2ConsensusNode(store_path=store_path, chain_id=chain_id)
        self.auto_dispatch_receipts = auto_dispatch_receipts
        self.auto_announce_blocks = auto_announce_blocks
        self.adapter = adapter or LocalCommitAdapter(self.consensus)
        self.consensus_mode = str(consensus_mode)
        self.auto_run_mvp_consensus = bool(auto_run_mvp_consensus)
        self.fetched_blocks: dict[int, BlockV2] = {}
        self.fetched_blocks_by_hash: dict[str, BlockV2] = {}
        self._pending_previews: dict[str, PendingConsensusPreview] = {}
        self._mvp_sortition_claims: dict[tuple[int, int, bytes], Any] = {}
        self._consensus_core: ConsensusCore | None = None
        self._consensus_store: SQLiteConsensusStore | None = None
        self._consensus_validator_ids: tuple[str, ...] = tuple()
        self._consensus_epoch_id = 0
        self._consensus_vrf_private_key_pem: bytes | None = None
        if self.consensus_mode == "mvp":
            validator_ids = tuple(consensus_validator_ids or (node_id,))
            self._consensus_validator_ids = validator_ids
            validator_set = _build_mvp_validator_set(
                validator_ids=validator_ids,
                chain_id=chain_id,
                epoch_id=self._consensus_epoch_id,
            )
            self._consensus_vrf_private_key_pem, _ = _mvp_consensus_keypair(
                validator_id=node_id,
                chain_id=chain_id,
                epoch_id=self._consensus_epoch_id,
                purpose="consensus-vrf",
            )
            consensus_state_path = str(Path(store_path).with_name(Path(store_path).stem + ".mvp_consensus.sqlite3"))
            self._consensus_store = SQLiteConsensusStore(consensus_state_path)
            self._consensus_core = ConsensusCore(
                chain_id=chain_id,
                epoch_id=self._consensus_epoch_id,
                local_validator_id=node_id,
                validator_set=validator_set,
                store=self._consensus_store,
            )
        self.network.register(self.peer, self.handle_envelope)
        self.validate_runtime_state()

    def close(self) -> None:
        try:
            self.consensus.close()
        finally:
            if self._consensus_store is not None:
                self._consensus_store.close()

    def register_genesis_value(self, owner_addr: str, value: ValueRange) -> None:
        self.consensus.register_genesis_allocation(owner_addr, value)

    def chain_cursor(self) -> ChainSyncCursor:
        return ChainSyncCursor(
            height=self.consensus.chain.current_height,
            block_hash_hex=self.consensus.chain.current_block_hash.hex(),
        )

    def consensus_runtime_snapshot(self) -> ConsensusRuntimeSnapshot:
        highest_qc = None if self._consensus_core is None else self._consensus_core.highest_qc
        locked_qc = None if self._consensus_core is None else self._consensus_core.locked_qc
        pacemaker = None if self._consensus_core is None else self._consensus_core.pacemaker
        return ConsensusRuntimeSnapshot(
            node_id=self.peer.node_id,
            consensus_mode=self.consensus_mode,
            chain_height=self.consensus.chain.current_height,
            chain_block_hash_hex=self.consensus.chain.current_block_hash.hex(),
            current_round=None if pacemaker is None else pacemaker.current_round,
            highest_qc_round=None if highest_qc is None else highest_qc.round,
            highest_qc_phase=None if highest_qc is None else highest_qc.phase.value,
            locked_qc_round=None if locked_qc is None else locked_qc.round,
            highest_tc_round=None if pacemaker is None else pacemaker.highest_tc_round,
            last_decided_round=None if pacemaker is None else pacemaker.last_decided_round,
            pending_preview_count=len(self._pending_previews),
        )

    def validate_runtime_state(self) -> ConsensusRuntimeSnapshot:
        snapshot = self.consensus_runtime_snapshot()
        if snapshot.chain_height < 0:
            raise ValueError("invalid_chain_height")
        if self.consensus_mode != "mvp":
            return snapshot
        if self._consensus_core is None:
            raise ValueError("missing_consensus_core")
        if snapshot.current_round is None or snapshot.current_round <= 0:
            raise ValueError("invalid_current_round")
        if snapshot.highest_qc_round is not None and snapshot.current_round <= snapshot.highest_qc_round:
            raise ValueError("current_round_not_ahead_of_highest_qc")
        if snapshot.highest_tc_round is not None and snapshot.current_round <= snapshot.highest_tc_round:
            raise ValueError("current_round_not_ahead_of_highest_tc")
        if (
            snapshot.highest_qc_round is not None
            and snapshot.locked_qc_round is not None
            and snapshot.locked_qc_round > snapshot.highest_qc_round
        ):
            raise ValueError("locked_qc_above_highest_qc")
        if (
            snapshot.last_decided_round is not None
            and snapshot.highest_qc_round is not None
            and snapshot.last_decided_round > snapshot.highest_qc_round
        ):
            raise ValueError("decided_round_above_highest_qc")
        return snapshot

    def produce_pending_block(self) -> BlockV2 | None:
        block = self.adapter.propose_block()
        if block is None:
            return None
        self._broadcast_block_announce(block)
        return block

    def handle_envelope(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        if envelope.msg_type == MSG_BUNDLE_SUBMIT:
            return self._on_bundle_submit(envelope)
        if envelope.msg_type == MSG_RECEIPT_REQ:
            return self._on_receipt_request(envelope)
        if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
            return self._on_block_fetch_request(envelope)
        if envelope.msg_type == MSG_BLOCK_FETCH_RESP:
            return self._on_block_fetch_response(envelope)
        if envelope.msg_type == MSG_BLOCK_ANNOUNCE:
            return self._on_block_announce(envelope)
        if envelope.msg_type == MSG_CHAIN_STATE_REQ:
            return self._on_chain_state_request(envelope)
        if envelope.msg_type == MSG_GENESIS_ALLOCATIONS_REQ:
            return self._on_genesis_allocations_request(envelope)
        if envelope.msg_type == MSG_CONSENSUS_PROPOSAL:
            return self._on_consensus_proposal(envelope)
        if envelope.msg_type == MSG_CONSENSUS_BUNDLE_FORWARD:
            return self._on_consensus_bundle_forward(envelope)
        if envelope.msg_type == MSG_CONSENSUS_SORTITION_CLAIM:
            return self._on_consensus_sortition_claim(envelope)
        if envelope.msg_type == MSG_CONSENSUS_TIMEOUT_VOTE:
            return self._on_consensus_timeout_vote(envelope)
        if envelope.msg_type == MSG_CONSENSUS_TIMEOUT_CERT:
            return self._on_consensus_timeout_cert(envelope)
        if envelope.msg_type == MSG_CONSENSUS_FINALIZE:
            return self._on_consensus_finalize(envelope)
        return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

    def _on_bundle_submit(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        submission = envelope.payload["submission"]
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BUNDLE_ACK,
                sender_id=self.peer.node_id,
                recipient_id=envelope.sender_id,
                request_id=envelope.request_id,
                payload={
                    "sender_addr": submission.sidecar.sender_addr,
                    "seq": submission.envelope.seq,
                    "bundle_hash": submission.envelope.bundle_hash.hex(),
                },
            )
        )
        if self.consensus_mode == "mvp":
            if self.auto_run_mvp_consensus:
                return self._auto_route_mvp_bundle(
                    submission=submission,
                    sender_peer_id=envelope.sender_id,
                )
            block = self._track_pending_mvp_bundle(submission=submission, sender_peer_id=envelope.sender_id)
            return {
                "ok": True,
                "status": "accepted_pending_consensus",
                "height": block.header.height,
                "block_hash": block.block_hash.hex(),
            }
        result = self.consensus.submit_bundle(submission)
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

    def _on_consensus_bundle_forward(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        submission = envelope.payload.get("submission")
        if not isinstance(submission, BundleSubmission):
            return {"ok": False, "error": "missing_submission"}
        ordered_ids_raw = envelope.payload.get("ordered_consensus_peer_ids", ())
        ordered_ids = tuple(str(item) for item in ordered_ids_raw if str(item))
        if not ordered_ids or ordered_ids[0] != self.peer.node_id:
            return {"ok": False, "error": "invalid_ordered_consensus_peer_ids"}
        sender_peer_id_raw = envelope.payload.get("sender_peer_id")
        sender_peer_id = str(sender_peer_id_raw) if sender_peer_id_raw else None
        block = self._track_pending_mvp_bundle(submission=submission, sender_peer_id=sender_peer_id)
        if not bool(envelope.payload.get("auto_commit", False)):
            return {
                "ok": True,
                "status": "accepted_pending_consensus",
                "forwarded": True,
                "height": block.header.height,
                "block_hash": block.block_hash.hex(),
            }
        round_result = self.run_mvp_consensus_round(consensus_peer_ids=ordered_ids)
        round_result["forwarded"] = True
        return round_result

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
        return {"ok": True, **payload}

    def _on_genesis_allocations_request(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        owner_addr = str(envelope.payload.get("owner_addr", "")).strip()
        if not owner_addr:
            return {"ok": False, "error": "owner_addr_required"}
        allocations = self.consensus.list_genesis_allocations(owner_addr)
        return {
            "ok": True,
            "owner_addr": owner_addr,
            "genesis_block_hash_hex": self.consensus.genesis_block_hash.hex(),
            "allocations": [value.to_canonical() for value in allocations],
        }

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

    def _on_block_fetch_response(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if envelope.payload.get("status") != "ok":
            return {
                "ok": envelope.payload.get("status") == "missing",
                "status": envelope.payload.get("status", "missing"),
            }
        block = envelope.payload.get("block")
        if not isinstance(block, BlockV2):
            return {"ok": False, "error": "missing_block"}
        self._remember_fetched_block(block)
        return {"ok": True, "height": block.header.height}

    def _on_block_announce(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        announced_height = int(envelope.payload["height"])
        announced_block = envelope.payload.get("block")
        if isinstance(announced_block, BlockV2):
            announced_block_hash = str(envelope.payload.get("block_hash", ""))
            if announced_block.header.height != announced_height:
                return {"ok": False, "error": "announced_block_height_mismatch"}
            if announced_block_hash and announced_block.block_hash.hex() != announced_block_hash:
                return {"ok": False, "error": "announced_block_hash_mismatch"}
            self._remember_fetched_block(announced_block)
        if announced_height <= self.consensus.chain.current_height:
            return {"ok": True, "status": "already_current"}
        try:
            sync_result = self._sync_announced_blocks(
                sender_id=envelope.sender_id,
                announced_height=announced_height,
                announced_block=announced_block if isinstance(announced_block, BlockV2) else None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        snapshot = self.validate_runtime_state()
        return {
            "ok": True,
            "status": "synced",
            "applied_heights": list(sync_result.applied_heights),
            "height": sync_result.latest_height,
            "block_hash": sync_result.latest_block_hash_hex,
            "runtime_snapshot": snapshot,
        }

    def _on_consensus_proposal(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        proposal = envelope.payload.get("proposal")
        block = envelope.payload.get("block")
        phase = envelope.payload.get("phase")
        justify_qc = envelope.payload.get("justify_qc")
        if not isinstance(proposal, Proposal):
            return {"ok": False, "error": "missing_proposal"}
        if not isinstance(block, BlockV2):
            return {"ok": False, "error": "missing_block"}
        if block.block_hash != proposal.block_hash:
            return {"ok": False, "error": "proposal_block_hash_mismatch"}
        if not isinstance(phase, VotePhase):
            return {"ok": False, "error": "missing_phase"}
        try:
            self.adapter.validate_proposal(block)
            vote = self._consensus_core.make_vote(proposal, justify_qc, phase=phase)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "vote": vote}

    def _on_consensus_finalize(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        block = envelope.payload.get("block")
        commit_qc = envelope.payload.get("commit_qc")
        if not isinstance(block, BlockV2):
            return {"ok": False, "error": "missing_block"}
        if not isinstance(commit_qc, QC) or commit_qc.phase is not VotePhase.COMMIT:
            return {"ok": False, "error": "missing_commit_qc"}
        snapshot = self._finalize_committed_block(block=block, commit_qc=commit_qc)
        return {
            "ok": True,
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
            "runtime_snapshot": snapshot,
        }

    def _on_consensus_sortition_claim(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None or self._consensus_vrf_private_key_pem is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        try:
            height = int(envelope.payload["height"])
            round = int(envelope.payload["round"])
            seed = bytes(envelope.payload["seed"])
        except Exception:
            return {"ok": False, "error": "missing_sortition_payload"}
        if len(seed) != 32:
            return {"ok": False, "error": "invalid_sortition_seed"}
        claim = self._build_mvp_sortition_claim(height=height, round=round, seed=seed)
        return {"ok": True, "claim": claim}

    def _on_consensus_timeout_vote(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        try:
            height = int(envelope.payload["height"])
            round = int(envelope.payload["round"])
        except Exception:
            return {"ok": False, "error": "missing_timeout_round"}
        timeout_vote = self._consensus_core.make_timeout_vote(height=height, round=round)
        return {"ok": True, "timeout_vote": timeout_vote}

    def _on_consensus_timeout_cert(self, envelope: NetworkEnvelope) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            return {"ok": False, "error": "consensus_mvp_disabled"}
        tc = envelope.payload.get("tc")
        if tc is None:
            return {"ok": False, "error": "missing_tc"}
        self._consensus_core.observe_tc(tc)
        return {
            "ok": True,
            "round": tc.round,
            "next_round": self._consensus_core.pacemaker.current_round,
        }

    def _track_pending_mvp_bundle(
        self,
        *,
        submission: BundleSubmission,
        sender_peer_id: str | None,
    ) -> BlockV2:
        self.consensus.submit_bundle(submission)
        block, _ = self.consensus.preview_block()
        preview = self._pending_previews.get(block.block_hash.hex())
        if preview is None:
            preview = PendingConsensusPreview(block=block, sender_peer_ids={})
            self._pending_previews[block.block_hash.hex()] = preview
        if sender_peer_id:
            preview.sender_peer_ids[submission.sidecar.sender_addr] = sender_peer_id
        return block

    def _auto_route_mvp_bundle(
        self,
        *,
        submission: BundleSubmission,
        sender_peer_id: str,
    ) -> dict[str, Any]:
        if self._consensus_core is None:
            raise ValueError("consensus_mvp_disabled")
        target_height = self.consensus.chain.current_height + 1
        target_round = max(1, self._consensus_core.pacemaker.current_round)
        seed = self._derive_mvp_sortition_seed(
            bundle_hash=submission.envelope.bundle_hash,
            height=target_height,
            round=target_round,
        )
        selection = self.select_mvp_proposer(
            consensus_peer_ids=self._consensus_validator_ids or (self.peer.node_id,),
            seed=seed,
            height=target_height,
            round=target_round,
        )
        winner_id = str(selection["selected_proposer_id"])
        ordered_ids = tuple(selection["ordered_consensus_peer_ids"])
        if winner_id == self.peer.node_id:
            self._track_pending_mvp_bundle(submission=submission, sender_peer_id=sender_peer_id)
            round_result = self.run_mvp_consensus_round(consensus_peer_ids=ordered_ids)
            round_result["selected_proposer_id"] = winner_id
            round_result["sortition_seed_hex"] = seed.hex()
            return round_result
        auto_commit = isinstance(self.network, StaticPeerNetwork)
        response = self.network.send(
            NetworkEnvelope(
                msg_type=MSG_CONSENSUS_BUNDLE_FORWARD,
                sender_id=self.peer.node_id,
                recipient_id=winner_id,
                payload={
                    "submission": submission,
                    "sender_peer_id": sender_peer_id,
                    "ordered_consensus_peer_ids": ordered_ids,
                    "sortition_seed": seed,
                    "auto_commit": auto_commit,
                },
            )
        )
        if not isinstance(response, dict):
            raise ValueError("missing_forward_response")
        response = dict(response)
        response["selected_proposer_id"] = winner_id
        response["sortition_seed_hex"] = seed.hex()
        return response

    def _derive_mvp_sortition_seed(self, *, bundle_hash: bytes, height: int, round: int) -> bytes:
        return keccak256(
            b"ezchain-v2-mvp-sortition-seed"
            + int(self.consensus.chain.chain_id).to_bytes(8, "big", signed=False)
            + int(height).to_bytes(8, "big", signed=False)
            + int(round).to_bytes(8, "big", signed=False)
            + bundle_hash
        )

    def run_mvp_consensus_round(
        self,
        *,
        consensus_peer_ids: tuple[str, ...],
        limit: int | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            raise ValueError("consensus_mvp_disabled")
        if not consensus_peer_ids or consensus_peer_ids[0] != self.peer.node_id:
            raise ValueError("local consensus host must be first proposer")
        block, _ = self.consensus.preview_block(timestamp=timestamp, limit=limit)
        preview = self._pending_previews.get(block.block_hash.hex())
        if preview is None:
            preview = PendingConsensusPreview(block=block, sender_peer_ids={})
            self._pending_previews[block.block_hash.hex()] = preview
        initial_justify_qc = self._consensus_core.highest_qc
        proposal = Proposal(
            chain_id=self.consensus.chain.chain_id,
            epoch_id=0,
            height=block.header.height,
            round=max(1, self._consensus_core.pacemaker.current_round),
            proposer_id=self.peer.node_id,
            validator_set_hash=self._consensus_core.validator_set.validator_set_hash,
            block_hash=block.block_hash,
            justify_qc_hash=None if initial_justify_qc is None else qc_hash(initial_justify_qc),
        )
        for peer_id in consensus_peer_ids[1:]:
            peer = self.network.peer_info(peer_id)
            if peer.role != "consensus":
                raise ValueError(f"peer_not_consensus:{peer_id}")
        prepare_qc = self._drive_phase_over_network(
            proposal=proposal,
            block=block,
            phase=VotePhase.PREPARE,
            proposal_justify_qc=initial_justify_qc,
            observed_qc=None,
            consensus_peer_ids=consensus_peer_ids,
        )
        precommit_qc = self._drive_phase_over_network(
            proposal=proposal,
            block=block,
            phase=VotePhase.PRECOMMIT,
            proposal_justify_qc=initial_justify_qc,
            observed_qc=prepare_qc,
            consensus_peer_ids=consensus_peer_ids,
        )
        commit_qc = self._drive_phase_over_network(
            proposal=proposal,
            block=block,
            phase=VotePhase.COMMIT,
            proposal_justify_qc=initial_justify_qc,
            observed_qc=precommit_qc,
            consensus_peer_ids=consensus_peer_ids,
        )
        self._finalize_local_mvp_commit(
            block=block,
            commit_qc=commit_qc,
            preview=preview,
            consensus_peer_ids=consensus_peer_ids,
        )
        self._pending_previews.pop(block.block_hash.hex(), None)
        snapshot = self.validate_runtime_state()
        return {
            "ok": True,
            "status": "committed",
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
            "prepare_qc_signers": prepare_qc.signers,
            "precommit_qc_signers": precommit_qc.signers,
            "commit_qc_signers": commit_qc.signers,
            "runtime_snapshot": snapshot,
        }

    def run_mvp_timeout_round(
        self,
        *,
        consensus_peer_ids: tuple[str, ...],
        height: int | None = None,
        round: int | None = None,
    ) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None:
            raise ValueError("consensus_mvp_disabled")
        if not consensus_peer_ids or consensus_peer_ids[0] != self.peer.node_id:
            raise ValueError("local consensus host must be first proposer")
        target_height = int(height) if height is not None else self.consensus.chain.current_height + 1
        target_round = int(round) if round is not None else max(1, self._consensus_core.pacemaker.current_round)
        local_timeout_vote = self._consensus_core.make_timeout_vote(height=target_height, round=target_round)
        timeout_votes = [local_timeout_vote]
        for peer_id in consensus_peer_ids[1:]:
            peer = self.network.peer_info(peer_id)
            if peer.role != "consensus":
                raise ValueError(f"peer_not_consensus:{peer_id}")
            response = self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_CONSENSUS_TIMEOUT_VOTE,
                    sender_id=self.peer.node_id,
                    recipient_id=peer_id,
                    payload={"height": target_height, "round": target_round},
                )
            )
            if not response or not response.get("ok"):
                raise ValueError(f"consensus_timeout_failed:{peer_id}")
            timeout_vote = response.get("timeout_vote")
            if timeout_vote is None:
                raise ValueError(f"missing_timeout_vote:{peer_id}")
            timeout_votes.append(timeout_vote)
        tc = None
        for timeout_vote in timeout_votes:
            maybe_tc = self._consensus_core.accept_timeout_vote(timeout_vote)
            if maybe_tc is not None:
                tc = maybe_tc
        if tc is None:
            raise ValueError("missing_tc")
        for peer_id in consensus_peer_ids[1:]:
            self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_CONSENSUS_TIMEOUT_CERT,
                    sender_id=self.peer.node_id,
                    recipient_id=peer_id,
                    payload={"tc": tc},
                )
            )
        snapshot = self.validate_runtime_state()
        return {
            "ok": True,
            "status": "timed_out",
            "height": target_height,
            "round": target_round,
            "next_round": self._consensus_core.pacemaker.current_round,
            "tc_signers": tc.signers,
            "high_qc_round": tc.high_qc_round,
            "runtime_snapshot": snapshot,
        }

    def select_mvp_proposer(
        self,
        *,
        consensus_peer_ids: tuple[str, ...],
        seed: bytes,
        height: int | None = None,
        round: int | None = None,
    ) -> dict[str, Any]:
        if self.consensus_mode != "mvp" or self._consensus_core is None or self._consensus_vrf_private_key_pem is None:
            raise ValueError("consensus_mvp_disabled")
        if len(seed) != 32:
            raise ValueError("seed must be 32 bytes")
        target_height = int(height) if height is not None else self.consensus.chain.current_height + 1
        target_round = int(round) if round is not None else max(1, self._consensus_core.pacemaker.current_round)
        local_claim = self._build_mvp_sortition_claim(height=target_height, round=target_round, seed=seed)
        claims = [local_claim]
        for peer_id in consensus_peer_ids:
            if peer_id == self.peer.node_id:
                continue
            peer = self.network.peer_info(peer_id)
            if peer.role != "consensus":
                raise ValueError(f"peer_not_consensus:{peer_id}")
            response = self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_CONSENSUS_SORTITION_CLAIM,
                    sender_id=self.peer.node_id,
                    recipient_id=peer_id,
                    payload={"height": target_height, "round": target_round, "seed": seed},
                )
            )
            if not response or not response.get("ok"):
                raise ValueError(f"sortition_claim_failed:{peer_id}")
            claim = response.get("claim")
            if claim is None:
                raise ValueError(f"missing_sortition_claim:{peer_id}")
            claims.append(claim)
        winner = select_best_proposer(
            claims,
            validator_set=self._consensus_core.validator_set,
            chain_id=self.consensus.chain.chain_id,
            epoch_id=self._consensus_epoch_id,
            height=target_height,
            round=target_round,
            seed=seed,
            verifier=verify_signed_proposer_claim,
        )
        if winner is None:
            raise ValueError("missing_valid_sortition_winner")
        ordered_peer_ids = (winner.validator_id, *tuple(peer_id for peer_id in consensus_peer_ids if peer_id != winner.validator_id))
        return {
            "selected_proposer_id": winner.validator_id,
            "ordered_consensus_peer_ids": ordered_peer_ids,
            "height": target_height,
            "round": target_round,
            "seed_hex": seed.hex(),
            "claims_total": len(claims),
        }

    def _build_mvp_sortition_claim(self, *, height: int, round: int, seed: bytes):
        if self._consensus_core is None or self._consensus_vrf_private_key_pem is None:
            raise ValueError("consensus_mvp_disabled")
        cache_key = (height, round, seed)
        cached = self._mvp_sortition_claims.get(cache_key)
        if cached is not None:
            return cached
        claim = build_signed_proposer_claim(
            chain_id=self.consensus.chain.chain_id,
            epoch_id=self._consensus_epoch_id,
            height=height,
            round=round,
            validator_id=self.peer.node_id,
            validator_set_hash=self._consensus_core.validator_set.validator_set_hash,
            seed=seed,
            private_key_pem=self._consensus_vrf_private_key_pem,
        )
        self._mvp_sortition_claims[cache_key] = claim
        return claim

    def _drive_phase_over_network(
        self,
        *,
        proposal: Proposal,
        block: BlockV2,
        phase: VotePhase,
        proposal_justify_qc: QC | None,
        observed_qc: QC | None,
        consensus_peer_ids: tuple[str, ...],
    ) -> QC:
        if self._consensus_core is None:
            raise ValueError("consensus_mvp_disabled")
        self._consensus_core.observe_qc(observed_qc)
        local_vote = self._consensus_core.make_vote(proposal, proposal_justify_qc, phase=phase)
        qc: QC | None = None
        for participant_id in consensus_peer_ids:
            if participant_id == self.peer.node_id:
                maybe_qc = self._consensus_core.accept_vote(local_vote)
                if maybe_qc is not None:
                    qc = maybe_qc
                break
        remote_votes: list[Vote] = []
        for peer_id in consensus_peer_ids[1:]:
            response = self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_CONSENSUS_PROPOSAL,
                    sender_id=self.peer.node_id,
                    recipient_id=peer_id,
                    payload={
                        "proposal": proposal,
                        "block": block,
                        "phase": phase,
                        "justify_qc": proposal_justify_qc,
                    },
                )
            )
            if not response or not response.get("ok"):
                raise ValueError(f"consensus_phase_failed:{phase.value}:{peer_id}")
            vote = response.get("vote")
            if not isinstance(vote, Vote):
                raise ValueError(f"missing_vote:{phase.value}:{peer_id}")
            remote_votes.append(vote)
        for vote in remote_votes:
            maybe_qc = self._consensus_core.accept_vote(vote)
            if maybe_qc is not None:
                qc = maybe_qc
        if qc is None:
            raise ValueError(f"missing_qc:{phase.value}")
        return qc

    def _dispatch_finalized_receipts(self, block: BlockV2, *, sender_peer_ids: dict[str, str]) -> None:
        for entry in block.diff_package.diff_entries:
            sender_peer_id = sender_peer_ids.get(entry.new_leaf.addr)
            if sender_peer_id is None:
                continue
            receipt = self.consensus.get_receipt(entry.new_leaf.addr, entry.bundle_envelope.seq).receipt
            if receipt is None:
                continue
            self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_RECEIPT_DELIVER,
                    sender_id=self.peer.node_id,
                    recipient_id=sender_peer_id,
                    payload={"receipt": receipt},
                )
            )

    def _remember_fetched_block(self, block: BlockV2) -> None:
        self.fetched_blocks[block.header.height] = block
        self.fetched_blocks_by_hash[block.block_hash.hex()] = block

    def _await_fetched_block(
        self,
        *,
        height: int | None = None,
        block_hash_hex: str | None = None,
        timeout_sec: float = 1.0,
    ) -> BlockV2 | None:
        deadline = time.time() + timeout_sec
        height = int(height) if height is not None else None
        block_hash_hex = str(block_hash_hex) if block_hash_hex is not None else None
        while time.time() < deadline:
            block = None
            if height is not None:
                block = self.fetched_blocks.get(height)
            elif block_hash_hex is not None:
                block = self.fetched_blocks_by_hash.get(block_hash_hex)
            if block is not None:
                return block
            time.sleep(0.01)
        if height is not None:
            return self.fetched_blocks.get(height)
        if block_hash_hex is not None:
            return self.fetched_blocks_by_hash.get(block_hash_hex)
        return None

    def _fetch_announced_block(self, *, sender_id: str, height: int) -> BlockV2:
        self.network.send(
            NetworkEnvelope(
                msg_type=MSG_BLOCK_FETCH_REQ,
                sender_id=self.peer.node_id,
                recipient_id=sender_id,
                payload={"height": height},
            )
        )
        block = self._await_fetched_block(height=height)
        if block is None:
            raise ValueError(f"missing_announced_block:{height}")
        return block

    def recover_chain_from_consensus_peers(self) -> tuple[int, ...]:
        peer_ids = tuple(
            peer.node_id
            for peer in self.network.list_peers(role="consensus")
            if peer.node_id != self.peer.node_id
        )
        if not peer_ids:
            return ()
        best_peer_id = None
        best_height = self.consensus.chain.current_height
        for peer_id in peer_ids:
            try:
                response = self.network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CHAIN_STATE_REQ,
                        sender_id=self.peer.node_id,
                        recipient_id=peer_id,
                        payload={},
                    )
                )
            except Exception:
                continue
            if not isinstance(response, dict) or not response.get("ok"):
                continue
            try:
                height = int(response.get("height", 0))
            except Exception:
                continue
            if height > best_height:
                best_height = height
                best_peer_id = peer_id
        if best_peer_id is None or best_height <= self.consensus.chain.current_height:
            return ()
        applied: list[int] = []
        for height in range(self.consensus.chain.current_height + 1, best_height + 1):
            block = None
            for peer_id in (best_peer_id, *tuple(pid for pid in peer_ids if pid != best_peer_id)):
                try:
                    self.network.send(
                        NetworkEnvelope(
                            msg_type=MSG_BLOCK_FETCH_REQ,
                            sender_id=self.peer.node_id,
                            recipient_id=peer_id,
                            payload={"height": height},
                        )
                    )
                except Exception:
                    continue
                block = self._await_fetched_block(height=height)
                if block is not None:
                    break
            if block is None:
                break
            self.adapter.validate_proposal(block)
            self.adapter.commit_block(block)
            applied.append(height)
        return tuple(applied)

    def _sync_announced_blocks(
        self,
        *,
        sender_id: str,
        announced_height: int,
        announced_block: BlockV2 | None = None,
    ) -> BlockSyncResult:
        applied: list[int] = []
        for height in range(self.consensus.chain.current_height + 1, announced_height + 1):
            if announced_block is not None and announced_block.header.height == height:
                block = announced_block
            else:
                block = self._fetch_announced_block(sender_id=sender_id, height=height)
            self.adapter.validate_proposal(block)
            self.adapter.commit_block(block)
            applied.append(height)
        return BlockSyncResult(
            applied_heights=tuple(applied),
            latest_height=self.consensus.chain.current_height,
            latest_block_hash_hex=self.consensus.chain.current_block_hash.hex(),
        )

    def _broadcast_block_announce(self, block: BlockV2) -> None:
        if not self.auto_announce_blocks:
            return
        payload = self._encode_block(block)
        self.network.broadcast(
            self.peer.node_id,
            MSG_BLOCK_ANNOUNCE,
            payload,
            role="consensus",
        )
        self.network.broadcast(
            self.peer.node_id,
            MSG_BLOCK_ANNOUNCE,
            payload,
            role="account",
        )

    def _finalize_committed_block(self, *, block: BlockV2, commit_qc: QC) -> ConsensusRuntimeSnapshot:
        if self._consensus_core is None:
            raise ValueError("consensus_mvp_disabled")
        self._consensus_core.observe_qc(commit_qc)
        self.adapter.validate_proposal(block)
        self.adapter.commit_block(block)
        return self.validate_runtime_state()

    def _finalize_local_mvp_commit(
        self,
        *,
        block: BlockV2,
        commit_qc: QC,
        preview: PendingConsensusPreview,
        consensus_peer_ids: tuple[str, ...],
    ) -> None:
        self._finalize_committed_block(block=block, commit_qc=commit_qc)
        self._dispatch_finalized_receipts(block, sender_peer_ids=preview.sender_peer_ids)
        self._broadcast_block_announce(block)
        for peer_id in consensus_peer_ids[1:]:
            self.network.send(
                NetworkEnvelope(
                    msg_type=MSG_CONSENSUS_FINALIZE,
                    sender_id=self.peer.node_id,
                    recipient_id=peer_id,
                    payload={"block": block, "commit_qc": commit_qc},
                )
            )

    @staticmethod
    def _encode_block(block: BlockV2) -> dict[str, Any]:
        return {
            "height": block.header.height,
            "block_hash": block.block_hash.hex(),
            "state_root": block.header.state_root.hex(),
            "block": block,
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
        consensus_peer_ids: tuple[str, ...] | None = None,
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
        self.consensus_peer_ids = self._normalize_consensus_peer_ids(consensus_peer_id, consensus_peer_ids)
        self.consensus_peer_id = self.consensus_peer_ids[0]
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

    def set_consensus_peer_id(self, consensus_peer_id: str) -> None:
        self.consensus_peer_ids = self._normalize_consensus_peer_ids(str(consensus_peer_id), self.consensus_peer_ids)
        self.consensus_peer_id = self.consensus_peer_ids[0]

    def set_consensus_peer_ids(self, consensus_peer_ids: tuple[str, ...] | list[str]) -> None:
        peer_ids = tuple(str(item) for item in consensus_peer_ids if str(item))
        if not peer_ids:
            raise ValueError("consensus_peer_ids required")
        self.consensus_peer_ids = self._normalize_consensus_peer_ids(peer_ids[0], peer_ids)
        self.consensus_peer_id = self.consensus_peer_ids[0]

    @staticmethod
    def _normalize_consensus_peer_ids(
        primary_peer_id: str,
        peer_ids: tuple[str, ...] | list[str] | None,
    ) -> tuple[str, ...]:
        ordered: list[str] = []
        for peer_id in (primary_peer_id, *(peer_ids or ())):
            peer_id = str(peer_id)
            if not peer_id or peer_id in ordered:
                continue
            ordered.append(peer_id)
        if not ordered:
            raise ValueError("consensus_peer_id required")
        return tuple(ordered)

    def _promote_consensus_peer(self, consensus_peer_id: str) -> None:
        self.set_consensus_peer_id(consensus_peer_id)

    def _send_to_consensus(self, msg_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        last_exc: Exception | None = None
        for peer_id in self.consensus_peer_ids:
            try:
                response = self.network.send(
                    NetworkEnvelope(
                        msg_type=msg_type,
                        sender_id=self.peer.node_id,
                        recipient_id=peer_id,
                        payload=payload,
                    )
                )
            except Exception as exc:
                last_exc = exc
                continue
            self._promote_consensus_peer(peer_id)
            return response
        if last_exc is not None:
            raise last_exc
        raise ValueError("consensus_peer_unavailable")

    def close(self) -> None:
        try:
            self._persist_network_state()
        finally:
            self.wallet.close()

    def register_genesis_value(self, value: ValueRange) -> None:
        self.wallet.add_genesis_value(value)

    def sync_genesis_allocations(self) -> int:
        response = self._send_to_consensus(MSG_GENESIS_ALLOCATIONS_REQ, {"owner_addr": self.address})
        if not isinstance(response, dict):
            raise ValueError("missing_genesis_allocations_response")
        if response.get("ok") is not True:
            raise ValueError(str(response.get("error", "genesis_allocations_request_failed")))
        owner_addr = str(response.get("owner_addr", "")).strip()
        if owner_addr != self.address:
            raise ValueError("genesis_allocation_owner_mismatch")
        applied = 0
        for item in response.get("allocations", ()):
            if not isinstance(item, dict):
                continue
            value = ValueRange(begin=int(item["begin"]), end=int(item["end"]))
            if self.wallet.has_genesis_value(value):
                continue
            self.wallet.add_genesis_value(value)
            applied += 1
        return applied

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

    def _await_fetched_block(
        self,
        *,
        height: int | None = None,
        block_hash_hex: str | None = None,
        timeout_sec: float = 1.0,
    ) -> BlockV2 | None:
        deadline = time.time() + timeout_sec
        height = int(height) if height is not None else None
        block_hash_hex = str(block_hash_hex) if block_hash_hex is not None else None
        while time.time() < deadline:
            block = None
            if height is not None:
                block = self.fetched_blocks.get(height)
            elif block_hash_hex is not None:
                block = self.fetched_blocks_by_hash.get(block_hash_hex)
            if block is not None:
                return block
            time.sleep(0.01)
        if height is not None:
            return self.fetched_blocks.get(height)
        if block_hash_hex is not None:
            return self.fetched_blocks_by_hash.get(block_hash_hex)
        return None

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
        response = self._send_to_consensus(MSG_BUNDLE_SUBMIT, {"submission": submission})
        if isinstance(response, dict) and response.get("ok") is False:
            raise ValueError(str(response.get("error", "bundle_submit_failed")))
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
            self._send_to_consensus(MSG_RECEIPT_REQ, {"sender_addr": self.address, "seq": pending.seq})
            if self._latest_receipt_for_seq(pending.seq) is not None:
                applied += 1
        return applied

    def recover_network_state(
        self,
        *,
        start_height: int | None = None,
        end_height: int | None = None,
    ) -> V2NetworkRecovery:
        applied_genesis_values = self.sync_genesis_allocations()
        applied_receipts = self.sync_pending_receipts()
        fetched_blocks = self.sync_chain_blocks(start_height=start_height, end_height=end_height)
        return V2NetworkRecovery(
            chain_cursor=self.last_seen_chain,
            applied_genesis_values=applied_genesis_values,
            applied_receipts=applied_receipts,
            fetched_blocks=fetched_blocks,
            pending_bundle_count=len(self.wallet.list_pending_bundles()),
            receipt_count=len(self.wallet.list_receipts()),
        )

    def refresh_chain_state(self) -> ChainSyncCursor | None:
        self._send_to_consensus(MSG_CHAIN_STATE_REQ, {})
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
        self._send_to_consensus(MSG_BLOCK_FETCH_REQ, payload)
        if height is not None:
            return self._await_fetched_block(height=int(height))
        return self._await_fetched_block(block_hash_hex=str(block_hash_hex))

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
    "BlockSyncResult",
    "ConsensusRuntimeSnapshot",
    "LocalCommitAdapter",
    "StaticPeerNetwork",
    "V2AccountHost",
    "V2ConsensusHost",
    "V2NetworkRecovery",
    "V2NetworkPayment",
    "open_static_network",
]
