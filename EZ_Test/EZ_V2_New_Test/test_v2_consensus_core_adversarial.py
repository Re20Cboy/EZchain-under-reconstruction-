"""
Consensus-core adversarial tests – validate_proposal / make_vote / accept_vote /
accept_timeout_vote paths on ConsensusCore and VoteCollector.

Spec coverage:
  - consensus-mvp-spec §3.2.2  validator_set_hash / epoch_id mismatch
  - consensus-mvp-spec §8.6    justify_qc_hash consistency
  - consensus-mvp-spec §9      safety rules (locked_qc, double-vote, double-timeout)
  - consensus-mvp-spec §16     items 11-14
"""

import hashlib
import unittest

from EZ_V2.consensus.core import ConsensusCore
from EZ_V2.consensus.qc import VoteCollector, TimeoutVoteCollector
from EZ_V2.consensus.store import InMemoryConsensusStore
from EZ_V2.consensus.types import (
    ConsensusValidator,
    Proposal,
    QC,
    TimeoutVote,
    Vote,
    VotePhase,
    proposal_hash,
    qc_hash,
    timeout_vote_hash,
    vote_hash,
)
from EZ_V2.consensus.validator_set import ValidatorSet
from EZ_V2.encoding import canonical_encode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VK = b"\x00" * 32  # dummy vote pubkey
_VRF = b"\x01" * 32  # dummy vrf pubkey


def _make_validators(n: int = 4) -> tuple[ConsensusValidator, ...]:
    return tuple(
        ConsensusValidator(
            validator_id=f"v{i}",
            consensus_vote_pubkey=_VK,
            vrf_pubkey=_VRF,
        )
        for i in range(n)
    )


def _make_vset(n: int = 4) -> ValidatorSet:
    return ValidatorSet.from_validators(_make_validators(n))


def _make_core(
    local_id: str = "v0", n: int = 4, chain_id: int = 9999, epoch_id: int = 0
) -> ConsensusCore:
    return ConsensusCore(
        chain_id=chain_id,
        epoch_id=epoch_id,
        local_validator_id=local_id,
        validator_set=_make_vset(n),
        store=InMemoryConsensusStore(),
    )


def _make_proposal(
    core: ConsensusCore,
    *,
    height: int = 1,
    round_: int = 1,
    proposer_id: str | None = None,
    validator_set_hash: bytes | None = None,
    epoch_id: int | None = None,
    block_hash: bytes | None = None,
    justify_qc_hash: bytes | None = None,
) -> Proposal:
    if proposer_id is None:
        proposer_id = core.validator_set.validator_ids[0]
    if validator_set_hash is None:
        validator_set_hash = core.validator_set.validator_set_hash
    if epoch_id is None:
        epoch_id = core.epoch_id
    if block_hash is None:
        block_hash = hashlib.sha256(b"dummy-block").digest()
    return Proposal(
        chain_id=core.chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round_,
        proposer_id=proposer_id,
        validator_set_hash=validator_set_hash,
        block_hash=block_hash,
        justify_qc_hash=justify_qc_hash,
    )


def _make_qc(
    core: ConsensusCore,
    *,
    height: int = 1,
    round_: int = 1,
    phase: VotePhase = VotePhase.PREPARE,
    block_hash: bytes | None = None,
    signers: tuple[str, ...] | None = None,
) -> QC:
    if block_hash is None:
        block_hash = hashlib.sha256(b"qc-block").digest()
    if signers is None:
        signers = core.validator_set.validator_ids[: core.validator_set.quorum_size]
    return QC(
        chain_id=core.chain_id,
        epoch_id=core.epoch_id,
        height=height,
        round=round_,
        phase=phase,
        validator_set_hash=core.validator_set.validator_set_hash,
        block_hash=block_hash,
        signers=tuple(sorted(signers)),
    )


