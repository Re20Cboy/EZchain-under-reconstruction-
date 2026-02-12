import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from EZ_App.cli import main
from EZ_App.node_manager import NodeManager


def test_node_manager_probe_bootstrap_mixed():
    with tempfile.TemporaryDirectory() as td:
        manager = NodeManager(data_dir=td, project_root=td)

        def fake_create_connection(address, timeout=0):
            if address == ("127.0.0.1", 11111):
                class _Conn:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                return _Conn()
            raise ConnectionRefusedError("mock-refused")

        with patch("EZ_App.node_manager.socket.create_connection", side_effect=fake_create_connection):
            result = manager.probe_bootstrap(["127.0.0.1:11111", "127.0.0.1:1"], timeout_sec=0.2)

        assert result["total"] == 2
        assert result["reachable"] == 1
        assert result["unreachable"] == 1
        assert len(result["checked"]) == 2


def test_node_manager_official_testnet_mode_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        manager = NodeManager(data_dir=td, project_root=td)
        started = manager.start(
            mode="official-testnet",
            bootstrap_nodes=["127.0.0.1:1"],
            network_name="testnet",
        )
        assert started["status"] == "started_external"

        status = manager.status(bootstrap_nodes=["127.0.0.1:1"])
        assert status["status"] == "running"
        assert status["mode"] == "official-testnet"
        assert "bootstrap_probe" in status

        stopped = manager.stop()
        assert stopped["status"] == "stopped"


def test_cli_network_check_output(capsys):
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezchain"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["127.0.0.1:1"]\n'
                "  consensus_nodes: 3\n"
                "  account_nodes: 1\n"
                "  start_port: 19500\n"
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_host: 127.0.0.1\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        code = main(["--config", str(cfg_path), "network", "check"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["network"] == "testnet"
        assert "bootstrap_probe" in payload
        assert payload["bootstrap_probe"]["total"] == 1
