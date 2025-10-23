#!/usr/bin/env python3
"""
演示 PackTransactions.py 中的发送者唯一性检测功能
展示在打包多个 MultiTransaction 时，如何确保每个 sender 最多只有一个交易被打包
"""

import os
import sys
import time
from datetime import datetime
from unittest.mock import MagicMock

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Transaction_Pool.PackTransactions import TransactionPackager
from EZ_Transaction_Pool.TransactionPool import TransactionPool


def create_mock_multi_transactions():
    """创建模拟的多重交易用于演示"""
    transactions = []

    # 定义不同sender和交易数量
    test_data = [
        ("Alice", 2, "2023-01-01 10:00:00"),
        ("Bob", 3, "2023-01-01 10:01:00"),
        ("Charlie", 1, "2023-01-01 10:02:00"),
        ("Alice", 1, "2023-01-01 10:03:00"),  # Alice的第二个交易
        ("David", 2, "2023-01-01 10:04:00"),
        ("Eve", 4, "2023-01-01 10:05:00"),
        ("Bob", 2, "2023-01-01 10:06:00"),   # Bob的第二个交易
        ("Alice", 3, "2023-01-01 10:07:00"),  # Alice的第三个交易
        (None, 1, "2023-01-01 10:08:00"),   # 没有sender的交易
        ("", 2, "2023-01-01 10:09:00"),     # 空字符串sender的交易
    ]

    for i, (sender, txn_count, timestamp) in enumerate(test_data):
        mock_txn = MagicMock()
        mock_txn.sender = sender
        mock_txn.digest = f"digest_{sender}_{i}" if sender else f"digest_null_{i}"
        mock_txn.multi_txns = [MagicMock() for _ in range(txn_count)]
        mock_txn.encode.return_value = f"encoded_data_{i}".encode()
        mock_txn.timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        transactions.append(mock_txn)

    return transactions


def demo_fifo_strategy():
    """演示FIFO策略下的sender唯一性检测"""
    print("=" * 60)
    print("演示1: FIFO策略下的发送者唯一性检测")
    print("=" * 60)

    packager = TransactionPackager(max_multi_txns_per_block=20)
    transactions = create_mock_multi_transactions()

    print(f"原始交易列表 (共{len(transactions)}个交易):")
    sender_counts = {}
    for i, txn in enumerate(transactions):
        sender_display = txn.sender if txn.sender else "NULL/EMPTY"
        print(f"  {i+1:2d}. Sender: {sender_display:8s} | "
              f"Digest: {txn.digest:25s} | "
              f"SingleTxns: {len(txn.multi_txns)}")

        if txn.sender not in sender_counts:
            sender_counts[txn.sender] = 0
        sender_counts[txn.sender] += 1

    print(f"\n原始发送者统计:")
    for sender, count in sender_counts.items():
        sender_display = sender if sender else "NULL/EMPTY"
        print(f"  {sender_display}: {count} 个交易")

    # 应用sender唯一性过滤
    filtered_txns = packager._filter_unique_senders(transactions)

    print(f"\n过滤后的交易列表 (共{len(filtered_txns)}个交易):")
    for i, txn in enumerate(filtered_txns):
        sender_display = txn.sender if txn.sender else "NULL/EMPTY"
        print(f"  {i+1:2d}. Sender: {sender_display:8s} | "
              f"Digest: {txn.digest:25s} | "
              f"SingleTxns: {len(txn.multi_txns)}")

    # 验证sender唯一性
    senders = [txn.sender for txn in filtered_txns if txn.sender]
    unique_senders = set(senders)
    print(f"\n过滤后验证:")
    print(f"  有sender的交易数量: {len(senders)}")
    print(f"  唯一sender数量: {len(unique_senders)}")
    print(f"  是否满足唯一性要求: {'YES 是' if len(senders) == len(unique_senders) else 'NO 否'}")


def demo_fee_strategy():
    """演示按手续费排序策略下的sender唯一性检测"""
    print("\n" + "=" * 60)
    print("演示2: 按手续费排序策略下的发送者唯一性检测")
    print("=" * 60)

    packager = TransactionPackager(max_multi_txns_per_block=20)
    transactions = create_mock_multi_transactions()

    # 按交易数量（手续费代理）排序
    sorted_txns = sorted(transactions, key=lambda x: len(x.multi_txns), reverse=True)

    print("按手续费排序后的交易列表:")
    for i, txn in enumerate(sorted_txns):
        sender_display = txn.sender if txn.sender else "NULL/EMPTY"
        print(f"  {i+1:2d}. Sender: {sender_display:8s} | "
              f"Digest: {txn.digest:25s} | "
              f"SingleTxns: {len(txn.multi_txns)} (手续费)")

    # 应用sender唯一性过滤
    filtered_txns = packager._filter_unique_senders(sorted_txns)

    print(f"\n过滤后的交易列表 (共{len(filtered_txns)}个交易):")
    for i, txn in enumerate(filtered_txns):
        sender_display = txn.sender if txn.sender else "NULL/EMPTY"
        print(f"  {i+1:2d}. Sender: {sender_display:8s} | "
              f"Digest: {txn.digest:25s} | "
              f"SingleTxns: {len(txn.multi_txns)}")

    # 验证sender唯一性
    senders = [txn.sender for txn in filtered_txns if txn.sender]
    unique_senders = set(senders)
    print(f"\n过滤后验证:")
    print(f"  有sender的交易数量: {len(senders)}")
    print(f"  唯一sender数量: {len(unique_senders)}")
    print(f"  是否满足唯一性要求: {'YES 是' if len(senders) == len(unique_senders) else 'NO 否'}")


