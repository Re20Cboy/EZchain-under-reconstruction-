#!/usr/bin/env python3
"""
VPB Refactored Test Suite - Testing VPB system after refactoring.

This test validates the refactored VPB system including:
- VPBStorage with SQLite integration
- VPBPair with dynamic Value access
- VPBManager with AccountValueCollection integration
- VPBPairs main interface
- Integration with AccountPickValues for transaction processing
"""

import pytest
import sys
import os
import tempfile
import shutil
import time

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_VPB.VPBPairs import VPBStorage, VPBPair, VPBManager, VPBPairs
    from EZ_Value.Value import Value, ValueState
    from EZ_Value.AccountValueCollection import AccountValueCollection
    from EZ_Value.AccountPickValues import AccountPickValues
    from EZ_Proof.Proofs import Proofs
    from EZ_BlockIndex.BlockIndexList import BlockIndexList
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    try:
        time.sleep(0.1)
        shutil.rmtree(temp_dir, ignore_errors=True)
    except:
        pass


@pytest.fixture
def account_setup(temp_dir):
    """Set up a complete account environment for testing."""
    account_address = "0x1234567890abcdef1234567890abcdef"
    db_path = os.path.join(temp_dir, "account_test.db")

    # Create components
    value_collection = AccountValueCollection(account_address)
    vpb_pairs = VPBPairs(account_address, value_collection)

    return {
        'account_address': account_address,
        'value_collection': value_collection,
        'vpb_pairs': vpb_pairs,
        'db_path': db_path
    }


