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
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import GATE_SMOKE_PROFILE


class LocalTCPMultiUserGateSmokeTests(unittest.TestCase):
    def test_gate_tcp_smoke_converges_and_preserves_supply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(GATE_SMOKE_PROFILE, td)
            try:
                cluster.start()
                summary = cluster.run_random_rounds()
                snapshot = cluster.snapshot()

                self.assertEqual(summary["tx_requested"], GATE_SMOKE_PROFILE.tx_count)
                self.assertEqual(snapshot["confirmed_tx_count"], GATE_SMOKE_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                self.assertEqual(
                    sum(item["receipt_count"] for item in snapshot["accounts"].values()),
                    GATE_SMOKE_PROFILE.tx_count,
                )
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, GATE_SMOKE_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=1)
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()

