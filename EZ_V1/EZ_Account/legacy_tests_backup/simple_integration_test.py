#!/usr/bin/env python3
"""
EZChain简化集成测试

为了避免多进程序列化问题，这个版本使用线程模拟多节点环境，
专注于验证核心功能的集成正确性。

作者：Claude
日期：2025年1月
"""

import sys
import os
import threading
import time
import random
import tempfile
import shutil
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block
from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.MultiTransactions import MultiTransactions
from backup_EZ_Transaction_Pool.TransactionPool import TransactionPool
from backup_EZ_Transaction_Pool.PackTransactions import TransactionPackager
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
class SimpleTestConfig:
    """简化测试配置"""
    num_accounts: int = 3
    num_transaction_rounds: int = 5
    transactions_per_round: int = 2
    block_interval: float = 2.0
    transaction_interval: float = 0.5
    test_duration: int = 20
    base_balance: int = 5000
    transaction_amount_range: Tuple[int, int] = (50, 200)


@dataclass
class SimpleTestStats:
    """简化测试统计"""
    total_transactions_created: int = 0
    total_transactions_confirmed: int = 0
    total_blocks_created: int = 0
    total_vpb_updates: int = 0
    errors: List[str] = None
    start_time: float = 0
    end_time: float = 0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def success_rate(self) -> float:
        if self.total_transactions_created == 0:
            return 0.0
        return (self.total_transactions_confirmed / self.total_transactions_created) * 100


@dataclass
class AccountInfo:
    """账户信息"""
    address: str
    private_key_pem: bytes
    public_key_pem: bytes
    name: str
    account: Optional[Account] = None


