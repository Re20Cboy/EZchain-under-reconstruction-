from __future__ import annotations

import unittest

from EZ_V2.consensus import (
    ConsensusCore,
    ConsensusValidator,
    Proposal,
    ValidatorSet,
    VotePhase,
    drive_single_round_commit,
    drive_timeout_round,
)


class EZV2ConsensusRunnerTests(unittest.TestCase):
    def _participants(self) -> tuple[ConsensusCore, ...]:
        validator_set = ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", b"vrf-a"),
                ConsensusValidator("node-b", b"vote-b", b"vrf-b"),
                ConsensusValidator("node-c", b"vote-c", b"vrf-c"),
                ConsensusValidator("node-d", b"vote-d", b"vrf-d"),
            )
        )
        return (
            ConsensusCore(chain_id=1, epoch_id=0, local_validator_id="node-a", validator_set=validator_set),
            ConsensusCore(chain_id=1, epoch_id=0, local_validator_id="node-b", validator_set=validator_set),
            ConsensusCore(chain_id=1, epoch_id=0, local_validator_id="node-c", validator_set=validator_set),
            ConsensusCore(chain_id=1, epoch_id=0, local_validator_id="node-d", validator_set=validator_set),
        )

    def test_drive_single_round_commit_forms_all_three_qcs(self) -> None:
        participants = self._participants()
        validator_set = participants[0].validator_set
        proposal = Proposal(
            chain_id=1,
            epoch_id=0,
            height=2,
            round=1,
            proposer_id="node-a",
            validator_set_hash=validator_set.validator_set_hash,
            block_hash=b"\x41" * 32,
        )
        result = drive_single_round_commit(
            proposal=proposal,
            justify_qc=None,
            participants=participants,
        )
        self.assertEqual(result.prepare_qc.phase, VotePhase.PREPARE)
        self.assertEqual(result.precommit_qc.phase, VotePhase.PRECOMMIT)
        self.assertEqual(result.commit_qc.phase, VotePhase.COMMIT)
        for participant in participants:
            self.assertEqual(participant.pacemaker.last_decided_round, 1)
            self.assertEqual(participant.locked_qc.block_hash, proposal.block_hash)

    def test_drive_timeout_round_advances_all_participants(self) -> None:
        participants = self._participants()
        tc = drive_timeout_round(height=3, round=1, participants=participants)
        self.assertEqual(tc.round, 1)
        self.assertEqual(tc.signers, ("node-a", "node-b", "node-c", "node-d"))
        for participant in participants:
            self.assertEqual(participant.pacemaker.current_round, 2)
