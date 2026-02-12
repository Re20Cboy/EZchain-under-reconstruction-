import asyncio
import contextlib
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from .codec import encode_message, decode_message
from .config import P2PConfig
from .logger import setup_logger
from .peer_manager import PeerManager, PeerInfo
from .security import (
    SUPPORTED_ALGORITHM,
    derive_public_key_pem,
    fingerprint_public_key,
    sign_envelope,
    verify_envelope_signature,
)
from .transport.tcp import TcpTransport
from .transport.base import AbstractTransport
try:
    from .transport.libp2p_daemon import Libp2pDaemonTransport
except Exception:  # optional
    Libp2pDaemonTransport = None  # type: ignore


Handler = Callable[[Dict[str, Any], str, asyncio.StreamWriter], Awaitable[None]]


class Router:
    DEFAULT_SIGNED_TYPES = {
        "HELLO",
        "WELCOME",
        "PING",
        "PONG",
        "ACCTXN_SUBMIT",
        "PROOF_TO_SENDER",
        "NEW_BLOCK",
    }

    def __init__(self, config: P2PConfig):
        self.cfg = config
        self.node_id = config.node_id or uuid.uuid4().hex
        self.logger = setup_logger("ez_p2p")
        self.peer_manager = PeerManager(max_neighbors=config.max_neighbors)
        self.handlers: Dict[str, Handler] = {}
        self._seen_msg_ids: Dict[str, int] = {}
        self._maintenance_task: Optional[asyncio.Task] = None
        self._clock_future_skew_ms = 30_000
        self._seed_state: Dict[str, Dict[str, Any]] = {}
        self._started_monotonic = time.monotonic()
        self._last_peer_seen_monotonic = self._started_monotonic
        self._maintenance_interval_sec = max(0.5, float(config.maintenance_interval_sec))
        self._seed_retry_base_sec = max(0.1, float(config.seed_retry_base_sec))
        self._seed_retry_max_sec = max(self._seed_retry_base_sec, float(config.seed_retry_max_sec))
        self._degraded_no_peer_sec = max(1.0, float(config.degraded_no_peer_sec))
        self._enforce_identity = bool(config.enforce_identity_verification)
        signed_types = set(config.signed_message_types or [])
        self._signed_message_types: Set[str] = signed_types if signed_types else set(self.DEFAULT_SIGNED_TYPES)
        self._identity_private_key_pem = config.identity_private_key_pem
        self._identity_public_key_pem = config.identity_public_key_pem
        if self._identity_private_key_pem and not self._identity_public_key_pem:
            self._identity_public_key_pem = derive_public_key_pem(self._identity_private_key_pem)

        # Transport selection
        self.transport: AbstractTransport
        if config.transport == "libp2p":
            if Libp2pDaemonTransport is None or not config.libp2p_control_path:
                raise RuntimeError("libp2p transport requested but not available or control path not set")
            self.transport = Libp2pDaemonTransport(config.libp2p_control_path, protocol=config.libp2p_protocol)
        else:
            self.transport = TcpTransport(config.listen_host, config.listen_port)
        self.transport.set_on_frame(self._on_frame)

        # built-in handlers
        self.register_handler("HELLO", self._h_hello)
        self.register_handler("WELCOME", self._h_welcome)
        self.register_handler("PING", self._h_ping)
        self.register_handler("PONG", self._h_pong)

    async def start(self):
        await self.transport.start()
        if self.cfg.transport == "tcp":
            self.logger.info("server_listen", extra={"extra": {"host": self.cfg.listen_host, "port": self.cfg.listen_port}})
        else:
            self.logger.info("libp2p_ready", extra={"extra": {"control": self.cfg.libp2p_control_path, "protocol": self.cfg.libp2p_protocol}})
        # connect to seeds (tcp addr or libp2p multiaddr)
        for seed in self.cfg.peer_seeds:
            self._seed_state.setdefault(seed, self._new_seed_state())
            await self._attempt_seed_hello(seed, force=True)
        if not self._maintenance_task:
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self):
        if self._maintenance_task:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task
            self._maintenance_task = None
        await self.transport.stop()

    async def _on_frame(self, data: bytes, remote_id: str, ctx: Any):
        if len(data) > self.cfg.msg_size_limit_bytes:
            self.logger.info("drop_oversize_message", extra={"extra": {"size": len(data)}})
            return
        try:
            msg = decode_message(data)
        except Exception as e:
            self.logger.warning("decode_failed", extra={"extra": {"err": str(e)}})
            return

        if not self._validate_envelope(msg):
            return

        if self._is_replay_or_duplicate(msg):
            return

        msg_type = msg.get("type")
        handler = self.handlers.get(msg_type)
        if not handler:
            self.logger.info("drop_unknown_type", extra={"extra": {"type": msg_type}})
            return
        await handler(msg, remote_id, ctx)

    def register_handler(self, msg_type: str, handler: Handler):
        self.handlers[msg_type] = handler

    async def broadcastToConsensus(self, payload: Dict[str, Any], msg_type: str):
        for p in self.peer_manager.select_by_role("consensus"):
            await self._send_to_addr(p.address, payload, msg_type, network="consensus")

    async def broadcastToAccounts(self, payload: Dict[str, Any], msg_type: str):
        for p in self.peer_manager.select_by_role("account"):
            await self._send_to_addr(p.address, payload, msg_type, network="account")

    async def sendToAccount(self, account_addr: str, payload: Dict[str, Any], msg_type: str):
        # account_addr is opaque here (user-defined). In MVP, treat as address string host:port
        await self._send_to_addr(account_addr, payload, msg_type, network="account")

    async def sendAccountToConsensus(self, payload: Dict[str, Any], msg_type: str):
        for p in self.peer_manager.select_by_role("consensus"):
            await self._send_to_addr(p.address, payload, msg_type, network="consensus")

    async def sendConsensusToAccount(self, account_addr: str, payload: Dict[str, Any], msg_type: str):
        await self._send_to_addr(account_addr, payload, msg_type, network="account")

    async def _send_to_addr(self, addr: str, payload: Dict[str, Any], msg_type: str, network: str):
        data = self._encode_outbound_message(network=network, msg_type=msg_type, payload=payload)
        retry_count = max(0, int(self.cfg.retry_count))
        backoff_ms = max(0, int(self.cfg.retry_backoff_ms))
        timeout_sec = max(0.1, self.cfg.send_timeout_ms / 1000.0)
        last_err: Optional[Exception] = None
        for attempt in range(retry_count + 1):
            try:
                await asyncio.wait_for(self.transport.send(addr, data), timeout=timeout_sec)
                return
            except Exception as e:
                last_err = e
                if attempt >= retry_count:
                    break
                await asyncio.sleep((backoff_ms * (2 ** attempt)) / 1000.0)
        raise RuntimeError(f"send_failed:{addr}:{msg_type}:{last_err}")

    async def _send_hello(self, addr: str):
        await self._send_to_addr(
            addr,
            {
                "node_id": self.node_id,
                "role": self.cfg.node_role,
                "protocol_version": self.cfg.protocol_version,
                "network_id": self.cfg.network_id,
                "latest_index": 0,
            },
            "HELLO",
            network="consensus" if self.cfg.node_role != "account" else "account",
        )

    # ---------------- built-in handlers ----------------
    async def _h_hello(self, msg: Dict[str, Any], remote_addr: str, writer: asyncio.StreamWriter):
        p = msg["payload"]
        info = PeerInfo(
            node_id=msg.get("sender_id") or p.get("node_id", ""),
            role=p.get("role", "account"),
            network_id=p.get("network_id", ""),
            latest_index=int(p.get("latest_index", 0)),
            address=remote_addr,
            last_seen_ms=int(time.time() * 1000),
            identity_fingerprint=self._extract_identity_fingerprint(msg),
        )
        self.peer_manager.add_peer(info)
        self._last_peer_seen_monotonic = time.monotonic()
        self._seed_mark_success(remote_addr)
        # reply welcome
        # reply WELCOME on the same connection to avoid dialing ephemeral ports
        payload = {
            "node_id": self.node_id,
            "role": self.cfg.node_role,
            "protocol_version": self.cfg.protocol_version,
            "network_id": self.cfg.network_id,
            "latest_index": 0,
        }
        data = self._encode_outbound_message(
            network=msg.get("network", "consensus"),
            msg_type="WELCOME",
            payload=payload,
        )
        await self.transport.send_via_context(ctx=writer, data=data)
        self.logger.info("hello_recv", extra={"extra": {"from": remote_addr, "role": info.role}})

    async def _h_welcome(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        p = msg["payload"]
        info = PeerInfo(
            node_id=msg.get("sender_id") or p.get("node_id", ""),
            role=p.get("role", "account"),
            network_id=p.get("network_id", ""),
            latest_index=int(p.get("latest_index", 0)),
            address=remote_addr,
            last_seen_ms=int(time.time() * 1000),
            identity_fingerprint=self._extract_identity_fingerprint(msg),
        )
        self.peer_manager.add_peer(info)
        self._last_peer_seen_monotonic = time.monotonic()
        self._seed_mark_success(remote_addr)
        self.logger.info("welcome_recv", extra={"extra": {"from": remote_addr, "role": info.role}})

    async def _h_ping(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        # reply PONG on the same connection
        payload = {"ts": msg["payload"].get("ts")}
        data = self._encode_outbound_message(network=msg.get("network", "account"), msg_type="PONG", payload=payload)
        await self.transport.send_via_context(writer, data)
        self.logger.info("ping_recv", extra={"extra": {"from": remote_addr}})

    async def _h_pong(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        self.logger.info("pong_recv", extra={"extra": {"from": remote_addr}})

    # ---------------- convenience APIs ----------------
    async def ping(self, addr: str):
        await self._send_to_addr(addr, {"ts": int(asyncio.get_event_loop().time() * 1000)}, "PING", network="account")

    # removed writer-specific helper; handled by transport

    def _validate_envelope(self, msg: Dict[str, Any]) -> bool:
        remote_version = str(msg.get("version", ""))
        if not remote_version:
            return False
        if not self._is_version_compatible(self.cfg.protocol_version, remote_version):
            self.logger.info(
                "drop_incompatible_version",
                extra={"extra": {"local": self.cfg.protocol_version, "remote": remote_version}},
            )
            return False
        if "msg_id" not in msg or "timestamp" not in msg or "type" not in msg:
            return False
        if not self._validate_identity(msg):
            return False
        return True

    def _encode_outbound_message(self, *, network: str, msg_type: str, payload: Dict[str, Any]) -> bytes:
        msg_id = uuid.uuid4().hex
        timestamp_ms = int(time.time() * 1000)
        sender_id = self.node_id
        auth = self._build_auth_fields(
            msg_type=msg_type,
            network=network,
            payload=payload,
            msg_id=msg_id,
            timestamp_ms=timestamp_ms,
            sender_id=sender_id,
        )
        return encode_message(
            network=network,
            msg_type=msg_type,
            payload=payload,
            protocol_version=self.cfg.protocol_version,
            msg_id=msg_id,
            timestamp_ms=timestamp_ms,
            sender_id=sender_id,
            auth=auth,
        )

    def _build_auth_fields(
        self,
        *,
        msg_type: str,
        network: str,
        payload: Dict[str, Any],
        msg_id: str,
        timestamp_ms: int,
        sender_id: str,
    ) -> Dict[str, Any] | None:
        if msg_type not in self._signed_message_types:
            return None
        if not self._identity_private_key_pem or not self._identity_public_key_pem:
            return None
        to_sign = {
            "version": self.cfg.protocol_version,
            "network": network,
            "type": msg_type,
            "msg_id": msg_id,
            "timestamp": timestamp_ms,
            "sender_id": sender_id,
            "payload": payload,
        }
        signature_hex = sign_envelope(to_sign, self._identity_private_key_pem)
        return {
            "algorithm": SUPPORTED_ALGORITHM,
            "public_key": self._identity_public_key_pem,
            "signature": signature_hex,
        }

    def _extract_identity_fingerprint(self, msg: Dict[str, Any]) -> str | None:
        auth = msg.get("auth")
        if not isinstance(auth, dict):
            return None
        pub = auth.get("public_key")
        if not isinstance(pub, str) or not pub:
            return None
        return fingerprint_public_key(pub)

    def _validate_identity(self, msg: Dict[str, Any]) -> bool:
        msg_type = str(msg.get("type", ""))
        if msg_type not in self._signed_message_types:
            return True

        sender_id = str(msg.get("sender_id", ""))
        auth = msg.get("auth")
        if not sender_id or not isinstance(auth, dict):
            self.logger.info("drop_missing_identity_fields", extra={"extra": {"type": msg_type}})
            return not self._enforce_identity

        algorithm = auth.get("algorithm")
        pub = auth.get("public_key")
        sig = auth.get("signature")
        if algorithm != SUPPORTED_ALGORITHM or not isinstance(pub, str) or not isinstance(sig, str):
            self.logger.info("drop_invalid_identity_metadata", extra={"extra": {"type": msg_type}})
            return not self._enforce_identity

        if not verify_envelope_signature(msg, signature_hex=sig, public_key_pem=pub):
            self.logger.info("drop_invalid_identity_signature", extra={"extra": {"type": msg_type, "sender_id": sender_id}})
            return not self._enforce_identity

        if msg_type in {"HELLO", "WELCOME"}:
            payload_node_id = str((msg.get("payload") or {}).get("node_id", ""))
            if payload_node_id and payload_node_id != sender_id:
                self.logger.info("drop_identity_payload_mismatch", extra={"extra": {"type": msg_type, "sender_id": sender_id}})
                return not self._enforce_identity

        return True

    def _is_replay_or_duplicate(self, msg: Dict[str, Any]) -> bool:
        now_ms = int(time.time() * 1000)
        msg_id = str(msg.get("msg_id", ""))
        msg_ts = int(msg.get("timestamp", 0))
        self._evict_old_msg_ids(now_ms)
        if msg_id in self._seen_msg_ids:
            return True
        # Basic replay guard: too old or too far in the future are both suspicious.
        if msg_ts < now_ms - self.cfg.dedup_window_ms:
            return True
        if msg_ts > now_ms + self._clock_future_skew_ms:
            return True
        self._seen_msg_ids[msg_id] = msg_ts
        return False

    def _evict_old_msg_ids(self, now_ms: Optional[int] = None):
        current_ms = now_ms or int(time.time() * 1000)
        threshold = current_ms - self.cfg.dedup_window_ms
        old_ids = [mid for mid, ts in self._seen_msg_ids.items() if ts < threshold]
        for mid in old_ids:
            self._seen_msg_ids.pop(mid, None)

    @staticmethod
    def _is_version_compatible(local_version: str, remote_version: str) -> bool:
        def _major(v: str) -> str:
            return v.split(".", 1)[0] if v else ""
        return _major(local_version) == _major(remote_version)

    async def _maintenance_loop(self):
        while True:
            await asyncio.sleep(self._maintenance_interval_sec)
            await self._maintenance_once()

    async def _maintenance_once(self):
        self._evict_old_msg_ids()
        for seed in self.cfg.peer_seeds:
            await self._attempt_seed_hello(seed)

    def _new_seed_state(self) -> Dict[str, Any]:
        return {
            "failures": 0,
            "next_retry_monotonic": 0.0,
            "last_attempt_monotonic": 0.0,
            "last_success_monotonic": 0.0,
            "last_error": "",
        }

    async def _attempt_seed_hello(self, seed: str, force: bool = False) -> None:
        state = self._seed_state.setdefault(seed, self._new_seed_state())
        now = time.monotonic()
        if not force and now < float(state.get("next_retry_monotonic", 0.0)):
            return

        state["last_attempt_monotonic"] = now
        try:
            if self.cfg.transport == "libp2p":
                await self.transport.connect_seed(seed)
            await self._send_hello(seed)
            state["failures"] = 0
            state["next_retry_monotonic"] = now + self._seed_retry_base_sec
            state["last_success_monotonic"] = now
            state["last_error"] = ""
        except Exception as e:
            failures = int(state.get("failures", 0)) + 1
            backoff = min(self._seed_retry_max_sec, self._seed_retry_base_sec * (2 ** min(failures - 1, 10)))
            state["failures"] = failures
            state["next_retry_monotonic"] = now + backoff
            state["last_error"] = str(e)
            self.logger.warning(
                "seed_connect_failed",
                extra={"extra": {"seed": seed, "failures": failures, "retry_in_sec": backoff, "err": str(e)}},
            )

    def _seed_mark_success(self, remote_addr: str) -> None:
        state = self._seed_state.get(remote_addr)
        if not state:
            return
        now = time.monotonic()
        state["failures"] = 0
        state["last_success_monotonic"] = now
        state["next_retry_monotonic"] = now + self._seed_retry_base_sec
        state["last_error"] = ""

    def get_health_status(self) -> Dict[str, Any]:
        now = time.monotonic()
        peer_count = len(self.peer_manager.list_peers())
        no_peer_for = max(0.0, now - self._last_peer_seen_monotonic)
        degraded = peer_count == 0 and no_peer_for >= self._degraded_no_peer_sec
        seed_state = {}
        for seed, state in self._seed_state.items():
            seed_state[seed] = {
                "failures": int(state.get("failures", 0)),
                "last_error": state.get("last_error", ""),
                "last_success_age_sec": (
                    round(now - float(state.get("last_success_monotonic", 0.0)), 3)
                    if float(state.get("last_success_monotonic", 0.0)) > 0
                    else None
                ),
                "next_retry_in_sec": max(0.0, round(float(state.get("next_retry_monotonic", 0.0)) - now, 3)),
            }
        return {
            "node_id": self.node_id,
            "peer_count": peer_count,
            "degraded": degraded,
            "no_peer_for_sec": round(no_peer_for, 3),
            "seed_state": seed_state,
        }
