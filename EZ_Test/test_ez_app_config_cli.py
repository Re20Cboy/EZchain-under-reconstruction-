import tempfile
import json
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout
from unittest import mock

from EZ_App.cli import main
from EZ_App.config import CONFIG_SCHEMA_VERSION, load_api_token, load_config
from EZ_App.runtime import TxEngine, TxResult
from EZ_App.wallet_store import WalletStore


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


def test_cli_config_migrate_legacy_file():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        cfg_path.write_text(
            (
                "network:\n"
                "  name: testnet\n"
                "app:\n"
                "  data_dir: .ezchain\n"
            ),
            encoding="utf-8",
        )

        code = main(["--config", str(cfg_path), "config", "migrate"])
        assert code == 0

        migrated = cfg_path.read_text(encoding="utf-8")
        assert "meta:" in migrated
        assert f"config_version: {CONFIG_SCHEMA_VERSION}" in migrated
        assert "security:" in migrated
        assert "api_token_file:" in migrated

        backups = list(Path(td).glob("ezchain.yaml.bak.*"))
        assert len(backups) == 1


def test_cli_node_account_status_reports_not_running():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\napp:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--config", str(cfg_path), "node", "account-status"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["status"] == "not_running"
        assert payload["reason"] == "v2_account_not_running"
        assert payload["mode_family"] == "v2-account"


def test_cli_node_account_status_keeps_sync_health_fields():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\napp:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": "0xabc123",
            "consensus_endpoint": "127.0.0.1:19500",
            "last_sync_ok": False,
            "sync_health": "degraded",
            "sync_health_reason": "consensus_sync_failed",
            "consecutive_sync_failures": 2,
        }

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with redirect_stdout(out):
                code = main(["--config", str(cfg_path), "node", "account-status"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["sync_health"] == "degraded"
        assert payload["sync_health_reason"] == "consensus_sync_failed"
        assert payload["consecutive_sync_failures"] == 2


def test_cli_blocks_remote_v2_tx_commands_until_tx_path_is_ready():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--config", str(cfg_path), "tx", "faucet", "--password", "pw123", "--amount", "100"])
        assert code == 2
        payload = json.loads(out.getvalue())
        assert payload["error"]["code"] == "tx_action_unsupported"
        assert payload["mode"] == "official-testnet"
        assert payload["tx_path_ready"] is False
        assert payload["tx_action"] == "tx_faucet"
        assert payload["tx_action_capability"] == "unsupported"


def test_cli_remote_v2_wallet_balance_reads_shared_account_wallet_db():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        address = wallet_store.summary(protocol_version="v2").address
        engine = TxEngine(str(data_dir), protocol_version="v2")
        engine.faucet(wallet_store, password="pw123", amount=120)

        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": address,
            "wallet_db_path": str(data_dir / "wallet_state_v2" / address / "wallet_v2.db"),
            "chain_cursor": {"height": 0, "block_hash_hex": "00" * 32},
            "pending_incoming_transfer_count": 0,
        }

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with redirect_stdout(out):
                code = main(["--config", str(cfg_path), "wallet", "balance", "--password", "pw123"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["address"] == address
        assert payload["available_balance"] == 120
        assert payload["protocol_version"] == "v2"


def test_cli_remote_v2_tx_send_uses_remote_account_path_when_recipient_endpoint_is_given():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        address = wallet_store.summary(protocol_version="v2").address
        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": address,
            "consensus_endpoint": "192.168.1.9:19500",
            "wallet_db_path": str(data_dir / "wallet_state_v2" / address / "wallet_v2.db"),
            "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            "pending_incoming_transfer_count": 0,
        }
        send_result = TxResult(
            tx_hash="0xremotehash",
            submit_hash="0xremotesubmit",
            amount=45,
            recipient="0xabc12345",
            status="confirmed",
            client_tx_id="cid-remote-1",
            receipt_height=2,
            receipt_block_hash="22" * 32,
        )

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with mock.patch("EZ_App.cli.TxEngine.send", return_value=send_result) as send_mock:
                with redirect_stdout(out):
                    code = main(
                        [
                            "--config",
                            str(cfg_path),
                            "tx",
                            "send",
                            "--recipient",
                            "0xabc12345",
                            "--amount",
                            "45",
                            "--password",
                            "pw123",
                            "--client-tx-id",
                            "cid-remote-1",
                            "--recipient-endpoint",
                            "127.0.0.1:19660",
                        ]
                    )
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["status"] == "confirmed"
        assert payload["receipt_height"] == 2
        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        assert kwargs["state"] == remote_state
        assert kwargs["recipient_endpoint"] == "127.0.0.1:19660"


def test_cli_remote_v2_tx_send_requires_running_v2_account():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        WalletStore(str(data_dir)).create_wallet(password="pw123", name="demo")
        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value={"status": "not_running"}):
            with redirect_stdout(out):
                code = main(
                    [
                        "--config",
                        str(cfg_path),
                        "tx",
                        "send",
                        "--recipient",
                        "0xabc12345",
                        "--amount",
                        "45",
                        "--password",
                        "pw123",
                        "--client-tx-id",
                        "cid-remote-preflight-1",
                        "--recipient-endpoint",
                        "127.0.0.1:19660",
                    ]
                )
        assert code == 2
        payload = json.loads(out.getvalue())
        assert payload["error"]["code"] == "remote_account_not_running"
        assert payload["tx_action"] == "tx_send"
        assert payload["tx_action_capability"] == "remote_send"


def test_cli_remote_v2_tx_send_requires_recipient_endpoint_when_contact_missing():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        address = wallet_store.summary(protocol_version="v2").address
        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": address,
            "consensus_endpoint": "192.168.1.9:19500",
            "wallet_db_path": str(data_dir / "wallet_state_v2" / address / "wallet_v2.db"),
            "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            "pending_incoming_transfer_count": 0,
        }

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with redirect_stdout(out):
                code = main(
                    [
                        "--config",
                        str(cfg_path),
                        "tx",
                        "send",
                        "--recipient",
                        "0xabc12345",
                        "--amount",
                        "45",
                        "--password",
                        "pw123",
                        "--client-tx-id",
                        "cid-remote-preflight-2",
                    ]
                )
        assert code == 2
        payload = json.loads(out.getvalue())
        assert payload["error"]["code"] == "recipient_endpoint_required"


