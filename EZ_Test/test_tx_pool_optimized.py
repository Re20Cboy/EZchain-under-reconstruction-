import unittest
import os
import tempfile
import time
import pickle
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_VPB.values.Value import Value
from EZ_Tx_Pool.TXPool import TxPool, ValidationResult


class TestTxPoolOptimized(unittest.TestCase):
    """Optimized test cases for TxPool class with performance improvements."""

    def setUp(self):
        """Set up test fixtures with optimizations."""
        # Create temporary database file
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()

        # Create pool instance with temporary database
        self.pool = TxPool(self.temp_db.name)

        # Use pre-generated or simpler keys for testing
        self.test_sender = "alice"
        self.test_sender2 = "bob"
        self.test_recipient = "charlie"

        # Create test values
        self.test_value1 = Value("0x1000", 100)
        self.test_value2 = Value("0x2000", 200)

        # Mock keys to avoid expensive crypto operations
        self.private_key_pem = b"mock_private_key_pem"
        self.public_key_pem = b"mock_public_key_pem"
        self.private_key_pem2 = b"mock_private_key_pem2"
        self.public_key_pem2 = b"mock_public_key_pem2"

        # Create mock transactions with minimal data
        self.txn1 = self._create_mock_transaction(self.test_sender, self.test_recipient, [self.test_value1], 1)
        self.txn2 = self._create_mock_transaction(self.test_sender, self.test_recipient, [self.test_value2], 2)
        self.txn3 = self._create_mock_transaction(self.test_sender2, self.test_recipient, [self.test_value1], 1)

        # Sign mock transactions
        self.txn1.signature = b"mock_signature_txn1"
        self.txn2.signature = b"mock_signature_txn2"
        self.txn3.signature = b"mock_signature_txn3"

        # Create mock MultiTransactions
        self.multi_txn1 = self._create_mock_multi_transactions(self.test_sender, [self.txn1, self.txn2])
        self.multi_txn2 = self._create_mock_multi_transactions(self.test_sender2, [self.txn3])

        # Sign mock MultiTransactions
        self.multi_txn1.signature = b"mock_signature_multi1"
        self.multi_txn2.signature = b"mock_signature_multi2"

        # Create mock SubmitTxInfos
        self.submit_tx_info1 = self._create_mock_submit_tx_info(
            self.multi_txn1, self.test_sender, self.private_key_pem, self.public_key_pem
        )
        self.submit_tx_info2 = self._create_mock_submit_tx_info(
            self.multi_txn2, self.test_sender2, self.private_key_pem2, self.public_key_pem2
        )

    def tearDown(self):
        """Clean up test fixtures."""
        import gc
        gc.collect()

        # Close database connections
        if hasattr(self.pool, 'lock'):
            try:
                with self.pool.lock:
                    pass  # Ensure lock is released
            except:
                pass

        # Remove temporary database file
        try:
            if os.path.exists(self.temp_db.name):
                os.unlink(self.temp_db.name)
        except:
            pass

    def _create_mock_transaction(self, sender, recipient, value, nonce):
        """Create a mock transaction with minimal overhead."""
        txn = Transaction.__new__(Transaction)
        txn.sender = sender
        txn.recipient = recipient
        txn.value = value
        txn.nonce = nonce
        txn.timestamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        txn.signature = b""
        txn.transaction_hash = f"txn_hash_{sender}_{nonce}"
        return txn

    def _create_mock_multi_transactions(self, sender, transactions):
        """Create mock MultiTransactions with minimal overhead."""
        multi_txn = MultiTransactions.__new__(MultiTransactions)
        multi_txn.sender = sender
        multi_txn.multi_txns = transactions
        multi_txn.timestamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        multi_txn.signature = b""
        multi_txn.digest = f"multi_hash_{sender}_{len(transactions)}"
        return multi_txn

    def _create_mock_submit_tx_info(self, multi_transactions, submitter_address, private_key_pem, public_key_pem):
        """Create mock SubmitTxInfo with minimal overhead."""
        submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        submit_tx_info.multi_transactions_hash = multi_transactions.digest
        submit_tx_info.submitter_address = submitter_address
        submit_tx_info.signature = b"mock_submit_signature"
        submit_tx_info.public_key = public_key_pem
        submit_tx_info.submit_timestamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        submit_tx_info.version = SubmitTxInfo.VERSION
        submit_tx_info._hash = f"submit_hash_{submitter_address}_{multi_transactions.digest}"
        return submit_tx_info

    def test_initialization(self):
        """Test pool initialization."""
        self.assertEqual(len(self.pool.pool), 0)
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertEqual(len(self.pool.hash_index), 0)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 0)
        self.assertIsNotNone(self.pool.stats)

        # Check stats initial values
        expected_stats = {
            'total_received': 0,
            'valid_received': 0,
            'invalid_received': 0,
            'duplicates': 0
        }
        self.assertEqual(self.pool.stats, expected_stats)

    def test_validation_result(self):
        """Test ValidationResult dataclass."""
        validation_result = ValidationResult(
            is_valid=True,
            signature_valid=True,
            structural_valid=True,
            submitter_match=True,
            duplicates_found=[]
        )

        self.assertTrue(validation_result.is_valid)
        self.assertTrue(validation_result.signature_valid)
        self.assertTrue(validation_result.structural_valid)
        self.assertTrue(validation_result.submitter_match)
        self.assertEqual(len(validation_result.duplicates_found), 0)

    def test_validate_submit_tx_info_missing_fields(self):
        """Test validation of SubmitTxInfo with missing fields."""
        # Test missing multi_transactions_hash
        invalid_submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info.multi_transactions_hash = ""
        invalid_submit_tx_info.submitter_address = self.test_sender
        invalid_submit_tx_info.signature = b"test_signature"
        invalid_submit_tx_info.public_key = self.public_key_pem
        invalid_submit_tx_info.submit_timestamp = "2023-01-01T00:00:00"
        invalid_submit_tx_info.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info._hash = None

        validation_result = self.pool.validate_submit_tx_info(invalid_submit_tx_info)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(validation_result.error_message, "Missing multi_transactions_hash")
        self.assertFalse(validation_result.structural_valid)

        # Test missing submitter_address
        invalid_submit_tx_info2 = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info2.multi_transactions_hash = "test_hash"
        invalid_submit_tx_info2.submitter_address = ""
        invalid_submit_tx_info2.signature = b"test_signature"
        invalid_submit_tx_info2.public_key = self.public_key_pem
        invalid_submit_tx_info2.submit_timestamp = "2023-01-01T00:00:00"
        invalid_submit_tx_info2.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info2._hash = None

        validation_result2 = self.pool.validate_submit_tx_info(invalid_submit_tx_info2)

        self.assertFalse(validation_result2.is_valid)
        self.assertEqual(validation_result2.error_message, "Missing submitter_address")
        self.assertFalse(validation_result2.structural_valid)

    def test_add_submit_tx_info_success(self):
        """Test successful addition of SubmitTxInfo."""
        success, message = self.pool.add_submit_tx_info(self.submit_tx_info1)

        self.assertTrue(success)
        self.assertEqual(message, "SubmitTxInfo added successfully")

        # Check pool contents
        self.assertEqual(len(self.pool.pool), 1)
        self.assertEqual(len(self.pool.submitter_index), 1)
        self.assertEqual(len(self.pool.hash_index), 1)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 1)

        # Check stats
        self.assertEqual(self.pool.stats['total_received'], 1)
        self.assertEqual(self.pool.stats['valid_received'], 1)
        self.assertEqual(self.pool.stats['invalid_received'], 0)
        self.assertEqual(self.pool.stats['duplicates'], 0)

    def test_add_submit_tx_info_duplicate_submitter(self):
        """Test addition of duplicate SubmitTxInfo with same submitter."""
        # Add first SubmitTxInfo
        success1, message1 = self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.assertTrue(success1)
        self.assertEqual(message1, "SubmitTxInfo added successfully")

        # Try to add second SubmitTxInfo from same submitter
        submit_tx_info_duplicate = self._create_mock_submit_tx_info(
            self.multi_txn1, self.test_sender, self.private_key_pem, self.public_key_pem
        )

        success2, message2 = self.pool.add_submit_tx_info(submit_tx_info_duplicate)

        self.assertFalse(success2)
        self.assertIn("has already submitted in this block", message2)

        # Check stats
        self.assertEqual(self.pool.stats['total_received'], 2)
        self.assertEqual(self.pool.stats['valid_received'], 1)
        self.assertEqual(self.pool.stats['invalid_received'], 0)
        self.assertEqual(self.pool.stats['duplicates'], 1)

    def test_add_submit_tx_info_different_submitters(self):
        """Test addition of SubmitTxInfos from different submitters."""
        # Add first SubmitTxInfo from alice
        success1, message1 = self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.assertTrue(success1)
        self.assertEqual(message1, "SubmitTxInfo added successfully")

        # Add second SubmitTxInfo from bob (different submitter)
        success2, message2 = self.pool.add_submit_tx_info(self.submit_tx_info2)
        self.assertTrue(success2)
        self.assertEqual(message2, "SubmitTxInfo added successfully")

        # Check pool contents
        self.assertEqual(len(self.pool.pool), 2)
        self.assertEqual(len(self.pool.submitter_index), 2)
        self.assertIn(self.test_sender, self.pool.submitter_index)
        self.assertIn(self.test_sender2, self.pool.submitter_index)

        # Check stats
        self.assertEqual(self.pool.stats['total_received'], 2)
        self.assertEqual(self.pool.stats['valid_received'], 2)
        self.assertEqual(self.pool.stats['invalid_received'], 0)
        self.assertEqual(self.pool.stats['duplicates'], 0)

    def test_remove_submit_tx_info(self):
        """Test removing SubmitTxInfo."""
        # Add SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info1)

        # Remove by hash
        success = self.pool.remove_submit_tx_info(self.submit_tx_info1.get_hash())

        self.assertTrue(success)
        self.assertEqual(len(self.pool.pool), 0)
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertEqual(len(self.pool.hash_index), 0)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 0)

        # Try to remove non-existent hash
        success = self.pool.remove_submit_tx_info("non_existent_hash")
        self.assertFalse(success)

    def test_get_submit_tx_infos_by_submitter(self):
        """Test getting SubmitTxInfos by submitter."""
        # Add SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info1)

        # Get by submitter
        result = self.pool.get_submit_tx_infos_by_submitter(self.test_sender)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].get_hash(), self.submit_tx_info1.get_hash())

        # Get non-existent submitter
        result = self.pool.get_submit_tx_infos_by_submitter("non_existent_submitter")
        self.assertEqual(len(result), 0)

    def test_clear_pool(self):
        """Test clearing the pool."""
        # Add multiple SubmitTxInfos from different submitters
        self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.pool.add_submit_tx_info(self.submit_tx_info2)

        # Clear pool
        self.pool.clear_pool()

        self.assertEqual(len(self.pool.pool), 0)
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertEqual(len(self.pool.hash_index), 0)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 0)

    def test_get_pool_stats(self):
        """Test getting pool statistics."""
        # Add multiple SubmitTxInfos from different submitters
        self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.pool.add_submit_tx_info(self.submit_tx_info2)

        stats = self.pool.get_pool_stats()

        self.assertEqual(stats['total_transactions'], 2)
        self.assertEqual(stats['unique_submitters'], 2)
        self.assertEqual(stats['stats']['total_received'], 2)
        self.assertEqual(stats['stats']['valid_received'], 2)

    def test_clear_pool_resets_submitter_index(self):
        """Test that clearing pool resets submitter index properly."""
        # Add SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info1)

        # Verify submitter is in index
        self.assertIn(self.test_sender, self.pool.submitter_index)

        # Clear pool
        self.pool.clear_pool()

        # Verify submitter index is cleared
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertNotIn(self.test_sender, self.pool.submitter_index)

        # Verify we can add SubmitTxInfo from same submitter again
        success, message = self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.assertTrue(success)
        self.assertEqual(message, "SubmitTxInfo added successfully")

    def test_index_rebuilding_after_removal(self):
        """Test index rebuilding after removal."""
        # Add multiple SubmitTxInfos from different submitters
        self.pool.add_submit_tx_info(self.submit_tx_info1)
        self.pool.add_submit_tx_info(self.submit_tx_info2)

        # Remove first SubmitTxInfo
        self.pool.remove_submit_tx_info(self.submit_tx_info1.get_hash())

        # Check that indices are properly rebuilt
        self.assertEqual(len(self.pool.pool), 1)
        self.assertEqual(len(self.pool.submitter_index), 1)
        self.assertEqual(len(self.pool.hash_index), 1)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 1)

        # Check that the remaining SubmitTxInfo is accessible
        result = self.pool.get_submit_tx_info_by_hash(self.submit_tx_info2.get_hash())
        self.assertIsNotNone(result)
        self.assertEqual(result.get_hash(), self.submit_tx_info2.get_hash())


if __name__ == '__main__':
    unittest.main()