from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "v2_capacity_model.py"


class V2CapacityModelScriptTests(unittest.TestCase):
    def test_script_emits_json_projection(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--node-count",
                "100000",
                "--consensus-nodes",
                "7",
                "--years",
                "0.25",
                "--tx-per-second",
                "2",
                "--bundles-per-block-target",
                "50",
                "--avg-transfer-hops",
                "4",
                "--checkpoint-interval-hops",
                "2",
                "--json-output",
            ],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["projection"]["effective_witness_hops"], 2)
        self.assertLessEqual(payload["projection"]["actual_bundles_per_block"], 4.0)
        self.assertGreater(payload["samples"]["receipt"]["json"], payload["samples"]["receipt"]["binary"])
        self.assertGreater(payload["projection"]["user_storage_json"]["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