def test_cli_remote_v2_tx_send_reports_wallet_address_mismatch():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        address = wallet_store.summary(protocol_version="v2").address
        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": address,
            "consensus_endpoint": "192.168.1.9:19500",
            "wallet_db_path": str(data_dir / "wallet_state_v2" / address / "wallet_v2.db"),
            "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            "pending_incoming_transfer_count": 0,
        }

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with mock.patch("EZ_App.cli.TxEngine.send", side_effect=ValueError("wallet_address_mismatch_with_account_node")):
                with redirect_stdout(out):
                    code = main(
                        [
                            "--config",
                            str(cfg_path),
                            "tx",
                            "send",
                            "--recipient",
                            "0xabc12345",
                            "--amount",
                            "45",
                            "--password",
                            "pw123",
                            "--client-tx-id",
                            "cid-remote-preflight-3",
                            "--recipient-endpoint",
                            "127.0.0.1:19660",
                        ]
                    )
        assert code == 2
        payload = json.loads(out.getvalue())
        assert payload["error"]["code"] == "wallet_address_mismatch_with_account_node"


def test_cli_remote_v2_tx_history_reads_shared_wallet_state():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        alice_dir = data_dir / "alice"
        bob_dir = data_dir / "bob"
        shared_backend = data_dir / "shared_backend"
        alice_store = WalletStore(str(alice_dir))
        bob_store = WalletStore(str(bob_dir))
        alice_store.create_wallet(password="pw123", name="alice")
        bob_store.create_wallet(password="pw123", name="bob")
        alice_engine = TxEngine(str(alice_dir), protocol_version="v2", v2_backend_dir=str(shared_backend))
        bob_engine = TxEngine(str(bob_dir), protocol_version="v2", v2_backend_dir=str(shared_backend))
        bob_addr = bob_store.summary(protocol_version="v2").address
        alice_engine.faucet(alice_store, password="pw123", amount=90)
        alice_engine.send(
            alice_store,
            password="pw123",
            recipient=bob_addr,
            amount=25,
            client_tx_id="cid-cli-history-1",
        )
        bob_engine.balance(bob_store, password="pw123")

        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": bob_addr,
            "wallet_db_path": str(bob_dir / "wallet_state_v2" / bob_addr / "wallet_v2.db"),
            "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            "pending_incoming_transfer_count": 0,
        }

        out = StringIO()
        with mock.patch("EZ_App.cli._build_runtime", return_value=(load_config(cfg_path), bob_store, mock.Mock(), bob_engine)):
            with mock.patch("EZ_App.cli._remote_read_state", return_value=remote_state):
                with redirect_stdout(out):
                    code = main(["--config", str(cfg_path), "tx", "history"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["protocol_version"] == "v2"
        assert payload["chain_height"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["status"] == "received"
        assert payload["items"][0]["amount"] == 25


def test_cli_contacts_set_list_remove_and_remote_send_can_reuse_saved_endpoint():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        address = wallet_store.summary(protocol_version="v2").address

        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "--config",
                    str(cfg_path),
                    "contacts",
                    "set",
                    "--address",
                    "0xpeer100",
                    "--endpoint",
                    "127.0.0.1:19660",
                ]
            )
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["address"] == "0xpeer100"
        assert payload["endpoint"] == "127.0.0.1:19660"
        assert payload["source"] == "manual"

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--config", str(cfg_path), "contacts", "list"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["items"][0]["address"] == "0xpeer100"

        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": address,
            "consensus_endpoint": "192.168.1.9:19500",
            "wallet_db_path": str(data_dir / "wallet_state_v2" / address / "wallet_v2.db"),
            "chain_cursor": {"height": 1, "block_hash_hex": "11" * 32},
            "pending_incoming_transfer_count": 0,
        }
        send_result = TxResult(
            tx_hash="0xremotehash2",
            submit_hash="0xremotesubmit2",
            amount=30,
            recipient="0xpeer100",
            status="confirmed",
            client_tx_id="cid-remote-3",
            receipt_height=2,
            receipt_block_hash="22" * 32,
        )

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with mock.patch("EZ_App.cli.TxEngine.send", return_value=send_result) as send_mock:
                with redirect_stdout(out):
                    code = main(
                        [
                            "--config",
                            str(cfg_path),
                            "tx",
                            "send",
                            "--recipient",
                            "0xpeer100",
                            "--amount",
                            "30",
                            "--password",
                            "pw123",
                            "--client-tx-id",
                            "cid-remote-3",
                        ]
                    )
        assert code == 0
        kwargs = send_mock.call_args.kwargs
        assert kwargs["recipient_endpoint"] == "127.0.0.1:19660"

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--config", str(cfg_path), "contacts", "remove", "--address", "0xpeer100"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["removed"] is True


