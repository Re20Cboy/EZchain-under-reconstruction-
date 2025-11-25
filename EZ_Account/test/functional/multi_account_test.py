"""
多账户测试

简化版本的多账户测试，基于线程而非进程实现
避免多进程序列化问题，专注于核心功能测试
"""

import sys
import os
import time
import tempfile
import shutil
import random
import threading
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
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class MultiAccountTestResult:
    """多账户测试结果"""
    num_accounts: int = 0
    test_duration: int = 0
    total_transactions: int = 0
    successful_transactions: int = 0
    total_blocks: int = 0
    errors: List[str] = None
    start_time: float = 0
    end_time: float = 0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class MockTransactionPool:
    """模拟交易池"""

    def __init__(self):
        self.transactions = []
        self.lock = threading.Lock()

    def add_transaction(self, transaction):
        """添加交易到池"""
        with self.lock:
            self.transactions.append(transaction)
            return True

    def get_pending_transactions(self, limit: int = 10):
        """获取待处理交易"""
        with self.lock:
            return self.transactions[:limit]

    def remove_transactions(self, transactions):
        """移除已处理的交易"""
        with self.lock:
            for txn in transactions:
                if txn in self.transactions:
                    self.transactions.remove(txn)


class MockBlockchain:
    """模拟区块链"""

    def __init__(self):
        self.blocks = []
        self.block_height = 0
        self.lock = threading.Lock()

    def create_block(self, transactions):
        """创建新区块"""
        with self.lock:
            block = {
                'height': self.block_height,
                'transactions': transactions,
                'timestamp': time.time()
            }
            self.blocks.append(block)
            self.block_height += 1
            return block


