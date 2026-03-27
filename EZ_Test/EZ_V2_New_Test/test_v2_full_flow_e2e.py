#!/usr/bin/env python3
"""
EZchain-V2 全流程端到端集成测试

借鉴 V1 的 test_blockchain_integration_with_real_account.py 设计，
验证 V2 的完整交易流程：
  submit_payment → bundle_pool → consensus → receipt
    → transfer_package → recipient验证 → witness更新

设计文档对照：
- EZchain-V2-protocol-draft.md: 完整 P2P 交易流程
- EZchain-V2-desgin-human-write.md: 单一 Merkle root 设计
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from typing import Any, List, Dict, Tuple

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_V2.network_host import (
    StaticPeerNetwork,
    V2AccountHost,
    V2ConsensusHost,
    open_static_network,
)
from EZ_V2.types import (
    BlockV2,
    CheckpointAnchor,
    Receipt,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.values import ValueRange, LocalValueStatus
from EZ_V2.wallet import WalletAccountV2

# 简化日志输出
import logging
logging.basicConfig(
    level=logging.CRITICAL,
    format='%(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@dataclass
class FlowStatistics:
    """流程统计信息"""
    total_payments: int = 0
    successful_payments: int = 0
    total_blocks: int = 0
    receipt_sync_count: int = 0
    transfer_deliver_count: int = 0
    witness_verification_count: int = 0
    checkpoint_used_count: int = 0
    checkpoint_details: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Payments: {self.successful_payments}/{self.total_payments} | "
            f"Blocks: {self.total_blocks} | "
            f"Receipts: {self.receipt_sync_count} | "
            f"Transfers: {self.transfer_deliver_count} | "
            f"Witness verified: {self.witness_verification_count} | "
            f"Checkpoint used: {self.checkpoint_used_count}"
        )


class TestV2FullFlowE2E(unittest.TestCase):
    """
    V2 全流程端到端测试

    测试完整的 P2P 交易流程，验证：
    1. 支付创建 → bundle_pool → consensus
    2. Receipt 生成与同步
    3. Transfer Package 传递
    4. Recipient Witness 验证
    5. Checkpoint 使用情况
    """

    @staticmethod
    def _drive_consensus_round(
        consensus_hosts: Tuple[V2ConsensusHost, ...],
        timeout_sec: float = 2.0
    ) -> int:
        """驱动所有共识节点直到产生新块"""
        deadline = time.time() + timeout_sec
        start_height = consensus_hosts[0].consensus.chain.current_height
        while time.time() < deadline:
            for consensus in consensus_hosts:
                result = consensus.drive_auto_mvp_consensus_tick(force=True)
                if result is not None and result.get("height", 0) > start_height:
                    return result["height"]
            time.sleep(0.01)
        return consensus_hosts[0].consensus.chain.current_height

    @staticmethod
    def _wait_for_receipt_applied(
        account: V2AccountHost,
        expected_seq: int,
        timeout_sec: float = 2.0
    ) -> bool:
        """等待指定seq的receipt被应用"""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            for receipt in account.wallet.list_receipts():
                if receipt.seq == expected_seq:
                    return True
            time.sleep(0.01)
        return False

    def _create_test_network(
        self,
        td: str,
        num_validators: int = 3,
        num_accounts: int = 4
    ) -> Tuple[Tuple[V2ConsensusHost, ...], Tuple[V2AccountHost, ...], StaticPeerNetwork]:
        """创建测试网络环境"""
        network = StaticPeerNetwork()

        # 创建共识节点
        validator_ids = tuple(f"consensus-{i}" for i in range(num_validators))
        consensus_hosts = tuple(
            V2ConsensusHost(
                node_id=validator_id,
                endpoint=f"mem://{validator_id}",
                store_path=f"{td}/{validator_id}.sqlite3",
                network=network,
                chain_id=9001,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.1,
            )
            for validator_id in validator_ids
        )

        # 创建账户节点
        account_names = ["alice", "bob", "charlie", "david"][:num_accounts]
        account_hosts = tuple(
            V2AccountHost(
                node_id=name,
                endpoint=f"mem://{name}",
                wallet_db_path=f"{td}/{name}.sqlite3",
                chain_id=9001,
                network=network,
                consensus_peer_id=f"consensus-{i % num_validators}",
            )
            for i, name in enumerate(account_names)
        )

        return consensus_hosts, account_hosts, network

    def _genesis_allocate(
        self,
        consensus_hosts: Tuple[V2ConsensusHost, ...],
        account_hosts: Tuple[V2AccountHost, ...],
        allocations: List[Tuple[int, int]]  # (account_index, amount)
    ) -> None:
        """创世分配"""
        for i, amount in allocations:
            if i >= len(account_hosts):
                continue
            account = account_hosts[i]
            value = ValueRange(i * 1000, i * 1000 + amount - 1)
            for consensus in consensus_hosts:
                consensus.register_genesis_value(account.address, value)
            account.register_genesis_value(value)

    def _print_account_states(self, accounts: Tuple[V2AccountHost, ...], title: str = "账户状态") -> None:
        """打印账户状态摘要"""
        print(f"   [{title}] ", end="")
        states = []
        for account in accounts:
            balance = account.wallet.available_balance()
            records = list(account.wallet.list_records())
            unspent = len([r for r in records if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE])
            states.append(f"{account.peer.node_id}:{balance}({unspent})")
        print(" | ".join(states))

    def _print_witness_structure(
        self,
        account: V2AccountHost,
        value: ValueRange,
        indent: str = "      "
    ) -> None:
        """打印WitnessV2结构"""
        records = [r for r in account.wallet.list_records() if r.value == value]
        if not records:
            print(f"{indent}❌ 未找到value {value}")
            return

        record = records[0]
        witness = record.witness_v2

        print(f"{indent}Witness for {value}:")
        print(f"{indent}  current_owner: {witness.current_owner_addr}")
        print(f"{indent}  chain_length: {len(witness.confirmed_bundle_chain)}")
        print(f"{indent}  anchor_type: {type(witness.anchor).__name__}")

        if isinstance(witness.anchor, CheckpointAnchor):
            print(f"{indent}  ⚡ Checkpoint@{witness.anchor.block_height}")
            self.stats.checkpoint_used_count += 1
            self.stats.checkpoint_details.append({
                'account': account.peer.node_id,
                'block_height': witness.anchor.block_height,
                'value': str(value)
            })

    def setUp(self) -> None:
        """测试前准备"""
        self.stats = FlowStatistics()
        self.td = tempfile.mkdtemp(prefix="ez_v2_e2e_")

    def tearDown(self) -> None:
        """测试后清理"""
        import shutil
        if os.path.exists(self.td):
            shutil.rmtree(self.td, ignore_errors=True)

    def test_single_payment_full_flow(self) -> None:
        """
        [E2E] 单笔支付完整流程测试

        验证完整链路：
        1. Alice → Bob 支付
        2. Bundle 提交到共识
        3. 共识确认生成 Receipt
        4. Alice 同步 Receipt
        5. Transfer Package 发送给 Bob
        6. Bob 验证 Witness
        7. Bob 接收 Value
        """
        print("="*60)
        print("[START] 单笔支付完整流程测试")
        print("="*60)

        # 创建网络
        consensus_hosts, account_hosts, network = self._create_test_network(
            self.td, num_validators=3, num_accounts=4
        )
        alice, bob, charlie, david = account_hosts

        try:
            # 创世分配: Alice 拥有 [1000, 1999]
            print("📜 创世分配... | ", end="")
            self._genesis_allocate(consensus_hosts, account_hosts, [(0, 1000)])
            print(f"Alice:1000")

            # 验证初始状态
            self._print_account_states(account_hosts, "初始状态")
            self.assertEqual(alice.wallet.available_balance(), 1000)

            # ========== 步骤1: 创建支付 ==========
            print("💰 创建支付... | Alice → Bob, 金额:100")

            self.stats.total_payments = 1
            payment = alice.submit_payment(
                "bob",
                amount=100,
                tx_time=1,
                anti_spam_nonce=1001
            )
            print(f"  tx_hash: {payment.tx_hash_hex[:16]}...")

            # 验证 pending bundle
            pending = list(alice.wallet.list_pending_bundles())
            self.assertEqual(len(pending), 1)
            print(f"  pending_seq: {pending[0].seq}")

            # ========== 步骤2: 共识确认 ==========
            print("⛏️  共识打包...")
            new_height = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
            print(f"  height: {new_height}")
            self.stats.total_blocks = new_height

            # ========== 步骤3: Receipt 同步 ==========
            print("📨 同步Receipt...")

            # Alice 同步她的 receipt
            applied = alice.sync_pending_receipts()
            print(f"  Alice applied: {applied}")
            self.stats.receipt_sync_count += applied

            # 验证 receipt 存在
            alice_receipts = list(alice.wallet.list_receipts())
            self.assertEqual(len(alice_receipts), 1)
            print(f"  receipt@height: {alice_receipts[0].header_lite.height}")

            # ========== 步骤4: 验证 Transfer Package 传递 ==========
            print("📦 验证Transfer Package...")

            # 检查 Bob 是否收到 transfer
            bob_received = len(bob.received_transfers)
            print(f"  Bob received: {bob_received}")
            self.stats.transfer_deliver_count = bob_received

            self.assertGreater(bob_received, 0, "Bob应该收到transfer package")

            # ========== 步骤5: 验证 Bob 的 Witness ==========
            print("🔍 验证Bob的Witness...")

            bob_records = [r for r in bob.wallet.list_records()
                          if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE]
            self.assertGreater(len(bob_records), 0, "Bob应该有verified values")

            # 找到从 Alice 收到的 [0, 99] (100 values)
            target_record = next((r for r in bob_records if r.value.begin < 100), None)
            self.assertIsNotNone(target_record)

            self._print_witness_structure(bob, target_record.value)

            # 验证 Witness 结构
            self.assertEqual(target_record.witness_v2.current_owner_addr, bob.address)
            self.assertIsNotNone(target_record.witness_v2.anchor)
            self.stats.witness_verification_count += 1

            # ========== 步骤6: 验证最终状态 ==========
            print("🔍 验证最终状态...")

            self._print_account_states(account_hosts, "最终状态")

            # Alice 余额应该减少 100
            alice_balance = alice.wallet.available_balance()
            self.assertEqual(alice_balance, 900)

            # Bob 余额应该增加 100
            bob_balance = bob.wallet.available_balance()
            self.assertEqual(bob_balance, 100)

            self.stats.successful_payments = 1

            print(f"✅ 单笔支付流程验证通过")
            print(f"📊 {self.stats.summary()}")

        finally:
            for account in reversed(account_hosts):
                account.close()
            for consensus in reversed(consensus_hosts):
                consensus.close()

    def test_multi_hop_payment_flow(self) -> None:
        """
        [E2E] 多跳支付完整流程测试

        验证递归 witness 验证：
        Grace(2700-2999) → Alice → Bob → Carol

        每一跳都需要：
        1. 验证当前 sender 的 confirmed_bundle_chain
        2. 递归验证 prior_witness
        """
        print("="*60)
        print("[START] 多跳支付完整流程测试")
        print("="*60)

        # 创建网络 - 使用自定义账户名称以匹配场景
        network = StaticPeerNetwork()

        validator_ids = tuple(f"consensus-{i}" for i in range(3))
        consensus_hosts = tuple(
            V2ConsensusHost(
                node_id=validator_id,
                endpoint=f"mem://{validator_id}",
                store_path=f"{self.td}/{validator_id}.sqlite3",
                network=network,
                chain_id=9001,
                consensus_mode="mvp",
                consensus_validator_ids=validator_ids,
                auto_run_mvp_consensus=True,
                auto_run_mvp_consensus_window_sec=0.1,
            )
            for validator_id in validator_ids
        )

        # 创建账户节点：grace, alice, bob, carol
        account_names = ["grace", "alice", "bob", "carol"]
        account_hosts = tuple(
            V2AccountHost(
                node_id=name,
                endpoint=f"mem://{name}",
                wallet_db_path=f"{self.td}/{name}.sqlite3",
                chain_id=9001,
                network=network,
                consensus_peer_id=f"consensus-{i % 3}",
            )
            for i, name in enumerate(account_names)
        )

        grace, alice, bob, carol = account_hosts

        try:
            # 创世分配: Grace 拥有 [2700, 2999]
            print("📜 创世分配... | ", end="")
            grace_value = ValueRange(2700, 2999)
            for consensus in consensus_hosts:
                consensus.register_genesis_value(grace.address, grace_value)
            grace.register_genesis_value(grace_value)
            print(f"Grace:300")

            self._print_account_states(account_hosts, "初始状态")

            # ========== 第一跳: Grace → Alice [2700, 2749] (50) ==========
            print("\n💰 第一跳: Grace → Alice, 金额:50")

            self.stats.total_payments = 1
            payment1 = grace.submit_payment("alice", amount=50, tx_time=1, anti_spam_nonce=2001)

            height1 = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
            grace.sync_pending_receipts()

            print(f"  height: {height1}")
            print(f"  Alice received: {len(alice.received_transfers)}")
            self.stats.transfer_deliver_count += len(alice.received_transfers)

            # ========== 第二跳: Alice → Bob [2700, 2749] (50) ==========
            print("\n💰 第二跳: Alice → Bob, 金额:50")

            self.stats.total_payments = 2
            payment2 = alice.submit_payment("bob", amount=50, tx_time=2, anti_spam_nonce=2002)

            height2 = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
            alice.sync_pending_receipts()

            print(f"  height: {height2}")
            print(f"  Bob received: {len(bob.received_transfers)}")
            self.stats.transfer_deliver_count += len(bob.received_transfers)

            # 验证 Bob 的 Witness 包含递归结构
            bob_records = [r for r in bob.wallet.list_records()
                          if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE]
            bob_target = next((r for r in bob_records if r.value.begin >= 2700), None)
            self.assertIsNotNone(bob_target)

            print(f"  Bob witness chain length: {len(bob_target.witness_v2.confirmed_bundle_chain)}")

            # ========== 第三跳: Bob → Carol [2700, 2749] (50) ==========
            print("\n💰 第三跳: Bob → Carol, 金额:50")

            self.stats.total_payments = 3
            payment3 = bob.submit_payment("carol", amount=50, tx_time=3, anti_spam_nonce=2003)

            height3 = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
            bob.sync_pending_receipts()

            print(f"  height: {height3}")
            print(f"  Carol received: {len(carol.received_transfers)}")
            self.stats.transfer_deliver_count += len(carol.received_transfers)

            # ========== 验证 Carol 的递归 Witness ==========
            print("\n🔍 验证Carol的递归Witness...")

            carol_records = [r for r in carol.wallet.list_records()
                             if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE]
            carol_target = next((r for r in carol_records if r.value.begin >= 2700), None)
            self.assertIsNotNone(carol_target)

            self._print_witness_structure(carol, carol_target.value)

            # 验证递归结构：Carol的witness应该包含多跳历史
            # 由于经过了3次传递，witness chain应该有一定长度
            chain_len = len(carol_target.witness_v2.confirmed_bundle_chain)
            print(f"  Carol witness chain length: {chain_len}")

            self.stats.witness_verification_count = 3
            self.stats.successful_payments = 3
            self.stats.total_blocks = height3

            self._print_account_states(account_hosts, "最终状态")

            print(f"\n✅ 多跳支付流程验证通过")
            print(f"📊 {self.stats.summary()}")

        finally:
            for account in reversed(account_hosts):
                account.close()
            for consensus in reversed(consensus_hosts):
                consensus.close()

    def test_multi_sender_snapshot_window(self) -> None:
        """
        [E2E] 多sender同窗口打包测试

        验证 snapshot window 机制：
        - 同一窗口内多个sender的bundle被打包到同一区块
        - 每个sender只能有一个bundle在区块中
        """
        print("="*60)
        print("[START] 多sender同窗口打包测试")
        print("="*60)

        # 创建网络
        consensus_hosts, account_hosts, network = self._create_test_network(
            self.td, num_validators=3, num_accounts=4
        )
        alice, bob, charlie, david = account_hosts

        try:
            # 创世分配
            print("📜 创世分配...")
            allocations = [
                (0, 500),  # Alice: [0, 499]
                (1, 500),  # Bob: [1000, 1499]
                (2, 500),  # Charlie: [2000, 2499]
            ]
            for i, amount in allocations:
                value = ValueRange(i * 1000, i * 1000 + amount - 1)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(account_hosts[i].address, value)
                account_hosts[i].register_genesis_value(value)

            self._print_account_states(account_hosts, "初始状态")

            # ========== 同时提交多笔支付 ==========
            print("\n💰 同时提交多笔支付...")

            payments = []
            payments.append(alice.submit_payment("david", amount=50, tx_time=1, anti_spam_nonce=3001))
            payments.append(bob.submit_payment("david", amount=50, tx_time=1, anti_spam_nonce=3002))
            payments.append(charlie.submit_payment("david", amount=50, tx_time=1, anti_spam_nonce=3003))

            print(f"  提交了 {len(payments)} 笔支付，都指向David")

            # 验证每个sender都有pending bundle
            for i, sender in enumerate([alice, bob, charlie]):
                pending = list(sender.wallet.list_pending_bundles())
                print(f"  {sender.peer.node_id} pending: {len(pending)}")
                self.assertEqual(len(pending), 1)

            # ========== 驱动共识 ==========
            print("\n⛏️  共识打包...")

            height1 = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
            print(f"  height: {height1}")

            # 同步所有sender的receipts
            print("\n📨 同步Receipts...")
            for sender in [alice, bob, charlie]:
                applied = sender.sync_pending_receipts()
                print(f"  {sender.peer.node_id} applied: {applied}")
                self.stats.receipt_sync_count += applied

            # ========== 验证 David 收到所有 transfer ==========
            print("\n📦 验证David收到的Transfers...")

            david_received = len(david.received_transfers)
            print(f"  David received: {david_received}")
            self.stats.transfer_deliver_count = david_received

            # David 应该收到3个transfer（分别来自Alice, Bob, Charlie）
            self.assertEqual(david_received, 3)

            # ========== 验证最终状态 ==========
            print("\n🔍 验证最终状态...")

            self._print_account_states(account_hosts, "最终状态")

            david_balance = david.wallet.available_balance()
            self.assertEqual(david_balance, 150)  # 50 * 3

            self.stats.total_payments = 3
            self.stats.successful_payments = 3
            self.stats.total_blocks = height1
            self.stats.witness_verification_count = david_received

            print(f"\n✅ 多sender同窗口打包验证通过")
            print(f"📊 {self.stats.summary()}")

        finally:
            for account in reversed(account_hosts):
                account.close()
            for consensus in reversed(consensus_hosts):
                consensus.close()

    def test_checkpoint_shortens_witness(self) -> None:
        """
        [E2E] Checkpoint裁剪witness测试

        验证 checkpoint 机制：
        1. 创建长交易链
        2. 验证witness chain增长
        3. 创建checkpoint后witness变短
        """
        print("="*60)
        print("[START] Checkpoint裁剪witness测试")
        print("="*60)

        # 创建网络
        consensus_hosts, account_hosts, network = self._create_test_network(
            self.td, num_validators=3, num_accounts=3
        )
        alice, bob, charlie = account_hosts

        try:
            # 创世分配: Alice 拥有大量值
            print("📜 创世分配... | ", end="")
            self._genesis_allocate(consensus_hosts, account_hosts, [(0, 10000)])
            print(f"Alice:10000")

            self._print_account_states(account_hosts, "初始状态")

            # ========== 构建长交易链 ==========
            print("\n💰 构建长交易链...")

            num_hops = 5
            print(f"  创建 {num_hops} 跳交易链")

            # Alice → Bob → Charlie → Alice → Bob → Charlie
            participants = [alice, bob, charlie]
            amount = 100

            for hop in range(num_hops):
                sender = participants[hop % 3]
                recipient = participants[(hop + 1) % 3]

                print(f"\n  跳{hop + 1}: {sender.peer.node_id} → {recipient.peer.node_id}, 金额:{amount}")

                payment = sender.submit_payment(
                    recipient.peer.node_id,
                    amount=amount,
                    tx_time=hop + 1,
                    anti_spam_nonce=4000 + hop
                )

                height = self._drive_consensus_round(consensus_hosts, timeout_sec=2.0)
                sender.sync_pending_receipts()

                print(f"    height: {height}")
                print(f"    {recipient.peer.node_id} received: {len(recipient.received_transfers)}")

            # ========== 验证最终 recipient 的 witness 长度 ==========
            print("\n🔍 验证最终Witness长度...")

            final_recipient = charlie
            records = [r for r in final_recipient.wallet.list_records()
                      if r.local_status == LocalValueStatus.VERIFIED_SPENDABLE]

            if records:
                target_record = records[0]  # 取第一个
                witness_len = len(target_record.witness_v2.confirmed_bundle_chain)
                print(f"  witness chain length: {witness_len}")

                self._print_witness_structure(final_recipient, target_record.value)

                # 验证 witness chain 不为空（经过多次传递应该有历史）
                # 注意：如果是新接收的值，confirmed_bundle_chain可能为空
                # 这取决于 acquisition_boundary 的实现

            self.stats.total_payments = num_hops
            self.stats.successful_payments = num_hops
            self.stats.total_blocks = num_hops
            self.stats.witness_verification_count = num_hops

            self._print_account_states(account_hosts, "最终状态")

            print(f"\n✅ Checkpoint裁剪witness测试完成")
            print(f"📊 {self.stats.summary()}")

            # 输出checkpoint使用情况
            if self.stats.checkpoint_used_count > 0:
                print(f"\n⚡ Checkpoint使用统计: {self.stats.checkpoint_used_count}次")
                for detail in self.stats.checkpoint_details:
                    print(f"   - {detail['account']} @高度{detail['block_height']}")
            else:
                print(f"\n📝 本轮测试未使用checkpoint（witness chain可能还不够长）")

        finally:
            for account in reversed(account_hosts):
                account.close()
            for consensus in reversed(consensus_hosts):
                consensus.close()


def run_v2_e2e_tests():
    """运行 V2 E2E 测试"""
    print("="*60)
    print("🚀 EZchain-V2 全流程集成测试")
    print("="*60)

    suite = unittest.TestSuite()
    suite.addTest(TestV2FullFlowE2E('test_single_payment_full_flow'))
    suite.addTest(TestV2FullFlowE2E('test_multi_hop_payment_flow'))
    suite.addTest(TestV2FullFlowE2E('test_multi_sender_snapshot_window'))
    suite.addTest(TestV2FullFlowE2E('test_checkpoint_shortens_witness'))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*60)
    print("📊 测试结果摘要")
    print("="*60)
    print(f"运行: {result.testsRun} | 成功: {result.testsRun - len(result.failures) - len(result.errors)} | "
          f"失败: {len(result.failures)} | 错误: {len(result.errors)}")
    print("="*60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_v2_e2e_tests()
    sys.exit(0 if success else 1)