def test_cli_contacts_export_self_and_import_card():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "official-testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        card_path = Path(td) / "bob-contact.json"
        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": "0xb0b123",
            "endpoint": "192.168.1.20:19500",
            "consensus_endpoint": "192.168.1.9:19500",
        }

        out = StringIO()
        with mock.patch("EZ_App.cli.NodeManager.account_status", return_value=remote_state):
            with redirect_stdout(out):
                code = main(
                    [
                        "--config",
                        str(cfg_path),
                        "contacts",
                        "export-self",
                        "--out",
                        str(card_path),
                    ]
                )
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["written"] is True
        assert card_path.exists()

        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "--config",
                    str(cfg_path),
                    "contacts",
                    "import-card",
                    "--file",
                    str(card_path),
                ]
            )
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["imported"] is True
        assert payload["contact"]["address"] == "0xb0b123"
        assert payload["contact"]["endpoint"] == "192.168.1.20:19500"


def test_cli_contacts_fetch_card_can_write_and_import():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "official-testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        fetched_card = {
            "kind": "ezchain-contact-card/v1",
            "address": "0xcafe123",
            "endpoint": "192.168.1.30:19500",
            "network": "official-testnet",
            "mode_family": "v2-account",
            "exported_at": "2026-03-21T00:00:00Z",
        }
        out_path = Path(td) / "carol-contact.json"

        out = StringIO()
        with mock.patch("EZ_App.cli.fetch_contact_card", return_value=fetched_card):
            with redirect_stdout(out):
                code = main(
                    [
                        "--config",
                        str(cfg_path),
                        "contacts",
                        "fetch-card",
                        "--url",
                        "http://192.168.1.30:8787",
                        "--out",
                        str(out_path),
                        "--import-to-contacts",
                    ]
                )
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["fetched"] is True
        assert payload["written"] is True
        assert payload["imported"] is True
        assert payload["contact"]["address"] == "0xcafe123"
        assert payload["contact"]["source"] == "service_fetch"
        assert out_path.exists()


def test_cli_contacts_show_returns_saved_contact_with_metadata():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezcli"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "official-testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                "  protocol_version: v2\n"
            ),
            encoding="utf-8",
        )

        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "--config",
                    str(cfg_path),
                    "contacts",
                    "set",
                    "--address",
                    "0xpeer300",
                    "--endpoint",
                    "127.0.0.1:19670",
                    "--network",
                    "official-testnet",
                    "--mode-family",
                    "v2-account",
                    "--consensus-endpoint",
                    "192.168.1.9:19500",
                    "--source",
                    "manual",
                ]
            )
        assert code == 0

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--config", str(cfg_path), "contacts", "show", "--address", "0xpeer300"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["address"] == "0xpeer300"
        assert payload["network"] == "official-testnet"
        assert payload["mode_family"] == "v2-account"
        assert payload["consensus_endpoint"] == "192.168.1.9:19500"
