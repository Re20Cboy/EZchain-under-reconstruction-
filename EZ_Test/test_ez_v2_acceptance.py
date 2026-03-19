import tempfile
import unittest
from pathlib import Path

from EZ_Test.v2_acceptance import run_stage4_acceptance


class EZV2AcceptanceTest(unittest.TestCase):
    def test_stage4_acceptance_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary = run_stage4_acceptance(
                root_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )

            self.assertEqual(summary["node"]["started_status"], "started")
            self.assertEqual(summary["node"]["already_running_status"], "already_running")
            self.assertEqual(summary["node"]["stopped_status"], "stopped")
            self.assertEqual(summary["node"]["status_after_stop"], "stopped")
            self.assertEqual(summary["node"]["restarted_status"], "started")
            self.assertEqual(summary["node"]["status_after_restart"], "running")

            self.assertEqual(summary["heights"]["faucet"], 0)
            self.assertEqual(summary["heights"]["alice_receipt"], 1)
            self.assertEqual(summary["heights"]["bob_receipt"], 2)
            self.assertEqual(summary["heights"]["carol_receipt"], 3)
            self.assertEqual(summary["heights"]["backend"], 3)
            self.assertEqual(summary["heights"]["status_backend"], 3)

            self.assertEqual(summary["balances"]["bob_after_receive"], 180)
            self.assertEqual(summary["balances"]["carol_after_receive"], 70)
            self.assertEqual(summary["balances"]["alice"], 335)
            self.assertEqual(summary["balances"]["bob"], 110)
            self.assertEqual(summary["balances"]["carol"], 55)

            self.assertEqual(summary["history_lengths"]["initial"], {"alice": 1, "bob": 1, "carol": 1})
            self.assertEqual(summary["history_lengths"]["repeated"], {"alice": 1, "bob": 1, "carol": 1})

            self.assertEqual(summary["receipts"], {"alice": 1, "bob": 1, "carol": 1})
            self.assertEqual(summary["checkpoints"]["during_creation_count"], 1)
            self.assertEqual(summary["checkpoints"]["count"], 1)
            self.assertEqual(summary["checkpoints"]["created_height"], 2)


if __name__ == "__main__":
    unittest.main()
