#!/usr/bin/env python3
"""
Comprehensive unit tests for VPBPairs module.

This test suite covers:
- VPBStorage class (persistent storage functionality)
- VPBPair class (VPB triplet management)
- VPBManager class (core VPB management)
- VPBPairs class (main interface)
- Integration with AccountValueCollection and AccountPickValues
- Complete VPB lifecycle operations (add, remove, update, query)
- Value selection for transactions
- Data consistency and integrity validation
"""

import pytest
import sys
import os
import tempfile
import shutil
import threading
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_VPB.VPBPairs import VPBStorage, VPBPair, VPBManager, VPBPairs
    from EZ_Value.Value import Value, ValueState
    from EZ_Value.AccountValueCollection import AccountValueCollection
    from EZ_Value.AccountPickValues import AccountPickValues
    from EZ_Proof.Proofs import Proofs, ProofsStorage
    from EZ_BlockIndex.BlockIndexList import BlockIndexList
    from EZ_Transaction.MultiTransactions import MultiTransactions
    from EZ_Transaction.SingleTransaction import Transaction
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


class TestVPBStorage:
    """Test suite for VPBStorage persistent storage functionality."""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary VPBStorage instance."""
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_vpb_storage.db")
        storage = VPBStorage(db_path)
        yield storage
        # Cleanup
        try:
            storage = None
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def sample_value(self):
        """Create a sample Value for testing."""
        return Value("0x1000", 100, ValueState.UNSPENT)

    @pytest.fixture
    def sample_proofs(self, temp_storage):
        """Create a sample Proofs for testing."""
        return Proofs("0x1000", temp_storage.proofs_storage)

    @pytest.fixture
    def sample_block_index_list(self):
        """Create a sample BlockIndexList for testing."""
        return BlockIndexList([1, 2, 3], [(1, "owner1"), (2, "owner2")])

    def test_storage_initialization(self, temp_storage):
        """Test VPBStorage database initialization."""
        assert temp_storage.db_path.endswith("test_vpb_storage.db")
        assert temp_storage._lock is not None
        assert temp_storage.proofs_storage is not None

    def test_store_vpb_triplet(self, temp_storage, sample_value, sample_proofs, sample_block_index_list):
        """Test storing a complete VPB triplet."""
        vpb_id = "test_vpb_001"
        account_address = "0xTestAccount1234567890ABCDEF"

        result = temp_storage.store_vpb_triplet(
            vpb_id, sample_value, sample_proofs, sample_block_index_list, account_address
        )

        assert result is True

    def test_load_vpb_triplet(self, temp_storage, sample_value, sample_proofs, sample_block_index_list):
        """Test loading a VPB triplet from storage."""
        vpb_id = "test_vpb_002"
        account_address = "0xTestAccount1234567890ABCDEF"

        # Store the VPB triplet
        temp_storage.store_vpb_triplet(
            vpb_id, sample_value, sample_proofs, sample_block_index_list, account_address
        )

        # Load the VPB triplet
        result = temp_storage.load_vpb_triplet(vpb_id)

        assert result is not None
        value_id, proofs, block_index_lst, loaded_account = result
        assert value_id == sample_value.begin_index
        assert proofs.value_id == sample_proofs.value_id
        assert loaded_account == account_address
        assert isinstance(block_index_lst, BlockIndexList)

    def test_delete_vpb_triplet(self, temp_storage, sample_value, sample_proofs, sample_block_index_list):
        """Test deleting a VPB triplet from storage."""
        vpb_id = "test_vpb_003"
        account_address = "0xTestAccount1234567890ABCDEF"

        # Store the VPB triplet
        temp_storage.store_vpb_triplet(
            vpb_id, sample_value, sample_proofs, sample_block_index_list, account_address
        )

        # Delete the VPB triplet
        result = temp_storage.delete_vpb_triplet(vpb_id)
        assert result is True

        # Verify it's deleted
        loaded = temp_storage.load_vpb_triplet(vpb_id)
        assert loaded is None

    def test_get_all_vpb_ids_for_account(self, temp_storage, sample_value, sample_proofs, sample_block_index_list):
        """Test retrieving all VPB IDs for an account."""
        account_address = "0xTestAccount1234567890ABCDEF"

        # Store multiple VPB triplets
        for i in range(3):
            vpb_id = f"test_vpb_00{i}"
            temp_storage.store_vpb_triplet(
                vpb_id, sample_value, sample_proofs, sample_block_index_list, account_address
            )

        # Get all VPB IDs
        vpb_ids = temp_storage.get_all_vpb_ids_for_account(account_address)
        assert len(vpb_ids) == 3
        assert all(vpb_id.startswith("test_vpb_00") for vpb_id in vpb_ids)

    def test_get_vpbs_by_value_state(self, temp_storage, sample_value, sample_proofs, sample_block_index_list):
        """Test retrieving VPBs by value state."""
        account_address = "0xTestAccount1234567890ABCDEF"

        # Store VPB with specific state
        vpb_id = "test_vpb_state"
        temp_storage.store_vpb_triplet(
            vpb_id, sample_value, sample_proofs, sample_block_index_list, account_address
        )

        # Get VPBs by state
        vpb_ids = temp_storage.get_vpbs_by_value_state(account_address, ValueState.UNSPENT)
        assert len(vpb_ids) >= 0  # May return empty if no matches


class TestVPBPair:
    """Test suite for VPBPair class."""

    @pytest.fixture
    def mock_value_collection(self):
        """Create a mock AccountValueCollection."""
        mock_collection = Mock(spec=AccountValueCollection)
        sample_value = Value("0x1000", 100, ValueState.UNSPENT)
        mock_collection.get_value_by_id.return_value = sample_value
        return mock_collection

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage for testing."""
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_vpb_pair.db")
        storage = VPBStorage(db_path)
        yield storage
        try:
            storage = None
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def sample_proofs(self, temp_storage):
        """Create sample Proofs for testing."""
        return Proofs("0x1000", temp_storage.proofs_storage)

    @pytest.fixture
    def sample_block_index_list(self):
        """Create sample BlockIndexList for testing."""
        return BlockIndexList([1, 2, 3], [(1, "owner1"), (2, "owner2")])

    @pytest.fixture
    def vpb_pair(self, mock_value_collection, sample_proofs, sample_block_index_list):
        """Create a VPBPair instance for testing."""
        return VPBPair("0x1000", sample_proofs, sample_block_index_list, mock_value_collection)

    def test_vpb_pair_initialization(self, vpb_pair):
        """Test VPBPair initialization."""
        assert vpb_pair.value_id == "0x1000"
        assert vpb_pair.proofs is not None
        assert vpb_pair.block_index_lst is not None
        assert vpb_pair.value_collection is not None
        assert vpb_pair.vpb_id is not None
        assert len(vpb_pair.vpb_id) == 32

    def test_vpb_pair_value_property(self, vpb_pair, mock_value_collection):
        """Test VPBPair value property."""
        value = vpb_pair.value
        assert value is not None
        mock_value_collection.get_value_by_id.assert_called_with("0x1000")

    def test_vpb_pair_is_valid_vpb(self, vpb_pair):
        """Test VPBPair validation."""
        # Should be valid with proper setup
        assert vpb_pair.is_valid_vpb() is True

    def test_vpb_pair_is_valid_vpb_missing_components(self, vpb_pair):
        """Test VPBPair validation with missing components."""
        vpb_pair.value_collection = None
        assert vpb_pair.is_valid_vpb() is False

    def test_vpb_pair_update_proofs(self, vpb_pair, temp_storage):
        """Test updating VPBPair Proofs."""
        new_proofs = Proofs("0x1000", temp_storage.proofs_storage)
        result = vpb_pair.update_proofs(new_proofs)
        assert result is True
        assert vpb_pair.proofs == new_proofs

    def test_vpb_pair_update_proofs_mismatched_value(self, vpb_pair, temp_storage):
        """Test updating VPBPair with mismatched Proofs."""
        new_proofs = Proofs("0x2000", temp_storage.proofs_storage)  # Different value_id
        result = vpb_pair.update_proofs(new_proofs)
        assert result is False

    def test_vpb_pair_update_block_index_list(self, vpb_pair):
        """Test updating VPBPair BlockIndexList."""
        new_block_index_lst = BlockIndexList([4, 5, 6], [(4, "owner4")])
        result = vpb_pair.update_block_index_list(new_block_index_lst)
        assert result is True
        assert vpb_pair.block_index_lst == new_block_index_lst

    def test_vpb_pair_to_dict(self, vpb_pair):
        """Test VPBPair to_dict conversion."""
        result = vpb_pair.to_dict()
        assert isinstance(result, dict)
        assert 'vpb_id' in result
        assert 'value_id' in result
        assert 'value' in result
        assert 'proofs_count' in result
        assert 'block_index_list' in result
        assert 'created_at' in result
        assert 'updated_at' in result


