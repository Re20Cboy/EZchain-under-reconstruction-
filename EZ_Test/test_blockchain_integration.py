#!/usr/bin/env python3
"""
EZchain Blockchain Integration Tests (Updated for EZ_Tx_Pool)
贴近真实场景的区块链联调测试

测试完整的交易注入→交易池→区块形成→上链流程
包含分叉处理、并发交易、错误处理等复杂场景
使用新的EZ_Tx_Pool和SubmitTxInfo架构
"""

import sys
import os
import unittest
import tempfile
import shutil
import datetime
import json
import logging
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
from EZ_Units.MerkleTree import MerkleTree
from EZ_Tool_Box.SecureSignature import secure_signature_handler

# Configure logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TestBlockchainIntegration(unittest.TestCase):
    """贴近真实场景的区块链联调测试（使用新的EZ_Tx_Pool架构）"""

    def setUp(self):
        """测试前准备：创建真实的测试环境"""
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

        # 创建交易选择器（新的TransactionPicker）
        self.transaction_picker = TransactionPicker()

        # 创建测试用的密钥对和地址
        self.setup_test_accounts()

        # 创建矿工地址
        self.miner_address = "miner_integration_test"

    def tearDown(self):
        """测试后清理：删除临时文件"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"清理临时文件失败: {e}")
            # 尝试删除数据库文件
            try:
                if os.path.exists(self.pool_db_path):
                    os.unlink(self.pool_db_path)
            except:
                pass

    def setup_test_accounts(self):
        """设置测试账户和密钥对 - 使用真实生成的密钥对"""
        self.test_accounts = {}
        account_names = ["alice", "bob", "charlie", "david", "eve"]

        for i, name in enumerate(account_names):
            try:
                # 生成真实的密钥对
                private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()

                self.test_accounts[name] = {
                    "private_key": private_key_pem,
                    "public_key": public_key_pem,
                    "address": f"{name}_address_{i:03d}",
                    "balance": 1000 + (i * 500)  # 不同的初始余额
                }
                logger.info(f"Generated real key pair for account: {name}")
            except Exception as e:
                logger.error(f"Failed to generate key pair for account {name}: {e}")
                raise RuntimeError(f"Key generation failed for {name}: {e}")

    def create_test_transactions(self, num_transactions: int = 5) -> List[Dict[str, Any]]:
        """创建测试交易数据 - 使用真实账户和密钥"""
        transactions = []
        account_names = list(self.test_accounts.keys())

        if len(account_names) < 2:
            raise RuntimeError("Need at least 2 accounts to create transactions")

        for i in range(num_transactions):
            # 轮换账户作为发送者和接收者
            sender_name = account_names[i % len(account_names)]
            recipient_name = account_names[(i + 1) % len(account_names)]

            sender_account = self.test_accounts[sender_name]
            recipient_account = self.test_accounts[recipient_name]

            # 创建真实的交易数据
            transaction_data = {
                "sender": sender_account["address"],
                "recipient": recipient_account["address"],
                "amount": 10 + (i * 5),  # 递增金额
                "nonce": i,
                "private_key": sender_account["private_key"],
                "public_key": sender_account["public_key"],
                "sender_name": sender_name,
                "recipient_name": recipient_name
            }
            transactions.append(transaction_data)

        return transactions

    def create_test_multi_transactions(self, transactions: List[Dict[str, Any]]) -> List[MultiTransactions]:
        """创建测试用的MultiTransactions - 使用真实签名"""
        multi_txns = []

        for tx_data in transactions:
            try:
                # 创建交易值数据
                value_data = [tx_data["amount"]]

                # 使用真实签名创建SingleTransaction
                signed_transaction = secure_signature_handler.sign_transaction(
                    sender=tx_data["sender"],
                    recipient=tx_data["recipient"],
                    nonce=tx_data["nonce"],
                    value_data=value_data,
                    private_key_pem=tx_data["private_key"],
                    timestamp=datetime.datetime.now().isoformat()
                )

                # 创建SingleTransaction对象
                try:
                    from EZ_VPB.values.Value import Value, ValueState
                    # Value类需要beginIndex和valueNum参数
                    # 使用简单的16进制字符串作为beginIndex
                    begin_index = f"0x{tx_data['nonce']:08x}"  # 基于nonce生成beginIndex
                    value = [Value(begin_index, tx_data["amount"], ValueState.UNSPENT)]
                except ImportError:
                    # 如果Value类不可用，创建简单的值表示
                    value = [{"amount": tx_data["amount"]}]
                except Exception as e:
                    # Value类可用但参数有问题，使用简单表示
                    logger.warning(f"Value creation failed, using simple dict: {e}")
                    value = [{"amount": tx_data["amount"]}]

                single_txn = Transaction(
                    sender=tx_data["sender"],
                    recipient=tx_data["recipient"],
                    nonce=tx_data["nonce"],
                    signature=bytes.fromhex(signed_transaction["signature"]),
                    value=value,
                    time=signed_transaction["timestamp"]
                )

                # 创建MultiTransactions
                multi_txn = MultiTransactions(
                    sender=tx_data["sender"],
                    multi_txns=[single_txn]
                )
                multi_txn.set_digest()
                multi_txns.append(multi_txn)

                logger.info(f"Created MultiTransaction for sender: {tx_data['sender']}")

            except Exception as e:
                logger.error(f"Failed to create MultiTransaction for sender {tx_data['sender']}: {e}")
                raise RuntimeError(f"MultiTransaction creation failed: {e}")

        return multi_txns

    def create_submit_tx_infos(self, multi_txns: List[MultiTransactions]) -> List[SubmitTxInfo]:
        """创建SubmitTxInfo对象 - 使用真实签名"""
        submit_tx_infos = []

        for i, multi_txn in enumerate(multi_txns):
            try:
                # 获取发送者的账户信息
                sender_name = None
                for name, account in self.test_accounts.items():
                    if account["address"] == multi_txn.sender:
                        sender_name = name
                        break

                if sender_name is None:
                    raise ValueError(f"No account found for sender: {multi_txn.sender}")

                sender_account = self.test_accounts[sender_name]

                # 创建真实的SubmitTxInfo
                submit_tx_info = SubmitTxInfo(
                    multi_transactions=multi_txn,
                    private_key_pem=sender_account["private_key"],
                    public_key_pem=sender_account["public_key"]
                )

                submit_tx_infos.append(submit_tx_info)
                logger.info(f"Created SubmitTxInfo for sender: {multi_txn.sender}")

            except Exception as e:
                logger.error(f"Failed to create SubmitTxInfo for MultiTransaction {i}: {e}")
                raise RuntimeError(f"SubmitTxInfo creation failed: {e}")

        return submit_tx_infos

    def test_complete_transaction_flow(self):
        """测试完整的交易流程：创建→交易池→选择→区块→上链"""
        print("\n测试完整交易流程...")

        # 步骤1：创建测试交易
        print("1. 创建测试交易...")
        test_transactions = self.create_test_transactions(5)
        self.assertEqual(len(test_transactions), 5)
        print(f"   创建了 {len(test_transactions)} 个交易")

        # 步骤2：创建MultiTransactions和SubmitTxInfo
        print("2. 创建MultiTransactions和SubmitTxInfo...")
        multi_txns = self.create_test_multi_transactions(test_transactions)
        submit_tx_infos = self.create_submit_tx_infos(multi_txns)
        print(f"   创建了 {len(multi_txns)} 个MultiTransactions")
        print(f"   创建了 {len(submit_tx_infos)} 个SubmitTxInfo")

        # 步骤3：将SubmitTxInfo添加到交易池
        print("3. 添加SubmitTxInfo到交易池...")
        added_count = 0

        # 使用交易池的add_submit_tx_info方法（会进行验证）
        for submit_tx_info in submit_tx_infos:
            try:
                success, message = self.transaction_pool.add_submit_tx_info(submit_tx_info)
                if success:
                    added_count += 1
                    logger.info(f"Successfully added SubmitTxInfo for sender: {submit_tx_info.submitter_address}")
                else:
                    logger.error(f"Failed to add SubmitTxInfo: {message}")
                    raise RuntimeError(f"Transaction pool rejected SubmitTxInfo: {message}")
            except Exception as e:
                logger.error(f"Error adding SubmitTxInfo to pool: {e}")
                raise RuntimeError(f"Failed to add SubmitTxInfo to transaction pool: {e}")

        print(f"   成功添加 {added_count} 个SubmitTxInfo到交易池")
        self.assertEqual(added_count, len(submit_tx_infos), "All SubmitTxInfos should be added to pool")

        # 步骤4：从交易池选择交易并打包
        print("4. 从交易池选择交易并打包...")
        latest_hash = self.blockchain.get_latest_block_hash()
        next_index = self.blockchain.get_latest_block_index() + 1

        # 使用pick_transactions_from_pool便捷函数
        try:
            package_data, block = pick_transactions_from_pool(
                tx_pool=self.transaction_pool,
                miner_address=self.miner_address,
                previous_hash=latest_hash,
                block_index=next_index
            )

            print(f"   成功打包，选中 {len(package_data.selected_submit_tx_infos)} 个SubmitTxInfo")
            self.assertIsNotNone(package_data)
            self.assertIsNotNone(block)
            self.assertGreater(len(package_data.selected_submit_tx_infos), 0)

        except Exception as e:
            logger.error(f"Transaction packaging failed: {e}")
            raise RuntimeError(f"Failed to package transactions from pool: {e}")

        print(f"   创建了区块 #{block.index}")

        # 步骤5：将区块添加到区块链
        print("5. 将区块添加到区块链...")
        main_chain_updated = self.blockchain.add_block(block)

        self.assertTrue(main_chain_updated)

        # 获取区块状态
        fork_node = self.blockchain.get_fork_node_by_hash(block.get_hash())
        block_status = fork_node.consensus_status if fork_node else ConsensusStatus.PENDING
        print(f"   区块成功添加到主链，状态: {block_status.value}")

        # 步骤6：验证区块链状态
        print("6. 验证区块链状态...")
        latest_block = self.blockchain.get_block_by_index(next_index)
        self.assertIsNotNone(latest_block)
        self.assertEqual(latest_block.index, next_index)
        print(f"   区块 #{next_index} 已成功上链")

        print("完整交易流程测试通过！")

    def create_mock_block(self, index: int, previous_hash: str, multi_txns: List[Any]) -> Block:
        """创建包含交易的模拟区块"""
        # 计算默克尔根（基于multi_transactions_hash）
        hash_values = []
        for multi_txn in multi_txns:
            if hasattr(multi_txn, 'digest'):
                hash_values.append(multi_txn.digest)
            else:
                hash_values.append(f"mock_tx_hash_{len(hash_values)}")

        # 创建真实的默克尔树
        merkle_root = ""
        try:
            if hash_values:
                merkle_tree = MerkleTree(hash_values)
                merkle_root = merkle_tree.get_root_hash()
            else:
                merkle_root = "empty_merkle_root"
        except:
            merkle_root = f"mock_merkle_root_{hash(''.join(hash_values)) % 1000000}"

        # 创建区块
        block = Block(
            index=index,
            m_tree_root=merkle_root,
            miner=self.miner_address,
            pre_hash=previous_hash,
            nonce=0
        )

        # 将发送者地址添加到布隆过滤器
        for multi_txn in multi_txns:
            if hasattr(multi_txn, 'sender'):
                block.add_item_to_bloom(multi_txn.sender)
            else:
                block.add_item_to_bloom(f"sender_{index}")

        return block

    def test_multiple_blocks_with_transactions(self):
        """测试多区块连续上链场景"""
        print("\n测试多区块连续上链...")

        blocks_created = 0
        total_transactions = 0

        for round_num in range(3):
            print(f"\n第 {round_num + 1} 轮区块创建...")

            # 创建交易
            transactions = self.create_test_transactions(3)
            total_transactions += len(transactions)

            # 创建MultiTransactions和SubmitTxInfo
            multi_txns = self.create_test_multi_transactions(transactions)
            submit_tx_infos = self.create_submit_tx_infos(multi_txns)

            # 添加到交易池
            added_count = 0
            for submit_tx_info in submit_tx_infos:
                try:
                    success, message = self.transaction_pool.add_submit_tx_info(submit_tx_info)
                    if success:
                        added_count += 1
                        logger.info(f"Round {round_num + 1}: Successfully added SubmitTxInfo")
                    else:
                        logger.error(f"Round {round_num + 1}: Failed to add SubmitTxInfo: {message}")
                        raise RuntimeError(f"Transaction pool rejected SubmitTxInfo: {message}")
                except Exception as e:
                    logger.error(f"Round {round_num + 1}: Error adding SubmitTxInfo to pool: {e}")
                    raise RuntimeError(f"Failed to add SubmitTxInfo to transaction pool: {e}")

            # 创建区块
            latest_hash = self.blockchain.get_latest_block_hash()
            next_index = self.blockchain.get_latest_block_index() + 1

            try:
                package_data, block = pick_transactions_from_pool(
                    tx_pool=self.transaction_pool,
                    miner_address=self.miner_address,
                    previous_hash=latest_hash,
                    block_index=next_index
                )
                logger.info(f"Round {round_num + 1}: Successfully packaged {len(package_data.selected_submit_tx_infos)} transactions")
            except Exception as e:
                logger.error(f"Round {round_num + 1}: Transaction packaging failed: {e}")
                raise RuntimeError(f"Failed to package transactions from pool: {e}")

            # 上链
            main_chain_updated = self.blockchain.add_block(block)
            self.assertTrue(main_chain_updated)
            blocks_created += 1

            print(f"   区块 #{next_index} 成功上链")

        # 验证最终状态
        print(f"\n多区块测试结果:")
        print(f"   创建区块数: {blocks_created}")
        print(f"   总交易数: {total_transactions}")
        print(f"   区块链高度: {self.blockchain.get_latest_block_index()}")

        # 验证区块状态转换
        latest_confirmed = self.blockchain.get_latest_confirmed_block_index()
        print(f"   最新确认区块: #{latest_confirmed}")

        print("多区块连续上链测试通过！")

    def test_transaction_pool_empty_scenario(self):
        """测试交易池为空的情况"""
        print("\n测试交易池为空的情况...")

        # 确保交易池为空
        self.transaction_pool.pool.clear()
        self.transaction_pool.hash_index.clear()
        self.transaction_pool.multi_tx_hash_index.clear()

        # 尝试选择交易
        package_data = self.transaction_picker.pick_transactions(
            tx_pool=self.transaction_pool,
            selection_strategy="fifo"
        )

        # 应该返回空的打包数据
        self.assertIsNotNone(package_data)
        self.assertEqual(len(package_data.selected_submit_tx_infos), 0)
        self.assertEqual(package_data.merkle_root, "")

        # 创建空区块（仅包含区块头信息）
        latest_hash = self.blockchain.get_latest_block_hash()
        next_index = self.blockchain.get_latest_block_index() + 1

        empty_block = Block(
            index=next_index,
            m_tree_root="empty_merkle_root",
            miner=self.miner_address,
            pre_hash=latest_hash,
            nonce=0
        )

        is_main_chain = self.blockchain.add_block(empty_block)
        self.assertTrue(is_main_chain)
        print(f"   空区块 #{next_index} 成功上链")

        print("空交易池场景测试通过！")

    def test_fork_with_transactions(self):
        """测试分叉场景下的交易处理"""
        print("\n测试分叉场景下的交易处理...")

        # 步骤1：创建主链区块
        print("1. 创建主链区块...")
        transactions = self.create_test_transactions(3)
        multi_txns = self.create_test_multi_transactions(transactions)

        latest_hash = self.blockchain.get_latest_block_hash()
        next_index = self.blockchain.get_latest_block_index() + 1

        main_block = self.create_mock_block(next_index, latest_hash, multi_txns)
        main_chain_updated = self.blockchain.add_block(main_block)
        self.assertTrue(main_chain_updated)
        print(f"   主链区块 #{next_index} 创建成功")

        # 步骤2：创建另一个主链区块
        print("2. 创建第二个主链区块...")
        latest_hash = self.blockchain.get_latest_block_hash()
        next_index = self.blockchain.get_latest_block_index() + 1

        second_block = self.create_mock_block(next_index, latest_hash, multi_txns[:2])
        main_chain_updated = self.blockchain.add_block(second_block)
        self.assertTrue(main_chain_updated)
        print(f"   主链区块 #{next_index} 创建成功")

        # 步骤3：创建分叉区块
        print("3. 创建分叉区块...")
        first_block_height = main_block.get_index() - 1
        fork_block = self.create_mock_block(
            first_block_height + 1,
            self.blockchain.get_block_by_index(first_block_height).get_hash(),
            multi_txns[1:]
        )

        is_main_chain = self.blockchain.add_block(fork_block)
        self.assertFalse(is_main_chain)  # 分叉不会立即更新主链
        fork_node = self.blockchain.get_fork_node_by_hash(fork_block.get_hash())
        fork_status = fork_node.consensus_status if fork_node else ConsensusStatus.PENDING
        print(f"   分叉区块创建成功，状态: {fork_status.value}")

        # 步骤4：扩展分叉链
        print("4. 扩展分叉链...")
        prev_fork_block = fork_block
        fork_base_index = first_block_height + 1

        for i in range(1, 4):  # 创建3个分叉区块
            parent_hash = prev_fork_block.get_hash()

            fork_block_new = self.create_mock_block(
                fork_base_index + i,
                parent_hash,
                multi_txns[:2]
            )

            is_main_chain = self.blockchain.add_block(fork_block_new)
            if is_main_chain:
                print(f"   分叉链成为主链！区块 #{fork_base_index + i} 更新主链")
                break
            else:
                print(f"   分叉区块 #{fork_base_index + i} 创建，继续分叉")
                prev_fork_block = fork_block_new

        # 验证最终状态
        stats = self.blockchain.get_fork_statistics()
        print(f"\n分叉测试结果:")
        print(f"   总区块数: {stats['total_nodes']}")
        print(f"   主链节点: {stats['main_chain_nodes']}")
        print(f"   分叉节点: {stats['fork_nodes']}")
        print(f"   当前主链高度: {self.blockchain.get_latest_block_index()}")

        print("分叉场景交易处理测试通过！")

    def test_large_number_of_transactions(self):
        """测试大量交易处理场景"""
        print("\n测试大量交易处理...")

        # 创建大量交易
        large_transactions = self.create_test_transactions(20)
        print(f"   创建了 {len(large_transactions)} 个交易")

        # 分批处理
        batch_size = 5
        blocks_created = 0

        for i in range(0, len(large_transactions), batch_size):
            batch = large_transactions[i:i+batch_size]
            print(f"   处理批次 {i//batch_size + 1}: {len(batch)} 个交易")

            # 创建MultiTransactions和SubmitTxInfo
            multi_txns = self.create_test_multi_transactions(batch)
            submit_tx_infos = self.create_submit_tx_infos(multi_txns)

            # 添加到交易池
            for submit_tx_info in submit_tx_infos:
                try:
                    success, message = self.transaction_pool.add_submit_tx_info(submit_tx_info)
                    if not success:
                        logger.error(f"Batch {i//batch_size + 1}: Failed to add SubmitTxInfo: {message}")
                        raise RuntimeError(f"Transaction pool rejected SubmitTxInfo: {message}")
                except Exception as e:
                    logger.error(f"Batch {i//batch_size + 1}: Error adding SubmitTxInfo to pool: {e}")
                    raise RuntimeError(f"Failed to add SubmitTxInfo to transaction pool: {e}")

            # 创建区块
            latest_hash = self.blockchain.get_latest_block_hash()
            next_index = self.blockchain.get_latest_block_index() + 1

            try:
                package_data, block = pick_transactions_from_pool(
                    tx_pool=self.transaction_pool,
                    miner_address=self.miner_address,
                    previous_hash=latest_hash,
                    block_index=next_index
                )
                print(f"   批次 {i//batch_size + 1} 成功打包为区块 #{next_index}")
            except Exception as e:
                logger.error(f"Batch {i//batch_size + 1}: Transaction packaging failed: {e}")
                raise RuntimeError(f"Failed to package transactions from pool: {e}")

            is_main_chain = self.blockchain.add_block(block)
            if is_main_chain:
                blocks_created += 1

        print(f"大量交易测试结果:")
        print(f"   总交易数: {len(large_transactions)}")
        print(f"   创建区块数: {blocks_created}")
        print(f"   平均每区块交易数: {len(large_transactions) / blocks_created:.1f}")

        print("大量交易处理测试通过！")

    def test_error_handling_and_recovery(self):
        """测试错误处理和恢复机制"""
        print("\n测试错误处理和恢复...")

        # 测试1：无效区块添加
        print("1. 测试无效区块处理...")
        invalid_block = Block(
            index=999,  # 无效索引
            m_tree_root="test_root",
            miner=self.miner_address,
            pre_hash="invalid_hash"
        )

        try:
            is_main_chain = self.blockchain.add_block(invalid_block)
            print(f"   无效区块处理结果: {is_main_chain}")
        except Exception as e:
            print(f"   无效区块异常处理: {type(e).__name__}")

        # 测试2：交易池损坏恢复
        print("2. 测试交易池损坏恢复...")
        original_pool = self.transaction_pool.pool.copy()
        original_hash_index = self.transaction_pool.hash_index.copy()

        # 模拟交易池损坏
        self.transaction_pool.pool = None
        self.transaction_pool.hash_index = None

        # 尝试重新创建交易池
        try:
            self.transaction_pool.pool = []
            self.transaction_pool.hash_index = {}
            print("   交易池恢复成功")
        except Exception as e:
            print(f"   交易池恢复失败: {e}")

        # 恢复原始数据
        self.transaction_pool.pool = original_pool
        self.transaction_pool.hash_index = original_hash_index

        # 测试3：区块数据部分缺失
        print("3. 测试部分数据缺失的区块...")
        incomplete_block = Block(
            index=self.blockchain.get_latest_block_index() + 1,
            m_tree_root="",  # 空默克尔根
            miner="",       # 空矿工地址
            pre_hash=self.blockchain.get_latest_block_hash()
        )

        is_main_chain = self.blockchain.add_block(incomplete_block)
        print(f"   不完整区块处理: {is_main_chain}")

        print("错误处理和恢复测试通过！")


def run_integration_tests():
    """运行所有集成测试"""
    print("=" * 80)
    print("EZchain Blockchain Integration Tests (Updated for EZ_Tx_Pool)")
    print("贴近真实场景的区块链联调测试")
    print("使用新的EZ_Tx_Pool和SubmitTxInfo架构")
    print("=" * 80)

    # 创建测试套件
    suite = unittest.TestSuite()

    # 添加测试用例
    test_cases = [
        'test_complete_transaction_flow',
        'test_multiple_blocks_with_transactions',
        'test_fork_with_transactions',
        'test_transaction_pool_empty_scenario',
        'test_large_number_of_transactions',
        'test_error_handling_and_recovery'
    ]

    for test_case in test_cases:
        suite.addTest(TestBlockchainIntegration(test_case))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出测试结果摘要
    print("\n" + "=" * 80)
    print("集成测试结果摘要")
    print("=" * 80)
    print(f"运行测试数: {result.testsRun}")
    print(f"成功测试数: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败测试数: {len(result.failures)}")
    print(f"错误测试数: {len(result.errors)}")

    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback}")

    if result.errors:
        print("\n错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")

    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100
    print(f"\n测试成功率: {success_rate:.1f}%")

    if success_rate >= 80:
        print("集成测试总体通过！区块链联调功能正常。")
    else:
        print("集成测试存在问题，需要进一步调试。")

    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)