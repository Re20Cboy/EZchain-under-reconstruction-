from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_accounts_coverage,
    assert_checkpoints_exist,
    assert_cluster_converged,
    assert_min_height,
    assert_multi_tx_bundle_activity,
    assert_multi_value_activity,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import COMPLEX_RECOVERY_PROFILE


class LocalTCPScaleComplexRecoveryTests(unittest.TestCase):
    def test_scale_tcp_complex_recovery_keeps_mixed_flow_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(COMPLEX_RECOVERY_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], COMPLEX_RECOVERY_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, COMPLEX_RECOVERY_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_min_height(snapshot, COMPLEX_RECOVERY_PROFILE.min_height_delta)
                assert_accounts_coverage(snapshot, min_accounts_touched=10)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=3)
                assert_multi_value_activity(snapshot, min_multi_value_txs=3)
                assert_multi_tx_bundle_activity(snapshot, min_bundle_count=4)

                max_height = max(item["height"] for item in snapshot["consensus"].values())
                self.assertTrue(snapshot["consensus"]["consensus-6"]["running"])
                self.assertEqual(snapshot["consensus"]["consensus-6"]["height"], max_height)
                for account in snapshot["accounts"].values():
                    self.assertIn(account["consensus_peer_id"], snapshot["running_consensus_ids"])
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
