from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from ..crypto import sign_message_secp256k1, verify_message_secp256k1
from ..encoding import canonical_encode
from .validator_set import ValidatorSet

SIGNED_SORTITION_PROOF_DOMAIN = b"EZCHAIN_V2_SIGNED_SORTITION_PROOF"
SIGNED_SORTITION_OUTPUT_DOMAIN = b"EZCHAIN_V2_SIGNED_SORTITION_OUTPUT"


def _require_hash32(name: str, value: bytes) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{name} must be 32 bytes")


@dataclass(frozen=True, slots=True)
class VRFProposerClaim:
    chain_id: int
    epoch_id: int
    height: int
    round: int
    validator_id: str
    validator_set_hash: bytes
    vrf_output: bytes
    vrf_proof: bytes

    def __post_init__(self) -> None:
        if self.chain_id < 0 or self.epoch_id < 0:
            raise ValueError("invalid vrf claim numeric field")
        if self.height <= 0 or self.round <= 0:
            raise ValueError("height and round must be positive")
        if not self.validator_id:
            raise ValueError("validator_id must be set")
        if not self.vrf_output:
            raise ValueError("vrf_output must be set")
        if not self.vrf_proof:
            raise ValueError("vrf_proof must be set")
        _require_hash32("validator_set_hash", self.validator_set_hash)

    def to_canonical(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "epoch_id": self.epoch_id,
            "height": self.height,
            "round": self.round,
            "validator_id": self.validator_id,
            "validator_set_hash": self.validator_set_hash,
            "vrf_output": self.vrf_output,
            "vrf_proof": self.vrf_proof,
        }


def build_proposer_sortition_message(
    *,
    chain_id: int,
    epoch_id: int,
    height: int,
    round: int,
    seed: bytes,
    validator_set_hash: bytes,
) -> bytes:
    _require_hash32("seed", seed)
    _require_hash32("validator_set_hash", validator_set_hash)
    if chain_id < 0 or epoch_id < 0 or height <= 0 or round <= 0:
        raise ValueError("invalid sortition numeric field")
    payload = {
        "chain_id": chain_id,
        "epoch_id": epoch_id,
        "height": height,
        "round": round,
        "seed": seed,
        "validator_set_hash": validator_set_hash,
    }
    return b"EZCHAIN_V2_VRF_PROPOSER" + canonical_encode(payload)


def claim_score(claim: VRFProposerClaim, *, sortition_message: bytes) -> bytes:
    return hashlib.sha256(
        b"EZCHAIN_V2_PROPOSER_SCORE"
        + sortition_message
        + claim.validator_id.encode("utf-8")
        + claim.vrf_output
    ).digest()


VRFVerifier = Callable[[VRFProposerClaim, bytes, bytes], bool]


def build_signed_proposer_claim(
    *,
    chain_id: int,
    epoch_id: int,
    height: int,
    round: int,
    validator_id: str,
    validator_set_hash: bytes,
    seed: bytes,
    private_key_pem: bytes,
) -> VRFProposerClaim:
    sortition_message = build_proposer_sortition_message(
        chain_id=chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round,
        seed=seed,
        validator_set_hash=validator_set_hash,
    )
    proof = sign_message_secp256k1(
        private_key_pem,
        sortition_message,
        domain=SIGNED_SORTITION_PROOF_DOMAIN,
    )
    output = hashlib.sha256(
        SIGNED_SORTITION_OUTPUT_DOMAIN + sortition_message + proof
    ).digest()
    return VRFProposerClaim(
        chain_id=chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round,
        validator_id=validator_id,
        validator_set_hash=validator_set_hash,
        vrf_output=output,
        vrf_proof=proof,
    )


def verify_signed_proposer_claim(claim: VRFProposerClaim, sortition_message: bytes, vrf_pubkey: bytes) -> bool:
    if not verify_message_secp256k1(
        vrf_pubkey,
        sortition_message,
        claim.vrf_proof,
        domain=SIGNED_SORTITION_PROOF_DOMAIN,
    ):
        return False
    expected_output = hashlib.sha256(
        SIGNED_SORTITION_OUTPUT_DOMAIN + sortition_message + claim.vrf_proof
    ).digest()
    return claim.vrf_output == expected_output


def select_best_proposer(
    claims: tuple[VRFProposerClaim, ...] | list[VRFProposerClaim],
    *,
    validator_set: ValidatorSet,
    chain_id: int,
    epoch_id: int,
    height: int,
    round: int,
    seed: bytes,
    verifier: VRFVerifier,
) -> VRFProposerClaim | None:
    sortition_message = build_proposer_sortition_message(
        chain_id=chain_id,
        epoch_id=epoch_id,
        height=height,
        round=round,
        seed=seed,
        validator_set_hash=validator_set.validator_set_hash,
    )
    best: VRFProposerClaim | None = None
    best_score: bytes | None = None
    for claim in claims:
        if claim.chain_id != chain_id or claim.epoch_id != epoch_id:
            continue
        if claim.height != height or claim.round != round:
            continue
        if claim.validator_set_hash != validator_set.validator_set_hash:
            continue
        validator = validator_set.get(claim.validator_id)
        if validator is None:
            continue
        if not verifier(claim, sortition_message, validator.vrf_pubkey):
            continue
        score = claim_score(claim, sortition_message=sortition_message)
        if best is None or score < best_score:
            best = claim
            best_score = score
    return best
