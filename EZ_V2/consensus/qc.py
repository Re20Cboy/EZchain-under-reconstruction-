from __future__ import annotations

from dataclasses import dataclass, field

from .types import QC, TC, TimeoutVote, Vote
from .validator_set import ValidatorSet


@dataclass(slots=True)
class VoteCollector:
    _votes_by_target: dict[tuple[int, int, str, bytes], set[str]] = field(default_factory=dict)
    _vote_choice_by_signer: dict[tuple[int, int, str, str], bytes] = field(default_factory=dict)

    def add_vote(self, vote: Vote, validator_set: ValidatorSet) -> QC | None:
        if vote.validator_set_hash != validator_set.validator_set_hash:
            raise ValueError("vote validator_set_hash mismatch")
        if not validator_set.contains(vote.voter_id):
            raise ValueError("vote signer is not in validator set")
        signer_key = (vote.height, vote.round, vote.phase.value, vote.voter_id)
        existing = self._vote_choice_by_signer.get(signer_key)
        if existing is not None and existing != vote.block_hash:
            raise ValueError("conflicting vote from same signer")
        self._vote_choice_by_signer[signer_key] = vote.block_hash
        target_key = (vote.height, vote.round, vote.phase.value, vote.block_hash)
        signers = self._votes_by_target.setdefault(target_key, set())
        signers.add(vote.voter_id)
        if not validator_set.has_quorum(signers):
            return None
        return QC(
            chain_id=vote.chain_id,
            epoch_id=vote.epoch_id,
            height=vote.height,
            round=vote.round,
            phase=vote.phase,
            validator_set_hash=vote.validator_set_hash,
            block_hash=vote.block_hash,
            signers=tuple(sorted(signers)),
        )

    def _restore_vote(self, height: int, round_: int, phase: str, voter_id: str, block_hash: bytes) -> None:
        """Restore a vote record from persistent storage (used on restart)."""
        signer_key = (height, round_, phase, voter_id)
        self._vote_choice_by_signer[signer_key] = block_hash
        target_key = (height, round_, phase, block_hash)
        signers = self._votes_by_target.setdefault(target_key, set())
        signers.add(voter_id)


@dataclass(slots=True)
class TimeoutVoteCollector:
    _signers_by_round: dict[tuple[int, int], set[str]] = field(default_factory=dict)
    _timeout_choice_by_signer: dict[tuple[int, int, str], tuple[int | None, bytes | None]] = field(default_factory=dict)
    _highest_qc_by_round: dict[tuple[int, int], tuple[int | None, bytes | None]] = field(default_factory=dict)

    def add_timeout_vote(self, timeout_vote: TimeoutVote, validator_set: ValidatorSet) -> TC | None:
        if timeout_vote.validator_set_hash != validator_set.validator_set_hash:
            raise ValueError("timeout vote validator_set_hash mismatch")
        if not validator_set.contains(timeout_vote.voter_id):
            raise ValueError("timeout vote signer is not in validator set")
        signer_key = (timeout_vote.height, timeout_vote.round, timeout_vote.voter_id)
        vote_choice = (timeout_vote.high_qc_round, timeout_vote.high_qc_hash)
        existing = self._timeout_choice_by_signer.get(signer_key)
        if existing is not None and existing != vote_choice:
            raise ValueError("conflicting timeout vote from same signer")
        self._timeout_choice_by_signer[signer_key] = vote_choice

        round_key = (timeout_vote.height, timeout_vote.round)
        signers = self._signers_by_round.setdefault(round_key, set())
        signers.add(timeout_vote.voter_id)

        current_high_qc = self._highest_qc_by_round.get(round_key)
        candidate_high_qc = (timeout_vote.high_qc_round, timeout_vote.high_qc_hash)
        if current_high_qc is None or _is_higher_qc(candidate_high_qc, current_high_qc):
            self._highest_qc_by_round[round_key] = candidate_high_qc

        if not validator_set.has_quorum(signers):
            return None

        high_qc_round, high_qc_hash = self._highest_qc_by_round.get(round_key, (None, None))
        return TC(
            chain_id=timeout_vote.chain_id,
            epoch_id=timeout_vote.epoch_id,
            height=timeout_vote.height,
            round=timeout_vote.round,
            validator_set_hash=timeout_vote.validator_set_hash,
            signers=tuple(sorted(signers)),
            high_qc_round=high_qc_round,
            high_qc_hash=high_qc_hash,
        )

    def _restore_timeout(
        self, height: int, round_: int, voter_id: str, high_qc_round: int | None, high_qc_hash: bytes | None,
    ) -> None:
        """Restore a timeout vote record from persistent storage (used on restart)."""
        self._timeout_choice_by_signer[(height, round_, voter_id)] = (high_qc_round, high_qc_hash)
        self._signers_by_round.setdefault((height, round_), set()).add(voter_id)
        candidate = (high_qc_round, high_qc_hash)
        current = self._highest_qc_by_round.get((height, round_))
        if current is None or _is_higher_qc(candidate, current):
            self._highest_qc_by_round[(height, round_)] = candidate


def _is_higher_qc(candidate: tuple[int | None, bytes | None], current: tuple[int | None, bytes | None]) -> bool:
    candidate_round, candidate_hash = candidate
    current_round, current_hash = current
    normalized_candidate_round = -1 if candidate_round is None else candidate_round
    normalized_current_round = -1 if current_round is None else current_round
    if normalized_candidate_round != normalized_current_round:
        return normalized_candidate_round > normalized_current_round
    if candidate_hash is None:
        return False
    if current_hash is None:
        return True
    return candidate_hash > current_hash
