from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import (
    assert_cluster_converged,
    assert_no_pending_leaks,
    assert_supply_conserved,
)
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import HEAVY_FAILOVER_PROFILE


class LocalTCPScaleFailoverTests(unittest.TestCase):
    def test_scale_tcp_failover_keeps_confirming_and_rotates_off_dead_peer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(HEAVY_FAILOVER_PROFILE, td)
            try:
                cluster.start()
                cluster.run_random_rounds(tx_count=40)

                stopped_id = f"consensus-{HEAVY_FAILOVER_PROFILE.consensus_count - 1}"
                cluster.stop_consensus(stopped_id)
                for node_id in cluster.active_account_ids:
                    host = cluster.account_nodes[node_id].host
                    assert host is not None
                    ordered = (stopped_id, *tuple(peer_id for peer_id in cluster.consensus_ids if peer_id != stopped_id))
                    host.set_consensus_peer_ids(ordered)

                cluster.run_random_rounds(tx_count=40, rotate_sender_primary=False)
                degraded_snapshot = cluster.snapshot()
                self.assertEqual(degraded_snapshot["confirmed_tx_count"], HEAVY_FAILOVER_PROFILE.tx_count)
                self.assertEqual(degraded_snapshot["failed_tx_count"], 0)
                for account in degraded_snapshot["accounts"].values():
                    self.assertNotEqual(account["consensus_peer_id"], stopped_id)

                cluster.restart_consensus(stopped_id)
                cluster.recover_all_accounts()
                final_snapshot = cluster.snapshot()
                assert_cluster_converged(final_snapshot)
                assert_supply_conserved(final_snapshot, HEAVY_FAILOVER_PROFILE.total_supply)
                assert_no_pending_leaks(final_snapshot)
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()

