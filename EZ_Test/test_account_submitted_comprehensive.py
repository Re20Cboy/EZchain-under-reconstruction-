#!/usr/bin/env python3
"""
Comprehensive tests for Account submitted transactions queue functionality
"""

import sys
import os
import time
import threading
from unittest.mock import Mock, patch

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_Account.Account import Account
    from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
    from EZ_Tx_Pool.TXPool import TxPool
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def test_concurrent_queue_operations():
    """Test thread safety of queue operations"""
    print("Testing concurrent queue operations...")

    # Create account
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_concurrent_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="ConcurrentTestAccount"
    )

    print(f"1. Account created for concurrency test: {account.name}")

    # Test data
    num_threads = 5
    transactions_per_thread = 10
    results = []
    errors = []

    def add_transactions(thread_id):
        try:
            for i in range(transactions_per_thread):
                tx_hash = f"thread_{thread_id}_tx_{i}"
                tx_data = {
                    'hash': tx_hash,
                    'thread_id': thread_id,
                    'index': i,
                    'sender': test_address
                }
                account._add_to_submitted_queue(tx_hash, tx_data)
                time.sleep(0.001)  # Small delay to increase chance of race conditions
            results.append(f"Thread {thread_id} completed successfully")
        except Exception as e:
            errors.append(f"Thread {thread_id} failed: {e}")

    # Start threads
    threads = []
    for i in range(num_threads):
        thread = threading.Thread(target=add_transactions, args=(i,))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Check results
    print(f"2. Threads completed: {len(results)}")
    print(f"3. Errors encountered: {len(errors)}")

    if errors:
        for error in errors:
            print(f"   Error: {error}")
        assert False, f"Concurrent operations failed: {len(errors)} errors"

    # Verify final state
    final_count = account.get_submitted_transactions_count()
    expected_count = num_threads * transactions_per_thread
    print(f"4. Final queue size: {final_count} (expected: {expected_count})")

    assert final_count == expected_count, f"Queue size mismatch: got {final_count}, expected {expected_count}"
    assert len(errors) == 0, f"Errors occurred during concurrent operations: {errors}"

    print("SUCCESS: Concurrent operations test passed")

    # Cleanup
    account.clear_submitted_transactions()
    account.cleanup()


def test_edge_cases():
    """Test edge cases and error conditions"""
    print("\nTesting edge cases...")

    # Create account
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_edge_cases_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="EdgeCasesTestAccount"
    )

    print(f"1. Account created for edge cases test: {account.name}")

    # Test 1: Remove non-existent transaction
    result1 = account.remove_from_submitted_queue("nonexistent_hash")
    print(f"2. Removing non-existent transaction: {result1} (should be False)")
    assert not result1, "Should return False for non-existent transaction"

    # Test 2: Get non-existent transaction
    result2 = account.get_submitted_transaction("nonexistent_hash")
    print(f"3. Getting non-existent transaction: {result2} (should be None)")
    assert result2 is None, "Should return None for non-existent transaction"

    # Test 3: Add transaction with None data
    account._add_to_submitted_queue("test_none_data", None)
    retrieved_none = account.get_submitted_transaction("test_none_data")
    print(f"4. Retrieved None data transaction: {retrieved_none is None}")
    assert retrieved_none is None, "Should handle None data correctly"

    # Test 4: Add transaction with empty data
    empty_data = {}
    account._add_to_submitted_queue("test_empty_data", empty_data)
    retrieved_empty = account.get_submitted_transaction("test_empty_data")
    print(f"5. Retrieved empty data transaction: {retrieved_empty == {}}")
    assert retrieved_empty == {}, "Should handle empty data correctly"

    # Test 5: Clear empty queue
    account.clear_submitted_transactions()  # Should not raise error
    count_after_clear = account.get_submitted_transactions_count()
    print(f"6. Queue size after clear: {count_after_clear}")
    assert count_after_clear == 0, "Clear should result in empty queue"

    # Test 6: Add same hash twice (should overwrite)
    tx_hash = "duplicate_hash"
    first_data = {"version": 1, "data": "first"}
    second_data = {"version": 2, "data": "second"}

    account._add_to_submitted_queue(tx_hash, first_data)
    account._add_to_submitted_queue(tx_hash, second_data)  # Should overwrite

    retrieved = account.get_submitted_transaction(tx_hash)
    print(f"7. Duplicate hash handling: retrieved version = {retrieved.get('version')}")
    assert retrieved["version"] == 2, "Should overwrite existing data with same hash"

    print("SUCCESS: Edge cases test passed")

    # Cleanup
    account.cleanup()


