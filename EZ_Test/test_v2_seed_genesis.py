import tempfile
import unittest
from pathlib import Path

from EZ_V2.consensus_store import ConsensusStateStore
from EZ_V2.values import ValueRange
from scripts.seed_v2_genesis import _build_allocations, seed_genesis


class V2SeedGenesisScriptTest(unittest.TestCase):
    def test_build_allocations_assigns_contiguous_ranges(self) -> None:
        allocations = _build_allocations(
            ("0xaaa=50", "0xbbb=30"),
            start_begin=100,
        )
        self.assertEqual(
            allocations,
            (
                ("0xaaa", ValueRange(100, 149)),
                ("0xbbb", ValueRange(150, 179)),
            ),
        )

    def test_seed_genesis_writes_allocations_to_multiple_empty_stores(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store_a = str(Path(td) / "a" / "consensus.sqlite3")
            store_b = str(Path(td) / "b" / "consensus.sqlite3")
            result = seed_genesis(
                store_paths=(store_a, store_b),
                allocations=(
                    ("0xaaa", ValueRange(0, 49)),
                    ("0xbbb", ValueRange(50, 99)),
                ),
            )
            self.assertEqual(result["status"], "seeded")
            for store_path in (store_a, store_b):
                store = ConsensusStateStore(store_path)
                try:
                    allocations = store.list_genesis_allocations()
                finally:
                    store.close()
                self.assertEqual(allocations["0xaaa"], (ValueRange(0, 49),))
                self.assertEqual(allocations["0xbbb"], (ValueRange(50, 99),))

