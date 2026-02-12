from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


class LocalService:
    def __init__(
        self,
        host: str,
        port: int,
        wallet_store: WalletStore,
        node_manager: NodeManager,
        tx_engine: TxEngine,
        api_token: str,
    ):
        self.host = host
        self.port = port
        self.wallet_store = wallet_store
        self.node_manager = node_manager
        self.tx_engine = tx_engine
        self.api_token = api_token

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
      <div class="muted">All POST routes and sensitive balance routes require token.</div>
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
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
  out(await r.json());
}
function createWallet(){ post("/wallet/create", { name:document.getElementById("name").value, password:document.getElementById("password").value }); }
function showWallet(){ get("/wallet/show"); }
function showBalance(){ get("/wallet/balance", true); }
function faucet(){ post("/tx/faucet", { amount: Number(document.getElementById("amount").value), password:document.getElementById("password").value }); }
function sendTx(){ post("/tx/send", { recipient:document.getElementById("recipient").value, amount:Number(document.getElementById("amount").value), password:document.getElementById("password").value }); }
function historyTx(){ get("/tx/history"); }
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

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

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
                    self._ok(service.node_manager.status())
                    return
                if self.path == "/network/info":
                    self._ok({"network": "testnet", "mode": "local"})
                    return
                self._err(404, "not_found", "Route not found")

            def do_POST(self):
                if not self._auth_ok():
                    self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                    return

                if self.path == "/wallet/create":
                    body = self._read_json()
                    password = body.get("password", "")
                    if not password:
                        self._err(400, "password_required", "password is required")
                        return
                    name = body.get("name", "default")
                    created = service.wallet_store.create_wallet(password=password, name=name)
                    self._ok({"address": created["address"], "mnemonic": created["mnemonic"]})
                    return

                if self.path == "/wallet/import":
                    body = self._read_json()
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
                    body = self._read_json()
                    password = body.get("password", "")
                    amount = int(body.get("amount", 0))
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
                    body = self._read_json()
                    recipient = body.get("recipient", "")
                    amount = int(body.get("amount", 0))
                    password = body.get("password", "")
                    try:
                        result = service.tx_engine.send(
                            service.wallet_store,
                            password=password,
                            recipient=recipient,
                            amount=amount,
                        )
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        self._err(500, "send_failed", str(exc))
                        return

                    sender = service.wallet_store.summary().address
                    history_item = {
                        "tx_id": result.tx_hash,
                        "submit_hash": result.submit_hash,
                        "sender": sender,
                        "recipient": result.recipient,
                        "amount": result.amount,
                        "status": result.status,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    service.wallet_store.append_history(history_item)
                    self._ok(history_item)
                    return

                if self.path == "/node/start":
                    body = self._read_json()
                    self._ok(service.node_manager.start(
                        consensus=int(body.get("consensus", 1)),
                        accounts=int(body.get("accounts", 1)),
                        start_port=int(body.get("start_port", 19500)),
                    ))
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
