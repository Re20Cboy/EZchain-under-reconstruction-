"""
EZChain Account Node Implementation

This module implements the core account node functionality for the EZChain blockchain system.
The account acts as a wallet-like entity that manages values, creates transactions, and maintains
VPBs (Verification Proof Balances) in a distributed manner.

Key Features:
- Local VPB maintenance
- Transaction creation and signing
- Transaction reception and verification (framework ready)
- Value management with state tracking
- Integration with existing EZChain modules
"""

import threading
import json
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# Core EZChain imports
from EZ_Value.Value import Value, ValueState
from EZ_Value.AccountValueCollection import AccountValueCollection
from EZ_Value.AccountPickValues import AccountPickValues
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
# TransactionPool is used by consensus nodes, not account nodes
# from EZ_Transaction_Pool.TransactionPool import TransactionPool
from EZ_VPB.VPBPairs import VPBpair
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_Tool_Box.Hash import hash


class Account:
    """
    EZChain Account Node

    Represents an account/wallet in the EZChain blockchain system. Each account maintains
    its own VPBs, creates transactions, and participates in the distributed validation network.
    """

    def __init__(self, address: str, private_key_pem: bytes, public_key_pem: bytes,
                 name: Optional[str] = None):
        """
        Initialize an EZChain account.

        Args:
            address: Account address (identifier)
            private_key_pem: PEM encoded private key for signing
            public_key_pem: PEM encoded public key for verification
            name: Optional human-readable name for the account
        """
        self.address = address
        self.name = name or f"Account_{address[:8]}"
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem

        # Initialize core components
        self.value_collection = AccountValueCollection(address)
        self.value_selector = AccountPickValues(address, self.value_collection)
        self.transaction_creator = CreateMultiTransactions(address, self.value_collection)

        # Account nodes don't maintain their own transaction pool
        # They submit transactions to consensus nodes' pools
        self.transaction_pool_url = None  # Optional: URL to submit transactions

        # VPB management
        from EZ_VPB.VPBPairs import VPBManager
        self.vpb_manager = VPBManager()
        self.vpb_lock = threading.RLock()

        # Set lock for VPB manager
        self.vpb_manager.set_lock(self.vpb_lock)

        # Account metadata
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        # Security: Use secure signature handler
        self.signature_handler = secure_signature_handler

        # Transaction history tracking
        self.transaction_history: List[Dict] = []
        self.history_lock = threading.RLock()

        print(f"Account {self.name} ({address}) initialized successfully")

    
    def get_all_balances(self) -> Dict[str, int]:
        """
        Get balances broken down by state.

        Returns:
            Dictionary with balances by state
        """
        balances = {}
        for state in ValueState:
            balances[state.name] = self.get_balance(state)
        return balances

    def get_values(self, state: Optional[ValueState] = None) -> List[Value]:
        """
        Get values from the account.

        Args:
            state: Optional state filter

        Returns:
            List of values
        """
        if state is None:
            return self.value_collection.get_all_values()
        return self.value_collection.find_by_state(state)

    def add_values(self, values: List[Value], proofs: Optional[List] = None,
                   block_indices: Optional[List] = None, position: str = "end") -> int:
        """
        Add values to the account collection with associated VPB information.

        Args:
            values: List of values to add
            proofs: List of proofs corresponding to values (optional)
            block_indices: List of block indices corresponding to values (optional)
            position: Where to add values ("start" or "end")

        Returns:
            Number of values added
        """
        added_count = 0

        # Ensure proofs and block_indices match values length if provided
        if proofs is not None and len(proofs) != len(values):
            raise ValueError("Length of proofs must match length of values")
        if block_indices is not None and len(block_indices) != len(values):
            raise ValueError("Length of block_indices must match length of values")

        for i, value in enumerate(values):
            try:
                # Add to the main value collection
                self.value_collection.add_value(value, position)

                # Add VPB information if provided
                if proofs is not None and block_indices is not None:
                    from EZ_BlockIndex import BlockIndexList
                    block_index_lst = BlockIndexList(block_indices[i], owner=self.address)
                    self.vpb_manager.add_vpb(value, proofs[i], block_index_lst)
                    print(f"Added value with {value.value_num} units and VPB to {self.name}")
                else:
                    print(f"Added value with {value.value_num} units to {self.name}")

                added_count += 1
            except Exception as e:
                print(f"Failed to add value: {e}")

        self.last_activity = datetime.now()
        return added_count

    def add_value_with_vpb(self, value: Value, proofs, block_index_lst) -> bool:
        """
        Add a single value with its VPB information.

        Args:
            value: Value object to add
            proofs: Proofs object
            block_index_lst: BlockIndexList object

        Returns:
            True if added successfully
        """
        try:
            # Add to value collection
            if self.value_collection.add_value(value):
                # Add VPB information
                success = self.vpb_manager.add_vpb(value, proofs, block_index_lst)
                if success:
                    print(f"Added value with {value.value_num} units and VPB to {self.name}")
                    self.last_activity = datetime.now()
                return success
            return False
        except Exception as e:
            print(f"Failed to add value with VPB: {e}")
            return False

    def create_batch_transactions(self, transaction_requests: List[Dict],
                                reference: Optional[str] = None) -> Optional[Dict]:
        """
        Create multiple transactions as a batch using CreateMultiTransactions.

        Args:
            transaction_requests: List of transaction requests with 'recipient' and 'amount'
            reference: Optional transaction reference

        Returns:
            Multi-transaction dictionary or None if failed
        """
        try:
            # Use CreateMultiTransactions to handle the complete batch transaction creation
            multi_transaction_result = self.transaction_creator.create_multi_transactions(
                transaction_requests=transaction_requests,
                private_key_pem=self.private_key_pem
            )

            if multi_transaction_result:
                # Record in history
                self._record_multi_transaction(multi_transaction_result, "batch_created", reference)

                multi_txn_hash = multi_transaction_result["multi_transactions"].digest
                print(f"Batch multi-transaction created with {multi_transaction_result['transaction_count']} transactions: {multi_txn_hash[:16] if multi_txn_hash else 'N/A'}...")
                return multi_transaction_result
            else:
                print(f"Failed to create batch multi-transaction")
                return None

        except Exception as e:
            print(f"Failed to create batch transactions: {e}")
            return None

    def confirm_multi_transaction(self, multi_txn_result: Dict) -> bool:
        """
        Confirm a multi-transaction and update value states.

        Args:
            multi_txn_result: Result from create_multi_transactions method

        Returns:
            True if confirmation successful, False otherwise
        """
        try:
            success = self.transaction_creator.confirm_multi_transactions(multi_txn_result)

            if success:
                # Record in history
                self._record_multi_transaction(multi_txn_result, "confirmed")
                print(f"Multi-transaction confirmed and value states updated")

                # Update last activity
                self.last_activity = datetime.now()

            return success

        except Exception as e:
            print(f"Failed to confirm multi-transaction: {e}")
            return False

    def submit_multi_transaction(self, multi_txn_result: Dict, transaction_pool=None) -> bool:
        """
        Submit a multi-transaction to the transaction pool.

        Args:
            multi_txn_result: Multi-transaction result from creation methods
            transaction_pool: Optional transaction pool connection

        Returns:
            True if submission successful, False otherwise
        """
        try:
            if transaction_pool is not None:
                # Use CreateMultiTransactions submission method
                success, message = self.transaction_creator.submit_to_transaction_pool(
                    multi_txn_result, transaction_pool, self.public_key_pem
                )

                if success:
                    # Record in history
                    self._record_multi_transaction(multi_txn_result, "submitted")
                    print(f"Multi-transaction submitted to transaction pool: {message}")
                    self.last_activity = datetime.now()
                else:
                    print(f"Failed to submit multi-transaction: {message}")

                return success
            else:
                # Simulate submission (for testing)
                multi_txn = multi_txn_result["multi_transactions"]
                print(f"Multi-transaction ready for network submission: {multi_txn.digest[:16] if multi_txn.digest else 'N/A'}...")

                # Record in history
                self._record_multi_transaction(multi_txn_result, "submitted")
                return True

        except Exception as e:
            print(f"Error submitting multi-transaction: {e}")
            return False

    def get_balance(self, state: ValueState = ValueState.UNSPENT) -> int:
        """
        Get account balance for values in a specific state.

        Args:
            state: Value state to calculate balance for (default: UNSPENT)

        Returns:
            Total balance amount
        """
        if state == ValueState.UNSPENT:
            # Use CreateMultiTransactions method for UNSPENT balance
            try:
                return self.transaction_creator.get_account_balance()
            except Exception as e:
                print(f"Error getting balance via CreateMultiTransactions: {e}")

        # Fallback to original method for other states or if CreateMultiTransactions fails
        values = self.value_collection.find_by_state(state)
        return sum(value.value_num for value in values)

    def get_available_balance(self) -> int:
        """
        Get current available balance using CreateMultiTransactions method.

        Returns:
            Available balance amount
        """
        try:
            return self.transaction_creator.get_account_balance()
        except Exception as e:
            print(f"Error getting available balance: {e}")
            # Fallback to original method
            values = self.value_collection.find_by_state(ValueState.UNSPENT)
            return sum(value.value_num for value in values)

    def get_account_integrity(self) -> bool:
        """
        Validate account integrity using CreateMultiTransactions method.

        Returns:
            True if account is valid, False otherwise
        """
        try:
            return self.transaction_creator.validate_account_integrity()
        except Exception as e:
            print(f"Error validating account integrity: {e}")
            return False

    def cleanup_confirmed_values(self) -> int:
        """
        Clean up confirmed values using CreateMultiTransactions method.

        Returns:
            Number of cleaned up values
        """
        try:
            return self.transaction_creator.cleanup_confirmed_values()
        except Exception as e:
            print(f"Error cleaning up confirmed values: {e}")
            return 0

    def verify_multi_transaction_signature(self, multi_txn_result: Dict) -> bool:
        """
        Verify a multi-transaction signature using the account's public key.

        Args:
            multi_txn_result: Multi-transaction result containing multi_transactions object

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            multi_txn = multi_txn_result.get("multi_transactions")
            if not multi_txn:
                print("No multi_transactions object found in result")
                return False

            # Use CreateMultiTransactions verification method
            return self.transaction_creator.verify_multi_transactions_signature(
                multi_txn,
                self.public_key_pem
            )

        except Exception as e:
            print(f"Failed to verify multi-transaction signature: {e}")
            return False

    def verify_all_transaction_signatures(self, multi_txn_result: Dict) -> Dict[str, bool]:
        """
        Verify all individual transaction signatures within a multi-transaction.

        Args:
            multi_txn_result: Multi-transaction result containing multi_transactions object

        Returns:
            Dictionary mapping transaction indices to verification results
        """
        try:
            multi_txn = multi_txn_result.get("multi_transactions")
            if not multi_txn:
                print("No multi_transactions object found in result")
                return {}

            # Use CreateMultiTransactions method to verify all signatures
            return self.transaction_creator.verify_all_transaction_signatures(
                multi_txn,
                self.public_key_pem
            )

        except Exception as e:
            print(f"Failed to verify all transaction signatures: {e}")
            return {}

    
    def set_transaction_pool_url(self, pool_url: str):
        """
        Set the URL for transaction pool submission (future network integration).

        Args:
            pool_url: URL of consensus node's transaction pool API
        """
        self.transaction_pool_url = pool_url
        print(f"Transaction pool URL set: {pool_url}")

    def get_pending_transactions(self, pool_connection=None) -> List[Dict]:
        """
        Get pending multi-transactions from consensus node's transaction pool.

        Args:
            pool_connection: Optional connection to consensus node's transaction pool

        Returns:
            List of pending multi-transactions
        """
        try:
            if pool_connection is not None:
                # Query external transaction pool for this account's multi-transactions
                pending = pool_connection.get_multi_transactions_by_sender(self.address)
                # Convert to dictionary format
                return [multi_txn.to_dict() for multi_txn in pending]
            else:
                # Return locally tracked pending transactions (those marked as LOCAL_COMMITTED)
                local_committed = self.value_collection.find_by_state(ValueState.LOCAL_COMMITTED)
                pending_count = len(local_committed)

                if pending_count > 0:
                    print(f"Account has {pending_count} locally committed multi-transactions pending confirmation")
                    # For now, return basic info
                    return [{
                        'sender': self.address,
                        'status': 'LOCAL_COMMITTED',
                        'count': pending_count,
                        'message': 'Multi-transactions submitted to network, awaiting confirmation'
                    }]

                return []

        except Exception as e:
            print(f"Error getting pending multi-transactions: {e}")
            return []

    def create_vpb(self, values: List[Value], proofs: List, block_indices: List) -> bool:
        """
        Create VPB triplets for multiple values.

        Args:
            values: List of values
            proofs: List of proofs
            block_indices: List of block indices

        Returns:
            True if all VPBs created successfully
        """
        try:
            if not (len(values) == len(proofs) == len(block_indices)):
                raise ValueError("Length of values, proofs, and block_indices must match")

            success_count = 0
            for value, proof, block_idx in zip(values, proofs, block_indices):
                if self.add_value_with_vpb(value, proof, block_idx):
                    success_count += 1

            self.last_activity = datetime.now()
            print(f"Created {success_count}/{len(values)} VPBs")
            return success_count == len(values)

        except Exception as e:
            print(f"Failed to create VPBs: {e}")
            return False

    def create_single_vpb(self, value: Value, proofs, block_indices) -> VPBpair:
        """
        Create a single VPB (Verification Proof Balance) triplet.

        Args:
            value: Value object
            proofs: Proofs object
            block_indices: BlockIndexList object

        Returns:
            VPBpair object
        """
        try:
            # Create VPB object
            vpb = VPBpair(value, proofs, block_indices)

            # Add to VPB manager and value collection
            if self.add_value_with_vpb(value, proofs, block_indices):
                self.last_activity = datetime.now()
                print(f"VPB created for value with {value.value_num} units")
                return vpb
            else:
                return None

        except Exception as e:
            print(f"Failed to create VPB: {e}")
            return None

    def update_vpb(self, value: Value, new_proofs=None, new_block_index_lst=None) -> bool:
        """
        Update an existing VPB for a specific value.

        Args:
            value: Value object whose VPB should be updated
            new_proofs: New proofs object (optional)
            new_block_index_lst: New block index list (optional)

        Returns:
            True if update successful
        """
        try:
            success = self.vpb_manager.update_vpb(value, new_proofs, new_block_index_lst)
            if success:
                print(f"VPB updated for value with {value.value_num} units")
            return success

        except Exception as e:
            print(f"Failed to update VPB: {e}")
            return False

    def remove_vpb(self, value: Value) -> bool:
        """
        Remove VPB for a specific value.

        Args:
            value: Value object whose VPB should be removed

        Returns:
            True if removal successful
        """
        try:
            success = self.vpb_manager.remove_vpb(value)
            if success:
                print(f"VPB removed for value with {value.value_num} units")
            return success

        except Exception as e:
            print(f"Failed to remove VPB: {e}")
            return False

    def get_vpb(self, value: Value) -> Optional[VPBpair]:
        """
        Get VPB for a specific value.

        Args:
            value: Value object

        Returns:
            VPBpair object or None if not found
        """
        return self.vpb_manager.get_vpb(value)

    def get_all_vpbs(self) -> Dict[str, VPBpair]:
        """
        Get all VPBs managed by this account.

        Returns:
            Dictionary mapping value identifiers to VPB objects
        """
        return self.vpb_manager.get_all_vpbs()

    def validate_vpb(self, vpb: VPBpair) -> bool:
        """
        Validate a VPB triplet.

        Args:
            vpb: VPBpair to validate

        Returns:
            True if VPB is valid
        """
        try:
            # Check if VPB components are consistent
            if not vpb.value or not vpb.proofs or not vpb.block_index_lst:
                return False

            # Use VPBpair's built-in validation
            return vpb.is_valid_vpb()

        except Exception as e:
            print(f"Failed to validate VPB: {e}")
            return False

    def validate_all_vpbs(self) -> bool:
        """
        Validate all VPBs managed by this account.

        Returns:
            True if all VPBs are valid
        """
        return self.vpb_manager.validate_vpb_consistency()

    def clear_all_vpbs(self) -> bool:
        """
        Clear all VPBs managed by this account.

        Returns:
            True if cleared successfully
        """
        try:
            success = self.vpb_manager.clear_all_vpbs()
            if success:
                print(f"All VPBs cleared for {self.name}")
            return success

        except Exception as e:
            print(f"Failed to clear VPBs: {e}")
            return False

    def receive_multi_transaction(self, multi_txn_result: Dict) -> bool:
        """
        Framework for receiving and validating multi-transactions.

        Args:
            multi_txn_result: Incoming multi-transaction result

        Returns:
            True if multi-transaction is accepted (framework ready)
        """
        try:
            # Validate multi-transaction structure
            multi_txn = multi_txn_result.get("multi_transactions")
            if not multi_txn:
                print("No multi_transactions object found")
                return False

            # Verify multi-transaction signature
            if not self.verify_multi_transaction_signature(multi_txn_result):
                print("Invalid multi-transaction signature")
                return False

            # Verify all individual transaction signatures
            signature_results = self.verify_all_transaction_signatures(multi_txn_result)
            if not all(signature_results.values()):
                print("Some individual transaction signatures are invalid")
                return False

            # VPB validation (placeholder - to be implemented)
            if not self._validate_multi_transaction_vpb(multi_txn_result):
                print("VPB validation failed")
                return False

            # Check if any transactions are for this account (as recipient)
            transactions_for_this_account = [
                tx for tx in multi_txn.multi_txns
                if tx.recipient == self.address
            ]

            if transactions_for_this_account:
                self._process_incoming_multi_transactions(transactions_for_this_account)

            print(f"Multi-transaction received: {multi_txn.digest[:16] if multi_txn.digest else 'N/A'}...")
            return True

        except Exception as e:
            print(f"Error processing received multi-transaction: {e}")
            return False

    def receive_transaction(self, transaction: Dict) -> bool:
        """
        Legacy method for backward compatibility.
        DEPRECATED: Use receive_multi_transaction instead.

        Args:
            transaction: Incoming transaction dictionary (legacy format)

        Returns:
            True if transaction is accepted (framework ready)
        """
        print("WARNING: receive_transaction is deprecated. Use receive_multi_transaction instead.")
        return False

    def get_account_info(self) -> Dict:
        """
        Get comprehensive account information.

        Returns:
            Account information dictionary
        """
        return {
            'address': self.address,
            'name': self.name,
            'balances': self.get_all_balances(),
            'total_values': len(self.get_values()),
            'pending_transactions': len(self.get_pending_transactions()),
            'local_vpbs': len(self.get_all_vpbs()),
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'transaction_history_count': len(self.transaction_history)
        }

    def validate_integrity(self) -> bool:
        """
        Validate account data integrity using CreateMultiTransactions.

        Returns:
            True if account data is consistent
        """
        try:
            # Use CreateMultiTransactions integrity validation
            if not self.get_account_integrity():
                print("CreateMultiTransactions integrity check failed")
                return False

            # Validate value collection integrity
            if not self.value_collection.validate_integrity():
                print("Value collection integrity check failed")
                return False

            # Validate VPB integrity
            if not self.validate_all_vpbs():
                print("VPB integrity check failed")
                return False

            # Validate local multi-transaction integrity
            # Note: Account nodes don't maintain transaction pools,
            # but we can validate locally tracked transactions
            local_committed = self.value_collection.find_by_state(ValueState.LOCAL_COMMITTED)
            if local_committed:
                print(f"Account has {len(local_committed)} locally committed multi-transactions awaiting confirmation")
                # Additional validation can be added here

            return True

        except Exception as e:
            print(f"Error during integrity validation: {e}")
            return False

    # Private helper methods

    def _record_transaction(self, transaction: Dict, action: str):
        """Record transaction in history."""
        try:
            with self.history_lock:
                history_entry = {
                    'hash': transaction['hash'],
                    'action': action,
                    'timestamp': datetime.now().isoformat(),
                    'amount': transaction.get('amount', 0),
                    'recipient': transaction.get('recipient'),
                    'sender': transaction.get('sender')
                }
                self.transaction_history.append(history_entry)

                # Keep only last 1000 entries
                if len(self.transaction_history) > 1000:
                    self.transaction_history = self.transaction_history[-1000:]

        except Exception as e:
            print(f"Error recording transaction: {e}")

    def _record_multi_transaction(self, multi_txn_result: Dict, action: str, reference: Optional[str] = None):
        """Record multi-transaction in history."""
        try:
            with self.history_lock:
                multi_txn = multi_txn_result["multi_transactions"]
                history_entry = {
                    'hash': multi_txn.digest,
                    'action': action,
                    'timestamp': datetime.now().isoformat(),
                    'transaction_count': multi_txn_result['transaction_count'],
                    'total_amount': multi_txn_result['total_amount'],
                    'recipients': multi_txn_result.get('recipients', []),
                    'sender': self.address,
                    'reference': reference,
                    'type': 'multi_transaction'
                }
                self.transaction_history.append(history_entry)

                # Keep only last 1000 entries
                if len(self.transaction_history) > 1000:
                    self.transaction_history = self.transaction_history[-1000:]

        except Exception as e:
            print(f"Error recording multi-transaction: {e}")

    def _basic_transaction_validation(self, transaction: Dict) -> bool:
        """Perform basic transaction validation."""
        required_fields = ['hash', 'sender', 'recipient', 'amount']
        return all(field in transaction for field in required_fields)

    def _validate_multi_transaction_vpb(self, multi_txn_result: Dict) -> bool:
        """
        Validate multi-transaction VPB (placeholder for future implementation).

        Args:
            multi_txn_result: Multi-transaction result

        Returns:
            True if VPB validation passes (placeholder)
        """
        # TODO: Implement VPB validation logic for multi-transactions
        # This would involve verifying the sender's VPB for all transactions
        return True

    def _validate_transaction_vpb(self, transaction: Dict) -> bool:
        """
        Legacy method for backward compatibility.
        DEPRECATED: Use _validate_multi_transaction_vpb instead.

        Args:
            transaction: Transaction dictionary (legacy format)

        Returns:
            True if VPB validation passes (placeholder)
        """
        print("WARNING: _validate_transaction_vpb is deprecated. Use _validate_multi_transaction_vpb instead.")
        # TODO: Implement VPB validation logic
        # This would involve verifying the sender's VPB for the transaction
        return True

    def _process_incoming_multi_transactions(self, transactions: List) -> None:
        """Process incoming multi-transactions where this account is the recipient."""
        try:
            for transaction in transactions:
                # Create new value objects for the received amount
                # This is a simplified implementation
                new_value = Value()
                # TODO: Proper value creation based on transaction details
                # new_value.amount = ... (create integer set for the amount)
                # new_value.state = ValueState.UNSPENT

                # Add to account collection
                # self.add_values([new_value])

                print(f"Received transaction with {len(transaction.value)} values")

        except Exception as e:
            print(f"Error processing incoming multi-transactions: {e}")

    def _process_incoming_transaction(self, transaction: Dict):
        """
        Legacy method for backward compatibility.
        DEPRECATED: Use _process_incoming_multi_transactions instead.
        """
        print("WARNING: _process_incoming_transaction is deprecated. Use _process_incoming_multi_transactions instead.")

    def cleanup(self):
        """Cleanup resources and sensitive data."""
        try:
            # Clear sensitive key material
            self.signature_handler.clear_key()

            # Clear VPB data
            self.clear_all_vpbs()

            # Clear transaction history
            with self.history_lock:
                self.transaction_history.clear()

            print(f"Account {self.name} cleaned up successfully")

        except Exception as e:
            print(f"Error during cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()