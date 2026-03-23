from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from ..encoding import canonical_encode


def _require_hash32(name: str, value: bytes | None) -> None:
    if value is None:
        return
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{name} must be 32 bytes")


def _hash_with_domain(domain: bytes, payload: object) -> bytes:
    return hashlib.sha256(domain + canonical_encode(payload)).digest()


@dataclass(frozen=True, slots=True)
class ConsensusValidator:
    validator_id: str
    consensus_vote_pubkey: bytes
    vrf_pubkey: bytes
    weight: int = 1

    def __post_init__(self) -> None:
        if not self.validator_id:
            raise ValueError("validator_id must be set")
        if not self.consensus_vote_pubkey:
            raise ValueError("consensus_vote_pubkey must be set")
        if not self.vrf_pubkey:
            raise ValueError("vrf_pubkey must be set")
        if self.weight <= 0:
            raise ValueError("weight must be positive")

    def to_canonical(self) -> dict:
        return {
            "validator_id": self.validator_id,
            "consensus_vote_pubkey": self.consensus_vote_pubkey,
            "vrf_pubkey": self.vrf_pubkey,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class ConsensusGenesisConfig:
    chain_id: int
    epoch_id: int
    validators: tuple[ConsensusValidator, ...]

    def __post_init__(self) -> None:
        if self.chain_id < 0:
            raise ValueError("chain_id must be non-negative")
        if self.epoch_id < 0:
            raise ValueError("epoch_id must be non-negative")
        if not self.validators:
            raise ValueError("validators cannot be empty")

    def to_canonical(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "validators": self.validators,
        }


class VotePhase(Enum):
    PREPARE = "prepare"
    PRECOMMIT = "precommit"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class Proposal:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    proposer_id: str
    validator_set_hash: bytes
    block_hash: bytes
    justify_qc_hash: bytes | None = None

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid proposal numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.proposer_id:
            raise ValueError("proposer_id must be set")
        _require_hash32("validator_set_hash", self.validator_set_hash)
        _require_hash32("block_hash", self.block_hash)
        _require_hash32("justify_qc_hash", self.justify_qc_hash)

    def signing_payload(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "proposer_id": self.proposer_id,
            "validator_set_hash": self.validator_set_hash,
            "block_hash": self.block_hash,
            "justify_qc_hash": self.justify_qc_hash,
        }


@dataclass(frozen=True, slots=True)
class Vote:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    voter_id: str
    validator_set_hash: bytes
    block_hash: bytes
    phase: VotePhase

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid vote numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.voter_id:
            raise ValueError("voter_id must be set")
        _require_hash32("validator_set_hash", self.validator_set_hash)
        _require_hash32("block_hash", self.block_hash)

    def signing_payload(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "voter_id": self.voter_id,
            "validator_set_hash": self.validator_set_hash,
            "block_hash": self.block_hash,
            "phase": self.phase,
        }


@dataclass(frozen=True, slots=True)
class TimeoutVote:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    voter_id: str
    validator_set_hash: bytes
    high_qc_round: int | None = None
    high_qc_hash: bytes | None = None

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid timeout vote numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.voter_id:
            raise ValueError("voter_id must be set")
        if self.high_qc_round is not None and self.high_qc_round < 0:
            raise ValueError("high_qc_round must be non-negative")
        _require_hash32("validator_set_hash", self.validator_set_hash)
        _require_hash32("high_qc_hash", self.high_qc_hash)

    def signing_payload(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "voter_id": self.voter_id,
            "validator_set_hash": self.validator_set_hash,
            "high_qc_round": self.high_qc_round,
            "high_qc_hash": self.high_qc_hash,
        }


@dataclass(frozen=True, slots=True)
class QC:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    phase: VotePhase
    validator_set_hash: bytes
    block_hash: bytes
    signers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid qc numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.signers:
            raise ValueError("signers cannot be empty")
        if tuple(sorted(self.signers)) != self.signers:
            raise ValueError("signers must be sorted")
        if len(set(self.signers)) != len(self.signers):
            raise ValueError("signers cannot contain duplicates")
        _require_hash32("validator_set_hash", self.validator_set_hash)
        _require_hash32("block_hash", self.block_hash)

    def to_canonical(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "phase": self.phase,
            "validator_set_hash": self.validator_set_hash,
            "block_hash": self.block_hash,
            "signers": self.signers,
        }


@dataclass(frozen=True, slots=True)
class TC:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    validator_set_hash: bytes
    signers: tuple[str, ...]
    high_qc_round: int | None = None
    high_qc_hash: bytes | None = None

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid tc numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.signers:
            raise ValueError("signers cannot be empty")
        if tuple(sorted(self.signers)) != self.signers:
            raise ValueError("signers must be sorted")
        if len(set(self.signers)) != len(self.signers):
            raise ValueError("signers cannot contain duplicates")
        if self.high_qc_round is not None and self.high_qc_round < 0:
            raise ValueError("high_qc_round must be non-negative")
        _require_hash32("validator_set_hash", self.validator_set_hash)
        _require_hash32("high_qc_hash", self.high_qc_hash)

    def to_canonical(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "validator_set_hash": self.validator_set_hash,
            "signers": self.signers,
            "high_qc_round": self.high_qc_round,
            "high_qc_hash": self.high_qc_hash,
        }


def proposal_hash(proposal: Proposal) -> bytes:
    return _hash_with_domain(b"EZCHAIN_V2_PROPOSAL", proposal.signing_payload())


def vote_hash(vote: Vote) -> bytes:
    return _hash_with_domain(b"EZCHAIN_V2_VOTE", vote.signing_payload())


def timeout_vote_hash(timeout_vote: TimeoutVote) -> bytes:
    return _hash_with_domain(b"EZCHAIN_V2_TIMEOUT_VOTE", timeout_vote.signing_payload())


def qc_hash(qc: QC) -> bytes:
    return _hash_with_domain(b"EZCHAIN_V2_QC", qc)


def tc_hash(tc: TC) -> bytes:
    return _hash_with_domain(b"EZCHAIN_V2_TC", tc)
