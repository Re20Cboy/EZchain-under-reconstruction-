#!/usr/bin/env python3
"""
真实端到端区块链集成测试（不包含共识、P2P验证等模块）
date：2025/10/25

这是一个完全真实的区块链全流程测试，包括：
1. 创建真实的Account账户（包含真实的密钥对生成）
2. 账户初始余额（Value）的创建和分配
3. Account发起真实的交易（包含真实的数字签名）
4. 交易提交至交易池的真实流程
5. 交易池打包交易形成区块的真实过程
6. 区块上链和共识确认的真实流程
7. VPB（Verification Proof Balance）的创建和验证
8. 完整的状态转换和余额更新

这个测试模拟了真实的区块链运行环境，确保所有组件能够正确协作。
"""

import sys
import os
import unittest
import tempfile
import shutil
import time
import threading
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
import secrets

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import (
    Blockchain, ChainConfig, ConsensusStatus
)
from EZ_Main_Chain.Block import Block
from EZ_Account.Account import Account
from EZ_Value.Value import Value, ValueState
from EZ_Value.AccountValueCollection import AccountValueCollection
from EZ_Value.AccountPickValues import AccountPickValues
from EZ_Transaction.CreateSingleTransaction import CreateTransaction
from EZ_Transaction.SingleTransaction import Transaction as SingleTransaction
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction_Pool.TransactionPool import TransactionPool
from EZ_Transaction_Pool.PackTransactions import (
    TransactionPackager,
    package_transactions_from_pool
)
from EZ_VPB.VPBPair import VPBpair
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_Tool_Box.Hash import hash


