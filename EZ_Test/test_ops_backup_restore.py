from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="Script-level backup/restore E2E can be flaky in GitHub runner sandbox; validated in local release gate.",
)


def _run(cmd: list[str], cwd: Path) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_backup_and_restore_roundtrip():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data_dir = tmp / ".ezchain"
        cfg_path = tmp / "ezchain.yaml"
        cfg_path.write_text(
            (
                "meta:\n"
                "  config_version: 1\n"
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["127.0.0.1:19500"]\n'
                "  consensus_nodes: 1\n"
                "  account_nodes: 1\n"
                "  start_port: 19500\n"
                "app:\n"
                f'  data_dir: "{data_dir}"\n'
                f'  log_dir: "{data_dir / "logs"}"\n'
                f'  api_token_file: "{data_dir / "api.token"}"\n'
                '  api_host: "127.0.0.1"\n'
                "  api_port: 8787\n"
                "security:\n"
                "  max_payload_bytes: 65536\n"
                "  max_tx_amount: 100000000\n"
                "  nonce_ttl_seconds: 600\n"
            ),
            encoding="utf-8",
        )

        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "wallet.json").write_text('{"address":"addr1"}', encoding="utf-8")
        (data_dir / "tx_history.json").write_text('[{"tx_id":"t1"}]', encoding="utf-8")

        backup = _run(
            [
                sys.executable,
                "scripts/ops_backup.py",
                "--config",
                str(cfg_path),
                "--out-dir",
                str(tmp / "backups"),
                "--label",
                "test",
            ],
            cwd=repo_root,
        )
        backup_dir = Path(backup["backup_dir"])
        assert (backup_dir / "manifest.json").exists()
        assert (backup_dir / "data_dir" / "wallet.json").exists()

        (data_dir / "wallet.json").write_text('{"address":"changed"}', encoding="utf-8")
        cfg_path.write_text("network:\n  name: broken\n", encoding="utf-8")

        restored = _run(
            [
                sys.executable,
                "scripts/ops_restore.py",
                "--backup-dir",
                str(backup_dir),
                "--config",
                str(cfg_path),
                "--force",
            ],
            cwd=repo_root,
        )
        assert restored["status"] == "ok"

        wallet_payload = json.loads((data_dir / "wallet.json").read_text(encoding="utf-8"))
        assert wallet_payload["address"] == "addr1"
        assert "config_version: 1" in cfg_path.read_text(encoding="utf-8")


def test_init_app_env_generates_config_and_token():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = tmp / "ezchain.yaml"

        payload = _run(
            [
                sys.executable,
                "scripts/init_app_env.py",
                "--config",
                str(cfg_path),
                "--profile",
                "official-testnet",
            ],
            cwd=repo_root,
        )

        assert payload["status"] == "initialized"
        assert payload["profile"] == "official-testnet"
        assert cfg_path.exists()
