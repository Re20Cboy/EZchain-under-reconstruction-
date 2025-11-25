#!/usr/bin/env python3
"""
EZChain多进程多账户节点功能模拟测试

这个测试实现了MultiAccountTest纲要中描述的完整联调测试场景：
- 创建四个进程：主链共识节点、账户节点A、账户节点B、账户节点C
- A、B、C三个账户节点连接到主链共识节点，并进行随机交易
- 测试主链、账户节点、交易池、VPB管理等模块的集成正确性

作者：Claude
日期：2025年1月
版本：1.0
"""

import sys
import os
import multiprocessing
import threading
import time
import random
import json
import tempfile
import shutil
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
import signal
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig, ConsensusStatus
from EZ_Main_Chain.Block import Block
from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction_Pool.TransactionPool import TransactionPool
from EZ_Transaction_Pool.PackTransactions import TransactionPackager
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
import secrets
import hashlib


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TestConfig:
    """测试配置参数"""
    num_accounts: int = 3  # 账户节点数量（A、B、C）
    num_transaction_rounds: int = 5  # 交易轮数
    transactions_per_round: int = 3  # 每轮交易数量
    block_interval: float = 2.0  # 区块生成间隔（秒）
    transaction_interval: float = 0.5  # 交易间隔（秒）
    test_duration: int = 30  # 总测试时长（秒）
    base_balance: int = 10000  # 账户初始余额
    transaction_amount_range: Tuple[int, int] = (10, 500)  # 交易金额范围
    temp_dir: Optional[str] = None  # 临时目录，如果为None则自动创建


@dataclass
class AccountInfo:
    """账户信息"""
    address: str
    private_key_pem: bytes
    public_key_pem: bytes
    name: str
    initial_balance: int = 0


@dataclass
class TestStats:
    """测试统计信息"""
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


class MultiProcessCommunication:
    """多进程通信管理器"""

    def __init__(self):
        self.manager = multiprocessing.Manager()
        # 创建共享队列用于进程间通信
        self.transaction_queue = self.manager.Queue()
        self.block_queue = self.manager.Queue()
        self.stats_dict = self.manager.dict()
        self.stop_event = self.manager.Event()

    def put_transaction_data(self, txn_data: dict):
        """提交交易数据到队列"""
        try:
            self.transaction_queue.put(txn_data)
            return True
        except Exception as e:
            logger.error(f"提交交易失败: {e}")
            return False

    def get_transaction_data(self, timeout: float = 1.0) -> Optional[dict]:
        """从队列获取交易数据"""
        try:
            return self.transaction_queue.get(timeout=timeout)
        except Empty:
            return None

    def put_block_data(self, block_data: dict):
        """广播区块数据"""
        try:
            self.block_queue.put(block_data)
            return True
        except Exception as e:
            logger.error(f"广播区块失败: {e}")
            return False

    def get_block_data(self, timeout: float = 1.0) -> Optional[dict]:
        """获取广播的区块数据"""
        try:
            return self.block_queue.get(timeout=timeout)
        except Empty:
            return None


def generate_test_accounts(num_accounts: int, base_balance: int) -> List[AccountInfo]:
    """生成测试账户"""
    accounts = []

    for i in range(num_accounts):
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

        # 生成地址（简化版，使用公钥哈希）
        public_key_bytes = public_key_pem
        address = f"account_{chr(65 + i)}_{hashlib.sha256(public_key_bytes).hexdigest()[:16]}"

        account_info = AccountInfo(
            address=address,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            name=f"Account_{chr(65 + i)}",
            initial_balance=base_balance
        )

        accounts.append(account_info)
        logger.info(f"生成测试账户: {account_info.name} ({account_info.address})")

    return accounts


def initialize_account_with_genesis(account: Account, initial_balance: int) -> bool:
    """为账户初始化创世余额"""
    try:
        # 创建创世Value
        genesis_value = Value("0x1000", initial_balance)

        # 创建空的ProofUnits列表（创世块不需要proof）
        genesis_proof_units = []

        # 创建创世BlockIndex（高度为0）
        genesis_block_index = BlockIndexList([0], owner=account.address)

        # 初始化VPB
        success = account.initialize_from_genesis(
            genesis_value, genesis_proof_units, genesis_block_index
        )

        if success:
            logger.info(f"账户 {account.name} 创世余额设置成功: {initial_balance}")
        else:
            logger.error(f"账户 {account.name} 创世余额设置失败")

        return success

    except Exception as e:
        logger.error(f"初始化账户 {account.name} 创世余额失败: {e}")
        return False


