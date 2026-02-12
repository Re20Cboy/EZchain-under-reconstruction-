from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> tuple[int, dict]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    output = proc.stdout.strip()
    parsed = {}
    if output:
        first = output.find("{")
        last = output.rfind("}")
        if first >= 0 and last > first:
            parsed = json.loads(output[first : last + 1])
    return proc.returncode, parsed


def test_testnet_profile_gate_passes_for_official_shape():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "ezchain.yaml"
        cfg.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["bootstrap.ezchain.test:19500"]\n'
                "  consensus_nodes: 3\n"
                "  account_nodes: 1\n"
                "  start_port: 19500\n"
                "app:\n"
                f'  data_dir: "{Path(td) / ".ezchain"}"\n'
                f'  log_dir: "{Path(td) / ".ezchain" / "logs"}"\n'
                f'  api_token_file: "{Path(td) / ".ezchain" / "api.token"}"\n'
                '  api_host: "127.0.0.1"\n'
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )
        code, payload = _run([sys.executable, "scripts/testnet_profile_gate.py", "--config", str(cfg)], cwd=root)
        assert code == 0
        assert payload["ok"] is True


def test_testnet_profile_gate_fails_for_loopback_bootstrap():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "ezchain.yaml"
        cfg.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["127.0.0.1:19500"]\n'
                "  consensus_nodes: 3\n"
                "  account_nodes: 1\n"
                "  start_port: 19500\n"
            ),
            encoding="utf-8",
        )
        code, payload = _run([sys.executable, "scripts/testnet_profile_gate.py", "--config", str(cfg)], cwd=root)
        assert code == 1
        assert payload["ok"] is False
        assert any("non-loopback" in item for item in payload["failures"])


def test_testnet_profile_gate_fails_for_wrong_topology():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "ezchain.yaml"
        cfg.write_text(
            (
                "network:\n"
                '  name: "testnet-local"\n'
                '  bootstrap_nodes: ["bootstrap.ezchain.test:19500"]\n'
                "  consensus_nodes: 1\n"
                "  account_nodes: 1\n"
                "  start_port: 19500\n"
            ),
            encoding="utf-8",
        )
        code, payload = _run([sys.executable, "scripts/testnet_profile_gate.py", "--config", str(cfg)], cwd=root)
        assert code == 1
        assert payload["ok"] is False
        assert any("consensus_nodes must be 3" in item for item in payload["failures"])
