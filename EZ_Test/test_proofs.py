#!/usr/bin/env python3
"""
Comprehensive tests for the refactored EZ_Proof module.
Tests the mapping table structure, persistent storage, and ProofsStorage functionality.
"""

import pytest
import sys
import os
import tempfile
import shutil
import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Proof.Proofs import Proofs, ProofsStorage
from EZ_Proof.ProofUnit import ProofUnit
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Units.MerkleTree import MerkleTree
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_Value.Value import Value, ValueState


class TestProofsStorage:
    """Test suite for ProofsStorage persistent storage functionality."""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary ProofsStorage instance."""
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_proofs_storage.db")
        storage = ProofsStorage(db_path)
        yield storage
        # Cleanup
        try:
            storage = None
            import time
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def sample_proof_unit(self):
        """Create a sample ProofUnit for testing."""
        # Create test values
        value1 = Value("0x1000", 100, ValueState.UNSPENT)
        value2 = Value("0x2000", 200, ValueState.UNSPENT)

        # Test owner
        owner = "test_owner_address"

        # Create transaction
        txn = Transaction(
            sender=owner,
            recipient="recipient_001",
            nonce=1,
            signature=None,
            value=[value1, value2],
            time=datetime.datetime.now().isoformat()
        )

        # Create MultiTransactions
        multi_txns = MultiTransactions(
            sender=owner,
            multi_txns=[txn]
        )
        multi_txns.set_digest()

        # Create Merkle tree and proof
        merkle_tree = MerkleTree([multi_txns.digest])
        merkle_root = merkle_tree.get_root_hash()
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        return proof_unit, merkle_root

    def test_storage_initialization(self, temp_storage):
        """Test ProofsStorage initialization."""
        assert temp_storage.db_path.endswith("test_proofs_storage.db")
        # Database should be created with proper tables
        assert os.path.exists(temp_storage.db_path)

    def test_store_and_load_proof_unit(self, temp_storage, sample_proof_unit):
        """Test storing and loading ProofUnit from storage."""
        proof_unit, _ = sample_proof_unit

        # Store the ProofUnit
        result = temp_storage.store_proof_unit(proof_unit)
        assert result is True

        # Load the ProofUnit
        loaded_unit = temp_storage.load_proof_unit(proof_unit.unit_id)
        assert loaded_unit is not None
        assert loaded_unit.unit_id == proof_unit.unit_id
        assert loaded_unit.owner == proof_unit.owner
        assert loaded_unit.reference_count == proof_unit.reference_count

    def test_add_value_mapping(self, temp_storage, sample_proof_unit):
        """Test adding value-ProofUnit mappings."""
        proof_unit, _ = sample_proof_unit

        # Store ProofUnit first
        temp_storage.store_proof_unit(proof_unit)

        # Add mapping
        result = temp_storage.add_value_mapping("test_value_1", proof_unit.unit_id)
        assert result is True

        # Add another mapping
        result = temp_storage.add_value_mapping("test_value_2", proof_unit.unit_id)
        assert result is True

        # Get proof units for values
        proof_units_1 = temp_storage.get_proof_units_for_value("test_value_1")
        proof_units_2 = temp_storage.get_proof_units_for_value("test_value_2")

        assert len(proof_units_1) == 1
        assert len(proof_units_2) == 1
        assert proof_units_1[0].unit_id == proof_unit.unit_id
        assert proof_units_2[0].unit_id == proof_unit.unit_id

    def test_remove_value_mapping(self, temp_storage, sample_proof_unit):
        """Test removing value-ProofUnit mappings."""
        proof_unit, _ = sample_proof_unit

        # Store ProofUnit and add mapping
        temp_storage.store_proof_unit(proof_unit)
        temp_storage.add_value_mapping("test_value", proof_unit.unit_id)

        # Verify mapping exists
        proof_units = temp_storage.get_proof_units_for_value("test_value")
        assert len(proof_units) == 1

        # Remove mapping
        result = temp_storage.remove_value_mapping("test_value", proof_unit.unit_id)
        assert result is True

        # Verify mapping is removed
        proof_units = temp_storage.get_proof_units_for_value("test_value")
        assert len(proof_units) == 0

    def test_delete_proof_unit(self, temp_storage, sample_proof_unit):
        """Test deleting ProofUnit from storage."""
        proof_unit, _ = sample_proof_unit

        # Store ProofUnit and add mapping
        temp_storage.store_proof_unit(proof_unit)
        temp_storage.add_value_mapping("test_value", proof_unit.unit_id)

        # Delete ProofUnit
        result = temp_storage.delete_proof_unit(proof_unit.unit_id)
        assert result is True

        # Verify ProofUnit is deleted
        loaded_unit = temp_storage.load_proof_unit(proof_unit.unit_id)
        assert loaded_unit is None

        # Verify mapping is also deleted
        proof_units = temp_storage.get_proof_units_for_value("test_value")
        assert len(proof_units) == 0

    def test_duplicate_mapping_prevention(self, temp_storage, sample_proof_unit):
        """Test that duplicate mappings are prevented."""
        proof_unit, _ = sample_proof_unit

        # Store ProofUnit
        temp_storage.store_proof_unit(proof_unit)

        # Add same mapping twice
        result1 = temp_storage.add_value_mapping("test_value", proof_unit.unit_id)
        result2 = temp_storage.add_value_mapping("test_value", proof_unit.unit_id)

        assert result1 is True
        assert result2 is True  # Should not fail, but should not create duplicate

        # Should still only have one mapping
        proof_units = temp_storage.get_proof_units_for_value("test_value")
        assert len(proof_units) == 1


class TestProofs:
    """Test suite for Proofs class with mapping table structure."""

    @pytest.fixture
    def temp_proofs_storage(self):
        """Create temporary ProofsStorage for Proofs testing."""
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_proofs.db")
        storage = ProofsStorage(db_path)
        yield storage
        # Cleanup
        try:
            storage = None
            import time
            time.sleep(0.1)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

    @pytest.fixture
    def sample_proof_unit_for_proofs(self):
        """Create a sample ProofUnit for Proofs testing."""
        # Create test values
        value = Value("0x3000", 150, ValueState.UNSPENT)

        owner = "proofs_test_owner"

        # Create transaction
        txn = Transaction(
            sender=owner,
            recipient="proofs_recipient",
            nonce=5,
            signature=None,
            value=[value],
            time=datetime.datetime.now().isoformat()
        )

        # Create MultiTransactions
        multi_txns = MultiTransactions(
            sender=owner,
            multi_txns=[txn]
        )
        multi_txns.set_digest()

        # Create Merkle tree and proof
        merkle_tree = MerkleTree([multi_txns.digest])
        merkle_root = merkle_tree.get_root_hash()
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        return proof_unit, merkle_root

    def test_proofs_initialization(self, temp_proofs_storage):
        """Test Proofs class initialization."""
        proofs = Proofs("test_value_id", temp_proofs_storage)
        assert proofs.value_id == "test_value_id"
        assert proofs.storage == temp_proofs_storage
        assert len(proofs) == 0

    def test_add_proof_unit(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test adding ProofUnit to Proofs collection."""
        proof_unit, _ = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Add ProofUnit
        result = proofs.add_proof_unit(proof_unit)
        assert result is True
        assert len(proofs) == 1
        assert proof_unit.unit_id in proofs

    def test_remove_proof_unit(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test removing ProofUnit from Proofs collection."""
        proof_unit, _ = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Add then remove ProofUnit
        proofs.add_proof_unit(proof_unit)
        result = proofs.remove_proof_unit(proof_unit.unit_id)
        assert result is True
        assert len(proofs) == 0
        assert proof_unit.unit_id not in proofs

    def test_get_proof_units(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test retrieving all ProofUnits from collection."""
        proof_unit, _ = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Initially empty
        proof_units = proofs.get_proof_units()
        assert len(proof_units) == 0

        # Add ProofUnit
        proofs.add_proof_unit(proof_unit)

        # Retrieve
        proof_units = proofs.get_proof_units()
        assert len(proof_units) == 1
        assert proof_units[0].unit_id == proof_unit.unit_id

    def test_clear_all(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test clearing all ProofUnits from collection."""
        proof_unit, _ = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Add multiple ProofUnits
        proofs.add_proof_unit(proof_unit)
        proofs.add_proof_unit(proof_unit)  # Add same unit (will be shared)
        # The set should contain unique unit IDs, so length should be 1
        assert len(proofs) == 1

        # Clear all
        result = proofs.clear_all()
        assert result is True
        assert len(proofs) == 0

    def test_proofs_iteration(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test iteration over Proofs collection."""
        proof_unit, _ = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Add ProofUnit
        proofs.add_proof_unit(proof_unit)

        # Iterate
        count = 0
        for pu in proofs:
            assert pu.unit_id == proof_unit.unit_id
            count += 1
        assert count == 1

    def test_proof_unit_sharing(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test sharing the same ProofUnit across different Values."""
        proof_unit, _ = sample_proof_unit_for_proofs

        # Create two different Proofs collections
        proofs1 = Proofs("value_1", temp_proofs_storage)
        proofs2 = Proofs("value_2", temp_proofs_storage)

        # Add the same ProofUnit to both collections
        result1 = proofs1.add_proof_unit(proof_unit)
        result2 = proofs2.add_proof_unit(proof_unit)

        assert result1 is True
        assert result2 is True

        # Both collections should have the ProofUnit
        assert len(proofs1) == 1
        assert len(proofs2) == 1

        # The ProofUnit should have reference count of 2
        loaded_unit = temp_proofs_storage.load_proof_unit(proof_unit.unit_id)
        assert loaded_unit.reference_count == 2

    def test_reference_counting_on_removal(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test reference counting when removing shared ProofUnits."""
        proof_unit, _ = sample_proof_unit_for_proofs

        # Create two Proofs collections and share ProofUnit
        proofs1 = Proofs("value_1", temp_proofs_storage)
        proofs2 = Proofs("value_2", temp_proofs_storage)

        proofs1.add_proof_unit(proof_unit)
        proofs2.add_proof_unit(proof_unit)

        # Remove from one collection
        result = proofs1.remove_proof_unit(proof_unit.unit_id)
        assert result is True

        # ProofUnit should still exist (reference count should be 1)
        loaded_unit = temp_proofs_storage.load_proof_unit(proof_unit.unit_id)
        assert loaded_unit is not None
        assert loaded_unit.reference_count == 1

        # Remove from second collection
        result = proofs2.remove_proof_unit(proof_unit.unit_id)
        assert result is True

        # Now ProofUnit should be deleted (reference count 0)
        loaded_unit = temp_proofs_storage.load_proof_unit(proof_unit.unit_id)
        assert loaded_unit is None

    def test_load_existing_mappings(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test loading existing mappings on Proofs initialization."""
        proof_unit, _ = sample_proof_unit_for_proofs
        value_id = "persistent_value"

        # Create Proofs and add ProofUnit
        proofs1 = Proofs(value_id, temp_proofs_storage)
        proofs1.add_proof_unit(proof_unit)
        assert len(proofs1) == 1

        # Create new Proofs instance with same value_id
        proofs2 = Proofs(value_id, temp_proofs_storage)

        # Should load existing mappings
        assert len(proofs2) == 1
        assert proof_unit.unit_id in proofs2

    def test_verify_all_proof_units(self, temp_proofs_storage, sample_proof_unit_for_proofs):
        """Test verifying all ProofUnits in collection."""
        proof_unit, merkle_root = sample_proof_unit_for_proofs
        proofs = Proofs("test_value", temp_proofs_storage)

        # Add ProofUnit
        proofs.add_proof_unit(proof_unit)

        # Verify all ProofUnits
        results = proofs.verify_all_proof_units(merkle_root=merkle_root)
        assert len(results) == 1
        assert results[0][0] is True  # First result should be valid
        assert "successful" in results[0][1].lower()


class TestProofUnitRefactored:
    """Test suite for refactored ProofUnit functionality."""

    @pytest.fixture
    def sample_proof_unit_refactored(self):
        """Create a sample ProofUnit for testing refactored functionality."""
        value = Value("0x4000", 75, ValueState.UNSPENT)
        owner = "refactored_test_owner"

        txn = Transaction(
            sender=owner,
            recipient="refactored_recipient",
            nonce=10,
            signature=None,
            value=[value],
            time=datetime.datetime.now().isoformat()
        )

        multi_txns = MultiTransactions(
            sender=owner,
            multi_txns=[txn]
        )
        multi_txns.set_digest()

        merkle_tree = MerkleTree([multi_txns.digest])
        merkle_root = merkle_tree.get_root_hash()
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        proof_unit = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        return proof_unit, merkle_root

    def test_unit_id_generation(self, sample_proof_unit_refactored):
        """Test that unit_id is generated correctly."""
        proof_unit, _ = sample_proof_unit_refactored

        assert proof_unit.unit_id is not None
        assert len(proof_unit.unit_id) == 64  # SHA256 hash length
        assert isinstance(proof_unit.unit_id, str)

    def test_reference_counting_initialization(self, sample_proof_unit_refactored):
        """Test initial reference count."""
        proof_unit, _ = sample_proof_unit_refactored

        assert proof_unit.reference_count == 1

    def test_reference_increment_decrement(self, sample_proof_unit_refactored):
        """Test reference count increment and decrement."""
        proof_unit, _ = sample_proof_unit_refactored

        # Test increment
        initial_count = proof_unit.reference_count
        proof_unit.increment_reference()
        assert proof_unit.reference_count == initial_count + 1

        # Test decrement
        new_count = proof_unit.reference_count
        proof_unit.decrement_reference()
        assert proof_unit.reference_count == new_count - 1

    def test_can_be_deleted(self, sample_proof_unit_refactored):
        """Test can_be_deleted method."""
        proof_unit, _ = sample_proof_unit_refactored

        # Initially should not be deletable (reference count = 1)
        assert not proof_unit.can_be_deleted()

        # Decrement to 0
        proof_unit.decrement_reference()
        assert proof_unit.can_be_deleted()

    def test_serialization(self, sample_proof_unit_refactored):
        """Test ProofUnit serialization to dictionary."""
        proof_unit, _ = sample_proof_unit_refactored

        data = proof_unit.to_dict()

        assert isinstance(data, dict)
        assert 'unit_id' in data
        assert 'owner' in data
        assert 'owner_multi_txns' in data
        assert 'owner_mt_proof' in data
        assert 'reference_count' in data

        assert data['unit_id'] == proof_unit.unit_id
        assert data['owner'] == proof_unit.owner
        assert data['reference_count'] == proof_unit.reference_count

    def test_custom_unit_id(self):
        """Test ProofUnit creation with custom unit_id."""
        value = Value("0x5000", 25, ValueState.UNSPENT)
        owner = "custom_id_test"

        txn = Transaction(
            sender=owner,
            recipient="custom_recipient",
            nonce=15,
            signature=None,
            value=[value],
            time=datetime.datetime.now().isoformat()
        )

        multi_txns = MultiTransactions(
            sender=owner,
            multi_txns=[txn]
        )
        multi_txns.set_digest()

        merkle_tree = MerkleTree([multi_txns.digest])
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        custom_id = "custom_unit_id_12345"
        proof_unit = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof,
            unit_id=custom_id
        )

        assert proof_unit.unit_id == custom_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])