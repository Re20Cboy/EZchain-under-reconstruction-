from __future__ import annotations

import unittest

from EZ_V2.consensus import ConsensusGenesisConfig, ConsensusValidator, ValidatorSet, compute_validator_set_hash


class EZV2ConsensusValidatorSetTests(unittest.TestCase):
    def test_validator_set_hash_is_stable_after_input_reordering(self) -> None:
        v1 = ConsensusValidator("node-b", b"vote-b", b"vrf-b")
        v2 = ConsensusValidator("node-a", b"vote-a", b"vrf-a")
        hash_a = compute_validator_set_hash((v1, v2))
        hash_b = compute_validator_set_hash((v2, v1))
        self.assertEqual(hash_a, hash_b)

    def test_validator_set_rejects_duplicate_validator_id(self) -> None:
        validators = (
            ConsensusValidator("node-a", b"vote-a-1", b"vrf-a-1"),
            ConsensusValidator("node-a", b"vote-a-2", b"vrf-a-2"),
        )
        with self.assertRaises(ValueError):
            ValidatorSet.from_validators(validators)

    def test_validator_set_uses_genesis_and_computes_quorum(self) -> None:
        genesis = ConsensusGenesisConfig(
            chain_id=9,
            epoch_id=0,
            validators=(
                ConsensusValidator("node-c", b"vote-c", b"vrf-c"),
                ConsensusValidator("node-a", b"vote-a", b"vrf-a"),
                ConsensusValidator("node-d", b"vote-d", b"vrf-d"),
                ConsensusValidator("node-b", b"vote-b", b"vrf-b"),
            ),
        )
        validator_set = ValidatorSet.from_genesis(genesis)
        self.assertEqual(validator_set.validator_ids, ("node-a", "node-b", "node-c", "node-d"))
        self.assertEqual(validator_set.quorum_size, 3)
        self.assertTrue(validator_set.has_quorum(("node-a", "node-b", "node-c")))
        self.assertFalse(validator_set.has_quorum(("node-a", "node-b")))
