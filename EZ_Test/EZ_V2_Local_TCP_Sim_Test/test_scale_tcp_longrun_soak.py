from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_accounts_coverage,
    assert_block_packing,
    assert_checkpoints_exist,
    assert_cluster_converged,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import LONGRUN_SOAK_PROFILE


class LocalTCPScaleLongrunSoakTests(unittest.TestCase):
    def test_scale_tcp_longrun_soak_survives_restarts_and_account_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(LONGRUN_SOAK_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], LONGRUN_SOAK_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                self.assertLess(snapshot["height_delta"], snapshot["confirmed_tx_count"])
                self.assertGreater(snapshot["height_delta"], 0)
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, LONGRUN_SOAK_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_accounts_coverage(snapshot, min_accounts_touched=12)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=4)
                assert_block_packing(snapshot, min_avg_bundles_per_height=10.0)
                max_height = max(item["height"] for item in snapshot["consensus"].values())
                for node_id in ("consensus-4", "consensus-5", "consensus-6"):
                    self.assertTrue(snapshot["consensus"][node_id]["running"])
                    self.assertEqual(snapshot["consensus"][node_id]["height"], max_height)
                for account in snapshot["accounts"].values():
                    self.assertIn(account["consensus_peer_id"], snapshot["running_consensus_ids"])
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