def test_large_volume_operations():
    """Test performance with large number of transactions"""
    print("\nTesting large volume operations...")

    # Create account
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_large_volume_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="LargeVolumeTestAccount"
    )

    print(f"1. Account created for large volume test: {account.name}")

    # Test parameters
    num_transactions = 1000

    # Measure time for adding transactions
    start_time = time.time()
    for i in range(num_transactions):
        tx_hash = f"large_volume_tx_{i:06d}"
        tx_data = {
            'hash': tx_hash,
            'index': i,
            'sender': test_address,
            'amount': i * 100,
            'timestamp': f'2024-01-01T12:{i%60:02d}:00'
        }
        account._add_to_submitted_queue(tx_hash, tx_data)

    add_time = time.time() - start_time
    print(f"2. Added {num_transactions} transactions in {add_time:.3f} seconds")

    # Verify count
    count = account.get_submitted_transactions_count()
    print(f"3. Queue size: {count}")
    assert count == num_transactions, f"Queue size should be {num_transactions}"

    # Measure time for retrieving all transactions
    start_time = time.time()
    all_txs = account.get_all_submitted_transactions()
    retrieve_time = time.time() - start_time
    print(f"4. Retrieved {len(all_txs)} transactions in {retrieve_time:.3f} seconds")

    # Test random access
    import random
    random_indices = random.sample(range(num_transactions), 10)

    start_time = time.time()
    for idx in random_indices:
        tx_hash = f"large_volume_tx_{idx:06d}"
        tx_data = account.get_submitted_transaction(tx_hash)
        assert tx_data is not None, f"Should retrieve transaction {tx_hash}"
        assert tx_data['index'] == idx, f"Retrieved data should be correct for {tx_hash}"

    random_access_time = time.time() - start_time
    print(f"5. Random access of 10 transactions in {random_access_time:.6f} seconds")

    # Measure time for removing all transactions
    start_time = time.time()
    for i in range(num_transactions):
        tx_hash = f"large_volume_tx_{i:06d}"
        success = account.remove_from_submitted_queue(tx_hash)
        assert success, f"Should successfully remove transaction {tx_hash}"

    remove_time = time.time() - start_time
    print(f"6. Removed {num_transactions} transactions in {remove_time:.3f} seconds")

    # Verify empty
    final_count = account.get_submitted_transactions_count()
    print(f"7. Final queue size: {final_count}")
    assert final_count == 0, "Queue should be empty after removing all transactions"

    print("SUCCESS: Large volume operations test passed")
    print(f"Performance summary:")
    print(f"  - Add: {num_transactions/add_time:.0f} transactions/second")
    print(f"  - Retrieve all: {len(all_txs)/retrieve_time:.0f} transactions/second")
    print(f"  - Remove: {num_transactions/remove_time:.0f} transactions/second")

    # Cleanup
    account.cleanup()


