#!/usr/bin/env python3
"""
EZChain基础集成测试

这个版本专注于验证Account和VPBManager的基本功能，
不使用复杂的Blockchain和TransactionPool。

作者：Claude
日期：2025年1月
"""

import sys
import os
import time
import tempfile
import shutil
import random
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.MultiTransactions import MultiTransactions
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
import hashlib


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class BasicTestConfig:
    """基础测试配置"""
    num_accounts: int = 3
    num_transactions: int = 5
    base_balance: int = 1000
    transaction_amount_range: Tuple[int, int] = (10, 200)


@dataclass
class BasicTestStats:
    """基础测试统计"""
    accounts_created: int = 0
    accounts_initialized: int = 0
    transactions_created: int = 0
    transactions_succeeded: int = 0
    vpb_operations: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class BasicIntegrationTest:
    """基础集成测试"""

    def __init__(self, config: BasicTestConfig):
        self.config = config
        self.stats = BasicTestStats()
        self.temp_dir = tempfile.mkdtemp(prefix="ezchain_basic_test_")
        self.accounts = []

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

    def create_test_account(self, name: str, balance: int) -> Optional[Account]:
        """创建测试账户"""
        try:
            # 生成密钥对
            private_key_pem, public_key_pem = self.generate_key_pair()

            # 生成地址
            address = f"{name}_{hashlib.sha256(public_key_pem).hexdigest()[:16]}"

            # 创建Account对象
            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=name
            )

            # 初始化创世余额
            genesis_value = Value("0x1000", balance)
            genesis_proof_units = []
            genesis_block_index = BlockIndexList([0], owner=address)

            if account.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index):
                logger.info(f"账户 {name} 创建成功，地址: {address}, 余额: {balance}")
                self.stats.accounts_created += 1
                self.stats.accounts_initialized += 1
                return account
            else:
                logger.error(f"账户 {name} 初始化失败")
                return None

        except Exception as e:
            error_msg = f"创建账户 {name} 失败: {e}"
            logger.error(error_msg)
            self.stats.errors.append(error_msg)
            return None

    def test_account_operations(self, account: Account) -> bool:
        """测试账户基本操作"""
        try:
            # 测试余额查询
            available_balance = account.get_available_balance()
            total_balance = account.get_total_balance()

            logger.info(f"账户 {account.name} 可用余额: {available_balance}, 总余额: {total_balance}")

            # 测试Value查询
            unspent_values = account.get_unspent_values()
            all_values = account.get_values()

            logger.info(f"账户 {account.name} 未花销Value数: {len(unspent_values)}, 总Value数: {len(all_values)}")

            # 测试VPB摘要
            vpb_summary = account.get_vpb_summary()
            logger.info(f"账户 {account.name} VPB摘要: {vpb_summary}")

            # 测试VPB完整性验证
            vpb_valid = account.validate_vpb_integrity()
            logger.info(f"账户 {account.name} VPB完整性: {'✅ 通过' if vpb_valid else '❌ 失败'}")

            self.stats.vpb_operations += 4
            return True

        except Exception as e:
            error_msg = f"测试账户 {account.name} 操作失败: {e}"
            logger.error(error_msg)
            self.stats.errors.append(error_msg)
            return False

    def test_transaction_creation(self, sender: Account, recipient: Account, amount: int) -> bool:
        """测试交易创建"""
        try:
            # 检查发送方余额
            if sender.get_available_balance() < amount:
                logger.warning(f"发送方 {sender.name} 余额不足，跳过交易")
                return False

            # 创建交易请求
            transaction_requests = [
                {
                    'recipient': recipient.address,
                    'amount': amount
                }
            ]

            # 创建多笔交易
            multi_txn_result = sender.create_batch_transactions(
                transaction_requests,
                reference=f"{sender.name}_to_{recipient.name}_{int(time.time())}"
            )

            if multi_txn_result:
                multi_txn = multi_txn_result["multi_transactions"]

                # 验证交易
                verification_result = sender.verify_multi_transaction_signature(multi_txn_result)

                if verification_result:
                    logger.info(f"交易创建成功: {sender.name} -> {recipient.name}, 金额: {amount}")
                    self.stats.transactions_created += 1
                    self.stats.transactions_succeeded += 1
                    self.stats.vpb_operations += 1
                    return True
                else:
                    logger.error(f"交易签名验证失败: {sender.name} -> {recipient.name}")
                    return False
            else:
                logger.error(f"交易创建失败: {sender.name} -> {recipient.name}")
                return False

        except Exception as e:
            error_msg = f"测试交易创建失败: {e}"
            logger.error(error_msg)
            self.stats.errors.append(error_msg)
            return False

    def run_test(self) -> BasicTestStats:
        """运行基础集成测试"""
        logger.info("开始基础集成测试")
        logger.info(f"临时目录: {self.temp_dir}")

        try:
            # 1. 创建测试账户
            logger.info("步骤 1: 创建测试账户")
            for i in range(self.config.num_accounts):
                name = f"TestAccount_{chr(65 + i)}"
                account = self.create_test_account(name, self.config.base_balance)
                if account:
                    self.accounts.append(account)

            if len(self.accounts) < 2:
                raise Exception("需要至少2个账户才能进行测试")

            # 2. 测试账户基本操作
            logger.info("步骤 2: 测试账户基本操作")
            for account in self.accounts:
                if not self.test_account_operations(account):
                    logger.error(f"账户 {account.name} 基本操作测试失败")

            # 3. 测试交易创建
            logger.info("步骤 3: 测试交易创建")
            transaction_count = 0
            for i in range(self.config.num_transactions):
                if len(self.accounts) >= 2:
                    # 随机选择发送方和接收方
                    sender_idx = random.randint(0, len(self.accounts) - 1)
                    recipient_idx = (sender_idx + 1) % len(self.accounts)

                    sender = self.accounts[sender_idx]
                    recipient = self.accounts[recipient_idx]

                    # 随机选择金额
                    amount = random.randint(*self.config.transaction_amount_range)

                    if self.test_transaction_creation(sender, recipient, amount):
                        transaction_count += 1

            # 4. 测试结果验证
            logger.info("步骤 4: 测试结果验证")
            final_success_rate = (self.stats.transactions_succeeded / max(self.stats.transactions_created, 1)) * 100

            logger.info("=" * 50)
            logger.info("基础集成测试结果")
            logger.info("=" * 50)
            logger.info(f"创建账户数: {self.stats.accounts_created}")
            logger.info(f"初始化账户数: {self.stats.accounts_initialized}")
            logger.info(f"创建交易数: {self.stats.transactions_created}")
            logger.info(f"成功交易数: {self.stats.transactions_succeeded}")
            logger.info(f"VPB操作数: {self.stats.vpb_operations}")
            logger.info(f"交易成功率: {final_success_rate:.2f}%")

            if self.stats.errors:
                logger.warning(f"错误数量: {len(self.stats.errors)}")
                for i, error in enumerate(self.stats.errors, 1):
                    logger.warning(f"  {i}. {error}")

            # 5. 最终账户状态
            logger.info("步骤 5: 最终账户状态")
            for account in self.accounts:
                account_info = account.get_account_info()
                logger.info(f"账户 {account.name} 最终信息:")
                logger.info(f"  地址: {account_info['address']}")
                logger.info(f"  可用余额: {account_info['balances']['available']}")
                logger.info(f"  总余额: {account_info['balances']['total']}")
                logger.info(f"  Value总数: {account_info['values_count']}")
                logger.info(f"  VPB统计: {account_info['vpb_summary']}")

            # 6. 评判测试结果
            test_passed = True

            if self.stats.accounts_created != self.config.num_accounts:
                logger.error("账户创建不完整")
                test_passed = False

            if self.stats.transactions_created == 0:
                logger.error("没有创建任何交易")
                test_passed = False

            if final_success_rate < 80:
                logger.error(f"交易成功率过低: {final_success_rate:.2f}%")
                test_passed = False

            if self.stats.errors:
                logger.error(f"存在 {len(self.stats.errors)} 个错误")
                test_passed = False

            if test_passed:
                logger.info("✅ 基础集成测试通过!")
            else:
                logger.error("❌ 基础集成测试失败!")

            return self.stats

        finally:
            # 清理临时目录
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"清理临时目录: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")


def main():
    """主函数"""
    # 创建测试配置
    config = BasicTestConfig(
        num_accounts=3,
        num_transactions=5,
        base_balance=1000,
        transaction_amount_range=(10, 200)
    )

    # 创建并运行测试
    test = BasicIntegrationTest(config)

    try:
        stats = test.run_test()
        return 0 if len(stats.errors) == 0 else 1
    except Exception as e:
        logger.error(f"测试运行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())