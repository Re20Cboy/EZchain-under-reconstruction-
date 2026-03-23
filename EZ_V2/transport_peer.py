from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Iterable

from .network_transport import NetworkTransport
from .networking import NetworkEnvelope, PeerInfo


class TransportPeerNetwork:
    """Static peer directory backed by a real NetworkTransport.

    The transport itself is request/response oriented. When a handler needs to
    push follow-up messages back to the original caller, this adapter captures
    those outbound envelopes and returns them in-band so the caller can apply
    them locally before the original send() completes. When a handler emits
    messages for other peers, those are flushed over the transport before the
    original request returns.
    """

    def __init__(
        self,
        transport: NetworkTransport,
        peers: Iterable[PeerInfo] = (),
        *,
        timeout_sec: float = 5.0,
    ):
        self.transport = transport
        self.timeout_sec = max(0.5, float(timeout_sec))
        self._peers: dict[str, PeerInfo] = {peer.node_id: peer for peer in peers}
        self._handler: Callable[[NetworkEnvelope], dict[str, Any] | None] | None = None
        self._local_peer_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._startup_error: BaseException | None = None
        self._incoming_lock: asyncio.Lock | None = None
        self._active_request_sender_id: str | None = None
        self._active_outbox: list[NetworkEnvelope] | None = None
        self._active_remote_deliveries: list[NetworkEnvelope] | None = None

    def register(
        self,
        peer: PeerInfo,
        handler: Callable[[NetworkEnvelope], dict[str, Any] | None],
    ) -> None:
        self._peers[peer.node_id] = peer
        self._local_peer_id = peer.node_id
        self._handler = handler

    def peer_info(self, node_id: str) -> PeerInfo:
        peer = self._peers.get(node_id)
        if peer is None:
            raise ValueError(f"unknown_peer:{node_id}")
        return peer

    def list_peers(self, role: str | None = None) -> tuple[PeerInfo, ...]:
        peers = tuple(self._peers.values())
        if role is None:
            return peers
        return tuple(peer for peer in peers if peer.role == role)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started.clear()
        self._startup_error = None
        thread = threading.Thread(
            target=self._run_loop,
            name=f"ez-v2-peer-{self._local_peer_id or 'unbound'}",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        self._started.wait(timeout=self.timeout_sec)
        if self._startup_error is not None:
            self.stop()
            raise RuntimeError("transport_peer_network_failed_to_start") from self._startup_error
        if not self._started.is_set():
            self.stop()
            raise RuntimeError("transport_peer_network_start_timeout")

    def stop(self) -> None:
        thread = self._thread
        loop = self._loop
        if thread is None:
            return
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=self.timeout_sec)
        self._thread = None
        self._loop = None
        self._incoming_lock = None
        self._active_request_sender_id = None
        self._active_outbox = None
        self._active_remote_deliveries = None

    def send(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        recipient_id = envelope.recipient_id
        if recipient_id is None:
            raise ValueError("recipient_id required for direct send")
        if recipient_id == self._local_peer_id:
            return self._dispatch_local_delivery(envelope)
        if self._thread is not None and threading.current_thread() is self._thread:
            if self._active_outbox is None or self._active_remote_deliveries is None:
                raise RuntimeError("transport_peer_network_outbox_not_available")
            if recipient_id == self._active_request_sender_id:
                self._active_outbox.append(envelope)
                return {"ok": True, "queued": "inline"}
            self._active_remote_deliveries.append(envelope)
            return {"ok": True, "queued": "remote"}
        response = self._submit_coroutine(self._send_remote(envelope))
        return self._apply_transport_response(response)

    def broadcast(
        self,
        sender_id: str,
        msg_type: str,
        payload: dict[str, Any],
        *,
        role: str | None = None,
    ) -> list[dict[str, Any] | None]:
        results: list[dict[str, Any] | None] = []
        for peer in self.list_peers(role=role):
            if peer.node_id == sender_id:
                continue
            results.append(
                self.send(
                    NetworkEnvelope(
                        msg_type=msg_type,
                        sender_id=sender_id,
                        recipient_id=peer.node_id,
                        payload=payload,
                    )
                )
            )
        return results

    async def _send_remote(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        peer = self.peer_info(envelope.recipient_id or "")
        return await self.transport.send(peer.endpoint, envelope)

    def _apply_transport_response(self, response: dict[str, Any] | None):
        if not isinstance(response, dict):
            return response
        deliveries = response.get("deliveries", ())
        for envelope in deliveries:
            if isinstance(envelope, NetworkEnvelope):
                self._dispatch_local_delivery(envelope)
        return response.get("result")

    def _dispatch_local_delivery(self, envelope: NetworkEnvelope) -> dict[str, Any] | None:
        if self._handler is None:
            raise RuntimeError("transport_peer_network_missing_handler")
        if self._local_peer_id is not None and envelope.recipient_id not in {None, self._local_peer_id}:
            raise ValueError(f"delivery_not_for_local_peer:{envelope.recipient_id}")
        return self._handler(envelope)

    def _submit_coroutine(self, coro):
        loop = self._loop
        if loop is None:
            raise RuntimeError("transport_peer_network_not_started")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=self.timeout_sec)

    async def _handle_envelope(self, envelope: NetworkEnvelope, _remote: str) -> dict[str, Any]:
        if self._handler is None:
            return {"result": {"ok": False, "error": "missing_handler"}, "deliveries": []}
        if self._incoming_lock is None:
            raise RuntimeError("transport_peer_network_not_ready")
        async with self._incoming_lock:
            self._active_request_sender_id = envelope.sender_id
            self._active_outbox = []
            self._active_remote_deliveries = []
            try:
                result = self._handler(envelope)
                for pending in list(self._active_remote_deliveries):
                    try:
                        await self._send_remote(pending)
                    except Exception:
                        # Remote follow-up deliveries are best-effort. A down
                        # peer must not turn the original request into a hard
                        # failure for the caller.
                        continue
                return {
                    "result": result,
                    "deliveries": list(self._active_outbox),
                }
            finally:
                self._active_request_sender_id = None
                self._active_outbox = None
                self._active_remote_deliveries = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._incoming_lock = asyncio.Lock()
        self.transport.set_handler(self._handle_envelope)
        try:
            loop.run_until_complete(self.transport.start())
        except BaseException as exc:
            self._startup_error = exc
            self._started.set()
            loop.close()
            return
        self._started.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self.transport.stop())
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