def test_submit_tx_infos_pool_integration():
    """Test integration with actual TXPool behavior"""
    print("\nTesting TXPool integration scenarios...")

    # Create account
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_pool_integration_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="PoolIntegrationTestAccount"
    )

    print(f"1. Account created for pool integration test: {account.name}")

    # Test scenario 1: Successful submission
    mock_submit_tx_info = Mock(spec=SubmitTxInfo)
    mock_submit_tx_info.multi_transactions_hash = "success_tx_hash_123"
    mock_submit_tx_info.submit_timestamp = "2024-01-01T12:00:00"
    mock_submit_tx_info.submitter_address = test_address

    mock_tx_pool = Mock(spec=TxPool)
    mock_tx_pool.add_submit_tx_info.return_value = (True, "Success")

    mock_multi_txn_result = {
        'multi_transactions': Mock(),
        'transaction_count': 3,
        'total_amount': 1500
    }
    mock_multi_txn_result['multi_transactions'].digest = "success_tx_hash_123"

    success = account.submit_tx_infos_to_pool(
        submit_tx_info=mock_submit_tx_info,
        tx_pool=mock_tx_pool,
        multi_txn_result=mock_multi_txn_result
    )

    print(f"2. Successful submission: {success}")
    assert success, "Submission should succeed"
    assert account.get_submitted_transactions_count() == 1, "Local queue should have 1 transaction"

    # Test scenario 2: Failed submission
    mock_submit_tx_info_2 = Mock(spec=SubmitTxInfo)
    mock_submit_tx_info_2.multi_transactions_hash = "failed_tx_hash_456"
    mock_submit_tx_info_2.submitter_address = test_address

    mock_tx_pool.add_submit_tx_info.return_value = (False, "Validation failed")

    failed_success = account.submit_tx_infos_to_pool(
        submit_tx_info=mock_submit_tx_info_2,
        tx_pool=mock_tx_pool,
        multi_txn_result=None
    )

    print(f"3. Failed submission: {failed_success}")
    assert not failed_success, "Failed submission should return False"
    assert account.get_submitted_transactions_count() == 1, "Local queue should not contain failed transaction"

    # Test scenario 3: Exception during submission
    mock_submit_tx_info_3 = Mock(spec=SubmitTxInfo)
    mock_submit_tx_info_3.multi_transactions_hash = "exception_tx_hash_789"
    mock_submit_tx_info_3.submitter_address = test_address

    mock_tx_pool.add_submit_tx_info.side_effect = Exception("Pool error")

    exception_success = account.submit_tx_infos_to_pool(
        submit_tx_info=mock_submit_tx_info_3,
        tx_pool=mock_tx_pool,
        multi_txn_result=None
    )

    print(f"4. Exception submission: {exception_success}")
    assert not exception_success, "Exception during submission should return False"
    assert account.get_submitted_transactions_count() == 1, "Local queue should not contain exception transaction"

    print("SUCCESS: TXPool integration test passed")

    # Cleanup
    account.cleanup()


def test_account_info_integration():
    """Test integration with account information"""
    print("\nTesting account info integration...")

    # Create account
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_account_info_account"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="AccountInfoTestAccount"
    )

    print(f"1. Account created: {account.name}")

    # Check initial account info
    info = account.get_account_info()
    print(f"2. Initial submitted transactions count: {info['submitted_transactions_count']}")
    assert info['submitted_transactions_count'] == 0, "Initial count should be 0"
    assert 'submitted_transactions_count' in info, "Account info should include submitted_transactions_count"

    # Add some transactions
    test_hashes = ["hash_1", "hash_2", "hash_3"]
    for i, tx_hash in enumerate(test_hashes):
        tx_data = {
            'hash': tx_hash,
            'index': i,
            'sender': test_address
        }
        account._add_to_submitted_queue(tx_hash, tx_data)

    # Check updated account info
    info = account.get_account_info()
    print(f"3. Updated submitted transactions count: {info['submitted_transactions_count']}")
    assert info['submitted_transactions_count'] == 3, "Updated count should be 3"

    # Remove one transaction
    account.remove_from_submitted_queue("hash_2")

    # Check account info after removal
    info = account.get_account_info()
    print(f"4. Count after removing one transaction: {info['submitted_transactions_count']}")
    assert info['submitted_transactions_count'] == 2, "Count should be 2 after removal"

    # Clear all transactions
    account.clear_submitted_transactions()

    # Check final account info
    info = account.get_account_info()
    print(f"5. Final submitted transactions count: {info['submitted_transactions_count']}")
    assert info['submitted_transactions_count'] == 0, "Final count should be 0"

    print("SUCCESS: Account info integration test passed")

    # Cleanup
    account.cleanup()


def run_all_tests():
    """Run all comprehensive tests"""
    print("=" * 80)
    print("COMPREHENSIVE ACCOUNT SUBMITTED TRANSACTIONS QUEUE TESTS")
    print("=" * 80)

    tests = [
        test_concurrent_queue_operations,
        test_edge_cases,
        test_large_volume_operations,
        test_submit_tx_infos_pool_integration,
        test_account_info_integration
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"\n✓ {test_func.__name__} PASSED")
        except Exception as e:
            failed += 1
            print(f"\n✗ {test_func.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
        print("-" * 60)

    print(f"\n" + "=" * 80)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("=" * 80)

    if failed == 0:
        print("🎉 ALL COMPREHENSIVE TESTS PASSED! 🎉")
        return True
    else:
        print("❌ SOME TESTS FAILED")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)