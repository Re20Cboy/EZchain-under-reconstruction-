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
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import GATE_RECOVERY_PROFILE


class LocalTCPMultiUserGateRecoveryTests(unittest.TestCase):
    def test_gate_tcp_recovery_restarts_consensus_and_keeps_flow_alive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(GATE_RECOVERY_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds(tx_count=6)
                restarted_id = f"consensus-{GATE_RECOVERY_PROFILE.consensus_count - 1}"
                applied = cluster.restart_consensus(restarted_id)
                self.assertIsInstance(applied, tuple)
                recoveries = cluster.recover_all_accounts()
                self.assertEqual(set(recoveries), set(cluster.active_account_ids))

                cluster.run_random_rounds(tx_count=6)
                snapshot = cluster.snapshot()

                self.assertEqual(snapshot["confirmed_tx_count"], GATE_RECOVERY_PROFILE.tx_count)
                self.assertEqual(snapshot["failed_tx_count"], 0)
                self.assertEqual(
                    snapshot["consensus"][restarted_id]["height"],
                    max(item["height"] for item in snapshot["consensus"].values()),
                )
                assert_cluster_converged(snapshot)
                assert_supply_conserved(snapshot, GATE_RECOVERY_PROFILE.total_supply)
                assert_no_pending_leaks(snapshot)
                assert_checkpoints_exist(snapshot, min_accounts_with_checkpoints=1)
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()

