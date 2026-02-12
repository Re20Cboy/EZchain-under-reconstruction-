from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


class NonceGuard:
    def __init__(self, nonce_file: Path, ttl_seconds: int):
        self.nonce_file = nonce_file
        self.ttl_seconds = max(1, ttl_seconds)
        self.lock = threading.Lock()

    def _load(self) -> Dict[str, float]:
        if not self.nonce_file.exists():
            return {}
        try:
            parsed = json.loads(self.nonce_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return {str(k): float(v) for k, v in parsed.items()}
        except Exception:
            return {}
        return {}

    def _save(self, data: Dict[str, float]) -> None:
        self.nonce_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def claim(self, nonce: str) -> bool:
        if not nonce:
            return False
        now = time.time()
        with self.lock:
            data = self._load()
            for key, expiry in list(data.items()):
                if expiry <= now:
                    data.pop(key, None)

            if nonce in data and data[nonce] > now:
                return False

            data[nonce] = now + self.ttl_seconds
            self._save(data)
            return True


class AuditLogger:
    REDACT_KEYS = {"password", "mnemonic", "encrypted_private_key", "X-EZ-Password", "X-EZ-Token"}

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            for key, item in value.items():
                if key in self.REDACT_KEYS:
                    sanitized[key] = "***"
                else:
                    sanitized[key] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(v) for v in value]
        return value

    def log(self, event: Dict[str, Any]) -> None:
        payload = self._sanitize(event)
        line = json.dumps(payload, ensure_ascii=True)
        with self.lock:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class ServiceMetrics:
    def __init__(self):
        self.started_at = time.time()
        self.lock = threading.Lock()
        self.requests_total = 0
        self.tx_send_success = 0
        self.tx_send_failed = 0
        self.node_status_checks = 0
        self.node_status_running = 0
        self.error_code_distribution: Dict[str, int] = defaultdict(int)
        self.tx_latency_ms = deque(maxlen=500)

    def record_response(self, status_code: int, error_code: str | None) -> None:
        with self.lock:
            self.requests_total += 1
            if error_code:
                self.error_code_distribution[error_code] += 1
            elif status_code >= 400:
                self.error_code_distribution["http_error"] += 1

    def record_tx_send(self, ok: bool, latency_ms: float | None, error_code: str | None = None) -> None:
        with self.lock:
            if ok:
                self.tx_send_success += 1
                if latency_ms is not None:
                    self.tx_latency_ms.append(float(latency_ms))
            else:
                self.tx_send_failed += 1
                if error_code:
                    self.error_code_distribution[error_code] += 1

    def record_node_status(self, status: str) -> None:
        with self.lock:
            self.node_status_checks += 1
            if status == "running":
                self.node_status_running += 1

    def snapshot(self, current_node_status: str) -> Dict[str, Any]:
        with self.lock:
            tx_total = self.tx_send_success + self.tx_send_failed
            tx_success_rate = (self.tx_send_success / tx_total) if tx_total else 0.0
            node_online_rate = (
                self.node_status_running / self.node_status_checks
                if self.node_status_checks
                else (1.0 if current_node_status == "running" else 0.0)
            )
            avg_latency = (
                sum(self.tx_latency_ms) / len(self.tx_latency_ms)
                if self.tx_latency_ms
                else None
            )
            return {
                "uptime_seconds": int(max(0, time.time() - self.started_at)),
                "requests_total": self.requests_total,
                "transactions": {
                    "send_success": self.tx_send_success,
                    "send_failed": self.tx_send_failed,
                    "success_rate": round(tx_success_rate, 4),
                    "avg_confirmation_latency_ms": round(avg_latency, 3) if avg_latency is not None else None,
                },
                "node_online_rate": round(node_online_rate, 4),
                "error_code_distribution": dict(self.error_code_distribution),
            }


