from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.daemon_harness import LocalTCPDaemonCluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import APP_USERFLOW_PROFILE
from EZ_V2.types import CheckpointAnchor, PriorWitnessLink, WitnessV2
from EZ_V2.wallet import WalletAccountV2


def _witness_contains_checkpoint_anchor(witness: WitnessV2) -> bool:
    anchor = witness.anchor
    if isinstance(anchor, CheckpointAnchor):
        return True
    if isinstance(anchor, PriorWitnessLink):
        return _witness_contains_checkpoint_anchor(anchor.prior_witness)
    return False


def _open_wallet(cluster: LocalTCPDaemonCluster, name: str) -> WalletAccountV2:
    state = cluster.read_account_state(name)
    return WalletAccountV2(
        address=cluster.account_specs[name].address,
        genesis_block_hash=b"\x00" * 32,
        db_path=str(state["wallet_db_path"]),
    )


class LocalTCPAppMultiRoundUserflowTests(unittest.TestCase):
    def test_app_tcp_multi_round_userflow_keeps_receipts_history_and_checkpoint_paths_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = LocalTCPDaemonCluster(root_dir=td, profile=APP_USERFLOW_PROFILE)
            try:
                cluster.start()

                first = cluster.send("alice", "bob", amount=150, client_tx_id="userflow-round-1")
                second = cluster.send("bob", "carol", amount=150, client_tx_id="userflow-round-2")
                checkpoint = cluster.create_checkpoint_from_latest_archived("bob")
                third = cluster.send("carol", "bob", amount=150, client_tx_id="userflow-round-3")
                fourth = cluster.send("bob", "alice", amount=75, client_tx_id="userflow-round-4")

                self.assertEqual(
                    [first.receipt_height, second.receipt_height, third.receipt_height, fourth.receipt_height],
                    [1, 2, 3, 4],
                )
                self.assertEqual(checkpoint["checkpoint_height"], 2)

                carol_wallet = _open_wallet(cluster, "carol")
                try:
                    unit = carol_wallet.db.get_confirmed_unit(cluster.account_specs["carol"].address, 1)
                    self.assertIsNotNone(unit)
                    tx = unit.bundle_sidecar.tx_list[0]
                    package = carol_wallet.export_transfer_package(tx, tx.value_list[0])
                    self.assertTrue(_witness_contains_checkpoint_anchor(package.witness_v2))
                finally:
                    carol_wallet.close()

                bob_wallet = _open_wallet(cluster, "bob")
                try:
                    partial_unit = bob_wallet.db.get_confirmed_unit(cluster.account_specs["bob"].address, 2)
                    self.assertIsNotNone(partial_unit)
                    partial_tx = partial_unit.bundle_sidecar.tx_list[0]
                    partial_package = bob_wallet.export_transfer_package(partial_tx, partial_tx.value_list[0])
                    self.assertFalse(_witness_contains_checkpoint_anchor(partial_package.witness_v2))
                finally:
                    bob_wallet.close()

                balances_before_restart = {name: cluster.balance(name) for name in APP_USERFLOW_PROFILE.account_names}
                receipts_before_restart = {name: cluster.receipts(name) for name in APP_USERFLOW_PROFILE.account_names}
                histories_before_restart = {name: cluster.history(name) for name in APP_USERFLOW_PROFILE.account_names}
                checkpoints_before_restart = cluster.checkpoints("bob")

                cluster.restart_account("bob")
                cluster.restart_consensus("consensus-2")

                balances_after_restart = {name: cluster.balance(name) for name in APP_USERFLOW_PROFILE.account_names}
                receipts_after_restart = {name: cluster.receipts(name) for name in APP_USERFLOW_PROFILE.account_names}
                histories_after_restart = {name: cluster.history(name) for name in APP_USERFLOW_PROFILE.account_names}
                checkpoints_after_restart = cluster.checkpoints("bob")

                self.assertEqual(
                    {name: view["available_balance"] for name, view in balances_after_restart.items()},
                    {name: view["available_balance"] for name, view in balances_before_restart.items()},
                )
                self.assertEqual(
                    {name: len(view["items"]) for name, view in receipts_after_restart.items()},
                    {name: len(view["items"]) for name, view in receipts_before_restart.items()},
                )
                self.assertEqual(checkpoints_after_restart["items"], checkpoints_before_restart["items"])
                for name in APP_USERFLOW_PROFILE.account_names:
                    self.assertEqual(len(histories_after_restart[name]["items"]), len(histories_before_restart[name]["items"]))

                fifth = cluster.send("alice", "bob", amount=20, client_tx_id="userflow-round-5")
                sixth = cluster.send("alice", "bob", amount=30, client_tx_id="userflow-round-6")
                seventh = cluster.send("bob", "carol", amount=125, client_tx_id="userflow-round-7")
                self.assertEqual(
                    [fifth.receipt_height, sixth.receipt_height, seventh.receipt_height],
                    [5, 6, 7],
                )

                bob_wallet = _open_wallet(cluster, "bob")
                try:
                    composed_unit = bob_wallet.db.get_confirmed_unit(cluster.account_specs["bob"].address, 3)
                    self.assertIsNotNone(composed_unit)
                    composed_tx = composed_unit.bundle_sidecar.tx_list[0]
                    self.assertEqual(len(composed_tx.value_list), 3)
                finally:
                    bob_wallet.close()

                final_balances = {name: cluster.balance(name) for name in APP_USERFLOW_PROFILE.account_names}
                final_receipts = {name: cluster.receipts(name) for name in APP_USERFLOW_PROFILE.account_names}
                final_histories = {name: cluster.history(name) for name in APP_USERFLOW_PROFILE.account_names}

                self.assertEqual(final_balances["alice"]["available_balance"], 875)
                self.assertEqual(final_balances["bob"]["available_balance"], 0)
                self.assertEqual(final_balances["carol"]["available_balance"], 125)
                self.assertEqual(len(final_receipts["alice"]["items"]), 3)
                self.assertEqual(len(final_receipts["bob"]["items"]), 3)
                self.assertEqual(len(final_receipts["carol"]["items"]), 1)
                for name in APP_USERFLOW_PROFILE.account_names:
                    self.assertGreaterEqual(
                        len(final_histories[name]["items"]),
                        len(histories_after_restart[name]["items"]),
                    )
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
