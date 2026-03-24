from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v2_multi_host_cluster import build_role_specs


class V2MultiHostClusterScriptTests(unittest.TestCase):
    def test_build_role_specs_for_mac_includes_two_consensus_and_one_account(self) -> None:
        specs = build_role_specs(
            role="mac",
            project_root=Path("/tmp/ezchain"),
            chain_id=821,
            mac_ip="100.90.152.124",
            ecs_ip="100.119.113.49",
            reset_account_ephemeral_state=True,
            reset_account_derived_state=True,
        )

        self.assertEqual([spec.name for spec in specs], ["consensus-0", "consensus-1", "mac-account"])
        self.assertIn("--listen-host", specs[0].command)
        self.assertIn("--auto-run-mvp-consensus", specs[0].command)
        self.assertIn("--reset-ephemeral-state", specs[2].command)
        self.assertIn("--reset-derived-state", specs[2].command)
        self.assertIn(".ezchain-mac-account-store/wallet.json", specs[2].command)

    def test_build_role_specs_for_ecs_includes_two_consensus_and_one_account(self) -> None:
        specs = build_role_specs(
            role="ecs",
            project_root=Path("/tmp/ezchain"),
            chain_id=821,
            mac_ip="100.90.152.124",
            ecs_ip="100.119.113.49",
            reset_account_ephemeral_state=False,
            reset_account_derived_state=False,
        )

        self.assertEqual([spec.name for spec in specs], ["consensus-2", "consensus-3", "ecs-account"])
        self.assertNotIn("--reset-ephemeral-state", specs[2].command)
        self.assertNotIn("--reset-derived-state", specs[2].command)
        self.assertIn("100.119.113.49:19500", specs[0].command)
        self.assertIn("consensus-0=100.90.152.124:19500", specs[0].command)


if __name__ == "__main__":
    unittest.main()
