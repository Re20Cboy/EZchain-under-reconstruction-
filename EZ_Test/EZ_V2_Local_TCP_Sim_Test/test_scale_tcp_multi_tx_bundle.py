from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_accounts_coverage,
    assert_checkpoints_exist,
    assert_cluster_converged,
    assert_min_height,
    assert_multi_tx_bundle_activity,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import MULTI_TX_BUNDLE_PROFILE


class LocalTCPScaleMultiTxBundleTests(unittest.TestCase):
    def test_scale_tcp_multi_tx_bundles_commit_cleanly_and_keep_pool_state_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(MULTI_TX_BUNDLE_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], MULTI_TX_BUNDLE_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                self.assertLess(snapshot["bundle_count"], snapshot["confirmed_tx_count"])
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, MULTI_TX_BUNDLE_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_min_height(snapshot, MULTI_TX_BUNDLE_PROFILE.min_height_delta)
                assert_accounts_coverage(snapshot, min_accounts_touched=8)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=2)
                assert_multi_tx_bundle_activity(snapshot, min_bundle_count=10)

                multi_bundle_entries = [
                    item
                    for item in snapshot["transactions"]
                    if int(item.get("bundle_tx_count", 0)) >= 2
                ]
                self.assertTrue(multi_bundle_entries)
                self.assertTrue(
                    all(2 <= int(item["bundle_tx_count"]) <= 3 for item in multi_bundle_entries),
                    multi_bundle_entries,
                )
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
