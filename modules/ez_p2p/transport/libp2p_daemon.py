from typing import Any, Optional, Callable, Awaitable

from .base import AbstractTransport, OnFrame


class Libp2pDaemonTransport(AbstractTransport):
    """
    Libp2p transport based on go-libp2p-daemon (p2pd).

    This implementation expects a running libp2p daemon and the Python
    client library available. It wires a single protocol for request/response
    streams and forwards payloads to the upper layer (Router).

    Requirements:
    - go-libp2p-daemon running (e.g., `p2pd -listen /ip4/0.0.0.0/tcp/4001`)
    - Python client library `p2pclient` installed
    """

    def __init__(self, control_path: str, protocol: str = "/ez/1.0.0"):
        self.control_path = control_path
        self.protocol = protocol
        self._on_frame_cb: Optional[OnFrame] = None
        self._client = None  # p2p client instance

    def set_on_frame(self, callback: OnFrame) -> None:
        self._on_frame_cb = callback

    async def start(self) -> None:
        try:
            from p2pclient.libp2p_daemon_bindings import Client
        except Exception as e:
            raise RuntimeError(
                "p2pclient is not installed. Please install it to use libp2p transport."
            ) from e

        # Connect to daemon
        self._client = Client(self.control_path)
        await self._client.connect()

        # Register stream handler for protocol
        async def handler(stream_info, reader, writer):
            # Read one frame (length-prefixed 4 bytes big-endian)
            import struct, asyncio
            try:
                header = await reader.readexactly(4)
                (length,) = struct.unpack("!I", header)
                payload = await reader.readexactly(length)
                if self._on_frame_cb:
                    remote_id = stream_info.peer_id.to_base58() if hasattr(stream_info.peer_id, "to_base58") else str(stream_info.peer_id)
                    await self._on_frame_cb(payload, remote_id, writer)
            except Exception:
                # best-effort; stream may be closed by peer
                pass

        await self._client.stream_handler(self.protocol, handler)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def send(self, addr: str, data: bytes) -> None:
        if not self._client:
            raise RuntimeError("libp2p transport not started")
        # addr is expected to be peer_id (base58) or multiaddr
        # For simplicity, assume peer_id
        stream_info, reader, writer = await self._client.stream_open(addr, [self.protocol])
        import struct
        writer.write(struct.pack("!I", len(data)))
        writer.write(data)
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def send_via_context(self, ctx: Any, data: bytes) -> None:
        # ctx is a libp2p stream writer
        import struct
        writer = ctx
        writer.write(struct.pack("!I", len(data)))
        writer.write(data)
        await writer.drain()

    async def connect_seed(self, seed: str) -> None:
        # seed can be a multiaddr of the form /ip4/host/tcp/port/p2p/<peerid>
        if not self._client:
            raise RuntimeError("libp2p transport not started")
        await self._client.connect(seed)

