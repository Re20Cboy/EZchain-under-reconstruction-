import http.client
import json
import tempfile
import threading
import time
from pathlib import Path
import pytest

from EZ_App.config import ensure_directories, load_api_token, load_config
from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.service import LocalService
from EZ_App.wallet_store import WalletStore


def _request(port: int, method: str, path: str, payload=None, headers=None, raw_body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = None
    h = headers or {}
    if raw_body is not None:
        body = raw_body
    elif payload is not None:
        body = json.dumps(payload)
        h = {"Content-Type": "application/json", **h}
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, json.loads(data)


def _start_server_or_skip(service: LocalService):
    try:
        server = service.build_server()
    except PermissionError:
        pytest.skip("socket bind not permitted in current environment")
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            status, body = _request(port, "GET", "/health")
            if status == 200 and body.get("ok") is True:
                break
        except Exception:
            pass
        time.sleep(0.05)
    else:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        raise AssertionError("service did not become ready in time")
    return server, port, thread


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

        server, port, thread = _start_server_or_skip(service)

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
            assert status == 400
            assert body["error"]["code"] == "nonce_required"

            status, body = _request(
                port,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 10, "client_tx_id": "cid-x-111"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "bad"},
            )
            assert status == 400
            assert body["error"]["code"] == "invalid_nonce_format"

            status, body = _request(
                port,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 10, "client_tx_id": "bad id"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-ok-1"},
            )
            assert status == 400
            assert body["error"]["code"] == "invalid_client_tx_id"

            send_headers = {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-0001"}
            status, body = _request(
                port,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 50, "client_tx_id": "cid-1"},
                send_headers,
            )
            assert status == 200
            assert body["ok"] is True
            assert body["data"]["status"] == "submitted"

            status, body = _request(
                port,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 50, "client_tx_id": "cid-1"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-0002"},
            )
            assert status == 409
            assert body["error"]["code"] == "duplicate_transaction"

            status, body = _request(
                port,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 10, "client_tx_id": "cid-2"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-0002"},
            )
            assert status == 409
            assert body["error"]["code"] == "replay_detected"

            status, body = _request(port, "GET", "/tx/history")
            assert status == 200
            assert body["ok"] is True
            assert len(body["data"]["items"]) >= 1

            status, body = _request(port, "GET", "/metrics")
            assert status == 200
            assert body["ok"] is True
            metrics = body["data"]
            assert "node_online_rate" in metrics
            assert "error_code_distribution" in metrics
            assert "transactions" in metrics
            assert metrics["transactions"]["send_success"] >= 1
            assert metrics["transactions"]["success_rate"] >= 0

            status, body = _request(port, "GET", "/network/info")
            assert status == 200
            assert body["ok"] is True
            assert body["data"]["network"] == "testnet"
            assert "bootstrap_probe" in body["data"]

            status, body = _request(
                port,
                "POST",
                "/wallet/create",
                headers={"X-EZ-Token": token, "Content-Type": "application/json", "Content-Length": "70000"},
                raw_body="x" * 70000,
            )
            assert status == 413
            assert body["error"]["code"] == "payload_too_large"

            status, body = _request(
                port,
                "POST",
                "/wallet/create",
                headers={
                    "X-EZ-Token": token,
                    "Content-Type": "application/json",
                    "Content-Length": "5",
                },
                raw_body='{"x":',
            )
            assert status == 400
            assert body["error"]["code"] == "invalid_request"

            log_path = data_dir / "logs" / "service_audit.log"
            assert log_path.exists()
            log_text = log_path.read_text(encoding="utf-8")
            assert "pw123" not in log_text
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_service_restart_recovers_history_and_nonce_state():
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
        auth_headers = {"X-EZ-Token": token}

        service1 = LocalService(
            host="127.0.0.1",
            port=0,
            wallet_store=WalletStore(cfg.app.data_dir),
            node_manager=NodeManager(data_dir=cfg.app.data_dir, project_root=str(Path(__file__).resolve().parent.parent)),
            tx_engine=TxEngine(cfg.app.data_dir),
            api_token=token,
        )
        server1, port1, thread1 = _start_server_or_skip(service1)

        try:
            status, _ = _request(port1, "POST", "/wallet/create", {"name": "demo", "password": "pw123"}, auth_headers)
            assert status == 200
            status, _ = _request(port1, "POST", "/tx/faucet", {"password": "pw123", "amount": 300}, auth_headers)
            assert status == 200
            status, body = _request(
                port1,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 50, "client_tx_id": "cid-restart-1"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-restart-1"},
            )
            assert status == 200
            assert body["ok"] is True
        finally:
            server1.shutdown()
            server1.server_close()
            thread1.join(timeout=2)

        service2 = LocalService(
            host="127.0.0.1",
            port=0,
            wallet_store=WalletStore(cfg.app.data_dir),
            node_manager=NodeManager(data_dir=cfg.app.data_dir, project_root=str(Path(__file__).resolve().parent.parent)),
            tx_engine=TxEngine(cfg.app.data_dir),
            api_token=token,
        )
        server2, port2, thread2 = _start_server_or_skip(service2)
        try:
            status, body = _request(port2, "GET", "/tx/history")
            assert status == 200
            ids = [item.get("client_tx_id") for item in body["data"]["items"]]
            assert "cid-restart-1" in ids

            status, body = _request(
                port2,
                "POST",
                "/tx/send",
                {"password": "pw123", "recipient": "0xabc123", "amount": 10, "client_tx_id": "cid-restart-2"},
                {"X-EZ-Token": token, "X-EZ-Nonce": "nonce-restart-1"},
            )
            assert status == 409
            assert body["error"]["code"] == "replay_detected"
        finally:
            server2.shutdown()
            server2.server_close()
            thread2.join(timeout=2)
