"""
Safety persistence tests — verify that critical consensus state survives restart
and document known gaps where in-memory-only state is lost.

Spec coverage:
  - consensus-mvp-spec §13  persistence requirements
  - consensus-mvp-spec §16  items 7, 11
  - consensus-mvp-spec §13.1 vote_log table

Key findings documented here:
  - locked_qc and highest_qc ARE persisted via SQLiteConsensusStore
  - pacemaker round IS persisted
  - _local_vote_choice is NOT persisted (design gap: revote after restart possible)
  - _local_timeout_rounds is NOT persisted (design gap: re-timeout after restart possible)
  - VoteCollector is NOT persisted (design gap: conflicting votes accepted after restart)
"""

import hashlib
import shutil
import tempfile
import unittest

from EZ_V2.consensus.core import ConsensusCore
from EZ_V2.consensus.qc import VoteCollector
from EZ_V2.consensus.store import SQLiteConsensusStore
from EZ_V2.consensus.types import (
    ConsensusValidator,
    Proposal,
    QC,
    Vote,
    VotePhase,
    qc_hash,
)
from EZ_V2.consensus.validator_set import ValidatorSet

_VK = b"\x00" * 32
_VRF = b"\x01" * 32


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


def _make_core(store, local_id: str = "v0", chain_id: int = 8888) -> ConsensusCore:
    return ConsensusCore(
        chain_id=chain_id,
        epoch_id=0,
        local_validator_id=local_id,
        validator_set=_make_vset(),
        store=store,
    )


def _make_qc(
    vset: ValidatorSet,
    *,
    height: int = 1,
    round_: int = 1,
    phase: VotePhase = VotePhase.PREPARE,
    block_hash: bytes | None = None,
    chain_id: int = 8888,
) -> QC:
    if block_hash is None:
        block_hash = hashlib.sha256(f"block-h{height}-r{round_}".encode()).digest()
    return QC(
        chain_id=chain_id,
        epoch_id=0,
        height=height,
        round=round_,
        phase=phase,
        validator_set_hash=vset.validator_set_hash,
        block_hash=block_hash,
        signers=tuple(sorted(vset.validator_ids[: vset.quorum_size])),
    )


def _make_proposal(
    vset: ValidatorSet,
    *,
    height: int = 1,
    round_: int = 1,
    block_hash: bytes | None = None,
    chain_id: int = 8888,
) -> Proposal:
    if block_hash is None:
        block_hash = hashlib.sha256(b"prop-block").digest()
    return Proposal(
        chain_id=chain_id,
        epoch_id=0,
        height=height,
        round=round_,
        proposer_id=vset.validator_ids[0],
        validator_set_hash=vset.validator_set_hash,
        block_hash=block_hash,
    )


# ---------------------------------------------------------------------------
# Persisted state tests
# ---------------------------------------------------------------------------


class TestLockedQcPersistedAcrossRestart(unittest.TestCase):
    """spec §13, §16.2 item 4 — locked_qc must survive restart"""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        db = f"{self.td}/store.sqlite3"

        vset = _make_vset()

        # Phase 1: create core, set locked_qc via PreCommitQC
        core1 = _make_core(SQLiteConsensusStore(db))
        self.vset = vset
        precommit_qc = _make_qc(vset, round_=3, phase=VotePhase.PRECOMMIT)
        core1.observe_qc(precommit_qc)
        self.assertIsNotNone(core1.locked_qc)
        self.assertEqual(core1.locked_qc.round, 3)
        core1.store.close()

        # Phase 2: reopen with same db path
        core2 = _make_core(SQLiteConsensusStore(db))
        self.core2 = core2

    def tearDown(self):
        self.core2.store.close()
        shutil.rmtree(self.td, ignore_errors=True)

    def test_locked_qc_survives_restart(self):
        self.assertIsNotNone(self.core2.locked_qc)
        self.assertEqual(self.core2.locked_qc.round, 3)
        self.assertEqual(
            self.core2.locked_qc.validator_set_hash,
            self.vset.validator_set_hash,
        )


class TestHighestQcPersistedAcrossRestart(unittest.TestCase):
    """spec §13 — highest_qc must survive restart"""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        db = f"{self.td}/store.sqlite3"
        vset = _make_vset()

        core1 = _make_core(SQLiteConsensusStore(db))
        self.vset = vset
        qc_r2 = _make_qc(vset, round_=2, phase=VotePhase.COMMIT)
        core1.observe_qc(qc_r2)
        self.assertIsNotNone(core1.highest_qc)
        self.assertEqual(core1.highest_qc.round, 2)
        core1.store.close()

        core2 = _make_core(SQLiteConsensusStore(db))
        self.core2 = core2

    def tearDown(self):
        self.core2.store.close()
        shutil.rmtree(self.td, ignore_errors=True)

    def test_highest_qc_survives_restart(self):
        self.assertIsNotNone(self.core2.highest_qc)
        self.assertEqual(self.core2.highest_qc.round, 2)