def _make_vote(
    core: ConsensusCore | None = None,
    *,
    chain_id: int = 9999,
    epoch_id: int = 0,
    height: int = 1,
    round_: int = 1,
    block_hash: bytes | None = None,
    voter_id: str | None = None,
    phase: VotePhase = VotePhase.PREPARE,
    validator_set_hash: bytes | None = None,
) -> Vote:
    if block_hash is None:
        block_hash = hashlib.sha256(b"vote-block").digest()
    if core is not None:
        if voter_id is None:
            voter_id = core.validator_set.validator_ids[0]
        if validator_set_hash is None:
            validator_set_hash = core.validator_set.validator_set_hash
        chain_id = core.chain_id
        epoch_id = core.epoch_id
    elif voter_id is None or validator_set_hash is None:
        raise ValueError("must provide voter_id and validator_set_hash when core is None")
    return Vote(
        chain_id=chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round_,
        voter_id=voter_id,
        validator_set_hash=validator_set_hash,
        block_hash=block_hash,
        phase=phase,
    )


def _make_timeout_vote(
    core: ConsensusCore | None = None,
    *,
    chain_id: int = 9999,
    epoch_id: int = 0,
    height: int = 1,
    round_: int = 1,
    voter_id: str | None = None,
    validator_set_hash: bytes | None = None,
) -> TimeoutVote:
    if core is not None:
        if voter_id is None:
            voter_id = core.validator_set.validator_ids[0]
        if validator_set_hash is None:
            validator_set_hash = core.validator_set.validator_set_hash
        chain_id = core.chain_id
        epoch_id = core.epoch_id
    elif voter_id is None or validator_set_hash is None:
        raise ValueError("must provide voter_id and validator_set_hash when core is None")
    return TimeoutVote(
        chain_id=chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round_,
        voter_id=voter_id,
        validator_set_hash=validator_set_hash,
    )


# ---------------------------------------------------------------------------
# Proposal validation (ConsensusCore.validate_proposal)
# ---------------------------------------------------------------------------


class TestProposalValidatorSetHashMismatch(unittest.TestCase):
    """spec §3.2.2, §16 item 12"""

    def test_wrong_validator_set_hash_rejected(self):
        core = _make_core()
        bad_hash = hashlib.sha256(b"wrong-validator-set").digest()
        proposal = _make_proposal(core, validator_set_hash=bad_hash)
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=None)
        self.assertIn("validator_set_hash", str(ctx.exception).lower())


class TestProposalEpochIdMismatch(unittest.TestCase):
    """spec §16 item 13"""

    def test_wrong_epoch_id_rejected(self):
        core = _make_core(epoch_id=0)
        proposal = _make_proposal(core, epoch_id=99)
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=None)
        self.assertIn("epoch", str(ctx.exception).lower())


class TestProposalJustifyQcHashMismatch(unittest.TestCase):
    """spec §16 item 14, §8.6"""

    def test_justify_qc_hash_differs_from_actual_qc(self):
        core = _make_core()
        qc = _make_qc(core, round_=1)
        # Compute correct hash first
        correct_hash = qc_hash(qc)
        # Now create proposal with a *different* hash
        bad_hash = hashlib.sha256(b"tampered-justify").digest()
        self.assertNotEqual(correct_hash, bad_hash)
        proposal = _make_proposal(core, justify_qc_hash=bad_hash)
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=qc)
        self.assertIn("justify_qc_hash", str(ctx.exception).lower())


class TestProposalJustifyQcMissing(unittest.TestCase):
    """spec §8.6 — if justify_qc_hash is set, justify_qc must be provided"""

    def test_missing_justify_qc_raises(self):
        core = _make_core()
        some_hash = hashlib.sha256(b"some-hash").digest()
        proposal = _make_proposal(core, justify_qc_hash=some_hash)
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=None)
        self.assertIn("missing", str(ctx.exception).lower())


