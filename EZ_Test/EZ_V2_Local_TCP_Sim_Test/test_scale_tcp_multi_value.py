from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_accounts_coverage,
    assert_checkpoints_exist,
    assert_cluster_converged,
    assert_min_height,
    assert_multi_value_activity,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import MULTIVALUE_PROFILE


class LocalTCPScaleMultiValueTests(unittest.TestCase):
    def test_scale_tcp_multi_value_compose_preserves_liveness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(MULTIVALUE_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], MULTIVALUE_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, MULTIVALUE_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_min_height(snapshot, MULTIVALUE_PROFILE.min_height_delta)
                assert_accounts_coverage(snapshot, min_accounts_touched=8)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=3)
                assert_multi_value_activity(snapshot, min_multi_value_txs=10)

                multi_value_entries = [
                    item
                    for item in snapshot["transactions"]
                    if int(item.get("multi_value_tx_count_in_bundle", 0)) > 0
                ]
                self.assertGreaterEqual(len(multi_value_entries), 10)
                self.assertTrue(
                    any(int(item.get("bundle_tx_count", 0)) == 1 for item in multi_value_entries),
                    multi_value_entries,
                )
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
