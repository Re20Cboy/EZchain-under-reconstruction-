from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class LocalValueStatus(Enum):
    VERIFIED_SPENDABLE = "verified_spendable"
    PENDING_BUNDLE = "pending_bundle"
    PENDING_CONFIRMATION = "pending_confirmation"
    RECEIPT_PENDING = "receipt_pending"
    RECEIPT_MISSING = "receipt_missing"
    LOCKED_FOR_VERIFICATION = "locked_for_verification"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class ValueRange:
    begin: int
    end: int

    def __post_init__(self) -> None:
        if self.begin < 0 or self.end < 0:
            raise ValueError("value range cannot be negative")
        if self.end < self.begin:
            raise ValueError("value range end must be >= begin")

    def to_canonical(self) -> dict:
        return {
            "begin": self.begin,
            "end": self.end,
        }

    @property
    def size(self) -> int:
        return self.end - self.begin + 1

    def intersects(self, other: "ValueRange") -> bool:
        return self.begin <= other.end and other.begin <= self.end

    def contains_value(self, value: int) -> bool:
        return self.begin <= value <= self.end

    def contains_range(self, other: "ValueRange") -> bool:
        return self.begin <= other.begin and other.end <= self.end

    def intersection(self, other: "ValueRange") -> "ValueRange | None":
        if not self.intersects(other):
            return None
        return ValueRange(max(self.begin, other.begin), min(self.end, other.end))

    def split_out(self, target: "ValueRange") -> tuple["ValueRange", tuple["ValueRange", ...]]:
        if not self.contains_range(target):
            raise ValueError("target range must be contained in source")
        remainders = []
        if self.begin < target.begin:
            remainders.append(ValueRange(self.begin, target.begin - 1))
        if target.end < self.end:
            remainders.append(ValueRange(target.end + 1, self.end))
        return target, tuple(remainders)


@dataclass(slots=True)
class LocalValueRecord:
    record_id: str
    value: ValueRange
    witness_v2: object
    local_status: LocalValueStatus
    acquisition_height: int

    def with_status(self, status: LocalValueStatus) -> "LocalValueRecord":
        return replace(self, local_status=status)
