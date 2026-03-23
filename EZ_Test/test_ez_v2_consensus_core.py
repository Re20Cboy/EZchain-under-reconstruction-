from __future__ import annotations

import unittest

from EZ_V2.consensus import (
    ConsensusCore,
    ConsensusValidator,
    Proposal,
    QC,
    TimeoutVote,
    ValidatorSet,
    Vote,
    VotePhase,
    qc_hash,
)


class EZV2ConsensusCoreTests(unittest.TestCase):
    def _validator_set(self) -> ValidatorSet:
        return ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", b"vrf-a"),
                ConsensusValidator("node-b", b"vote-b", b"vrf-b"),
                ConsensusValidator("node-c", b"vote-c", b"vrf-c"),
                ConsensusValidator("node-d", b"vote-d", b"vrf-d"),
            )
        )

    def _core(self) -> ConsensusCore:
        validator_set = self._validator_set()
        return ConsensusCore(
            chain_id=1,
            epoch_id=0,
            local_validator_id="node-a",
            validator_set=validator_set,
        )

    def test_local_vote_conflict_is_rejected(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        proposal_1 = Proposal(
            chain_id=1,
            epoch_id=0,
            height=3,
            round=1,
            proposer_id="node-b",
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x11" * 32,
        )
        proposal_2 = Proposal(
            chain_id=1,
            epoch_id=0,
            height=3,
            round=1,
            proposer_id="node-c",
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x22" * 32,
        )
        core.make_vote(proposal_1, None, phase=VotePhase.PREPARE)
        with self.assertRaises(ValueError):
            core.make_vote(proposal_2, None, phase=VotePhase.PREPARE)

    def test_precommit_qc_updates_lock_and_round(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        block_hash = b"\x33" * 32
        votes = (
            Vote(1, 0, 4, 2, "node-a", validator_set.validator_set_hash, block_hash, VotePhase.PRECOMMIT),
            Vote(1, 0, 4, 2, "node-b", validator_set.validator_set_hash, block_hash, VotePhase.PRECOMMIT),
            Vote(1, 0, 4, 2, "node-c", validator_set.validator_set_hash, block_hash, VotePhase.PRECOMMIT),
        )
        qc = None
        for vote in votes:
            qc = core.accept_vote(vote)
        self.assertIsNotNone(qc)
        self.assertEqual(qc.phase, VotePhase.PRECOMMIT)
        self.assertEqual(core.locked_qc.block_hash, block_hash)
        self.assertEqual(core.pacemaker.locked_qc_round, 2)
        self.assertEqual(core.pacemaker.current_round, 3)

    def test_commit_qc_marks_decided(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        block_hash = b"\x44" * 32
        votes = (
            Vote(1, 0, 5, 3, "node-a", validator_set.validator_set_hash, block_hash, VotePhase.COMMIT),
            Vote(1, 0, 5, 3, "node-b", validator_set.validator_set_hash, block_hash, VotePhase.COMMIT),
            Vote(1, 0, 5, 3, "node-c", validator_set.validator_set_hash, block_hash, VotePhase.COMMIT),
        )
        qc = None
        for vote in votes:
            qc = core.accept_vote(vote)
        self.assertIsNotNone(qc)
        self.assertEqual(core.pacemaker.last_decided_round, 3)
        self.assertEqual(core.highest_qc.block_hash, block_hash)
        self.assertEqual(core.highest_qc.phase, VotePhase.COMMIT)

    def test_duplicate_vote_is_idempotent_after_qc(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        vote_a = Vote(1, 0, 6, 2, "node-a", validator_set.validator_set_hash, b"\x88" * 32, VotePhase.PREPARE)
        vote_b = Vote(1, 0, 6, 2, "node-b", validator_set.validator_set_hash, b"\x88" * 32, VotePhase.PREPARE)
        vote_c = Vote(1, 0, 6, 2, "node-c", validator_set.validator_set_hash, b"\x88" * 32, VotePhase.PREPARE)

        self.assertIsNone(core.accept_vote(vote_a))
        self.assertIsNone(core.accept_vote(vote_b))
        qc = core.accept_vote(vote_c)
        assert qc is not None

        duplicate_qc = core.accept_vote(vote_b)
        assert duplicate_qc is not None
        self.assertEqual(duplicate_qc.signers, qc.signers)
        self.assertEqual(duplicate_qc.block_hash, qc.block_hash)

    def test_locked_qc_rejects_lower_justify_from_other_branch(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        locked_qc = QC(
            chain_id=1,
            epoch_id=0,
            height=6,
            round=4,
            phase=VotePhase.PRECOMMIT,
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x55" * 32,
            signers=("node-a", "node-b", "node-c"),
        )
        core.store.update_locked_qc(locked_qc)
        core.store.save_qc(qc_hash(locked_qc), locked_qc)

        lower_qc = QC(
            chain_id=1,
            epoch_id=0,
            height=6,
            round=3,
            phase=VotePhase.PREPARE,
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x66" * 32,
            signers=("node-a", "node-b", "node-c"),
        )
        proposal = Proposal(
            chain_id=1,
            epoch_id=0,
            height=7,
            round=5,
            proposer_id="node-b",
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x77" * 32,
            justify_qc_hash=qc_hash(lower_qc),
        )
        with self.assertRaises(ValueError):
            core.validate_proposal(proposal, lower_qc)

    def test_timeout_votes_form_tc_and_advance_round(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        timeout_votes = (
            TimeoutVote(1, 0, 8, 2, "node-a", validator_set.validator_set_hash, 1, b"\x10" * 32),
            TimeoutVote(1, 0, 8, 2, "node-b", validator_set.validator_set_hash, 3, b"\x30" * 32),
            TimeoutVote(1, 0, 8, 2, "node-c", validator_set.validator_set_hash, 2, b"\x20" * 32),
        )
        tc = None
        for timeout_vote in timeout_votes:
            tc = core.accept_timeout_vote(timeout_vote)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.high_qc_round, 3)
        self.assertEqual(tc.high_qc_hash, b"\x30" * 32)
        self.assertEqual(core.pacemaker.current_round, 3)

    def test_observe_tc_advances_local_round(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        tc = core.accept_timeout_vote(TimeoutVote(1, 0, 9, 1, "node-a", validator_set.validator_set_hash, 0, b"\x10" * 32))
        self.assertIsNone(tc)
        observed_tc = core.accept_timeout_vote(TimeoutVote(1, 0, 9, 1, "node-b", validator_set.validator_set_hash, 2, b"\x20" * 32))
        self.assertIsNone(observed_tc)
        observed_tc = core.accept_timeout_vote(TimeoutVote(1, 0, 9, 1, "node-c", validator_set.validator_set_hash, 3, b"\x30" * 32))
        assert observed_tc is not None

        follower = ConsensusCore(
            chain_id=1,
            epoch_id=0,
            local_validator_id="node-d",
            validator_set=validator_set,
        )
        follower.observe_tc(observed_tc)

        self.assertEqual(follower.pacemaker.current_round, 2)

    def test_duplicate_timeout_vote_is_idempotent_after_tc(self) -> None:
        core = self._core()
        validator_set = core.validator_set
        timeout_vote_a = TimeoutVote(1, 0, 10, 2, "node-a", validator_set.validator_set_hash, 1, b"\x10" * 32)
        timeout_vote_b = TimeoutVote(1, 0, 10, 2, "node-b", validator_set.validator_set_hash, 3, b"\x30" * 32)
        timeout_vote_c = TimeoutVote(1, 0, 10, 2, "node-c", validator_set.validator_set_hash, 2, b"\x20" * 32)

        self.assertIsNone(core.accept_timeout_vote(timeout_vote_a))
        self.assertIsNone(core.accept_timeout_vote(timeout_vote_b))
        tc = core.accept_timeout_vote(timeout_vote_c)
        assert tc is not None

        duplicate_tc = core.accept_timeout_vote(timeout_vote_b)
        assert duplicate_tc is not None
        self.assertEqual(duplicate_tc.signers, tc.signers)
        self.assertEqual(duplicate_tc.high_qc_round, tc.high_qc_round)
