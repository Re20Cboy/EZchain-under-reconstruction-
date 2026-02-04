import asyncio
import socket
import uuid
import struct
from typing import Any, Awaitable, Callable, Dict, Optional

from .codec import encode_message, decode_message
from .config import P2PConfig
from .logger import setup_logger
from .peer_manager import PeerManager, PeerInfo
from .transport.tcp import TcpTransport
from .transport.base import AbstractTransport
try:
    from .transport.libp2p_daemon import Libp2pDaemonTransport
except Exception:  # optional
    Libp2pDaemonTransport = None  # type: ignore


Handler = Callable[[Dict[str, Any], str, asyncio.StreamWriter], Awaitable[None]]


class Router:
    def __init__(self, config: P2PConfig):
        self.cfg = config
        self.node_id = config.node_id or uuid.uuid4().hex
        self.logger = setup_logger("ez_p2p")
        self.peer_manager = PeerManager(max_neighbors=config.max_neighbors)
        self.handlers: Dict[str, Handler] = {}

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
            try:
                if self.cfg.transport == "libp2p":
                    await self.transport.connect_seed(seed)
                else:
                    # no-op: for tcp seeds we dial on first send/hello
                    pass
                await self._send_hello(seed)
            except Exception as e:
                self.logger.warning("seed_connect_failed", extra={"extra": {"seed": seed, "err": str(e)}})

    async def _on_frame(self, data: bytes, remote_id: str, ctx: Any):
        try:
            msg = decode_message(data)
        except Exception as e:
            self.logger.warning("decode_failed", extra={"extra": {"err": str(e)}})
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
        data = encode_message(network=network, msg_type=msg_type, payload=payload, protocol_version=self.cfg.protocol_version)
        await self.transport.send(addr, data)

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
            node_id=p.get("node_id", ""),
            role=p.get("role", "account"),
            network_id=p.get("network_id", ""),
            latest_index=int(p.get("latest_index", 0)),
            address=remote_addr,
        )
        self.peer_manager.add_peer(info)
        # reply welcome
        # reply WELCOME on the same connection to avoid dialing ephemeral ports
        payload = {
            "node_id": self.node_id,
            "role": self.cfg.node_role,
            "protocol_version": self.cfg.protocol_version,
            "network_id": self.cfg.network_id,
            "latest_index": 0,
        }
        data = encode_message(
            network=msg.get("network", "consensus"),
            msg_type="WELCOME",
            payload=payload,
            protocol_version=self.cfg.protocol_version,
        )
        await self.transport.send_via_context(ctx=writer, data=data)
        self.logger.info("hello_recv", extra={"extra": {"from": remote_addr, "role": info.role}})

    async def _h_welcome(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        p = msg["payload"]
        info = PeerInfo(
            node_id=p.get("node_id", ""),
            role=p.get("role", "account"),
            network_id=p.get("network_id", ""),
            latest_index=int(p.get("latest_index", 0)),
            address=remote_addr,
        )
        self.peer_manager.add_peer(info)
        self.logger.info("welcome_recv", extra={"extra": {"from": remote_addr, "role": info.role}})

    async def _h_ping(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        # reply PONG on the same connection
        payload = {"ts": msg["payload"].get("ts")}
        data = encode_message(network=msg.get("network", "account"), msg_type="PONG", payload=payload, protocol_version=self.cfg.protocol_version)
        await self.transport.send_via_context(writer, data)
        self.logger.info("ping_recv", extra={"extra": {"from": remote_addr}})

    async def _h_pong(self, msg: Dict[str, Any], remote_addr: str, writer: Any):
        self.logger.info("pong_recv", extra={"extra": {"from": remote_addr}})

    # ---------------- convenience APIs ----------------
    async def ping(self, addr: str):
        await self._send_to_addr(addr, {"ts": int(asyncio.get_event_loop().time() * 1000)}, "PING", network="account")

    # removed writer-specific helper; handled by transport
