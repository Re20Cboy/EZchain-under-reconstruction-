import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from EZ_App.cli import main
from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


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


def test_node_manager_v2_localnet_reports_embedded_backend_state():
    with tempfile.TemporaryDirectory() as td:
        manager = NodeManager(data_dir=td, project_root=str(Path(__file__).resolve().parent.parent))
        started = manager.start(mode="v2-localnet", network_name="testnet")
        assert started["status"] == "started"
        assert started["mode"] == "v2-localnet"
        assert int(started["pid"]) > 0

        wallet_store = WalletStore(td)
        wallet_store.create_wallet(password="pw123", name="demo")
        engine = TxEngine(td, protocol_version="v2")
        engine.faucet(wallet_store, password="pw123", amount=200)
        result = engine.send(wallet_store, password="pw123", recipient="0xabc123", amount=50, client_tx_id="cid-node-v2")
        assert result.receipt_height == 1

        status = manager.status()
        assert status["status"] == "running"
        assert status["mode"] == "v2-localnet"
        assert status["backend"]["height"] == 1
        assert status["backend"]["chain_id"] == 1
        assert status["backend"]["current_block_hash"]

        stopped = manager.stop()
        assert stopped["status"] == "stopped"
        assert stopped["mode"] == "v2-localnet"


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
