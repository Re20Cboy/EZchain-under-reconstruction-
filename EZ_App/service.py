from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from EZ_App.contact_card import build_contact_card, contact_entry_from_card, fetch_contact_card, load_contact_card
from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.ui_panel import build_local_panel_html
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
    NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
    CLIENT_TX_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{4,128}$")
    RECIPIENT_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{4,160}$")

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
        default_mode = "local"
        self.network_info = network_info or {
            "name": "testnet",
            "mode": default_mode,
            "mode_family": NodeManager._mode_family(default_mode),
            "roles": NodeManager._roles_for_mode(default_mode),
            "bootstrap_nodes": [],
            "consensus_nodes": 1,
            "account_nodes": 1,
            "start_port": 19500,
        }
        nonce_file = Path(wallet_store.base_dir) / "used_nonces.json"
        self.nonce_guard = NonceGuard(nonce_file=nonce_file, ttl_seconds=nonce_ttl_seconds)
        effective_log_dir = Path(log_dir) if log_dir else (Path(wallet_store.base_dir) / "logs")
        self.audit_logger = AuditLogger(effective_log_dir / "service_audit.log")
        self.metrics = ServiceMetrics()

    def _ui_html(self) -> str:
        return build_local_panel_html()

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
                        "time": datetime.now(timezone.utc).isoformat(),
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

            def _validate_nonce(self, nonce: str) -> bool:
                if not nonce:
                    self._err(400, "nonce_required", "Missing X-EZ-Nonce")
                    return False
                if not service.NONCE_PATTERN.fullmatch(nonce):
                    self._err(400, "invalid_nonce_format", "X-EZ-Nonce must match [A-Za-z0-9_-]{8,128}")
                    return False
                return True

            def _validate_send_fields(self, recipient: str, password: str, client_tx_id: str) -> bool:
                if not password:
                    self._err(400, "password_required", "password is required")
                    return False
                if not isinstance(recipient, str) or not service.RECIPIENT_PATTERN.fullmatch(recipient):
                    self._err(400, "invalid_recipient", "recipient must match [A-Za-z0-9_.:-]{4,160}")
                    return False
                if not isinstance(client_tx_id, str) or not service.CLIENT_TX_ID_PATTERN.fullmatch(client_tx_id):
                    self._err(400, "invalid_client_tx_id", "client_tx_id must match [A-Za-z0-9_.:-]{4,128}")
                    return False
                return True

            def _tx_path_ready(self) -> bool:
                return bool(service.network_info.get("tx_path_ready", True))

            def _tx_capabilities(self) -> Dict[str, str]:
                raw = service.network_info.get("tx_capabilities")
                if isinstance(raw, dict):
                    return {str(key): str(value) for key, value in raw.items()}
                if service.tx_engine.protocol_version == "v2" and str(service.network_info.get("mode", "")) == "official-testnet":
                    return {
                        "wallet_balance": "remote_read",
                        "wallet_checkpoints": "remote_read",
                        "tx_pending": "remote_read",
                        "tx_receipts": "remote_read",
                        "tx_history": "remote_read",
                        "tx_send": "remote_send",
                        "tx_faucet": "unsupported",
                    }
                if service.tx_engine.protocol_version == "v2":
                    return {
                        "wallet_balance": "local",
                        "wallet_checkpoints": "local",
                        "tx_pending": "local",
                        "tx_receipts": "local",
                        "tx_history": "local",
                        "tx_send": "local",
                        "tx_faucet": "local",
                    }
                return {
                    "wallet_balance": "local",
                    "wallet_checkpoints": "unsupported",
                    "tx_pending": "unsupported",
                    "tx_receipts": "unsupported",
                    "tx_history": "local",
                    "tx_send": "local",
                    "tx_faucet": "local",
                }

            def _tx_path_note(self) -> str:
                return str(
                    service.network_info.get(
                        "tx_path_note",
                        "Tx commands run through the local runtime.",
                    )
                )

            def _tx_action_key(self, action: str) -> str:
                return str(action).replace(" ", "_")

            def _err_tx_path_not_ready(self, action: str) -> None:
                action_key = self._tx_action_key(action)
                capability = self._tx_capabilities().get(action_key, "unsupported")
                if capability == "unsupported":
                    self._err(501, "tx_action_unsupported", f"{action} is not supported on this profile. {self._tx_path_note()}")
                    return
                self._err(501, "tx_path_not_ready", f"{action} is not available on this profile yet. {self._tx_path_note()}")

            def _err_tx_action(self, code: int, err_code: str, message: str) -> None:
                self._err(code, err_code, f"{message}. {self._tx_path_note()}")

            def _remote_read_state(self):
                state = self._remote_account_status()
                if state is None:
                    return None
                if state.get("status") != "running":
                    return None
                if state.get("mode_family") != "v2-account":
                    return None
                if not str(state.get("wallet_db_path", "")).strip():
                    return None
                return state

            def _remote_account_status(self):
                state = service.node_manager.account_status(
                    bootstrap_nodes=service.network_info.get("bootstrap_nodes", []),
                )
                return state if isinstance(state, dict) else None

            def _wallet_summary_if_exists(self):
                try:
                    return service.wallet_store.summary(protocol_version=service.tx_engine.protocol_version)
                except FileNotFoundError:
                    return None

            def _tx_send_readiness(self) -> Dict[str, Any]:
                capability = self._tx_capabilities().get("tx_send", "unsupported")
                if capability == "local":
                    return {
                        "capability": capability,
                        "ready": True,
                        "recipient_endpoint_required_per_send": False,
                        "blockers": [],
                    }
                if capability == "unsupported":
                    return {
                        "capability": capability,
                        "ready": False,
                        "recipient_endpoint_required_per_send": False,
                        "blockers": ["tx_send_unsupported_on_profile"],
                    }

                raw_state = self._remote_account_status()
                wallet_summary = self._wallet_summary_if_exists()
                remote_account_running = bool(isinstance(raw_state, dict) and raw_state.get("status") == "running")
                consensus_endpoint_present = bool(
                    isinstance(raw_state, dict) and str(raw_state.get("consensus_endpoint", "")).strip()
                )
                wallet_db_present = bool(
                    isinstance(raw_state, dict) and str(raw_state.get("wallet_db_path", "")).strip()
                )
                local_wallet_present = wallet_summary is not None
                remote_address = "" if not isinstance(raw_state, dict) else str(raw_state.get("address", "")).strip()
                local_address = "" if wallet_summary is None else str(wallet_summary.address)
                wallet_address_matches = None
                if local_wallet_present and remote_address:
                    wallet_address_matches = local_address == remote_address

                blockers: list[str] = []
                if not remote_account_running:
                    blockers.append("remote_account_not_running")
                if remote_account_running and not consensus_endpoint_present:
                    blockers.append("consensus_endpoint_missing")
                if remote_account_running and not wallet_db_present:
                    blockers.append("wallet_db_path_missing")
                if not local_wallet_present:
                    blockers.append("local_wallet_not_created")
                if wallet_address_matches is False:
                    blockers.append("wallet_address_mismatch_with_account_node")

                return {
                    "capability": capability,
                    "ready": len(blockers) == 0,
                    "recipient_endpoint_required_per_send": True,
                    "local_wallet_present": local_wallet_present,
                    "local_wallet_address": local_address,
                    "remote_account_status": None if not isinstance(raw_state, dict) else raw_state.get("status", ""),
                    "remote_account_address": remote_address,
                    "consensus_endpoint_present": consensus_endpoint_present,
                    "wallet_db_present": wallet_db_present,
                    "wallet_address_matches": wallet_address_matches,
                    "blockers": blockers,
                }

            def _remote_send_preflight(self, *, recipient: str, recipient_endpoint: str):
                remote_state = self._remote_read_state()
                if remote_state is None:
                    return None, (
                        "remote_account_not_running",
                        "tx send requires a running v2-account on this profile",
                    )
                if not str(remote_state.get("consensus_endpoint", "")).strip():
                    return None, (
                        "consensus_endpoint_missing",
                        "tx send requires the remote v2-account to expose its consensus endpoint",
                    )
                resolved_recipient_endpoint = str(recipient_endpoint or "").strip()
                if not resolved_recipient_endpoint:
                    resolved_recipient_endpoint = str(service.wallet_store.get_contact_endpoint(recipient) or "").strip()
                if not resolved_recipient_endpoint:
                    return None, (
                        "recipient_endpoint_required",
                        "tx send requires recipient_endpoint or a saved contact endpoint on this profile",
                    )
                return {
                    "state": remote_state,
                    "recipient_endpoint": resolved_recipient_endpoint,
                }, None

            def _tx_send_error(self, exc: ValueError) -> tuple[str, str] | None:
                message = str(exc)
                if message == "wallet_address_mismatch_with_account_node":
                    return (
                        "wallet_address_mismatch_with_account_node",
                        "Local wallet address does not match the running remote v2-account address",
                    )
                if message == "consensus_endpoint_missing":
                    return (
                        "consensus_endpoint_missing",
                        "tx send requires the remote v2-account to expose its consensus endpoint",
                    )
                if message == "recipient_endpoint_required":
                    return (
                        "recipient_endpoint_required",
                        "tx send requires recipient_endpoint or a saved contact endpoint on this profile",
                    )
                return None

            def _contact_address_from_path(self) -> str | None:
                prefix = "/contacts/"
                if not self.path.startswith(prefix):
                    return None
                address = self.path[len(prefix):].strip()
                if not address:
                    return None
                return address

            def _set_contact_from_payload(self, body: Dict[str, Any]):
                address = str(body.get("address", "")).strip()
                endpoint = str(body.get("endpoint", "")).strip()
                if not address:
                    self._err(400, "address_required", "address is required")
                    return None
                if not endpoint:
                    self._err(400, "endpoint_required", "endpoint is required")
                    return None
                return service.wallet_store.set_contact(
                    address=address,
                    endpoint=endpoint,
                    network=str(body.get("network", "") or "").strip() or None,
                    mode_family=str(body.get("mode_family", "") or "").strip() or None,
                    consensus_endpoint=str(body.get("consensus_endpoint", "") or "").strip() or None,
                    source=str(body.get("source", "") or "").strip() or "service_api",
                    fetched_from=str(body.get("fetched_from", "") or "").strip() or None,
                )

            def log_message(self, fmt: str, *args):
                return

            def do_GET(self):
                if self.path == "/health":
                    self._ok({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})
                    return
                if self.path == "/" or self.path == "/ui":
                    self._write_html(200, service._ui_html())
                    return
                if self.path == "/wallet/show":
                    try:
                        s = service.wallet_store.summary(protocol_version=service.tx_engine.protocol_version)
                        self._ok({"address": s.address, "name": s.name, "created_at": s.created_at})
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                    return
                if self.path == "/wallet/balance":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    if not self._tx_path_ready():
                        remote_state = self._remote_read_state()
                        if remote_state is None:
                            self._err_tx_path_not_ready("wallet balance")
                            return
                    password = self.headers.get("X-EZ-Password", "")
                    if not password:
                        self._err(400, "password_required", "Missing X-EZ-Password header")
                        return
                    try:
                        if not self._tx_path_ready():
                            data = service.tx_engine.remote_balance(service.wallet_store, password=password, state=remote_state)
                        else:
                            data = service.tx_engine.balance(service.wallet_store, password=password)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except Exception as exc:
                        self._err(500, "balance_failed", str(exc))
                        return
                    self._ok(data)
                    return
                if self.path == "/wallet/checkpoints":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    if not self._tx_path_ready():
                        remote_state = self._remote_read_state()
                        if remote_state is None:
                            self._err_tx_path_not_ready("wallet checkpoints")
                            return
                    password = self.headers.get("X-EZ-Password", "")
                    if not password:
                        self._err(400, "password_required", "Missing X-EZ-Password header")
                        return
                    try:
                        if not self._tx_path_ready():
                            data = service.tx_engine.remote_checkpoints(service.wallet_store, password=password, state=remote_state)
                        else:
                            data = service.tx_engine.checkpoints(service.wallet_store, password=password)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        self._err(500, "checkpoints_failed", str(exc))
                        return
                    self._ok(data)
                    return
                if self.path == "/tx/history":
                    if not self._tx_path_ready():
                        remote_state = self._remote_read_state()
                        if remote_state is None:
                            self._err_tx_path_not_ready("tx history")
                            return
                        try:
                            data = service.tx_engine.remote_history(service.wallet_store, state=remote_state)
                        except ValueError as exc:
                            self._err(400, "invalid_request", str(exc))
                            return
                        except Exception as exc:
                            self._err(500, "history_failed", str(exc))
                            return
                        self._ok(data)
                        return
                    self._ok(service.tx_engine.history(service.wallet_store))
                    return
                if self.path == "/tx/pending":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    if not self._tx_path_ready():
                        remote_state = self._remote_read_state()
                        if remote_state is None:
                            self._err_tx_path_not_ready("tx pending")
                            return
                    password = self.headers.get("X-EZ-Password", "")
                    if not password:
                        self._err(400, "password_required", "Missing X-EZ-Password header")
                        return
                    try:
                        if not self._tx_path_ready():
                            data = service.tx_engine.remote_pending(service.wallet_store, password=password, state=remote_state)
                        else:
                            data = service.tx_engine.pending(service.wallet_store, password=password)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        self._err(500, "pending_failed", str(exc))
                        return
                    self._ok(data)
                    return
                if self.path == "/tx/receipts":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    if not self._tx_path_ready():
                        remote_state = self._remote_read_state()
                        if remote_state is None:
                            self._err_tx_path_not_ready("tx receipts")
                            return
                    password = self.headers.get("X-EZ-Password", "")
                    if not password:
                        self._err(400, "password_required", "Missing X-EZ-Password header")
                        return
                    try:
                        if not self._tx_path_ready():
                            data = service.tx_engine.remote_receipts(service.wallet_store, password=password, state=remote_state)
                        else:
                            data = service.tx_engine.receipts(service.wallet_store, password=password)
                    except FileNotFoundError:
                        self._err(404, "wallet_not_found", "Wallet not found")
                        return
                    except ValueError as exc:
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        self._err(500, "receipts_failed", str(exc))
                        return
                    self._ok(data)
                    return
                if self.path == "/node/status":
                    node_status = service.node_manager.status()
                    service.metrics.record_node_status(node_status.get("status", "stopped"))
                    self._ok(node_status)
                    return
                if self.path == "/node/account-status":
                    self._ok(service.node_manager.account_status())
                    return
                if self.path == "/node/contact-card":
                    try:
                        card = build_contact_card(
                            service.node_manager.account_status(
                                bootstrap_nodes=service.network_info.get("bootstrap_nodes", []),
                            ),
                            network_name=str(service.network_info.get("name", "testnet")),
                        )
                    except ValueError as exc:
                        self._err(409, "contact_card_unavailable", str(exc))
                        return
                    self._ok(card)
                    return
                if self.path == "/contacts":
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    self._ok({"items": service.wallet_store.list_contacts()})
                    return
                contact_address = self._contact_address_from_path()
                if contact_address is not None:
                    if not self._auth_ok():
                        self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                        return
                    item = service.wallet_store.get_contact(contact_address)
                    if item is None:
                        self._err(404, "contact_not_found", "Contact not found")
                        return
                    self._ok(item)
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
                            "mode_family": service.network_info.get(
                                "mode_family",
                                NodeManager._mode_family(str(service.network_info.get("mode", "local"))),
                            ),
                            "roles": service.network_info.get(
                                "roles",
                                NodeManager._roles_for_mode(str(service.network_info.get("mode", "local"))),
                            ),
                            "bootstrap_nodes": bootstrap_nodes,
                            "consensus_nodes": int(service.network_info.get("consensus_nodes", 1)),
                            "account_nodes": int(service.network_info.get("account_nodes", 1)),
                            "start_port": int(service.network_info.get("start_port", 0)),
                            "bootstrap_probe": probe,
                            "tx_send_readiness": self._tx_send_readiness(),
                            "tx_capabilities": self._tx_capabilities(),
                            "tx_path": service.network_info.get("tx_path", "legacy_local_runtime"),
                            "tx_path_ready": bool(service.network_info.get("tx_path_ready", True)),
                            "tx_path_note": service.network_info.get(
                                "tx_path_note",
                                "Tx commands run through the local runtime.",
                            ),
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
                    summary = service.wallet_store.summary(protocol_version=service.tx_engine.protocol_version)
                    self._ok({"address": summary.address, "mnemonic": created["mnemonic"]})
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
                    summary = service.wallet_store.summary(protocol_version=service.tx_engine.protocol_version)
                    self._ok({"address": summary.address})
                    return

                if self.path == "/tx/faucet":
                    if not self._tx_path_ready():
                        self._err_tx_path_not_ready("tx faucet")
                        return
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
                    if not self._validate_nonce(nonce):
                        return
                    if not service.nonce_guard.claim(nonce):
                        self._err(409, "replay_detected", "Replay nonce detected")
                        return

                    recipient = body.get("recipient", "")
                    recipient_endpoint = str(body.get("recipient_endpoint", "") or "").strip()
                    password = body.get("password", "")
                    client_tx_id = body.get("client_tx_id") or uuid.uuid4().hex
                    if not self._validate_send_fields(recipient=recipient, password=password, client_tx_id=client_tx_id):
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="invalid_request")
                        return
                    try:
                        amount = int(body.get("amount", 0))
                    except (TypeError, ValueError):
                        self._err(400, "invalid_request", "amount must be an integer")
                        return

                    remote_state = None
                    resolved_recipient_endpoint = recipient_endpoint
                    if not self._tx_path_ready():
                        remote_send, remote_error = self._remote_send_preflight(
                            recipient=str(recipient),
                            recipient_endpoint=recipient_endpoint,
                        )
                        if remote_send is None and remote_error is not None:
                            error_code, error_message = remote_error
                            service.metrics.record_tx_send(ok=False, latency_ms=None, error_code=error_code)
                            self._err_tx_action(409 if error_code == "remote_account_not_running" else 400, error_code, error_message)
                            return
                        remote_state = remote_send["state"]
                        resolved_recipient_endpoint = remote_send["recipient_endpoint"]

                    try:
                        result = service.tx_engine.send(
                            service.wallet_store,
                            password=password,
                            recipient=recipient,
                            amount=amount,
                            client_tx_id=client_tx_id,
                            state=remote_state,
                            recipient_endpoint=resolved_recipient_endpoint or None,
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
                        mapped_error = self._tx_send_error(exc)
                        if mapped_error is not None:
                            error_code, error_message = mapped_error
                            service.metrics.record_tx_send(ok=False, latency_ms=None, error_code=error_code)
                            self._err(400, error_code, error_message)
                            return
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="invalid_request")
                        self._err(400, "invalid_request", str(exc))
                        return
                    except Exception as exc:
                        service.metrics.record_tx_send(ok=False, latency_ms=None, error_code="send_failed")
                        self._err(500, "send_failed", str(exc))
                        return

                    sender = service.wallet_store.summary(protocol_version=service.tx_engine.protocol_version).address
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if result.receipt_height is not None:
                        history_item["receipt_height"] = result.receipt_height
                    if result.receipt_block_hash is not None:
                        history_item["receipt_block_hash"] = result.receipt_block_hash
                    service.wallet_store.append_history(history_item)
                    self._ok(history_item)
                    return

                if self.path == "/node/start":
                    node_mode = "v2-localnet" if service.tx_engine.protocol_version == "v2" else "local"
                    self._ok(
                        service.node_manager.start(
                            consensus=int(body.get("consensus", 1)),
                            accounts=int(body.get("accounts", 1)),
                            start_port=int(body.get("start_port", 19500)),
                            mode=node_mode,
                        )
                    )
                    return

                if self.path == "/contacts":
                    saved = self._set_contact_from_payload(body)
                    if saved is None:
                        return
                    self._ok(saved)
                    return

                if self.path == "/contacts/import-card":
                    file_path = str(body.get("file", "") or "").strip()
                    if not file_path:
                        self._err(400, "file_required", "file is required")
                        return
                    try:
                        card = load_contact_card(file_path)
                        saved = service.wallet_store.set_contact(**contact_entry_from_card(card, source="contact_card_file"))
                    except Exception as exc:
                        self._err(400, "invalid_contact_card", str(exc))
                        return
                    self._ok({"contact": saved, "card": card})
                    return

                if self.path == "/contacts/fetch-card":
                    url = str(body.get("url", "") or "").strip()
                    if not url:
                        self._err(400, "url_required", "url is required")
                        return
                    try:
                        card = fetch_contact_card(url)
                        saved = service.wallet_store.set_contact(
                            **contact_entry_from_card(card, source="service_fetch", fetched_from=url)
                        )
                    except Exception as exc:
                        self._err(400, "contact_fetch_failed", str(exc))
                        return
                    self._ok({"contact": saved, "card": card, "source_url": url})
                    return

                if self.path == "/node/stop":
                    self._ok(service.node_manager.stop())
                    return

                self._err(404, "not_found", "Route not found")

            def do_DELETE(self):
                if not self._auth_ok():
                    self._err(401, "unauthorized", "Missing or invalid X-EZ-Token")
                    return
                contact_address = self._contact_address_from_path()
                if contact_address is None:
                    self._err(404, "not_found", "Route not found")
                    return
                removed = service.wallet_store.remove_contact(contact_address)
                if not removed:
                    self._err(404, "contact_not_found", "Contact not found")
                    return
                self._ok({"removed": True, "address": contact_address})

        return Handler

    def build_server(self) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((self.host, self.port), self._build_handler())

    def run(self) -> None:
        server = self.build_server()
        server.serve_forever()
