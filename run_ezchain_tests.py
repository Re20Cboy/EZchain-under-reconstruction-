#!/usr/bin/env python3
"""
One-key test runner for the EZchain project.

This script orchestrates the major test suites in EZ_Test to provide broad
feature coverage with a single command:

    python run_ezchain_tests.py

Use --help for additional options (group selection, skipping slow tests, etc.).
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parent
TEST_ROOT = ROOT_DIR / "EZ_Test"


TEST_GROUPS: Tuple[Dict[str, object], ...] = (
    {
        "name": "core",
        "title": "Core Data Structures",
        "description": "Value model, Merkle proofs, Bloom filter, and block primitives",
        "tests": [
            "EZ_Test/test_value.py",
            "EZ_Test/test_merkle_tree.py",
            "EZ_Test/test_merkle_proof.py",
            "EZ_Test/test_bloom.py",
            "EZ_Test/test_block.py",
            "EZ_Test/test_block_index_list.py",
        ],
    },
    {
        "name": "accounts",
        "title": "Account Management",
        "description": "Account state, value collection, and value picking workflows",
        "tests": [
            "EZ_Test/test_account.py",
            "EZ_Test/test_account_value_collection.py",
            "EZ_Test/test_account_pick_values.py",
        ],
    },
    {
        "name": "transactions",
        "title": "Transaction Lifecycle",
        "description": "Single/multi transactions, packing, sender uniqueness, and pool",
        "tests": [
            "EZ_Test/test_single_transaction.py",
            "EZ_Test/test_multi_transactions.py",
            "EZ_Test/test_pack_transactions_integration.py",
            "EZ_Test/test_pack_transactions_sender_uniqueness.py",
            "EZ_Test/test_integration_creat_single_transaction.py",
            "EZ_Test/test_transactions_pool.py",
        ],
    },
    {
        "name": "security",
        "title": "Security and Proofs",
        "description": "Secure signature handling and VPB proof units",
        "tests": [
            "EZ_Test/test_secure_signature.py",
            "EZ_Test/test_proof_unit_integration.py",
        ],
    },
    {
        "name": "blockchain",
        "title": "Blockchain Core",
        "description": "Blockchain logic, integration flow, and real end-to-end scenarios",
        "tests": [
            "EZ_Test/test_blockchain.py",
            "EZ_Test/test_blockchain_integration.py",
            "EZ_Test/test_real_blockchain_simple.py",
            "EZ_Test/test_real_end_to_end_blockchain.py",
        ],
    },
    {
        "name": "simulation",
        "title": "Simulation Tools",
        "description": "Transaction injector and simulation bridge",
        "tests": [
            "EZ_Test/test_transaction_injector.py",
        ],
    },
)


SLOW_TESTS = {
    "EZ_Test/test_real_end_to_end_blockchain.py",
}


class TestFailure(Exception):
    """Raised when one or more test groups fail."""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run grouped EZchain tests with a single command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              python run_ezchain_tests.py
              python run_ezchain_tests.py --groups core blockchain
              python run_ezchain_tests.py --skip-slow
              python run_ezchain_tests.py --pytest-args "-k Value"
            """
        ),
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        help="Subset of groups to run (default: all groups).",
    )
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Skip tests marked as slow (currently: real end-to-end blockchain).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available test groups and exit.",
    )
    parser.add_argument(
        "--pytest-args",
        default="",
        help="Additional arguments to pass to pytest (quote them).",
    )
    return parser.parse_args(argv)


def ensure_pytest_available() -> None:
    try:
        import importlib

        importlib.import_module("pytest")
    except ImportError as exc:  # pragma: no cover - guard clause
        raise SystemExit(
            "Pytest is not available. Install dependencies via "
            "'pip install -r requirements.txt' and retry."
        ) from exc


def list_groups() -> None:
    print("Available test groups:\n")
    for group in TEST_GROUPS:
        print(f"- {group['name']}: {group['title']}")
        print(f"    {group['description']}")
        for path in group["tests"]:  # type: ignore[index]
            print(f"    • {path}")
        print()


def normalize_group_selection(selected: Sequence[str] | None) -> Tuple[Dict[str, object], ...]:
    if not selected:
        return TEST_GROUPS

    available = {group["name"]: group for group in TEST_GROUPS}
    missing = [name for name in selected if name not in available]
    if missing:
        available_names = ", ".join(sorted(available))
        missing_names = ", ".join(missing)
        raise SystemExit(f"Unknown group(s): {missing_names}. Choose from: {available_names}")

    return tuple(available[name] for name in selected)


def filter_slow_tests(test_paths: List[str]) -> List[str]:
    return [path for path in test_paths if path not in SLOW_TESTS]


def run_group(
    group: Dict[str, object],
    pytest_args: List[str],
    skip_slow: bool,
) -> Tuple[bool, float, List[str]]:
    tests: List[str] = list(group["tests"])  # type: ignore[assignment]
    if skip_slow:
        tests = filter_slow_tests(tests)
    if not tests:
        print(f"[ SKIP ] {group['title']} (all tests filtered)")
        return True, 0.0, []

    print("\n" + "=" * 80)
    print(f"Running group: {group['title']}")
    print(group["description"])
    print("=" * 80)

    cmd = [sys.executable, "-m", "pytest", "-v"] + pytest_args + tests
    start = time.perf_counter()
    completed = subprocess.run(cmd, cwd=ROOT_DIR)
    duration = time.perf_counter() - start

    success = completed.returncode == 0
    status = "PASS" if success else "FAIL"
    print(f"\n[{status}] {group['title']} finished in {duration:.2f}s")
    return success, duration, tests


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list:
        list_groups()
        return 0

    ensure_pytest_available()

    selected_groups = normalize_group_selection(args.groups)
    pytest_args = shlex.split(args.pytest_args)

    overall_success = True
    summary: List[Tuple[str, bool, float, List[str]]] = []

    for group in selected_groups:
        success, duration, tests_run = run_group(group, pytest_args, args.skip_slow)
        overall_success &= success
        summary.append((group["title"], success, duration, tests_run))

    print("\n" + "#" * 80)
    print("Test Summary")
    print("#" * 80)
    for title, success, duration, tests in summary:
        marker = "PASS" if success else "FAIL"
        test_list = ", ".join(Path(path).name for path in tests) or "no tests run"
        print(f"{marker:<5} {title:<30} ({duration:.2f}s) -> {test_list}")

    if not overall_success:
        raise TestFailure(
            "One or more test groups failed. Check the logs above for details."
        )

    print("\nAll selected test groups completed successfully.")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    try:
        raise SystemExit(main())
    except TestFailure as failure:
        print(failure)
        raise SystemExit(1)
