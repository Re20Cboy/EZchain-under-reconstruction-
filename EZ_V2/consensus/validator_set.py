from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..encoding import canonical_encode
from .types import ConsensusGenesisConfig, ConsensusValidator


def compute_validator_set_hash(validators: tuple[ConsensusValidator, ...]) -> bytes:
    ordered = tuple(sorted(validators, key=lambda item: item.validator_id))
    payload = {
        "validators": ordered,
    }
    return hashlib.sha256(b"EZCHAIN_V2_VALIDATOR_SET" + canonical_encode(payload)).digest()


@dataclass(frozen=True, slots=True)
class ValidatorSet:
    validators: tuple[ConsensusValidator, ...]
    validator_set_hash: bytes
    quorum_size: int

    @classmethod
    def from_genesis(cls, genesis: ConsensusGenesisConfig) -> "ValidatorSet":
        return cls.from_validators(genesis.validators)

    @classmethod
    def from_validators(cls, validators: tuple[ConsensusValidator, ...]) -> "ValidatorSet":
        if not validators:
            raise ValueError("validators cannot be empty")
        ordered = tuple(sorted(validators, key=lambda item: item.validator_id))
        if len({item.validator_id for item in ordered}) != len(ordered):
            raise ValueError("validator_id must be unique")
        if any(item.weight != 1 for item in ordered):
            raise ValueError("mvp validator set requires equal weight validators")
        quorum_size = (2 * len(ordered)) // 3 + 1
        return cls(
            validators=ordered,
            validator_set_hash=compute_validator_set_hash(ordered),
            quorum_size=quorum_size,
        )

    @property
    def validator_count(self) -> int:
        return len(self.validators)

    @property
    def validator_ids(self) -> tuple[str, ...]:
        return tuple(item.validator_id for item in self.validators)

    def get(self, validator_id: str) -> ConsensusValidator | None:
        for validator in self.validators:
            if validator.validator_id == validator_id:
                return validator
        return None

    def contains(self, validator_id: str) -> bool:
        return self.get(validator_id) is not None

    def has_quorum(self, signers: tuple[str, ...] | list[str] | set[str]) -> bool:
        unique = {signer for signer in signers if self.contains(signer)}
        return len(unique) >= self.quorum_size
