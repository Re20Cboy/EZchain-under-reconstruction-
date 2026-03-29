from __future__ import annotations

import json
from typing import Any


def assert_cluster_converged(snapshot: dict[str, Any]) -> None:
    running = [
        item
        for item in snapshot.get("consensus", {}).values()
        if isinstance(item, dict) and item.get("running", True)
    ]
    assert running, "no_running_consensus_nodes"
    heights = {int(item.get("height", -1)) for item in running}
    head_hashes = {str(item.get("head_hash", "")) for item in running}
    assert len(heights) == 1, f"consensus_height_diverged:{running}"
    assert len(head_hashes) == 1, f"consensus_head_hash_diverged:{running}"


def assert_supply_conserved(snapshot: dict[str, Any], expected_total_supply: int) -> None:
    total_supply = int(snapshot.get("total_supply", -1))
    assert total_supply == int(expected_total_supply), (
        f"total_supply_mismatch:expected={expected_total_supply}:actual={total_supply}"
    )


def assert_no_pending_leaks(snapshot: dict[str, Any]) -> None:
    leaking = {
        node_id: item
        for node_id, item in snapshot.get("accounts", {}).items()
        if int(item.get("pending_bundle_count", 0)) > 0
    }
    assert not leaking, f"pending_bundle_leak:{leaking}"


def assert_checkpoints_exist(snapshot: dict[str, Any], min_accounts_with_checkpoints: int) -> None:
    count = sum(
        1
        for item in snapshot.get("accounts", {}).values()
        if int(item.get("checkpoint_count", 0)) > 0
    )
    assert count >= int(min_accounts_with_checkpoints), (
        f"checkpoint_accounts_too_few:expected>={min_accounts_with_checkpoints}:actual={count}"
    )


def assert_min_height(snapshot: dict[str, Any], expected_delta: int) -> None:
    actual = int(snapshot.get("height_delta", 0))
    assert actual >= int(expected_delta), f"height_delta_too_small:expected>={expected_delta}:actual={actual}"


def assert_accounts_coverage(snapshot: dict[str, Any], min_accounts_touched: int) -> None:
    actual = len(tuple(snapshot.get("accounts_touched", ())))
    assert actual >= int(min_accounts_touched), (
        f"accounts_touched_too_few:expected>={min_accounts_touched}:actual={actual}"
    )


def assert_multi_value_activity(snapshot: dict[str, Any], min_multi_value_txs: int) -> None:
    actual = int(snapshot.get("multi_value_tx_count", 0))
    assert actual >= int(min_multi_value_txs), (
        f"multi_value_tx_count_too_small:expected>={min_multi_value_txs}:actual={actual}"
    )


def assert_multi_tx_bundle_activity(snapshot: dict[str, Any], min_bundle_count: int) -> None:
    actual = int(snapshot.get("multi_tx_bundle_count", 0))
    assert actual >= int(min_bundle_count), (
        f"multi_tx_bundle_count_too_small:expected>={min_bundle_count}:actual={actual}"
    )


def assert_userflow_history_and_receipts(
    *,
    history_views: dict[str, dict[str, Any]],
    receipt_views: dict[str, dict[str, Any]],
    expected_users: tuple[str, ...],
    expected_receipt_count: int,
) -> None:
    for user in expected_users:
        receipts = receipt_views[user]["items"]
        history_items = history_views[user]["items"]
        assert len(receipts) == expected_receipt_count, (
            f"receipt_count_mismatch:{user}:expected={expected_receipt_count}:actual={len(receipts)}"
        )
        assert len(history_items) >= expected_receipt_count, (
            f"history_too_short:{user}:expected>={expected_receipt_count}:actual={len(history_items)}"
        )
        encoded = [json.dumps(item, sort_keys=True) for item in history_items]
        assert len(encoded) == len(set(encoded)), f"history_contains_duplicates:{user}:{history_items}"
        receipt_heights = [int(item["height"]) for item in receipts]
        assert receipt_heights == sorted(receipt_heights), f"receipt_heights_not_sorted:{user}:{receipts}"
