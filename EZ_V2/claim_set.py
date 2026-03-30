from __future__ import annotations

from .crypto import keccak256
from .encoding import canonical_encode
from .types import BundleSidecar, ClaimRangeSet
from .values import ValueRange


def build_claim_range_set(values: tuple[ValueRange, ...] | list[ValueRange]) -> ClaimRangeSet:
    ordered = sorted(values, key=lambda item: (item.begin, item.end))
    if not ordered:
        return ClaimRangeSet(ranges=())
    merged: list[ValueRange] = [ordered[0]]
    for item in ordered[1:]:
        previous = merged[-1]
        if item.begin <= previous.end + 1:
            merged[-1] = ValueRange(previous.begin, max(previous.end, item.end))
            continue
        merged.append(item)
    return ClaimRangeSet(ranges=tuple(merged))


def claim_range_set_from_sidecar(sidecar: BundleSidecar) -> ClaimRangeSet:
    values: list[ValueRange] = []
    for tx in sidecar.tx_list:
        values.extend(tx.value_list)
    return build_claim_range_set(values)


def claim_range_set_hash(claim_ranges: ClaimRangeSet) -> bytes:
    return keccak256(
        b"EZCHAIN_CLAIM_SET_V1" + canonical_encode(tuple(item.to_canonical() for item in claim_ranges.ranges))
    )


def claim_range_set_intersects(claim_ranges: ClaimRangeSet, value: ValueRange) -> bool:
    return any(item.intersects(value) or item.contains_range(value) or value.contains_range(item) for item in claim_ranges.ranges)


def claim_range_set_json_obj(claim_ranges: ClaimRangeSet) -> list[dict[str, int]]:
    return [item.to_canonical() for item in claim_ranges.ranges]


def claim_range_set_from_json_obj(payload) -> ClaimRangeSet:
    if not isinstance(payload, list):
        raise ValueError("claim range payload must be a list")
    ranges = tuple(
        ValueRange(begin=int(item["begin"]), end=int(item["end"]))
        for item in payload
        if isinstance(item, dict)
    )
    return ClaimRangeSet(ranges=ranges)


__all__ = [
    "build_claim_range_set",
    "claim_range_set_from_json_obj",
    "claim_range_set_from_sidecar",
    "claim_range_set_hash",
    "claim_range_set_intersects",
    "claim_range_set_json_obj",
]
