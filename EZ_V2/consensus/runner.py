from __future__ import annotations

from dataclasses import dataclass

from .core import ConsensusCore
from .types import Proposal, QC, TC, TimeoutVote, Vote, VotePhase


@dataclass(slots=True)
class ConsensusRoundRunner:
    core: ConsensusCore

    def on_proposal(self, proposal: Proposal, justify_qc: QC | None, *, phase: VotePhase) -> Vote:
        return self.core.make_vote(proposal, justify_qc, phase=phase)

    def on_vote(self, vote: Vote) -> QC | None:
        return self.core.accept_vote(vote)

    def on_timeout(self, timeout_vote: TimeoutVote) -> TC | None:
        return self.core.accept_timeout_vote(timeout_vote)


@dataclass(frozen=True, slots=True)
class ConsensusRoundResult:
    prepare_qc: QC
    precommit_qc: QC
    commit_qc: QC


def drive_single_round_commit(
    *,
    proposal: Proposal,
    justify_qc: QC | None,
    participants: tuple[ConsensusCore, ...] | list[ConsensusCore],
) -> ConsensusRoundResult:
    ordered = tuple(participants)
    prepare_qc = _drive_vote_phase(
        proposal=proposal,
        justify_qc=justify_qc,
        participants=ordered,
        phase=VotePhase.PREPARE,
    )
    precommit_qc = _drive_vote_phase(
        proposal=proposal,
        justify_qc=justify_qc,
        participants=ordered,
        phase=VotePhase.PRECOMMIT,
    )
    commit_qc = _drive_vote_phase(
        proposal=proposal,
        justify_qc=justify_qc,
        participants=ordered,
        phase=VotePhase.COMMIT,
    )
    return ConsensusRoundResult(
        prepare_qc=prepare_qc,
        precommit_qc=precommit_qc,
        commit_qc=commit_qc,
    )


def drive_timeout_round(
    *,
    height: int,
    round: int,
    participants: tuple[ConsensusCore, ...] | list[ConsensusCore],
) -> TC:
    ordered = tuple(participants)
    tc: TC | None = None
    timeout_votes = [participant.make_timeout_vote(height=height, round=round) for participant in ordered]
    for timeout_vote in timeout_votes:
        for participant in ordered:
            maybe_tc = participant.accept_timeout_vote(timeout_vote)
            if maybe_tc is not None:
                tc = maybe_tc
    if tc is None:
        raise ValueError("failed to form tc")
    return tc


def _drive_vote_phase(
    *,
    proposal: Proposal,
    justify_qc: QC | None,
    participants: tuple[ConsensusCore, ...],
    phase: VotePhase,
) -> QC:
    qc: QC | None = None
    votes = [participant.make_vote(proposal, justify_qc, phase=phase) for participant in participants]
    for vote in votes:
        for participant in participants:
            maybe_qc = participant.accept_vote(vote)
            if maybe_qc is not None:
                qc = maybe_qc
    if qc is None:
        raise ValueError(f"failed to form {phase.value} qc")
    return qc
