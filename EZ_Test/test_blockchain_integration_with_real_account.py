#!/usr/bin/env python3
"""
EZchain Blockchain Integration Tests with Real Account Nodes - Fixed Version
使用真实Account节点的区块链联调测试 - 修复版本

测试完整的交易注入→交易池→区块形成→上链流程
使用Account.py作为真实账户节点，调用其相关的交易创建和提交操作
完全使用项目模块，不使用任何mock或模拟数据
"""

import sys
import os
import unittest
import tempfile
import shutil
import datetime
import json
import logging
import random
from typing import List, Dict, Any, Tuple

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import (
    Blockchain, ChainConfig, ConsensusStatus
)
from EZ_Main_Chain.Block import Block
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import TransactionPicker, pick_transactions_from_pool
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_GENESIS.genesis import GenesisBlockCreator, create_genesis_block, create_genesis_vpb_for_account

# Configure logging - disable most logging to reduce verbosity
logging.basicConfig(level=logging.CRITICAL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TestBlockchainIntegrationWithRealAccount(unittest.TestCase):
    """使用真实Account节点的区块链联调测试"""

    def setUp(self):
        """测试前准备：创建真实的测试环境和Account节点"""
        # 创建临时目录用于测试
        self.temp_dir = tempfile.mkdtemp()

        # 配置区块链参数（快速确认用于测试）
        self.config = ChainConfig(
            confirmation_blocks=2,  # 2个区块确认
            max_fork_height=3,      # 3个区块后孤儿
            debug_mode=True
        )

        # 创建区块链实例
        self.blockchain = Blockchain(config=self.config)

        # 创建交易池（使用临时数据库）
        self.pool_db_path = os.path.join(self.temp_dir, "test_pool.db")
        self.transaction_pool = TxPool(db_path=self.pool_db_path)

        # 创建交易选择器
        self.transaction_picker = TransactionPicker()

        # 创建真实的Account节点
        self.setup_real_accounts()

        # 创建矿工地址
        self.miner_address = "miner_real_account_test"

    def tearDown(self):
        """测试后清理：删除临时文件"""
        try:
            # 清理Account节点
            for account in self.accounts:
                try:
                    account.cleanup()
                except Exception as e:
                    logger.error(f"清理Account节点失败: {e}")

            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.error(f"清理临时文件失败: {e}")
            # 尝试删除数据库文件
            try:
                if os.path.exists(self.pool_db_path):
                    os.unlink(self.pool_db_path)
            except:
                pass

    def setup_real_accounts(self):
        """创建真实的Account节点并使用项目的创世块模块初始化"""
        self.accounts = []
        account_names = ["alice", "bob", "charlie", "david"]

        print("创建真实Account节点...")

        # 先创建所有Account节点
        for i, name in enumerate(account_names):
            try:
                # 生成真实的密钥对
                private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
                address = f"{name}_real_address_{i:03d}"

                # 创建真实的Account节点
                account = Account(
                    address=address,
                    private_key_pem=private_key_pem,
                    public_key_pem=public_key_pem,
                    name=name
                )

                self.accounts.append(account)
                logger.info(f"创建Account节点: {name} ({address})")

            except Exception as e:
                logger.error(f"创建Account节点失败 {name}: {e}")
                raise RuntimeError(f"Account节点创建失败 {name}: {e}")

        # 使用项目的创世块模块初始化所有账户
        self.initialize_accounts_with_project_genesis()

        print(f"成功创建并初始化 {len(self.accounts)} 个真实Account节点")

    def initialize_accounts_with_project_genesis(self):
        """使用项目自带的EZ_GENESIS模块初始化所有账户"""
        print("= 开始创世初始化...")

        # 创建创世块创建器，使用自定义的面额配置
        custom_denomination = [
            (1000, 1), (500, 1), (100, 5), (50, 10), (10, 20), (1, 50)
        ]

        print(f"[CONFIG] 为 {len(self.accounts)} 个账户创建创世块，配置: 1000×1 + 500×1 + 100×5 + 50×10 + 10×20 + 1×50")

        # 创建创世块
        genesis_block = create_genesis_block(
            accounts=self.accounts,
            denomination_config=custom_denomination,
            custom_sender="0x0000000000000000000000000000000000000",
            custom_miner="ezchain_test_genesis_miner"
        )

        print(f"[SUCCESS] 创世块已创建 (#{genesis_block.index})")

        # 将创世块添加到区块链
        main_chain_updated = self.blockchain.add_block(genesis_block)
        print(f"[{'SUCCESS' if main_chain_updated else 'WARNING'}] 创世块{'已' if main_chain_updated else '未'}添加到主链")

        # 获取创世数据（避免重复创建）
        genesis_creator = GenesisBlockCreator(custom_denomination)
        genesis_multi_txns = genesis_creator._create_genesis_transactions(
            accounts=self.accounts,
            sender_address="0x0000000000000000000000000000000000000"
        )
        merkle_tree, _ = genesis_creator._build_genesis_merkle_tree(genesis_multi_txns)

        # 为每个账户初始化VPB
        for i, account in enumerate(self.accounts):
            print(f"为账户 {account.name} 创世初始化...")

            # 获取对应账户的创世交易（简化验证）
            account_genesis_txn = genesis_multi_txns[i]
            if not account_genesis_txn or not account_genesis_txn.multi_txns:
                raise RuntimeError(f"账户 {account.name} 的创世交易无效")

            # 使用创世块的VPB创建函数
            genesis_values, genesis_proof_units, block_index_result = create_genesis_vpb_for_account(
                account_addr=account.address,
                genesis_block=genesis_block,
                genesis_multi_txn=account_genesis_txn,
                merkle_tree=merkle_tree,
                denomination_config=custom_denomination
            )

            # 批量VPB初始化
            success = account.vpb_manager.initialize_from_genesis_batch(
                genesis_values=genesis_values,
                genesis_proof_units=genesis_proof_units,
                genesis_block_index=block_index_result
            )

            if success:
                total_value = sum(v.value_num for v in genesis_values)
                available_balance = account.get_available_balance()
                print(f"   [SUCCESS] 创世初始化成功: {len(genesis_values)}个Values, 总面额{total_value}, 可用{available_balance}")
            else:
                raise RuntimeError(f"账户 {account.name} VPB初始化失败")

        print(f"[COMPLETE] 所有账户创世初始化完成！")

    def create_real_transaction_requests(self, num_transactions: int = 5) -> List[List[Dict]]:
        """使用真实Account创建交易请求，使用随机选择发送者和接收者，随机金额"""
        all_transaction_requests = []

        for round_num in range(num_transactions):
            round_requests = []
            available_senders = []

            # 首先找出所有有足够余额的发送者
            min_amount = 1  # 最小交易金额
            for account in self.accounts:
                available_balance = account.get_available_balance()
                if available_balance >= min_amount:
                    available_senders.append(account)

            if len(available_senders) < 2:
                logger.warning(f"第{round_num}轮：可用发送者不足({len(available_senders)}个)，跳过此轮")
                continue

            # 每轮创建随机数量的交易请求
            num_requests_this_round = min(random.randint(1, len(available_senders)), len(self.accounts) - 1)

            for i in range(num_requests_this_round):
                # 随机选择发送者和接收者
                sender_account = random.choice(available_senders)
                # 接收者从所有账户中随机选择，但不能是自己
                possible_recipients = [acc for acc in self.accounts if acc.address != sender_account.address]
                recipient_account = random.choice(possible_recipients)

                # 检查发送者当前余额（可能之前的交易已经改变了余额）
                current_balance = sender_account.get_available_balance()

                # 定义可用的面额值（基于创世块配置）
                available_denominations = [100, 50, 10, 1]

                # 过滤出发送者余额支持的面额
                affordable_denominations = [denom for denom in available_denominations
                                         if denom <= current_balance]

                if not affordable_denominations:
                    logger.warning(f"Account {sender_account.name} 余额不足: {current_balance}")
                    # 从可用发送者列表中移除余额不足的账户
                    if sender_account in available_senders:
                        available_senders.remove(sender_account)
                    continue

                # 从可用的面额中随机选择一个金额
                amount = random.choice(affordable_denominations)

                # 生成更真实的nonce和reference
                nonce = random.randint(10000, 99999) + round_num * 100000
                reference = f"tx_{sender_account.name[:3]}_{recipient_account.name[:3]}_{round_num}_{i}"

                # 创建交易请求
                transaction_request = {
                    "sender": sender_account.address,  # 添加sender字段以便后续处理
                    "recipient": recipient_account.address,
                    "amount": amount,
                    "nonce": nonce,
                    "reference": reference
                }

                round_requests.append(transaction_request)
                logger.info(f"创建交易请求: {sender_account.name} → {recipient_account.name}, 金额: {amount}")

            if round_requests:
                all_transaction_requests.append(round_requests)

        return all_transaction_requests

    def create_transactions_from_accounts(self, transaction_requests_list: List[List[Dict]]) -> List[SubmitTxInfo]:
        """使用真实Account创建交易"""
        submit_tx_infos = []

        for round_num, round_requests in enumerate(transaction_requests_list):
            # 为每个账户创建批量交易
            for i, account in enumerate(self.accounts):
                # 找到这个账户的请求
                account_requests = [req for req in round_requests
                                 if self.get_account_by_address(req.get("sender")) == account]

                if not account_requests:
                    continue

                try:
                    # 使用Account的批量交易创建功能
                    multi_txn_result = account.create_batch_transactions(
                        transaction_requests=account_requests,
                        reference=f"round_{round_num}_account_{account.name}"
                    )

                    if multi_txn_result:
                        # 创建SubmitTxInfo
                        submit_tx_info = account.create_submit_tx_info(multi_txn_result)

                        if submit_tx_info:
                            submit_tx_infos.append(submit_tx_info)
                            logger.info(f"Account {account.name} 创建了 {len(account_requests)} 笔交易")
                        else:
                            logger.error(f"Account {account.name} 创建SubmitTxInfo失败")
                    else:
                        logger.error(f"Account {account.name} 批量创建交易失败")

                except Exception as e:
                    logger.error(f"Account {account.name} 创建交易异常: {e}")
                    continue

        return submit_tx_infos

    def get_account_by_address(self, address: str) -> Account:
        """根据地址获取Account节点"""
        for account in self.accounts:
            if account.address == address:
                return account
        return None

    def test_complete_real_account_transaction_flow(self):
        """测试完整的真实Account交易流程：创建→交易池→选择→区块→上链"""
        print("\n" + "="*60)
        print("[START] 开始完整真实Account交易流程测试")
        print("="*60)

        # 步骤1：检查Account节点状态
        print("\n📊 1. 检查账户初始状态...")
        total_balance = 0
        for account in self.accounts:
            account_info = account.get_account_info()
            total_balance += account_info['balances']['total']
            print(f"   💳 {account.name}: 总余额={account_info['balances']['total']}, 可用={account_info['balances']['available']}")
            self.assertGreater(account_info['balances']['total'], 0,
                              f"Account {account.name} 应该有余额")

        # print(f"   💰 所有账户总余额: {total_balance}")

        # 步骤2：创建真实交易请求
        print("\n📝 2. 创建交易请求...")
        transaction_requests_list = self.create_real_transaction_requests(2)  # 减少轮数
        total_requests = sum(len(requests) for requests in transaction_requests_list)
        print(f"   创建 {len(transaction_requests_list)} 轮交易，总计 {total_requests} 个请求")

        # 简明输出交易请求内容，方便调试
        print("   📋 交易请求详情:")
        for round_num, round_requests in enumerate(transaction_requests_list):
            print(f"     第{round_num + 1}轮 ({len(round_requests)}笔交易):")
            for req in round_requests[:4]:  # 只显示前4笔交易，避免输出过多
                sender_name = self.get_account_by_address(req.get("sender")).name if req.get("sender") and self.get_account_by_address(req.get("sender")) else "未知"
                recipient_name = self.get_account_by_address(req["recipient"]).name if self.get_account_by_address(req["recipient"]) else "未知"
                print(f"       {sender_name} → {recipient_name}: {req['amount']}")
            if len(round_requests) > 4:
                print(f"       ... 还有 {len(round_requests) - 4} 笔交易")
    
        # 步骤3：使用真实Account创建交易
        print("\n⚡ 3. 创建交易...")
        submit_tx_infos = self.create_transactions_from_accounts(transaction_requests_list)
        print(f"   成功创建 {len(submit_tx_infos)} 个SubmitTxInfo")
        self.assertGreater(len(submit_tx_infos), 0, "应该创建成功一些交易")

        # 步骤4：将SubmitTxInfo添加到交易池
        print("\n📥 4. 添加交易到交易池...")
        added_count = 0

        for submit_tx_info in submit_tx_infos:
            try:
                success, message = self.transaction_pool.add_submit_tx_info(submit_tx_info)
                if success:
                    added_count += 1
                    logger.info(f"成功添加SubmitTxInfo: {submit_tx_info.submitter_address}")
                else:
                    logger.error(f"添加SubmitTxInfo失败: {message}")
                    # 不抛出异常，继续处理其他交易
            except Exception as e:
                logger.error(f"添加SubmitTxInfo到交易池异常: {e}")
                continue

        print(f"   ✅ 成功添加 {added_count}/{len(submit_tx_infos)} 个交易到交易池")
        self.assertGreater(added_count, 0, "至少应该添加成功一些交易到交易池")

        # 步骤5：从交易池选择交易并打包
        print("\n⛏️  5. 打包区块...")
        try:
            package_data, block = pick_transactions_from_pool(
                tx_pool=self.transaction_pool,
                miner_address=self.miner_address,
                previous_hash=self.blockchain.get_latest_block_hash(),
                block_index=self.blockchain.get_latest_block_index() + 1
            )

            self.assertIsNotNone(package_data)
            self.assertIsNotNone(block)

            if len(package_data.selected_submit_tx_infos) > 0:
                print(f"   📦 创建区块 #{block.index}, 包含 {len(package_data.selected_submit_tx_infos)} 个交易")
                print(f"   🌳 默克尔根: {package_data.merkle_root[:16]}...")
            else:
                print(f"   📦 创建空区块 #{block.index}")

        except Exception as e:
            logger.error(f"交易打包失败: {e}")
            raise RuntimeError(f"从交易池打包交易失败: {e}")

        # 步骤6：将区块添加到区块链
        print("\n🔗 6. 添加区块到区块链...")
        main_chain_updated = self.blockchain.add_block(block)
        self.assertTrue(main_chain_updated)

        fork_node = self.blockchain.get_fork_node_by_hash(block.get_hash())
        block_status = fork_node.consensus_status if fork_node else ConsensusStatus.PENDING
        print(f"   {'✅' if main_chain_updated else '⚠️'} 区块#{'已' if main_chain_updated else '未'}添加到主链, 状态: {block_status.value}")

        # 步骤7：验证Account节点状态
        print("\n🔍 7. 验证最终状态...")
        final_total_balance = 0
        for account in self.accounts:
            account_info = account.get_account_info()
            final_total_balance += account_info['balances']['total']

            # 验证账户完整性
            integrity_valid = account.validate_integrity()
            status_icon = "✅" if integrity_valid else "❌"
            print(f"   {status_icon} {account.name}: 总余额={account_info['balances']['total']}, "
                  f"可用={account_info['balances']['available']}, 交易历史={account_info['transaction_history_count']}")

            self.assertTrue(integrity_valid, f"Account {account.name} 完整性验证失败")

        # 计算余额变化
        balance_change = final_total_balance - total_balance
        fee_rate = (abs(balance_change) / total_balance * 100) if total_balance > 0 else 0

        print(f"\n💰 余额变化: {total_balance} → {final_total_balance} (交易费用: {fee_rate:.1f}%)")

        print("\n" + "="*60)
        print("🎉 真实Account完整交易流程测试通过！")
        print("="*60)


def run_real_account_integration_tests():
    """运行所有真实Account集成测试"""
    print("=" * 80)
    print("🚀 EZchain 真实Account节点集成测试 - 优化版")
    print("突出关键信息，精简输出，便于观察和调试")
    print("=" * 80)

    # 创建测试套件
    suite = unittest.TestSuite()
    suite.addTest(TestBlockchainIntegrationWithRealAccount('test_complete_real_account_transaction_flow'))

    # 运行测试 - 使用较低冗余度
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    # 输出精简测试结果摘要
    print("\n" + "=" * 80)
    print("📊 测试结果摘要")
    print("=" * 80)

    success_count = result.testsRun - len(result.failures) - len(result.errors)
    success_rate = (success_count / result.testsRun * 100) if result.testsRun > 0 else 0

    print(f"📈 运行测试: {result.testsRun}")
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {len(result.failures)}")
    print(f"💥 错误: {len(result.errors)}")
    print(f"📊 成功率: {success_rate:.1f}%")

    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  • {test}")

    if result.errors:
        print("\n💥 错误的测试:")
        for test, traceback in result.errors:
            print(f"  • {test}")

    print("\n" + "=" * 80)
    if success_rate >= 100:
        print("🎉 真实Account集成测试全部通过！系统运行正常")
    elif success_rate >= 80:
        print("✅ 真实Account集成测试基本通过，部分功能正常")
    else:
        print("⚠️ 真实Account集成测试存在问题，需要进一步调试")
    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_real_account_integration_tests()
    sys.exit(0 if success else 1)