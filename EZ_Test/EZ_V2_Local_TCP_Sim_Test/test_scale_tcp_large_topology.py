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
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import XL_TOPOLOGY_PROFILE


class LocalTCPScaleLargeTopologyTests(unittest.TestCase):
    def test_scale_tcp_large_topology_converges_without_pending_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(XL_TOPOLOGY_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], XL_TOPOLOGY_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                self.assertLess(snapshot["height_delta"], snapshot["confirmed_tx_count"])
                self.assertGreater(snapshot["height_delta"], 0)
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, XL_TOPOLOGY_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_accounts_coverage(snapshot, min_accounts_touched=20)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=3)
                assert_block_packing(snapshot, min_avg_bundles_per_height=8.0)
                for account in snapshot["accounts"].values():
                    self.assertGreaterEqual(account["total_balance"], account["available_balance"])
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
