#!/usr/bin/env python3
"""
测试Account类的提交交易队列功能
"""

import sys
import os
from unittest.mock import Mock

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_Account.Account import Account
    from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
    from EZ_Transaction.MultiTransactions import MultiTransactions
    from EZ_Tx_Pool.TXPool import TxPool
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def test_submitted_transactions_queue():
    """测试提交交易队列的基本功能"""
    print("开始测试Account提交交易队列功能...")

    # 创建测试用的密钥对（这里用简单数据代替实际的PEM密钥）
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_account_address_123"

    # 创建Account实例
    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="TestAccount"
    )

    print(f"1. 创建Account成功: {account.name}")

    # 测试初始状态
    initial_count = account.get_submitted_transactions_count()
    print(f"2. 初始提交交易队列大小: {initial_count}")
    assert initial_count == 0, "初始队列应该为空"

    # 模拟添加交易到队列
    test_tx_hash = "test_multi_transaction_hash_123"
    test_tx_data = {
        'hash': test_tx_hash,
        'sender': test_address,
        'transaction_count': 3,
        'total_amount': 1000,
        'timestamp': '2024-01-01T12:00:00'
    }

    # 使用私有方法添加到队列（模拟提交到交易池后的同步操作）
    account._add_to_submitted_queue(test_tx_hash, test_tx_data)

    print(f"3. 已添加交易到本地队列: {test_tx_hash[:16]}...")

    # 检查队列大小
    after_add_count = account.get_submitted_transactions_count()
    print(f"4. 添加后队列大小: {after_add_count}")
    assert after_add_count == 1, "添加后队列应该包含1个交易"

    # 测试获取交易
    retrieved_tx = account.get_submitted_transaction(test_tx_hash)
    print(f"5. 从队列获取交易成功: {retrieved_tx is not None}")
    assert retrieved_tx is not None, "应该能够获取添加的交易"
    assert retrieved_tx['hash'] == test_tx_hash, "获取的交易数据应该正确"

    # 测试获取所有交易
    all_txs = account.get_all_submitted_transactions()
    print(f"6. 获取所有交易: {len(all_txs)} 个")
    assert len(all_txs) == 1, "应该有1个交易"
    assert test_tx_hash in all_txs, "应该包含测试交易"

    # 测试账户信息包含提交交易数量
    account_info = account.get_account_info()
    print(f"7. 账户信息中的提交交易数量: {account_info['submitted_transactions_count']}")
    assert account_info['submitted_transactions_count'] == 1, "账户信息应该显示正确的提交交易数量"

    # 测试移除交易（模拟交易确认后的清理）
    remove_success = account.remove_from_submitted_queue(test_tx_hash)
    print(f"8. 移除交易成功: {remove_success}")
    assert remove_success, "应该成功移除交易"

    # 检查移除后的状态
    after_remove_count = account.get_submitted_transactions_count()
    print(f"9. 移除后队列大小: {after_remove_count}")
    assert after_remove_count == 0, "移除后队列应该为空"

    # 测试移除不存在的交易
    remove_nonexistent = account.remove_from_submitted_queue("nonexistent_hash")
    print(f"10. 移除不存在交易: {remove_nonexistent}")
    assert not remove_nonexistent, "不应该能移除不存在的交易"

    # 测试清空队列
    # 先添加几个交易
    for i in range(3):
        tx_hash = f"test_tx_hash_{i}"
        tx_data = {'hash': tx_hash, 'sender': test_address}
        account._add_to_submitted_queue(tx_hash, tx_data)

    print(f"11. 添加3个交易后队列大小: {account.get_submitted_transactions_count()}")
    assert account.get_submitted_transactions_count() == 3, "应该有3个交易"

    # 清空队列
    clear_success = account.clear_submitted_transactions()
    print(f"12. 清空队列成功: {clear_success}")
    assert clear_success, "应该成功清空队列"
    assert account.get_submitted_transactions_count() == 0, "清空后队列应该为空"

    print("\n✅ 所有测试通过！Account提交交易队列功能正常工作。")

    # 清理
    account.cleanup()
    print("13. Account资源已清理")


def test_submit_tx_infos_integration():
    """测试submit_tx_infos_to_pool方法的集成功能"""
    print("\n开始测试submit_tx_infos_to_pool集成功能...")

    # 创建测试数据
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_account_address_456"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="IntegrationTestAccount"
    )

    print(f"1. 创建Account成功: {account.name}")

    # 模拟SubmitTxInfo（这里用Mock代替实际创建）
    mock_submit_tx_info = Mock(spec=SubmitTxInfo)
    mock_submit_tx_info.multi_transactions_hash = "test_multi_tx_hash_789"
    mock_submit_tx_info.submit_timestamp = "2024-01-01T12:00:00"
    mock_submit_tx_info.submitter_address = test_address

    # 模拟交易池
    mock_tx_pool = Mock(spec=TxPool)
    mock_tx_pool.add_submit_tx_info.return_value = (True, "Success")

    # 模拟multi_txn_result
    mock_multi_txn_result = {
        'multi_transactions': Mock(),
        'transaction_count': 2,
        'total_amount': 500
    }
    mock_multi_txn_result['multi_transactions'].digest = "test_multi_tx_hash_789"

    print("2. 模拟交易池和交易数据创建完成")

    # 测试提交功能
    submit_success = account.submit_tx_infos_to_pool(
        submit_tx_info=mock_submit_tx_info,
        tx_pool=mock_tx_pool,
        multi_txn_result=mock_multi_txn_result
    )

    print(f"3. 提交交易成功: {submit_success}")
    assert submit_success, "提交应该成功"

    # 检查本地队列是否同步添加
    queue_count = account.get_submitted_transactions_count()
    print(f"4. 本地队列大小: {queue_count}")
    assert queue_count == 1, "本地队列应该包含1个交易"

    # 检查交易池是否被调用
    mock_tx_pool.add_submit_tx_info.assert_called_once_with(mock_submit_tx_info)
    print("5. 交易池add_submit_tx_info方法被正确调用")

    print("\n✅ submit_tx_infos_to_pool集成测试通过！")

    # 清理
    account.cleanup()
    print("6. Account资源已清理")


if __name__ == "__main__":
    print("=" * 60)
    print("Account 提交交易队列功能测试")
    print("=" * 60)

    try:
        test_submitted_transactions_queue()
        test_submit_tx_infos_integration()
        print("\n" + "=" * 60)
        print("🎉 所有测试都成功完成！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)