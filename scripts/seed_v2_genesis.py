#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from EZ_V2.consensus_store import ConsensusStateStore
from EZ_V2.values import ValueRange


def _parse_allocation(spec: str) -> tuple[str, int]:
    owner_addr, amount_s = str(spec).split("=", 1)
    owner_addr = owner_addr.strip()
    if not owner_addr:
        raise ValueError("allocation_missing_owner_addr")
    amount = int(amount_s)
    if amount <= 0:
        raise ValueError("allocation_amount_must_be_positive")
    return owner_addr, amount


def _build_allocations(specs: tuple[str, ...], *, start_begin: int) -> tuple[tuple[str, ValueRange], ...]:
    cursor = int(start_begin)
    allocations: list[tuple[str, ValueRange]] = []
    for spec in specs:
        owner_addr, amount = _parse_allocation(spec)
        value = ValueRange(begin=cursor, end=cursor + amount - 1)
        allocations.append((owner_addr, value))
        cursor = value.end + 1
    return tuple(allocations)


def seed_genesis(*, store_paths: tuple[str, ...], allocations: tuple[tuple[str, ValueRange], ...]) -> dict[str, object]:
    stores_result: list[dict[str, object]] = []
    for store_path in store_paths:
        store = ConsensusStateStore(store_path)
        try:
            metadata = store.load_metadata()
            current_height = 0 if metadata is None else int(metadata.current_height)
            if current_height > 0:
                raise ValueError(f"store_not_genesis_empty:{store_path}:height={current_height}")
            before = store.list_genesis_allocations()
            for owner_addr, value in allocations:
                store.save_genesis_allocation(owner_addr, value)
            after = store.list_genesis_allocations()
            stores_result.append(
                {
                    "store_path": str(Path(store_path)),
                    "current_height": current_height,
                    "allocations_before": sum(len(values) for values in before.values()),
                    "allocations_after": sum(len(values) for values in after.values()),
                }
            )
        finally:
            store.close()
    return {
        "status": "seeded",
        "stores": stores_result,
        "allocations": [
            {
                "owner_addr": owner_addr,
                "value_begin": value.begin,
                "value_end": value.end,
                "amount": value.size,
            }
            for owner_addr, value in allocations
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed V2 genesis allocations into one or more consensus sqlite stores")
    parser.add_argument("--store", action="append", required=True, help="Repeatable path to consensus.sqlite3")
    parser.add_argument(
        "--allocation",
        action="append",
        required=True,
        help="Repeatable owner allocation in the form 0xabc...=amount; ranges are assigned sequentially",
    )
    parser.add_argument("--start-begin", type=int, default=0, help="First value range begin offset")
    args = parser.parse_args()

    allocations = _build_allocations(tuple(args.allocation), start_begin=args.start_begin)
    print(json.dumps(seed_genesis(store_paths=tuple(args.store), allocations=allocations), indent=2))


if __name__ == "__main__":
    main()
