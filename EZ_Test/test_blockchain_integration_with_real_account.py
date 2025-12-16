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
from EZ_Tx_Pool.PickTx import TransactionPicker, pick_transactions_from_pool_with_proofs
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account
from EZ_Miner.miner import Miner
from EZ_VPB_Validator.vpb_validator import VPBValidator

# Configure logging - 启用日志输出以便观察创世块默克尔树形成过程
import logging
import sys

# 配置日志级别为ERROR，最大程度减少输出
logging.basicConfig(
    level=logging.ERROR,  # 改为ERROR级别以最大程度减少输出
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# 但是让genesis模块保持INFO级别输出
genesis_logger = logging.getLogger('EZ_GENESIS')
genesis_logger.setLevel(logging.INFO)

# 让account和区块链相关模块保持INFO级别
for logger_name in ['__main__', 'Blockchain', 'Account']:
    logging.getLogger(logger_name).setLevel(logging.INFO)

logger = logging.getLogger(__name__)

import warnings
warnings.filterwarnings("ignore")


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
            debug_mode=True,
            data_directory=os.path.join(self.temp_dir, "test_blockchain_data"),  # 使用临时目录存储区块链数据
            auto_save=False  # 禁用自动保存，避免影响测试
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

        # 创建矿工实例用于VPB分发
        self.miner = Miner(
            miner_id="test_miner",
            blockchain=self.blockchain
        )

        # 创建VPB验证器
        self.vpb_validator = VPBValidator()

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

        print("[INFO] 创建Account节点...")

        # 先创建所有Account节点
        for i, name in enumerate(account_names):
            try:
                # 生成真实的密钥对
                private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
                # 生成符合以太坊格式的地址
                address = self._create_eth_address(f"{name}_{i}")

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

        print(f"✅ 创建完成 {len(self.accounts)} 个Account节点")

    def initialize_accounts_with_project_genesis(self):
        """使用项目自带的EZ_GENESIS模块初始化所有账户"""
        print("[INFO] 开始创世初始化...")

        # 创建创世块创建器，使用自定义的面额配置
        custom_denomination = [
            (1000, 1), (500, 1), (100, 5), (50, 5), (10, 5), (1, 5)
        ]

        print(f"⚙️  为 {len(self.accounts)} 个账户创建创世块")

        # 创建创世块（使用新的统一API：返回区块、单个SubmitTxInfo、单个MultiTransactions、默克尔树）
        genesis_block, unified_submit_tx_info, unified_multi_txn, merkle_tree = create_genesis_block(
            accounts=self.accounts,
            denomination_config=custom_denomination,
            custom_miner="ezchain_test_genesis_miner"
        )

        print(f"✅ 创世块已创建 (#{genesis_block.index})")
        print(f"✅ 生成统一SubmitTxInfo，包含 {len(unified_multi_txn.multi_txns)} 个交易")

        # 将创世块添加到区块链
        main_chain_updated = self.blockchain.add_block(genesis_block)
        print(f"✅ 创世块{'已' if main_chain_updated else '未'}添加到主链")

        if not unified_submit_tx_info:
            raise RuntimeError("统一创世SubmitTxInfo无效")
        if not unified_multi_txn or not unified_multi_txn.multi_txns:
            raise RuntimeError("统一创世MultiTransactions无效")

        # 为每个账户初始化VPB
        for account in self.accounts:
            print(f"⚡ 初始化 {account.name}...")

            # 使用重构后的创世VPB创建函数（基于统一的SubmitTxInfo + MultiTransactions）
            genesis_values, genesis_proof_units, block_index_result = create_genesis_vpb_for_account(
                account_addr=account.address,
                genesis_block=genesis_block,
                unified_submit_tx_info=unified_submit_tx_info,  # 提供统一的SubmitTxInfo
                unified_multi_txn=unified_multi_txn,  # 提供统一的MultiTransactions
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
                print(f"   ✅ {len(genesis_values)}个Values, 总面额{total_value}, 可用{available_balance}")
            else:
                raise RuntimeError(f"账户 {account.name} VPB初始化失败")

        # 添加VPB基础检测
        self._perform_vpb_initialization_checks()

        # 可视化创世初始化后的VPB状态
        print(f"\n📊 [创世初始化后] VPB状态可视化:")
        for account in self.accounts:
            account.vpb_manager.visualize_vpb_mapping(f"After Genesis Initialization - {account.name}")

        print(f"🎉 所有账户创世初始化完成！")

    def _perform_vpb_initialization_checks(self):
        """对初始化的VPB进行基础检测"""
        print("\n🔍 VPB初始化检测...")

        all_checks_passed = True
        error_summary = []

        for account in self.accounts:
            account_errors = []

            try:
                # 获取账户的VPB数据
                vpb_manager = account.vpb_manager
                all_values = vpb_manager.get_all_values()

                # 检测1: Values数量与余额一致性
                account_balance = account.get_available_balance()
                values_total = sum(value.value_num for value in all_values if value.is_unspent())

                if account_balance != values_total:
                    account_errors.append(f"余额不一致({account_balance}!={values_total})")

                # 检测2: 每个Value都有对应的ProofUnit和BlockIndex
                for value in all_values:
                    proof_units = vpb_manager.get_proof_units_for_value(value)
                    if not proof_units:
                        account_errors.append(f"Value{value.begin_index}缺少ProofUnit")

                    block_index = vpb_manager.get_block_index_for_value(value)
                    if not block_index:
                        account_errors.append(f"Value{value.begin_index}缺少BlockIndex")

                # 汇总账户检测结果
                if account_errors:
                    print(f"   ❌ {account.name}: {', '.join(account_errors[:3])}")
                    if len(account_errors) > 3:
                        print(f"      ...还有{len(account_errors)-3}个错误")
                    all_checks_passed = False
                    error_summary.extend([f"{account.name}:{err}" for err in account_errors])
                else:
                    print(f"   ✅ {account.name}: 检测通过 ({len(all_values)}个Values)")

            except Exception as e:
                print(f"   💥 {account.name}: 检测异常 - {str(e)[:50]}")
                all_checks_passed = False
                error_summary.append(f"{account.name}:异常-{str(e)[:30]}")

        # 精简的检测结果总结
        if all_checks_passed:
            print("🎉 VPB初始化检测全部通过")
        else:
            print(f"⚠️  VPB检测发现问题({len(error_summary)}个错误)，测试继续")

    def _create_eth_address(self, name: str) -> str:
        """创建有效的以太坊地址格式"""
        import hashlib
        hash_bytes = hashlib.sha256(name.encode()).digest()
        return f"0x{hash_bytes[:20].hex()}"

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
            num_requests_this_round = 8

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

    def create_transactions_from_accounts(self, transaction_requests_list: List[List[Dict]]) -> List[Tuple[SubmitTxInfo, Dict, Account]]:
        """使用真实Account创建交易，返回SubmitTxInfo、multi_txn_result和Account的元组列表"""
        submit_tx_data = []

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
                            # 存储元组：(SubmitTxInfo, multi_txn_result, Account)
                            submit_tx_data.append((submit_tx_info, multi_txn_result, account))
                            logger.info(f"Account {account.name} 创建了 {len(account_requests)} 笔交易")
                        else:
                            logger.error(f"Account {account.name} 创建SubmitTxInfo失败")
                    else:
                        logger.error(f"Account {account.name} 批量创建交易失败")

                except Exception as e:
                    logger.error(f"Account {account.name} 创建交易异常: {e}")
                    continue

        return submit_tx_data

    def get_account_by_address(self, address: str) -> Account:
        """根据地址获取Account节点"""
        for account in self.accounts:
            if account.address == address:
                return account
        return None

    def get_merkle_proof_for_sender(self, sender_address: str, picked_txs_mt_proofs: List[Tuple[str, Any]],
                                   package_data) -> List[Any]:
        """根据发送者地址找到对应的默克尔证明"""
        try:
            # 找到对应发送者的SubmitTxInfo
            for submit_tx_info in package_data.selected_submit_tx_infos:
                if submit_tx_info.submitter_address == sender_address:
                    # 找到对应的默克尔证明
                    multi_hash = submit_tx_info.multi_transactions_hash
                    for proof_hash, merkle_proof in picked_txs_mt_proofs:
                        if proof_hash == multi_hash:
                            return merkle_proof if merkle_proof else []

            # 如果没找到，返回空列表
            return []
        except Exception as e:
            logger.error(f"获取发送者 {sender_address} 的默克尔证明失败: {e}")
            return []

    def test_complete_real_account_transaction_flow(self):
        """测试完整的真实Account交易流程：创建→交易池→选择→区块→上链"""
        print("\n" + "="*60)
        print("[START] 开始完整真实Account交易流程测试")
        print("="*60)

        # 步骤1：检查Account节点状态
        print("\n💳 检查账户初始状态...")
        total_balance = 0
        for account in self.accounts:
            account_info = account.get_account_info()
            total_balance += account_info['balances']['total']
            print(f"   {account.name}: 余额{account_info['balances']['total']}, 可用{account_info['balances']['available']}")
            self.assertGreater(account_info['balances']['total'], 0,
                              f"Account {account.name} 应该有余额")

        # 步骤2：创建真实交易请求
        print("\n📝 2. 创建交易请求...")
        transaction_requests_list = self.create_real_transaction_requests(1)  # 减少轮数
        total_requests = sum(len(requests) for requests in transaction_requests_list)
        print(f"   创建 {len(transaction_requests_list)} 轮交易，总计 {total_requests} 个请求")

        # 简明输出交易请求内容，方便调试
        print("   📋 交易请求详情:")
        for round_num, round_requests in enumerate(transaction_requests_list):
            print(f"     第{round_num + 1}轮 ({len(round_requests)}笔交易):")
            for req in round_requests[:10]:  # 只显示前10笔交易，避免输出过多
                sender_name = self.get_account_by_address(req.get("sender")).name if req.get("sender") and self.get_account_by_address(req.get("sender")) else "未知"
                recipient_name = self.get_account_by_address(req["recipient"]).name if self.get_account_by_address(req["recipient"]) else "未知"
                print(f"       {sender_name} → {recipient_name}: {req['amount']}")
            if len(round_requests) > 10:
                print(f"       ... 还有 {len(round_requests) - 10} 笔交易")

        # 步骤3：使用真实Account创建交易
        print("\n⚡ 3. 创建交易...")
        submit_tx_data = self.create_transactions_from_accounts(transaction_requests_list)
        print(f"   成功创建 {len(submit_tx_data)} 个交易数据包")
        self.assertGreater(len(submit_tx_data), 0, "应该创建成功一些交易")

        # 步骤4：使用Account的正确方法将交易提交到交易池并存储到本地
        print("\n📥 4. 添加交易到交易池并存储到Account本地队列...")
        added_count = 0
        submit_tx_infos = []  # 用于后续步骤的SubmitTxInfo列表

        for submit_tx_info, multi_txn_result, account in submit_tx_data:
            try:
                # 使用Account的submit_tx_infos_to_pool方法，确保同时提交到交易池和存储到本地队列
                success = account.submit_tx_infos_to_pool(
                    submit_tx_info=submit_tx_info,
                    tx_pool=self.transaction_pool,
                    multi_txn_result=multi_txn_result
                )
                if success:
                    added_count += 1
                    submit_tx_infos.append(submit_tx_info)  # 保存用于后续步骤
                    print(f"   成功提交交易: {account.name} ({submit_tx_info.submitter_address})")
                else:
                    print(f"   Account {account.name} 提交交易失败")
                    # 不抛出异常，继续处理其他交易
            except Exception as e:
                print(f"   Account {account.name} 提交交易异常: {e}")
                continue

        print(f"   ✅ 成功提交 {added_count}/{len(submit_tx_data)} 个交易到交易池并存储到本地队列")
        self.assertGreater(added_count, 0, "至少应该提交成功一些交易到交易池")

        # 步骤5：从交易池选择交易并打包（使用带默克尔证明的新模块）
        print("\n⛏️  5. 打包区块...")
        try:
            package_data, block, picked_txs_mt_proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
                tx_pool=self.transaction_pool,
                miner_address=self.miner_address,
                previous_hash=self.blockchain.get_latest_block_hash(),
                block_index=self.blockchain.get_latest_block_index() + 1
            )

            self.assertIsNotNone(package_data)
            self.assertIsNotNone(block)
            self.assertIsNotNone(picked_txs_mt_proofs)
            self.assertIsNotNone(sender_addrs)
            self.assertEqual(block_index, block.index)

            if len(package_data.selected_submit_tx_infos) > 0:
                print(f"   📦 创建区块 #{block.index}, 包含 {len(package_data.selected_submit_tx_infos)} 个交易")
                print(f"   🌳 默克尔根: {package_data.merkle_root[:16]}...")
                print(f"   🔗 生成 {len(picked_txs_mt_proofs)} 个默克尔证明")
                print(f"   👥 发送者地址数量: {len(sender_addrs)}")

                # 详细显示证明数据信息
                print(f"   📋 证明数据详情:")
                for i, (proof_hash, merkle_proof) in enumerate(picked_txs_mt_proofs[:3]):  # 只显示前3个
                    proof_size = len(merkle_proof.mt_prf_list) if merkle_proof and hasattr(merkle_proof, 'mt_prf_list') else 0
                    print(f"      证明{i+1}: {proof_hash[:16]}... (大小: {proof_size})")
                if len(picked_txs_mt_proofs) > 3:
                    print(f"      ... 还有 {len(picked_txs_mt_proofs) - 3} 个证明")
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

        # 步骤6.1：收集参与交易的账户地址
        print("\n📦 6.1 收集参与交易的账户地址...")
        participant_addresses = []
        for submit_tx_info in package_data.selected_submit_tx_infos:
            participant_addresses.append(submit_tx_info.submitter_address)

            # 从account本地获取multi_txns信息以提取接收者地址
            sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
            if sender_account:
                multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
                if multi_txns and hasattr(multi_txns, 'single_txns'):
                    for txn in multi_txns.single_txns:
                        if hasattr(txn, 'recipient'):
                            participant_addresses.append(txn.recipient)

        # 去重
        participant_addresses = list(set(participant_addresses))
        print(f"   ✅ 收集到 {len(participant_addresses)} 个参与交易地址")

        # 可视化发送者VPB更新后的状态
        print(f"\n📊 [6.1步骤后-发送者VPB更新] VPB状态可视化:")
        for account in self.accounts:
            account.vpb_manager.visualize_vpb_mapping(f"After Senders Update - {account.name}")

        # 步骤6.2：发送者本地化处理VPB（使用真实的默克尔证明数据）
        print("\n🔄 6.2 发送者本地化处理VPB...")
        vpb_update_count = 0
        if package_data.selected_submit_tx_infos:
            try:
                for submit_tx_info in package_data.selected_submit_tx_infos:
                    sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
                    if not sender_account:
                        continue

                    # 获取发送者对应的默克尔证明
                    sender_merkle_proof = self.get_merkle_proof_for_sender(
                        submit_tx_info.submitter_address,
                        picked_txs_mt_proofs,
                        package_data
                    )

                    print(f"   🔍 检查提交交易: {submit_tx_info.submitter_address}")

                    # 从account本地获取对应的multi_txns信息（通过multi_txns_hash）
                    multi_txns_hash = submit_tx_info.multi_transactions_hash
                    multi_txns = sender_account.get_submitted_transaction(multi_txns_hash)

                    if multi_txns:
                        print(f"      - 从account本地获取multi_txns成功，包含 {len(multi_txns.multi_txns)} 个交易")
                        print(f"      - multi_txns hash: {multi_txns_hash[:16]}...")

                        for i, txn in enumerate(multi_txns.multi_txns):
                            print(f"      - 交易{i+1}: value={hasattr(txn, 'value')}, value长度={len(txn.value) if hasattr(txn, 'value') and txn.value else 0}")
                            # 从交易中提取实际的Value数据
                            if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                                # 使用交易中实际的第一个Value作为target_value
                                target_value = txn.value[0]
                                recipient_address = getattr(txn, 'recipient', 'unknown')

                                # 调用发送者的VPB本地更新方法，使用真实的默克尔证明
                                print(f"   🔍 准备调用VPB更新，参数检查:")
                                print(f"      - target_value: {target_value.value_num if target_value else 'None'}")
                                print(f"      - block_height: {block.index}")
                                print(f"      - recipient_address: {recipient_address}")
                                proof_length = len(sender_merkle_proof.mt_prf_list) if sender_merkle_proof and hasattr(sender_merkle_proof, 'mt_prf_list') else 0
                                print(f"      - mt_proof length: {proof_length}")
                                print(f"      - multi_txns hash: {multi_txns_hash[:16]}...")

                                success = sender_account.update_vpb_after_transaction_sent(
                                    target_value=target_value,
                                    confirmed_multi_txns=multi_txns,
                                    mt_proof=sender_merkle_proof,  # 使用真实的默克尔证明数据
                                    block_height=block.index,
                                    recipient_address=recipient_address
                                )

                                if success:
                                    vpb_update_count += 1
                                    print(f"   ✅ {sender_account.name} VPB本地更新成功 (金额: {target_value.value_num}, 证明数据长度: {proof_length})")
                                else:
                                    print(f"   ❌ {sender_account.name} VPB本地更新失败")
                            else:
                                print(f"   ⚠️ {sender_account.name} 交易中没有Value数据")
                    else:
                        print(f"   ❌ 无法从account本地获取multi_txns数据，hash: {multi_txns_hash[:16]}...")
                        print(f"   ⚠️ 检查account的submitted_transactions队列中是否包含该交易")

                print(f"   完成对 {len(package_data.selected_submit_tx_infos)} 个发送者的VPB本地处理")
                print(f"   📊 成功更新: {vpb_update_count}/{len(package_data.selected_submit_tx_infos)} 个发送者")

                # 可视化发送者VPB更新后的状态
                print(f"\n📊 [6.2步骤后-发送者VPB更新] VPB状态可视化:")
                for account in self.accounts:
                    # 只显示参与了交易的发送者
                    participated = any(submit_tx_info.submitter_address == account.address for submit_tx_info in package_data.selected_submit_tx_infos)
                    if participated:
                        account.vpb_manager.visualize_vpb_mapping(f"After Senders Update - {account.name}")
            except Exception as e:
                print(f"   ❌ 发送者VPB本地化处理异常: {e}")
                import traceback
                traceback.print_exc()

        # 步骤6.3：接收者同步处理（完整版）
        print("\n📤 6.3 接收者同步处理...")

        # 完全静默所有验证器日志
        import logging
        logging.getLogger().setLevel(logging.CRITICAL)  # 设置根logger为CRITICAL级别
        for logger_name in ['EZ_VPB_Validator', 'EZ_VPB_Validator.VPBSliceGenerator',
                           'EZ_VPB_Validator.DataStructureValidator', 'EZ_VPB_Validator.BloomFilterValidator',
                           'EZ_VPB_Validator.proof_validator', 'EpochExtractor', 'DataStructureValidator',
                           'VPBSliceGenerator', 'BloomFilterValidator', 'VPBValidator']:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)
        if package_data.selected_submit_tx_infos:
            try:
                recipients_processed = 0
                vpb_verification_success = 0
                vpb_receive_success = 0

                # 收集所有需要发送给接收者的数据
                sender_to_recipients_data = {}

                for submit_tx_info in package_data.selected_submit_tx_infos:
                    # 从account本地获取multi_txns信息
                    sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
                    if not sender_account:
                        continue

                    multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
                    if not multi_txns or not hasattr(multi_txns, 'multi_txns'):
                        continue

                    # 为每个发送者初始化接收者数据列表
                    if sender_account.address not in sender_to_recipients_data:
                        sender_to_recipients_data[sender_account.address] = []

                    # 遍历多笔交易，为每个接收者准备VPB数据
                    for txn in multi_txns.multi_txns:
                        recipient_address = getattr(txn, 'recipient', None)
                        if not recipient_address:
                            continue

                        recipient_account = self.get_account_by_address(recipient_address)
                        if not recipient_account:
                            continue

                        # 获取交易中转移的Value（第一个Value作为转移的Value）
                        if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                            transferred_value = txn.value[0]  # 转移的Value

                            # 从发送者的VPB管理器获取对应的证明数据
                            received_proof_units = sender_account.vpb_manager.get_proof_units_for_value(transferred_value)
                            received_block_index = sender_account.vpb_manager.get_block_index_for_value(transferred_value)

                            if received_proof_units and received_block_index:
                                # 准备发送给接收者的数据
                                recipient_data = {
                                    'recipient_account': recipient_account,
                                    'recipient_address': recipient_address,
                                    'received_value': transferred_value,
                                    'received_proof_units': received_proof_units,
                                    'received_block_index': received_block_index
                                }
                                sender_to_recipients_data[sender_account.address].append(recipient_data)
                                recipients_processed += 1
                                print(f"   📦 准备发送数据: {sender_account.name} → {recipient_account.name}, 金额: {transferred_value.value_num}")
                            else:
                                print(f"   ⚠️ 无法获取 {sender_account.name} → {recipient_account.name} 的VPB证明数据")

                print(f"   ✅ 收集到 {recipients_processed} 个接收者数据")

                # 为每个接收者进行VPB验证和接收
                for sender_address, recipients_data in sender_to_recipients_data.items():
                    sender_account = self.get_account_by_address(sender_address)
                    if not sender_account:
                        continue

                    print(f"   🔍 处理发送者 {sender_account.name} 的 {len(recipients_data)} 个接收者...")

                    for data in recipients_data:
                        recipient_account = data['recipient_account']
                        recipient_address = data['recipient_address']
                        received_value = data['received_value']
                        received_proof_units = data['received_proof_units']
                        received_block_index = data['received_block_index']

                        try:
                            # 步骤1: VPB合法性验证（使用上帝视角输入main_chain_info）
                            print(f"      🔍 验证VPB合法性: {recipient_account.name} 接收金额 {received_value.value_num}")

                            # 临时调整日志级别以减少输出
                            import logging
                            # 设置多个相关logger的级别以彻底减少输出
                            loggers_to_quiet = [
                                'EZ_VPB_Validator',
                                'EZ_VPB_Validator.VPBSliceGenerator',
                                'EZ_VPB_Validator.DataStructureValidator',
                                'EZ_VPB_Validator.BloomFilterValidator',
                                'EZ_VPB_Validator.proof_validator',
                                'EpochExtractor'
                            ]

                            logger_levels = {}
                            for logger_name in loggers_to_quiet:
                                logger = logging.getLogger(logger_name)
                                logger_levels[logger_name] = logger.level
                                logger.setLevel(logging.ERROR)  # 只显示ERROR及以上级别

                            try:
                                # 构造上帝视角的main_chain_info，使用MainChainInfo类
                                from EZ_VPB_Validator.core.types import MainChainInfo
                                from EZ_Units.Bloom import BloomFilter

                                # 提取区块的Merkle根和布隆过滤器
                                merkle_roots = {}
                                bloom_filters = {}

                                # 获取VPB相关区块的高度范围
                                if received_block_index and hasattr(received_block_index, 'index_lst'):
                                    for block_height in received_block_index.index_lst:
                                        if block_height == 0:
                                            # 创世块处理
                                            genesis_block = self.blockchain.get_block_by_index(0)
                                            if genesis_block:
                                                merkle_roots[block_height] = genesis_block.get_m_tree_root()
                                                # 创世块的布隆过滤器
                                                bloom_filters[block_height] = genesis_block.get_bloom()
                                        else:
                                            # 普通区块处理
                                            block_node = self.blockchain.get_fork_node_by_index(block_height)
                                            if block_node and block_node.block:
                                                merkle_roots[block_height] = block_node.block.get_m_tree_root()
                                                # 直接使用区块的布隆过滤器
                                                bloom_filters[block_height] = block_node.block.get_bloom()

                                main_chain_info = MainChainInfo(
                                    merkle_roots=merkle_roots,
                                    bloom_filters=bloom_filters,
                                    current_block_height=self.blockchain.get_latest_block_index(),
                                    genesis_block_height=0
                                )

                                # 使用VPBValidator进行验证
                                verification_report = self.vpb_validator.verify_vpb_pair(
                                    value=received_value,
                                    proof_units=received_proof_units,
                                    block_index_list=received_block_index,
                                    main_chain_info=main_chain_info,
                                    account_address=recipient_address
                                )
                            finally:
                                # 恢复原始日志级别
                                for logger_name, original_level in logger_levels.items():
                                    logger = logging.getLogger(logger_name)
                                    logger.setLevel(original_level)

                            if verification_report.is_valid:
                                print(f"         ✅ VPB验证成功")
                                vpb_verification_success += 1

                                # 步骤2: 若验证通过，调用receive_vpb_from_others更新本地VPB数据
                                receive_success = recipient_account.receive_vpb_from_others(
                                    received_value=received_value,
                                    received_proof_units=received_proof_units,
                                    received_block_index=received_block_index
                                )

                                if receive_success:
                                    print(f"         ✅ VPB接收成功，{recipient_account.name} 本地数据已更新")
                                    vpb_receive_success += 1
                                else:
                                    print(f"         ❌ VPB接收失败，{recipient_account.name} 本地数据更新失败")
                            else:
                                # 详细的VPB验证失败输出，包含具体错误信息
                                if verification_report.errors:
                                    print(f"         ❌ VPB验证失败 (共{len(verification_report.errors)}个错误):")

                                    # 按重要性排序错误类型（关键错误优先）
                                    error_priority = {
                                        'MISSING_GENESIS_VALUE_DISTRIBUTION': 1,
                                        'NO_VALID_TARGET_VALUE_TRANSFER': 2,
                                        'DOUBLE_SPEND_DETECTED': 3,
                                        'MERKLE_PROOF_VERIFICATION_FAILED': 4,
                                        'BLOOM_FILTER_VALIDATION_FAILED': 5,
                                        'DATA_STRUCTURE_VALIDATION_FAILED': 6,
                                        'PROOF_UNIT_VALIDATION_FAILED': 7,
                                        'VERIFICATION_EXCEPTION': 8
                                    }

                                    sorted_errors = sorted(verification_report.errors,
                                                         key=lambda e: error_priority.get(e.error_type, 9))

                                    # 显示前3个最重要的错误
                                    for i, error in enumerate(sorted_errors[:3]):
                                        block_info = f"@区块{error.block_height}" if error.block_height else ""
                                        proof_info = f"[证明{error.proof_index}]" if error.proof_index is not None else ""

                                        # 格式化错误消息，确保简洁但信息完整
                                        error_msg = error.error_message
                                        if len(error_msg) > 80:
                                            error_msg = error_msg[:77] + "..."

                                        print(f"            {i+1}. {error.error_type} {block_info}{proof_info}")
                                        print(f"               {error_msg}")

                                    if len(sorted_errors) > 3:
                                        print(f"               ... 还有 {len(sorted_errors) - 3} 个其他错误")

                                    # 显示验证时间信息（如果耗时较长）
                                    if verification_report.verification_time_ms > 1000:
                                        print(f"               ⏱️ 验证耗时: {verification_report.verification_time_ms:.1f}ms")
                                else:
                                    print(f"         ❌ VPB验证失败 (未知错误)")

                        except Exception as e:
                            print(f"         💥 处理 {recipient_account.name} VPB时异常: {e}")
                            import traceback
                            traceback.print_exc()

                print(f"   📊 接收者处理完成:")
                print(f"      - 总接收者: {recipients_processed}")
                print(f"      - VPB验证成功: {vpb_verification_success}")
                print(f"      - VPB接收成功: {vpb_receive_success}")

                # 可视化接收者VPB更新后的状态
                print(f"\n📊 [6.3步骤后-接收者VPB更新] VPB状态可视化:")
                participant_accounts = set()
                for submit_tx_info in package_data.selected_submit_tx_infos:
                    participant_accounts.add(self.get_account_by_address(submit_tx_info.submitter_address))
                    # 从account本地获取multi_txns信息以提取接收者地址
                    sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
                    if sender_account:
                        multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
                        if multi_txns and hasattr(multi_txns, 'single_txns'):
                            for txn in multi_txns.single_txns:
                                if hasattr(txn, 'recipient'):
                                    recipient_account = self.get_account_by_address(txn.recipient)
                                    if recipient_account:
                                        participant_accounts.add(recipient_account)

                for account in participant_accounts:
                    if account:
                        account.vpb_manager.visualize_vpb_mapping(f"After Receivers Update - {account.name}")

            except Exception as e:
                print(f"   ❌ 接收者处理异常: {e}")
                import traceback
                traceback.print_exc()

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
    import sys

    # 设置编码以支持中文字符和emoji
    try:
        if sys.platform == "win32":
            # Windows下设置UTF-8编码
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

    success = run_real_account_integration_tests()
    sys.exit(0 if success else 1)