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
import datetime
import json
import logging
import random
import copy
from typing import List, Dict, Any, Tuple

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

# 导入临时数据管理器
from temp_data_manager import TempDataManager, create_test_environment

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
from EZ_VPB.values.Value import Value, ValueState
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account
from EZ_Miner.miner import Miner

# Configure logging - 精简输出，只保留关键信息
import logging
import sys

# 配置根logger为CRITICAL级别，最大程度减少输出
logging.basicConfig(
    level=logging.CRITICAL,  # 只显示严重错误
    format='%(levelname)s: %(message)s',  # 简化格式
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# 只保留关键模块的INFO级别输出，其他全部设为ERROR或CRITICAL
critical_loggers = [
    'EZ_VPB_Validator', 'EZ_VPB_Validator.VPBSliceGenerator',
    'EZ_VPB_Validator.DataStructureValidator', 'EZ_VPB_Validator.BloomFilterValidator',
    'EZ_VPB_Validator.proof_validator', 'EpochExtractor', 'DataStructureValidator',
    'VPBSliceGenerator', 'BloomFilterValidator', 'VPBValidator'
]

# 关闭所有详细日志
for logger_name in critical_loggers:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# 只让genesis模块保持必要的INFO输出
genesis_logger = logging.getLogger('EZ_GENESIS')
genesis_logger.setLevel(logging.WARNING)  # 降低到WARNING级别

# 当前测试模块保持INFO级别，但只输出关键信息
current_logger = logging.getLogger(__name__)
current_logger.setLevel(logging.WARNING)

# 其他可能产生大量输出的模块也设为CRITICAL
other_verbose_loggers = [
    'EZ_Tool_Box', 'SecureSignature', 'MultiTransactions', 'SingleTransaction',
    'TxPool', 'PickTx', 'AccountProofManager', 'AccountValueCollection'
]

for logger_name in other_verbose_loggers:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

import warnings
warnings.filterwarnings("ignore")


class TestBlockchainIntegrationWithRealAccount(unittest.TestCase):
    """使用真实Account节点的区块链联调测试"""

    def __init__(self, methodName='runTest'):
        super().__init__(methodName)
        # 添加日志详细度控制开关
        self.verbose_logging = os.getenv('VERBOSE_TEST_LOGGING', 'true').lower() == 'true'
        # 添加VPB可视化控制开关
        self.show_vpb_visualization = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    def setUp(self):
        """测试前准备：创建真实的测试环境和Account节点"""
        # 清理根目录下的旧测试文件
        self._cleanup_legacy_test_files()

        # 创建临时数据管理器，确保每次测试都有独立环境
        self.temp_manager = create_test_environment(
            test_name="blockchain_integration_with_real_account",
            max_sessions=3
        )
        # 使用上下文管理器方式创建会话
        self.temp_manager.cleanup_old_sessions()  # 先清理旧会话
        self.temp_manager.create_session()

        # 验证临时目录创建成功
        session_dir = self.temp_manager.get_current_session_dir()
        blockchain_dir = self.temp_manager.get_blockchain_data_dir()
        pool_db_path = self.temp_manager.get_pool_db_path()
        account_storage_dir = self.temp_manager.get_account_storage_dir()

        # 精简输出: 不再显示这些DEBUG信息
        # if self.verbose_logging:
        #     print(f"[DEBUG] 临时会话目录: {session_dir}")
        #     print(f"[DEBUG] 区块链数据目录: {blockchain_dir}")
        #     print(f"[DEBUG] 交易池数据库路径: {pool_db_path}")
        #     print(f"[DEBUG] 账户存储目录: {account_storage_dir}")

        # 配置区块链参数（快速确认用于测试）
        self.config = ChainConfig(
            confirmation_blocks=2,  # 2个区块确认
            max_fork_height=3,      # 3个区块后孤儿
            debug_mode=True,
            data_directory=self.temp_manager.get_blockchain_data_dir(),  # 使用管理的临时目录存储区块链数据
            auto_save=False  # 禁用自动保存，避免影响测试
        )

        # 创建区块链实例
        self.blockchain = Blockchain(config=self.config)

        # 创建交易池（使用管理的临时数据库）
        self.pool_db_path = self.temp_manager.get_pool_db_path()
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

        # 性能优化：创建账户地址到Account对象的映射字典，提高查找效率
        self.account_address_map = {account.address: account for account in self.accounts}

        # 不再需要创建通用VPB验证器，每个Account都有自己的VPBValidator

    def _cleanup_legacy_test_files(self):
        """清理旧的测试文件"""
        import glob
        import os

        # 需要清理的特定文件（更精确，避免误删）
        specific_files = [
            "temp_sequence_test.db",
            "temp_test_ordering.db",
            "test_vpb_storage.db",
            "ez_account_proof_storage.db",
            "ez_vpb_storage.db"
        ]

        # 需要清理的文件模式（更安全的模式）
        file_patterns = [
            "temp_*.db",
            "test_*.db",
            "ez_account_proof_*.db",      # 匹配 ez_account_proof_0x....db
            "ez_account_block_index_*.db", # 匹配 ez_account_block_index_0x....db
            "ez_account_value_collection_*.db"  # 匹配 ez_account_value_collection_0x....db
        ]

        # 获取项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ez_test_dir = os.path.join(project_root, "EZ_Test")

        cleanup_dirs = [project_root, ez_test_dir]

        try:
            for directory in cleanup_dirs:
                if not os.path.exists(directory):
                    continue

                # 清理特定文件
                for file_name in specific_files:
                    file_path = os.path.join(directory, file_name)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            logger.info(f"清理特定测试文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"清理文件失败 {file_path}: {e}")

                # 清理模式匹配的文件
                original_cwd = os.getcwd()
                try:
                    os.chdir(directory)
                    for pattern in file_patterns:
                        for file_path in glob.glob(pattern):
                            try:
                                # 额外安全检查
                                if (os.path.isfile(file_path) and
                                    not any(skip in file_path.lower() for skip in ['git', 'node_modules', '__pycache__', 'important'])):
                                    os.remove(file_path)
                                    logger.info(f"清理模式匹配文件: {os.path.join(directory, file_path)}")
                            except Exception as e:
                                logger.warning(f"清理文件失败 {file_path}: {e}")
                finally:
                    os.chdir(original_cwd)

        except Exception as e:
            logger.error(f"清理旧测试文件时出错: {e}")

    def tearDown(self):
        """测试后清理：删除临时文件"""
        print("\n" + "="*60)
        print("[TEARDOWN] 开始清理测试环境...")
        print("="*60)

        # 强制刷新输出
        import sys
        sys.stdout.flush()
        sys.stderr.flush()

        try:
            # 清理Account节点
            if hasattr(self, 'accounts'):
                print(f"[TEARDOWN] 清理 {len(self.accounts)} 个Account节点...")
                for i, account in enumerate(self.accounts):
                    try:
                        print(f"[TEARDOWN] 清理Account节点 {i+1}/{len(self.accounts)}: {account.name}")
                        account.cleanup()
                        print(f"[TEARDOWN] Account节点 {account.name} 清理完成")
                    except Exception as e:
                        print(f"[TEARDOWN] 清理Account节点 {account.name} 失败: {e}")
                        logger.error(f"清理Account节点失败: {e}")

            # 使用临时数据管理器清理当前会话
            if hasattr(self, 'temp_manager') and self.temp_manager:
                try:
                    session_dir = self.temp_manager.get_current_session_dir()
                    print(f"[TEARDOWN] 清理临时会话目录: {session_dir}")
                    self.temp_manager.cleanup_current_session()
                    print(f"[TEARDOWN] 临时会话目录清理完成")
                except Exception as e:
                    print(f"[TEARDOWN] 临时数据管理器清理失败: {e}")
                    logger.error(f"临时数据管理器清理失败: {e}")

            # 额外清理：确保根目录下的临时文件被删除
            print("[TEARDOWN] 执行额外清理...")
            self._cleanup_legacy_test_files()

            print("[TEARDOWN] 所有清理工作完成")

        except Exception as e:
            print(f"[TEARDOWN] 清理临时文件失败: {e}")
            logger.error(f"清理临时文件失败: {e}")
            import traceback
            traceback.print_exc()
            # 尝试手动清理
            try:
                if hasattr(self, 'temp_manager') and self.temp_manager:
                    print("[TEARDOWN] 尝试手动清理临时数据管理器...")
                    self.temp_manager.cleanup_current_session()
                    print("[TEARDOWN] 手动清理完成")
            except Exception as cleanup_error:
                print(f"[TEARDOWN] 手动清理也失败了: {cleanup_error}")

        finally:
            print("[TEARDOWN] tearDown方法执行完毕")
            # 强制刷新输出
            sys.stdout.flush()
            sys.stderr.flush()
            print("="*60)

    def setup_real_accounts(self):
        """创建真实的Account节点并使用项目的创世块模块初始化"""
        self.accounts = []
        account_names = ["alice", "bob", "charlie", "david"]

        print("创建Account节点... | ", end="")

        # 先创建所有Account节点
        created_accounts = []
        for i, name in enumerate(account_names):
            try:
                # 生成真实的密钥对
                private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
                # 生成符合以太坊格式的地址
                address = self._create_eth_address(f"{name}_{i}")

                # 创建真实的Account节点，使用临时目录存储数据
                account_storage_dir = self.temp_manager.get_account_storage_dir()

                account = Account(
                    address=address,
                    private_key_pem=private_key_pem,
                    public_key_pem=public_key_pem,
                    name=name,
                    data_directory=account_storage_dir
                )

                self.accounts.append(account)
                created_accounts.append(name)

            except Exception as e:
                print(f"失败: {name} - {str(e)[:20]}")
                raise RuntimeError(f"Account节点创建失败 {name}: {e}")

        print(f"{len(self.accounts)}个成功 | {', '.join(created_accounts)}")

        # 使用项目的创世块模块初始化所有账户
        self.initialize_accounts_with_project_genesis()

        print(f"[OK] 创建完成 {len(self.accounts)} 个Account节点")

    def initialize_accounts_with_project_genesis(self):
        """使用项目自带的EZ_GENESIS模块初始化所有账户"""
        print("开始创世初始化... | ", end="")

        # 创建创世块创建器，使用自定义的面额配置
        custom_denomination = [
            (1000, 1), (500, 1), (100, 5), (50, 5), (10, 5), (1, 5)
        ]

        # 创建创世块（使用新的统一API：返回区块、单个SubmitTxInfo、单个MultiTransactions、默克尔树）
        genesis_block, unified_submit_tx_info, unified_multi_txn, merkle_tree = create_genesis_block(
            accounts=self.accounts,
            denomination_config=custom_denomination,
            custom_miner="ezchain_test_genesis_miner"
        )

        # 将创世块添加到区块链
        main_chain_updated = self.blockchain.add_block(genesis_block)

        print(f"区块#{genesis_block.index} | {len(unified_multi_txn.multi_txns)}交易 | {'主链' if main_chain_updated else '分支'}")

        if not unified_submit_tx_info:
            raise RuntimeError("统一创世SubmitTxInfo无效")
        if not unified_multi_txn or not unified_multi_txn.multi_txns:
            raise RuntimeError("统一创世MultiTransactions无效")

        # 为每个账户初始化VPB
        vpb_init_results = []
        for account in self.accounts:
            # 使用重构后的创世VPB创建函数（基于统一的SubmitTxInfo + MultiTransactions）
            genesis_values, genesis_proof_units, block_index_result = create_genesis_vpb_for_account(
                account_addr=account.address,
                genesis_block=genesis_block,
                unified_submit_tx_info=unified_submit_tx_info,
                unified_multi_txn=unified_multi_txn,
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
                vpb_init_results.append(f"{account.name}({total_value})")
            else:
                raise RuntimeError(f"账户 {account.name} VPB初始化失败")

        print(f"VPB初始化: {', '.join(vpb_init_results)}")

        # 添加VPB基础检测
        self._perform_vpb_initialization_checks()

        # 可视化创世初始化后的VPB状态
        if self.show_vpb_visualization:
            print(f"\n📊 [创世初始化后] VPB状态可视化:")
            for account in self.accounts:
                account.vpb_manager.visualize_confirmed_values(f"After Genesis Initialization - {account.name}")

        # 使用新的Value摘要打印方法（受详细度控制）
        # 精简输出: 不再显示详细的Values Summary
        # if self.verbose_logging:
        #     for account in self.accounts:
        #         account.print_values_summary()

        print(f"🎉 所有账户创世初始化完成！")

    def _perform_vpb_initialization_checks(self):
        """对初始化的VPB进行基础检测"""
        print("VPB初始化检测... | ", end="")

        all_checks_passed = True
        check_results = []

        for account in self.accounts:
            try:
                # 获取账户的VPB数据
                vpb_manager = account.vpb_manager
                all_values = vpb_manager.get_all_values()

                # 检测1: Values数量与余额一致性
                account_balance = account.get_available_balance()
                values_total = sum(value.value_num for value in all_values if value.is_unspent())

                # 检测2: 每个Value都有对应的ProofUnit和BlockIndex
                missing_items = 0
                for value in all_values:
                    proof_units = vpb_manager.get_proof_units_for_value(value)
                    block_index = vpb_manager.get_block_index_for_value(value)
                    if not proof_units or not block_index:
                        missing_items += 1

                status = "✅" if account_balance == values_total and missing_items == 0 else "❌"
                check_results.append(f"{status}{account.name}")

                if account_balance != values_total or missing_items > 0:
                    all_checks_passed = False

            except Exception as e:
                check_results.append(f"💥{account.name}")
                all_checks_passed = False

        result = "全部通过" if all_checks_passed else f"发现问题"
        print(f"{' | '.join(check_results)} | {result}")

    def _create_eth_address(self, name: str) -> str:
        """创建有效的以太坊地址格式"""
        import hashlib
        hash_bytes = hashlib.sha256(name.encode()).digest()
        return f"0x{hash_bytes[:20].hex()}"

    def create_real_transaction_requests(self, num_transactions: int = None) -> List[List[Dict]]:
        """
        使用真实Account创建交易请求，按照指定逻辑：
        1）创建随机m个交易（m在4~10之间），随机选择m对发送者+接收者
        2）检查发送者的value列表（假设有n个value），确定合理的交易金额（基于value数量的1/5左右）
        3）若发送者没有value等原因造成无法生成交易，则跳过此account
        4）【修复】按sender分组，同一sender的多个交易打包到一个MultiTransactions中
        """
        # 使用字典按sender地址分组存储交易请求
        sender_transaction_groups = {}

        # 1）创建随机m个交易（m在4~10之间）
        m = random.randint(4, 10) if num_transactions is None else num_transactions

        # 随机选择m对发送者+接收者（确保发送者和接收者不同）
        sender_receiver_pairs = []
        for _ in range(m):
            # 随机选择发送者和接收者
            available_accounts = list(self.accounts)
            sender = random.choice(available_accounts)
            # 确保接收者不是发送者
            possible_recipients = [acc for acc in available_accounts if acc.address != sender.address]
            if possible_recipients:
                recipient = random.choice(possible_recipients)
                sender_receiver_pairs.append((sender, recipient))

        if not sender_receiver_pairs:
            print("   ⚠️ 无法创建发送者-接收者对")
            return []

        # 预先计算所有账户的未花费values和总余额，避免重复计算
        account_values_cache = {}
        account_balance_cache = {}
        for account in self.accounts:
            unspent_values = account.get_unspent_values()
            account_values_cache[account.address] = unspent_values
            account_balance_cache[account.address] = sum(value.value_num for value in unspent_values)

        # 为每一对创建交易请求，按sender分组
        for i, (sender_account, recipient_account) in enumerate(sender_receiver_pairs):
            try:
                # 2）检查发送者的value列表（使用缓存）
                sender_values = account_values_cache[sender_account.address]
                n = len(sender_values)

                if n == 0:
                    print(f"   ⚠️ 发送者 {sender_account.name} 没有可用value，跳过")
                    continue  # 3）若发送者没有value，跳过此account

                # 获取发送者的总余额（使用缓存）
                total_balance = account_balance_cache[sender_account.address]

                if total_balance <= 0:
                    print(f"   ⚠️ 发送者 {sender_account.name} 总余额为0，跳过")
                    continue

                # 2）基于value数量确定合理的交易金额（随机选择1个value的面值作为交易金额）
                # 这样可以确保Account的贪心算法能够精确匹配（贪心策略优先选择大额value）
                # 只选择单个value，避免子集和问题的复杂性
                selected_value = random.choice(sender_values)
                selected_total = selected_value.value_num

                # 确保交易金额合理：不超过总余额，且至少为1
                amount = max(1, min(selected_total, total_balance))

                # 生成nonce和reference
                nonce = random.randint(10000, 99999) + i * 100000
                reference = f"tx_{sender_account.name[:3]}_{recipient_account.name[:3]}_{i}"

                # 创建交易请求（保持sender字段以便后续处理）
                transaction_request = {
                    "sender": sender_account.address,  # 保留sender字段
                    "recipient": recipient_account.address,
                    "amount": amount,
                    "nonce": nonce,
                    "reference": reference
                }

                # 【关键修改】按sender地址分组，同一sender的交易放在同一个列表中
                sender_address = sender_account.address
                if sender_address not in sender_transaction_groups:
                    sender_transaction_groups[sender_address] = []
                sender_transaction_groups[sender_address].append(transaction_request)

                print(f"   💰 创建交易请求: {sender_account.name} → {recipient_account.name}, 金额: {amount} (选择1个value)")

            except Exception as e:
                print(f"   ❌ 创建交易请求失败: {sender_account.name} → {recipient_account.name}, 错误: {e}")
                continue  # 3）若无法生成交易，跳过此account

        # 4）无论最后是否真的生成了m笔交易，都将返回结果（注意，这里至少应该保障有1笔交易）
        if not sender_transaction_groups:
            print("   ⚠️ 没有成功创建任何交易，尝试强制创建一笔最小交易")
            # 强制尝试创建一笔最小交易（使用缓存）
            for sender in self.accounts:
                if account_balance_cache[sender.address] > 0:
                    for recipient in self.accounts:
                        if recipient.address != sender.address:
                            amount = 1  # 最小交易金额
                            transaction_request = {
                                "sender": sender.address,
                                "recipient": recipient.address,
                                "amount": amount,
                                "nonce": random.randint(10000, 99999),
                                "reference": f"emergency_tx_{sender.name[:3]}_{recipient.name[:3]}"
                            }
                            # 添加到分组中
                            sender_transaction_groups[sender.address] = [transaction_request]
                            print(f"   🆘 强制创建紧急交易: {sender.name} → {recipient.name}, 金额: {amount}")
                            break
                    if sender_transaction_groups:
                        break

        # 【关键修改】将分组后的交易转换为列表格式，每个sender的所有交易为一轮
        all_transaction_requests = list(sender_transaction_groups.values())

        # 打印分组统计信息
        print(f"   📊 交易分组统计: {len(all_transaction_requests)}个sender, 总计{sum(len(group) for group in all_transaction_requests)}笔交易")
        for i, group in enumerate(all_transaction_requests):
            if group:
                sender_addr = group[0].get("sender", "unknown")
                sender_account = self.get_account_by_address(sender_addr)
                sender_name = sender_account.name if sender_account else "unknown"
                print(f"      组{i+1}: {sender_name} -> {len(group)}笔交易")

        return all_transaction_requests

    def create_transactions_from_accounts(self, transaction_requests_list: List[List[Dict]]) -> List[Tuple[SubmitTxInfo, Dict, Account]]:
        """
        使用真实Account创建交易，返回SubmitTxInfo、multi_txn_result和Account的元组列表
        更新：适配新的交易请求结构，每轮包含同一sender的多个交易请求，打包到一个MultiTransactions中
        """
        submit_tx_data = []

        # 预先缓存账户查找结果，避免重复查找
        account_cache = {}
        def get_cached_account(address):
            if address not in account_cache:
                account_cache[address] = self.get_account_by_address(address)
            return account_cache[address]

        for round_num, round_requests in enumerate(transaction_requests_list):
            if not round_requests:
                continue

            # 【修改】每轮现在包含同一sender的多个交易请求
            # 获取sender地址（从第一个交易请求中获取）
            sender_address = round_requests[0].get("sender")

            if not sender_address:
                print(f"   ⚠️ 第{round_num}轮交易请求缺少sender信息，跳过")
                continue

            # 找到对应的发送账户（使用缓存）
            sender_account = get_cached_account(sender_address)
            if not sender_account:
                print(f"   ⚠️ 第{round_num}轮找不到发送账户 {sender_address}，跳过")
                continue

            try:
                # 计算本轮所有交易的总金额
                total_required_amount = sum(tx.get("amount", 0) for tx in round_requests)
                available_balance = sender_account.get_available_balance()

                if available_balance < total_required_amount:
                    print(f"   ⚠️ 发送者 {sender_account.name} 余额不足 ({available_balance} < {total_required_amount})，跳过本轮{len(round_requests)}笔交易")
                    continue

                # 【关键修改】使用Account的批量交易创建功能，一次性处理同一sender的多个交易
                multi_txn_result = sender_account.create_batch_transactions(
                    transaction_requests=round_requests,  # 传入整个交易请求列表
                    reference=f"round_{round_num}_account_{sender_account.name}"
                )

                if multi_txn_result:
                    # 创建SubmitTxInfo
                    submit_tx_info = sender_account.create_submit_tx_info(multi_txn_result)

                    if submit_tx_info:
                        # 存储元组：(SubmitTxInfo, multi_txn_result, Account)
                        submit_tx_data.append((submit_tx_info, multi_txn_result, sender_account))

                        # 打印摘要信息
                        recipient_names = []
                        for tx in round_requests:
                            recipient_account = get_cached_account(tx.get("recipient"))
                            if recipient_account:
                                recipient_names.append(recipient_account.name)
                        print(f"   ✅ Account {sender_account.name} 创建批量交易 → {', '.join(recipient_names)}, 共{len(round_requests)}笔, 总金额:{total_required_amount}")
                    else:
                        print(f"   ❌ Account {sender_account.name} 创建SubmitTxInfo失败")
                else:
                    print(f"   ❌ Account {sender_account.name} 批量创建交易失败")

            except Exception as e:
                print(f"   ❌ Account {sender_account.name} 创建批量交易异常: {e}")
                import traceback
                traceback.print_exc()
                continue

        return submit_tx_data

    def get_account_by_address(self, address: str) -> Account:
        """根据地址获取Account节点（使用字典查找优化性能）"""
        return self.account_address_map.get(address)

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
        print("="*60)
        print("[START] 完整Account交易流程测试")
        print("="*60)

        # 初始化checkpoint统计
        checkpoint_stats = {
            'total_verifications': 0,
            'checkpoint_used_count': 0,
            'checkpoint_details': []
        }

        # 步骤1：检查Account节点状态
        print("💳 检查账户初始状态 | ", end="")
        total_balance = 0
        account_status = []
        for account in self.accounts:
            account_info = account.get_account_info()
            total_balance += account_info['balances']['total']
            account_status.append(f"{account.name}:{account_info['balances']['total']}")
            self.assertGreater(account_info['balances']['total'], 0,
                              f"Account {account.name} 应该有余额")
        print(" | ".join(account_status))

        # 步骤2：创建真实交易请求
        print("📝 创建交易请求... | ", end="")
        transaction_requests_list = self.create_real_transaction_requests()
        total_requests = sum(len(requests) for requests in transaction_requests_list)
        print(f"{len(transaction_requests_list)}轮 {total_requests}笔")

        # 简明输出交易请求内容
        if self.verbose_logging:
            print("📋 交易详情:")
            for round_num, round_requests in enumerate(transaction_requests_list):
                tx_summary = []
                for req in round_requests[:5]:
                    sender_name = self.get_account_by_address(req.get("sender")).name if req.get("sender") and self.get_account_by_address(req.get("sender")) else "未知"
                    recipient_name = self.get_account_by_address(req["recipient"]).name if self.get_account_by_address(req["recipient"]) else "未知"
                    tx_summary.append(f"{sender_name}→{recipient_name}:{req['amount']}")
                print(f"  轮{round_num+1}: {', '.join(tx_summary)}{'...' if len(round_requests) > 5 else ''}")

        # 步骤3：使用真实Account创建交易
        print("⚡ 创建交易 | ", end="")
        submit_tx_data = self.create_transactions_from_accounts(transaction_requests_list)
        print(f"{len(submit_tx_data)}个交易包")
        self.assertGreater(len(submit_tx_data), 0, "应该创建成功一些交易")

        # 步骤4：使用Account的正确方法将交易提交到交易池并存储到本地
        print("📥 提交交易到池... | ", end="")
        added_count = 0
        submit_tx_infos = []
        successful_accounts = []

        for submit_tx_info, multi_txn_result, account in submit_tx_data:
            try:
                success = account.submit_tx_infos_to_pool(
                    submit_tx_info=submit_tx_info,
                    tx_pool=self.transaction_pool,
                    multi_txn_result=multi_txn_result
                )
                if success:
                    added_count += 1
                    submit_tx_infos.append(submit_tx_info)
                    successful_accounts.append(account.name)
            except Exception as e:
                continue

        print(f"{added_count}/{len(submit_tx_data)} 成功 | {', '.join(successful_accounts)}")
        self.assertGreater(added_count, 0, "至少应该提交成功一些交易到交易池")

        # 步骤5：从交易池选择交易并打包
        print("⛏️  打包区块 | ", end="")
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
                print(f"区块#{block.index} | {len(package_data.selected_submit_tx_infos)}交易 | {len(picked_txs_mt_proofs)}证明 | {len(sender_addrs)}发送者")
                if self.verbose_logging:
                    print(f"  默克尔根: {package_data.merkle_root[:16]}...")
            else:
                print(f"空区块 #{block.index}")

        except Exception as e:
            logger.error(f"交易打包失败: {e}")
            raise RuntimeError(f"从交易池打包交易失败: {e}")

        # 步骤6：将区块添加到区块链
        print("🔗 添加区块... | ", end="")
        main_chain_updated = self.blockchain.add_block(block)
        self.assertTrue(main_chain_updated)

        fork_node = self.blockchain.get_fork_node_by_hash(block.get_hash())
        block_status = fork_node.consensus_status if fork_node else ConsensusStatus.PENDING
        print(f"{'主链' if main_chain_updated else '分支'} | 状态: {block_status.value}")

        # 步骤6.1：收集参与交易的账户地址
        print("📦 收集参与地址... | ", end="")
        participant_addresses = []
        for submit_tx_info in package_data.selected_submit_tx_infos:
            participant_addresses.append(submit_tx_info.submitter_address)
            sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
            if sender_account:
                multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
                if multi_txns and hasattr(multi_txns, 'single_txns'):
                    for txn in multi_txns.single_txns:
                        if hasattr(txn, 'recipient'):
                            participant_addresses.append(txn.recipient)

        participant_addresses = list(set(participant_addresses))
        print(f"{len(participant_addresses)}个地址")

        # 可视化发送者VPB更新后的状态
        if self.show_vpb_visualization:
            print(f"\n📊 [6.1步骤后] VPB状态可视化:")
            for account in self.accounts:
                account.vpb_manager.visualize_confirmed_values(f"After Senders Update - {account.name}")

        # 步骤6.2：发送者本地化处理VPB
        print("🔄 发送者VPB更新...")

        # 【调试】记录发送者VPB更新前的状态
        print("\n   📊 [6.2更新前] 各账户状态:")
        for account in self.accounts:
            unspent_values = account.get_unspent_values()
            confirmed_values = account.get_values(ValueState.CONFIRMED)
            unspent_total = sum(v.value_num for v in unspent_values)
            confirmed_total = sum(v.value_num for v in confirmed_values)
            print(f"      {account.name}: UNSPENT={unspent_total} ({len(unspent_values)}个), CONFIRMED={confirmed_total} ({len(confirmed_values)}个)")

        print("   | 开始更新... | ", end="")
        vpb_update_count = 0
        if package_data.selected_submit_tx_infos:
            try:
                processed_senders = []
                for submit_tx_info in package_data.selected_submit_tx_infos:
                    sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
                    if not sender_account:
                        continue

                    sender_merkle_proof = self.get_merkle_proof_for_sender(
                        submit_tx_info.submitter_address,
                        picked_txs_mt_proofs,
                        package_data
                    )

                    multi_txns_hash = submit_tx_info.multi_transactions_hash
                    multi_txns = sender_account.get_submitted_transaction(multi_txns_hash)

                    if multi_txns:
                        total_values = sum(len(txn.value) for txn in multi_txns.multi_txns
                                         if hasattr(txn, 'value') and txn.value)

                        if total_values > 0:
                            primary_recipient = next((txn.recipient for txn in multi_txns.multi_txns
                                                   if hasattr(txn, 'recipient') and txn.recipient), "unknown")

                            success = sender_account.update_vpb_after_transaction_sent(
                                confirmed_multi_txns=multi_txns,
                                mt_proof=sender_merkle_proof,
                                block_height=block.index,
                                recipient_address=primary_recipient
                            )

                            if success:
                                vpb_update_count += 1
                                processed_senders.append(sender_account.name)

                print(f"{vpb_update_count}/{len(package_data.selected_submit_tx_infos)} 成功 | {', '.join(processed_senders)}")

                # 【调试】记录发送者VPB更新后的状态
                print("\n   📊 [6.2更新后] 各账户状态:")
                for account in self.accounts:
                    unspent_values = account.get_unspent_values()
                    confirmed_values = account.get_values(ValueState.CONFIRMED)
                    unspent_total = sum(v.value_num for v in unspent_values)
                    confirmed_total = sum(v.value_num for v in confirmed_values)
                    total_values = unspent_total + confirmed_total
                    print(f"      {account.name}: UNSPENT={unspent_total} ({len(unspent_values)}个), CONFIRMED={confirmed_total} ({len(confirmed_values)}个), TOTAL={total_values}")

                # 可视化发送者VPB更新后的状态
                if self.show_vpb_visualization:
                    print(f"\n📊 [6.2步骤后-发送者VPB更新] VPB状态可视化:")
                    for account in self.accounts:
                        # 只显示参与了交易的发送者
                        participated = any(submit_tx_info.submitter_address == account.address for submit_tx_info in package_data.selected_submit_tx_infos)
                        if participated:
                            account.vpb_manager.visualize_confirmed_values(f"After Senders Update - {account.name}")
            except Exception as e:
                print(f"   ❌ 发送者VPB本地化处理异常: {e}")
                import traceback
                traceback.print_exc()

        # 步骤6.3：接收者同步处理
        print("📤 接收者VPB处理...")

        # 【调试】记录接收者VPB处理前的状态
        print("\n   📊 [6.3处理前] 各账户状态:")
        for account in self.accounts:
            unspent_values = account.get_unspent_values()
            confirmed_values = account.get_values(ValueState.CONFIRMED)
            unspent_total = sum(v.value_num for v in unspent_values)
            confirmed_total = sum(v.value_num for v in confirmed_values)
            total_values = unspent_total + confirmed_total
            print(f"      {account.name}: UNSPENT={unspent_total} ({len(unspent_values)}个), CONFIRMED={confirmed_total} ({len(confirmed_values)}个), TOTAL={total_values}")

        # 静默验证器日志
        import logging
        logging.getLogger().setLevel(logging.CRITICAL)
        for logger_name in ['EZ_VPB_Validator', 'EZ_VPB_Validator.VPBSliceGenerator',
                           'EZ_VPB_Validator.DataStructureValidator', 'EZ_VPB_Validator.BloomFilterValidator',
                           'EZ_VPB_Validator.proof_validator', 'EpochExtractor', 'DataStructureValidator',
                           'VPBSliceGenerator', 'BloomFilterValidator', 'VPBValidator']:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)

        recipients_processed = 0
        vpb_verification_success = 0
        vpb_receive_success = 0

        if package_data.selected_submit_tx_infos:
            try:
                sender_to_recipients_data = {}

                for submit_tx_info in package_data.selected_submit_tx_infos:
                    sender_account = self.get_account_by_address(submit_tx_info.submitter_address)
                    if not sender_account:
                        continue

                    multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
                    if not multi_txns or not hasattr(multi_txns, 'multi_txns'):
                        continue

                    if sender_account.address not in sender_to_recipients_data:
                        sender_to_recipients_data[sender_account.address] = []

                    for txn in multi_txns.multi_txns:
                        recipient_address = getattr(txn, 'recipient', None)
                        if not recipient_address:
                            continue

                        recipient_account = self.get_account_by_address(recipient_address)
                        if not recipient_account:
                            continue

                        # 遍历交易中的所有value，为每个value都进行VPB检查
                        if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                            if self.verbose_logging and len(txn.value) > 1:
                                print(f"   💡 处理交易到 {recipient_account.name}: 发现 {len(txn.value)} 个value，将逐个进行VPB检查")

                            for single_value in txn.value:
                                transferred_value = copy.deepcopy(single_value)
                                received_proof_units = copy.deepcopy(sender_account.vpb_manager.get_proof_units_for_value(transferred_value))
                                received_block_index = copy.deepcopy(sender_account.vpb_manager.get_block_index_for_value(transferred_value))

                                if received_proof_units and received_block_index:
                                    recipient_data = {
                                        'recipient_account': recipient_account,
                                        'recipient_address': recipient_address,
                                        'received_value': transferred_value,
                                        'received_proof_units': received_proof_units,
                                        'received_block_index': received_block_index
                                    }
                                    sender_to_recipients_data[sender_account.address].append(recipient_data)
                                    recipients_processed += 1

                # 为每个接收者进行VPB验证和接收
                for sender_address, recipients_data in sender_to_recipients_data.items():
                    sender_account = self.get_account_by_address(sender_address)
                    if not sender_account:
                        continue

                    for data in recipients_data:
                        recipient_account = data['recipient_account']
                        received_value = data['received_value']
                        received_proof_units = data['received_proof_units']
                        received_block_index = data['received_block_index']

                        try:
                            # VPB验证
                            from EZ_VPB_Validator.core.types import MainChainInfo
                            merkle_roots = {}
                            bloom_filters = {}

                            if received_block_index and hasattr(received_block_index, 'index_lst'):
                                for block_height in received_block_index.index_lst:
                                    if block_height == 0:
                                        genesis_block = self.blockchain.get_block_by_index(0)
                                        if genesis_block:
                                            merkle_roots[block_height] = genesis_block.get_m_tree_root()
                                            bloom_filters[block_height] = genesis_block.get_bloom()
                                    else:
                                        block_node = self.blockchain.get_fork_node_by_index(block_height)
                                        if block_node and block_node.block:
                                            merkle_roots[block_height] = block_node.block.get_m_tree_root()
                                            bloom_filters[block_height] = block_node.block.get_bloom()

                            main_chain_info = MainChainInfo(
                                merkle_roots=merkle_roots,
                                bloom_filters=bloom_filters,
                                current_block_height=self.blockchain.get_latest_block_index(),
                                genesis_block_height=0
                            )

                            verification_report = recipient_account.verify_vpb(
                                value=copy.deepcopy(received_value),
                                proof_units=copy.deepcopy(received_proof_units),
                                block_index_list=copy.deepcopy(received_block_index),
                                main_chain_info=main_chain_info
                            )

                            # 检查是否使用了checkpoint
                            checkpoint_stats['total_verifications'] += 1
                            if verification_report.checkpoint_used:
                                checkpoint = verification_report.checkpoint_used
                                checkpoint_stats['checkpoint_used_count'] += 1
                                value_info = f"{checkpoint.value_begin_index[:10]}...({checkpoint.value_num})"
                                print(f"   ⚡ Checkpoint: {recipient_account.name} @高度{checkpoint.block_height} | {value_info}")

                                # 记录checkpoint详情
                                checkpoint_stats['checkpoint_details'].append({
                                    'account': recipient_account.name,
                                    'block_height': checkpoint.block_height,
                                    'value_info': value_info
                                })

                            if verification_report.is_valid:
                                vpb_verification_success += 1
                                receive_success = recipient_account.receive_vpb_from_others(
                                    received_value=copy.deepcopy(received_value),
                                    received_proof_units=copy.deepcopy(received_proof_units),
                                    received_block_index=copy.deepcopy(received_block_index)
                                )
                                if receive_success:
                                    vpb_receive_success += 1

                        except Exception as e:
                            if self.verbose_logging:
                                print(f"处理 {recipient_account.name} VPB异常: {str(e)[:30]}")

                print(f"总计value:{recipients_processed} | 验证成功:{vpb_verification_success} | 接收成功:{vpb_receive_success}")

                # 【调试】记录接收者VPB处理后的状态
                print("\n   📊 [6.3处理后] 各账户状态:")
                for account in self.accounts:
                    unspent_values = account.get_unspent_values()
                    confirmed_values = account.get_values(ValueState.CONFIRMED)
                    unspent_total = sum(v.value_num for v in unspent_values)
                    confirmed_total = sum(v.value_num for v in confirmed_values)
                    total_values = unspent_total + confirmed_total
                    print(f"      {account.name}: UNSPENT={unspent_total} ({len(unspent_values)}个), CONFIRMED={confirmed_total} ({len(confirmed_values)}个), TOTAL={total_values}")

                # 可视化接收者VPB更新后的状态
                if self.show_vpb_visualization:
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
                            account.vpb_manager.visualize_confirmed_values(f"After Receivers Update - {account.name}")

            except Exception as e:
                print(f"   ❌ 接收者处理异常: {e}")
                import traceback
                traceback.print_exc()

        # 步骤7：验证Account节点状态
        print("🔍 验证最终状态... | ", end="")
        final_total_balance = 0
        account_final_status = []
        for account in self.accounts:
            account_info = account.get_account_info()
            final_total_balance += account_info['balances']['total']

            # 精简输出: 不再显示详细的Values Summary
            # if self.verbose_logging:
            #     account.print_values_summary()

            integrity_valid = account.validate_integrity()
            status_icon = "✅" if integrity_valid else "❌"
            account_final_status.append(f"{status_icon}{account.name}:{account_info['balances']['total']}")

            self.assertTrue(integrity_valid, f"Account {account.name} 完整性验证失败")

        balance_change = final_total_balance - total_balance
        fee_rate = (abs(balance_change) / total_balance * 100) if total_balance > 0 else 0

        print(f"{' | '.join(account_final_status)} | 余额变化:{total_balance}→{final_total_balance} ({fee_rate:.1f}%)")

        # 输出checkpoint统计
        if checkpoint_stats['total_verifications'] > 0:
            checkpoint_rate = (checkpoint_stats['checkpoint_used_count'] / checkpoint_stats['total_verifications'] * 100)
            print(f"⚡ Checkpoint统计: {checkpoint_stats['checkpoint_used_count']}/{checkpoint_stats['total_verifications']} 次验证使用checkpoint ({checkpoint_rate:.1f}%)")
            if checkpoint_stats['checkpoint_used_count'] > 0 and self.verbose_logging:
                print(f"   详情:")
                for detail in checkpoint_stats['checkpoint_details']:
                    print(f"   - {detail['account']} @高度{detail['block_height']} | {detail['value_info']}")

        print("="*60)
        print("🎉 真实Account完整交易流程测试通过！")
        print("="*60)

        # 返回checkpoint统计信息供多轮测试使用
        return checkpoint_stats


def run_real_account_integration_tests():
    """运行所有真实Account集成测试"""
    print("=" * 60)
    print("🚀 EZchain Account集成测试 - 精简版")
    print("=" * 60)

    # 显示当前日志设置
    verbose_logging = os.getenv('VERBOSE_TEST_LOGGING', 'false').lower() == 'true'
    show_vpb_visualization = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    print(f"📝 日志: 详细={verbose_logging} | VPB可视化={show_vpb_visualization}")
    if not verbose_logging and not show_vpb_visualization:
        print("🎯 简洁模式")
    else:
        print("📊 详细模式")
    print("-" * 60)

    # 创建测试套件
    suite = unittest.TestSuite()
    suite.addTest(TestBlockchainIntegrationWithRealAccount('test_complete_real_account_transaction_flow'))

    # 运行测试 - 使用较低冗余度
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    # 输出精简测试结果摘要
    print("\n" + "=" * 60)
    print("📊 测试结果摘要")
    print("=" * 60)

    success_count = result.testsRun - len(result.failures) - len(result.errors)
    success_rate = (success_count / result.testsRun * 100) if result.testsRun > 0 else 0

    print(f"运行:{result.testsRun} | 成功:{success_count} | 失败:{len(result.failures)} | 错误:{len(result.errors)} | 成功率:{success_rate:.1f}%")

    if result.failures:
        print(f"❌ 失败: {', '.join(str(test) for test, _ in result.failures)}")
    if result.errors:
        print(f"💥 错误: {', '.join(str(test) for test, _ in result.errors)}")

    print("=" * 60)
    if success_rate >= 100:
        print("🎉 测试全部通过！系统运行正常")
    elif success_rate >= 80:
        print("✅ 测试基本通过，部分功能正常")
    else:
        print("⚠️ 测试存在问题，需要进一步调试")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    import os

    # 设置编码以支持中文字符和emoji
    try:
        if sys.platform == "win32":
            # Windows下设置UTF-8编码
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            # 在Windows下设置环境变量以支持UTF-8
            os.environ['PYTHONIOENCODING'] = 'utf-8'
    except:
        pass

    success = run_real_account_integration_tests()
    sys.exit(0 if success else 1)