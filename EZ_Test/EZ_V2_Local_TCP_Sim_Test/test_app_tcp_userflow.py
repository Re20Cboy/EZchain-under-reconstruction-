from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import assert_userflow_history_and_receipts
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.daemon_harness import LocalTCPDaemonCluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import APP_USERFLOW_PROFILE


class LocalTCPAppUserflowTests(unittest.TestCase):
    def test_app_tcp_userflow_survives_restart_and_keeps_history_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = LocalTCPDaemonCluster(root_dir=td, profile=APP_USERFLOW_PROFILE)
            try:
                cluster.start()

                first = cluster.send("alice", "bob", amount=150, client_tx_id="app-round-1")
                second = cluster.send("bob", "carol", amount=150, client_tx_id="app-round-2")
                checkpoint = cluster.create_checkpoint_from_latest_archived("bob")
                third = cluster.send("carol", "alice", amount=40, client_tx_id="app-round-3")

                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(checkpoint["checkpoint_height"], 2)

                balances_before = {name: cluster.balance(name) for name in APP_USERFLOW_PROFILE.account_names}
                receipts_before = {name: cluster.receipts(name) for name in APP_USERFLOW_PROFILE.account_names}
                histories_before = {name: cluster.history(name) for name in APP_USERFLOW_PROFILE.account_names}
                checkpoints_before = cluster.checkpoints("bob")

                self.assertEqual(balances_before["alice"]["available_balance"], 890)
                self.assertEqual(balances_before["bob"]["available_balance"], 0)
                self.assertEqual(balances_before["carol"]["available_balance"], 110)
                self.assertEqual(len(checkpoints_before["items"]), 1)
                assert_userflow_history_and_receipts(
                    history_views=histories_before,
                    receipt_views=receipts_before,
                    expected_users=APP_USERFLOW_PROFILE.account_names,
                    expected_receipt_count=1,
                )

                for name in APP_USERFLOW_PROFILE.account_names:
                    cluster.restart_account(name)

                balances_after = {name: cluster.balance(name) for name in APP_USERFLOW_PROFILE.account_names}
                receipts_after = {name: cluster.receipts(name) for name in APP_USERFLOW_PROFILE.account_names}
                histories_after = {name: cluster.history(name) for name in APP_USERFLOW_PROFILE.account_names}
                checkpoints_after = cluster.checkpoints("bob")

                self.assertEqual(
                    {name: view["available_balance"] for name, view in balances_after.items()},
                    {name: view["available_balance"] for name, view in balances_before.items()},
                )
                self.assertEqual(
                    {name: len(view["items"]) for name, view in receipts_after.items()},
                    {name: len(view["items"]) for name, view in receipts_before.items()},
                )
                self.assertEqual(checkpoints_after["items"], checkpoints_before["items"])
                for name in APP_USERFLOW_PROFILE.account_names:
                    self.assertGreaterEqual(len(histories_after[name]["items"]), len(histories_before[name]["items"]))
                    self.assertEqual(len(histories_after[name]["items"]), len(histories_before[name]["items"]))
                assert_userflow_history_and_receipts(
                    history_views=histories_after,
                    receipt_views=receipts_after,
                    expected_users=APP_USERFLOW_PROFILE.account_names,
                    expected_receipt_count=1,
                )
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