class TestVPBRefactored:
    """Test the refactored VPB system."""

    def test_complete_vpb_workflow(self, account_setup):
        """Test a complete VPB workflow from creation to cleanup."""
        setup = account_setup
        value_collection = setup['value_collection']
        vpb_pairs = setup['vpb_pairs']

        # Step 1: Create multiple values
        values = [
            Value("0x10000000000000000000000000000001", 100, ValueState.UNSPENT),
            Value("0x20000000000000000000000000000002", 200, ValueState.UNSPENT),
            Value("0x30000000000000000000000000000003", 300, ValueState.UNSPENT)
        ]

        for value in values:
            value_collection.add_value(value)

        # Step 2: Create VPBs for all values
        for value in values:
            proofs = Proofs(value.begin_index, vpb_pairs.storage.proofs_storage)
            block_index_lst = BlockIndexList([1, 2, 3], [(1, "owner1")])
            result = vpb_pairs.add_vpb(value, proofs, block_index_lst)
            assert result is True, f"Failed to add VPB for value {value.begin_index}"

        # Step 3: Verify all VPBs exist
        for value in values:
            vpb = vpb_pairs.get_vpb(value)
            assert vpb is not None, f"VPB not found for value {value.begin_index}"
            assert vpb.value_id == value.begin_index

        # Step 4: Test statistics
        stats = vpb_pairs.get_statistics()
        assert stats['total'] == 3
        assert stats['unspent'] == 3

        # Step 5: Test VPB updates
        value = values[0]
        vpb = vpb_pairs.get_vpb(value)
        new_block_index_lst = BlockIndexList([4, 5, 6], [(4, "owner4")])

        result = vpb_pairs.update_vpb(value, new_block_index_lst=new_block_index_lst)
        assert result is True, "Failed to update VPB"

        # Step 6: Test value state changes and VPB consistency
        value.state = ValueState.SELECTED
        updated_vpb = vpb_pairs.get_vpb(value)
        assert updated_vpb.value.state == ValueState.SELECTED

        # Step 7: Test export functionality
        export_data = vpb_pairs.export_data()
        assert isinstance(export_data, dict)
        assert 'vpbs' in export_data
        assert len(export_data['vpbs']) == 3

        # Step 8: Test validation
        validation_result = vpb_pairs.validate_all_vpbs()
        assert validation_result is True, "VPB validation failed"

        # Step 9: Test cleanup
        vpb_pairs.cleanup()
        final_stats = vpb_pairs.get_statistics()
        assert final_stats['total'] == 0

    def test_vpb_storage_persistence(self, temp_dir):
        """Test VPB storage persistence across sessions."""
        db_path = os.path.join(temp_dir, "persistence_test.db")
        account_address = "0xabcdef1234567890abcdef1234567890"
        value_id = "0x40000000000000000000000000000004"

        # Session 1: Store VPB data
        storage1 = VPBStorage(db_path)
        value = Value(value_id, 400, ValueState.UNSPENT)
        proofs = Proofs(value_id, storage1.proofs_storage)
        block_index_lst = BlockIndexList([7, 8, 9], [(7, "owner7")])
        vpb_id = "persistence_test_vpb"

        result = storage1.store_vpb_triplet(vpb_id, value, proofs, block_index_lst, account_address)
        assert result is True, "Failed to store VPB triplet"

        # Session 2: Load VPB data
        storage2 = VPBStorage(db_path)
        loaded_data = storage2.load_vpb_triplet(vpb_id)
        assert loaded_data is not None, "Failed to load VPB triplet"

        loaded_value_id, loaded_proofs, loaded_block_index_lst, loaded_account = loaded_data
        assert loaded_value_id == value_id
        assert loaded_account == account_address
        assert isinstance(loaded_block_index_lst, BlockIndexList)

        # Cleanup
        storage2.delete_vpb_triplet(vpb_id)

    def test_vpb_manager_integration(self, account_setup):
        """Test VPBManager integration with AccountValueCollection."""
        setup = account_setup
        manager = setup['vpb_pairs'].manager
        value_collection = setup['value_collection']

        # Add values to collection
        value = Value("0x50000000000000000000000000000005", 500, ValueState.UNSPENT)
        value_collection.add_value(value)

        # Test adding VPB through manager
        proofs = Proofs(value.begin_index, manager.storage.proofs_storage)
        block_index_lst = BlockIndexList([10], [(10, "owner10")])
        result = manager.add_vpb(value, proofs, block_index_lst)
        assert result is True, "Manager failed to add VPB"

        # Test getting VPB by ID
        vpb = manager.get_vpb_by_id(value.begin_index)
        assert vpb is not None, "Manager failed to get VPB by ID"
        assert vpb.value_id == value.begin_index

        # Test getting all VPBs
        all_vpbs = manager.get_all_vpbs()
        assert len(all_vpbs) == 1
        assert value.begin_index in all_vpbs

        # Test VPB consistency validation
        validation_result = manager.validate_vpb_consistency()
        assert validation_result is True, "VPB consistency validation failed"

    def test_vpb_pair_validation(self, temp_dir):
        """Test VPBPair validation logic."""
        db_path = os.path.join(temp_dir, "validation_test.db")

        # Create mock value collection
        mock_collection = Mock()
        sample_value = Value("0x60000000000000000000000000000006", 600, ValueState.UNSPENT)
        mock_collection.get_value_by_id.return_value = sample_value

        # Create storage and components
        storage = VPBStorage(db_path)
        proofs = Proofs(sample_value.begin_index, storage.proofs_storage)
        block_index_lst = BlockIndexList([11, 12], [(11, "owner11")])

        # Test valid VPB
        vpb = VPBPair(sample_value.begin_index, proofs, block_index_lst, mock_collection)
        assert vpb.is_valid_vpb() is True, "Valid VPB should pass validation"

        # Test invalid VPB (missing value collection)
        vpb.value_collection = None
        assert vpb.is_valid_vpb() is False, "VPB without value collection should fail validation"

        # Test invalid VPB (missing proofs)
        vpb.value_collection = mock_collection
        vpb.proofs = None
        assert vpb.is_valid_vpb() is False, "VPB without proofs should fail validation"

    def test_error_handling(self, account_setup):
        """Test error handling in VPB system."""
        setup = account_setup
        vpb_pairs = setup['vpb_pairs']

        # Test adding VPB without proper setup
        value = Value("0x70000000000000000000000000000007", 700, ValueState.UNSPENT)
        proofs = Proofs(value.begin_index, vpb_pairs.storage.proofs_storage)
        block_index_lst = BlockIndexList([13], [(13, "owner13")])

        # This should work since value is added to collection
        setup['value_collection'].add_value(value)
        result = vpb_pairs.add_vpb(value, proofs, block_index_lst)
        assert result is True, "Should be able to add VPB with proper setup"

        # Test adding duplicate VPB
        result = vpb_pairs.add_vpb(value, proofs, block_index_lst)
        assert result is False, "Should not be able to add duplicate VPB"

        # Test removing non-existent VPB
        non_existent_value = Value("0x80000000000000000000000000000008", 800, ValueState.UNSPENT)
        result = vpb_pairs.remove_vpb(non_existent_value)
        assert result is False, "Should not be able to remove non-existent VPB"


class Mock:
    """Simple mock class for testing."""
    def __init__(self):
        self.get_value_by_id = MockMethod()

class MockMethod:
    """Mock method class."""
    def __init__(self, return_value=None):
        self.return_value = return_value or Value("0x60000000000000000000000000000006", 600, ValueState.UNSPENT)

    def __call__(self, value_id):
        return self.return_value


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])