class LocalService:
    def __init__(
        self,
        host: str,
        port: int,
        wallet_store: WalletStore,
        node_manager: NodeManager,
        tx_engine: TxEngine,
        api_token: str,
        max_payload_bytes: int = 65536,
        nonce_ttl_seconds: int = 600,
        log_dir: str | None = None,
        network_info: Dict[str, Any] | None = None,
    ):
        self.host = host
        self.port = port
        self.wallet_store = wallet_store
        self.node_manager = node_manager
        self.tx_engine = tx_engine
        self.api_token = api_token
        self.max_payload_bytes = max(1024, max_payload_bytes)
        self.network_info = network_info or {"name": "testnet", "mode": "local", "bootstrap_nodes": []}
        nonce_file = Path(wallet_store.base_dir) / "used_nonces.json"
        self.nonce_guard = NonceGuard(nonce_file=nonce_file, ttl_seconds=nonce_ttl_seconds)
        effective_log_dir = Path(log_dir) if log_dir else (Path(wallet_store.base_dir) / "logs")
        self.audit_logger = AuditLogger(effective_log_dir / "service_audit.log")
        self.metrics = ServiceMetrics()

    def _ui_html(self) -> str:
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EZchain Local Panel</title>
  <style>
    :root { --bg:#f5f7fb; --card:#fff; --ink:#1f2937; --muted:#6b7280; --line:#e5e7eb; --accent:#0f766e; }
    body { font-family: "SF Mono", Menlo, Monaco, monospace; margin: 0; background: linear-gradient(120deg,#f5f7fb,#e8f7f3); color: var(--ink); }
    .wrap { max-width: 980px; margin: 24px auto; padding: 0 16px; }
    h1 { margin: 0 0 16px; font-size: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
    .row { display:flex; gap:8px; margin:8px 0; }
    input, button { font: inherit; padding: 8px; border-radius: 8px; border: 1px solid var(--line); width: 100%; }
    button { background: var(--accent); color: #fff; border: 0; cursor: pointer; width: auto; }
    pre { background:#0b1020; color:#d1fae5; padding:10px; border-radius:8px; overflow:auto; max-height: 240px; }
    .muted { color: var(--muted); font-size: 12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>EZchain Local Panel</h1>
    <div class="card">
      <div class="row">
        <input id="token" placeholder="X-EZ-Token (run: ezchain_cli.py auth show-token)" />
      </div>
      <div class="muted">All POST routes and sensitive balance routes require token. /tx/send also requires nonce and client_tx_id.</div>
    </div>
    <div class="grid">
      <div class="card">
        <h3>Wallet</h3>
        <div class="row"><input id="name" placeholder="name" value="default"/></div>
        <div class="row"><input id="password" placeholder="password" type="password"/></div>
        <div class="row">
          <button onclick="createWallet()">Create</button>
          <button onclick="showWallet()">Show</button>
          <button onclick="showBalance()">Balance</button>
        </div>
      </div>
      <div class="card">
        <h3>Transactions</h3>
        <div class="row"><input id="recipient" placeholder="recipient address"/></div>
        <div class="row"><input id="amount" placeholder="amount" value="100"/></div>
        <div class="row"><input id="client_tx_id" placeholder="client_tx_id (optional auto)"/></div>
        <div class="row">
          <button onclick="faucet()">Faucet</button>
          <button onclick="sendTx()">Send</button>
          <button onclick="historyTx()">History</button>
        </div>
      </div>
      <div class="card">
        <h3>Node</h3>
        <div class="row">
          <button onclick="nodeStart()">Start</button>
          <button onclick="nodeStatus()">Status</button>
          <button onclick="nodeStop()">Stop</button>
          <button onclick="showMetrics()">Metrics</button>
        </div>
      </div>
    </div>
    <div class="card"><pre id="out">Ready.</pre></div>
  </div>
<script>
const out = (v) => document.getElementById("out").textContent = JSON.stringify(v, null, 2);
const token = () => document.getElementById("token").value.trim();
const headers = (json=true) => {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const t = token();
  if (t) h["X-EZ-Token"] = t;
  return h;
};
async function get(url, auth=false) {
  const h = {};
  if (auth && token()) h["X-EZ-Token"] = token();
  const r = await fetch(url, { headers: h });
  out(await r.json());
}
async function post(url, body, extraHeaders={}) {
  const r = await fetch(url, { method: "POST", headers: { ...headers(true), ...extraHeaders }, body: JSON.stringify(body) });
  out(await r.json());
}
function createWallet(){ post("/wallet/create", { name:document.getElementById("name").value, password:document.getElementById("password").value }); }
function showWallet(){ get("/wallet/show"); }
function showBalance(){ get("/wallet/balance", true); }
function faucet(){ post("/tx/faucet", { amount: Number(document.getElementById("amount").value), password:document.getElementById("password").value }); }
function sendTx(){
  const clientTxId = document.getElementById("client_tx_id").value || crypto.randomUUID();
  post(
    "/tx/send",
    {
      recipient:document.getElementById("recipient").value,
      amount:Number(document.getElementById("amount").value),
      password:document.getElementById("password").value,
      client_tx_id: clientTxId
    },
    { "X-EZ-Nonce": crypto.randomUUID() }
  );
}
function historyTx(){ get("/tx/history"); }
function showMetrics(){ get("/metrics"); }
function nodeStart(){ post("/node/start", { consensus:1, accounts:1, start_port:19500 }); }
function nodeStatus(){ get("/node/status"); }
function nodeStop(){ post("/node/stop", {}); }
</script>
</body>
</html>
"""

    def _build_handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _write(self, code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                error_code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
                service.audit_logger.log(
                    {
                        "time": datetime.utcnow().isoformat(),
                        "remote": self.client_address[0] if self.client_address else "unknown",
                        "method": self.command,
                        "path": self.path,
                        "status": code,
                        "ok": payload.get("ok", False) if isinstance(payload, dict) else False,
                        "error_code": error_code,
                    }
                )
                service.metrics.record_response(status_code=code, error_code=error_code)

            def _write_html(self, code: int, html: str) -> None:
                body = html.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _ok(self, payload: Dict[str, Any], code: int = 200) -> None:
                self._write(code, {"ok": True, "data": payload})

            def _err(self, code: int, err_code: str, message: str) -> None:
                self._write(code, {"ok": False, "error": {"code": err_code, "message": message}})

            def _payload_too_large(self) -> bool:
                raw = self.headers.get("Content-Length", "0")
                try:
                    size = int(raw)
                except ValueError:
                    self._err(400, "invalid_content_length", "Invalid Content-Length")
                    return True
                if size > service.max_payload_bytes:
                    self._err(413, "payload_too_large", "Payload exceeds max size")
                    return True
                return False

            def _read_json(self) -> Dict[str, Any]:
                if self._payload_too_large():
                    return {}

                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}

                raw = self.rfile.read(length)
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    raise ValueError("invalid_json")

                if not isinstance(parsed, dict):
                    raise ValueError("invalid_json_object")
                return parsed

            def _auth_ok(self) -> bool:
                token = self.headers.get("X-EZ-Token", "")
                return bool(token) and token == service.api_token

            def log_message(self, fmt: str, *args):
                return

            def do_GET(self):
                if self.path == "/health":
                    self._ok({"status": "ok", "time": datetime.utcnow().isoformat()})
                    return
                if self.path == "/" or self.path == "/ui":
                    self._write_html(200, service._ui_html())
                    return
                if self.path == "/wallet/show":
                    try:
                        s = service.wallet_store.summary()
                        self._ok({"address": s.address, "name": s.name, "created_at": s.created_at})
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                    return
                if self.path == "/wallet/balance":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    password = self.headers.get("X-EZ-Password", "")
                    if not password:
                        self._err(400, "password_required", "Missing X-EZ-Password header")
                        return
                    try:
                        data = service.tx_engine.balance(service.wallet_store, password=password)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except Exception as exc:
                        self._err(500, "balance_failed", str(exc))
                        return
                    self._ok(data)
                    return
                if self.path == "/tx/history":
                    self._ok({"items": service.wallet_store.get_history()})
                    return
                if self.path == "/node/status":
                    node_status = service.node_manager.status()
                    service.metrics.record_node_status(node_status.get("status", "stopped"))
                    self._ok(node_status)
                    return
                if self.path == "/metrics":
                    node_status = service.node_manager.status().get("status", "stopped")
                    self._ok(service.metrics.snapshot(current_node_status=node_status))
                    return
                if self.path == "/network/info":
                    bootstrap_nodes = service.network_info.get("bootstrap_nodes", [])
                    probe = service.node_manager.probe_bootstrap(bootstrap_nodes) if bootstrap_nodes else {
                        "total": 0,
                        "reachable": 0,
                        "unreachable": 0,
                        "all_reachable": False,
                        "any_reachable": False,
                        "checked": [],
                    }
                    self._ok(
                        {
                            "network": service.network_info.get("name", "testnet"),
                            "mode": service.network_info.get("mode", "local"),
                            "bootstrap_nodes": bootstrap_nodes,
                            "bootstrap_probe": probe,
                        }
                    )
                    return
                self._err(404, "not_found", "Route not found")

            def do_POST(self):
                if not self._auth_ok():
                    self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                    return

                try:
                    body = self._read_json()
                except ValueError as exc:
                    self._err(400, "invalid_request", str(exc))
                    return

                if self.path == "/wallet/create":
                    password = body.get("password", "")
                    if not password:
                        self._err(400, "password_required", "password is required")
                        return
                    name = body.get("name", "default")
                    created = service.wallet_store.create_wallet(password=password, name=name)
                    self._ok({"address": created["address"], "mnemonic": created["mnemonic"]})
                    return

                if self.path == "/wallet/import":
                    mnemonic = body.get("mnemonic", "")
                    password = body.get("password", "")
                    if not mnemonic or not password:
                        self._err(400, "mnemonic_and_password_required", "mnemonic and password are required")
                        return
                    imported = service.wallet_store.import_wallet(
                        mnemonic=mnemonic,
                        password=password,
                        name=body.get("name", "default"),
                    )
                    self._ok({"address": imported["address"]})
                    return

                if self.path == "/tx/faucet":
                    password = body.get("password", "")
                    try:
                        amount = int(body.get("amount", 0))
                    except (TypeError, ValueError):
                        self._err(400, "invalid_request", "amount must be an integer")
                        return
                    try:
                        data = service.tx_engine.faucet(service.wallet_store, password=password, amount=amount)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        self._err(500, "internal_error", str(exc))
                        return
                    self._ok(data)
                    return

                if self.path == "/tx/send":
                    started = time.perf_counter()
                    nonce = self.headers.get("X-EZ-Nonce", "")
                    if not nonce:
                        self._err(400, "nonce_required", "Missing X-EZ-Nonce")
                        return
                    if not service.nonce_guard.claim(nonce):
                        self._err(409, "replay_detected", "Replay nonce detected")
                        return

                    recipient = body.get("recipient", "")
                    password = body.get("password", "")
                    client_tx_id = body.get("client_tx_id") or uuid.uuid4().hex
                    try:
                        amount = int(body.get("amount", 0))
                    except (TypeError, ValueError):
                        self._err(400, "invalid_request", "amount must be an integer")
                        return

                    try:
                        result = service.tx_engine.send(
                            service.wallet_store,
                            password=password,
                            recipient=recipient,
                            amount=amount,
                            client_tx_id=client_tx_id,
                        )
                    except FileNotFoundError:
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="wallet_not_found")
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        if str(exc) == "duplicate_transaction":
                            service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="duplicate_transaction")
                            self._err(409, "duplicate_transaction", "Duplicate client_tx_id")
                            return
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="invalid_request")
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="send_failed")
                        self._err(500, "send_failed", str(exc))
                        return

                    sender = service.wallet_store.summary().address
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    service.metrics.record_tx_send(ok=True, latency_ms=latency_ms)
                    history_item = {
                        "tx_id": result.tx_hash,
                        "submit_hash": result.submit_hash,
                        "sender": sender,
                        "recipient": result.recipient,
                        "amount": result.amount,
                        "status": result.status,
                        "client_tx_id": result.client_tx_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    service.wallet_store.append_history(history_item)
                    self._ok(history_item)
                    return

                if self.path == "/node/start":
                    self._ok(
                        service.node_manager.start(
                            consensus=int(body.get("consensus", 1)),
                            accounts=int(body.get("accounts", 1)),
                            start_port=int(body.get("start_port", 19500)),
                        )
                    )
                    return

                if self.path == "/node/stop":
                    self._ok(service.node_manager.stop())
                    return

                self._err(404, "not_found", "Route not found")

        return Handler

    def build_server(self) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((self.host, self.port), self._build_handler())

    def run(self) -> None:
        server = self.build_server()
        server.serve_forever()
