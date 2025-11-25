"""
集成测试

修复版本：解决empty range for randrange()错误
主要修复：
1. 增加初始账户余额以减少value分裂问题
2. 修改交易金额生成逻辑，从预设面额中选择
3. 增加余额检查避免randrange错误
"""

import sys
import os
import time
import tempfile
import shutil
import random
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
while project_root and os.path.basename(project_root) != 'real_EZchain':
    parent = os.path.dirname(project_root)
    if parent == project_root:  # 防止无限循环
        break
    project_root = parent
sys.path.insert(0, project_root)

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.MultiTransactions import MultiTransactions
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib

# 导入区块链节点
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.BlockchainNode import BlockchainNode

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class IntegrationTestResult:
    """集成测试结果"""
    total_accounts: int = 0
    successful_accounts: int = 0
    total_transactions: int = 0
    successful_transactions: int = 0
    total_operations: int = 0
    errors: List[str] = None
    start_time: float = 0
    end_time: float = 0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def success_rate(self) -> float:
        """总体成功率"""
        return (self.successful_transactions / max(self.total_transactions, 1)) * 100

    @property
    def duration(self) -> float:
        """测试耗时"""
        return self.end_time - self.start_time


class IntegrationTest:
    """集成测试类"""

    def __init__(self, temp_dir: Optional[str] = None, cleanup: bool = True):
        """
        初始化集成测试

        Args:
            temp_dir: 临时目录
            cleanup: 是否清理临时文件
        """
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="ezchain_integration_test_")
        self.cleanup = cleanup
        self.accounts: List[Account] = []
        self.result = IntegrationTestResult()

        # 预设的交易面额，避免value分裂
        self.transaction_denominations = [1, 5, 10, 50, 100]

        # 初始化区块链节点
        self.blockchain_node = BlockchainNode(node_id="test_node", mining_difficulty=1)
        logger.info("区块链节点初始化完成")

    def generate_key_pair(self):
        """生成密钥对"""
        private_key = ec.generate_private_key(ec.SECP256K1(), default_backend())
        public_key = private_key.public_key()

        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_key_pem, public_key_pem

    def create_account(self, name: str, balance: int = 5000) -> Optional[Account]:
        """创建账户并分配定额面额的value"""
        try:
            private_key_pem, public_key_pem = self.generate_key_pair()
            address = f"{name}_{hashlib.sha256(public_key_pem).hexdigest()[:16]}"

            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=name
            )

            # 定额面额分配方案
            # 100块50个 = 5000, 50块50个 = 2500, 10块50个 = 500, 5块50个 = 250, 1块50个 = 50
            # 总计: 8300元
            denomination_config = [
                (100, 50),   # 100块50个
                (50, 50),    # 50块50个
                (10, 50),    # 10块50个
                (5, 50),     # 5块50个
                (1, 50)      # 1块50个
            ]

            total_balance = 0
            first_value = True

            # 创建所有定额面额value
            for amount, count in denomination_config:
                for i in range(count):
                    value = Value(f"0x{1000 + total_balance:04x}", amount, ValueState.UNSPENT)
                    block_index = BlockIndexList([0], owner=address)

                    if first_value:
                        # 第一个value作为创世value
                        if not account.initialize_from_genesis(value, [], block_index):
                            logger.error(f"账户 {name} 创世初始化失败")
                            return None
                        first_value = False
                    else:
                        # 直接通过ValueCollection添加value
                        if not account.vpb_manager.value_collection.add_value(value):
                            logger.error(f"账户 {name} 添加value {amount} 失败")
                            return None

                        # 获取新添加value的node_id
                        node_id = account.vpb_manager._get_node_id_for_value(value)
                        if not node_id:
                            logger.error(f"无法获取新value的node_id")
                            return None

                        # 手动建立映射关系
                        account.vpb_manager._node_id_to_value_id[node_id] = value.begin_index

                        # 添加block_index映射
                        account.vpb_manager._block_indices[node_id] = block_index

                        # 添加到proof_manager
                        if not account.vpb_manager.proof_manager.add_value(value):
                            logger.warning(f"添加value到proof_manager失败，但继续执行")

                    total_balance += amount

            logger.info(f"创建账户: {name} (地址: {address}, 余额: {total_balance})")
            logger.info(f"面额分配: 100x{denomination_config[0][1]}, 50x{denomination_config[1][1]}, "
                       f"10x{denomination_config[2][1]}, 5x{denomination_config[3][1]}, 1x{denomination_config[4][1]}")

            # 注册账户到区块链节点
            if self.blockchain_node.register_account(account):
                logger.info(f"账户 {name} 已注册到区块链节点")
            else:
                logger.error(f"账户 {name} 注册到区块链节点失败")
                return None

            self.accounts.append(account)
            self.result.successful_accounts += 1
            return account

        except Exception as e:
            logger.error(f"创建账户 {name} 失败: {e}")
            self.result.errors.append(f"创建账户 {name} 失败: {e}")
            return None

    def get_available_balance(self, account: Account) -> int:
        """获取可用余额（修复版本）"""
        try:
            return account.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)
        except Exception as e:
            logger.error(f"查询账户 {account.name} 余额失败: {e}")
            return 0

    def generate_transaction_amount(self, sender_balance: int) -> Optional[int]:
        """
        生成交易金额，从预设面额中选择，避免value分裂

        Args:
            sender_balance: 发送方余额

        Returns:
            交易金额，如果无法生成则返回None
        """
        # 从预设面额中选择合适的金额
        valid_amounts = [amount for amount in self.transaction_denominations
                        if amount <= sender_balance]

        if not valid_amounts:
            return None

        return random.choice(valid_amounts)

    def create_transaction(self, sender: Account, recipient: Account, amount: int) -> bool:
        """创建交易并提交到区块链节点"""
        try:
            sender_balance = self.get_available_balance(sender)
            if sender_balance < amount:
                logger.warning(f"发送方 {sender.name} 余额不足: {sender_balance} < {amount}")
                return False

            transaction_requests = [
                {
                    'recipient': recipient.address,
                    'amount': amount
                }
            ]

            multi_txn_result = sender.create_batch_transactions(
                transaction_requests,
                reference=f"{sender.name}_to_{recipient.name}_{int(time.time())}"
            )

            if multi_txn_result:
                multi_txn = multi_txn_result["multi_transactions"]
                selected_values = multi_txn_result.get("selected_values", [])
                change_values = multi_txn_result.get("change_values", [])

                # 提交交易到区块链节点
                success = self.blockchain_node.submit_transaction(
                    multi_transactions=multi_txn,
                    selected_values=selected_values,
                    change_values=change_values,
                    sender_address=sender.address
                )

                if success:
                    logger.info(f"交易已提交到区块链节点: {sender.name} -> {recipient.name}, 金额: {amount}")
                    logger.debug(f"交易哈希: {getattr(multi_txn, 'digest', 'N/A')}")

                    self.result.successful_transactions += 1
                    return True
                else:
                    logger.error(f"交易提交到区块链节点失败: {sender.name} -> {recipient.name}")
                    return False
            else:
                logger.error(f"交易创建失败: {sender.name} -> {recipient.name}")
                return False

        except Exception as e:
            error_msg = f"创建交易失败: {e}"
            logger.error(error_msg)
            self.result.errors.append(error_msg)
            return False

    def run_integration_test(self, num_accounts: int = 3, num_transactions: int = 5) -> IntegrationTestResult:
        """
        运行集成测试

        Args:
            num_accounts: 账户数量
            num_transactions: 交易数量

        Returns:
            测试结果
        """
        logger.info("开始集成测试")
        logger.info(f"临时目录: {self.temp_dir}")

        self.result.start_time = time.time()
        self.result.total_accounts = num_accounts

        try:
            # 1. 创建账户
            logger.info(f"步骤 1: 创建 {num_accounts} 个账户")
            for i in range(num_accounts):
                name = f"User_{chr(65 + i)}"
                self.create_account(name, 5000)  # 增加到5000余额

            if len(self.accounts) < 2:
                raise Exception("需要至少2个账户才能进行测试")

            # 2. 账户操作测试
            logger.info("步骤 2: 账户操作测试")
            for account in self.accounts:
                balance = self.get_available_balance(account)
                total_balance = account.get_total_balance()
                logger.info(f"账户 {account.name}: 可用={balance}, 总额={total_balance}")

                # 测试VPB完整性
                vpb_valid = account.validate_vpb_integrity()
                logger.info(f"账户 {account.name} VPB完整性: {'通过' if vpb_valid else '失败'}")

                self.result.total_operations += 2

            # 3. 交易测试
            logger.info(f"步骤 3: 创建 {num_transactions} 笔交易")
            self.result.total_transactions = num_transactions

            for i in range(num_transactions):
                if len(self.accounts) >= 2:
                    # 随机选择发送方和接收方
                    sender_idx = random.randint(0, len(self.accounts) - 1)
                    recipient_idx = (sender_idx + 1) % len(self.accounts)

                    sender = self.accounts[sender_idx]
                    recipient = self.accounts[recipient_idx]

                    # 使用改进的金额生成方法
                    amount = self.generate_transaction_amount(self.get_available_balance(sender))

                    if amount is None:
                        logger.warning(f"跳过交易: {sender.name} 余额不足或无可用面额")
                        continue

                    self.create_transaction(sender, recipient, amount)
                    self.result.total_operations += 1

            # 4. 等待区块链处理和VPB更新
            logger.info("步骤 4: 等待区块链处理和VPB更新")
            time.sleep(10)  # 等待挖矿和VPB更新

            # 显示区块链信息
            chain_info = self.blockchain_node.get_chain_info()
            logger.info(f"区块链状态: {chain_info}")

            # 5. 最终状态检查
            logger.info("步骤 5: 最终状态检查")
            for account in self.accounts:
                balance = self.get_available_balance(account)
                account_info = account.get_account_info()
                chain_balance = self.blockchain_node.get_account_balance(account.address)
                logger.info(f"账户 {account.name} 最终状态:")
                logger.info(f"  本地余额: {balance}")
                logger.info(f"  链上余额: {chain_balance}")
                logger.info(f"  Value数: {len(account.get_values())}")
                logger.info(f"  VPB统计: {account_info['vpb_summary']}")

        except Exception as e:
            error_msg = f"集成测试执行失败: {e}"
            logger.error(error_msg)
            self.result.errors.append(error_msg)

        finally:
            self.result.end_time = time.time()
            self._print_results()
            if self.cleanup:
                self._cleanup()

        return self.result

    def _print_results(self):
        """打印测试结果"""
        logger.info("=" * 50)
        logger.info("集成测试结果")
        logger.info("=" * 50)
        logger.info(f"测试耗时: {self.result.duration:.2f} 秒")
        logger.info(f"账户创建: {self.result.successful_accounts}/{self.result.total_accounts}")
        logger.info(f"交易创建: {self.result.successful_transactions}/{self.result.total_transactions}")
        logger.info(f"总体操作: {self.result.total_operations}")
        logger.info(f"成功率: {self.result.success_rate:.1f}%")

        if self.result.errors:
            logger.warning(f"错误数量: {len(self.result.errors)}")
            for i, error in enumerate(self.result.errors, 1):
                logger.warning(f"  {i}. {error}")

    def _cleanup(self):
        """清理测试环境"""
        try:
            # 关闭区块链节点
            if hasattr(self, 'blockchain_node'):
                self.blockchain_node.shutdown()
                logger.info("区块链节点已关闭")

            for account in self.accounts:
                if hasattr(account, 'cleanup'):
                    account.cleanup()

            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理失败: {e}")


# 便捷函数
def run_integration_test(num_accounts: int = 3, num_transactions: int = 5) -> IntegrationTestResult:
    """运行集成测试的便捷函数"""
    test = IntegrationTest()
    return test.run_integration_test(num_accounts, num_transactions)


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行测试
    result = run_integration_test()

    # 根据结果设置退出码
    if (result.success_rate >= 80 and len(result.errors) == 0):
        print("集成测试通过!")
        exit(0)
    else:
        print("集成测试失败!")
        exit(1)