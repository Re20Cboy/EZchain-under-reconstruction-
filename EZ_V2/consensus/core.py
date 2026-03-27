from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field

from .pacemaker import PacemakerState
from .qc import TimeoutVoteCollector, VoteCollector
from .store import InMemoryConsensusStore, SQLiteConsensusStore
from .types import (
    Proposal,
    QC,
    TC,
    TimeoutVote,
    Vote,
    VotePhase,
    proposal_hash,
    qc_hash,
    tc_hash,
)
from .validator_set import ValidatorSet


@dataclass(slots=True)
class ConsensusCore:
    chain_id: int
    epoch_id: int
    local_validator_id: str
    validator_set: ValidatorSet
    store: InMemoryConsensusStore | SQLiteConsensusStore = field(default_factory=InMemoryConsensusStore)
    pacemaker: PacemakerState = field(default_factory=PacemakerState)
    vote_collector: VoteCollector = field(default_factory=VoteCollector)
    timeout_vote_collector: TimeoutVoteCollector = field(default_factory=TimeoutVoteCollector)
    _local_vote_choice: dict[tuple[int, int, str], bytes] = field(default_factory=dict)
    _local_timeout_rounds: set[tuple[int, int]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("chain_id and epoch_id must be non-negative")
        if not self.validator_set.contains(self.local_validator_id):
            raise ValueError("local_validator_id must be in validator set")
        persisted = self.store.load_persisted_state()
        self.pacemaker = persisted.pacemaker_state
        self.store.highest_qc = persisted.highest_qc
        self.store.locked_qc = persisted.locked_qc
        # Restore vote/timeout logs from persistent storage
        for h, r, phase, vid, bhash in self.store.load_vote_records():
            if vid == self.local_validator_id:
                self._local_vote_choice[(h, r, phase)] = bhash
            self.vote_collector._restore_vote(h, r, phase, vid, bhash)
        for h, r, vid, qc_r, qc_h in self.store.load_timeout_records():
            if vid == self.local_validator_id:
                self._local_timeout_rounds.add((h, r))
            self.timeout_vote_collector._restore_timeout(h, r, vid, qc_r, qc_h)

    @property
    def highest_qc(self) -> QC | None:
        return self.store.highest_qc

    @property
    def locked_qc(self) -> QC | None:
        return self.store.locked_qc

    def validate_proposal(self, proposal: Proposal, justify_qc: QC | None) -> None:
        self.observe_qc(justify_qc)
        if proposal.chain_id != self.chain_id or proposal.epoch_id != self.epoch_id:
            raise ValueError("proposal chain or epoch mismatch")
        if proposal.validator_set_hash != self.validator_set.validator_set_hash:
            raise ValueError("proposal validator_set_hash mismatch")
        if not self.validator_set.contains(proposal.proposer_id):
            raise ValueError("proposal proposer is not in validator set")
        # A local pacemaker may already move to next round after seeing a QC,
        # while the same round still finishes its later phases.
        if proposal.round + 1 < self.pacemaker.current_round:
            raise ValueError("proposal round is stale")
        if proposal.justify_qc_hash is not None:
            if justify_qc is None:
                raise ValueError("proposal justify_qc missing")
            if qc_hash(justify_qc) != proposal.justify_qc_hash:
                raise ValueError("proposal justify_qc_hash mismatch")
            if justify_qc.validator_set_hash != self.validator_set.validator_set_hash:
                raise ValueError("justify_qc validator_set_hash mismatch")
        if self.locked_qc is not None and justify_qc is not None:
            if (
                proposal.block_hash != self.locked_qc.block_hash
                and justify_qc.round < self.locked_qc.round
                and justify_qc.block_hash != self.locked_qc.block_hash
            ):
                raise ValueError("proposal justify_qc is below locked qc")
        self.store.save_proposal(proposal_hash(proposal), proposal)

    def observe_qc(self, qc: QC | None) -> None:
        if qc is None:
            return
        self.store.save_qc(qc_hash(qc), qc)
        lock_round = qc.round if qc.phase is VotePhase.PRECOMMIT else None
        self.pacemaker = self.pacemaker.note_qc(qc.round, lock_round=lock_round)
        if qc.phase is VotePhase.PRECOMMIT:
            self.store.update_locked_qc(qc)
            self.store.prune_vote_log(qc.round)
            self.store.prune_timeout_log(qc.round)
        if qc.phase is VotePhase.COMMIT:
            self.pacemaker = self.pacemaker.note_decide(qc.round)
        self._persist_runtime_state()

    def observe_tc(self, tc: TC | None) -> None:
        if tc is None:
            return
        self.store.save_tc(tc_hash(tc), tc)
        self.pacemaker = self.pacemaker.note_tc(tc.round)
        self._persist_runtime_state()

    def make_vote(self, proposal: Proposal, justify_qc: QC | None, *, phase: VotePhase) -> Vote:
        self.validate_proposal(proposal, justify_qc)
        vote_key = (proposal.height, proposal.round, phase.value)
        existing = self._local_vote_choice.get(vote_key)
        if existing is not None and existing != proposal.block_hash:
            raise ValueError("local validator already voted for another block in this phase")
        self._local_vote_choice[vote_key] = proposal.block_hash
        self.store.save_vote_record(proposal.height, proposal.round, phase.value,
                                   self.local_validator_id, proposal.block_hash)
        return Vote(
            chain_id=self.chain_id,
            epoch_id=self.epoch_id,
            height=proposal.height,
            round=proposal.round,
            voter_id=self.local_validator_id,
            validator_set_hash=self.validator_set.validator_set_hash,
            block_hash=proposal.block_hash,
            phase=phase,
        )

    def accept_vote(self, vote: Vote) -> QC | None:
        qc = self.vote_collector.add_vote(vote, self.validator_set)
        self.store.save_vote_record(vote.height, vote.round, vote.phase.value,
                                   vote.voter_id, vote.block_hash)
        if qc is None:
            return None
        self.store.save_qc(qc_hash(qc), qc)
        lock_round = qc.round if qc.phase is VotePhase.PRECOMMIT else None
        self.pacemaker = self.pacemaker.note_qc(qc.round, lock_round=lock_round)
        if qc.phase is VotePhase.PRECOMMIT:
            self.store.update_locked_qc(qc)
            self.store.prune_vote_log(qc.round)
            self.store.prune_timeout_log(qc.round)
        if qc.phase is VotePhase.COMMIT:
            self.pacemaker = self.pacemaker.note_decide(qc.round)
        self._persist_runtime_state()
        return qc

    def make_timeout_vote(self, *, height: int, round: int) -> TimeoutVote:
        if height <= 0 or round <= 0:
            raise ValueError("height and round must be positive")
        round_key = (height, round)
        if round_key in self._local_timeout_rounds:
            raise ValueError("local validator already timed out this round")
        self._local_timeout_rounds.add(round_key)
        highest_qc = self.highest_qc
        self.store.save_timeout_record(height, round, self.local_validator_id,
                                      None if highest_qc is None else highest_qc.round,
                                      None if highest_qc is None else qc_hash(highest_qc))
        return TimeoutVote(
            chain_id=self.chain_id,
            epoch_id=self.epoch_id,
            height=height,
            round=round,
            voter_id=self.local_validator_id,
            validator_set_hash=self.validator_set.validator_set_hash,
            high_qc_round=None if highest_qc is None else highest_qc.round,
            high_qc_hash=None if highest_qc is None else qc_hash(highest_qc),
        )

    def accept_timeout_vote(self, timeout_vote: TimeoutVote) -> TC | None:
        tc = self.timeout_vote_collector.add_timeout_vote(timeout_vote, self.validator_set)
        self.store.save_timeout_record(timeout_vote.height, timeout_vote.round,
                                      timeout_vote.voter_id,
                                      timeout_vote.high_qc_round, timeout_vote.high_qc_hash)
        if tc is None:
            return None
        self.store.save_tc(tc_hash(tc), tc)
        self.pacemaker = self.pacemaker.note_tc(tc.round)
        self._persist_runtime_state()
        return tc

    def _persist_runtime_state(self) -> None:
        self.store.save_pacemaker_state(self.pacemaker)
