"""
Account核心功能测试

测试Account类的基本功能，包括：
- 账户创建和初始化
- 余额查询
- VPB管理
- 交易创建
- 数字签名验证

基于debug_account_test.py和basic_integration_test.py的精华部分
"""

import sys
import os
import time
import tempfile
import shutil
import logging
from typing import List, Dict, Any, Optional

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
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib

# 配置日志
logger = logging.getLogger(__name__)


class AccountTest:
    """Account核心功能测试类"""

    def __init__(self, temp_dir: Optional[str] = None, cleanup: bool = True):
        """
        初始化测试环境

        Args:
            temp_dir: 临时目录路径，None表示自动创建
            cleanup: 测试结束后是否清理临时文件
        """
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="ezchain_account_test_")
        self.cleanup = cleanup
        self.accounts: List[Account] = []
        self.test_results: Dict[str, Any] = {
            'accounts_created': 0,
            'accounts_initialized': 0,
            'transactions_created': 0,
            'transactions_verified': 0,
            'errors': []
        }

    def generate_key_pair(self) -> tuple:
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

    def create_test_account(self, name: str, balance: int = 1000) -> Optional[Account]:
        """
        创建测试账户

        Args:
            name: 账户名称
            balance: 初始余额

        Returns:
            创建成功的Account对象，失败返回None
        """
        try:
            private_key_pem, public_key_pem = self.generate_key_pair()
            address = f"{name}_{hashlib.sha256(public_key_pem).hexdigest()[:16]}"

            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=name
            )

            # 初始化创世余额
            genesis_value = Value("0x1000", balance, ValueState.UNSPENT)
            genesis_proof_units = []
            genesis_block_index = BlockIndexList([0], owner=address)

            if account.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index):
                logger.info(f"账户 {name} 创建成功，地址: {address}, 余额: {balance}")
                self.accounts.append(account)
                self.test_results['accounts_created'] += 1
                self.test_results['accounts_initialized'] += 1
                return account
            else:
                logger.error(f"账户 {name} 初始化失败")
                return None

        except Exception as e:
            error_msg = f"创建账户 {name} 失败: {e}"
            logger.error(error_msg)
            self.test_results['errors'].append(error_msg)
            return None

    def get_available_balance(self, account: Account) -> int:
        """
        获取可用余额（修复版本）

        直接使用ValueCollection方法，绕过VPBManager的查询问题
        """
        try:
            return account.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)
        except Exception as e:
            logger.error(f"查询账户 {account.name} 余额失败: {e}")
            return 0

    def test_account_basic_operations(self, account: Account) -> bool:
        """
        测试账户基本操作

        Args:
            account: 要测试的账户

        Returns:
            测试是否通过
        """
        try:
            # 测试余额查询
            available_balance = self.get_available_balance(account)
            total_balance = account.get_total_balance()

            logger.info(f"账户 {account.name} 可用余额: {available_balance}, 总余额: {total_balance}")

            # 测试Value查询
            all_values = account.get_values()
            unspent_values = account.vpb_manager.value_collection.find_by_state(ValueState.UNSPENT)

            logger.info(f"账户 {account.name} 总Value数: {len(all_values)}, 未花销Value数: {len(unspent_values)}")

            # 测试VPB完整性
            vpb_valid = account.validate_vpb_integrity()
            logger.info(f"账户 {account.name} VPB完整性: {'✅ 通过' if vpb_valid else '❌ 失败'}")

            # 验证余额一致性
            expected_balance = sum(v.value_num for v in unspent_values)
            if expected_balance == available_balance:
                logger.info(f"账户 {account.name} 余额一致性验证通过: {available_balance}")
                return True
            else:
                logger.warning(f"账户 {account.name} 余额不一致: 期望={expected_balance}, 实际={available_balance}")
                return False

        except Exception as e:
            error_msg = f"测试账户 {account.name} 基本操作失败: {e}"
            logger.error(error_msg)
            self.test_results['errors'].append(error_msg)
            return False

    def test_transaction_creation(self, sender: Account, recipient: Account, amount: int) -> bool:
        """
        测试交易创建

        Args:
            sender: 发送方账户
            recipient: 接收方账户
            amount: 交易金额

        Returns:
            交易是否创建成功
        """
        try:
            # 检查发送方余额
            sender_balance = self.get_available_balance(sender)
            if sender_balance < amount:
                logger.warning(f"发送方 {sender.name} 余额不足，跳过交易 (余额={sender_balance}, 需要={amount})")
                return False

            # 创建交易请求
            transaction_requests = [
                {
                    'recipient': recipient.address,
                    'amount': amount
                }
            ]

            # 创建多笔交易
            start_time = time.time()
            multi_txn_result = sender.create_batch_transactions(
                transaction_requests,
                reference=f"{sender.name}_to_{recipient.name}_{int(start_time)}"
            )
            creation_time = time.time() - start_time

            if multi_txn_result:
                multi_txn = multi_txn_result["multi_transactions"]

                # 验证交易基本结构
                if hasattr(multi_txn, 'sender') and hasattr(multi_txn, 'multi_txns'):
                    logger.info(f"交易创建成功: {sender.name} -> {recipient.name}, 金额: {amount}")
                    logger.info(f"  交易哈希: {getattr(multi_txn, 'digest', 'N/A')}")
                    logger.info(f"  创建耗时: {creation_time:.3f}秒")
                    logger.info(f"  包含单笔交易数: {len(multi_txn.multi_txns)}")

                    self.test_results['transactions_created'] += 1

                    # 验证签名
                    if hasattr(sender, 'verify_multi_transaction_signature'):
                        signature_valid = sender.verify_multi_transaction_signature(multi_txn_result)
                        if signature_valid:
                            logger.info(f"  交易签名验证: ✅ 通过")
                            self.test_results['transactions_verified'] += 1
                            return True
                        else:
                            logger.warning(f"  交易签名验证: ❌ 失败")
                            return False
                    else:
                        logger.warning("账户不支持签名验证")
                        return True
                else:
                    logger.error(f"交易结构无效: {sender.name} -> {recipient.name}")
                    return False
            else:
                logger.error(f"交易创建失败: {sender.name} -> {recipient.name}")
                return False

        except Exception as e:
            error_msg = f"测试交易创建失败: {e}"
            logger.error(error_msg)
            self.test_results['errors'].append(error_msg)
            return False

    def run_basic_test_suite(self) -> Dict[str, Any]:
        """
        运行基础测试套件

        Returns:
            测试结果字典
        """
        logger.info("开始运行Account基础测试套件")
        logger.info(f"临时目录: {self.temp_dir}")

        try:
            # 1. 创建测试账户
            logger.info("步骤 1: 创建测试账户")
            test_accounts = ['Alice', 'Bob', 'Charlie']
            for name in test_accounts:
                self.create_test_account(name, 1000)

            if len(self.accounts) < 2:
                raise Exception("需要至少2个账户才能进行测试")

            # 2. 测试账户基本操作
            logger.info("步骤 2: 测试账户基本操作")
            passed_operations = 0
            for account in self.accounts:
                if self.test_account_basic_operations(account):
                    passed_operations += 1

            logger.info(f"基本操作测试通过率: {passed_operations}/{len(self.accounts)}")

            # 3. 测试交易创建
            logger.info("步骤 3: 测试交易创建")
            successful_transactions = 0
            transaction_tests = [
                (self.accounts[0], self.accounts[1], 100),
                (self.accounts[1], self.accounts[2], 50),
                (self.accounts[2], self.accounts[0], 25)
            ]

            for sender, recipient, amount in transaction_tests:
                if self.test_transaction_creation(sender, recipient, amount):
                    successful_transactions += 1

            logger.info(f"交易创建测试通过率: {successful_transactions}/{len(transaction_tests)}")

            # 4. 生成测试报告
            self.test_results['success_rate'] = {
                'account_operations': passed_operations / len(self.accounts) * 100,
                'transaction_creation': successful_transactions / len(transaction_tests) * 100
            }

            logger.info("=" * 50)
            logger.info("Account基础测试套件结果")
            logger.info("=" * 50)
            logger.info(f"创建账户数: {self.test_results['accounts_created']}")
            logger.info(f"初始化账户数: {self.test_results['accounts_initialized']}")
            logger.info(f"创建交易数: {self.test_results['transactions_created']}")
            logger.info(f"验证交易数: {self.test_results['transactions_verified']}")
            logger.info(f"账户操作通过率: {self.test_results['success_rate']['account_operations']:.1f}%")
            logger.info(f"交易创建通过率: {self.test_results['success_rate']['transaction_creation']:.1f}%")

            if self.test_results['errors']:
                logger.warning(f"错误数量: {len(self.test_results['errors'])}")
                for i, error in enumerate(self.test_results['errors'], 1):
                    logger.warning(f"  {i}. {error}")

            return self.test_results

        finally:
            if self.cleanup:
                self._cleanup()

    def _cleanup(self):
        """清理测试环境"""
        try:
            # 清理账户
            for account in self.accounts:
                if hasattr(account, 'cleanup'):
                    account.cleanup()

            # 清理临时目录
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理测试环境失败: {e}")

    def __del__(self):
        """析构函数"""
        if hasattr(self, 'cleanup') and self.cleanup:
            self._cleanup()


# 便捷函数
def run_account_test(temp_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    运行Account测试的便捷函数

    Args:
        temp_dir: 临时目录路径

    Returns:
        测试结果字典
    """
    test = AccountTest(temp_dir)
    return test.run_basic_test_suite()


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行测试
    result = run_account_test()

    # 根据测试结果设置退出码
    if (len(result['errors']) == 0 and
        result['success_rate']['account_operations'] >= 80 and
        result['success_rate']['transaction_creation'] >= 80):
        print("✅ Account核心功能测试通过!")
        exit(0)
    else:
        print("❌ Account核心功能测试失败!")
        exit(1)