class TestProposalJustifyQcValidatorSetHashMismatch(unittest.TestCase):
    """spec §8.6 — justify QC's validator_set_hash must match local"""

    def test_justify_qc_foreign_validator_set_rejected(self):
        core = _make_core()
        # Create a QC from a *different* validator set
        foreign_vset = ValidatorSet.from_validators(
            tuple(
                ConsensusValidator(
                    validator_id=f"foreign-{i}",
                    consensus_vote_pubkey=_VK,
                    vrf_pubkey=_VRF,
                )
                for i in range(4)
            )
        )
        qc = QC(
            chain_id=core.chain_id,
            epoch_id=core.epoch_id,
            height=1,
            round=1,
            phase=VotePhase.PREPARE,
            validator_set_hash=foreign_vset.validator_set_hash,
            block_hash=hashlib.sha256(b"foreign-block").digest(),
            signers=tuple(sorted(foreign_vset.validator_ids[: foreign_vset.quorum_size])),
        )
        proposal = _make_proposal(core, justify_qc_hash=qc_hash(qc))
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=qc)
        self.assertIn("validator_set_hash", str(ctx.exception).lower())


class TestProposalLockedQcBypass(unittest.TestCase):
    """spec §9 rule 2 — proposal justified by QC below locked_qc is rejected"""

    def test_justify_qc_below_locked_qc_rejected(self):
        core = _make_core()
        # First, establish a locked_qc at round 5
        locked_qc = _make_qc(core, height=1, round_=5, phase=VotePhase.PRECOMMIT)
        core.store.update_locked_qc(locked_qc)
        # Now propose at round 6, justified by a QC at round 3 with different block
        low_qc = _make_qc(
            core,
            height=1,
            round_=3,
            phase=VotePhase.PREPARE,
            block_hash=hashlib.sha256(b"different-block").digest(),
        )
        proposal = _make_proposal(
            core,
            height=1,
            round_=6,
            block_hash=hashlib.sha256(b"new-block").digest(),
            justify_qc_hash=qc_hash(low_qc),
        )
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=low_qc)
        self.assertIn("locked", str(ctx.exception).lower())

    def test_justify_qc_at_or_above_locked_qc_accepted(self):
        """A proposal justified by QC at locked round for the same block is fine."""
        core = _make_core()
        block_hash = hashlib.sha256(b"locked-block").digest()
        locked_qc = _make_qc(
            core, height=1, round_=5, phase=VotePhase.PRECOMMIT,
            block_hash=block_hash,
        )
        core.store.update_locked_qc(locked_qc)
        # Propose at round 6, justify_qc at round 5, same block
        justify = _make_qc(
            core, height=1, round_=5, phase=VotePhase.PREPARE,
            block_hash=block_hash,
        )
        proposal = _make_proposal(
            core, height=1, round_=6, block_hash=block_hash,
            justify_qc_hash=qc_hash(justify),
        )
        # Should NOT raise
        core.validate_proposal(proposal, justify_qc=justify)


class TestProposalStaleRound(unittest.TestCase):
    """Pacemaker rule — proposal at round << current_round is stale"""

    def test_stale_round_rejected(self):
        core = _make_core()
        # Advance pacemaker to round 10
        from EZ_V2.consensus.pacemaker import PacemakerState

        core.pacemaker = PacemakerState(current_round=10)
        proposal = _make_proposal(core, round_=3)  # 3 + 1 = 4 < 10
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=None)
        self.assertIn("stale", str(ctx.exception).lower())


