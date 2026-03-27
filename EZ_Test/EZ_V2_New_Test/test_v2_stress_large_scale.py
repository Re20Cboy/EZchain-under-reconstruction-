#!/usr/bin/env python3
"""
EZchain-V2 大规模压力测试

覆盖场景：
1. 20 个账户并发提交（同一 snapshot window 内）
2. 50 笔顺序支付链
3. Many-to-many 支付网格
4. 大额 value range 碎片化
5. 长链状态正确性验证
6. 多块 snapshot window

注意：V2 架构中 recipient 的 available_balance 需要通过
deliver_transfer_package 才能更新（链上确认只更新 sender 的 receipt）。
因此压力测试包含完整的 submit → produce → export → deliver 流程。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_V2.chain import ChainStateV2
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2

logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

CHAIN_ID = 90092
GENESIS_HASH = b"\xbb" * 32


def _make_wallet(address: str, td: str) -> WalletAccountV2:
    return WalletAccountV2(
        address=address,
        genesis_block_hash=GENESIS_HASH,
        db_path=str(Path(td) / f"{address[:12]}.sqlite3"),
    )


def _make_keypair_and_wallet(td: str) -> tuple[bytes, bytes, str, WalletAccountV2]:
    priv, pub = generate_secp256k1_keypair()
    addr = address_from_public_key_pem(pub)
    wallet = _make_wallet(addr, td)
    return priv, pub, addr, wallet


def _full_payment(runtime: V2Runtime, sender_wallet: WalletAccountV2,
                  sender_priv: bytes, sender_pub: bytes,
                  recipient_addr: str, amount: int, nonce: int,
                  chain_id: int = CHAIN_ID, tx_time: int = 1,
                  deliver_to_recipient: WalletAccountV2 | None = None,
                  ):
    """完整的支付流程: submit → produce → export → deliver

    返回 (ProduceBlockResult, TransferDeliveryResult | None)
    """
    submission, _, tx = sender_wallet.build_payment_bundle(
        recipient_addr=recipient_addr,
        amount=amount,
        private_key_pem=sender_priv,
        public_key_pem=sender_pub,
        chain_id=chain_id,
        expiry_height=10000,
        fee=0,
        anti_spam_nonce=nonce,
        tx_time=tx_time,
    )
    runtime.submit_bundle(submission)
    result = runtime.produce_block(timestamp=2)

    sender_addr = submission.sidecar.sender_addr
    delivery = result.deliveries[sender_addr]
    if not delivery.applied:
        return result, None

    if deliver_to_recipient is None:
        return result, None

    # 导出 transfer package 并投递给 recipient
    archived = [r for r in sender_wallet.list_records()
                if r.local_status == LocalValueStatus.ARCHIVED]
    if not archived:
        return result, None

    record = archived[-1]  # 使用最近的 archived record
    package = sender_wallet.export_transfer_package(
        delivery.confirmed_unit.bundle_sidecar.tx_list[0],
        record.value,
    )
    deliver_result = runtime.deliver_transfer_package(package)
    return result, deliver_result


class TestLargeScaleConcurrentSubmission(unittest.TestCase):
    """大规模并发提交测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_concurrent_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_20_accounts_submit_in_same_snapshot_window(self) -> None:
        """20 个账户在同一 snapshot window 内提交支付

        所有支付应被包含在同一个 block 中。
        """
        NUM_SENDERS = 20
        AMOUNT = 50
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        # 创建 20 个 sender + 1 个 recipient
        _, _, recipient_addr, recipient_wallet = _make_keypair_and_wallet(self.td)
        runtime.register_wallet(recipient_wallet)

        senders = []
        for i in range(NUM_SENDERS):
            priv, pub, addr, wallet = _make_keypair_and_wallet(self.td)
            value = ValueRange(i * 1000, i * 1000 + 999)
            wallet.add_genesis_value(value)
            runtime.register_genesis_allocation(addr, value)
            runtime.register_wallet(wallet)
            senders.append((priv, pub, addr, wallet))

        try:
            # 20 个 sender 同时提交（不 produce，先全部进 mempool）
            for i, (priv, pub, addr, wallet) in enumerate(senders):
                submission, _, tx = wallet.build_payment_bundle(
                    recipient_addr=recipient_addr,
                    amount=AMOUNT,
                    private_key_pem=priv,
                    public_key_pem=pub,
                    chain_id=CHAIN_ID,
                    expiry_height=10000,
                    fee=0,
                    anti_spam_nonce=1000 + i,
                    tx_time=1,
                )
                runtime.submit_bundle(submission)

            # 单次 produce_block 应该打包所有 20 笔支付
            result = runtime.produce_block(timestamp=2)
            self.assertEqual(result.block.header.height, 1)

            # 验证所有 sender 的 receipt 都被确认
            for priv, pub, addr, wallet in senders:
                self.assertIn(addr, result.deliveries)
                delivery = result.deliveries[addr]
                self.assertTrue(delivery.applied, f"sender {addr[:12]} receipt not applied: {delivery.error}")

            # 导出并投递所有 transfer packages 给 recipient
            total_delivered = 0
            for priv, pub, addr, wallet in senders:
                delivery = result.deliveries[addr]
                archived = [r for r in wallet.list_records()
                            if r.local_status == LocalValueStatus.ARCHIVED]
                if archived:
                    record = archived[0]
                    package = wallet.export_transfer_package(
                        delivery.confirmed_unit.bundle_sidecar.tx_list[0],
                        record.value,
                    )
                    deliver = runtime.deliver_transfer_package(package)
                    if deliver.accepted:
                        total_delivered += 1

            # 所有 transfer 应成功投递
            self.assertEqual(total_delivered, NUM_SENDERS)
            # recipient 应该收到 20 * 50 = 1000
            self.assertEqual(recipient_wallet.available_balance(), NUM_SENDERS * AMOUNT)

        finally:
            for _, _, _, wallet in senders:
                wallet.close()
            recipient_wallet.close()

    def test_10_accounts_multiple_rounds(self) -> None:
        """10 个账户连续 3 轮支付

        每轮所有账户支付给下一个账户（环形）。
        """
        NUM = 10
        ROUNDS = 3
        AMOUNT = 30
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        accounts = []
        for i in range(NUM):
            priv, pub, addr, wallet = _make_keypair_and_wallet(self.td)
            value = ValueRange(i * 10000, i * 10000 + 9999)
            wallet.add_genesis_value(value)
            runtime.register_genesis_allocation(addr, value)
            runtime.register_wallet(wallet)
            accounts.append((priv, pub, addr, wallet))

        try:
            for round_num in range(ROUNDS):
                for i in range(NUM):
                    sender = accounts[i]
                    recipient = accounts[(i + 1) % NUM]
                    result, _ = _full_payment(
                        runtime, sender[3], sender[0], sender[1],
                        recipient[2], AMOUNT,
                        nonce=round_num * NUM + i + 1,
                        tx_time=round_num * NUM + i + 1,
                    )
                    delivery = result.deliveries[sender[2]]
                    self.assertTrue(delivery.applied,
                                    f"round={round_num} sender={i}: {delivery.error}")

            # 所有账户应有正余额（发出 3 * 30，收 3 * 30）
            for i, (priv, pub, addr, wallet) in enumerate(accounts):
                self.assertTrue(wallet.available_balance() > 0,
                                f"account {i} has zero balance after {ROUNDS} rounds")
        finally:
            for _, _, _, wallet in accounts:
                wallet.close()


