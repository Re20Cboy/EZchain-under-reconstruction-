import asyncio
import struct
from typing import Awaitable, Callable, Optional, Any

from .base import AbstractTransport, OnFrame

FrameHandler = Callable[[bytes, asyncio.StreamWriter], Awaitable[None]]


class TCPServer:
    def __init__(self, host: str, port: int, on_frame: FrameHandler):
        self._host = host
        self._port = port
        self._on_frame = on_frame
        self._server: Optional[asyncio.base_events.Server] = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle_conn, self._host, self._port)

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                header = await reader.readexactly(4)
                (length,) = struct.unpack("!I", header)
                payload = await reader.readexactly(length)
                await self._on_frame(payload, writer)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            writer.close()
            await writer.wait_closed()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class TCPClient:
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, timeout: float = 3.0):
        self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(self._host, self._port), timeout=timeout)

    async def send(self, data: bytes):
        if not self._writer:
            raise RuntimeError("not connected")
        self._writer.write(struct.pack("!I", len(data)))
        self._writer.write(data)
        await self._writer.drain()

    async def recv(self) -> bytes:
        if not self._reader:
            raise RuntimeError("not connected")
        header = await self._reader.readexactly(4)
        (length,) = struct.unpack("!I", header)
        return await self._reader.readexactly(length)

    async def close(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None


class TcpTransport(AbstractTransport):
    def __init__(self, host: str, port: int):
        self._server = TCPServer(host, port, self._on_frame)
        self._on_frame_cb: Optional[OnFrame] = None
        self._clients: dict[str, TCPClient] = {}

    def set_on_frame(self, callback: OnFrame) -> None:
        self._on_frame_cb = callback

    async def start(self) -> None:
        await self._server.start()

    async def stop(self) -> None:
        await self._server.stop()
        for c in list(self._clients.values()):
            await c.close()
        self._clients.clear()

    async def _on_frame(self, payload: bytes, writer: asyncio.StreamWriter) -> None:
        if not self._on_frame_cb:
            return
        peername = writer.get_extra_info("peername")
        remote_addr = f"{peername[0]}:{peername[1]}" if isinstance(peername, tuple) else str(peername)
        await self._on_frame_cb(payload, remote_addr, writer)

    async def _ensure_client(self, host: str, port: int) -> TCPClient:
        addr = f"{host}:{port}"
        client = self._clients.get(addr)
        if client:
            return client
        client = TCPClient(host, port)
        await client.connect(timeout=3.0)
        self._clients[addr] = client
        return client

    async def send(self, addr: str, data: bytes) -> None:
        host, port_s = addr.split(":")
        client = await self._ensure_client(host, int(port_s))
        await client.send(data)

    async def send_via_context(self, ctx: Any, data: bytes) -> None:
        if not isinstance(ctx, asyncio.StreamWriter):
            raise RuntimeError("invalid TCP context")
        ctx.write(struct.pack("!I", len(data)))
        ctx.write(data)
        await ctx.drain()
