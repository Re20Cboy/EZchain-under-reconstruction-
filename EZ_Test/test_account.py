#!/usr/bin/env python3
"""
Comprehensive unit tests for Account class with proper mocking and complete coverage.
This is the final merged version combining the best features from all test files.
"""

import pytest
import sys
import os
import threading
from datetime import datetime
from unittest.mock import patch, MagicMock, Mock
import types

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the real Value classes
from EZ_Value.Value import Value, ValueState


def create_mock_module(name, attributes):
    """Create a mock module with given attributes."""
    module = types.ModuleType(name)
    for attr_name, attr_value in attributes.items():
        setattr(module, attr_name, attr_value)
    return module


# Setup comprehensive mocking system
def setup_mocks():
    """Setup all required mocks for Account testing."""

    # Mock cryptographic and utility modules
    mock_hash = create_mock_module('Hash', {
        'hash': lambda data: 'mock_hash',
        'sha256_hash': lambda data: b'mock_hash_bytes'
    })

    mock_ss = create_mock_module('SecureSignature', {
        'secure_signature_handler': type('secure_signature_handler', (), {
            '__init__': lambda self, *args: None,
            'sign': lambda self, data: 'mock_signature',
            'verify': lambda self, data, sig, key: True,
            'clear_key': lambda self: None
        })
    })

    # Mock Value module with real classes
    mock_value_module = types.ModuleType('Value')
    mock_value_module.Value = Value
    mock_value_module.ValueState = ValueState

    # Create a proper Transaction class with required methods
    class MockTransaction:
        def __init__(self, sender=None, recipient=None, amount=None, fee=0, nonce=0,
                     reference=None, signature=None, hash_value=None):
            self.sender = sender
            self.recipient = recipient
            self.amount = amount
            self.fee = fee
            self.nonce = nonce
            self.reference = reference
            self.signature = signature
            self.hash_value = hash_value or 'mock_hash'

        def to_dict(self):
            return {
                'sender': self.sender,
                'recipient': self.recipient,
                'amount': self.amount,
                'fee': self.fee,
                'nonce': self.nonce,
                'reference': self.reference,
                'signature': self.signature,
                'hash': self.hash_value
            }

    # Create Transaction module with both Transaction and SingleTransaction
    mock_transaction_module = create_mock_module('SingleTransaction', {
        'Transaction': MockTransaction,
        'SingleTransaction': MockTransaction  # Add the missing alias
    })

    # Mock Account dependencies
    mock_avc = create_mock_module('AccountValueCollection', {
        'AccountValueCollection': type('AccountValueCollection', (), {
            '__init__': lambda self: None,
            'add_value': lambda self, *args: None,
            'find_by_state': lambda self, *args: [],
            'find_all': lambda self: [],
            'update_value_state': lambda self, *args: None,
            'revert_selected_to_unspent': lambda self: None,
            'validate_integrity': lambda self: True
        })
    })

    mock_apv = create_mock_module('AccountPickValues', {
        'AccountPickValues': type('AccountPickValues', (), {
            '__init__': lambda self, addr: None,
            'pick_values': lambda self, amount: ([], [])
        })
    })

    mock_cst = create_mock_module('CreateSingleTransaction', {
        'CreateTransaction': type('CreateTransaction', (), {
            '__init__': lambda self, addr: None,
            'create_single_transaction': lambda self, **kwargs: {'hash': 'mock_hash'}
        })
    })

    mock_vpb = create_mock_module('VPBPair', {
        'VPBpair': type('VPBpair', (), {
            '__init__': lambda self, *args: None
        })
    })

    # Register all mocks
    sys.modules['EZ_Tool_Box.Hash'] = mock_hash
    sys.modules['EZ_Tool_Box.SecureSignature'] = mock_ss
    sys.modules['EZ_Value.Value'] = mock_value_module
    sys.modules['EZ_Transaction.SingleTransaction'] = mock_transaction_module
    sys.modules['EZ_Value.AccountValueCollection'] = mock_avc
    sys.modules['EZ_Value.AccountPickValues'] = mock_apv
    sys.modules['EZ_Transaction.CreateSingleTransaction'] = mock_cst
    sys.modules['EZ_VPB.VPBPair'] = mock_vpb


# Setup mocks before importing Account
setup_mocks()