class TestSequentialPaymentChain(unittest.TestCase):
    """长顺序支付链测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_chain_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_30_sequential_payments_preserve_conservation(self) -> None:
        """Alice → Bob 连续 30 笔支付，验证值守恒"""
        TOTAL_PAYMENTS = 30
        AMOUNT = 2
        INITIAL_VALUE = ValueRange(0, 9999)

        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(INITIAL_VALUE)
        runtime.register_genesis_allocation(alice_addr, INITIAL_VALUE)
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        try:
            for i in range(TOTAL_PAYMENTS):
                result, deliver = _full_payment(
                    runtime, alice, alice_priv, alice_pub, bob_addr,
                    AMOUNT, nonce=100 + i, tx_time=100 + i,
                    deliver_to_recipient=bob,
                )
                self.assertTrue(result.deliveries[alice_addr].applied,
                                f"payment {i} failed: {result.deliveries[alice_addr].error}")
                self.assertTrue(deliver.accepted, f"delivery {i} failed: {deliver.error}")

            # 验证值守恒
            alice_balance = alice.available_balance()
            bob_balance = bob.available_balance()
            total_transferred = TOTAL_PAYMENTS * AMOUNT

            self.assertEqual(bob_balance, total_transferred)
            self.assertEqual(alice_balance + bob_balance, INITIAL_VALUE.size)
            self.assertEqual(result.block.header.height, TOTAL_PAYMENTS)

        finally:
            alice.close()
            bob.close()

    def test_20_payments_performance_baseline(self) -> None:
        """20 笔支付性能基线 — 确保不超过合理时间"""
        TOTAL_PAYMENTS = 20
        AMOUNT = 1
        INITIAL_VALUE = ValueRange(0, 99999)

        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(INITIAL_VALUE)
        runtime.register_genesis_allocation(alice_addr, INITIAL_VALUE)
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        try:
            start = time.perf_counter()
            for i in range(TOTAL_PAYMENTS):
                _full_payment(
                    runtime, alice, alice_priv, alice_pub, bob_addr,
                    AMOUNT, nonce=200 + i, tx_time=200 + i,
                    deliver_to_recipient=bob,
                )
            elapsed = time.perf_counter() - start

            # 20 笔本地支付（含 openssl 签名）应在 60 秒内完成
            self.assertLess(elapsed, 60.0,
                            f"{TOTAL_PAYMENTS} payments took {elapsed:.2f}s — too slow")

            alice_balance = alice.available_balance()
            bob_balance = bob.available_balance()
            self.assertEqual(bob_balance, TOTAL_PAYMENTS * AMOUNT)
            self.assertEqual(alice_balance + bob_balance, INITIAL_VALUE.size)

            logger.info(f"{TOTAL_PAYMENTS} full-cycle payments: {elapsed:.3f}s "
                        f"({TOTAL_PAYMENTS / max(elapsed, 0.001):.1f} ops/sec)")

        finally:
            alice.close()
            bob.close()


class TestManyToManyPaymentMesh(unittest.TestCase):
    """Many-to-Many 支付网格测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_mesh_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_5x5_payment_mesh(self) -> None:
        """5 个 sender × 5 个 recipient = 25 笔交叉支付

        每个 sender 给每个 recipient 支付一笔。
        """
        NUM = 5
        AMOUNT = 10
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        senders = []
        for i in range(NUM):
            priv, pub, addr, wallet = _make_keypair_and_wallet(self.td)
            value = ValueRange(i * 100000, i * 100000 + 49999)
            wallet.add_genesis_value(value)
            runtime.register_genesis_allocation(addr, value)
            runtime.register_wallet(wallet)
            senders.append((priv, pub, addr, wallet))

        recipients = []
        for i in range(NUM):
            _, _, addr, wallet = _make_keypair_and_wallet(self.td)
            runtime.register_wallet(wallet)
            recipients.append((addr, wallet))

        try:
            for si, (priv, pub, s_addr, s_wallet) in enumerate(senders):
                for ri, (r_addr, r_wallet) in enumerate(recipients):
                    nonce = si * NUM + ri + 1
                    result, deliver = _full_payment(
                        runtime, s_wallet, priv, pub, r_addr,
                        AMOUNT, nonce=nonce, tx_time=nonce,
                        deliver_to_recipient=r_wallet,
                    )
                    delivery = result.deliveries[s_addr]
                    self.assertTrue(delivery.applied,
                                    f"sender={si} recipient={ri}: {delivery.error}")
                    self.assertTrue(deliver.accepted,
                                    f"delivery sender={si} recipient={ri}: {deliver.error}")

            # 每个 recipient 应该收到 NUM * AMOUNT
            for ri, (r_addr, r_wallet) in enumerate(recipients):
                self.assertEqual(r_wallet.available_balance(), NUM * AMOUNT)

        finally:
            for _, _, _, wallet in senders:
                wallet.close()
            for _, wallet in recipients:
                wallet.close()


