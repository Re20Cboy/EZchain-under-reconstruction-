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
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


class TestTxPool(unittest.TestCase):
    """Test cases for TxPool class with SubmitTxInfo"""

    def setUp(self):
        """Set up test fixtures."""
        
        # Create temporary database file
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        

        # Create pool instance with temporary database
        
        self.pool = TxPool(self.temp_db.name)
        

        # Generate test keys
        
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = self.private_key.public_key()
        

        # Serialize keys
        
        self.private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        self.public_key_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        

        # Create test sender and recipient
        self.test_sender = "sender_test"
        self.test_recipient = "recipient_test"

        # Create test values
        self.test_value1 = Value("0x1000", 100)
        self.test_value2 = Value("0x2000", 200)

        # Create test transactions
        
        self.txn1 = Transaction.new_transaction(
            sender=self.test_sender,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )

        self.txn2 = Transaction.new_transaction(
            sender=self.test_sender,
            recipient=self.test_recipient,
            value=[self.test_value2],
            nonce=2
        )
        

        # Sign individual transactions
        
        self.txn1.sig_txn(self.private_key_pem)
        
        self.txn2.sig_txn(self.private_key_pem)
        

        # Create test MultiTransactions
        
        self.multi_txn = MultiTransactions(
            sender=self.test_sender,
            multi_txns=[self.txn1, self.txn2]
        )
        

        # Sign the MultiTransactions
        
        self.multi_txn.sig_acc_txn(self.private_key_pem)
        

        # Create test SubmitTxInfo
        
        self.submit_tx_info = SubmitTxInfo.create_from_multi_transactions(
            self.multi_txn, self.private_key_pem, self.public_key_pem
        )
        

    def tearDown(self):
        """Clean up test fixtures."""
        
        import tempfile
        import shutil

        # Stop the cleanup thread first
        
        if hasattr(self.pool, '_cleanup_thread'):
            self.pool._cleanup_thread = None

        # Force garbage collection to close any remaining connections
        
        import gc
        gc.collect()

        # Try to close any database connections more aggressively
        
        if hasattr(self.pool, 'lock'):
            try:
                with self.pool.lock:
                    
                    # Use Windows-specific approach to close file handles
                    import ctypes
                    if os.name == 'nt':
                        try:
                            import ctypes.wintypes
                            kernel32 = ctypes.windll.kernel32
                            handle = kernel32.CreateFileW(
                                self.temp_db.name,
                                0x80000000,  # GENERIC_READ
                                1,           # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                                None,
                                3,           # OPEN_EXISTING
                                0x02000000,  # FILE_FLAG_DELETE_ON_CLOSE
                                None
                            )
                            if handle != -1:  # INVALID_HANDLE_VALUE
                                kernel32.CloseHandle(handle)
                            
                        except Exception as e:
                            
                            pass
                    
            except Exception as e:
                
                pass

        # Use shutil.rmtree for more aggressive cleanup on Windows
        if os.path.exists(self.temp_db.name):
            try:
                os.unlink(self.temp_db.name)
            except PermissionError:
                # As a last resort, mark for deletion on reboot
                if os.name == 'nt':
                    try:
                        import ctypes
                        movefileex = ctypes.windll.kernel32.MoveFileExW
                        movefileex(self.temp_db.name, None, 4)  # MOVEFILE_DELAY_UNTIL_REBOOT
                    except:
                        pass
                # Or use tempfile for cleanup
                try:
                    temp_dir = os.path.dirname(self.temp_db.name)
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass

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

    def test_validate_submit_tx_info_missing_hash(self):
        """Test validation of SubmitTxInfo with missing hash."""
        # Create invalid SubmitTxInfo
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

    def test_validate_submit_tx_info_missing_submitter(self):
        """Test validation of SubmitTxInfo with missing submitter."""
        # Create invalid SubmitTxInfo
        invalid_submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info.multi_transactions_hash = "test_hash"
        invalid_submit_tx_info.submitter_address = ""
        invalid_submit_tx_info.signature = b"test_signature"
        invalid_submit_tx_info.public_key = self.public_key_pem
        invalid_submit_tx_info.submit_timestamp = "2023-01-01T00:00:00"
        invalid_submit_tx_info.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info._hash = None

        validation_result = self.pool.validate_submit_tx_info(invalid_submit_tx_info)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(validation_result.error_message, "Missing submitter_address")
        self.assertFalse(validation_result.structural_valid)

    def test_validate_submit_tx_info_missing_signature(self):
        """Test validation of SubmitTxInfo with missing signature."""
        # Create invalid SubmitTxInfo
        invalid_submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info.multi_transactions_hash = "test_hash"
        invalid_submit_tx_info.submitter_address = self.test_sender
        invalid_submit_tx_info.signature = None
        invalid_submit_tx_info.public_key = self.public_key_pem
        invalid_submit_tx_info.submit_timestamp = "2023-01-01T00:00:00"
        invalid_submit_tx_info.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info._hash = None

        validation_result = self.pool.validate_submit_tx_info(invalid_submit_tx_info)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(validation_result.error_message, "Missing signature")
        self.assertFalse(validation_result.structural_valid)

    def test_validate_submit_tx_info_invalid_timestamp(self):
        """Test validation of SubmitTxInfo with invalid timestamp."""
        # Create invalid SubmitTxInfo
        invalid_submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info.multi_transactions_hash = "test_hash"
        invalid_submit_tx_info.submitter_address = self.test_sender
        invalid_submit_tx_info.signature = b"test_signature"
        invalid_submit_tx_info.public_key = self.public_key_pem
        invalid_submit_tx_info.submit_timestamp = "invalid_timestamp"
        invalid_submit_tx_info.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info._hash = None

        validation_result = self.pool.validate_submit_tx_info(invalid_submit_tx_info)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(validation_result.error_message, "Invalid timestamp format")
        self.assertFalse(validation_result.structural_valid)

    def test_validate_submit_tx_info_valid_with_multi_transactions(self):
        """Test validation of valid SubmitTxInfo with MultiTransactions."""
        validation_result = self.pool.validate_submit_tx_info(self.submit_tx_info, self.multi_txn)

        self.assertTrue(validation_result.is_valid)
        self.assertTrue(validation_result.signature_valid)
        self.assertTrue(validation_result.structural_valid)
        self.assertTrue(validation_result.submitter_match)
        self.assertEqual(len(validation_result.duplicates_found), 0)

    def test_validate_submit_tx_info_valid_without_multi_transactions(self):
        """Test validation of valid SubmitTxInfo without MultiTransactions."""
        validation_result = self.pool.validate_submit_tx_info(self.submit_tx_info)

        self.assertTrue(validation_result.is_valid)
        self.assertTrue(validation_result.signature_valid)
        self.assertTrue(validation_result.structural_valid)
        self.assertTrue(validation_result.submitter_match)
        self.assertEqual(len(validation_result.duplicates_found), 0)

    def test_add_submit_tx_info_success(self):
        """Test successful addition of SubmitTxInfo."""
        success, message = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

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

    def test_add_submit_tx_info_invalid(self):
        """Test addition of invalid SubmitTxInfo."""
        # Create invalid SubmitTxInfo
        invalid_submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)
        invalid_submit_tx_info.multi_transactions_hash = ""
        invalid_submit_tx_info.submitter_address = self.test_sender
        invalid_submit_tx_info.signature = b"test_signature"
        invalid_submit_tx_info.public_key = self.public_key_pem
        invalid_submit_tx_info.submit_timestamp = "2023-01-01T00:00:00"
        invalid_submit_tx_info.version = SubmitTxInfo.VERSION
        invalid_submit_tx_info._hash = None

        success, message = self.pool.add_submit_tx_info(invalid_submit_tx_info)

        self.assertFalse(success)
        self.assertIn("Missing multi_transactions_hash", message)

        # Check stats
        self.assertEqual(self.pool.stats['total_received'], 1)
        self.assertEqual(self.pool.stats['valid_received'], 0)
        self.assertEqual(self.pool.stats['invalid_received'], 1)

    def test_add_submit_tx_info_duplicate(self):
        """Test addition of duplicate SubmitTxInfo with same submitter."""
        
        # Add first time
        
        success1, message1 = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)
        
        self.assertTrue(success1)

        # Add second time (duplicate submitter)
        
        success2, message2 = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)
        

        self.assertFalse(success2)
        self.assertIn("has already submitted in this block", message2)

        # Check stats
        
        self.assertEqual(self.pool.stats['total_received'], 2)
        self.assertEqual(self.pool.stats['valid_received'], 1)
        self.assertEqual(self.pool.stats['invalid_received'], 0)
        self.assertEqual(self.pool.stats['duplicates'], 1)
        

    def test_get_submit_tx_infos_by_submitter(self):
        """Test getting SubmitTxInfos by submitter."""
        # Add the test SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Get by submitter
        result = self.pool.get_submit_tx_infos_by_submitter(self.test_sender)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].get_hash(), self.submit_tx_info.get_hash())

        # Get non-existent submitter
        result = self.pool.get_submit_tx_infos_by_submitter("non_existent_submitter")
        self.assertEqual(len(result), 0)

    def test_get_submit_tx_info_by_hash(self):
        """Test getting SubmitTxInfo by hash."""
        # Add the test SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Get by hash
        result = self.pool.get_submit_tx_info_by_hash(self.submit_tx_info.get_hash())

        self.assertIsNotNone(result)
        self.assertEqual(result.get_hash(), self.submit_tx_info.get_hash())

        # Get non-existent hash
        result = self.pool.get_submit_tx_info_by_hash("non_existent_hash")
        self.assertIsNone(result)

    def test_get_submit_tx_info_by_multi_tx_hash(self):
        """Test getting SubmitTxInfo by MultiTransactions hash."""
        # Add the test SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Get by MultiTransactions hash
        result = self.pool.get_submit_tx_info_by_multi_tx_hash(self.multi_txn.digest)

        self.assertIsNotNone(result)
        self.assertEqual(result.multi_transactions_hash, self.multi_txn.digest)

        # Get non-existent MultiTransactions hash
        result = self.pool.get_submit_tx_info_by_multi_tx_hash("non_existent_hash")
        self.assertIsNone(result)

    def test_remove_submit_tx_info(self):
        """Test removing SubmitTxInfo."""
        # Add the test SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Remove by hash
        success = self.pool.remove_submit_tx_info(self.submit_tx_info.get_hash())

        self.assertTrue(success)
        self.assertEqual(len(self.pool.pool), 0)
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertEqual(len(self.pool.hash_index), 0)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 0)

        # Try to remove non-existent hash
        success = self.pool.remove_submit_tx_info("non_existent_hash")
        self.assertFalse(success)

    def test_get_pool_stats(self):
        """Test getting pool statistics."""
        # Add first SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Create another MultiTransactions and SubmitTxInfo with DIFFERENT submitter
        test_sender2 = "sender_test_2"

        # Generate new keys for different submitter
        private_key2 = ec.generate_private_key(ec.SECP256R1())
        public_key2 = private_key2.public_key()
        private_key_pem2 = private_key2.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key_pem2 = public_key2.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Create test transactions for second sender
        txn1_sender2 = Transaction.new_transaction(
            sender=test_sender2,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )
        txn1_sender2.sig_txn(private_key_pem2)

        multi_txn2 = MultiTransactions(
            sender=test_sender2,
            multi_txns=[txn1_sender2]
        )
        multi_txn2.sig_acc_txn(private_key_pem2)

        submit_tx_info2 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn2, private_key_pem2, public_key_pem2
        )
        self.pool.add_submit_tx_info(submit_tx_info2, multi_txn2)

        stats = self.pool.get_pool_stats()

        self.assertEqual(stats['total_transactions'], 2)
        self.assertEqual(stats['unique_submitters'], 2)
        self.assertEqual(stats['stats']['total_received'], 2)
        self.assertEqual(stats['stats']['valid_received'], 2)
        self.assertIn('pool_size_bytes', stats)

    def test_get_all_submit_tx_infos(self):
        """Test getting all SubmitTxInfos."""
        # Add first SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Create another MultiTransactions and SubmitTxInfo with DIFFERENT submitter
        test_sender2 = "sender_test_2"

        # Generate new keys for different submitter
        private_key2 = ec.generate_private_key(ec.SECP256R1())
        public_key2 = private_key2.public_key()
        private_key_pem2 = private_key2.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key_pem2 = public_key2.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Create test transactions for second sender
        txn1_sender2 = Transaction.new_transaction(
            sender=test_sender2,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )
        txn1_sender2.sig_txn(private_key_pem2)

        multi_txn2 = MultiTransactions(
            sender=test_sender2,
            multi_txns=[txn1_sender2]
        )
        multi_txn2.sig_acc_txn(private_key_pem2)

        submit_tx_info2 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn2, private_key_pem2, public_key_pem2
        )
        self.pool.add_submit_tx_info(submit_tx_info2, multi_txn2)

        result = self.pool.get_all_submit_tx_infos()

        self.assertEqual(len(result), 2)
        # Check that we get copies, not references
        self.assertIsNot(result[0], self.pool.pool[0])
        self.assertIsNot(result[1], self.pool.pool[1])

    def test_clear_pool(self):
        """Test clearing the pool."""
        # Add first SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Create another SubmitTxInfo with DIFFERENT submitter and add
        test_sender2 = "sender_test_2"

        # Generate new keys for different submitter
        private_key2 = ec.generate_private_key(ec.SECP256R1())
        public_key2 = private_key2.public_key()
        private_key_pem2 = private_key2.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key_pem2 = public_key2.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Create test transactions for second sender
        txn1_sender2 = Transaction.new_transaction(
            sender=test_sender2,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )
        txn1_sender2.sig_txn(private_key_pem2)

        multi_txn2 = MultiTransactions(
            sender=test_sender2,
            multi_txns=[txn1_sender2]
        )
        multi_txn2.sig_acc_txn(private_key_pem2)

        submit_tx_info2 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn2, private_key_pem2, public_key_pem2
        )
        self.pool.add_submit_tx_info(submit_tx_info2, multi_txn2)

        # Clear pool
        self.pool.clear_pool()

        self.assertEqual(len(self.pool.pool), 0)
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertEqual(len(self.pool.hash_index), 0)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 0)

    def test_thread_safety(self):
        """Test thread safety of pool operations."""
        
        import threading
        import time

        # Create multiple threads that add SubmitTxInfos
        results = []
        errors = []

        def worker(thread_id):
            
            try:
                # Create unique MultiTransactions and SubmitTxInfo for each thread
                unique_sender = f"sender_{thread_id}"

                # Create unique transactions
                test_txn = Transaction.new_transaction(
                    sender=unique_sender,
                    recipient=self.test_recipient,
                    value=[self.test_value1],
                    nonce=thread_id
                )
                test_txn.sig_txn(self.private_key_pem)

                # Create MultiTransactions
                multi_txn = MultiTransactions(
                    sender=unique_sender,
                    multi_txns=[test_txn]
                )
                multi_txn.sig_acc_txn(self.private_key_pem)

                # Create SubmitTxInfo
                submit_tx_info = SubmitTxInfo.create_from_multi_transactions(
                    multi_txn, self.private_key_pem, self.public_key_pem
                )

                
                success, message = self.pool.add_submit_tx_info(submit_tx_info, multi_txn)
                
                results.append((thread_id, success, message))

            except Exception as e:
                
                errors.append((thread_id, str(e)))

        # Start multiple threads
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        
        for t in threads:
            
            t.join()
            

        # Check results
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)

        # All should have succeeded
        for thread_id, success, message in results:
            self.assertTrue(success)

        # Check final pool size
        self.assertEqual(len(self.pool.pool), 10)

    def test_database_persistence(self):
        """Test database persistence."""
        
        # Add SubmitTxInfo
        
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Create new pool instance with same database
        
        new_pool = TxPool(self.temp_db.name)
        

        # Check that data persists
        self.assertEqual(len(new_pool.pool), 1)
        self.assertEqual(len(new_pool.submitter_index), 1)
        self.assertEqual(len(new_pool.hash_index), 1)
        self.assertEqual(len(new_pool.multi_tx_hash_index), 1)

        # Check stats
        self.assertEqual(new_pool.stats['total_received'], 1)
        self.assertEqual(new_pool.stats['valid_received'], 1)

    def test_index_rebuilding(self):
        """Test index rebuilding after removal."""
        # Add first SubmitTxInfo
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Create second SubmitTxInfo with DIFFERENT submitter
        test_sender2 = "sender_test_2"

        # Generate new keys for different submitter
        private_key2 = ec.generate_private_key(ec.SECP256R1())
        public_key2 = private_key2.public_key()
        private_key_pem2 = private_key2.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key_pem2 = public_key2.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Create test transactions for second sender
        txn1_sender2 = Transaction.new_transaction(
            sender=test_sender2,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )
        txn1_sender2.sig_txn(private_key_pem2)

        multi_txn2 = MultiTransactions(
            sender=test_sender2,
            multi_txns=[txn1_sender2]
        )
        multi_txn2.sig_acc_txn(private_key_pem2)

        submit_tx_info2 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn2, private_key_pem2, public_key_pem2
        )
        self.pool.add_submit_tx_info(submit_tx_info2, multi_txn2)

        # Remove first SubmitTxInfo
        self.pool.remove_submit_tx_info(self.submit_tx_info.get_hash())

        # Check that indices are properly rebuilt
        self.assertEqual(len(self.pool.pool), 1)
        self.assertEqual(len(self.pool.submitter_index), 1)
        self.assertEqual(len(self.pool.hash_index), 1)
        self.assertEqual(len(self.pool.multi_tx_hash_index), 1)

        # Check that the remaining SubmitTxInfo is accessible
        result = self.pool.get_submit_tx_info_by_hash(submit_tx_info2.get_hash())
        self.assertIsNotNone(result)
        self.assertEqual(result.get_hash(), submit_tx_info2.get_hash())

    def test_submitter_uniqueness_enforcement(self):
        """Test that each submitter can only submit once per block."""
        # Add first SubmitTxInfo from test_sender
        success1, message1 = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)
        self.assertTrue(success1)
        self.assertEqual(message1, "SubmitTxInfo added successfully")

        # Create different MultiTransactions from same submitter
        txn3 = Transaction.new_transaction(
            sender=self.test_sender,
            recipient=self.test_recipient,
            value=[self.test_value2],
            nonce=3
        )
        txn3.sig_txn(self.private_key_pem)

        multi_txn3 = MultiTransactions(
            sender=self.test_sender,
            multi_txns=[txn3]
        )
        multi_txn3.sig_acc_txn(self.private_key_pem)

        submit_tx_info3 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn3, self.private_key_pem, self.public_key_pem
        )

        # Try to add second SubmitTxInfo from same submitter - should fail
        success2, message2 = self.pool.add_submit_tx_info(submit_tx_info3, multi_txn3)
        self.assertFalse(success2)
        self.assertIn("has already submitted in this block", message2)

        # Verify only first SubmitTxInfo is in pool
        self.assertEqual(len(self.pool.pool), 1)
        self.assertEqual(self.pool.pool[0].get_hash(), self.submit_tx_info.get_hash())

    def test_different_submitters_allowed(self):
        """Test that different submitters can both submit in the same block."""
        # Add first SubmitTxInfo from test_sender
        success1, _ = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)
        self.assertTrue(success1)

        # Create SubmitTxInfo from different submitter
        test_sender2 = "sender_test_2"

        # Generate new keys for different submitter
        private_key2 = ec.generate_private_key(ec.SECP256R1())
        public_key2 = private_key2.public_key()
        private_key_pem2 = private_key2.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key_pem2 = public_key2.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Create test transactions for second sender
        txn1_sender2 = Transaction.new_transaction(
            sender=test_sender2,
            recipient=self.test_recipient,
            value=[self.test_value1],
            nonce=1
        )
        txn1_sender2.sig_txn(private_key_pem2)

        multi_txn2 = MultiTransactions(
            sender=test_sender2,
            multi_txns=[txn1_sender2]
        )
        multi_txn2.sig_acc_txn(private_key_pem2)

        submit_tx_info2 = SubmitTxInfo.create_from_multi_transactions(
            multi_txn2, private_key_pem2, public_key_pem2
        )

        # Add second SubmitTxInfo from different submitter - should succeed
        success2, message2 = self.pool.add_submit_tx_info(submit_tx_info2, multi_txn2)
        self.assertTrue(success2)
        self.assertEqual(message2, "SubmitTxInfo added successfully")

        # Verify both SubmitTxInfos are in pool
        self.assertEqual(len(self.pool.pool), 2)
        self.assertEqual(len(self.pool.submitter_index), 2)

        # Verify both submitters are in submitter_index
        self.assertIn(self.test_sender, self.pool.submitter_index)
        self.assertIn(test_sender2, self.pool.submitter_index)

    def test_clear_pool_resets_submitter_index(self):
        """Test that clearing pool resets submitter index properly."""
        # Add SubmitTxInfo from test_sender
        self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)

        # Verify submitter is in index
        self.assertIn(self.test_sender, self.pool.submitter_index)

        # Clear pool
        self.pool.clear_pool()

        # Verify submitter index is cleared
        self.assertEqual(len(self.pool.submitter_index), 0)
        self.assertNotIn(self.test_sender, self.pool.submitter_index)

        # Verify we can add SubmitTxInfo from same submitter again
        success, message = self.pool.add_submit_tx_info(self.submit_tx_info, self.multi_txn)
        self.assertTrue(success)
        self.assertEqual(message, "SubmitTxInfo added successfully")


if __name__ == '__main__':
    # 设置更详细的日志输出
    

    # 运行特定测试来定位问题
    import sys
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        
        suite = unittest.TestLoader().loadTestsFromName(test_name, __name__)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
    else:
        # 运行所有测试
        
        unittest.main(verbosity=2)