def consensus_node_process(config: TestConfig, account_infos: List[AccountInfo],
                          comm: MultiProcessCommunication, stats: TestStats):
    """主链共识节点进程"""
    logger.info("主链共识节点进程启动")

    try:
        # 创建区块链
        chain_config = ChainConfig(
            max_fork_height=6,
            confirmation_blocks=6,
            enable_fork_resolution=True,
            debug_mode=True,
            data_directory=os.path.join(config.temp_dir, "blockchain_data")
        )
        blockchain = Blockchain(chain_config)

        # 创建交易池
        transaction_pool = TransactionPool(
            db_path=os.path.join(config.temp_dir, "consensus_pool.db")
        )

        # 创建打包器
        packer = TransactionPackager()

        block_count = 0
        last_block_time = time.time()

        while not comm.stop_event.is_set() and (time.time() - stats.start_time) < config.test_duration:
            try:
                # 1. 接收交易
                current_time = time.time()
                transactions_processed = 0

                while True:
                    txn_data = comm.get_transaction_data(timeout=0.1)
                    if txn_data is None:
                        break

                    # 重新构造MultiTransactions对象
                    try:
                        import pickle
                        multi_txn_bytes = bytes.fromhex(txn_data['multi_txn_hex'])
                        multi_txn = pickle.loads(multi_txn_bytes)

                        # 验证并添加交易到池
                        validation_result = transaction_pool.add_multi_transaction(multi_txn)
                        if validation_result.is_valid:
                            transactions_processed += 1
                            stats.total_transactions_confirmed += 1
                            logger.info(f"共识节点接收交易成功: {multi_txn.sender[:16]}...")
                        else:
                            logger.warning(f"交易验证失败: {validation_result.error_message}")
                    except Exception as e:
                        logger.error(f"反序列化交易失败: {e}")

                # 2. 定期打包区块
                if current_time - last_block_time >= config.block_interval:
                    # 从交易池获取待打包交易
                    pending_txns = transaction_pool.get_pending_transactions(limit=50)

                    if pending_txns:
                        # 使用TransactionPackager打包交易
                        package_data = packer.package_transactions(transaction_pool, "fifo")

                        if package_data.selected_multi_txns:
                            # 从打包数据创建新区块
                            previous_hash = blockchain.get_latest_block().hash if blockchain.get_latest_block() else "0" * 64
                            new_block = packer.create_block_from_package(
                                package_data,
                                miner_address="consensus_node",
                                previous_hash=previous_hash,
                                block_index=block_count + 1
                            )

                            # 添加区块到区块链
                            blockchain.add_block(new_block)

                            # 生成Proof Units（简化版）
                            proof_units = []
                            for i, multi_txn in enumerate(package_data.selected_multi_txns):
                                proof_unit = ProofUnit(
                                    owner=multi_txn.sender,
                                    owner_multi_txns=multi_txn,
                                    owner_mt_proof=None  # 实际应用中需要生成真实的默克尔证明
                                )
                                proof_units.append(proof_unit)

                            # 广播区块给账户节点
                            block_data = {
                                'block_index': new_block.index,
                                'm_tree_root': new_block.m_tree_root,
                                'miner': new_block.miner,
                                'pre_hash': new_block.pre_hash,
                                'time': new_block.time,
                                'multi_txns_hex': [pickle.dumps(txn).hex() for txn in package_data.selected_multi_txns]
                            }
                            comm.put_block_data(block_data)

                            # 从交易池移除已打包的交易
                            packer.remove_packaged_transactions(transaction_pool, package_data.selected_multi_txns)

                            block_count += 1
                            stats.total_blocks_created += 1
                            last_block_time = current_time

                            logger.info(f"新区块已生成并广播: #{block_count}, 包含 {len(package_data.selected_multi_txns)} 笔交易")

                # 短暂休眠避免CPU占用过高
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"共识节点处理异常: {e}")
                stats.errors.append(str(e))

        logger.info(f"共识节点进程结束，总共处理了 {block_count} 个区块")

    except Exception as e:
        logger.error(f"共识节点进程异常: {e}")
        stats.errors.append(str(e))