class TestPacemakerRoundPersistedAcrossRestart(unittest.TestCase):
    """spec §13 — pacemaker round must survive restart"""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        db = f"{self.td}/store.sqlite3"
        vset = _make_vset()

        core1 = _make_core(SQLiteConsensusStore(db))
        qc_r5 = _make_qc(vset, round_=5, phase=VotePhase.PREPARE)
        core1.observe_qc(qc_r5)
        # pacemaker should have advanced to round 6
        self.assertEqual(core1.pacemaker.current_round, 6)
        core1.store.close()

        core2 = _make_core(SQLiteConsensusStore(db))
        self.core2 = core2

    def tearDown(self):
        self.core2.store.close()
        shutil.rmtree(self.td, ignore_errors=True)

    def test_pacemaker_round_survives_restart(self):
        self.assertEqual(self.core2.pacemaker.current_round, 6)


# ---------------------------------------------------------------------------
# Vote log persistence — previously known gaps, now fixed
# ---------------------------------------------------------------------------


class TestVoteLogPersistedAcrossRestart(unittest.TestCase):
    """spec §13.1, §16 item 11 — vote_log must survive restart.

    After fix: _local_vote_choice is persisted to SQLite.
    Restarting and voting for a different block in the same (h,r,phase) MUST raise.
    """

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = f"{self.td}/store.sqlite3"
        self.vset = _make_vset()
        self.block_a = hashlib.sha256(b"block-a").digest()
        self.block_b = hashlib.sha256(b"block-b").digest()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_vote_log_prevents_revote_after_restart(self):
        db = self.db
        vset = self.vset

        # Phase 1: vote for block_a at (h=1, r=1, prepare)
        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        prop_a = _make_proposal(vset, block_hash=self.block_a)
        vote_a = core1.make_vote(prop_a, justify_qc=None, phase=VotePhase.PREPARE)
        self.assertEqual(vote_a.block_hash, self.block_a)
        store1.close()

        # Phase 2: restart and attempt to vote for block_b in same (h,r,phase)
        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        prop_b = _make_proposal(vset, block_hash=self.block_b)
        with self.assertRaises(ValueError) as ctx:
            core2.make_vote(prop_b, justify_qc=None, phase=VotePhase.PREPARE)
        self.assertIn("already voted", str(ctx.exception).lower())
        store2.close()

    def test_vote_log_same_block_allowed_after_restart(self):
        """Re-voting for the SAME block in the same (h,r,phase) must still work."""
        db = self.db
        vset = self.vset

        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        prop = _make_proposal(vset, block_hash=self.block_a)
        core1.make_vote(prop, justify_qc=None, phase=VotePhase.PREPARE)
        store1.close()

        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        vote_b = core2.make_vote(prop, justify_qc=None, phase=VotePhase.PREPARE)
        self.assertEqual(vote_b.block_hash, self.block_a)
        store2.close()


class TestTimeoutLogPersistedAcrossRestart(unittest.TestCase):
    """spec §13 — timeout log must survive restart.

    After fix: _local_timeout_rounds is persisted to SQLite.
    Restarting and timing out the same (h,r) MUST raise.
    """

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = f"{self.td}/store.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_timeout_log_prevents_retimeout_after_restart(self):
        db = self.db

        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        tv1 = core1.make_timeout_vote(height=1, round=1)
        self.assertEqual(tv1.round, 1)
        store1.close()

        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        with self.assertRaises(ValueError) as ctx:
            core2.make_timeout_vote(height=1, round=1)
        self.assertIn("already timed out", str(ctx.exception).lower())
        store2.close()

    def test_timeout_log_different_round_allowed_after_restart(self):
        db = self.db

        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        core1.make_timeout_vote(height=1, round=1)
        store1.close()

        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        tv2 = core2.make_timeout_vote(height=1, round=2)
        self.assertEqual(tv2.round, 2)
        store2.close()


