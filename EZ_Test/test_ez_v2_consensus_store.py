from __future__ import annotations

import tempfile
import unittest

from EZ_V2.consensus import (
    ConsensusCore,
    ConsensusValidator,
    SQLiteConsensusStore,
    TimeoutVote,
    ValidatorSet,
    Vote,
    VotePhase,
)


class EZV2ConsensusStoreTests(unittest.TestCase):
    def _validator_set(self) -> ValidatorSet:
        return ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", b"vrf-a"),
                ConsensusValidator("node-b", b"vote-b", b"vrf-b"),
                ConsensusValidator("node-c", b"vote-c", b"vrf-c"),
                ConsensusValidator("node-d", b"vote-d", b"vrf-d"),
            )
        )

    def test_sqlite_store_recovers_qc_lock_and_pacemaker_state_after_reopen(self) -> None:
        validator_set = self._validator_set()
        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/consensus.sqlite3"
            store = SQLiteConsensusStore(db_path)
            core = ConsensusCore(
                chain_id=7,
                epoch_id=0,
                local_validator_id="node-a",
                validator_set=validator_set,
                store=store,
            )

            precommit_votes = (
                Vote(7, 0, 10, 4, "node-a", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.PRECOMMIT),
                Vote(7, 0, 10, 4, "node-b", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.PRECOMMIT),
                Vote(7, 0, 10, 4, "node-c", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.PRECOMMIT),
            )
            for vote in precommit_votes:
                core.accept_vote(vote)

            commit_votes = (
                Vote(7, 0, 10, 4, "node-a", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.COMMIT),
                Vote(7, 0, 10, 4, "node-b", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.COMMIT),
                Vote(7, 0, 10, 4, "node-c", validator_set.validator_set_hash, b"\x11" * 32, VotePhase.COMMIT),
            )
            for vote in commit_votes:
                core.accept_vote(vote)
            store.close()

            reopened_store = SQLiteConsensusStore(db_path)
            reopened_core = ConsensusCore(
                chain_id=7,
                epoch_id=0,
                local_validator_id="node-a",
                validator_set=validator_set,
                store=reopened_store,
            )
            self.assertIsNotNone(reopened_core.highest_qc)
            self.assertIsNotNone(reopened_core.locked_qc)
            self.assertEqual(reopened_core.highest_qc.phase, VotePhase.COMMIT)
            self.assertEqual(reopened_core.locked_qc.phase, VotePhase.PRECOMMIT)
            self.assertEqual(reopened_core.highest_qc.round, 4)
            self.assertEqual(reopened_core.locked_qc.round, 4)
            self.assertEqual(reopened_core.pacemaker.current_round, 5)
            self.assertEqual(reopened_core.pacemaker.last_decided_round, 4)
            reopened_store.close()

    def test_sqlite_store_recovers_timeout_progress_after_reopen(self) -> None:
        validator_set = self._validator_set()
        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/timeout.sqlite3"
            store = SQLiteConsensusStore(db_path)
            core = ConsensusCore(
                chain_id=8,
                epoch_id=0,
                local_validator_id="node-a",
                validator_set=validator_set,
                store=store,
            )

            timeout_votes = (
                TimeoutVote(8, 0, 12, 3, "node-a", validator_set.validator_set_hash, 1, b"\x10" * 32),
                TimeoutVote(8, 0, 12, 3, "node-b", validator_set.validator_set_hash, 4, b"\x40" * 32),
                TimeoutVote(8, 0, 12, 3, "node-c", validator_set.validator_set_hash, 2, b"\x20" * 32),
            )
            for timeout_vote in timeout_votes:
                core.accept_timeout_vote(timeout_vote)
            store.close()

            reopened_store = SQLiteConsensusStore(db_path)
            reopened_core = ConsensusCore(
                chain_id=8,
                epoch_id=0,
                local_validator_id="node-a",
                validator_set=validator_set,
                store=reopened_store,
            )
            self.assertEqual(reopened_core.pacemaker.current_round, 4)
            self.assertEqual(reopened_core.pacemaker.highest_tc_round, 3)
            self.assertIsNone(reopened_core.highest_qc)
            reopened_store.close()