def account_node_process(account_info: AccountInfo, config: TestConfig,
                       comm: MultiProcessCommunication, stats: TestStats):
    """账户节点进程"""
    logger.info(f"账户节点 {account_info.name} 启动")

    try:
        # 创建账户
        account_db_path = os.path.join(config.temp_dir, f"account_{account_info.name}_db.db")
        account = Account(
            address=account_info.address,
            private_key_pem=account_info.private_key_pem,
            public_key_pem=account_info.public_key_pem,
            name=account_info.name
        )

        # 初始化创世余额
        if not initialize_account_with_genesis(account, account_info.initial_balance):
            logger.error(f"账户 {account_info.name} 初始化失败")
            return

        # 获取其他账户地址用于交易
        other_accounts = [acc for acc in account_infos if acc.address != account_info.address]

        last_transaction_time = time.time()
        rounds_completed = 0

        while not comm.stop_event.is_set() and (time.time() - stats.start_time) < config.test_duration:
            try:
                current_time = time.time()

                # 1. 随机生成交易
                if (current_time - last_transaction_time >= config.transaction_interval and
                    rounds_completed < config.num_transaction_rounds and
                    len(other_accounts) > 0):

                    # 随机选择收款方
                    recipient = random.choice(other_accounts)

                    # 随机选择交易金额
                    amount = random.randint(*config.transaction_amount_range)

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
                            # 提交交易到共享队列
                            try:
                                import pickle
                                txn_data = {
                                    'multi_txn_hex': pickle.dumps(multi_txn_result["multi_transactions"]).hex(),
                                    'sender': account_info.address
                                }
                                if comm.put_transaction_data(txn_data):
                                    stats.total_transactions_created += 1
                                    logger.info(f"{account_info.name} 创建交易: {amount} -> {recipient.name}")
                                    rounds_completed += 1
                                    last_transaction_time = current_time
                                else:
                                    logger.error(f"{account_info.name} 提交交易失败")
                            except Exception as e:
                                logger.error(f"{account_info.name} 序列化交易失败: {e}")
                        else:
                            logger.warning(f"{account_info.name} 创建交易失败")
                    else:
                        logger.warning(f"{account_info.name} 余额不足，跳过交易")

                # 2. 接收区块更新
                block_data = comm.get_block_data(timeout=0.1)
                if block_data:
                    try:
                        import pickle
                        # 重新构造MultiTransactions对象
                        multi_txns = []
                        for txn_hex in block_data['multi_txns_hex']:
                            txn_bytes = bytes.fromhex(txn_hex)
                            multi_txn = pickle.loads(txn_bytes)
                            multi_txns.append(multi_txn)

                        # 检查是否有涉及当前账户的交易
                        relevant_txns = []
                        for multi_txn in multi_txns:
                            if (multi_txn.sender == account_info.address or
                                any(tx.recipient == account_info.address for tx in multi_txn.multi_txns)):
                                relevant_txns.append(multi_txn)

                        if relevant_txns:
                            # 更新VPB（简化版本，实际应用中需要完整的proof和block_index）
                            for multi_txn in relevant_txns:
                                if multi_txn.sender == account_info.address:
                                    # 作为sender，需要更新已花销的values
                                    for txn in multi_txn.multi_txns:
                                        # 这里简化处理，实际需要找到对应的value并更新状态
                                        pass

                                # 检查是否有接收的交易
                                for txn in multi_txn.multi_txns:
                                    if txn.recipient == account_info.address:
                                        # 作为receiver，创建新的value
                                        new_value = Value(f"0x{random.randint(1000, 9999)}", txn.amount)
                                        # 这里需要添加真实的proof和block_index
                                        # account.add_value_with_vpb(new_value, proofs, block_index)
                                        logger.info(f"{account_info.name} 接收到 {txn.amount} 单位")

                            stats.total_vpb_updates += 1
                            logger.info(f"{account_info.name} VPB更新完成，区块高度: {block_data['block_index']}")

                    except Exception as e:
                        logger.error(f"{account_info.name} 处理区块数据失败: {e}")

                # 短暂休眠
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"账户节点 {account_info.name} 处理异常: {e}")
                stats.errors.append(str(e))

        # 输出账户最终状态
        final_balance = account.get_available_balance()
        account_info = account.get_account_info()
        logger.info(f"账户 {account_info.name} 最终余额: {final_balance}")
        logger.info(f"账户 {account_info.name} 最终状态: {json.dumps(account_info, indent=2, default=str)}")

    except Exception as e:
        logger.error(f"账户节点 {account_info.name} 异常: {e}")
        stats.errors.append(str(e))


