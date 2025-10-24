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
from EZ_Transaction.CreateSingleTransaction import CreateTransaction
from EZ_Transaction.SingleTransaction import SingleTransaction
# TransactionPool is used by consensus nodes, not account nodes
# from EZ_Transaction_Pool.TransactionPool import TransactionPool
from EZ_VPB.VPBPair import VPBpair
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
        self.value_collection = AccountValueCollection()
        self.value_selector = AccountPickValues(address)
        self.transaction_creator = CreateTransaction(address)

        # Account nodes don't maintain their own transaction pool
        # They submit transactions to consensus nodes' pools
        self.transaction_pool_url = None  # Optional: URL to submit transactions

        # Local VPB storage
        self.local_vpbs: Dict[str, VPBpair] = {}
        self.vpb_lock = threading.RLock()

        # Account metadata
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        # Security: Use secure signature handler
        self.signature_handler = secure_signature_handler(private_key_pem, public_key_pem)

        # Transaction history tracking
        self.transaction_history: List[Dict] = []
        self.history_lock = threading.RLock()

        print(f"Account {self.name} ({address}) initialized successfully")

    def get_balance(self, state: ValueState = ValueState.UNSPENT) -> int:
        """
        Get account balance for values in a specific state.

        Args:
            state: Value state to calculate balance for (default: UNSPENT)

        Returns:
            Total balance amount
        """
        values = self.value_collection.find_by_state(state)
        return sum(len(value.amount) for value in values)

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
            return self.value_collection.find_all()
        return self.value_collection.find_by_state(state)

    def add_values(self, values: List[Value], position: str = "end") -> int:
        """
        Add values to the account collection.

        Args:
            values: List of values to add
            position: Where to add values ("start" or "end")

        Returns:
            Number of values added
        """
        added_count = 0
        for value in values:
            try:
                self.value_collection.add_value(value, position)
                added_count += 1
                print(f"Added value with {len(value.amount)} units to {self.name}")
            except Exception as e:
                print(f"Failed to add value: {e}")

        self.last_activity = datetime.now()
        return added_count

    def create_transaction(self, recipient: str, amount: int,
                          reference: Optional[str] = None) -> Optional[Dict]:
        """
        Create a new transaction.

        Args:
            recipient: Recipient address
            amount: Amount to transfer
            reference: Optional transaction reference

        Returns:
            Transaction dictionary or None if failed
        """
        try:
            # Select values for the transaction
            selected_values, change_values = self.value_selector.pick_values(amount)

            if not selected_values:
                print(f"Insufficient balance for transaction of {amount} units")
                return None

            # Create the transaction
            transaction = self.transaction_creator.create_single_transaction(
                recipient=recipient,
                amount=amount,
                reference=reference
            )

            if transaction:
                # Mark selected values as SELECTED
                for value in selected_values:
                    self.value_collection.update_value_state(value.id, ValueState.SELECTED)

                # Add change values if any
                if change_values:
                    self.add_values(change_values, "start")

                # Record in history
                self._record_transaction(transaction, "created")

                print(f"Transaction created: {transaction['hash'][:16]}...")
                return transaction

        except Exception as e:
            print(f"Failed to create transaction: {e}")
            # Revert value states on failure
            self.value_collection.revert_selected_to_unspent()

        return None

    def sign_transaction(self, transaction: Dict) -> bool:
        """
        Sign a transaction using the account's private key.

        Args:
            transaction: Transaction dictionary

        Returns:
            True if signing successful
        """
        try:
            # Prepare transaction for signing
            transaction_for_signing = self._prepare_transaction_for_signing(transaction)

            # Sign using secure signature handler
            signature = self.signature_handler.sign(transaction_for_signing)

            if signature:
                transaction['signature'] = signature
                transaction['public_key'] = self.public_key_pem.decode('utf-8')

                # Record in history
                self._record_transaction(transaction, "signed")

                print(f"Transaction signed: {transaction['hash'][:16]}...")
                return True

        except Exception as e:
            print(f"Failed to sign transaction: {e}")

        return False

    def verify_transaction(self, transaction: Dict) -> bool:
        """
        Verify a transaction signature.

        Args:
            transaction: Transaction dictionary

        Returns:
            True if signature is valid
        """
        try:
            if 'signature' not in transaction or 'public_key' not in transaction:
                return False

            # Prepare transaction for verification
            transaction_for_verification = self._prepare_transaction_for_signing(transaction)

            # Verify signature
            is_valid = self.signature_handler.verify(
                transaction_for_verification,
                transaction['signature'],
                transaction['public_key'].encode('utf-8')
            )

            return is_valid

        except Exception as e:
            print(f"Failed to verify transaction: {e}")
            return False

    def submit_transaction(self, transaction: Dict, pool_connection=None) -> bool:
        """
        Submit a transaction to a consensus node's transaction pool.

        Args:
            transaction: Signed transaction dictionary
            pool_connection: Optional connection to consensus node's transaction pool

        Returns:
            True if submission successful
        """
        try:
            # Create SingleTransaction object
            single_tx = SingleTransaction(
                sender=transaction['sender'],
                recipient=transaction['recipient'],
                amount=transaction['amount'],
                fee=transaction.get('fee', 0),
                nonce=transaction.get('nonce', 0),
                reference=transaction.get('reference'),
                signature=transaction['signature'],
                hash_value=transaction['hash']
            )

            # Submit to external transaction pool (consensus node)
            if pool_connection is not None:
                # Submit via provided connection (e.g., network API, local pool access)
                success = pool_connection.add_transaction(single_tx)
            else:
                # For now, we'll simulate submission
                # In practice, this would be submitted to consensus nodes via network
                print(f"Transaction ready for network submission: {transaction['hash'][:16]}...")
                success = True

            if success:
                # Update value states to LOCAL_COMMITTED
                self._update_transaction_value_states(transaction, ValueState.LOCAL_COMMITTED)

                # Record in history
                self._record_transaction(transaction, "submitted")

                print(f"Transaction submitted: {transaction['hash'][:16]}...")
                return True
            else:
                # Revert value states on failure
                self._update_transaction_value_states(transaction, ValueState.UNSPENT)
                print(f"Failed to submit transaction")

        except Exception as e:
            print(f"Error submitting transaction: {e}")
            # Revert value states on error
            self._update_transaction_value_states(transaction, ValueState.UNSPENT)

        return False

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
        Get pending transactions from consensus node's transaction pool.

        Args:
            pool_connection: Optional connection to consensus node's transaction pool

        Returns:
            List of pending transactions
        """
        try:
            if pool_connection is not None:
                # Query external transaction pool for this account's transactions
                pending = pool_connection.get_transactions_by_sender(self.address)
                # Convert to dictionary format
                return [tx.to_dict() for tx in pending]
            else:
                # Return locally tracked pending transactions (those marked as LOCAL_COMMITTED)
                local_committed = self.value_collection.find_by_state(ValueState.LOCAL_COMMITTED)
                pending_count = len(local_committed)

                if pending_count > 0:
                    print(f"Account has {pending_count} locally committed transactions pending confirmation")
                    # For now, return basic info
                    return [{
                        'sender': self.address,
                        'status': 'LOCAL_COMMITTED',
                        'count': pending_count,
                        'message': 'Transactions submitted to network, awaiting confirmation'
                    }]

                return []

        except Exception as e:
            print(f"Error getting pending transactions: {e}")
            return []

    def create_vpb(self, values: List[Value], proofs: List, block_indices: List) -> VPBpair:
        """
        Create a VPB (Verification Proof Balance) triplet.

        Args:
            values: List of values
            proofs: List of proofs
            block_indices: List of block indices

        Returns:
            VPBpair object
        """
        try:
            vpb = VPBpair(
                value=values,
                proofs=proofs,
                blockIndexList=block_indices
            )

            # Store VPB locally
            with self.vpb_lock:
                vpb_id = hash(json.dumps([v.to_dict_for_signing() for v in values], sort_keys=True))
                self.local_vpbs[vpb_id] = vpb

            self.last_activity = datetime.now()
            print(f"VPB created with {len(values)} values")
            return vpb

        except Exception as e:
            print(f"Failed to create VPB: {e}")
            return None

    def update_vpb(self, vpb_id: str, **kwargs) -> bool:
        """
        Update an existing VPB.

        Args:
            vpb_id: VPB identifier
            **kwargs: Fields to update

        Returns:
            True if update successful
        """
        try:
            with self.vpb_lock:
                if vpb_id not in self.local_vpbs:
                    return False

                vpb = self.local_vpbs[vpb_id]

                # Update VPB components
                if 'values' in kwargs:
                    vpb.value = kwargs['values']
                if 'proofs' in kwargs:
                    vpb.proofs = kwargs['proofs']
                if 'block_indices' in kwargs:
                    vpb.blockIndexList = kwargs['block_indices']

                print(f"VPB {vpb_id[:16]}... updated")
                return True

        except Exception as e:
            print(f"Failed to update VPB: {e}")
            return False

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
            if not vpb.value or not vpb.proofs or not vpb.blockIndexList:
                return False

            # Validate that proofs match values
            if len(vpb.proofs) != len(vpb.value):
                return False

            # Check block index list consistency
            if len(vpb.blockIndexList) != len(vpb.value):
                return False

            # Additional validation can be added here
            # For now, basic structural validation

            return True

        except Exception as e:
            print(f"Failed to validate VPB: {e}")
            return False

    def receive_transaction(self, transaction: Dict) -> bool:
        """
        Framework for receiving and validating transactions.

        Args:
            transaction: Incoming transaction dictionary

        Returns:
            True if transaction is accepted (framework ready)
        """
        try:
            # Basic validation
            if not self._basic_transaction_validation(transaction):
                return False

            # Verify transaction signature
            if not self.verify_transaction(transaction):
                print("Invalid transaction signature")
                return False

            # VPB validation (placeholder - to be implemented)
            if not self._validate_transaction_vpb(transaction):
                print("VPB validation failed")
                return False

            # If this account is the recipient, add values to account
            if transaction.get('recipient') == self.address:
                self._process_incoming_transaction(transaction)

            print(f"Transaction received: {transaction['hash'][:16]}...")
            return True

        except Exception as e:
            print(f"Error processing received transaction: {e}")
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
            'local_vpbs': len(self.local_vpbs),
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'transaction_history_count': len(self.transaction_history)
        }

    def validate_integrity(self) -> bool:
        """
        Validate account data integrity.

        Returns:
            True if account data is consistent
        """
        try:
            # Validate value collection integrity
            if not self.value_collection.validate_integrity():
                print("Value collection integrity check failed")
                return False

            # Validate VPB integrity
            for vpb_id, vpb in self.local_vpbs.items():
                if not self.validate_vpb(vpb):
                    print(f"VPB {vpb_id[:16]}... integrity check failed")
                    return False

            # Validate local transaction integrity
            # Note: Account nodes don't maintain transaction pools,
            # but we can validate locally tracked transactions
            local_committed = self.value_collection.find_by_state(ValueState.LOCAL_COMMITTED)
            if local_committed:
                print(f"Account has {len(local_committed)} locally committed transactions awaiting confirmation")
                # Additional validation can be added here

            return True

        except Exception as e:
            print(f"Error during integrity validation: {e}")
            return False

    # Private helper methods

    def _prepare_transaction_for_signing(self, transaction: Dict) -> Dict:
        """Prepare transaction dictionary for signing."""
        # Create a copy without signature fields
        tx_copy = transaction.copy()
        tx_copy.pop('signature', None)
        tx_copy.pop('public_key', None)
        return tx_copy

    def _update_transaction_value_states(self, transaction: Dict, target_state: ValueState):
        """Update value states for a transaction."""
        try:
            # This is a simplified implementation
            # In practice, you'd track which values belong to which transaction
            selected_values = self.value_collection.find_by_state(ValueState.SELECTED)
            for value in selected_values:
                self.value_collection.update_value_state(value.id, target_state)

        except Exception as e:
            print(f"Error updating value states: {e}")

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

    def _basic_transaction_validation(self, transaction: Dict) -> bool:
        """Perform basic transaction validation."""
        required_fields = ['hash', 'sender', 'recipient', 'amount']
        return all(field in transaction for field in required_fields)

    def _validate_transaction_vpb(self, transaction: Dict) -> bool:
        """
        Validate transaction VPB (placeholder for future implementation).

        Args:
            transaction: Transaction dictionary

        Returns:
            True if VPB validation passes (placeholder)
        """
        # TODO: Implement VPB validation logic
        # This would involve verifying the sender's VPB for the transaction
        return True

    def _process_incoming_transaction(self, transaction: Dict):
        """Process an incoming transaction where this account is the recipient."""
        try:
            # Create new value objects for the received amount
            # This is a simplified implementation
            new_value = Value()
            # TODO: Proper value creation based on transaction details
            # new_value.amount = ... (create integer set for the amount)
            # new_value.state = ValueState.UNSPENT

            # Add to account collection
            # self.add_values([new_value])

            print(f"Received {transaction.get('amount', 0)} units")

        except Exception as e:
            print(f"Error processing incoming transaction: {e}")

    def cleanup(self):
        """Cleanup resources and sensitive data."""
        try:
            # Clear sensitive key material
            self.signature_handler.clear_key()

            # Clear VPB data
            with self.vpb_lock:
                self.local_vpbs.clear()

            # Clear transaction history
            with self.history_lock:
                self.transaction_history.clear()

            print(f"Account {self.name} cleaned up successfully")

        except Exception as e:
            print(f"Error during cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()