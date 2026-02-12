import http.client
import json
import tempfile
import threading
from pathlib import Path
import pytest

from EZ_App.config import ensure_directories, load_api_token, load_config
from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.service import LocalService
from EZ_App.wallet_store import WalletStore


def _request(port: int, method: str, path: str, payload=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = None
    h = headers or {}
    if payload is not None:
        body = json.dumps(payload)
        h = {"Content-Type": "application/json", **h}
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, json.loads(data)


def test_service_auth_and_tx_flow():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezsvc"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\napp:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_host: 127.0.0.1\n"
                "  api_port: 0\n"
            ),
            encoding="utf-8",
        )

        cfg = load_config(cfg_path)
        ensure_directories(cfg)
        token = load_api_token(cfg)

        wallet_store = WalletStore(cfg.app.data_dir)
        node_manager = NodeManager(data_dir=cfg.app.data_dir, project_root=str(Path(__file__).resolve().parent.parent))
        tx_engine = TxEngine(cfg.app.data_dir)
        service = LocalService(
            host="127.0.0.1",
            port=0,
            wallet_store=wallet_store,
            node_manager=node_manager,
            tx_engine=tx_engine,
            api_token=token,
        )

        try:
            server = service.build_server()
        except PermissionError:
            pytest.skip("socket bind not permitted in current environment")
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            status, body = _request(port, "GET", "/health")
            assert status == 200
            assert body["ok"] is True

            status, body = _request(port, "POST", "/wallet/create", {"name": "demo", "password": "pw123"})
            assert status == 401
            assert body["error"]["code"] == "unauthorized"

            auth_headers = {"X-EZ-Token": token}
            status, body = _request(port, "POST", "/wallet/create", {"name": "demo", "password": "pw123"}, auth_headers)
            assert status == 200
            assert body["ok"] is True
            assert body["data"]["address"].startswith("0x")

            status, body = _request(port, "POST", "/tx/faucet", {"password": "pw123", "amount": 300}, auth_headers)
            assert status == 200
            assert body["ok"] is True

            status, body = _request(
                port,
                "GET",
                "/wallet/balance",
                headers={"X-EZ-Token": token, "X-EZ-Password": "pw123"},
            )
            assert status == 200
            assert body["ok"] is True
            assert body["data"]["available_balance"] >= 300

            status, body = _request(port, "POST", "/tx/send", {"password": "pw123", "recipient": "0xabc123", "amount": 50}, auth_headers)
            assert status == 200
            assert body["ok"] is True
            assert body["data"]["status"] == "submitted"

            status, body = _request(port, "GET", "/tx/history")
            assert status == 200
            assert body["ok"] is True
            assert len(body["data"]["items"]) >= 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
