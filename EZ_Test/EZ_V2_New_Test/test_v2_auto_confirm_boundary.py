#!/usr/bin/env python3
"""
EZchain-V2 Auto-Confirm 与 Delivery 边界测试

覆盖 Wave 4 报告中标记的 P1 缺口：
- Auto-confirm 门控（全局/按钱包、默认值/覆盖值）
- Receipt 应用边界（重复投递、手动同步、wallet异常）
- Transfer Delivery 边界（未注册recipient、重复投递、replay prevention）

参考设计文档: EZchain-V2-protocol-draft.md Receipt/Delivery 章节
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_V2.chain import ChainStateV2
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.localnet import V2ConsensusNode
from EZ_V2.network_host import LocalCommitAdapter
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2

logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

CHAIN_ID = 90071
GENESIS_HASH = b"\x88" * 32


def _make_wallet(address: str, td: str) -> WalletAccountV2:
    return WalletAccountV2(
        address=address,
        genesis_block_hash=GENESIS_HASH,
        db_path=str(Path(td) / f"{address[:8]}.sqlite3"),
    )


def _make_keypair_and_wallet(td: str) -> tuple[bytes, bytes, str, WalletAccountV2]:
    priv, pub = generate_secp256k1_keypair()
    addr = address_from_public_key_pem(pub)
    wallet = _make_wallet(addr, td)
    return priv, pub, addr, wallet


def _submit_and_produce(runtime: V2Runtime, sender_wallet: WalletAccountV2,
                        sender_priv: bytes, sender_pub: bytes,
                        recipient_addr: str, amount: int = 50,
                        chain_id: int = CHAIN_ID):
    """提交一笔支付并produce block，返回 ProduceBlockResult"""
    submission, _, tx = sender_wallet.build_payment_bundle(
        recipient_addr=recipient_addr,
        amount=amount,
        private_key_pem=sender_priv,
        public_key_pem=sender_pub,
        chain_id=chain_id,
        expiry_height=100,
        fee=0,
        anti_spam_nonce=1,
        tx_time=1,
    )
    runtime.submit_bundle(submission)
    return runtime.produce_block(timestamp=2)


class TestAutoConfirmGate(unittest.TestCase):
    """Auto-confirm 门控逻辑测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_ac_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_default_auto_confirm_applies_receipt(self) -> None:
        """默认 auto_confirm=True，receipt 应自动应用到 wallet"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)  # auto_confirm_receipts=None → uses global True

        try:
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            delivery = result.deliveries[alice_addr]
            self.assertTrue(delivery.applied)
            self.assertIsNone(delivery.error)
            self.assertIsNotNone(delivery.confirmed_unit)
            self.assertEqual(alice.available_balance(), 150)
        finally:
            alice.close()
            bob.close()

    def test_global_off_blocks_all_receipts(self) -> None:
        """全局 auto_confirm=False，所有 receipt 不应自动应用"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID),
                            auto_confirm_registered_wallets=False)
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)  # None → uses global False

        try:
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            delivery = result.deliveries[alice_addr]
            self.assertFalse(delivery.applied)
            self.assertEqual(delivery.error, "auto_confirm_disabled")
            self.assertIsNone(delivery.confirmed_unit)

            # wallet 仍有 pending bundle
            pending = list(alice.list_pending_bundles())
            self.assertEqual(len(pending), 1)
        finally:
            alice.close()
            bob.close()

    def test_per_wallet_true_overrides_global_false(self) -> None:
        """按钱包 auto_confirm=True 覆盖全局 False"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID),
                            auto_confirm_registered_wallets=False)
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice, auto_confirm_receipts=True)

        try:
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            delivery = result.deliveries[alice_addr]
            self.assertTrue(delivery.applied)
            self.assertIsNone(delivery.error)
        finally:
            alice.close()
            bob.close()

    def test_per_wallet_none_uses_global(self) -> None:
        """auto_confirm_receipts=None 时使用全局值"""
        for global_val in [True, False]:
            priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
            _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

            alice.add_genesis_value(ValueRange(0, 199))
            runtime = V2Runtime(
                chain=ChainStateV2(chain_id=CHAIN_ID),
                auto_confirm_registered_wallets=global_val,
            )
            runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
            runtime.register_wallet(alice, auto_confirm_receipts=None)

            try:
                result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)
                delivery = result.deliveries[alice_addr]
                self.assertEqual(delivery.applied, global_val)
                if not global_val:
                    self.assertEqual(delivery.error, "auto_confirm_disabled")
            finally:
                alice.close()
                bob.close()

    def test_unregistered_wallet_returns_error(self) -> None:
        """未注册的wallet应返回 wallet_not_registered 错误"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        # 不注册 alice 的 wallet

        try:
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            delivery = result.deliveries[alice_addr]
            self.assertFalse(delivery.applied)
            self.assertEqual(delivery.error, "wallet_not_registered")
        finally:
            alice.close()
            bob.close()


