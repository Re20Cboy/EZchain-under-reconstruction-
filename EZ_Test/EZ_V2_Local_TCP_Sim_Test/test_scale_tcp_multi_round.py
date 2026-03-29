from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_checkpoints_exist,
    assert_cluster_converged,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import HEAVY_MULTI_ROUND_PROFILE


class LocalTCPScaleMultiRoundTests(unittest.TestCase):
    def test_scale_tcp_multi_round_preserves_supply_and_participation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(HEAVY_MULTI_ROUND_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], HEAVY_MULTI_ROUND_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, HEAVY_MULTI_ROUND_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=3)
                for account in snapshot["accounts"].values():
                    self.assertGreaterEqual(account["total_balance"], account["available_balance"])
                    self.assertGreater(account["send_count"] + account["receive_count"], 0)
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()

