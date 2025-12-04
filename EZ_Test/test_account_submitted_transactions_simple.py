#!/usr/bin/env python3
"""
Test Account submitted transactions queue functionality
"""

import sys
import os
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


def test_submitted_transactions_queue():
    """Test basic functionality of submitted transactions queue"""
    print("Testing Account submitted transactions queue functionality...")

    # Create test key pair data
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_account_address_123"

    # Create Account instance
    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="TestAccount"
    )

    print(f"1. Account created successfully: {account.name}")

    # Test initial state
    initial_count = account.get_submitted_transactions_count()
    print(f"2. Initial submitted transactions queue size: {initial_count}")
    assert initial_count == 0, "Initial queue should be empty"

    # Simulate adding transaction to queue
    test_tx_hash = "test_multi_transaction_hash_123"
    test_tx_data = {
        'hash': test_tx_hash,
        'sender': test_address,
        'transaction_count': 3,
        'total_amount': 1000,
        'timestamp': '2024-01-01T12:00:00'
    }

    # Add to queue using private method (simulating sync after pool submission)
    account._add_to_submitted_queue(test_tx_hash, test_tx_data)

    print(f"3. Added transaction to local queue: {test_tx_hash[:16]}...")

    # Check queue size
    after_add_count = account.get_submitted_transactions_count()
    print(f"4. Queue size after add: {after_add_count}")
    assert after_add_count == 1, "Queue should contain 1 transaction after add"

    # Test getting transaction
    retrieved_tx = account.get_submitted_transaction(test_tx_hash)
    print(f"5. Retrieved transaction from queue: {retrieved_tx is not None}")
    assert retrieved_tx is not None, "Should be able to retrieve added transaction"
    assert retrieved_tx['hash'] == test_tx_hash, "Retrieved transaction data should be correct"

    # Test getting all transactions
    all_txs = account.get_all_submitted_transactions()
    print(f"6. Retrieved all transactions: {len(all_txs)} items")
    assert len(all_txs) == 1, "Should have 1 transaction"
    assert test_tx_hash in all_txs, "Should contain test transaction"

    # Test account info includes submitted transactions count
    account_info = account.get_account_info()
    print(f"7. Submitted transactions count in account info: {account_info['submitted_transactions_count']}")
    assert account_info['submitted_transactions_count'] == 1, "Account info should show correct count"

    # Test removing transaction (simulating cleanup after confirmation)
    remove_success = account.remove_from_submitted_queue(test_tx_hash)
    print(f"8. Transaction removal success: {remove_success}")
    assert remove_success, "Should successfully remove transaction"

    # Check state after removal
    after_remove_count = account.get_submitted_transactions_count()
    print(f"9. Queue size after removal: {after_remove_count}")
    assert after_remove_count == 0, "Queue should be empty after removal"

    print("SUCCESS: All tests passed! Account submitted transactions queue is working correctly.")

    # Cleanup
    account.cleanup()
    print("10. Account resources cleaned up")


def test_submit_tx_infos_integration():
    """Test submit_tx_infos_to_pool method integration"""
    print("\nTesting submit_tx_infos_to_pool integration...")

    # Create test data
    test_private_key = b"test_private_key_data"
    test_public_key = b"test_public_key_data"
    test_address = "test_account_address_456"

    account = Account(
        address=test_address,
        private_key_pem=test_private_key,
        public_key_pem=test_public_key,
        name="IntegrationTestAccount"
    )

    print(f"1. Account created successfully: {account.name}")

    # Mock SubmitTxInfo
    mock_submit_tx_info = Mock(spec=SubmitTxInfo)
    mock_submit_tx_info.multi_transactions_hash = "test_multi_tx_hash_789"
    mock_submit_tx_info.submit_timestamp = "2024-01-01T12:00:00"
    mock_submit_tx_info.submitter_address = test_address

    # Mock transaction pool
    mock_tx_pool = Mock(spec=TxPool)
    mock_tx_pool.add_submit_tx_info.return_value = (True, "Success")

    # Mock multi_txn_result
    mock_multi_txn_result = {
        'multi_transactions': Mock(),
        'transaction_count': 2,
        'total_amount': 500
    }
    mock_multi_txn_result['multi_transactions'].digest = "test_multi_tx_hash_789"

    print("2. Mock transaction pool and data created")

    # Test submission functionality
    submit_success = account.submit_tx_infos_to_pool(
        submit_tx_info=mock_submit_tx_info,
        tx_pool=mock_tx_pool,
        multi_txn_result=mock_multi_txn_result
    )

    print(f"3. Transaction submission success: {submit_success}")
    assert submit_success, "Submission should succeed"

    # Check if local queue is synced
    queue_count = account.get_submitted_transactions_count()
    print(f"4. Local queue size: {queue_count}")
    assert queue_count == 1, "Local queue should contain 1 transaction"

    # Check if transaction pool was called
    mock_tx_pool.add_submit_tx_info.assert_called_once_with(mock_submit_tx_info)
    print("5. Transaction pool add_submit_tx_info method called correctly")

    print("SUCCESS: submit_tx_infos_to_pool integration test passed!")

    # Cleanup
    account.cleanup()
    print("6. Account resources cleaned up")


if __name__ == "__main__":
    print("=" * 60)
    print("Account Submitted Transactions Queue Test")
    print("=" * 60)

    try:
        test_submitted_transactions_queue()
        test_submit_tx_infos_integration()
        print("\n" + "=" * 60)
        print("SUCCESS: All tests completed successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\nFAILED: Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)