class TestLargeValueRangeFragmentation(unittest.TestCase):
    """大额 value range 碎片化测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_frag_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_value_split_into_small_payments(self) -> None:
        """一个大额 value 被分成多笔小支付

        验证碎片化后所有 value 仍然正确追踪。
        """
        TOTAL_PAYMENTS = 10
        AMOUNT = 1
        INITIAL_VALUE = ValueRange(0, 99999)  # 100000 units

        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)
        _, _, carol_addr, carol = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(INITIAL_VALUE)
        runtime.register_genesis_allocation(alice_addr, INITIAL_VALUE)
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)
        runtime.register_wallet(carol)

        try:
            # 交替支付给 bob 和 carol
            for i in range(TOTAL_PAYMENTS):
                recipient = bob if i % 2 == 0 else carol
                recipient_wallet = bob if i % 2 == 0 else carol
                result, deliver = _full_payment(
                    runtime, alice, alice_priv, alice_pub,
                    recipient.address, AMOUNT,
                    nonce=500 + i, tx_time=500 + i,
                    deliver_to_recipient=recipient_wallet,
                )
                delivery = result.deliveries[alice_addr]
                self.assertTrue(delivery.applied, f"payment {i} failed: {delivery.error}")
                self.assertTrue(deliver.accepted, f"delivery {i} failed: {deliver.error}")

            # 验证值守恒
            alice_balance = alice.available_balance()
            bob_balance = bob.available_balance()
            carol_balance = carol.available_balance()

            expected_bob = (TOTAL_PAYMENTS // 2) * AMOUNT
            expected_carol = (TOTAL_PAYMENTS - TOTAL_PAYMENTS // 2) * AMOUNT

            self.assertEqual(bob_balance, expected_bob)
            self.assertEqual(carol_balance, expected_carol)
            self.assertEqual(alice_balance + bob_balance + carol_balance, INITIAL_VALUE.size)

            # 验证 alice 的 record 状态（包括剩余的未消费 value + 10 笔 ARCHIVED）
            records = list(alice.list_records())
            archived = [r for r in records if r.local_status == LocalValueStatus.ARCHIVED]
            self.assertEqual(len(archived), TOTAL_PAYMENTS)
            # 应该还有一笔未消费的 value
            spendable = [r for r in records if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE]
            self.assertTrue(len(spendable) >= 1)

        finally:
            alice.close()
            bob.close()
            carol.close()


class TestLongChainStateCorrectness(unittest.TestCase):
    """长链状态正确性验证"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_state_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_block_height_monotonicity_across_50_blocks(self) -> None:
        """50 个 block 的高度必须严格递增"""
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 999999))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 999999))
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        try:
            last_height = 0
            for i in range(50):
                result, _ = _full_payment(
                    runtime, alice, alice_priv, alice_pub, bob_addr,
                    amount=1, nonce=1000 + i, tx_time=1000 + i,
                )
                current_height = result.block.header.height
                self.assertGreater(current_height, last_height,
                                   f"height not monotonic at block {i}: "
                                   f"{last_height} >= {current_height}")
                last_height = current_height

            self.assertEqual(last_height, 50)

        finally:
            alice.close()
            bob.close()

    def test_state_root_changes_across_blocks(self) -> None:
        """每个 block 的 state_root 必须不同（因为状态在变化）"""
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(ValueRange(0, 99999))
        runtime.register_genesis_allocation(alice_addr, ValueRange(0, 99999))
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        try:
            state_roots = []
            for i in range(20):
                result, _ = _full_payment(
                    runtime, alice, alice_priv, alice_pub, bob_addr,
                    amount=5, nonce=2000 + i, tx_time=2000 + i,
                )
                state_roots.append(result.block.header.state_root)

            # 每个 state_root 应该唯一
            self.assertEqual(len(set(state_roots)), len(state_roots),
                             "state_root should be unique per block")

        finally:
            alice.close()
            bob.close()