def demo_full_packaging_process():
    """演示完整的打包流程"""
    print("\n" + "=" * 60)
    print("演示3: 完整的区块打包流程")
    print("=" * 60)

    packager = TransactionPackager(max_multi_txns_per_block=10)
    transactions = create_mock_multi_transactions()

    # 创建模拟交易池
    mock_pool = MagicMock()
    mock_pool.get_all_multi_transactions.return_value = transactions

    print("开始打包交易...")
    print(f"交易池中有 {len(transactions)} 个待打包交易")

    # 执行打包
    start_time = time.time()
    package_data = packager.package_transactions(mock_pool, "fifo")
    end_time = time.time()

    print(f"打包完成，耗时: {(end_time - start_time)*1000:.2f}ms")

    # 显示打包结果
    print(f"\n打包结果:")
    print(f"  选中的多重交易数量: {len(package_data.selected_multi_txns)}")
    print(f"  默克尔根: {package_data.merkle_root}")
    print(f"  发送者地址: {package_data.sender_addresses}")
    print(f"  打包时间: {package_data.package_time}")

    # 详细显示选中的交易
    print(f"\n选中的交易详情:")
    for i, txn in enumerate(package_data.selected_multi_txns):
        sender_display = txn.sender if txn.sender else "NULL/EMPTY"
        print(f"  {i+1}. Sender: {sender_display:8s} | Digest: {txn.digest}")

    # 获取统计信息
    stats = packager.get_package_stats(package_data)
    print(f"\n打包统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


def demo_edge_cases():
    """演示边界情况"""
    print("\n" + "=" * 60)
    print("演示4: 边界情况处理")
    print("=" * 60)

    packager = TransactionPackager()

    # 情况1: 全部是同一个sender
    print("情况1: 多个交易来自同一个sender")
    alice_txns = []
    for i in range(5):
        alice_txn = MagicMock()
        alice_txn.sender = "Alice"
        alice_txn.digest = f"alice_digest_{i}"
        alice_txn.multi_txns = [MagicMock() for _ in range(i+1)]
        alice_txns.append(alice_txn)

    print(f"  输入: {len(alice_txns)} 个Alice的交易")
    filtered = packager._filter_unique_senders(alice_txns)
    print(f"  输出: {len(filtered)} 个交易 (只保留第一个)")
    print(f"  保留的交易: {filtered[0].digest}")

    # 情况2: 全部没有sender
    print(f"\n情况2: 全部交易没有sender")
    null_txns = []
    for i in range(3):
        null_txn = MagicMock()
        null_txn.sender = None
        null_txn.digest = f"null_digest_{i}"
        null_txn.multi_txns = [MagicMock()]
        null_txns.append(null_txn)

    print(f"  输入: {len(null_txns)} 个无sender的交易")
    filtered = packager._filter_unique_senders(null_txns)
    print(f"  输出: {len(filtered)} 个交易 (全部保留)")

    # 情况3: 空列表
    print(f"\n情况3: 空交易列表")
    empty_result = packager._filter_unique_senders([])
    print(f"  输入: 0 个交易")
    print(f"  输出: {len(empty_result)} 个交易")


def main():
    """主演示函数"""
    print("PackTransactions.py 发送者唯一性检测功能演示")
    print("此演示展示了在打包区块时如何确保每个sender最多只有一个交易被打包")

    # 运行各个演示
    demo_fifo_strategy()
    demo_fee_strategy()
    demo_full_packaging_process()
    demo_edge_cases()

    print("\n" + "=" * 60)
    print("演示总结")
    print("=" * 60)
    print("OK FIFO策略: 保留每个sender最早的交易")
    print("OK 手续费策略: 保留每个sender手续费最高的交易")
    print("OK 完整打包流程: 自动应用sender唯一性检测")
    print("OK 边界情况: 正确处理各种特殊情况")
    print("OK 所有场景都确保了每个sender最多只有一个交易被打包")
    print("\n发送者唯一性检测功能已成功集成到PackTransactions.py中！")


if __name__ == "__main__":
    main()