class TestReceiptApplicationBoundaries(unittest.TestCase):
    """Receipt 应用边界测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_ra_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_redeliver_receipt_fails_gracefully(self) -> None:
        """重复投递同一 receipt 应优雅失败（pending bundle 已消费）"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)

        try:
            # 第一次 produce_block 消费了 receipt
            result1 = _submit_and_produce(runtime, alice, priv, pub, bob_addr)
            self.assertTrue(result1.deliveries[alice_addr].applied)

            # 尝试再次 deliver 同一 receipt
            receipts_to_redeliver = {alice_addr: result1.receipts[alice_addr]}
            deliveries2 = runtime.deliver_receipts(receipts_to_redeliver)
            delivery2 = deliveries2[alice_addr]

            self.assertFalse(delivery2.applied)
            self.assertIn("no pending bundle", delivery2.error)
        finally:
            alice.close()
            bob.close()

    def test_manual_sync_after_auto_confirm_disabled(self) -> None:
        """auto_confirm=False 后通过手动 sync_wallet_receipts 可以应用 receipt"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID),
                            auto_confirm_registered_wallets=False)
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)

        try:
            # produce_block 不自动应用
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)
            self.assertFalse(result.deliveries[alice_addr].applied)

            # 手动同步拉取
            sync_results = runtime.sync_wallet_receipts(alice_addr)
            self.assertEqual(len(sync_results), 1)
            self.assertTrue(sync_results[0].applied)

            # wallet 已更新
            self.assertEqual(alice.available_balance(), 150)
            pending = list(alice.list_pending_bundles())
            self.assertEqual(len(pending), 0)
        finally:
            alice.close()
            bob.close()

    def test_wallet_exception_caught_gracefully(self) -> None:
        """wallet.on_receipt_confirmed 抛异常时应被捕获，返回错误信息"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)

        try:
            with patch.object(
                alice, "on_receipt_confirmed",
                side_effect=RuntimeError("mock_wallet_corruption"),
            ):
                result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            delivery = result.deliveries[alice_addr]
            self.assertFalse(delivery.applied)
            self.assertEqual(delivery.error, "mock_wallet_corruption")
        finally:
            alice.close()
            bob.close()


class TestTransferDeliveryBoundaries(unittest.TestCase):
    """Transfer Delivery 边界测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_td_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_deliver_to_unregistered_recipient(self) -> None:
        """向未注册的 recipient 投递应返回 wallet_not_registered"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)
        # 不注册 bob

        try:
            # 先 produce block 使 receipt 被确认
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            # 导出 transfer package
            # 获取 wallet 中的 ARCHIVED 记录
            archived = [r for r in alice.list_records()
                        if r.local_status == LocalValueStatus.ARCHIVED]
            self.assertTrue(len(archived) > 0, "should have archived records after receipt confirmed")

            record = archived[0]
            # 从 confirmed_unit 中获取 tx
            confirmed_unit = result.deliveries[alice_addr].confirmed_unit
            tx = confirmed_unit.bundle_sidecar.tx_list[0]
            package = alice.export_transfer_package(tx, record.value)

            deliver_result = runtime.deliver_transfer_package(package)

            self.assertFalse(deliver_result.accepted)
            self.assertEqual(deliver_result.error, "wallet_not_registered")
            self.assertIsNone(deliver_result.record)
        finally:
            alice.close()
            bob.close()

    def test_duplicate_transfer_rejected(self) -> None:
        """重复投递同一 transfer package 应被拒绝"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 199))
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 199))
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        try:
            result = _submit_and_produce(runtime, alice, priv, pub, bob_addr)

            # 导出 transfer package
            archived = [r for r in alice.list_records()
                        if r.local_status == LocalValueStatus.ARCHIVED]
            record = archived[0]
            confirmed_unit = result.deliveries[alice_addr].confirmed_unit
            tx = confirmed_unit.bundle_sidecar.tx_list[0]
            package = alice.export_transfer_package(tx, record.value)

            # 第一次投递成功
            result1 = runtime.deliver_transfer_package(package)
            self.assertTrue(result1.accepted)

            # 第二次投递应被拒绝
            result2 = runtime.deliver_transfer_package(package)
            self.assertFalse(result2.accepted)
            self.assertIn("already accepted", result2.error)
        finally:
            alice.close()
            bob.close()

    def test_commit_block_replay_returns_none(self) -> None:
        """重复提交同一 block 应返回 None（replay prevention）"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 99))
        node = V2ConsensusNode(
            store_path=f"{self.td}/consensus.sqlite3",
            chain_id=CHAIN_ID,
            genesis_block_hash=GENESIS_HASH,
        )
        node.register_genesis_allocation(alice_addr, ValueRange(0, 99))
        node.register_wallet(alice)

        try:
            submission, _, tx = alice.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=priv,
                public_key_pem=pub,
                chain_id=CHAIN_ID,
                expiry_height=100,
                fee=0,
                anti_spam_nonce=1,
                tx_time=1,
            )
            node.submit_bundle(submission)
            produced = node.produce_block(timestamp=2)

            # 通过 adapter 重放同一 block
            adapter = LocalCommitAdapter(node)
            replay_result = adapter.commit_block(produced.block)
            self.assertIsNone(replay_result)
        finally:
            alice.close()
            bob.close()
            node.close()

    def test_receipt_dispatch_unknown_peer_no_crash(self) -> None:
        """向未注册的 sender peer 投递 receipt 不应崩溃"""
        priv, pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 99))
        node = V2ConsensusNode(
            store_path=f"{self.td}/consensus.sqlite3",
            chain_id=CHAIN_ID,
            genesis_block_hash=GENESIS_HASH,
        )
        node.register_genesis_allocation(alice_addr, ValueRange(0, 99))
        node.register_wallet(alice)

        try:
            submission, _, tx = alice.build_payment_bundle(
                recipient_addr=bob_addr,
                amount=50,
                private_key_pem=priv,
                public_key_pem=pub,
                chain_id=CHAIN_ID,
                expiry_height=100,
                fee=0,
                anti_spam_nonce=1,
                tx_time=1,
            )
            node.submit_bundle(submission)
            produced = node.produce_block(timestamp=2)

            # produce_block 已内部处理了 receipt delivery
            # 验证 produce_block 成功完成（不会因为未知 peer 而崩溃）
            self.assertEqual(produced.block.header.height, 1)
            self.assertIn(alice_addr, produced.receipts)
        finally:
            alice.close()
            bob.close()
            node.close()
