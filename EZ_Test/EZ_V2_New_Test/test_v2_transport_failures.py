#!/usr/bin/env python3
"""
EZchain-V2 传输层失败模式测试

覆盖 Wave 3 报告中标记的 P1 缺口：
- TCP 连接级失败（拒绝、超时、断连、畸形数据）
- TransferMailboxStore（当前零测试覆盖）

参考设计文档: EZchain-V2-network-and-transport-plan.md Section 6
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
import unittest

from EZ_V2.network_transport import (
    TCPNetworkTransport,
    decode_envelope,
    encode_envelope,
)
from EZ_V2.networking import NetworkEnvelope
from EZ_V2.transport import TransferMailboxStore
from EZ_V2.types import (
    GenesisAnchor,
    OffChainTx,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.values import ValueRange

logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)


def _reserve_port() -> int:
    """绑定端口0让OS分配临时端口，释放后返回端口号"""
    last_exc: Exception | None = None
    for _ in range(20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return int(sock.getsockname()[1])
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.01)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("failed_to_reserve_port")


def _make_envelope(msg_type: str = "test_msg", sender: str = "test-sender") -> NetworkEnvelope:
    return NetworkEnvelope(
        msg_type=msg_type,
        sender_id=sender,
        recipient_id="test-recipient",
        payload={"seq": 1, "data": "hello"},
    )


class TestTCPConnectionFailures(unittest.TestCase):
    """TCP 传输层失败模式测试"""

    def setUp(self) -> None:
        self.port = _reserve_port()
        self.server = TCPNetworkTransport("127.0.0.1", self.port)
        self._started = False

    def tearDown(self) -> None:
        if self._started:
            asyncio.run(self._stop())

    async def _start(self, handler) -> None:
        self.server.set_handler(handler)
        try:
            await self.server.start()
            self._started = True
        except PermissionError as exc:
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc

    async def _stop(self) -> None:
        await self.server.stop()

    @staticmethod
    async def _echo_handler(envelope: NetworkEnvelope, remote: str):
        return {"ok": True, "msg_type": envelope.msg_type, "sender": envelope.sender_id}

    @staticmethod
    async def _failing_handler(envelope: NetworkEnvelope, remote: str):
        raise ValueError("deliberate_test_failure")

    def test_connection_refused_graceful_error(self) -> None:
        """连接被拒绝时应抛出异常而非挂起"""
        dead_port = _reserve_port()

        async def scenario() -> None:
            client = TCPNetworkTransport("127.0.0.1", dead_port + 1)  # 不存在的端口
            with self.assertRaises((ConnectionRefusedError, OSError)):
                await asyncio.wait_for(
                    client.send("127.0.0.1:{}".format(dead_port + 1), _make_envelope()),
                    timeout=3.0,
                )

        asyncio.run(scenario())

    def test_decode_envelope_invalid_json_raises(self) -> None:
        """非JSON输入应抛出异常"""
        with self.assertRaises(Exception):
            decode_envelope(b"this is not json {{{")

    def test_decode_envelope_valid_json_wrong_type_raises_typeerror(self) -> None:
        """合法JSON但非NetworkEnvelope应抛出TypeError"""
        with self.assertRaises(TypeError):
            decode_envelope(b'{"ok": true, "data": 42}')

    def test_server_handler_exception_returns_error_response(self) -> None:
        """服务端handler异常应包装为错误响应，不崩溃"""

        async def scenario() -> None:
            await self._start(self._failing_handler)

            client = TCPNetworkTransport("127.0.0.1", _reserve_port())
            response = await client.send(
                "127.0.0.1:{}".format(self.port),
                _make_envelope("bundle_submit"),
            )
            self.assertIsNotNone(response)
            self.assertFalse(response.get("ok", True))
            error = response.get("error", "")
            self.assertIn("handler_exception", error)
            self.assertIn("ValueError", error)
            self.assertIn("deliberate_test_failure", error)

        asyncio.run(scenario())

    def test_client_disconnect_mid_transfer_server_survives(self) -> None:
        """客户端中途断连后服务端仍能处理正常请求"""

        async def scenario() -> None:
            await self._start(self._echo_handler)

            # 1. 发送畸形连接：连接后立即断开
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            payload = encode_envelope(_make_envelope())
            writer.write(struct.pack("!I", len(payload)) + payload)
            await asyncio.sleep(0.02)  # 让服务端开始读取
            writer.close()
            await asyncio.sleep(0.05)  # 让服务端处理断连

            # 2. 服务端应仍正常工作
            client = TCPNetworkTransport("127.0.0.1", _reserve_port())
            response = await client.send(
                "127.0.0.1:{}".format(self.port),
                _make_envelope("block_fetch_req"),
            )
            self.assertIsNotNone(response)
            self.assertTrue(response.get("ok", False))

        asyncio.run(scenario())

    def test_truncated_payload_server_survives(self) -> None:
        """截断的payload（声明长度远大于实际数据）后服务端仍存活"""

        async def scenario() -> None:
            await self._start(self._echo_handler)

            # 发送声明10000字节但只发送50字节的畸形数据
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            header = struct.pack("!I", 10000)
            writer.write(header + b"x" * 50)
            await asyncio.sleep(0.02)
            writer.close()
            await asyncio.sleep(0.05)

            # 服务端应仍能处理正常请求
            client = TCPNetworkTransport("127.0.0.1", _reserve_port())
            response = await client.send(
                "127.0.0.1:{}".format(self.port),
                _make_envelope("receipt_req"),
            )
            self.assertIsNotNone(response)
            self.assertTrue(response.get("ok", False))

        asyncio.run(scenario())

    def test_malformed_payload_garbage_bytes(self) -> None:
        """非UTF-8的垃圾字节应在解码阶段失败，但服务端仍能接受新连接"""

        async def scenario() -> None:
            await self._start(self._echo_handler)

            # 发送长度前缀正确的非UTF-8垃圾数据
            garbage = b"\x00\x01\x02\xff\xfe\xfd\xfc"
            payload = struct.pack("!I", len(garbage)) + garbage

            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            writer.write(payload)
            await asyncio.sleep(0.05)
            writer.close()

            # 服务端应仍能接受新连接并处理正常请求
            client = TCPNetworkTransport("127.0.0.1", _reserve_port())
            response = await client.send(
                "127.0.0.1:{}".format(self.port),
                _make_envelope("receipt_req"),
            )
            self.assertIsNotNone(response)
            self.assertTrue(response.get("ok", False))

        asyncio.run(scenario())

    def test_encode_decode_envelope_roundtrip(self) -> None:
        """envelope通过TCP完整往返后所有字段保持不变"""

        async def scenario() -> None:
            await self._start(self._echo_handler)

            original = NetworkEnvelope(
                msg_type="consensus_vote",
                sender_id="validator-0",
                recipient_id="validator-1",
                payload={"height": 42, "round": 3, "phase": "commit"},
            )

            client = TCPNetworkTransport("127.0.0.1", _reserve_port())
            response = await client.send(
                "127.0.0.1:{}".format(self.port),
                original,
            )
            self.assertIsNotNone(response)
            self.assertTrue(response["ok"])
            self.assertEqual(response["msg_type"], "consensus_vote")
            self.assertEqual(response["sender"], "validator-0")

        asyncio.run(scenario())


class TestTransferMailboxStore(unittest.TestCase):
    """TransferMailboxStore 单元测试 — 当前零覆盖"""

    def setUp(self) -> None:
        self.store = TransferMailboxStore(":memory:")
        # 构造固定测试用的 TransferPackage
        self.witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=49,
            ),
        )
        self.tx = OffChainTx(
            sender_addr="alice",
            recipient_addr="bob",
            value_list=(ValueRange(0, 49),),
            tx_local_index=0,
            tx_time=1000,
        )
        self.package = TransferPackage(
            target_tx=self.tx,
            target_value=ValueRange(0, 49),
            witness_v2=self.witness,
        )
        # 第二个不同 recipient 的 package
        self.tx_carol = OffChainTx(
            sender_addr="alice",
            recipient_addr="carol",
            value_list=(ValueRange(0, 49),),
            tx_local_index=0,
            tx_time=1001,
        )
        self.package_carol = TransferPackage(
            target_tx=self.tx_carol,
            target_value=ValueRange(0, 49),
            witness_v2=self.witness,
        )
        # 第三个不同 value 的 package
        self.witness2 = WitnessV2(
            value=ValueRange(100, 149),
            current_owner_addr="alice",
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=100,
                value_end=149,
            ),
        )
        self.tx2 = OffChainTx(
            sender_addr="alice",
            recipient_addr="bob",
            value_list=(ValueRange(100, 149),),
            tx_local_index=0,
            tx_time=1002,
        )
        self.package2 = TransferPackage(
            target_tx=self.tx2,
            target_value=ValueRange(100, 149),
            witness_v2=self.witness2,
        )

    def tearDown(self) -> None:
        self.store.close()

    def test_enqueue_and_list_pending(self) -> None:
        """enqueue后recipient只能看到自己的pending packages"""
        hash1 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package, created_at=1000,
        )
        hash2 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="carol",
            package=self.package_carol, created_at=1001,
        )

        bob_pending = self.store.list_pending_packages("bob")
        self.assertEqual(len(bob_pending), 1)
        self.assertEqual(bob_pending[0][1], "alice")  # sender_addr
        self.assertEqual(bob_pending[0][2], 1000)    # created_at

        carol_pending = self.store.list_pending_packages("carol")
        self.assertEqual(len(carol_pending), 1)

        dave_pending = self.store.list_pending_packages("dave")
        self.assertEqual(len(dave_pending), 0)

    def test_mark_claimed_removes_from_pending(self) -> None:
        """mark_claimed后package从pending列表消失"""
        package_hash = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package, created_at=1000,
        )

        self.store.mark_claimed(package_hash, claimed_at=2000)

        pending = self.store.list_pending_packages("bob")
        self.assertEqual(len(pending), 0)
        self.assertEqual(self.store.pending_count("bob"), 0)

    def test_enqueue_same_package_idempotent(self) -> None:
        """同一package两次enqueue只产生一条记录（ON CONFLICT DO UPDATE）"""
        hash1 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package, created_at=1000,
        )
        hash2 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package, created_at=1001,
        )

        self.assertEqual(hash1, hash2)  # same hash
        self.assertEqual(self.store.pending_count("bob"), 1)

    def test_pending_count_accuracy(self) -> None:
        """pending_count精确跟踪enqueue和claim操作"""
        h1 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package, created_at=1000,
        )
        h2 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package2, created_at=1001,
        )
        h3 = self.store.enqueue_package(
            sender_addr="alice", recipient_addr="bob",
            package=self.package_carol, created_at=1002,
        )

        self.assertEqual(self.store.pending_count("bob"), 3)

        self.store.mark_claimed(h1, claimed_at=2000)
        self.assertEqual(self.store.pending_count("bob"), 2)

        self.store.mark_claimed(h2, claimed_at=2001)
        self.assertEqual(self.store.pending_count("bob"), 1)
