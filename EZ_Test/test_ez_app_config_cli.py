import tempfile
from pathlib import Path

from EZ_App.cli import main
from EZ_App.config import load_api_token, load_config


def test_load_config_yaml_subset():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ezchain.yaml"
        p.write_text(
            (
                "network:\n  name: testnet\n  start_port: 19999\n"
                "app:\n  data_dir: .tmp_ez\n  api_port: 8899\n"
                "security:\n  max_payload_bytes: 4096\n"
            ),
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.network.start_port == 19999
        assert cfg.app.api_port == 8899
        assert cfg.security.max_payload_bytes == 4096


def test_cli_wallet_create_show():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        log_dir = data_dir / "logs"
        token_file = data_dir / "api.token"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\napp:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {log_dir}\n"
                f"  api_token_file: {token_file}\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        code = main(["--config", str(cfg_path), "wallet", "create", "--password", "pw123", "--name", "demo"])
        assert code == 0
        code = main(["--config", str(cfg_path), "wallet", "show"])
        assert code == 0

        cfg = load_config(cfg_path)
        token = load_api_token(cfg)
        assert len(token) > 10
