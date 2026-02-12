from __future__ import annotations

import hashlib
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from EZ_App.node_manager import NodeManager
from EZ_App.wallet_store import WalletStore


class LocalService:
    def __init__(self, host: str, port: int, wallet_store: WalletStore, node_manager: NodeManager):
        self.host = host
        self.port = port
        self.wallet_store = wallet_store
        self.node_manager = node_manager

    def run(self) -> None:
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _write(self, code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def log_message(self, fmt: str, *args):
                return

            def do_GET(self):
                if self.path == "/health":
                    self._write(200, {"status": "ok", "time": datetime.utcnow().isoformat()})
                    return
                if self.path == "/wallet/show":
                    try:
                        s = service.wallet_store.summary()
                        self._write(200, {"address": s.address, "name": s.name, "created_at": s.created_at})
                    except FileNotFoundError:
                        self._write(404, {"error": "wallet_not_found"})
                    return
                if self.path == "/tx/history":
                    self._write(200, {"items": service.wallet_store.get_history()})
                    return
                if self.path == "/node/status":
                    self._write(200, service.node_manager.status())
                    return
                if self.path == "/network/info":
                    self._write(200, {"network": "testnet", "mode": "local"})
                    return
                self._write(404, {"error": "not_found"})

            def do_POST(self):
                if self.path == "/wallet/create":
                    body = self._read_json()
                    password = body.get("password", "")
                    if not password:
                        self._write(400, {"error": "password_required"})
                        return
                    name = body.get("name", "default")
                    created = service.wallet_store.create_wallet(password=password, name=name)
                    self._write(200, {"address": created["address"], "mnemonic": created["mnemonic"]})
                    return
                if self.path == "/wallet/import":
                    body = self._read_json()
                    mnemonic = body.get("mnemonic", "")
                    password = body.get("password", "")
                    if not mnemonic or not password:
                        self._write(400, {"error": "mnemonic_and_password_required"})
                        return
                    imported = service.wallet_store.import_wallet(mnemonic=mnemonic, password=password, name=body.get("name", "default"))
                    self._write(200, {"address": imported["address"]})
                    return
                if self.path == "/tx/send":
                    body = self._read_json()
                    sender = body.get("sender", "")
                    recipient = body.get("recipient", "")
                    amount = int(body.get("amount", 0))
                    if not sender or not recipient or amount <= 0:
                        self._write(400, {"error": "invalid_tx_payload"})
                        return
                    tx_id = hashlib.sha256(f"{sender}:{recipient}:{amount}:{datetime.utcnow().isoformat()}".encode("utf-8")).hexdigest()
                    item = {
                        "tx_id": tx_id,
                        "sender": sender,
                        "recipient": recipient,
                        "amount": amount,
                        "status": "submitted",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    service.wallet_store.append_history(item)
                    self._write(200, item)
                    return
                if self.path == "/node/start":
                    body = self._read_json()
                    self._write(200, service.node_manager.start(
                        consensus=int(body.get("consensus", 1)),
                        accounts=int(body.get("accounts", 1)),
                        start_port=int(body.get("start_port", 19500)),
                    ))
                    return
                if self.path == "/node/stop":
                    self._write(200, service.node_manager.stop())
                    return
                self._write(404, {"error": "not_found"})

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        server.serve_forever()