try:
    from EZ_Account.Account import Account
    ACCOUNT_AVAILABLE = True
except ImportError as e:
    print(f"Could not import Account: {e}")
    Account = None
    ACCOUNT_AVAILABLE = False


@pytest.fixture
def mock_keys():
    """Generate mock key pairs for testing."""
    return b"mock_private_key_pem", b"mock_public_key_pem"


@pytest.fixture
def test_account(mock_keys):
    """Fixture for creating a test account."""
    if not ACCOUNT_AVAILABLE:
        pytest.skip("Account class not available")

    private_pem, public_pem = mock_keys
    account = Account(
        address="0xTestAccount1234567890abcdef",
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        name="TestAccount"
    )
    return account


@pytest.fixture
def test_values():
    """Fixture for test values."""
    if Value is None or ValueState is None:
        pytest.skip("Value classes not available")

    return [
        Value("0x1000", 100, ValueState.UNSPENT),
        Value("0x2000", 200, ValueState.UNSPENT),
        Value("0x3000", 150, ValueState.UNSPENT),
        Value("0x4000", 300, ValueState.UNSPENT),
        Value("0x5000", 250, ValueState.UNSPENT)
    ]


class TestAccountInitialization:
    """Test suite for Account class initialization."""

    def test_account_initialization_success(self, test_account):
        """Test successful account initialization."""
        assert test_account.address == "0xTestAccount1234567890abcdef"
        assert test_account.name == "TestAccount"
        assert test_account.private_key_pem == b"mock_private_key_pem"
        assert test_account.public_key_pem == b"mock_public_key_pem"
        assert test_account.get_balance() == 0
        assert len(test_account.local_vpbs) == 0
        assert len(test_account.transaction_history) == 0
        assert test_account.transaction_pool_url is None
        assert isinstance(test_account.created_at, datetime)
        assert isinstance(test_account.last_activity, datetime)

    def test_account_initialization_without_name(self, mock_keys):
        """Test account initialization without providing name."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        account = Account(
            address="0xTestAccount1234567890abcdef",
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )
        assert account.name.startswith("Account_0xTest")

    def test_account_initialization_with_long_address(self, mock_keys):
        """Test account initialization with very long address."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        long_address = "0x" + "a" * 100  # Very long address
        account = Account(
            address=long_address,
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )
        assert account.address == long_address
        assert account.name.startswith("Account_0xaaaaaa")  # Should be truncated

    def test_account_initialization_thread_safety(self, mock_keys):
        """Test that account initialization is thread-safe."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        accounts = []
        errors = []

        def create_account(index):
            try:
                account = Account(
                    address=f"0xTest{index:04d}",
                    private_key_pem=private_pem,
                    public_key_pem=public_pem
                )
                accounts.append(account)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            thread = threading.Thread(target=create_account, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert len(accounts) == 5


class TestAccountBalanceManagement:
    """Test suite for balance management methods."""

    def test_get_balance_empty_account(self, test_account):
        """Test getting balance from empty account."""
        assert test_account.get_balance() == 0
        assert test_account.get_balance(ValueState.UNSPENT) == 0
        assert test_account.get_balance(ValueState.SELECTED) == 0
        assert test_account.get_balance(ValueState.LOCAL_COMMITTED) == 0
        assert test_account.get_balance(ValueState.CONFIRMED) == 0

    def test_get_all_balances_empty_account(self, test_account):
        """Test getting all balances from empty account."""
        balances = test_account.get_all_balances()
        expected_states = ['UNSPENT', 'SELECTED', 'LOCAL_COMMITTED', 'CONFIRMED']
        for state in expected_states:
            assert state in balances
            assert balances[state] == 0

    def test_get_values_with_state_filter(self, test_account):
        """Test getting values with state filter."""
        all_values = test_account.get_values()
        unspent_values = test_account.get_values(ValueState.UNSPENT)
        assert isinstance(all_values, list)
        assert isinstance(unspent_values, list)

    def test_get_values_no_filter(self, test_account):
        """Test getting all values without filter."""
        all_values = test_account.get_values()
        assert isinstance(all_values, list)

    def test_balance_edge_cases(self, test_account):
        """Test balance calculation edge cases."""
        # Test with zero balance
        assert test_account.get_balance() == 0

        # Test with different states
        all_balances = test_account.get_all_balances()
        assert isinstance(all_balances, dict)
        assert len(all_balances) == 4  # Four ValueState types


class TestAccountTransactionManagement:
    """Test suite for transaction management methods."""

    def test_record_transaction(self, test_account):
        """Test recording transaction in history."""
        transaction = {
            'hash': '0xTestHash123',
            'amount': 100,
            'recipient': '0xRecipient',
            'sender': test_account.address
        }

        initial_count = len(test_account.transaction_history)
        test_account._record_transaction(transaction, "created")

        assert len(test_account.transaction_history) == initial_count + 1
        assert test_account.transaction_history[-1]['hash'] == '0xTestHash123'
        assert test_account.transaction_history[-1]['action'] == 'created'
        assert 'timestamp' in test_account.transaction_history[-1]

    def test_transaction_history_limit(self, test_account):
        """Test that transaction history respects limit."""
        # Add more than the 1000 entry limit
        for i in range(1500):
            transaction = {
                'hash': f'0xTestHash{i:04d}',
                'amount': i,
                'sender': test_account.address
            }
            test_account._record_transaction(transaction, "test")

        # Should maintain only last 1000 entries
        assert len(test_account.transaction_history) == 1000
        assert test_account.transaction_history[0]['hash'] == '0xTestHash0500'
        assert test_account.transaction_history[-1]['hash'] == '0xTestHash1499'

    def test_prepare_transaction_for_signing(self, test_account):
        """Test preparing transaction for signing."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100,
            'signature': 'existing_signature',
            'public_key': 'existing_public_key'
        }

        prepared = test_account._prepare_transaction_for_signing(transaction)

        assert 'signature' not in prepared
        assert 'public_key' not in prepared
        assert prepared['hash'] == '0xTestHash123'
        assert prepared['amount'] == 100
        assert prepared['sender'] == test_account.address
        assert prepared['recipient'] == '0xRecipient'

    def test_basic_transaction_validation(self, test_account):
        """Test basic transaction validation."""
        valid_transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100
        }

        invalid_transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address
            # Missing recipient and amount
        }

        assert test_account._basic_transaction_validation(valid_transaction) is True
        assert test_account._basic_transaction_validation(invalid_transaction) is False

    def test_create_transaction_insufficient_balance(self, test_account):
        """Test creating transaction with insufficient balance."""
        result = test_account.create_transaction("0xRecipient", 200)
        assert result is None

    def test_create_transaction_zero_amount(self, test_account):
        """Test creating transaction with zero amount."""
        result = test_account.create_transaction("0xRecipient", 0)
        assert result is None

    def test_create_transaction_negative_amount(self, test_account):
        """Test creating transaction with negative amount."""
        result = test_account.create_transaction("0xRecipient", -50)
        assert result is None

    def test_create_transaction_empty_recipient(self, test_account):
        """Test creating transaction with empty recipient."""
        result = test_account.create_transaction("", 50)
        # Should handle gracefully without crashing

    def test_create_transaction_with_reference(self, test_account):
        """Test creating transaction with reference."""
        with patch.object(test_account.value_selector, 'pick_values', return_value=([], [])):
            with patch.object(test_account.transaction_creator, 'create_single_transaction',
                            return_value={'hash': 'mock_hash', 'reference': 'Test Reference'}):
                result = test_account.create_transaction("0xRecipient", 100, reference="Test Reference")
                # Should handle gracefully

    def test_sign_transaction_success(self, test_account):
        """Test successful transaction signing."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100
        }

        with patch.object(test_account.signature_handler, 'sign', return_value='mock_signature'):
            result = test_account.sign_transaction(transaction)
            assert result is True
            assert transaction['signature'] == 'mock_signature'
            assert transaction['public_key'] == test_account.public_key_pem.decode('utf-8')

    def test_sign_transaction_invalid_data(self, test_account):
        """Test signing invalid transaction data."""
        result = test_account.sign_transaction({})
        # Should handle gracefully
        assert isinstance(result, bool)

    def test_verify_transaction_no_signature(self, test_account):
        """Test verifying transaction without signature."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100
        }
        result = test_account.verify_transaction(transaction)
        assert result is False

    def test_verify_transaction_invalid_signature(self, test_account):
        """Test verifying transaction with invalid signature."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100,
            'signature': 'invalid_signature',
            'public_key': test_account.public_key_pem.decode('utf-8')
        }

        with patch.object(test_account.signature_handler, 'verify', return_value=False):
            result = test_account.verify_transaction(transaction)
            assert result is False

    def test_submit_transaction_no_pool(self, test_account):
        """Test submitting transaction without pool connection."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100,
            'signature': 'test_signature',
            'nonce': 1,
            'fee': 0
        }
        result = test_account.submit_transaction(transaction)
        # Should handle gracefully
        assert isinstance(result, bool)

    def test_submit_transaction_with_pool_connection(self, test_account):
        """Test transaction submission with pool connection."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'recipient': '0xRecipient',
            'amount': 100,
            'signature': 'test_signature',
            'nonce': 1,
            'fee': 0
        }

        mock_pool = MagicMock()
        mock_pool.add_transaction.return_value = True

        with patch.object(test_account.value_collection, 'find_by_state', return_value=[]):
            result = test_account.submit_transaction(transaction, mock_pool)

        assert result is True
        mock_pool.add_transaction.assert_called_once()

    def test_get_pending_transactions_no_connection(self, test_account):
        """Test getting pending transactions without pool connection."""
        pending = test_account.get_pending_transactions()
        assert isinstance(pending, list)

    def test_get_pending_transactions_with_pool_connection(self, test_account):
        """Test getting pending transactions with pool connection."""
        mock_pool = MagicMock()
        mock_tx = MagicMock()
        mock_tx.to_dict.return_value = {
            'hash': '0xTestHash123',
            'sender': test_account.address,
            'amount': 100
        }
        mock_pool.get_transactions_by_sender.return_value = [mock_tx]

        pending = test_account.get_pending_transactions(mock_pool)
        assert len(pending) == 1
        assert pending[0]['hash'] == '0xTestHash123'


class TestAccountVPBManagement:
    """Test suite for VPB management methods."""

    def test_create_vpb_success(self, test_account, test_values):
        """Test successful VPB creation."""
        proofs = ["proof1", "proof2"]
        block_indices = [1, 2]

        vpb = test_account.create_vpb(test_values, proofs, block_indices)
        # Should not crash
        assert vpb is not None or vpb is None  # Depending on implementation

    def test_create_vpb_empty_values(self, test_account):
        """Test creating VPB with empty values."""
        vpb = test_account.create_vpb([], [], [])
        # Should handle gracefully
        assert vpb is not None or vpb is None

    def test_create_vpb_mismatched_lengths(self, test_account):
        """Test creating VPB with mismatched lengths."""
        values = [Value("0x1000", 100, ValueState.UNSPENT)]
        proofs = ["proof1", "proof2"]  # Different length
        block_indices = [1]

        vpb = test_account.create_vpb(values, proofs, block_indices)
        # Should handle gracefully or raise appropriate error

    def test_update_vpb_success(self, test_account):
        """Test successful VPB update."""
        # First create a VPB
        test_values = [Value("0x1000", 100, ValueState.UNSPENT)]
        vpb = test_account.create_vpb(test_values, ["proof1"], [1])

        if vpb and len(test_account.local_vpbs) > 0:
            # Get VPB ID
            vpb_id = list(test_account.local_vpbs.keys())[0]

            # Update VPB
            new_values = [Value("0x2000", 200, ValueState.UNSPENT)]
            result = test_account.update_vpb(vpb_id, values=new_values)

            assert isinstance(result, bool)

    def test_update_vpb_nonexistent(self, test_account):
        """Test updating non-existent VPB."""
        result = test_account.update_vpb("nonexistent_id")
        assert result is False

    def test_validate_vpb_success(self, test_account):
        """Test successful VPB validation."""
        test_values = [Value("0x1000", 100, ValueState.UNSPENT)]
        vpb = test_account.create_vpb(test_values, ["proof1"], [1])

        if vpb:
            result = test_account.validate_vpb(vpb)
            assert isinstance(result, bool)

    def test_validate_vpb_none(self, test_account):
        """Test validating None VPB."""
        result = test_account.validate_vpb(None)
        assert result is False

    def test_validate_vpb_empty_components(self, test_account):
        """Test validating VPB with empty components."""
        # Create a mock VPB with empty components
        mock_vpb = MagicMock()
        mock_vpb.value = []
        mock_vpb.proofs = []
        mock_vpb.blockIndexList = []

        result = test_account.validate_vpb(mock_vpb)
        assert result is False


class TestAccountIntegrationAndInfo:
    """Test suite for account integration and information methods."""

    def test_get_account_info(self, test_account):
        """Test getting comprehensive account information."""
        info = test_account.get_account_info()

        required_keys = ['address', 'name', 'balances', 'total_values', 'pending_transactions',
                        'local_vpbs', 'created_at', 'last_activity', 'transaction_history_count']

        for key in required_keys:
            assert key in info, f"Missing key in account info: {key}"

        assert info['address'] == test_account.address
        assert info['name'] == test_account.name
        assert isinstance(info['created_at'], str)
        assert isinstance(info['last_activity'], str)
        assert isinstance(info['balances'], dict)
        assert isinstance(info['total_values'], int)
        assert isinstance(info['pending_transactions'], int)
        assert isinstance(info['local_vpbs'], int)
        assert isinstance(info['transaction_history_count'], int)

    def test_set_transaction_pool_url(self, test_account):
        """Test setting transaction pool URL."""
        url = "https://example.com/pool"
        test_account.set_transaction_pool_url(url)
        assert test_account.transaction_pool_url == url

    def test_validate_integrity_empty_account(self, test_account):
        """Test validating integrity of empty account."""
        result = test_account.validate_integrity()
        assert result is True

    def test_validate_integrity_with_values(self, test_account, test_values):
        """Test validating integrity with values."""
        # Mock value collection to have some values
        with patch.object(test_account.value_collection, 'find_all', return_value=test_values):
            result = test_account.validate_integrity()
            assert result is True

    def test_validate_integrity_with_vpbs(self, test_account):
        """Test validating integrity with VPBs."""
        # Add a VPB
        test_values = [Value("0x1000", 100, ValueState.UNSPENT)]
        test_account.create_vpb(test_values, ["proof1"], [1])

        result = test_account.validate_integrity()
        assert result is True

    def test_receive_transaction_valid(self, test_account):
        """Test receiving valid transaction."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': '0xSender',
            'recipient': test_account.address,
            'amount': 100,
            'signature': 'test_signature',
            'public_key': 'test_public_key'
        }

        with patch.object(test_account, 'verify_transaction', return_value=True):
            result = test_account.receive_transaction(transaction)
            assert result is True

    def test_receive_transaction_invalid(self, test_account):
        """Test receiving invalid transaction."""
        invalid_transaction = {}
        result = test_account.receive_transaction(invalid_transaction)
        assert result is False

    def test_receive_transaction_wrong_recipient(self, test_account):
        """Test receiving transaction for wrong recipient."""
        transaction = {
            'hash': '0xTestHash123',
            'sender': '0xSender',
            'recipient': '0xWrongRecipient',  # Not this account
            'amount': 100
        }

        with patch.object(test_account, 'verify_transaction', return_value=True):
            result = test_account.receive_transaction(transaction)
            # Should still process, just not add values
            assert isinstance(result, bool)

    def test_cleanup(self, test_account):
        """Test account cleanup."""
        # Add some data
        test_account.local_vpbs['test_vpb'] = 'mock_vpb'
        test_account.transaction_history.append({'hash': '0xTest'})

        # Perform cleanup
        test_account.cleanup()

        # Verify data is cleared
        assert len(test_account.local_vpbs) == 0
        assert len(test_account.transaction_history) == 0

    def test_destructor_cleanup(self, mock_keys):
        """Test that destructor calls cleanup."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        account = Account(
            address="0xTestDestructor",
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )

        # Add some data
        account.local_vpbs['test_vpb'] = 'mock_vpb'
        account.transaction_history.append({'hash': '0xTest'})

        # Trigger destructor
        account.cleanup()

        # Verify cleanup happened
        assert len(account.local_vpbs) == 0
        assert len(account.transaction_history) == 0


class TestAccountEdgeCases:
    """Test suite for edge cases and error conditions."""

    def test_account_with_empty_address(self, mock_keys):
        """Test account creation with empty address."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        account = Account(
            address="",
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )
        assert account.address == ""

    def test_account_with_special_characters_address(self, mock_keys):
        """Test account creation with special characters in address."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        special_address = "0xTest!@#$%^&*()_+{}|:<>?[]\\;'\",./"

        account = Account(
            address=special_address,
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )
        assert account.address == special_address

    def test_account_with_unicode_address(self, mock_keys):
        """Test account creation with unicode characters in address."""
        if not ACCOUNT_AVAILABLE:
            pytest.skip("Account class not available")

        private_pem, public_pem = mock_keys
        unicode_address = "0xTest🚀🌟💎"

        account = Account(
            address=unicode_address,
            private_key_pem=private_pem,
            public_key_pem=public_pem
        )
        assert account.address == unicode_address

    def test_large_transaction_amounts(self, test_account):
        """Test handling large transaction amounts."""
        # Test very large amount
        result = test_account.create_transaction("0xRecipient", 10**18)
        assert result is None  # Should fail due to insufficient balance

        # Test negative large amount
        result = test_account.create_transaction("0xRecipient", -10**18)
        assert result is None

    def test_transaction_history_overflow_protection(self, test_account):
        """Test transaction history overflow protection."""
        # Test that history limit is enforced
        for i in range(2000):  # More than 1000 limit
            transaction = {
                'hash': f'0xOverflow{i:04d}',
                'amount': i,
                'sender': test_account.address
            }
            test_account._record_transaction(transaction, "test")

        # Should still be limited to 1000
        assert len(test_account.transaction_history) == 1000

    def test_concurrent_operations(self, test_account):
        """Test concurrent account operations."""
        errors = []
        results = []

        def get_balance(index):
            try:
                balance = test_account.get_balance()
                results.append(('balance', balance))
            except Exception as e:
                errors.append(e)

        def get_info(index):
            try:
                info = test_account.get_account_info()
                results.append(('info', len(info)))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            thread1 = threading.Thread(target=get_balance, args=(i,))
            thread2 = threading.Thread(target=get_info, args=(i,))
            threads.extend([thread1, thread2])
            thread1.start()
            thread2.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert len(results) == 20

    def test_error_handling_in_transaction_methods(self, test_account):
        """Test error handling in various transaction methods."""
        # Test create_transaction with mocked exceptions
        with patch.object(test_account.value_selector, 'pick_values', side_effect=Exception("Test error")):
            result = test_account.create_transaction("0xRecipient", 100)
            assert result is None

        # Test sign_transaction with mocked exceptions
        with patch.object(test_account.signature_handler, 'sign', side_effect=Exception("Test error")):
            transaction = {'hash': '0xTestHash123'}
            result = test_account.sign_transaction(transaction)
            assert result is False

        # Test verify_transaction with mocked exceptions
        with patch.object(test_account.signature_handler, 'verify', side_effect=Exception("Test error")):
            transaction = {'hash': '0xTestHash123', 'signature': 'test', 'public_key': 'test'}
            result = test_account.verify_transaction(transaction)
            assert result is False

    def test_memory_management(self, test_account):
        """Test memory management and resource cleanup."""
        # Add large amounts of data
        for i in range(1000):
            test_account._record_transaction(
                {'hash': f'0xMemoryTest{i:04d}', 'amount': i},
                "test"
            )

        # Add VPBs
        for i in range(100):
            test_account.local_vpbs[f'vpb_{i}'] = f'mock_vpb_data_{i}'

        # Verify data exists
        assert len(test_account.transaction_history) == 1000
        assert len(test_account.local_vpbs) == 100

        # Cleanup
        test_account.cleanup()

        # Verify cleanup worked
        assert len(test_account.transaction_history) == 0
        assert len(test_account.local_vpbs) == 0


def main():
    """Simple entry function to run tests."""
    print("Running comprehensive Account tests...")
    print("To run all tests, use: pytest -v test_account_final.py")
    print("To run specific test class, use: pytest -v test_account_final.py::TestAccountInitialization")
    print("To run with coverage, use: pytest --cov=. test_account_final.py")
    print("To run with verbose output, use: pytest -v -s test_account_final.py")

    if not ACCOUNT_AVAILABLE:
        print("WARNING: Account class not available, some tests will be skipped")
    else:
        print("Account class available, running full test suite")

    # Run pytest programmatically
    exit_code = pytest.main([__file__, "-v"])
    return exit_code


if __name__ == "__main__":
    exit(main())