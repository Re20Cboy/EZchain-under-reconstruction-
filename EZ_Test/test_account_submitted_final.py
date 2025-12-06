#!/usr/bin/env python3
"""
Final comprehensive tests for Account submitted transactions queue functionality
"""

import sys
import os
import time
import threading
from unittest.mock import Mock

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_Account.Account import Account
    from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
    from EZ_Tx_Pool.TXPool import TxPool
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def test_basic_functionality():
    """Test basic queue functionality"""
    print("Testing basic functionality...")

    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_basic_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="BasicTestAccount"
    )

    # Test initial state
    assert account.get_submitted_transactions_count() == 0
    assert account.get_submitted_transaction("nonexistent") is None
    assert len(account.get_all_submitted_transactions()) == 0

    # Test adding transactions
    for i in range(5):
        tx_hash = f"tx_hash_{i}"
        tx_data = {"hash": tx_hash, "index": i}
        account._add_to_submitted_queue(tx_hash, tx_data)

    assert account.get_submitted_transactions_count() == 5

    # Test retrieving transactions
    tx = account.get_submitted_transaction("tx_hash_2")
    assert tx is not None
    assert tx["index"] == 2

    all_txs = account.get_all_submitted_transactions()
    assert len(all_txs) == 5
    assert "tx_hash_2" in all_txs

    # Test removing transactions
    success = account.remove_from_submitted_queue("tx_hash_2")
    assert success
    assert account.get_submitted_transactions_count() == 4
    assert account.get_submitted_transaction("tx_hash_2") is None

    # Test account info integration
    info = account.get_account_info()
    assert info["submitted_transactions_count"] == 4

    account.cleanup()
    print("Basic functionality test PASSED")


def test_error_handling():
    """Test error handling and edge cases"""
    print("Testing error handling...")

    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_error_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="ErrorTestAccount"
    )

    # Test removing non-existent transaction
    assert not account.remove_from_submitted_queue("nonexistent")

    # Test getting non-existent transaction
    assert account.get_submitted_transaction("nonexistent") is None

    # Test duplicate hash (should overwrite)
    account._add_to_submitted_queue("duplicate", {"version": 1})
    account._add_to_submitted_queue("duplicate", {"version": 2})

    tx = account.get_submitted_transaction("duplicate")
    assert tx["version"] == 2

    # Test clearing empty queue
    account.clear_submitted_transactions()
    assert account.get_submitted_transactions_count() == 0

    account.cleanup()
    print("Error handling test PASSED")


def test_thread_safety():
    """Test thread safety"""
    print("Testing thread safety...")

    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_thread_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="ThreadTestAccount"
    )

    num_threads = 3
    transactions_per_thread = 5

    def worker(thread_id):
        for i in range(transactions_per_thread):
            tx_hash = f"thread_{thread_id}_tx_{i}"
            tx_data = {"thread_id": thread_id, "index": i}
            account._add_to_submitted_queue(tx_hash, tx_data)

    threads = []
    for i in range(num_threads):
        thread = threading.Thread(target=worker, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    expected_count = num_threads * transactions_per_thread
    assert account.get_submitted_transactions_count() == expected_count

    account.cleanup()
    print("Thread safety test PASSED")


def test_pool_integration():
    """Test integration with transaction pool"""
    print("Testing pool integration...")

    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_pool_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="PoolTestAccount"
    )

    # Mock transaction pool
    mock_pool = Mock()
    mock_pool.add_submit_tx_info.return_value = (True, "Success")

    # Mock submit info
    mock_submit_info = Mock(spec=SubmitTxInfo)
    mock_submit_info.multi_transactions_hash = "test_hash_123"
    mock_submit_info.submitter_address = test_address

    # Mock multi transaction result
    mock_result = {
        'multi_transactions': Mock(),
        'transaction_count': 2,
        'total_amount': 1000
    }
    mock_result['multi_transactions'].digest = "test_hash_123"

    # Test successful submission
    success = account.submit_tx_infos_to_pool(mock_submit_info, mock_pool, mock_result)
    assert success
    assert account.get_submitted_transactions_count() == 1

    # Test failed submission
    mock_pool.add_submit_tx_info.return_value = (False, "Failed")
    mock_submit_info.multi_transactions_hash = "test_hash_456"

    success = account.submit_tx_infos_to_pool(mock_submit_info, mock_pool)
    assert not success
    assert account.get_submitted_transactions_count() == 1  # Should not add failed transaction

    account.cleanup()
    print("Pool integration test PASSED")


def test_performance():
    """Test performance with larger datasets"""
    print("Testing performance...")

    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_perf_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="PerfTestAccount"
    )

    # Test adding many transactions
    num_transactions = 100
    start_time = time.time()

    for i in range(num_transactions):
        tx_hash = f"perf_tx_{i:04d}"
        tx_data = {"index": i, "data": f"test_data_{i}"}
        account._add_to_submitted_queue(tx_hash, tx_data)

    add_time = time.time() - start_time
    assert account.get_submitted_transactions_count() == num_transactions

    # Test retrieval performance
    start_time = time.time()
    all_txs = account.get_all_submitted_transactions()
    retrieve_time = time.time() - start_time

    assert len(all_txs) == num_transactions

    # Test removal performance
    start_time = time.time()
    for i in range(num_transactions):
        tx_hash = f"perf_tx_{i:04d}"
        account.remove_from_submitted_queue(tx_hash)

    remove_time = time.time() - start_time
    assert account.get_submitted_transactions_count() == 0

    print(f"Performance results for {num_transactions} transactions:")
    print(f"  Add: {num_transactions/add_time:.0f} tx/sec")
    print(f"  Retrieve: {len(all_txs)/max(retrieve_time, 0.001):.0f} tx/sec")
    print(f"  Remove: {num_transactions/max(remove_time, 0.001):.0f} tx/sec")

    account.cleanup()
    print("Performance test PASSED")


def run_all_tests():
    """Run all tests"""
    print("=" * 70)
    print("ACCOUNT SUBMITTED TRANSACTIONS QUEUE - COMPREHENSIVE TESTS")
    print("=" * 70)

    tests = [
        test_basic_functionality,
        test_error_handling,
        test_thread_safety,
        test_pool_integration,
        test_performance
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"PASSED: {test_func.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAILED: {test_func.__name__} - {e}")
            import traceback
            traceback.print_exc()
        print("-" * 50)

    print(f"\nSUMMARY: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed == 0:
        print("ALL TESTS PASSED SUCCESSFULLY!")
        return True
    else:
        print("SOME TESTS FAILED!")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)