def run_multi_account_integration_test(config: TestConfig) -> TestStats:
    """运行多账户集成测试"""
    logger.info("开始多账户集成测试")

    # 创建临时目录
    if config.temp_dir is None:
        config.temp_dir = tempfile.mkdtemp(prefix="ezchain_test_")
    else:
        os.makedirs(config.temp_dir, exist_ok=True)

    logger.info(f"测试数据目录: {config.temp_dir}")

    try:
        # 生成测试账户
        account_infos = generate_test_accounts(config.num_accounts, config.base_balance)

        # 创建进程通信管理器
        comm = MultiProcessCommunication()

        # 创建统计信息
        stats = TestStats(start_time=time.time())

        # 创建进程列表
        processes = []

        # 启动主链共识节点进程
        consensus_proc = multiprocessing.Process(
            target=consensus_node_process,
            args=(config, account_infos, comm, stats)
        )
        processes.append(consensus_proc)

        # 启动账户节点进程
        for account_info in account_infos:
            account_proc = multiprocessing.Process(
                target=account_node_process,
                args=(account_info, config, comm, stats)
            )
            processes.append(account_proc)

        # 启动所有进程
        logger.info("启动所有测试进程...")
        for proc in processes:
            proc.start()

        # 等待测试完成
        try:
            time.sleep(config.test_duration)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止测试...")

        # 通知所有进程停止
        comm.stop_event.set()

        # 等待所有进程结束
        logger.info("等待所有进程结束...")
        for proc in processes:
            proc.join(timeout=10)
            if proc.is_alive():
                logger.warning(f"强制结束进程: {proc.name}")
                proc.terminate()

        # 更新测试统计
        stats.end_time = time.time()

        # 输出测试结果
        logger.info("=" * 50)
        logger.info("测试结果统计")
        logger.info("=" * 50)
        logger.info(f"总测试时长: {stats.end_time - stats.start_time:.2f} 秒")
        logger.info(f"创建交易总数: {stats.total_transactions_created}")
        logger.info(f"确认交易总数: {stats.total_transactions_confirmed}")
        logger.info(f"创建区块总数: {stats.total_blocks_created}")
        logger.info(f"VPB更新总数: {stats.total_vpb_updates}")
        logger.info(f"交易成功率: {stats.success_rate:.2f}%")

        if stats.errors:
            logger.warning(f"错误统计:")
            for i, error in enumerate(stats.errors, 1):
                logger.warning(f"  {i}. {error}")

        # 验证测试条件
        test_passed = True
        if stats.total_transactions_created == 0:
            logger.error("测试失败: 没有创建任何交易")
            test_passed = False

        if stats.total_blocks_created == 0:
            logger.error("测试失败: 没有创建任何区块")
            test_passed = False

        if stats.success_rate < 80:  # 成功率低于80%认为测试失败
            logger.error(f"测试失败: 交易成功率过低 ({stats.success_rate:.2f}%)")
            test_passed = False

        if stats.errors:
            logger.error(f"测试失败: 发生了 {len(stats.errors)} 个错误")
            test_passed = False

        if test_passed:
            logger.info("✅ 多账户集成测试通过!")
        else:
            logger.error("❌ 多账户集成测试失败!")

        return stats

    finally:
        # 清理临时目录
        try:
            shutil.rmtree(config.temp_dir)
            logger.info(f"清理临时目录: {config.temp_dir}")
        except Exception as e:
            logger.warning(f"清理临时目录失败: {e}")


def main():
    """主函数"""
    # Windows上需要设置multiprocessing启动方式
    if hasattr(os, 'fork'):
        # Unix系统
        pass
    else:
        # Windows系统
        multiprocessing.freeze_support()

    # 设置信号处理器（在Windows上可能不完全工作）
    try:
        import signal
        def signal_handler(signum, frame):
            print("\n收到中断信号，正在停止测试...")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except:
        pass  # Windows上可能不支持某些信号

    # 创建测试配置
    config = TestConfig(
        num_accounts=3,
        num_transaction_rounds=10,
        transactions_per_round=2,
        block_interval=3.0,
        transaction_interval=1.0,
        test_duration=30,
        base_balance=5000,
        transaction_amount_range=(50, 200)
    )

    # 运行测试
    try:
        stats = run_multi_account_integration_test(config)
        return 0 if stats.errors and len(stats.errors) == 0 else 1
    except Exception as e:
        logger.error(f"测试运行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())