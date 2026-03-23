from __future__ import annotations

import unittest

from EZ_V2.consensus import (
    ConsensusValidator,
    VRFProposerClaim,
    ValidatorSet,
    build_signed_proposer_claim,
    select_best_proposer,
    verify_signed_proposer_claim,
)
from EZ_V2.crypto import generate_secp256k1_keypair


class EZV2ConsensusSortitionTests(unittest.TestCase):
    def _validator_set(self) -> ValidatorSet:
        _, node_a_vrf_public = generate_secp256k1_keypair()
        _, node_b_vrf_public = generate_secp256k1_keypair()
        _, node_c_vrf_public = generate_secp256k1_keypair()
        _, node_d_vrf_public = generate_secp256k1_keypair()
        return ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", node_a_vrf_public),
                ConsensusValidator("node-b", b"vote-b", node_b_vrf_public),
                ConsensusValidator("node-c", b"vote-c", node_c_vrf_public),
                ConsensusValidator("node-d", b"vote-d", node_d_vrf_public),
            )
        )

    def test_select_best_proposer_ignores_invalid_claims(self) -> None:
        validator_set = self._validator_set()
        good_claim = VRFProposerClaim(
            chain_id=1,
            epoch_id=0,
            height=5,
            round=2,
            validator_id="node-a",
            validator_set_hash=validator_set.validator_set_hash,
            vrf_output=b"\x01" * 32,
            vrf_proof=b"proof-a",
        )
        wrong_hash_claim = VRFProposerClaim(
            chain_id=1,
            epoch_id=0,
            height=5,
            round=2,
            validator_id="node-b",
            validator_set_hash=b"\x22" * 32,
            vrf_output=b"\x00" * 32,
            vrf_proof=b"proof-b",
        )
        chosen = select_best_proposer(
            [wrong_hash_claim, good_claim],
            validator_set=validator_set,
            chain_id=1,
            epoch_id=0,
            height=5,
            round=2,
            seed=b"\x99" * 32,
            verifier=lambda claim, message, vrf_pubkey: claim.vrf_proof.startswith(b"proof"),
        )
        self.assertEqual(chosen, good_claim)

    def test_select_best_proposer_uses_lowest_valid_score(self) -> None:
        node_a_private, node_a_public = generate_secp256k1_keypair()
        node_b_private, node_b_public = generate_secp256k1_keypair()
        validator_set = ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", node_a_public),
                ConsensusValidator("node-b", b"vote-b", node_b_public),
            )
        )
        claim_a = build_signed_proposer_claim(
            chain_id=1,
            epoch_id=0,
            height=7,
            round=1,
            validator_id="node-a",
            validator_set_hash=validator_set.validator_set_hash,
            seed=b"\x55" * 32,
            private_key_pem=node_a_private,
        )
        claim_b = build_signed_proposer_claim(
            chain_id=1,
            epoch_id=0,
            height=7,
            round=1,
            validator_id="node-b",
            validator_set_hash=validator_set.validator_set_hash,
            seed=b"\x55" * 32,
            private_key_pem=node_b_private,
        )
        chosen = select_best_proposer(
            [claim_a, claim_b],
            validator_set=validator_set,
            chain_id=1,
            epoch_id=0,
            height=7,
            round=1,
            seed=b"\x55" * 32,
            verifier=verify_signed_proposer_claim,
        )
        self.assertIn(chosen, (claim_a, claim_b))

    def test_signed_proposer_claim_verifier_rejects_wrong_key_and_tampered_output(self) -> None:
        node_a_private, node_a_public = generate_secp256k1_keypair()
        _, node_b_public = generate_secp256k1_keypair()
        validator_set = ValidatorSet.from_validators(
            (
                ConsensusValidator("node-a", b"vote-a", node_a_public),
                ConsensusValidator("node-b", b"vote-b", node_b_public),
            )
        )
        claim = build_signed_proposer_claim(
            chain_id=1,
            epoch_id=0,
            height=9,
            round=2,
            validator_id="node-a",
            validator_set_hash=validator_set.validator_set_hash,
            seed=b"\x66" * 32,
            private_key_pem=node_a_private,
        )
        chosen = select_best_proposer(
            [claim],
            validator_set=validator_set,
            chain_id=1,
            epoch_id=0,
            height=9,
            round=2,
            seed=b"\x66" * 32,
            verifier=verify_signed_proposer_claim,
        )
        self.assertEqual(chosen, claim)

        tampered_claim = VRFProposerClaim(
            chain_id=claim.chain_id,
            epoch_id=claim.epoch_id,
            height=claim.height,
            round=claim.round,
            validator_id=claim.validator_id,
            validator_set_hash=claim.validator_set_hash,
            vrf_output=b"\x00" * 32,
            vrf_proof=claim.vrf_proof,
        )
        chosen = select_best_proposer(
            [tampered_claim],
            validator_set=validator_set,
            chain_id=1,
            epoch_id=0,
            height=9,
            round=2,
            seed=b"\x66" * 32,
            verifier=verify_signed_proposer_claim,
        )
        self.assertIsNone(chosen)

        chosen = select_best_proposer(
            [claim],
            validator_set=validator_set,
            chain_id=1,
            epoch_id=0,
            height=9,
            round=2,
            seed=b"\x66" * 32,
            verifier=lambda claim_obj, message, vrf_pubkey: verify_signed_proposer_claim(claim_obj, message, node_b_public),
        )
        self.assertIsNone(chosen)