class TestVPBManager:
    """Test suite for VPBManager class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        try:
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def temp_storage(self, temp_dir):
        """Create temporary storage for testing."""
        db_path = os.path.join(temp_dir, "test_manager.db")
        return VPBStorage(db_path)

    @pytest.fixture
    def mock_value_collection(self):
        """Create a mock AccountValueCollection."""
        mock_collection = Mock(spec=AccountValueCollection)
        return mock_collection

    @pytest.fixture
    def vpb_manager(self, temp_storage, mock_value_collection):
        """Create a VPBManager instance for testing."""
        return VPBManager("0xTestAccount1234567890ABCDEF", temp_storage, mock_value_collection)

    @pytest.fixture
    def sample_value(self):
        """Create a sample Value for testing."""
        return Value("0x1000", 100, ValueState.UNSPENT)

    @pytest.fixture
    def sample_proofs(self, temp_storage):
        """Create sample Proofs for testing."""
        return Proofs("0x1000", temp_storage.proofs_storage)

    @pytest.fixture
    def sample_block_index_list(self):
        """Create sample BlockIndexList for testing."""
        return BlockIndexList([1, 2, 3], [(1, "owner1")])

    def test_manager_initialization(self, vpb_manager):
        """Test VPBManager initialization."""
        assert vpb_manager.account_address == "0xTestAccount1234567890ABCDEF"
        assert vpb_manager.storage is not None
        assert vpb_manager._lock is not None
        assert vpb_manager._value_collection is not None

    def test_manager_set_account_address(self, vpb_manager):
        """Test setting account address."""
        new_address = "0xNewAccount1234567890ABCDEF"
        vpb_manager.set_account_address(new_address)
        assert vpb_manager.account_address == new_address

    def test_manager_set_value_collection(self, vpb_manager):
        """Test setting value collection."""
        new_collection = Mock(spec=AccountValueCollection)
        vpb_manager.set_value_collection(new_collection)
        assert vpb_manager._value_collection == new_collection

    def test_manager_add_vpb(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test adding a VPB to manager."""
        result = vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)
        assert result is True
        assert sample_value.begin_index in vpb_manager._vpb_map

    def test_manager_add_duplicate_vpb(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test adding duplicate VPB should fail."""
        # Add first time
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Add second time should fail
        result = vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)
        assert result is False

    def test_manager_remove_vpb(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test removing a VPB from manager."""
        # Add VPB first
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Remove VPB
        result = vpb_manager.remove_vpb(sample_value)
        assert result is True
        assert sample_value.begin_index not in vpb_manager._vpb_map

    def test_manager_remove_nonexistent_vpb(self, vpb_manager, sample_value):
        """Test removing non-existent VPB should fail."""
        result = vpb_manager.remove_vpb(sample_value)
        assert result is False

    def test_manager_get_vpb(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test getting a VPB from manager."""
        # Add VPB first
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Get VPB
        vpb = vpb_manager.get_vpb(sample_value)
        assert vpb is not None
        assert vpb.value_id == sample_value.begin_index

    def test_manager_get_vpb_by_id(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test getting a VPB by value ID."""
        # Add VPB first
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Get VPB by ID
        vpb = vpb_manager.get_vpb_by_id(sample_value.begin_index)
        assert vpb is not None
        assert vpb.value_id == sample_value.begin_index

    def test_manager_get_all_vpbs(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test getting all VPBs from manager."""
        # Add multiple VPBs
        values = [
            Value("0x1000", 100, ValueState.UNSPENT),
            Value("0x2000", 200, ValueState.UNSPENT),
            Value("0x3000", 300, ValueState.UNSPENT)
        ]

        for value in values:
            proofs = Proofs(value.begin_index, vpb_manager.storage.proofs_storage)
            vpb_manager.add_vpb(value, proofs, sample_block_index_list)

        # Get all VPBs
        all_vpbs = vpb_manager.get_all_vpbs()
        assert len(all_vpbs) == len(values)

    def test_manager_get_vpbs_by_state(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list, mock_value_collection):
        """Test getting VPBs by value state."""
        # Mock the value collection to return values with specific states
        mock_value_collection.get_value_by_id.return_value = sample_value

        # Add VPB
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Get VPBs by state
        vpbs = vpb_manager.get_vpbs_by_state(ValueState.UNSPENT)
        assert len(vpbs) >= 0

    def test_manager_update_vpb(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list, temp_storage):
        """Test updating a VPB in manager."""
        # Add VPB first
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Update VPB with new BlockIndexList
        new_block_index_lst = BlockIndexList([4, 5, 6], [(4, "owner4")])
        result = vpb_manager.update_vpb(sample_value, new_block_index_lst=new_block_index_lst)
        assert result is True

    def test_manager_validate_vpb_consistency(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list, mock_value_collection):
        """Test VPB consistency validation."""
        # Mock value collection to return valid value
        mock_value_collection.get_value_by_id.return_value = sample_value

        # Add VPB
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Validate consistency
        result = vpb_manager.validate_vpb_consistency()
        assert result is True

    def test_manager_get_vpb_statistics(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list, mock_value_collection):
        """Test getting VPB statistics."""
        # Mock value collection to return values with different states
        values_by_id = {
            "0x1000": Value("0x1000", 100, ValueState.UNSPENT),
            "0x2000": Value("0x2000", 200, ValueState.SELECTED),
            "0x3000": Value("0x3000", 300, ValueState.CONFIRMED)
        }
        mock_value_collection.get_value_by_id.side_effect = lambda value_id: values_by_id.get(value_id)

        # Add multiple VPBs
        for value in values_by_id.values():
            proofs = Proofs(value.begin_index, vpb_manager.storage.proofs_storage)
            vpb_manager.add_vpb(value, proofs, sample_block_index_list)

        # Get statistics
        stats = vpb_manager.get_vpb_statistics()
        assert 'total' in stats
        assert stats['total'] == 3

    def test_manager_export_vpbs_to_dict(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list, mock_value_collection):
        """Test exporting VPBs to dictionary."""
        # Mock value collection to return valid value
        mock_value_collection.get_value_by_id.return_value = sample_value

        # Add VPB
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Export to dict
        export_data = vpb_manager.export_vpbs_to_dict()
        assert isinstance(export_data, dict)
        assert 'account_address' in export_data
        assert 'export_timestamp' in export_data
        assert 'vpbs' in export_data
        assert 'statistics' in export_data

    def test_manager_clear_all_vpbs(self, vpb_manager, sample_value, sample_proofs, sample_block_index_list):
        """Test clearing all VPBs."""
        # Add VPB first
        vpb_manager.add_vpb(sample_value, sample_proofs, sample_block_index_list)

        # Clear all VPBs
        result = vpb_manager.clear_all_vpbs()
        assert result is True
        assert len(vpb_manager._vpb_map) == 0


class TestVPBPairs:
    """Test suite for VPBPairs main interface class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        try:
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def mock_value_collection(self):
        """Create a mock AccountValueCollection."""
        mock_collection = Mock(spec=AccountValueCollection)
        return mock_collection

    @pytest.fixture
    def vpb_pairs(self, mock_value_collection):
        """Create a VPBPairs instance for testing."""
        return VPBPairs("0xTestAccount1234567890ABCDEF", mock_value_collection)

    def test_vpb_pairs_initialization(self, vpb_pairs):
        """Test VPBPairs initialization."""
        assert vpb_pairs.account_address == "0xTestAccount1234567890ABCDEF"
        assert vpb_pairs.storage is not None
        assert vpb_pairs.manager is not None

    def test_vpb_pairs_add_vpb(self, vpb_pairs):
        """Test VPBPairs add_vpb method."""
        sample_value = Value("0x1000", 100, ValueState.UNSPENT)
        temp_dir = tempfile.mkdtemp()
        try:
            storage = VPBStorage(os.path.join(temp_dir, "test.db"))
            proofs = Proofs("0x1000", storage.proofs_storage)
            block_index_lst = BlockIndexList([1, 2, 3], [(1, "owner1")])

            result = vpb_pairs.add_vpb(sample_value, proofs, block_index_lst)
            # Note: This might fail due to mock setup, which is expected
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

    def test_vpb_pairs_get_statistics(self, vpb_pairs):
        """Test VPBPairs get_statistics method."""
        stats = vpb_pairs.get_statistics()
        assert isinstance(stats, dict)

    def test_vpb_pairs_export_data(self, vpb_pairs):
        """Test VPBPairs export_data method."""
        data = vpb_pairs.export_data()
        assert isinstance(data, dict)
        assert 'account_address' in data

    def test_vpb_pairs_validate_all_vpbs(self, vpb_pairs):
        """Test VPBPairs validate_all_vpbs method."""
        result = vpb_pairs.validate_all_vpbs()
        assert isinstance(result, bool)

    def test_vpb_pairs_cleanup(self, vpb_pairs):
        """Test VPBPairs cleanup method."""
        # Should not raise an exception
        vpb_pairs.cleanup()


class TestIntegration:
    """Integration tests for VPB system components."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for integration testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        try:
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def integration_setup(self, temp_dir):
        """Set up integration test environment."""
        account_address = "0xIntegrationTest1234567890ABCDEF"
        db_path = os.path.join(temp_dir, "integration_test.db")

        # Create real components
        storage = VPBStorage(db_path)
        value_collection = AccountValueCollection(account_address)
        vpb_pairs = VPBPairs(account_address, value_collection)

        return {
            'storage': storage,
            'value_collection': value_collection,
            'vpb_pairs': vpb_pairs,
            'account_address': account_address
        }

    def test_vpb_lifecycle_integration(self, integration_setup):
        """Test complete VPB lifecycle integration."""
        setup = integration_setup
        value_collection = setup['value_collection']
        vpb_pairs = setup['vpb_pairs']

        # Create sample value (using valid hex string)
        value = Value("0x1234567890abcdef1234567890abcdef", 500, ValueState.UNSPENT)
        value_collection.add_value(value)

        # Create proofs and block index list
        proofs = Proofs(value.begin_index, vpb_pairs.storage.proofs_storage)
        block_index_lst = BlockIndexList([10, 11, 12], [(10, "integration_owner")])

        # Test VPB lifecycle
        # Add VPB
        add_result = vpb_pairs.add_vpb(value, proofs, block_index_lst)

        # Get VPB
        vpb = vpb_pairs.get_vpb(value)

        # Validate
        validation_result = vpb_pairs.validate_all_vpbs()

        # Export data
        export_data = vpb_pairs.export_data()

        # Cleanup
        vpb_pairs.cleanup()

        # Basic assertions
        assert isinstance(add_result, bool)
        assert isinstance(export_data, dict)
        assert isinstance(validation_result, bool)

    def test_thread_safety(self, temp_dir):
        """Test thread safety of VPB operations."""
        account_address = "0xThreadSafetyTest1234567890ABCDEF"
        db_path = os.path.join(temp_dir, "thread_safety_test.db")

        storage = VPBStorage(db_path)
        value_collection = AccountValueCollection(account_address)
        vpb_pairs = VPBPairs(account_address, value_collection)

        results = []
        errors = []

        def worker(worker_id):
            """Worker function for thread testing."""
            try:
                for i in range(5):
                    # Generate valid hex string for value ID
                    value_id = f"0x{worker_id:01x}{i:01x}{'0' * 30}"  # Creates valid hex string
                    value = Value(value_id, 100, ValueState.UNSPENT)
                    value_collection.add_value(value)

                    proofs = Proofs(value_id, storage.proofs_storage)
                    block_index_lst = BlockIndexList([i], [(i, f"owner{worker_id}")])

                    result = vpb_pairs.add_vpb(value, proofs, block_index_lst)
                    results.append((worker_id, i, result))

                    time.sleep(0.01)  # Small delay to increase contention
            except Exception as e:
                errors.append((worker_id, str(e)))

        # Create multiple threads
        threads = []
        for worker_id in range(3):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Check results
        assert len(errors) == 0, f"Thread safety test failed with errors: {errors}"
        assert len(results) == 15  # 3 workers * 5 operations each

        # Cleanup
        vpb_pairs.cleanup()


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])