class SimpleIntegrationTest:
    """简化集成测试"""

    def __init__(self, config: SimpleTestConfig):
        self.config = config
        self.stats = SimpleTestStats()
        self.running = False
        self.lock = threading.RLock()

        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp(prefix="ezchain_simple_test_")

        # 共享组件
        self.transaction_pool = None
        self.blockchain = None
        self.accounts = []
        self.transaction_packager = None

    def generate_test_accounts(self) -> List[AccountInfo]:
        """生成测试账户"""
        accounts = []

        for i in range(self.config.num_accounts):
            # 生成密钥对
            private_key = ec.generate_private_key(ec.SECP256K1(), default_backend())
            public_key = private_key.public_key()

            # 序列化密钥
            private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

            public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            # 生成地址
            address = f"account_{chr(65 + i)}_{hashlib.sha256(public_key_pem).hexdigest()[:16]}"

            account_info = AccountInfo(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=f"Account_{chr(65 + i)}"
            )

            accounts.append(account_info)
            logger.info(f"生成测试账户: {account_info.name} ({account_info.address})")

        return accounts

    def initialize_account(self, account_info: AccountInfo) -> bool:
        """初始化账户"""
        try:
            # 创建Account对象
            account = Account(
                address=account_info.address,
                private_key_pem=account_info.private_key_pem,
                public_key_pem=account_info.public_key_pem,
                name=account_info.name
            )

            # 初始化创世余额
            genesis_value = Value("0x1000", self.config.base_balance)
            genesis_proof_units = []
            genesis_block_index = BlockIndexList([0], owner=account_info.address)

            success = account.initialize_from_genesis(
                genesis_value, genesis_proof_units, genesis_block_index
            )

            if success:
                account_info.account = account
                logger.info(f"账户 {account_info.name} 初始化成功，余额: {self.config.base_balance}")
            else:
                logger.error(f"账户 {account_info.name} 初始化失败")

            return success

        except Exception as e:
            logger.error(f"初始化账户 {account_info.name} 失败: {e}")
            return False

    def setup_shared_components(self):
        """设置共享组件"""
        try:
            # 创建区块链
            chain_config = ChainConfig(
                max_fork_height=6,
                confirmation_blocks=6,
                enable_fork_resolution=True,
                debug_mode=True,
                data_directory=os.path.join(self.temp_dir, "blockchain_data")
            )
            self.blockchain = Blockchain(chain_config)

            # 创建交易池
            self.transaction_pool = TransactionPool(
                db_path=os.path.join(self.temp_dir, "transaction_pool.db")
            )

            # 创建交易打包器
            self.transaction_packager = TransactionPackager()

            logger.info("共享组件初始化完成")
            return True

        except Exception as e:
            logger.error(f"初始化共享组件失败: {e}")
            return False

    def consensus_thread(self):
        """共识线程"""
        logger.info("共识线程启动")
        block_count = 0
        last_block_time = time.time()

        while self.running:
            try:
                current_time = time.time()

                # 定期打包区块
                if current_time - last_block_time >= self.config.block_interval:
                    # 从交易池获取待打包交易
                    pending_txns = self.transaction_pool.get_pending_transactions(limit=50)

                    if pending_txns:
                        # 使用TransactionPackager打包交易
                        package_data = self.transaction_packager.package_transactions(
                            self.transaction_pool, "fifo"
                        )

                        if package_data.selected_multi_txns:
                            # 从打包数据创建新区块
                            previous_hash = self.blockchain.get_latest_block().get_hash() if self.blockchain.get_latest_block() else "0" * 64
                            new_block = self.transaction_packager.create_block_from_package(
                                package_data,
                                miner_address="consensus_node",
                                previous_hash=previous_hash,
                                block_index=block_count + 1
                            )

                            # 添加区块到区块链
                            self.blockchain.add_block(new_block)

                            # 从交易池移除已打包的交易
                            self.transaction_packager.remove_packaged_transactions(
                                self.transaction_pool, package_data.selected_multi_txns
                            )

                            with self.lock:
                                block_count += 1
                                self.stats.total_blocks_created += 1
                                self.stats.total_transactions_confirmed += len(package_data.selected_multi_txns)

                            logger.info(f"共识节点生成区块: #{block_count}, 包含 {len(package_data.selected_multi_txns)} 笔交易")

                    last_block_time = current_time

                # 短暂休眠
                time.sleep(0.1)

            except Exception as e:
                with self.lock:
                    self.stats.errors.append(f"共识线程错误: {e}")
                logger.error(f"共识线程错误: {e}")

        logger.info("共识线程结束")

    def account_thread(self, account_info: AccountInfo):
        """账户线程"""
        logger.info(f"账户线程 {account_info.name} 启动")

        account = account_info.account
        other_accounts = [acc for acc in self.accounts if acc.address != account_info.address]

        last_transaction_time = time.time()
        rounds_completed = 0

        while self.running:
            try:
                current_time = time.time()

                # 随机生成交易
                if (current_time - last_transaction_time >= self.config.transaction_interval and
                    rounds_completed < self.config.num_transaction_rounds and
                    len(other_accounts) > 0):

                    # 随机选择收款方
                    recipient = random.choice(other_accounts)

                    # 随机选择交易金额
                    amount = random.randint(*self.config.transaction_amount_range)

                    # 检查余额是否足够
                    if account.get_available_balance() >= amount:
                        # 创建交易请求
                        transaction_requests = [
                            {
                                'recipient': recipient.address,
                                'amount': amount
                            }
                        ]

                        # 创建多笔交易
                        multi_txn_result = account.create_batch_transactions(
                            transaction_requests,
                            reference=f"{account_info.name}_to_{recipient.name}_{rounds_completed}"
                        )

                        if multi_txn_result:
                            # 提交交易到交易池
                            validation_result = self.transaction_pool.add_multi_transaction(
                                multi_txn_result["multi_transactions"]
                            )

                            if validation_result.is_valid:
                                with self.lock:
                                    self.stats.total_transactions_created += 1
                                logger.info(f"{account_info.name} 创建交易: {amount} -> {recipient.name}")
                                rounds_completed += 1
                                last_transaction_time = current_time
                            else:
                                logger.warning(f"{account_info.name} 交易验证失败: {validation_result.error_message}")
                        else:
                            logger.warning(f"{account_info.name} 创建交易失败")
                    else:
                        logger.warning(f"{account_info.name} 余额不足，跳过交易")

                # 短暂休眠
                time.sleep(0.1)

            except Exception as e:
                with self.lock:
                    self.stats.errors.append(f"账户线程 {account_info.name} 错误: {e}")
                logger.error(f"账户线程 {account_info.name} 错误: {e}")

        # 输出账户最终状态
        try:
            final_balance = account.get_available_balance()
            logger.info(f"账户 {account_info.name} 最终余额: {final_balance}")
        except Exception as e:
            logger.error(f"获取账户 {account_info.name} 最终状态失败: {e}")

        logger.info(f"账户线程 {account_info.name} 结束")

    def run_test(self) -> SimpleTestStats:
        """运行测试"""
        logger.info("开始简化集成测试")

        try:
            # 生成测试账户
            self.accounts = self.generate_test_accounts()

            # 初始化账户
            for account_info in self.accounts:
                if not self.initialize_account(account_info):
                    raise Exception(f"初始化账户 {account_info.name} 失败")

            # 设置共享组件
            if not self.setup_shared_components():
                raise Exception("初始化共享组件失败")

            # 设置运行标志
            self.running = True
            self.stats.start_time = time.time()

            # 创建线程
            threads = []

            # 启动共识线程
            consensus_thread = threading.Thread(target=self.consensus_thread, name="Consensus")
            threads.append(consensus_thread)

            # 启动账户线程
            for account_info in self.accounts:
                account_thread = threading.Thread(
                    target=self.account_thread,
                    args=(account_info,),
                    name=f"Account_{account_info.name}"
                )
                threads.append(account_thread)

            # 启动所有线程
            logger.info("启动所有线程...")
            for thread in threads:
                thread.start()

            # 等待测试完成
            try:
                time.sleep(self.config.test_duration)
            except KeyboardInterrupt:
                logger.info("收到中断信号，正在停止测试...")

            # 停止测试
            self.running = False
            self.stats.end_time = time.time()

            # 等待所有线程结束
            logger.info("等待所有线程结束...")
            for thread in threads:
                thread.join(timeout=5)
                if thread.is_alive():
                    logger.warning(f"线程 {thread.name} 未正常结束")

            # 输出测试结果
            logger.info("=" * 50)
            logger.info("测试结果统计")
            logger.info("=" * 50)
            logger.info(f"总测试时长: {self.stats.end_time - self.stats.start_time:.2f} 秒")
            logger.info(f"创建交易总数: {self.stats.total_transactions_created}")
            logger.info(f"确认交易总数: {self.stats.total_transactions_confirmed}")
            logger.info(f"创建区块总数: {self.stats.total_blocks_created}")
            logger.info(f"交易成功率: {self.stats.success_rate:.2f}%")

            if self.stats.errors:
                logger.warning(f"错误统计:")
                for i, error in enumerate(self.stats.errors, 1):
                    logger.warning(f"  {i}. {error}")

            # 验证测试条件
            test_passed = True
            if self.stats.total_transactions_created == 0:
                logger.error("测试失败: 没有创建任何交易")
                test_passed = False

            if self.stats.total_blocks_created == 0:
                logger.error("测试失败: 没有创建任何区块")
                test_passed = False

            if self.stats.success_rate < 80:
                logger.error(f"测试失败: 交易成功率过低 ({self.stats.success_rate:.2f}%)")
                test_passed = False

            if self.stats.errors:
                logger.error(f"测试失败: 发生了 {len(self.stats.errors)} 个错误")
                test_passed = False

            if test_passed:
                logger.info("✅ 简化集成测试通过!")
            else:
                logger.error("❌ 简化集成测试失败!")

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
    config = SimpleTestConfig(
        num_accounts=3,
        num_transaction_rounds=5,
        transactions_per_round=2,
        block_interval=2.0,
        transaction_interval=0.5,
        test_duration=20,
        base_balance=5000,
        transaction_amount_range=(50, 200)
    )

    # 创建并运行测试
    test = SimpleIntegrationTest(config)

    try:
        stats = test.run_test()
        return 0 if stats.errors and len(stats.errors) == 0 else 1
    except Exception as e:
        logger.error(f"测试运行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())