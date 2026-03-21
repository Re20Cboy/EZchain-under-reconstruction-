from __future__ import annotations

import abc
import asyncio
import struct
from typing import Awaitable, Callable

from .networking import NetworkEnvelope
from .serde import dumps_json, loads_json

OnEnvelope = Callable[[NetworkEnvelope, str], Awaitable[dict | None]]


def encode_envelope(envelope: NetworkEnvelope) -> bytes:
    return dumps_json(envelope).encode("utf-8")


def decode_envelope(data: bytes) -> NetworkEnvelope:
    parsed = loads_json(data.decode("utf-8"))
    if not isinstance(parsed, NetworkEnvelope):
        raise TypeError("decoded payload is not a NetworkEnvelope")
    return parsed


class NetworkTransport(abc.ABC):
    @abc.abstractmethod
    def set_handler(self, handler: OnEnvelope) -> None:
        ...

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def send(self, endpoint: str, envelope: NetworkEnvelope) -> dict | None:
        ...


class _TCPClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def connect(self, timeout: float = 3.0) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=timeout,
        )

    async def send_and_recv(self, payload: bytes) -> bytes:
        if self.writer is None or self.reader is None:
            raise RuntimeError("client_not_connected")
        self.writer.write(struct.pack("!I", len(payload)))
        self.writer.write(payload)
        await self.writer.drain()
        header = await self.reader.readexactly(4)
        (length,) = struct.unpack("!I", header)
        return await self.reader.readexactly(length)

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()
        self.reader = None
        self.writer = None


class TCPNetworkTransport(NetworkTransport):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._server: asyncio.base_events.Server | None = None
        self._handler: OnEnvelope | None = None
        self._clients: dict[str, _TCPClient] = {}

    def set_handler(self, handler: OnEnvelope) -> None:
        self._handler = handler

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_conn, self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for client in list(self._clients.values()):
            await client.close()
        self._clients.clear()

    async def send(self, endpoint: str, envelope: NetworkEnvelope) -> dict | None:
        host, port_s = endpoint.rsplit(":", 1)
        client = await self._ensure_client(host, int(port_s))
        try:
            raw = await client.send_and_recv(encode_envelope(envelope))
        except Exception:
            await self._drop_client(endpoint)
            raise
        return loads_json(raw.decode("utf-8"))

    async def _ensure_client(self, host: str, port: int) -> _TCPClient:
        endpoint = f"{host}:{port}"
        client = self._clients.get(endpoint)
        if client is not None and client.writer is not None:
            return client
        client = _TCPClient(host, port)
        await client.connect()
        self._clients[endpoint] = client
        return client

    async def _drop_client(self, endpoint: str) -> None:
        client = self._clients.pop(endpoint, None)
        if client is not None:
            await client.close()

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername")
        remote = f"{peername[0]}:{peername[1]}" if isinstance(peername, tuple) else str(peername)
        try:
            while True:
                header = await reader.readexactly(4)
                (length,) = struct.unpack("!I", header)
                payload = await reader.readexactly(length)
                envelope = decode_envelope(payload)
                if self._handler is None:
                    response: dict | None = {"ok": False, "error": "missing_handler"}
                else:
                    response = await self._handler(envelope, remote)
                wire = dumps_json(response or {"ok": True}).encode("utf-8")
                writer.write(struct.pack("!I", len(wire)))
                writer.write(wire)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()


__all__ = [
    "NetworkTransport",
    "OnEnvelope",
    "TCPNetworkTransport",
    "decode_envelope",
    "encode_envelope",
]
