from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.v2_two_host_cluster import (
    _pid_running,
    _build_role_specs,
    _build_topology,
    _materialize_wallets,
    _run_tx_batch,
    _topology_from_args,
)


class V2TwoHostClusterTests(unittest.TestCase):
    def test_pid_running_treats_permission_error_as_alive(self) -> None:
        with patch("scripts.v2_two_host_cluster.os.kill", side_effect=PermissionError("nope")):
            self.assertTrue(_pid_running(123))

    def test_topology_from_args_matches_cli_shape(self) -> None:
        class Args:
            cluster_name = "demo-cli"
            chain_id = 821
            mac_consensus_count = 3
            mac_account_count = 2
            ecs_consensus_count = 4
            ecs_account_count = 5
            mac_consensus_host = "100.90.152.124"
            mac_account_host = "100.90.152.124"
            ecs_consensus_host = "118.178.171.23"
            ecs_account_host = "118.178.171.23"
            genesis_amount = 500
            consensus_base_port = 19500
            account_base_port = 19600
            mac_consensus_base_port = -1
            ecs_consensus_base_port = 29500
            mac_account_base_port = -1
            ecs_account_base_port = 29600

        topology = _topology_from_args(Args())
        self.assertEqual(topology["cluster_name"], "demo-cli")
        self.assertEqual(topology["cluster_dir"], ".ezchain-twohost/demo-cli")
        self.assertEqual(topology["consensus_nodes"][0]["endpoint"], "100.90.152.124:19500")
        self.assertEqual(topology["consensus_nodes"][3]["endpoint"], "118.178.171.23:29500")
        self.assertEqual(topology["account_nodes"][0]["endpoint"], "100.90.152.124:19600")
        self.assertEqual(topology["account_nodes"][2]["consensus_endpoint"], "127.0.0.1:29500")

    def test_build_topology_uses_requested_per_host_counts(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=3,
            mac_account_count=2,
            ecs_consensus_count=4,
            ecs_account_count=5,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )

        self.assertEqual(len(topology["consensus_nodes"]), 7)
        self.assertEqual(len(topology["account_nodes"]), 7)
        self.assertEqual(len([n for n in topology["consensus_nodes"] if n["role"] == "mac"]), 3)
        self.assertEqual(len([n for n in topology["consensus_nodes"] if n["role"] == "ecs"]), 4)
        self.assertEqual(len([n for n in topology["account_nodes"] if n["role"] == "mac"]), 2)
        self.assertEqual(len([n for n in topology["account_nodes"] if n["role"] == "ecs"]), 5)
        self.assertEqual(len(topology["genesis_allocations"]), 7)
        self.assertEqual(topology["cluster_dir"], ".ezchain-twohost/demo")
        self.assertEqual(topology["consensus_nodes"][0]["endpoint"], "100.90.152.124:19500")
        self.assertEqual(topology["consensus_nodes"][3]["endpoint"], "118.178.171.23:29500")
        self.assertEqual(topology["account_nodes"][0]["consensus_endpoint"], "127.0.0.1:19500")
        self.assertEqual(topology["account_nodes"][2]["consensus_endpoint"], "127.0.0.1:29500")

    def test_build_role_specs_for_mac_uses_generated_topology(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=2,
            mac_account_count=2,
            ecs_consensus_count=2,
            ecs_account_count=1,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )
        with tempfile.TemporaryDirectory() as td:
            specs = _build_role_specs(
                project_root=Path(td),
                topology=topology,
                role="mac",
                network_timeout_sec=20.0,
                reset_account_ephemeral_state=True,
                reset_account_derived_state=True,
            )

        self.assertEqual(len([spec for spec in specs if spec.kind == "consensus"]), 2)
        self.assertEqual(len([spec for spec in specs if spec.kind == "account"]), 2)
        self.assertTrue(all("--genesis-allocations-file" in spec.command for spec in specs if spec.kind == "consensus"))
        self.assertTrue(all("--consensus-peer-id" in spec.command for spec in specs if spec.kind == "account"))

    def test_materialize_wallets_creates_local_wallet_files_for_role(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=2,
            mac_account_count=2,
            ecs_consensus_count=1,
            ecs_account_count=1,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td)
            created = _materialize_wallets(project_root, topology, role="mac", password="pw123")

            self.assertEqual(len(created), 2)
            for account in topology["account_nodes"]:
                wallet_file = project_root / account["wallet_file"]
                if account["role"] == "mac":
                    self.assertTrue(wallet_file.exists())
                else:
                    self.assertFalse(wallet_file.exists())

    def test_run_tx_batch_enriches_state_with_all_account_peers(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=2,
            mac_account_count=2,
            ecs_consensus_count=1,
            ecs_account_count=1,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )
        captured: dict[str, object] = {}
        balance_calls: dict[str, int] = {}

        class FakeStore:
            def __init__(self, path: str):
                self.path = path

        class FakeEngine:
            def __init__(self, *args, **kwargs):
                return None

            def remote_balance(self, store, password: str, state):
                node_id = Path(store.path).name
                balance_calls[node_id] = balance_calls.get(node_id, 0) + 1
                if balance_calls[node_id] == 1:
                    return {"available_balance": 100, "pending_bundle_count": 0}
                return {"available_balance": 90, "pending_bundle_count": 0}

            def remote_send(self, store, password: str, *, recipient, amount, recipient_endpoint, state, client_tx_id):
                captured["state"] = state
                captured["recipient_endpoint"] = recipient_endpoint
                return type(
                    "Result",
                    (),
                    {
                        "status": "submitted",
                        "receipt_height": None,
                        "tx_hash": "tx",
                        "submit_hash": "submit",
                    },
                )()

        def fake_state(path: Path):
            return {
                "address": "0xsender",
                "pending_bundle_count": 0,
                "consensus_endpoint": "127.0.0.1:19500",
                "wallet_db_path": "wallet.db",
            }

        with tempfile.TemporaryDirectory() as td, patch("scripts.v2_two_host_cluster.WalletStore", FakeStore), patch(
            "scripts.v2_two_host_cluster.TxEngine", FakeEngine
        ), patch("scripts.v2_two_host_cluster._safe_read_json", side_effect=fake_state):
            result = _run_tx_batch(
                project_root=Path(td),
                topology=topology,
                role="mac",
                password="pw123",
                tx_count=1,
                max_amount=50,
                seed=7,
                settle_timeout_sec=0.1,
                settle_grace_sec=0.0,
                stop_on_failure=True,
            )

        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["failed"], 0)
        account_peers = captured["state"]["account_peers"]
        self.assertEqual(len(account_peers), len(topology["account_nodes"]))
        self.assertIn(
            {
                "node_id": topology["account_nodes"][-1]["node_id"],
                "address": topology["account_nodes"][-1]["address"],
                "endpoint": topology["account_nodes"][-1]["endpoint"],
            },
            account_peers,
        )

    def test_run_tx_batch_waits_for_pending_bundle_to_settle(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=2,
            mac_account_count=2,
            ecs_consensus_count=1,
            ecs_account_count=1,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )
        balance_calls: dict[str, int] = {}

        class FakeStore:
            def __init__(self, path: str):
                self.path = path

        class FakeEngine:
            def __init__(self, *args, **kwargs):
                return None

            def remote_balance(self, store, password: str, state):
                node_id = Path(store.path).name
                balance_calls[node_id] = balance_calls.get(node_id, 0) + 1
                if balance_calls[node_id] == 1:
                    return {"available_balance": 100, "pending_bundle_count": 0}
                if balance_calls[node_id] == 2:
                    return {"available_balance": 50, "pending_bundle_count": 1}
                return {"available_balance": 50, "pending_bundle_count": 0}

            def remote_send(self, store, password: str, *, recipient, amount, recipient_endpoint, state, client_tx_id):
                return type(
                    "Result",
                    (),
                    {
                        "status": "submitted",
                        "receipt_height": None,
                        "tx_hash": "tx",
                        "submit_hash": "submit",
                    },
                )()

        def fake_state(path: Path):
            return {
                "address": "0xsender",
                "pending_bundle_count": 0,
                "consensus_endpoint": "127.0.0.1:19500",
                "wallet_db_path": "wallet.db",
            }

        with tempfile.TemporaryDirectory() as td, patch("scripts.v2_two_host_cluster.WalletStore", FakeStore), patch(
            "scripts.v2_two_host_cluster.TxEngine", FakeEngine
        ), patch("scripts.v2_two_host_cluster._safe_read_json", side_effect=fake_state):
            result = _run_tx_batch(
                project_root=Path(td),
                topology=topology,
                role="mac",
                password="pw123",
                tx_count=1,
                max_amount=50,
                seed=9,
                settle_timeout_sec=0.5,
                settle_grace_sec=0.0,
                stop_on_failure=True,
            )

        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(max(balance_calls.values()), 3)

    def test_run_tx_batch_reports_preflight_failures_before_sending(self) -> None:
        topology = _build_topology(
            cluster_name="demo",
            chain_id=821,
            mac_consensus_count=2,
            mac_account_count=2,
            ecs_consensus_count=1,
            ecs_account_count=1,
            mac_consensus_host="100.90.152.124",
            mac_account_host="100.90.152.124",
            ecs_consensus_host="118.178.171.23",
            ecs_account_host="118.178.171.23",
            genesis_amount=500,
            mac_consensus_base_port=19500,
            ecs_consensus_base_port=29500,
            mac_account_base_port=19600,
            ecs_account_base_port=29600,
        )

        with tempfile.TemporaryDirectory() as td, patch(
            "scripts.v2_two_host_cluster._preflight",
            return_value={
                "role": "mac",
                "all_reachable": False,
                "probes": [{"endpoint": "118.178.171.23:29600", "ok": False, "error": "TimeoutError:timed out"}],
            },
        ):
            result = _run_tx_batch(
                project_root=Path(td),
                topology=topology,
                role="mac",
                password="pw123",
                tx_count=3,
                max_amount=50,
                seed=1,
                settle_timeout_sec=0.1,
                settle_grace_sec=0.0,
                stop_on_failure=True,
            )

        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["failures"][0]["error"], "remote_endpoints_unreachable")


if __name__ == "__main__":
    unittest.main()