class TestProposalUnknownProposer(unittest.TestCase):
    """spec §3.2.2 item 1 — proposer must be in validator set"""

    def test_unknown_proposer_rejected(self):
        core = _make_core()
        proposal = _make_proposal(core, proposer_id="attacker-node")
        with self.assertRaises(ValueError) as ctx:
            core.validate_proposal(proposal, justify_qc=None)
        self.assertIn("proposer", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Vote acceptance (VoteCollector)
# ---------------------------------------------------------------------------


class TestVoteValidatorSetHashMismatch(unittest.TestCase):
    """spec §16 item 12 — vote with wrong validator_set_hash rejected"""

    def test_vote_wrong_validator_set_hash_rejected(self):
        vset = _make_vset()
        collector = VoteCollector()
        bad_hash = hashlib.sha256(b"wrong-vote-vset").digest()
        vote = _make_vote(
            validator_set_hash=bad_hash,
            voter_id="v0",
        )
        with self.assertRaises(ValueError) as ctx:
            collector.add_vote(vote, vset)
        self.assertIn("validator_set_hash", str(ctx.exception).lower())


class TestVoteUnknownValidator(unittest.TestCase):
    """spec §3.2.2 — vote from unknown signer rejected"""

    def test_vote_from_unknown_signer_rejected(self):
        vset = _make_vset(4)
        collector = VoteCollector()
        vote = _make_vote(
            voter_id="ghost-node",
            validator_set_hash=vset.validator_set_hash,
        )
        with self.assertRaises(ValueError) as ctx:
            collector.add_vote(vote, vset)
        self.assertIn("not in validator", str(ctx.exception).lower())


class TestConflictingVoteSameSigner(unittest.TestCase):
    """spec §9 rule 1 — same signer cannot vote for different block in same phase"""

    def test_conflicting_vote_detected(self):
        vset = _make_vset(4)
        collector = VoteCollector()
        block_a = hashlib.sha256(b"block-a").digest()
        block_b = hashlib.sha256(b"block-b").digest()
        vote1 = _make_vote(
            voter_id="v0",
            block_hash=block_a,
            validator_set_hash=vset.validator_set_hash,
        )
        collector.add_vote(vote1, vset)
        vote2 = _make_vote(
            voter_id="v0",
            block_hash=block_b,
            validator_set_hash=vset.validator_set_hash,
        )
        with self.assertRaises(ValueError) as ctx:
            collector.add_vote(vote2, vset)
        self.assertIn("conflicting", str(ctx.exception).lower())

    def test_same_block_same_signer_is_idempotent(self):
        """Voting twice for the same block must NOT raise."""
        vset = _make_vset(4)
        collector = VoteCollector()
        block = hashlib.sha256(b"block-x").digest()
        vote1 = _make_vote(
            voter_id="v0", block_hash=block,
            validator_set_hash=vset.validator_set_hash,
        )
        collector.add_vote(vote1, vset)
        vote2 = _make_vote(
            voter_id="v0", block_hash=block,
            validator_set_hash=vset.validator_set_hash,
        )
        # Should NOT raise
        collector.add_vote(vote2, vset)


# ---------------------------------------------------------------------------
# Timeout vote acceptance
# ---------------------------------------------------------------------------


class TestTimeoutVoteValidatorSetHashMismatch(unittest.TestCase):
    """spec §16 item 12"""

    def test_timeout_vote_wrong_validator_set_hash_rejected(self):
        vset = _make_vset()
        collector = TimeoutVoteCollector()
        bad_hash = hashlib.sha256(b"bad-tv-vset").digest()
        tv = _make_timeout_vote(
            validator_set_hash=bad_hash,
            voter_id="v0",
        )
        with self.assertRaises(ValueError) as ctx:
            collector.add_timeout_vote(tv, vset)
        self.assertIn("validator_set_hash", str(ctx.exception).lower())


class TestConflictingTimeoutVoteSameSigner(unittest.TestCase):
    """spec §9 — same signer cannot send conflicting timeout votes"""

    def test_conflicting_timeout_vote_detected(self):
        vset = _make_vset(4)
        collector = TimeoutVoteCollector()
        tv1 = _make_timeout_vote(
            voter_id="v0",
            validator_set_hash=vset.validator_set_hash,
        )
        # Modify high_qc_round/hash for the second vote
        tv2 = TimeoutVote(
            chain_id=tv1.chain_id,
            epoch_id=tv1.epoch_id,
            height=tv1.height,
            round=tv1.round,
            voter_id=tv1.voter_id,
            validator_set_hash=tv1.validator_set_hash,
            high_qc_round=99,
            high_qc_hash=hashlib.sha256(b"fake-qc").digest(),
        )
        collector.add_timeout_vote(tv1, vset)
        with self.assertRaises(ValueError) as ctx:
            collector.add_timeout_vote(tv2, vset)
        self.assertIn("conflicting", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# make_timeout_vote double-timeout (ConsensusCore)
# ---------------------------------------------------------------------------


class TestDuplicateTimeoutSameRound(unittest.TestCase):
    """spec §9 — cannot timeout same (height, round) twice"""

    def test_duplicate_timeout_rejected(self):
        core = _make_core()
        core.make_timeout_vote(height=1, round=1)
        with self.assertRaises(ValueError) as ctx:
            core.make_timeout_vote(height=1, round=1)
        self.assertIn("already timed out", str(ctx.exception).lower())

    def test_different_round_allowed(self):
        core = _make_core()
        core.make_timeout_vote(height=1, round=1)
        # Different round should succeed
        tv = core.make_timeout_vote(height=1, round=2)
        self.assertEqual(tv.round, 2)


# ---------------------------------------------------------------------------
# Domain separator verification
# ---------------------------------------------------------------------------


class TestDomainSeparatorEnforcement(unittest.TestCase):
    """spec §7.3.2 — Proposal, Vote, TimeoutVote use distinct domain separators.
    Verify that hashing the *same semantic payload* with different domains produces
    different hashes (i.e., a Vote signed with Proposal domain would not match)."""

    def test_proposal_hash_differs_from_vote_hash(self):
        """Even with overlapping fields, different domains → different hashes."""
        chain_id = 9999
        epoch_id = 0
        height = 1
        round_ = 1
        validator_set_hash = _make_vset().validator_set_hash
        block_hash = hashlib.sha256(b"block").digest()

        proposal = Proposal(
            chain_id=chain_id,
            epoch_id=epoch_id,
            height=height,
            round=round_,
            proposer_id="v0",
            validator_set_hash=validator_set_hash,
            block_hash=block_hash,
        )
        vote = Vote(
            chain_id=chain_id,
            epoch_id=epoch_id,
            height=height,
            round=round_,
            voter_id="v0",
            validator_set_hash=validator_set_hash,
            block_hash=block_hash,
            phase=VotePhase.PREPARE,
        )
        self.assertNotEqual(proposal_hash(proposal), vote_hash(vote))

    def test_vote_hash_differs_from_timeout_vote_hash(self):
        chain_id = 9999
        epoch_id = 0
        height = 1
        round_ = 1
        validator_set_hash = _make_vset().validator_set_hash

        vote = Vote(
            chain_id=chain_id,
            epoch_id=epoch_id,
            height=height,
            round=round_,
            voter_id="v0",
            validator_set_hash=validator_set_hash,
            block_hash=hashlib.sha256(b"block").digest(),
            phase=VotePhase.PREPARE,
        )
        tv = TimeoutVote(
            chain_id=chain_id,
            epoch_id=epoch_id,
            height=height,
            round=round_,
            voter_id="v0",
            validator_set_hash=validator_set_hash,
        )
        self.assertNotEqual(vote_hash(vote), timeout_vote_hash(tv))

    def test_all_three_domains_are_distinct(self):
        """All three hash domains must be pairwise distinct."""
        vset = _make_vset()
        proposal = Proposal(
            chain_id=1, epoch_id=0, height=1, round=1,
            proposer_id="v0",
            validator_set_hash=vset.validator_set_hash,
            block_hash=hashlib.sha256(b"x").digest(),
        )
        vote = Vote(
            chain_id=1, epoch_id=0, height=1, round=1,
            voter_id="v0",
            validator_set_hash=vset.validator_set_hash,
            block_hash=hashlib.sha256(b"x").digest(),
            phase=VotePhase.PREPARE,
        )
        tv = TimeoutVote(
            chain_id=1, epoch_id=0, height=1, round=1,
            voter_id="v0",
            validator_set_hash=vset.validator_set_hash,
        )
        h_p = proposal_hash(proposal)
        h_v = vote_hash(vote)
        h_t = timeout_vote_hash(tv)
        self.assertEqual(len({h_p, h_v, h_t}), 3, "all three domain hashes must differ")


if __name__ == "__main__":
    unittest.main()