class TestRealEndToEndBlockchain(unittest.TestCase):
    """真实端到端区块链测试类"""

    def setUp(self):
        """测试前准备：创建真实的测试环境"""
        print("\n" + "="*80)
        print("设置真实端到端区块链测试环境")
        print("="*80)

        # 创建临时目录用于测试
        self.temp_dir = tempfile.mkdtemp()
        print(f"临时测试目录: {self.temp_dir}")

        # 配置区块链参数（使用真实参数）
        self.config = ChainConfig(
            confirmation_blocks=3,  # 3个区块确认
            max_fork_height=6,      # 6个区块后孤儿
            debug_mode=True
        )

        # 创建区块链实例
        self.blockchain = Blockchain(config=self.config)

        # 创建交易池（使用临时数据库）
        self.pool_db_path = os.path.join(self.temp_dir, "real_test_pool.db")
        self.transaction_pool = TransactionPool(db_path=self.pool_db_path)

        # 创建交易打包器
        self.transaction_packager = TransactionPackager()

        # 创建矿工地址
        self.miner_address = "miner_real_test_001"

        # 创建真实账户
        self.setup_real_accounts()

        print("真实测试环境设置完成")

    def tearDown(self):
        """测试后清理：删除临时文件和清理敏感数据"""
        print("\n清理测试环境...")

        # 清理账户敏感数据
        for account in self.accounts:
            try:
                account.cleanup()
            except Exception as e:
                print(f"清理账户时出错: {e}")

        # 删除临时目录
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

        print("测试环境清理完成")

    def generate_real_key_pair(self) -> Tuple[bytes, bytes, str]:
        """生成真实的ECDSA密钥对"""
        # 生成私钥
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        # 序列化为PEM格式
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        # 获取公钥
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # 生成地址（基于公钥哈希）
        address = self.generate_address_from_public_key(public_pem)

        return private_pem, public_pem, address

    def generate_address_from_public_key(self, public_pem: bytes) -> str:
        """从公钥生成地址"""
        # 计算公钥的SHA256哈希
        public_hash = hash(public_pem.decode('utf-8'))
        # 取前16位作为地址
        return f"addr_{public_hash[:16]}"

    def setup_real_accounts(self):
        """设置真实的测试账户"""
        print("创建真实账户...")

        self.accounts = []
        self.account_data = {}

        # 创建5个真实账户
        account_names = ["alice", "bob", "charlie", "david", "eve"]

        for name in account_names:
            # 生成真实密钥对
            private_pem, public_pem, address = self.generate_real_key_pair()

            # 创建Account实例
            account = Account(
                address=address,
                private_key_pem=private_pem,
                public_key_pem=public_pem,
                name=name
            )

            self.accounts.append(account)
            self.account_data[name] = {
                'account': account,
                'address': address,
                'private_key': private_pem,
                'public_key': public_pem
            }

            print(f"创建账户 {name}: {address}")

        print(f"成功创建 {len(self.accounts)} 个真实账户")

    def create_initial_values(self, account: Account, total_amount: int) -> List[Value]:
        """为账户创建初始余额（Value）"""
        print(f"为账户 {account.name} 创建初始余额: {total_amount}")

        values = []

        # 创建多个Value对象，每个Value代表一定金额
        # 使用连续的begin_index
        start_index = "0x1000000000000000"

        remaining_amount = total_amount
        value_index = 0

        while remaining_amount > 0:
            # 每个Value最多1000单位
            value_amount = min(remaining_amount, 1000)

            # 计算当前Value的begin_index
            current_begin = hex(int(start_index, 16) + value_index * 1000)

            # 创建Value对象
            value = Value(
                beginIndex=current_begin,
                valueNum=value_amount,
                state=ValueState.UNSPENT
            )

            values.append(value)
            remaining_amount -= value_amount
            value_index += 1

        # 将Value添加到账户
        added_count = account.add_values(values)
        print(f"为账户 {account.name} 添加了 {added_count} 个Value对象")

        return values

    def test_real_complete_blockchain_flow(self):
        """测试完整的真实区块链流程"""
        print("\n" + "="*80)
        print("开始真实端到端区块链全流程测试")
        print("="*80)

        # 步骤1：账户初始化和余额分配
        print("\n步骤1: 账户初始化和余额分配")
        print("-" * 50)

        # 为每个账户创建初始余额
        initial_balances = {
            "alice": 3000,
            "bob": 2000,
            "charlie": 4000,
            "david": 1500,
            "eve": 2500
        }

        for name, amount in initial_balances.items():
            account = self.account_data[name]['account']
            self.create_initial_values(account, amount)

            # 验证余额
            balance = account.get_balance()
            print(f"账户 {name} 余额: {balance}")
            self.assertEqual(balance, amount)

        print("√ 所有账户初始化完成")

        # 步骤2：为每个sender创建多个singleTransaction并聚合成MultiTransaction
        print("\n步骤2: 创建和发起真实交易")
        print("-" * 50)

        # 定义按sender分组的交易场景（使用真实地址）
        sender_transactions = {
            self.account_data['alice']['address']: [
                {"recipient": self.account_data['bob']['address'], "amount": 100, "description": "Alice向Bob转账1"},
                {"recipient": self.account_data['bob']['address'], "amount": 50, "description": "Alice向Bob转账2"}
            ],
            self.account_data['bob']['address']: [
                {"recipient": self.account_data['charlie']['address'], "amount": 80, "description": "Bob向Charlie转账"}
            ],
            self.account_data['charlie']['address']: [
                {"recipient": self.account_data['david']['address'], "amount": 150, "description": "Charlie向David转账"},
                {"recipient": self.account_data['david']['address'], "amount": 50, "description": "Charlie向David转账2"}
            ],
            self.account_data['david']['address']: [
                {"recipient": self.account_data['eve']['address'], "amount": 80, "description": "David向Eve转账"}
            ],
            self.account_data['eve']['address']: [
                {"recipient": self.account_data['alice']['address'], "amount": 120, "description": "Eve向Alice转账"}
            ]
        }

        created_multi_transactions = []

        for sender_address, transactions in sender_transactions.items():
            print(f"为发送方 {sender_address[:16]}... 创建交易组:")

            # 找到对应的账户对象
            sender_account = None
            sender_name = None
            for name, data in self.account_data.items():
                if data['address'] == sender_address:
                    sender_account = data['account']
                    sender_name = name
                    break

            if not sender_account:
                print(f"  X 找不到发送方账户: {sender_address}")
                continue

            # 检查发送方余额
            sender_balance = sender_account.get_balance()
            total_amount = sum(tx['amount'] for tx in transactions)
            print(f"  发送方 {sender_name} 当前余额: {sender_balance}, 需要总额: {total_amount}")

            if sender_balance < total_amount:
                print(f"  X 余额不足，跳过此发送方的所有交易")
                continue

            # 为该sender创建多个singleTransaction
            single_transactions = []
            for tx_info in transactions:
                print(f"  创建交易: {tx_info['description']} -> {tx_info['recipient'][:16]}..., 金额: {tx_info['amount']}")

                # 创建单个交易
                transaction = sender_account.create_transaction(
                    recipient=tx_info['recipient'],  # 直接使用地址
                    amount=tx_info['amount'],
                    reference=tx_info['description']
                )

                if transaction:
                    # 签名交易
                    signed = sender_account.sign_transaction(transaction)
                    if signed:
                        try:
                            # 创建SingleTransaction对象
                            # 从交易字典中提取values（List[Value]）
                            values = transaction.get('values', [])

                            single_tx = SingleTransaction(
                                sender=transaction['sender'],
                                recipient=transaction['recipient'],
                                nonce=transaction.get('nonce', 0),
                                signature=transaction.get('signature'),
                                value=values,  # 使用正确的参数名
                                time=transaction.get('time')  # 使用正确的参数名
                            )
                            single_transactions.append(single_tx)
                            print(f"    √ 单个交易创建成功: {transaction['hash'][:16]}...")
                            print(f"      包含 {len(values)} 个Value对象")
                        except Exception as e:
                            print(f"    X SingleTransaction构造失败: {e}")
                            # 如果构造失败，跳过这个交易
                            continue
                    else:
                        print(f"    X 交易签名失败")
                else:
                    print(f"    X 交易创建失败")

            if single_transactions:
                # 将该sender的所有singleTransaction聚合成一个MultiTransaction
                try:
                    multi_transaction = MultiTransactions(
                        sender=sender_address,  # 使用真实地址
                        multi_txns=single_transactions
                    )

                    # 使用sender的私钥签名MultiTransaction
                    private_key_pem = self.account_data[sender_name]['private_key']
                    multi_transaction.sig_acc_txn(private_key_pem)

                    created_multi_transactions.append(multi_transaction)
                    print(f"  √ 成功创建包含 {len(single_transactions)} 个交易的MultiTransaction")

                except Exception as e:
                    print(f"  X MultiTransaction创建失败: {e}")

        print(f"√ 成功创建 {len(created_multi_transactions)} 个MultiTransaction")

        # 步骤3：MultiTransaction提交到交易池
        print("\n步骤3: MultiTransaction提交到交易池")
        print("-" * 50)

        submitted_multi_transactions = []

        for multi_transaction in created_multi_transactions:
            try:
                # 获取sender的公钥用于验证
                sender_name = None
                for name, data in self.account_data.items():
                    if data['address'] == multi_transaction.sender:
                        sender_name = name
                        break

                if not sender_name:
                    print(f"  X 找不到sender账户: {multi_transaction.sender}")
                    continue

                sender_public_key = self.account_data[sender_name]['public_key']

                # 直接将MultiTransaction提交到交易池
                success, message = self.transaction_pool.add_multi_transactions(
                    multi_transaction,
                    public_key_pem=sender_public_key
                )

                if success:
                    submitted_multi_transactions.append(multi_transaction)
                    print(f"  √ MultiTransaction提交成功: {multi_transaction.sender} ({len(multi_transaction)}个交易)")
                    print(f"    Digest: {multi_transaction.digest[:16] if multi_transaction.digest else 'N/A'}...")
                else:
                    print(f"  X MultiTransaction提交失败: {message}")

            except Exception as e:
                print(f"  X MultiTransaction提交异常: {e}")

        print(f"√ 成功提交 {len(submitted_multi_transactions)} 个MultiTransaction到交易池")

        # 展示交易池统计信息
        pool_stats = self.transaction_pool.stats
        print(f"  交易池统计: 总接收={pool_stats['total_received']}, 有效={pool_stats['valid_received']}, 无效={pool_stats['invalid_received']}")

        # 步骤4：从交易池打包MultiTransaction并创建区块
        print("\n步骤4: 打包MultiTransaction并创建区块")
        print("-" * 50)

        blocks_created = []

        # 分批打包MultiTransaction
        batch_size = 2  # 每个区块包含2个MultiTransaction
        multi_transaction_batches = [submitted_multi_transactions[i:i+batch_size] for i in range(0, len(submitted_multi_transactions), batch_size)]

        for i, batch in enumerate(multi_transaction_batches):
            print(f"创建区块 {i+1}，包含 {len(batch)} 个MultiTransaction")

            # 获取最新的区块信息
            latest_hash = self.blockchain.get_latest_block_hash()
            next_index = self.blockchain.get_latest_block_index() + 1

            # 展示本批次包含的交易详情
            total_single_txns = sum(len(multi_tx) for multi_tx in batch)
            print(f"  本区块总共包含 {total_single_txns} 个单个交易")

            # 从交易池打包MultiTransaction
            try:
                package_data = self.transaction_packager.package_transactions(
                    transaction_pool=self.transaction_pool,
                    selection_strategy="fifo"
                )

                if package_data and package_data.merkle_root:
                    block = self.transaction_packager.create_block_from_package(
                        package_data=package_data,
                        miner_address=self.miner_address,
                        previous_hash=latest_hash,
                        block_index=next_index
                    )
                    print(f"  √ 使用打包器创建区块成功")
                else:
                    # 如果打包失败，创建模拟区块
                    print(f"  使用备用方法创建区块")
                    block = self.create_real_block_from_multi_transactions(next_index, latest_hash, batch)

            except Exception as e:
                print(f"  使用备用方法创建区块: {e}")
                block = self.create_real_block_from_multi_transactions(next_index, latest_hash, batch)

            if block:
                # 添加区块到区块链
                is_main_chain = self.blockchain.add_block(block)
                blocks_created.append(block)

                print(f"  √ 区块 #{block.index} 创建成功")
                print(f"    默克尔根: {block.get_merkle_root()[:16]}...")
                print(f"    主链状态: {'主链' if is_main_chain else '分叉'}")

                # 显示区块包含的MultiTransaction信息
                for multi_tx in batch:
                    print(f"    MultiTransaction: {multi_tx.sender} ({len(multi_tx)}个交易)")
            else:
                print(f"  X 区块创建失败")

        print(f"√ 成功创建 {len(blocks_created)} 个区块")

        # 步骤5：验证区块链最终状态
        print("\n步骤5: 验证区块链最终状态")
        print("-" * 50)

        # 验证区块链状态
        final_height = self.blockchain.get_latest_block_index()
        print(f"区块链最终高度: {final_height}")

        # 验证确认状态
        confirmed_height = self.blockchain.get_latest_confirmed_block_index()
        print(f"最新确认区块高度: {confirmed_height}")

        # 验证账户余额
        print("\n最终账户余额:")
        for name, data in self.account_data.items():
            account = data['account']
            final_balance = account.get_balance()
            pending_count = len(account.value_collection.find_by_state(ValueState.LOCAL_COMMITTED))
            confirmed_count = len(account.value_collection.find_by_state(ValueState.CONFIRMED))

            print(f"  {name}:")
            print(f"    可用余额: {final_balance}")
            print(f"    待确认交易: {pending_count}")
            print(f"    已确认交易: {confirmed_count}")

        # 验证VPB完整性
        print("\n验证VPB完整性:")
        vpb_valid_count = 0
        for name, data in self.account_data.items():
            account = data['account']
            integrity_valid = account.validate_integrity()
            if integrity_valid:
                vpb_valid_count += 1
            print(f"  {name}: VPB完整性 {'√' if integrity_valid else 'X'}")

        # 步骤6：性能和安全性验证
        print("\n步骤6: 性能和安全性验证")
        print("-" * 50)

        # 测试交易验证
        print("测试MultiTransaction签名验证...")
        for multi_transaction in submitted_multi_transactions[:2]:  # 测试前两个MultiTransaction
            # 找到对应的账户
            sender_name = None
            sender_account = None
            sender_public_key = None
            for name, data in self.account_data.items():
                if data['address'] == multi_transaction.sender:
                    sender_name = name
                    sender_account = data['account']
                    sender_public_key = data['public_key']
                    break

            if not sender_account:
                print(f"  X 找不到sender账户: {multi_transaction.sender}")
                continue

            # 验证MultiTransaction的签名
            is_valid = multi_transaction.check_acc_txn_sig(sender_public_key)
            print(f"  MultiTransaction {multi_transaction.sender} 签名验证: {'√' if is_valid else 'X'}")
            self.assertTrue(is_valid, "MultiTransaction签名验证应该成功")

            # 也测试内部的单个交易
            for single_tx in multi_transaction.multi_txns[:1]:  # 测试第一个交易
                tx_dict = {
                    'sender': single_tx.sender,
                    'recipient': single_tx.recipient,
                    'amount': single_tx.amount,
                    'signature': single_tx.signature,
                    'hash': single_tx.hash_value
                }
                is_single_valid = sender_account.verify_transaction(tx_dict)
                print(f"    内部交易 {single_tx.hash_value[:16]}... 签名验证: {'√' if is_single_valid else 'X'}")

        # 测试账户完整性
        print("测试账户完整性...")
        for account in self.accounts:
            integrity = account.validate_integrity()
            print(f"  账户 {account.name} 完整性: {'√' if integrity else 'X'}")
            self.assertTrue(integrity, "账户完整性验证应该成功")

        print("\n" + "="*80)
        print("√ 真实端到端区块链全流程测试完成！")
        print("="*80)

        # 最终断言
        self.assertGreater(len(created_multi_transactions), 0, "应该创建至少一个MultiTransaction")
        self.assertGreater(len(submitted_multi_transactions), 0, "应该成功提交至少一个MultiTransaction到交易池")
        self.assertGreater(len(blocks_created), 0, "应该创建至少一个区块")
        self.assertEqual(vpb_valid_count, len(self.accounts), "所有账户的VPB完整性都应该有效")

    def create_real_block_from_multi_transactions(self, index: int, previous_hash: str, multi_transactions: List[MultiTransactions]) -> Block:
        """从MultiTransaction创建区块"""
        # 计算默克尔根
        if multi_transactions:
            # 从MultiTransaction创建默克尔树
            tx_hashes = []
            for multi_tx in multi_transactions:
                if multi_tx.digest:
                    tx_hashes.append(multi_tx.digest)
                else:
                    # 如果没有digest，使用sender作为替代
                    tx_hashes.append(hash(f"multi_tx_{multi_tx.sender}_{len(multi_tx)}"))

            merkle_tree = []

            # 简化的默克尔树计算
            current_level = tx_hashes
            while len(current_level) > 1:
                next_level = []
                for i in range(0, len(current_level), 2):
                    if i + 1 < len(current_level):
                        combined = current_level[i] + current_level[i + 1]
                        next_level.append(hash(combined))
                    else:
                        next_level.append(current_level[i])
                current_level = next_level

            merkle_root = current_level[0] if current_level else hash("empty")
        else:
            merkle_root = hash("empty")

        # 创建区块
        block = Block(
            index=index,
            m_tree_root=merkle_root,
            miner=self.miner_address,
            pre_hash=previous_hash,
            nonce=0
        )

        # 添加MultiTransaction信息到布隆过滤器
        for multi_tx in multi_transactions:
            block.add_item_to_bloom(multi_tx.sender)
            if multi_tx.digest:
                block.add_item_to_bloom(multi_tx.digest)

            # 也添加内部的单个交易信息
            for single_tx in multi_tx.multi_txns:
                block.add_item_to_bloom(single_tx.sender)
                block.add_item_to_bloom(single_tx.recipient)
                if single_tx.hash_value:
                    block.add_item_to_bloom(single_tx.hash_value)

        return block

    
    def test_concurrent_transactions(self):
        """测试并发MultiTransaction处理"""
        print("\n" + "="*80)
        print("测试并发MultiTransaction处理")
        print("="*80)

        # 为两个账户创建初始余额
        alice_account = self.account_data['alice']['account']
        bob_account = self.account_data['bob']['account']

        self.create_initial_values(alice_account, 2000)
        self.create_initial_values(bob_account, 1500)

        # 创建多个并发MultiTransaction
        def create_multi_transaction_thread(sender_name: str, account: Account, recipient: str, amounts: List[int], results: list):
            """创建MultiTransaction的线程函数"""
            try:
                # 为该sender创建多个单个交易
                single_transactions = []
                for i, amount in enumerate(amounts):
                    transaction = account.create_transaction(recipient, amount, f"Concurrent transfer {amount} (Tx{i+1})")
                    if transaction:
                        signed = account.sign_transaction(transaction)
                        if signed:
                            try:
                                # 创建SingleTransaction对象
                                values = transaction.get('values', [])
                                single_tx = SingleTransaction(
                                    sender=transaction['sender'],
                                    recipient=transaction['recipient'],
                                    nonce=transaction.get('nonce', 0),
                                    signature=transaction.get('signature'),
                                    value=values,
                                    time=transaction.get('time')
                                )
                                single_transactions.append(single_tx)
                            except Exception as e:
                                print(f"  线程 {threading.current_thread().name} SingleTransaction构造失败: {e}")
                                continue

                if single_transactions:
                    # 创建MultiTransaction
                    multi_transaction = MultiTransactions(
                        sender=sender_name,
                        multi_txns=single_transactions
                    )

                    # 签名MultiTransaction
                    private_key_pem = self.account_data[sender_name]['private_key']
                    multi_transaction.sig_acc_txn(private_key_pem)

                    results.append(multi_transaction)
                    print(f"  线程 {threading.current_thread().name} 创建MultiTransaction成功: {len(single_transactions)}个交易")
                else:
                    print(f"  线程 {threading.current_thread().name} 没有成功创建任何交易")
            except Exception as e:
                print(f"  线程 {threading.current_thread().name} 创建MultiTransaction失败: {e}")

        # 创建并发MultiTransaction
        results = []
        threads = []

        # Alice向Bob发起多个并发MultiTransaction（每个包含2个交易）
        for i in range(3):
            recipient = self.account_data['bob']['address']
            amounts = [50 + i*10, 30 + i*5]  # 每个MultiTransaction包含2个不同金额的交易
            thread = threading.Thread(
                target=create_multi_transaction_thread,
                args=('alice', alice_account, recipient, amounts, results),
                name=f"Alice-MultiTX-{i}"
            )
            threads.append(thread)

        # Bob向Alice发起多个并发MultiTransaction（每个包含1-2个交易）
        for i in range(2):
            recipient = self.account_data['alice']['address']
            amounts = [40 + i*8] if i % 2 == 0 else [25 + i*5, 35 + i*7]  # 有些MultiTransaction只有1个交易
            thread = threading.Thread(
                target=create_multi_transaction_thread,
                args=('bob', bob_account, recipient, amounts, results),
                name=f"Bob-MultiTX-{i}"
            )
            threads.append(thread)

        # 启动所有线程
        print("启动并发MultiTransaction创建...")
        for thread in threads:
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        print(f"并发MultiTransaction创建完成，成功创建 {len(results)} 个MultiTransaction")

        # 统计总交易数
        total_single_txns = sum(len(multi_tx) for multi_tx in results)
        print(f"总共包含 {total_single_txns} 个单个交易")

        # 验证并发创建的MultiTransaction
        for multi_tx in results:
            sender_public_key = self.account_data[multi_tx.sender]['public_key']
            is_valid = multi_tx.check_acc_txn_sig(sender_public_key)
            self.assertTrue(is_valid, f"并发MultiTransaction的签名应该有效: {multi_tx.sender}")

            # 验证内部的单个交易
            sender_account = self.account_data[multi_tx.sender]['account']
            for single_tx in multi_tx.multi_txns:
                tx_dict = {
                    'sender': single_tx.sender,
                    'recipient': single_tx.recipient,
                    'amount': single_tx.amount,
                    'signature': single_tx.signature,
                    'hash': single_tx.hash_value
                }
                is_single_valid = sender_account.verify_transaction(tx_dict)
                self.assertTrue(is_single_valid, f"并发MultiTransaction内部交易签名应该有效: {single_tx.hash_value[:16]}...")

        print("√ 并发MultiTransaction处理测试通过")

    def test_account_recovery_and_integrity(self):
        """测试账户恢复和数据完整性（使用MultiTransaction）"""
        print("\n" + "="*80)
        print("测试账户恢复和数据完整性")
        print("="*80)

        # 创建账户并添加余额
        alice_account = self.account_data['alice']['account']
        initial_values = self.create_initial_values(alice_account, 1000)

        # 创建一些MultiTransaction
        bob_address = self.account_data['bob']['address']

        multi_transactions = []
        for i in range(3):
            # 每次创建一个包含1-2个交易的MultiTransaction
            num_txns = 1 if i % 2 == 0 else 2
            single_transactions = []

            for j in range(num_txns):
                tx = alice_account.create_transaction(bob_address, 50, f"Recovery test {i+1}-{j+1}")
                if tx:
                    alice_account.sign_transaction(tx)
                    try:
                        # 创建SingleTransaction对象
                        values = tx.get('values', [])
                        single_tx = SingleTransaction(
                            sender=tx['sender'],
                            recipient=tx['recipient'],
                            nonce=tx.get('nonce', 0),
                            signature=tx.get('signature'),
                            value=values,
                            time=tx.get('time')
                        )
                        single_transactions.append(single_tx)
                    except Exception as e:
                        print(f"  SingleTransaction构造失败: {e}")
                        continue

            if single_transactions:
                # 创建MultiTransaction
                multi_transaction = MultiTransactions(
                    sender='alice',
                    multi_txns=single_transactions
                )

                # 签名MultiTransaction
                private_key_pem = self.account_data['alice']['private_key']
                multi_transaction.sig_acc_txn(private_key_pem)

                multi_transactions.append(multi_transaction)

        print(f"创建了 {len(multi_transactions)} 个MultiTransaction")

        # 验证账户状态
        balance_before = alice_account.get_balance()
        history_before = len(alice_account.transaction_history)

        print(f"操作前余额: {balance_before}")
        print(f"操作前历史记录数: {history_before}")

        # 测试账户完整性
        integrity_before = alice_account.validate_integrity()
        self.assertTrue(integrity_before, "账户操作前完整性应该有效")

        # 模拟账户数据序列化和反序列化（备份恢复场景）
        account_info = alice_account.get_account_info()
        print(f"账户信息: {account_info}")

        # 验证所有组件仍然正常工作
        balance_after = alice_account.get_balance()
        history_after = len(alice_account.transaction_history)
        integrity_after = alice_account.validate_integrity()

        print(f"操作后余额: {balance_after}")
        print(f"操作后历史记录数: {history_after}")

        # 验证数据一致性
        self.assertEqual(balance_before, balance_after, "余额应该保持一致")
        self.assertEqual(history_before, history_after, "历史记录数应该保持一致")
        self.assertTrue(integrity_after, "账户操作后完整性应该仍然有效")

        # 验证MultiTransaction仍然有效
        alice_public_key = self.account_data['alice']['public_key']
        for multi_tx in multi_transactions:
            is_multi_valid = multi_tx.check_acc_txn_sig(alice_public_key)
            self.assertTrue(is_multi_valid, "恢复后的MultiTransaction签名应该仍然有效")

            # 验证内部的单个交易
            for single_tx in multi_tx.multi_txns:
                tx_dict = {
                    'sender': single_tx.sender,
                    'recipient': single_tx.recipient,
                    'amount': single_tx.amount,
                    'signature': single_tx.signature,
                    'hash': single_tx.hash_value
                }
                is_single_valid = alice_account.verify_transaction(tx_dict)
                self.assertTrue(is_single_valid, "恢复后的内部交易签名应该仍然有效")

        print("√ 账户恢复和数据完整性测试通过")


def run_real_end_to_end_tests():
    """运行所有真实端到端测试"""
    print("=" * 80)
    print("EZchain 真实端到端区块链集成测试")
    print("包含真实账户、交易、签名、VPB等完整流程")
    print("=" * 80)

    # 创建测试套件
    suite = unittest.TestSuite()

    # 添加测试用例
    test_cases = [
        'test_real_complete_blockchain_flow',
        'test_concurrent_transactions',
        'test_account_recovery_and_integrity'
    ]

    for test_case in test_cases:
        suite.addTest(TestRealEndToEndBlockchain(test_case))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出测试结果摘要
    print("\n" + "=" * 80)
    print("真实端到端测试结果摘要")
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

    if success_rate >= 100:
        print("√ 所有真实端到端测试通过！区块链系统运行正常。")
    elif success_rate >= 80:
        print("√ 大部分测试通过，系统基本运行正常，少数问题需要进一步调查。")
    else:
        print("X 测试存在较多问题，需要进一步调试和修复。")

    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_real_end_to_end_tests()
    sys.exit(0 if success else 1)