class TestMultiBlockSnapshotWindows(unittest.TestCase):
    """多块 snapshot window 测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_stress_window_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_5_snapshot_windows_5_senders_each(self) -> None:
        """5 个 snapshot window，每 window 有 5 个 sender

        总共 25 笔支付分布在 5 个 block 中。
        """
        WINDOWS = 5
        SENDERS_PER_WINDOW = 5
        AMOUNT = 5

        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))

        # 创建 collector
        _, _, collector_addr, collector = _make_keypair_and_wallet(self.td)
        runtime.register_wallet(collector)

        all_senders = []
        sender_idx = 0

        try:
            for w in range(WINDOWS):
                window_senders = []
                for s in range(SENDERS_PER_WINDOW):
                    priv, pub, addr, wallet = _make_keypair_and_wallet(self.td)
                    value = ValueRange(sender_idx * 10000, sender_idx * 10000 + 999)
                    wallet.add_genesis_value(value)
                    runtime.register_genesis_allocation(addr, value)
                    runtime.register_wallet(wallet)
                    window_senders.append((priv, pub, addr, wallet))
                    all_senders.append((priv, pub, addr, wallet))
                    sender_idx += 1

                # 所有 sender 在同一 window 提交
                for s, (priv, pub, addr, wallet) in enumerate(window_senders):
                    submission, _, tx = wallet.build_payment_bundle(
                        recipient_addr=collector_addr,
                        amount=AMOUNT,
                        private_key_pem=priv,
                        public_key_pem=pub,
                        chain_id=CHAIN_ID,
                        expiry_height=10000,
                        fee=0,
                        anti_spam_nonce=w * 100 + s + 1,
                        tx_time=w * 100 + s + 1,
                    )
                    runtime.submit_bundle(submission)

                # Produce one block for this window
                result = runtime.produce_block(timestamp=2)
                self.assertEqual(result.block.header.height, w + 1)

                # 验证所有 sender 的 receipt 被确认
                for priv, pub, addr, wallet in window_senders:
                    delivery = result.deliveries[addr]
                    self.assertTrue(delivery.applied,
                                    f"window={w} sender={s}: {delivery.error}")

                # 导出并投递 transfer packages 给 collector
                for priv, pub, addr, wallet in window_senders:
                    delivery = result.deliveries[addr]
                    archived = [r for r in wallet.list_records()
                                if r.local_status == LocalValueStatus.ARCHIVED]
                    if archived:
                        record = archived[0]
                        package = wallet.export_transfer_package(
                            delivery.confirmed_unit.bundle_sidecar.tx_list[0],
                            record.value,
                        )
                        deliver = runtime.deliver_transfer_package(package)
                        self.assertTrue(deliver.accepted,
                                        f"window={w} delivery failed: {deliver.error}")

            # collector 应该收到所有支付
            total = WINDOWS * SENDERS_PER_WINDOW * AMOUNT
            self.assertEqual(collector.available_balance(), total)

        finally:
            for _, _, _, wallet in all_senders:
                wallet.close()
            collector.close()


if __name__ == "__main__":
    unittest.main()
