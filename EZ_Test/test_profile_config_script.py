from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_profile_config_writes_official_template():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "official.yaml"
        code, stdout, _ = _run(
            [
                sys.executable,
                "scripts/profile_config.py",
                "--profile",
                "official-testnet",
                "--out",
                str(out),
            ],
            cwd=repo_root,
        )
        assert code == 0
        payload = json.loads(stdout)
        assert payload["status"] == "ok"
        assert payload["profile"] == "official-testnet"
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert 'consensus_nodes: 3' in text
        assert 'bootstrap_nodes: ["bootstrap.ezchain.test:19500"]' in text


def test_profile_config_refuses_overwrite_without_force():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "ezchain.yaml"
        out.write_text("network:\n  name: keep-me\n", encoding="utf-8")

        code, _, stderr = _run(
            [
                sys.executable,
                "scripts/profile_config.py",
                "--profile",
                "local-dev",
                "--out",
                str(out),
            ],
            cwd=repo_root,
        )
        assert code != 0
        assert "target_exists" in stderr

        code, stdout, _ = _run(
            [
                sys.executable,
                "scripts/profile_config.py",
                "--profile",
                "local-dev",
                "--out",
                str(out),
                "--force",
            ],
            cwd=repo_root,
        )
        assert code == 0
        payload = json.loads(stdout)
        assert payload["overwritten"] is True
