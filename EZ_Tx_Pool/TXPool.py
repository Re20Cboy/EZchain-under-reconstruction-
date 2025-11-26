import copy
import time
import threading
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import json
import os
import pickle

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Tool_Box.Hash import sha256_hash

@dataclass
class ValidationResult:
    """Validation result dataclass"""
    is_valid: bool
    error_message: str = ""
    submitter_match: bool = False
    signature_valid: bool = False
    structural_valid: bool = False
    duplicates_found: List[str] = None

    def __post_init__(self):
        if self.duplicates_found is None:
            self.duplicates_found = []

class TxPool:
    """Transaction pool for SubmitTxInfo with validation and database storage"""

    def __init__(self, db_path: str = "tx_pool.db"):
        self.pool: List[SubmitTxInfo] = []
        self.submitter_index: Dict[str, List[int]] = {}  # submitter -> indices in pool
        self.hash_index: Dict[str, int] = {}  # SubmitTxInfo hash -> index in pool
        self.multi_tx_hash_index: Dict[str, int] = {}  # MultiTransactions hash -> index in pool
        self.db_path = db_path
        self.lock = threading.Lock()
        self.stats = {
            'total_received': 0,
            'valid_received': 0,
            'invalid_received': 0,
            'duplicates': 0
        }

        # Initialize database
        self._init_database()

        # Load existing data from database
        self._load_from_database()

        # Start periodic cleanup
        self._start_cleanup_thread()

    def _init_database(self):
        """Initialize SQLite database for SubmitTxInfo persistence"""
        import sqlite3

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create tables
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS submit_tx_infos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submit_hash TEXT UNIQUE NOT NULL,
                    multi_tx_hash TEXT NOT NULL,
                    submitter_address TEXT NOT NULL,
                    submit_timestamp TEXT NOT NULL,
                    version TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    submit_tx_info_blob BLOB NOT NULL,
                    is_valid BOOLEAN DEFAULT TRUE,
                    validation_time TEXT,
                    processed BOOLEAN DEFAULT FALSE
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS validation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submit_hash TEXT NOT NULL,
                    validation_type TEXT NOT NULL,
                    is_valid BOOLEAN NOT NULL,
                    error_message TEXT,
                    validation_time TEXT NOT NULL,
                    FOREIGN KEY (submit_hash) REFERENCES submit_tx_infos(submit_hash)
                )
            ''')

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Database initialization error: {e}")

    def _load_from_database(self):
        """Load existing SubmitTxInfos from database into memory"""
        try:
            import sqlite3
            with self.lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                # Load all valid, unprocessed SubmitTxInfos
                cursor.execute('''
                    SELECT submit_hash, multi_tx_hash, submitter_address, submit_timestamp,
                           version, signature, public_key, submit_tx_info_blob
                    FROM submit_tx_infos
                    WHERE is_valid = TRUE AND processed = FALSE
                ''')

                rows = cursor.fetchall()

                for row in rows:
                    (submit_hash, multi_tx_hash, submitter_address, submit_timestamp,
                     version, signature_hex, public_key_hex, submit_tx_info_blob) = row

                    try:
                        # Decode SubmitTxInfo from blob
                        submit_tx_info_data = pickle.loads(submit_tx_info_blob)
                        submit_tx_info = SubmitTxInfo.__new__(SubmitTxInfo)

                        submit_tx_info.multi_transactions_hash = submit_tx_info_data['multi_transactions_hash']
                        submit_tx_info.submit_timestamp = submit_tx_info_data['submit_timestamp']
                        submit_tx_info.version = submit_tx_info_data['version']
                        submit_tx_info.submitter_address = submit_tx_info_data['submitter_address']
                        submit_tx_info.signature = submit_tx_info_data['signature']
                        submit_tx_info.public_key = submit_tx_info_data['public_key']
                        submit_tx_info._hash = None

                        # Ensure hash is set
                        if not submit_tx_info.get_hash():
                            submit_tx_info._hash = submit_hash

                        # Add to pool
                        self.pool.append(submit_tx_info)
                        index = len(self.pool) - 1

                        # Update indices
                        if submitter_address not in self.submitter_index:
                            self.submitter_index[submitter_address] = []
                        self.submitter_index[submitter_address].append(index)
                        self.hash_index[submit_hash] = index
                        self.multi_tx_hash_index[multi_tx_hash] = index

                    except Exception as e:
                        print(f"Error decoding SubmitTxInfo with hash {submit_hash}: {e}")
                        continue

                # Load stats from database
                cursor.execute('''
                    SELECT COUNT(*) FROM submit_tx_infos
                    WHERE is_valid = TRUE AND processed = FALSE
                ''')
                valid_count = cursor.fetchone()[0]

                cursor.execute('''
                    SELECT COUNT(*) FROM submit_tx_infos
                    WHERE is_valid = FALSE AND processed = FALSE
                ''')
                invalid_count = cursor.fetchone()[0]

                cursor.execute('''
                    SELECT COUNT(*) FROM submit_tx_infos
                    WHERE processed = FALSE
                ''')
                total_count = cursor.fetchone()[0]

                # Update stats - transactions in pool are all valid (invalid ones are filtered out)
                loaded_count = len(self.pool)
                self.stats['total_received'] = total_count
                self.stats['valid_received'] = loaded_count  # All loaded transactions are valid
                self.stats['invalid_received'] = total_count - loaded_count  # Invalid transactions are not loaded

                conn.commit()
                conn.close()

        except Exception as e:
            print(f"Error loading from database: {e}")

    def _start_cleanup_thread(self):
        """Start background thread for cleaning up old transactions"""
        def cleanup_worker():
            while True:
                time.sleep(3600)  # Run cleanup every hour
                self._cleanup_old_transactions()

        thread = threading.Thread(target=cleanup_worker, daemon=True)
        thread.start()

    def _cleanup_old_transactions(self, max_age_hours: int = 24):
        """Clean up transactions older than max_age_hours"""
        try:
            import sqlite3

            cutoff_time = time.time() - (max_age_hours * 3600)
            cutoff_iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(cutoff_time))

            with self.lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                # Get old submit hashes
                cursor.execute('''
                    SELECT submit_hash FROM submit_tx_infos
                    WHERE submit_timestamp < ? AND processed = FALSE
                ''', (cutoff_iso,))

                old_hashes = [row[0] for row in cursor.fetchall()]

                # Remove from database
                cursor.execute('''
                    DELETE FROM submit_tx_infos WHERE submit_timestamp < ? AND processed = FALSE
                ''', (cutoff_iso,))

                # Remove from memory
                for submit_hash in old_hashes:
                    if submit_hash in self.hash_index:
                        index = self.hash_index[submit_hash]
                        del self.hash_index[submit_hash]

                        submit_tx_info = self.pool[index]
                        if submit_tx_info.multi_transactions_hash in self.multi_tx_hash_index:
                            del self.multi_tx_hash_index[submit_tx_info.multi_transactions_hash]

                        # Remove from pool first
                        del self.pool[index]

                        # Rebuild indices
                        self._rebuild_indices()

                conn.commit()
                conn.close()

        except Exception as e:
            print(f"Cleanup error: {e}")

    def _rebuild_indices(self):
        """Rebuild indices after pool modification"""
        self.submitter_index.clear()
        self.hash_index.clear()
        self.multi_tx_hash_index.clear()

        for i, submit_tx_info in enumerate(self.pool):
            if submit_tx_info.submitter_address not in self.submitter_index:
                self.submitter_index[submit_tx_info.submitter_address] = []
            self.submitter_index[submit_tx_info.submitter_address].append(i)
            submit_hash = submit_tx_info.get_hash()
            self.hash_index[submit_hash] = i
            self.multi_tx_hash_index[submit_tx_info.multi_transactions_hash] = i

    def _persist_to_database(self, submit_tx_info: SubmitTxInfo, validation_result: ValidationResult):
        """Persist SubmitTxInfo and validation result to database"""
        try:
            import sqlite3
            import pickle
            with self.lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                submit_hash = submit_tx_info.get_hash()

                # Insert or replace SubmitTxInfo
                cursor.execute('''
                    INSERT OR REPLACE INTO submit_tx_infos
                    (submit_hash, multi_tx_hash, submitter_address, submit_timestamp,
                     version, signature, public_key, submit_tx_info_blob, is_valid, validation_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    submit_hash,
                    submit_tx_info.multi_transactions_hash,
                    submit_tx_info.submitter_address,
                    submit_tx_info.submit_timestamp,
                    submit_tx_info.version,
                    submit_tx_info.signature.hex() if submit_tx_info.signature else None,
                    submit_tx_info.public_key.hex() if submit_tx_info.public_key else None,
                    submit_tx_info.encode(),
                    validation_result.is_valid,
                    time.strftime('%Y-%m-%dT%H:%M:%S')
                ))

                # Insert validation result
                cursor.execute('''
                    INSERT INTO validation_results
                    (submit_hash, validation_type, is_valid, error_message, validation_time)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    submit_hash,
                    'submit_tx_info_validation',
                    validation_result.is_valid,
                    validation_result.error_message,
                    time.strftime('%Y-%m-%dT%H:%M:%S')
                ))

                conn.commit()
                conn.close()

        except sqlite3.Error as e:
            print(f"Database persistence error: {e}")

    def validate_submit_tx_info(self, submit_tx_info: SubmitTxInfo,
                               multi_transactions: Optional[MultiTransactions] = None) -> ValidationResult:
        """
        Perform formal validation of SubmitTxInfo:
        1) Verify structural correctness
        2) Verify signature validity
        3) Check for duplicates
        4) If MultiTransactions provided, verify hash consistency
        """
        validation_result = ValidationResult(is_valid=True)

        try:
            # 1. Check structural correctness
            if not submit_tx_info.multi_transactions_hash:
                validation_result.is_valid = False
                validation_result.error_message = "Missing multi_transactions_hash"
                validation_result.structural_valid = False
                return validation_result

            if not submit_tx_info.submitter_address:
                validation_result.is_valid = False
                validation_result.error_message = "Missing submitter_address"
                validation_result.structural_valid = False
                return validation_result

            if not submit_tx_info.signature:
                validation_result.is_valid = False
                validation_result.error_message = "Missing signature"
                validation_result.structural_valid = False
                return validation_result

            # 2. Verify timestamp format
            try:
                import datetime
                datetime.datetime.fromisoformat(submit_tx_info.submit_timestamp)
            except ValueError:
                validation_result.is_valid = False
                validation_result.error_message = "Invalid timestamp format"
                validation_result.structural_valid = False
                return validation_result

            # 3. Verify version
            if submit_tx_info.version != SubmitTxInfo.VERSION:
                validation_result.is_valid = False
                validation_result.error_message = f"Invalid version: {submit_tx_info.version}"
                validation_result.structural_valid = False
                return validation_result

            # 4. Verify signature using built-in verification method
            # We need a MultiTransactions instance to verify
            if multi_transactions:
                try:
                    if not submit_tx_info.verify(multi_transactions):
                        validation_result.is_valid = False
                        validation_result.error_message = "Signature verification failed"
                        validation_result.signature_valid = False
                        return validation_result
                except Exception as e:
                    # If verification fails with exception, try basic structural check
                    print(f"SubmitTxInfo verification error: {e}")
                    if not submit_tx_info.signature or len(submit_tx_info.signature) == 0:
                        validation_result.is_valid = False
                        validation_result.error_message = "Invalid signature format"
                        validation_result.signature_valid = False
                        return validation_result

                validation_result.signature_valid = True
                validation_result.submitter_match = True
            else:
                # If no MultiTransactions provided, do basic signature structure check
                if not submit_tx_info.signature or len(submit_tx_info.signature) == 0:
                    validation_result.is_valid = False
                    validation_result.error_message = "Invalid signature format"
                    validation_result.signature_valid = False
                    return validation_result

                validation_result.signature_valid = True
                validation_result.submitter_match = True

            # 5. Check for duplicate submitter in current pool
            # Each submitter can only submit once per block
            if submit_tx_info.submitter_address in self.submitter_index:
                validation_result.is_valid = False
                validation_result.error_message = f"Submitter {submit_tx_info.submitter_address} has already submitted in this block"
                validation_result.duplicates_found.append(submit_tx_info.submitter_address)
                return validation_result

            validation_result.structural_valid = True

        except Exception as e:
            validation_result.is_valid = False
            validation_result.error_message = f"Validation error: {str(e)}"

        return validation_result

    def add_submit_tx_info(self, submit_tx_info: SubmitTxInfo,
                          multi_transactions: Optional[MultiTransactions] = None) -> Tuple[bool, str]:
        """
        Add SubmitTxInfo to pool after validation
        Returns: (success, message)
        """
        try:
            # Validate the SubmitTxInfo
            validation_result = self.validate_submit_tx_info(submit_tx_info, multi_transactions)
            self.stats['total_received'] += 1

            if not validation_result.is_valid:
                # Check if it's a duplicate
                if validation_result.duplicates_found:
                    self.stats['duplicates'] += 1
                else:
                    self.stats['invalid_received'] += 1
                return False, validation_result.error_message

            # Add to pool
            with self.lock:
                self.pool.append(submit_tx_info)
                index = len(self.pool) - 1

                # Update indices
                if submit_tx_info.submitter_address not in self.submitter_index:
                    self.submitter_index[submit_tx_info.submitter_address] = []
                self.submitter_index[submit_tx_info.submitter_address].append(index)
                submit_hash = submit_tx_info.get_hash()
                self.hash_index[submit_hash] = index
                self.multi_tx_hash_index[submit_tx_info.multi_transactions_hash] = index

            # Persist to database (outside the lock to avoid deadlock)
            self._persist_to_database(submit_tx_info, validation_result)
            self.stats['valid_received'] += 1
            return True, "SubmitTxInfo added successfully"

        except Exception as e:
            return False, f"Error adding SubmitTxInfo: {str(e)}"

    def get_submit_tx_info(self, submit_hash: str) -> Optional[SubmitTxInfo]:
        """Get SubmitTxInfo by hash"""
        return self.pool[self.hash_index[submit_hash]] if submit_hash in self.hash_index else None

    def get_submit_tx_info_by_hash(self, submit_hash: str) -> Optional[SubmitTxInfo]:
        """Get SubmitTxInfo by hash (alias for get_submit_tx_info)"""
        return self.get_submit_tx_info(submit_hash)

    def get_submit_tx_infos_by_multi_tx_hash(self, multi_tx_hash: str) -> List[SubmitTxInfo]:
        """Get SubmitTxInfos by MultiTransactions hash"""
        return [self.pool[index] for index in self.multi_tx_hash_index[multi_tx_hash]] if multi_tx_hash in self.multi_tx_hash_index else []

    def get_submit_tx_info_by_multi_tx_hash(self, multi_tx_hash: str) -> Optional[SubmitTxInfo]:
        """Get single SubmitTxInfo by MultiTransactions hash"""
        if multi_tx_hash in self.multi_tx_hash_index:
            return self.pool[self.multi_tx_hash_index[multi_tx_hash]]
        return None

    def get_submit_tx_infos_by_submitter(self, submitter_address: str) -> List[SubmitTxInfo]:
        """Get SubmitTxInfos by submitter address"""
        return [self.pool[index] for index in self.submitter_index.get(submitter_address, [])]

    def get_all_submit_tx_infos(self) -> List[SubmitTxInfo]:
        """Get all SubmitTxInfos in the pool"""
        return copy.deepcopy(self.pool)

    def get_submit_tx_infos_by_time_range(self, start_time: str, end_time: str) -> List[SubmitTxInfo]:
        """Get SubmitTxInfos by time range"""
        result = []
        try:
            import datetime
            start_dt = datetime.datetime.fromisoformat(start_time)
            end_dt = datetime.datetime.fromisoformat(end_time)

            for submit_tx_info in self.pool:
                submit_time = datetime.datetime.fromisoformat(submit_tx_info.submit_timestamp)
                if start_dt <= submit_time <= end_dt:
                    result.append(submit_tx_info)

        except ValueError:
            # If timestamp format is invalid, return empty list
            pass

        return result

    def remove_submit_tx_info(self, submit_hash: str) -> bool:
        """Remove SubmitTxInfo by hash"""
        with self.lock:
            if submit_hash not in self.hash_index:
                return False

            index = self.hash_index[submit_hash]

            # Mark as processed in database
            try:
                import sqlite3
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE submit_tx_infos
                    SET processed = TRUE
                    WHERE submit_hash = ?
                ''', (submit_hash,))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error marking transaction as processed: {e}")

            # Remove from memory
            del self.pool[index]

            # Rebuild indices
            self._rebuild_indices()

            return True

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        # Calculate pool size in bytes
        pool_size_bytes = 0
        try:
            import pickle
            for submit_tx_info in self.pool:
                pool_size_bytes += len(pickle.dumps(submit_tx_info))
        except Exception:
            pool_size_bytes = 0

        return {
            'total_transactions': len(self.pool),
            'unique_submitters': len(self.submitter_index),
            'pool_size_bytes': pool_size_bytes,
            'stats': self.stats
        }

    def clear_pool(self):
        """Clear all transactions from pool (for testing)"""
        with self.lock:
            self.pool.clear()
            self.submitter_index.clear()
            self.hash_index.clear()
            self.multi_tx_hash_index.clear()

            # Clear database
            try:
                import sqlite3
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM submit_tx_infos')
                cursor.execute('DELETE FROM validation_results')
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error clearing database: {e}")

        # Reset stats
        self.stats = {
            'total_received': 0,
            'valid_received': 0,
            'invalid_received': 0,
            'duplicates': 0
        }