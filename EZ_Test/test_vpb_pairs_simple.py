#!/usr/bin/env python3
"""
Simple test suite for VPBPairs module.

This is a lightweight test file for quick verification of basic VPB functionality.
"""

import sys
import os
import tempfile
import shutil
import time

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_VPB.VPBPairs import VPBPairs, VPBStorage, VPBPair
    from EZ_Value.Value import Value, ValueState
    from EZ_Value.AccountValueCollection import AccountValueCollection
    from EZ_Proof.Proofs import Proofs
    from EZ_BlockIndex.BlockIndexList import BlockIndexList
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def test_basic_vpb_functionality():
    """Test basic VPB functionality."""
    print("Testing basic VPB functionality...")

    # Create temporary directory for testing
    temp_dir = tempfile.mkdtemp()
    try:
        account_address = "0x1234567890abcdef1234567890abcdef"

        # Create components
        value_collection = AccountValueCollection(account_address)
        vpb_pairs = VPBPairs(account_address, value_collection)

        # Create sample value (using valid hex string)
        value = Value("0x10000000000000000000000000000001", 100, ValueState.UNSPENT)
        value_collection.add_value(value)

        # Create proofs and block index list
        proofs = Proofs(value.begin_index, vpb_pairs.storage.proofs_storage)
        block_index_lst = BlockIndexList([1, 2, 3], [(1, "owner1"), (2, "owner2")])

        # Test adding VPB
        result = vpb_pairs.add_vpb(value, proofs, block_index_lst)
        assert result is True, "Failed to add VPB"
        print("+ VPB added successfully")

        # Test getting VPB
        vpb = vpb_pairs.get_vpb(value)
        assert vpb is not None, "Failed to get VPB"
        print("+ VPB retrieved successfully")

        # Test validation
        validation_result = vpb_pairs.validate_all_vpbs()
        assert validation_result is True, "VPB validation failed"
        print("+ VPB validation passed")

        # Test statistics
        stats = vpb_pairs.get_statistics()
        assert isinstance(stats, dict), "Stats should be a dictionary"
        assert 'total' in stats, "Stats should include total count"
        print(f"+ VPB statistics: {stats}")

        # Test export
        export_data = vpb_pairs.export_data()
        assert isinstance(export_data, dict), "Export data should be a dictionary"
        assert 'vpbs' in export_data, "Export data should include VPBs"
        print("+ VPB export successful")

        # Cleanup
        vpb_pairs.cleanup()
        print("+ VPB cleanup completed")

        print("[SUCCESS] All basic VPB tests passed!")
        return True

    except Exception as e:
        print(f"[ERROR] Basic VPB test failed: {e}")
        return False
    finally:
        try:
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


def test_vpb_storage():
    """Test VPB storage functionality."""
    print("\nTesting VPB storage functionality...")

    temp_dir = tempfile.mkdtemp()
    try:
        # Create storage
        storage = VPBStorage(os.path.join(temp_dir, "test_storage.db"))

        # Create test data
        value = Value("0x20000000000000000000000000000002", 200, ValueState.UNSPENT)
        proofs = Proofs(value.begin_index, storage.proofs_storage)
        block_index_lst = BlockIndexList([4, 5, 6], [(4, "owner4")])
        vpb_id = "test_vpb_storage_001"
        account_address = "0xabcdef1234567890abcdef1234567890"

        # Test storage
        result = storage.store_vpb_triplet(vpb_id, value, proofs, block_index_lst, account_address)
        assert result is True, "Failed to store VPB triplet"
        print("+ VPB triplet stored successfully")

        # Test loading
        loaded_data = storage.load_vpb_triplet(vpb_id)
        assert loaded_data is not None, "Failed to load VPB triplet"
        value_id, loaded_proofs, loaded_block_index_lst, loaded_account = loaded_data
        assert value_id == value.begin_index, "Loaded value ID mismatch"
        assert loaded_account == account_address, "Loaded account mismatch"
        print("+ VPB triplet loaded successfully")

        # Test getting all VPB IDs for account
        vpb_ids = storage.get_all_vpb_ids_for_account(account_address)
        assert vpb_id in vpb_ids, "VPB ID not found in account VPBs"
        print("+ Account VPB IDs retrieved successfully")

        # Test deletion
        delete_result = storage.delete_vpb_triplet(vpb_id)
        assert delete_result is True, "Failed to delete VPB triplet"

        # Verify deletion
        deleted_data = storage.load_vpb_triplet(vpb_id)
        assert deleted_data is None, "VPB triplet should be deleted"
        print("+ VPB triplet deleted successfully")

        print("[SUCCESS] All VPB storage tests passed!")
        return True

    except Exception as e:
        print(f"[ERROR] VPB storage test failed: {e}")
        return False
    finally:
        try:
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


def main():
    """Main test function."""
    print("=" * 60)
    print("VPBPairs Simple Test Suite")
    print("=" * 60)

    # Run basic functionality test
    basic_result = test_basic_vpb_functionality()

    # Run storage test
    storage_result = test_vpb_storage()

    # Overall result
    print("\n" + "=" * 60)
    if basic_result and storage_result:
        print("[SUCCESS] All tests passed! VPBPairs is working correctly.")
        print("=" * 60)
        return True
    else:
        print("[ERROR] Some tests failed. Please check the implementation.")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)