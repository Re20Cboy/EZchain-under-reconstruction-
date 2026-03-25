from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v2_two_host_cluster import _build_role_specs, _build_topology, _materialize_wallets


class V2TwoHostClusterTests(unittest.TestCase):
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
            consensus_base_port=19500,
            account_base_port=19600,
        )

        self.assertEqual(len(topology["consensus_nodes"]), 7)
        self.assertEqual(len(topology["account_nodes"]), 7)
        self.assertEqual(len([n for n in topology["consensus_nodes"] if n["role"] == "mac"]), 3)
        self.assertEqual(len([n for n in topology["consensus_nodes"] if n["role"] == "ecs"]), 4)
        self.assertEqual(len([n for n in topology["account_nodes"] if n["role"] == "mac"]), 2)
        self.assertEqual(len([n for n in topology["account_nodes"] if n["role"] == "ecs"]), 5)
        self.assertEqual(len(topology["genesis_allocations"]), 7)

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
            consensus_base_port=19500,
            account_base_port=19600,
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
            consensus_base_port=19500,
            account_base_port=19600,
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


if __name__ == "__main__":
    unittest.main()
