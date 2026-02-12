import json
import tempfile
from pathlib import Path

from EZ_App.cli import main
from EZ_App.config import load_config
from EZ_App.profiles import apply_network_profile, list_profiles


def test_list_profiles_contains_expected():
    profiles = list_profiles()
    assert "local-dev" in profiles
    assert "official-testnet" in profiles


def test_apply_network_profile_updates_config_file():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        cfg_path.write_text("network:\n  name: testnet\n", encoding="utf-8")

        cfg = apply_network_profile(cfg_path, "official-testnet")
        assert cfg.network.consensus_nodes == 3
        assert cfg.network.bootstrap_nodes == ["bootstrap.ezchain.test:19500"]

        loaded = load_config(cfg_path)
        assert loaded.network.consensus_nodes == 3


def test_cli_network_profile_flow(capsys):
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezchain"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\n"
                f"app:\n  data_dir: {data_dir}\n  log_dir: {data_dir / 'logs'}\n  api_token_file: {data_dir / 'api.token'}\n"
            ),
            encoding="utf-8",
        )

        code = main(["--config", str(cfg_path), "network", "set-profile", "--name", "official-testnet"])
        assert code == 0

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["profile"] == "official-testnet"
        assert parsed["consensus_nodes"] == 3

        code = main(["--config", str(cfg_path), "network", "info"])
        assert code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["bootstrap_nodes"] == ["bootstrap.ezchain.test:19500"]
