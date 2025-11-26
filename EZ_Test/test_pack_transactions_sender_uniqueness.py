#!/usr/bin/env python3
"""
测试 PackTransactions.py 中的发送者唯一性检测逻辑
确保在打包多个 MultiTransaction 到区块时，每个 sender 最多只有一个交易被打包
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backup_EZ_Transaction_Pool.PackTransactions import TransactionPackager, PackagedBlockData
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction


class TestSenderUniqueness(unittest.TestCase):
    """测试发送者唯一性检测逻辑"""

    def setUp(self):
        """设置测试环境"""
        self.packager = TransactionPackager(max_multi_txns_per_block=50)

        # 创建模拟的 MultiTransaction 对象
        self.create_mock_transactions()

    def create_mock_transactions(self):
        """创建模拟的多重交易"""
        self.mock_txns = []

        # 创建多个不同sender的交易
        senders = ["Alice", "Bob", "Charlie", "David", "Eve"]

        for i, sender in enumerate(senders):
            mock_txn = MagicMock(spec=MultiTransactions)
            mock_txn.sender = sender
            mock_txn.digest = f"digest_{sender}_{i}"
            mock_txn.multi_txns = [MagicMock(spec=Transaction), MagicMock(spec=Transaction)]
            mock_txn.encode.return_value = f"encoded_{sender}_{i}".encode()
            self.mock_txns.append(mock_txn)

        # 创建一些重复sender的交易（Alice和Bob各有多个交易）
        alice_txn2 = MagicMock(spec=MultiTransactions)
        alice_txn2.sender = "Alice"
        alice_txn2.digest = "digest_Alice_extra"
        alice_txn2.multi_txns = [MagicMock(spec=Transaction)]
        alice_txn2.encode.return_value = "encoded_Alice_extra".encode()
        self.mock_txns.append(alice_txn2)

        alice_txn3 = MagicMock(spec=MultiTransactions)
        alice_txn3.sender = "Alice"
        alice_txn3.digest = "digest_Alice_extra2"
        alice_txn3.multi_txns = [MagicMock(spec=Transaction)]
        alice_txn3.encode.return_value = "encoded_Alice_extra2".encode()
        self.mock_txns.append(alice_txn3)

        bob_txn2 = MagicMock(spec=MultiTransactions)
        bob_txn2.sender = "Bob"
        bob_txn2.digest = "digest_Bob_extra"
        bob_txn2.multi_txns = [MagicMock(spec=Transaction), MagicMock(spec=Transaction), MagicMock(spec=Transaction)]
        bob_txn2.encode.return_value = "encoded_Bob_extra".encode()
        self.mock_txns.append(bob_txn2)

        # 创建一个没有sender的交易
        null_sender_txn = MagicMock(spec=MultiTransactions)
        null_sender_txn.sender = None
        null_sender_txn.digest = "digest_null_sender"
        null_sender_txn.multi_txns = [MagicMock(spec=Transaction)]
        null_sender_txn.encode.return_value = "encoded_null_sender".encode()
        self.mock_txns.append(null_sender_txn)

        # 创建一个空字符串sender的交易
        empty_sender_txn = MagicMock(spec=MultiTransactions)
        empty_sender_txn.sender = ""
        empty_sender_txn.digest = "digest_empty_sender"
        empty_sender_txn.multi_txns = [MagicMock(spec=Transaction)]
        empty_sender_txn.encode.return_value = "encoded_empty_sender".encode()
        self.mock_txns.append(empty_sender_txn)

    def test_filter_unique_senders_fifo(self):
        """测试FIFO策略下的发送者唯一性过滤"""
        # 测试FIFO策略
        filtered_txns = self.packager._filter_unique_senders(self.mock_txns)

        # 验证每个sender最多只有一个交易
        senders = [txn.sender for txn in filtered_txns if txn.sender]
        unique_senders = set(senders)

        # 应该只有5个不同的sender（Alice, Bob, Charlie, David, Eve）
        self.assertEqual(len(unique_senders), 5)
        self.assertEqual(len(senders), 5)

        # 验证保留了哪些sender的交易（应该是第一次出现的）
        sender_digests = {txn.sender: txn.digest for txn in filtered_txns if txn.sender}
        self.assertEqual(sender_digests["Alice"], "digest_Alice_0")  # 保留第一个Alice交易
        self.assertEqual(sender_digests["Bob"], "digest_Bob_1")     # 保留第一个Bob交易

        # 验证没有sender的交易也被保留
        null_sender_count = len([txn for txn in filtered_txns if not txn.sender])
        self.assertEqual(null_sender_count, 2)  # None和空字符串sender的交易

    def test_filter_unique_senders_with_sorted_input(self):
        """测试排序后的输入"""
        # 模拟按手续费排序后的列表（Alice的交易排在前面）
        sorted_txns = [
            self.mock_txns[5],  # Alice_extra (高手续费)
            self.mock_txns[6],  # Alice_extra2
            self.mock_txns[7],  # Bob_extra (高手续费)
            self.mock_txns[0],  # Alice_0
            self.mock_txns[1],  # Bob_1
            self.mock_txns[2],  # Charlie
            self.mock_txns[3],  # David
            self.mock_txns[4],  # Eve
        ]

        filtered_txns = self.packager._filter_unique_senders(sorted_txns)

        # 验证每个sender最多只有一个交易
        senders = [txn.sender for txn in filtered_txns if txn.sender]
        unique_senders = set(senders)

        self.assertEqual(len(unique_senders), 5)  # Alice, Bob, Charlie, David, Eve (都在这个排序列表中)

        # 验证保留了排序后最早的交易
        sender_digests = {txn.sender: txn.digest for txn in filtered_txns if txn.sender}
        self.assertEqual(sender_digests["Alice"], "digest_Alice_extra")  # 保留排序后第一个Alice
        self.assertEqual(sender_digests["Bob"], "digest_Bob_extra")     # 保留排序后第一个Bob

    def test_select_transactions_with_uniqueness_check(self):
        """测试_select_transactions方法包含唯一性检查"""
        # 测试FIFO策略
        selected_txns = self.packager._select_transactions(self.mock_txns, "fifo")

        # 验证sender唯一性
        senders = [txn.sender for txn in selected_txns if txn.sender]
        self.assertEqual(len(senders), len(set(senders)))  # 确保无重复sender

        # 测试fee策略
        selected_txns_fee = self.packager._select_transactions(self.mock_txns, "fee")

        # 验证sender唯一性
        senders_fee = [txn.sender for txn in selected_txns_fee if txn.sender]
        self.assertEqual(len(senders_fee), len(set(senders_fee)))  # 确保无重复sender

        # 测试默认策略
        selected_txns_default = self.packager._select_transactions(self.mock_txns, "unknown")

        # 验证sender唯一性
        senders_default = [txn.sender for txn in selected_txns_default if txn.sender]
        self.assertEqual(len(senders_default), len(set(senders_default)))  # 确保无重复sender

    def test_package_transactions_with_sender_uniqueness(self):
        """测试完整的打包流程确保sender唯一性"""
        # 创建模拟的交易池
        mock_pool = MagicMock(spec=TransactionPool)
        mock_pool.get_all_multi_transactions.return_value = self.mock_txns

        # 执行打包
        package_data = self.packager.package_transactions(mock_pool, "fifo")

        # 验证打包结果中的sender唯一性
        selected_txns = package_data.selected_multi_txns
        senders = [txn.sender for txn in selected_txns if txn.sender]

        # 验证无重复sender
        self.assertEqual(len(senders), len(set(senders)))

        # 验证发送者地址列表也反映了唯一性
        unique_senders_from_package = set(package_data.sender_addresses)
        unique_senders_from_txns = {txn.sender for txn in selected_txns if txn.sender}
        self.assertEqual(unique_senders_from_package, unique_senders_from_txns)

    def test_edge_cases(self):
        """测试边界情况"""
        # 测试空列表
        empty_result = self.packager._filter_unique_senders([])
        self.assertEqual(len(empty_result), 0)

        # 测试全部是同一个sender的交易
        alice_txns = []
        for i in range(5):
            alice_txn = MagicMock(spec=MultiTransactions)
            alice_txn.sender = "Alice"
            alice_txn.digest = f"alice_digest_{i}"
            alice_txn.multi_txns = [MagicMock(spec=Transaction)]
            alice_txn.encode.return_value = f"alice_encoded_{i}".encode()
            alice_txns.append(alice_txn)

        alice_filtered = self.packager._filter_unique_senders(alice_txns)
        self.assertEqual(len(alice_filtered), 1)  # 只保留一个
        self.assertEqual(alice_filtered[0].digest, "alice_digest_0")  # 保留第一个

        # 测试全部没有sender的交易
        no_sender_txns = []
        for i in range(3):
            no_sender_txn = MagicMock(spec=MultiTransactions)
            no_sender_txn.sender = None
            no_sender_txn.digest = f"no_sender_digest_{i}"
            no_sender_txn.multi_txns = [MagicMock(spec=Transaction)]
            no_sender_txn.encode.return_value = f"no_sender_encoded_{i}".encode()
            no_sender_txns.append(no_sender_txn)

        no_sender_filtered = self.packager._filter_unique_senders(no_sender_txns)
        self.assertEqual(len(no_sender_filtered), 3)  # 全部保留

        # 测试混合None和空字符串sender
        mixed_sender_txns = []
        for sender in [None, "", None, "", "Alice"]:
            mixed_txn = MagicMock(spec=MultiTransactions)
            mixed_txn.sender = sender
            mixed_txn.digest = f"mixed_digest_{sender}"
            mixed_txn.multi_txns = [MagicMock(spec=Transaction)]
            mixed_txn.encode.return_value = f"mixed_encoded_{sender}".encode()
            mixed_sender_txns.append(mixed_txn)

        mixed_filtered = self.packager._filter_unique_senders(mixed_sender_txns)
        # 两个None和两个空字符串sender的交易都应该保留，只有一个Alice交易保留
        self.assertEqual(len(mixed_filtered), 5)

    def test_max_transactions_limit_after_uniqueness_filter(self):
        """测试在唯一性过滤后的交易数量限制"""
        # 设置较小的最大交易数
        small_packager = TransactionPackager(max_multi_txns_per_block=3)

        mock_pool = MagicMock(spec=TransactionPool)
        mock_pool.get_all_multi_transactions.return_value = self.mock_txns

        # 执行打包
        package_data = small_packager.package_transactions(mock_pool, "fifo")

        # 验证交易数量不超过限制
        self.assertLessEqual(len(package_data.selected_multi_txns), 3)

        # 验证sender唯一性仍然保持
        senders = [txn.sender for txn in package_data.selected_multi_txns if txn.sender]
        self.assertEqual(len(senders), len(set(senders)))


class TestPackagedBlockData(unittest.TestCase):
    """测试 PackagedBlockData 数据结构"""

    def test_packaged_block_data_structure(self):
        """测试 PackagedBlockData 的结构完整性"""
        mock_txns = []
        for i in range(3):
            mock_txn = MagicMock(spec=MultiTransactions)
            mock_txn.sender = f"sender_{i}"
            mock_txn.digest = f"digest_{i}"
            mock_txns.append(mock_txn)

        package_data = PackagedBlockData(
            selected_multi_txns=mock_txns,
            merkle_root="test_merkle_root",
            sender_addresses=["sender_0", "sender_1", "sender_2"],
            package_time=datetime.now()
        )

        # 验证数据结构
        self.assertEqual(len(package_data.selected_multi_txns), 3)
        self.assertEqual(package_data.merkle_root, "test_merkle_root")
        self.assertEqual(len(package_data.sender_addresses), 3)

        # 验证to_dict方法
        data_dict = package_data.to_dict()
        self.assertIn('multi_transactions_digests', data_dict)
        self.assertIn('merkle_root', data_dict)
        self.assertIn('sender_addresses', data_dict)
        self.assertIn('package_time', data_dict)


def run_sender_uniqueness_tests():
    """运行所有发送者唯一性测试"""
    print("=" * 60)
    print("Testing Sender Uniqueness Logic in PackTransactions")
    print("=" * 60)

    # 创建测试套件
    test_suite = unittest.TestSuite()

    # 添加测试用例
    test_classes = [TestSenderUniqueness, TestPackagedBlockData]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # 输出测试结果总结
    print("\n" + "=" * 60)
    print("Test Results Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    success = len(result.failures) == 0 and len(result.errors) == 0
    print(f"\nOverall result: {'PASSED' if success else 'FAILED'}")
    print("=" * 60)

    return success


if __name__ == "__main__":
    run_sender_uniqueness_tests()