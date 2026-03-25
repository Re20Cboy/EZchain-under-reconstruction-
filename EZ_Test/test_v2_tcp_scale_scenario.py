from __future__ import annotations

import tempfile
import unittest

from scripts.v2_tcp_scale_scenario import run_scenario


class V2TCPScaleScenarioTests(unittest.TestCase):
    def test_run_scenario_confirms_random_transactions_and_preserves_supply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = run_scenario(
                root_dir=tmpdir,
                chain_id=821,
                consensus_count=3,
                account_count=4,
                tx_count=6,
                genesis_amount=200,
                min_amount=5,
                max_amount=25,
                checkpoint_every=2,
                seed=7,
                network_timeout_sec=5.0,
                reset_root=False,
            )

        self.assertEqual(summary["tx_requested"], 6)
        self.assertEqual(summary["tx_confirmed"], 6)
        self.assertEqual(summary["tx_failed"], 0)
        self.assertEqual(set(summary["consensus_heights"].values()), {6})
        self.assertEqual(summary["total_supply"], 800)
        self.assertEqual(len(summary["transactions"]), 6)
        self.assertTrue(
            any(account["checkpoint_count"] > 0 for account in summary["accounts"].values())
        )
        self.assertTrue(
            all(account["pending_bundle_count"] == 0 for account in summary["accounts"].values())
        )


if __name__ == "__main__":
    unittest.main()