class MultiAccountTest:
    """多账户测试类"""

    def __init__(self, temp_dir: Optional[str] = None, cleanup: bool = True):
        """
        初始化多账户测试

        Args:
            temp_dir: 临时目录
            cleanup: 是否清理临时文件
        """
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="ezchain_multi_test_")
        self.cleanup = cleanup
        self.accounts: List[Account] = []
        self.running = False
        self.result = MultiAccountTestResult()

        # 模拟组件
        self.transaction_pool = MockTransactionPool()
        self.blockchain = MockBlockchain()

        # 线程同步
        self.lock = threading.RLock()

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

    def create_accounts(self, num_accounts: int, initial_balance: int = 1000) -> bool:
        """创建测试账户"""
        try:
            logger.info(f"创建 {num_accounts} 个测试账户，初始余额: {initial_balance}")

            for i in range(num_accounts):
                private_key_pem, public_key_pem = self.generate_key_pair()
                address = f"Node{i}_{hashlib.sha256(public_key_pem).hexdigest()[:12]}"

                account = Account(
                    address=address,
                    private_key_pem=private_key_pem,
                    public_key_pem=public_key_pem,
                    name=f"Node{i}"
                )

                # 初始化创世余额
                genesis_value = Value(f"0x{1000 + i}", initial_balance, ValueState.UNSPENT)
                genesis_proof_units = []
                genesis_block_index = BlockIndexList([0], owner=address)

                if account.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index):
                    self.accounts.append(account)
                    self.result.num_accounts += 1
                else:
                    logger.error(f"账户 {i} 初始化失败")
                    return False

            logger.info(f"成功创建 {len(self.accounts)} 个账户")
            return True

        except Exception as e:
            logger.error(f"创建账户失败: {e}")
            self.result.errors.append(f"创建账户失败: {e}")
            return False

    def get_available_balance(self, account: Account) -> int:
        """获取可用余额"""
        try:
            return account.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)
        except Exception as e:
            logger.error(f"查询账户 {account.name} 余额失败: {e}")
            return 0

    def account_transaction_worker(self, account: Account, num_transactions: int):
        """账户交易工作线程"""
        logger.info(f"账户 {account.name} 交易线程启动")

        transactions_created = 0
        attempts = 0
        max_attempts = num_transactions * 3  # 最多尝试3倍数量的交易

        while self.running and transactions_created < num_transactions and attempts < max_attempts:
            try:
                # 随机选择其他账户作为接收方
                other_accounts = [a for a in self.accounts if a.address != account.address]
                if not other_accounts:
                    break

                recipient = random.choice(other_accounts)
                sender_balance = self.get_available_balance(account)

                if sender_balance < 10:  # 最低交易金额
                    break

                # 随机交易金额
                amount = random.randint(10, min(100, sender_balance))

                # 创建交易
                transaction_requests = [
                    {
                        'recipient': recipient.address,
                        'amount': amount
                    }
                ]

                multi_txn_result = account.create_batch_transactions(
                    transaction_requests,
                    reference=f"{account.name}_txn_{transactions_created}"
                )

                if multi_txn_result:
                    # 提交到交易池
                    self.transaction_pool.add_transaction(multi_txn_result["multi_transactions"])
                    transactions_created += 1
                    self.result.successful_transactions += 1

                    with self.lock:
                        self.result.total_transactions += 1

                    logger.info(f"账户 {account.name} 创建交易 #{transactions_created}: {amount} -> {recipient.name}")

                attempts += 1

                # 随机延迟
                time.sleep(random.uniform(0.1, 0.5))

            except Exception as e:
                logger.error(f"账户 {account.name} 交易失败: {e}")
                attempts += 1

        logger.info(f"账户 {account.name} 交易线程结束，创建了 {transactions_created} 笔交易")

    def consensus_worker(self, block_interval: float):
        """共识节点工作线程"""
        logger.info("共识线程启动")

        last_block_time = time.time()

        while self.running:
            try:
                current_time = time.time()

                # 定期打包区块
                if current_time - last_block_time >= block_interval:
                    pending_txns = self.transaction_pool.get_pending_transactions(limit=10)

                    if pending_txns:
                        # 创建区块
                        block = self.blockchain.create_block(pending_txns)

                        # 从交易池移除已打包的交易
                        self.transaction_pool.remove_transactions(pending_txns)

                        with self.lock:
                            self.result.total_blocks += 1

                        logger.info(f"共识节点创建区块 #{block['height']}, 包含 {len(pending_txns)} 笔交易")

                    last_block_time = current_time

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"共识线程错误: {e}")
                self.result.errors.append(f"共识线程错误: {e}")

        logger.info("共识线程结束")

    def run_multi_account_test(self, num_accounts: int = 3, num_transactions: int = 5,
                             test_duration: int = 20, block_interval: float = 2.0) -> MultiAccountTestResult:
        """
        运行多账户测试

        Args:
            num_accounts: 账户数量
            num_transactions: 每个账户的交易数量
            test_duration: 测试持续时间（秒）
            block_interval: 区块生成间隔（秒）

        Returns:
            测试结果
        """
        logger.info("开始多账户测试")
        logger.info(f"配置: {num_accounts}个账户, {num_transactions}笔交易/账户, {test_duration}秒测试时长")
        logger.info(f"临时目录: {self.temp_dir}")

        self.result.start_time = time.time()
        self.result.num_accounts = num_accounts
        self.result.test_duration = test_duration

        try:
            # 1. 创建账户
            if not self.create_accounts(num_accounts, 1000):
                raise Exception("创建账户失败")

            if len(self.accounts) < 2:
                raise Exception("需要至少2个账户")

            # 2. 启动测试
            self.running = True

            # 启动共识线程
            consensus_thread = threading.Thread(
                target=self.consensus_worker,
                args=(block_interval,),
                name="Consensus"
            )
            consensus_thread.start()

            # 启动账户交易线程
            account_threads = []
            for account in self.accounts:
                thread = threading.Thread(
                    target=self.account_transaction_worker,
                    args=(account, num_transactions),
                    name=f"Account-{account.name}"
                )
                thread.start()
                account_threads.append(thread)

            logger.info(f"启动了 1个共识线程和 {len(account_threads)} 个账户线程")

            # 3. 等待测试完成
            time.sleep(test_duration)

            # 4. 停止测试
            self.running = False
            self.result.end_time = time.time()

            # 5. 等待所有线程结束
            logger.info("等待所有线程结束...")
            for thread in account_threads + [consensus_thread]:
                thread.join(timeout=3)
                if thread.is_alive():
                    logger.warning(f"线程 {thread.name} 未正常结束")

            # 6. 打印结果
            self._print_results()

            return self.result

        except Exception as e:
            error_msg = f"多账户测试执行失败: {e}"
            logger.error(error_msg)
            self.result.errors.append(error_msg)
            self.result.end_time = time.time()
            return self.result

        finally:
            if self.cleanup:
                self._cleanup()

    def _print_results(self):
        """打印测试结果"""
        duration = self.result.end_time - self.result.start_time

        logger.info("=" * 60)
        logger.info("多账户测试结果")
        logger.info("=" * 60)
        logger.info(f"测试时长: {duration:.2f} 秒")
        logger.info(f"参与账户: {self.result.num_accounts}")
        logger.info(f"创建交易总数: {self.result.total_transactions}")
        logger.info(f"成功交易总数: {self.result.successful_transactions}")
        logger.info(f"创建区块总数: {self.result.total_blocks}")
        logger.info(f"平均TPS: {self.result.total_transactions / max(duration, 1):.2f}")

        if self.result.errors:
            logger.warning(f"错误数量: {len(self.result.errors)}")
            for i, error in enumerate(self.result.errors, 1):
                logger.warning(f"  {i}. {error}")

        # 评判测试结果
        test_passed = True
        if self.result.num_accounts < 2:
            logger.error("账户数量不足")
            test_passed = False

        if self.result.total_transactions == 0:
            logger.error("没有创建任何交易")
            test_passed = False

        success_rate = (self.result.successful_transactions / max(self.result.total_transactions, 1)) * 100
        if success_rate < 50:
            logger.error(f"交易成功率过低: {success_rate:.1f}%")
            test_passed = False

        if test_passed:
            logger.info("✅ 多账户测试通过!")
        else:
            logger.error("❌ 多账户测试失败!")

    def _cleanup(self):
        """清理测试环境"""
        try:
            for account in self.accounts:
                if hasattr(account, 'cleanup'):
                    account.cleanup()

            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理失败: {e}")


# 便捷函数
def run_multi_account_test(num_accounts: int = 3, num_transactions: int = 5,
                          test_duration: int = 20) -> MultiAccountTestResult:
    """运行多账户测试的便捷函数"""
    test = MultiAccountTest()
    return test.run_multi_account_test(num_accounts, num_transactions, test_duration)


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行测试
    result = run_multi_account_test(num_accounts=3, num_transactions=3, test_duration=15)

    # 根据结果设置退出码
    if len(result.errors) == 0 and result.successful_transactions > 0:
        print("✅ 多账户测试通过!")
        exit(0)
    else:
        print("❌ 多账户测试失败!")
        exit(1)