class TestVoteCollectorPersistedAcrossRestart(unittest.TestCase):
    """spec §13 item 14 — VoteCollector dedup must survive restart.

    After fix: conflicting remote votes from the same signer are detected
    after restart.
    """

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = f"{self.td}/store.sqlite3"
        self.vset = _make_vset()
        self.block_a = hashlib.sha256(b"vc-block-a").digest()
        self.block_b = hashlib.sha256(b"vc-block-b").digest()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_vote_collector_rejects_conflicting_after_restart(self):
        db = self.db
        vset = self.vset

        # Phase 1: accept a vote from v0 for block_a
        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        vote_a = Vote(
            chain_id=8888, epoch_id=0, height=1, round=1,
            voter_id="v0", validator_set_hash=vset.validator_set_hash,
            block_hash=self.block_a, phase=VotePhase.PREPARE,
        )
        core1.accept_vote(vote_a)
        store1.close()

        # Phase 2: restart and try conflicting vote from v0 for block_b
        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        vote_b = Vote(
            chain_id=8888, epoch_id=0, height=1, round=1,
            voter_id="v0", validator_set_hash=vset.validator_set_hash,
            block_hash=self.block_b, phase=VotePhase.PREPARE,
        )
        with self.assertRaises(ValueError) as ctx:
            core2.accept_vote(vote_b)
        self.assertIn("conflicting", str(ctx.exception).lower())
        store2.close()

    def test_vote_collector_same_vote_allowed_after_restart(self):
        """Accepting the same vote again after restart must be idempotent."""
        db = self.db
        vset = self.vset

        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)
        vote = Vote(
            chain_id=8888, epoch_id=0, height=1, round=1,
            voter_id="v0", validator_set_hash=vset.validator_set_hash,
            block_hash=self.block_a, phase=VotePhase.PREPARE,
        )
        core1.accept_vote(vote)
        store1.close()

        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)
        # Same vote should not raise
        result = core2.accept_vote(vote)
        store2.close()


class TestVoteLogPruning(unittest.TestCase):
    """Verify that vote/timeout logs are pruned when locked_qc advances."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = f"{self.td}/store.sqlite3"
        self.vset = _make_vset()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_prune_vote_log_on_precommit_qc(self):
        db = self.db
        vset = self.vset

        store = SQLiteConsensusStore(db)
        core = _make_core(store)

        # Vote at round 1 and round 3
        prop_r1 = _make_proposal(vset, height=1, round_=1)
        core.make_vote(prop_r1, justify_qc=None, phase=VotePhase.PREPARE)
        prop_r3 = _make_proposal(vset, height=1, round_=3)
        core.make_vote(prop_r3, justify_qc=None, phase=VotePhase.PREPARE)

        # All records present
        records = store.load_vote_records()
        self.assertEqual(len(records), 2)

        # Advance locked_qc to round 3 via PreCommitQC
        precommit_qc = _make_qc(vset, round_=3, phase=VotePhase.PRECOMMIT)
        core.observe_qc(precommit_qc)

        # Round 1 entries should be pruned (round < 3), round 3 kept
        records = store.load_vote_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1], 3)  # round == 3
        store.close()

    def test_prune_timeout_log_on_precommit_qc(self):
        db = self.db
        vset = self.vset

        store = SQLiteConsensusStore(db)
        core = _make_core(store)

        # Timeout at round 1 and round 4
        core.make_timeout_vote(height=1, round=1)
        core.make_timeout_vote(height=1, round=4)

        records = store.load_timeout_records()
        self.assertEqual(len(records), 2)

        # Advance locked_qc to round 4
        precommit_qc = _make_qc(vset, round_=4, phase=VotePhase.PRECOMMIT)
        core.observe_qc(precommit_qc)

        records = store.load_timeout_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1], 4)  # round == 4
        store.close()


class TestVoteLogMultiRoundPersistence(unittest.TestCase):
    """Verify vote log works correctly across multiple rounds and phases."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = f"{self.td}/store.sqlite3"
        self.vset = _make_vset()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_multi_round_votes_restored(self):
        db = self.db
        vset = self.vset

        store1 = SQLiteConsensusStore(db)
        core1 = _make_core(store1)

        # Vote in round 1 prepare
        prop_r1 = _make_proposal(vset, height=1, round_=1)
        core1.make_vote(prop_r1, justify_qc=None, phase=VotePhase.PREPARE)
        # Vote in round 2 precommit
        prop_r2 = _make_proposal(vset, height=1, round_=2)
        core1.make_vote(prop_r2, justify_qc=None, phase=VotePhase.PRECOMMIT)
        # Vote in round 3 commit
        prop_r3 = _make_proposal(vset, height=1, round_=3)
        core1.make_vote(prop_r3, justify_qc=None, phase=VotePhase.COMMIT)
        store1.close()

        # Restart and verify all votes are restored
        store2 = SQLiteConsensusStore(db)
        core2 = _make_core(store2)

        # Same block should be allowed (idempotent)
        core2.make_vote(prop_r1, justify_qc=None, phase=VotePhase.PREPARE)
        core2.make_vote(prop_r2, justify_qc=None, phase=VotePhase.PRECOMMIT)
        core2.make_vote(prop_r3, justify_qc=None, phase=VotePhase.COMMIT)

        # Different block should be rejected for all three
        diff_prop = _make_proposal(vset, height=1, round_=1,
                                     block_hash=hashlib.sha256(b"diff").digest())
        with self.assertRaises(ValueError):
            core2.make_vote(diff_prop, justify_qc=None, phase=VotePhase.PREPARE)

        store2.close()


if __name__ == "__main__":
    unittest.main()
