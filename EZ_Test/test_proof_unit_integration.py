#!/usr/bin/env python3
"""
Integration tests for ProofUnit module.
This test file creates real MultiTransactions, MerkleTrees, and ProofUnits to test
the verify_proof_unit function with actual system dependencies.
"""

import pytest
import sys
import os
import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Proof.ProofUnit import ProofUnit
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Units.MerkleTree import MerkleTree
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_Value.Value import Value, ValueState


class TestProofUnitIntegration:
    """Integration test suite for ProofUnit verification with real system components."""

    @pytest.fixture
    def test_setup(self):
        """Set up test data with realistic transactions and values."""
        # Create test values for transactions
        value1 = Value("0x1000", 100, ValueState.UNSPENT)
        value2 = Value("0x2000", 200, ValueState.UNSPENT)
        value3 = Value("0x3000", 50, ValueState.UNSPENT)

        # Test owner address
        test_owner = "test_owner_address_001"

        # Create test transactions
        txn1 = Transaction(
            sender=test_owner,
            recipient="recipient_001",
            nonce=1,
            signature=None,
            value=[value1, value2],
            time=datetime.datetime.now().isoformat()
        )

        txn2 = Transaction(
            sender=test_owner,
            recipient="recipient_002",
            nonce=2,
            signature=None,
            value=[value3],
            time=datetime.datetime.now().isoformat()
        )

        return {
            'owner': test_owner,
            'transactions': [txn1, txn2],
            'values': [value1, value2, value3]
        }

    def test_successful_proof_unit_verification(self, test_setup):
        """Test successful verification of a valid ProofUnit."""
        # Create MultiTransactions
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=test_setup['transactions']
        )

        # Set the digest for MultiTransactions
        multi_txns.set_digest()

        # Create multiple MultiTransactions to build a Merkle tree
        other_multi_txns_list = []
        for i in range(3):  # Create 3 additional MultiTransactions
            other_values = [Value(f"0x400{i}", 50 + i * 10, ValueState.UNSPENT)]
            other_txns = Transaction(
                sender=f"other_owner_{i}",
                recipient=f"other_recipient_{i}",
                nonce=i + 10,
                signature=None,
                value=other_values,
                time=datetime.datetime.now().isoformat()
            )
            other_multi = MultiTransactions(
                sender=f"other_owner_{i}",
                multi_txns=[other_txns]
            )
            other_multi.set_digest()
            other_multi_txns_list.append(other_multi)

        # Build list including our target MultiTransactions
        all_multi_txns = [multi_txns] + other_multi_txns_list

        # Create Merkle tree from digests
        digest_list = [mt.digest for mt in all_multi_txns]
        merkle_tree = MerkleTree(digest_list)
        merkle_root = merkle_tree.get_root_hash()

        # Get proof for our MultiTransactions (should be at index 0)
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        # Verify the ProofUnit
        is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

        assert is_valid, f"Expected valid verification, got error: {message}"
        assert message == "ProofUnit verification successful"

    def test_invalid_owner_mismatch(self, test_setup):
        """Test verification failure when owner doesn't match MultiTransactions sender."""
        # Create MultiTransactions with different sender
        multi_txns = MultiTransactions(
            sender="different_owner",
            multi_txns=test_setup['transactions']
        )
        multi_txns.set_digest()

        # Create a simple proof for testing
        merkle_tree = MerkleTree([multi_txns.digest])
        merkle_root = merkle_tree.get_root_hash()
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit with mismatched owner
        proof_unit = ProofUnit(
            owner=test_setup['owner'],  # Different from MultiTransactions sender
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        # Verify should fail
        is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

        assert not is_valid
        assert "does not match owner" in message

    def test_invalid_individual_transaction_sender(self, test_setup):
        """Test verification failure when individual transaction has wrong sender."""
        # Create one transaction with wrong sender
        wrong_txn = Transaction(
            sender="wrong_sender",
            recipient="recipient_001",
            nonce=3,
            signature=None,
            value=test_setup['values'],
            time=datetime.datetime.now().isoformat()
        )

        # Mix correct and incorrect transactions
        mixed_transactions = [test_setup['transactions'][0], wrong_txn]

        multi_txns = MultiTransactions(
            sender=test_setup['owner'],  # Correct sender for MultiTransactions
            multi_txns=mixed_transactions
        )
        multi_txns.set_digest()

        # Create simple proof
        merkle_tree = MerkleTree([multi_txns.digest])
        merkle_root = merkle_tree.get_root_hash()
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        # Verify should fail due to wrong individual transaction sender
        is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

        assert not is_valid
        assert "does not match owner" in message

    def test_invalid_merkle_proof_mismatch(self, test_setup):
        """Test verification failure when Merkle proof doesn't match MultiTransactions."""
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=test_setup['transactions']
        )
        multi_txns.set_digest()

        # Create Merkle tree with different data
        different_digest = "different_digest_data"
        merkle_tree = MerkleTree([different_digest])
        merkle_root = merkle_tree.get_root_hash()

        # Get proof for different data
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit with mismatched proof
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof  # Proof for different data
        )

        # Verify should fail
        is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

        assert not is_valid
        assert "Merkle proof leaf hash mismatch" in message

    def test_empty_merkle_proof(self, test_setup):
        """Test verification failure with empty Merkle proof."""
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=test_setup['transactions']
        )
        multi_txns.set_digest()

        # Create empty proof
        empty_proof = MerkleTreeProof([])

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=empty_proof
        )

        # Verify should fail
        is_valid, message = proof_unit.verify_proof_unit(merkle_root="some_root")

        assert not is_valid
        assert "Merkle proof list is empty" in message

    def test_missing_merkle_root_parameter(self, test_setup):
        """Test verification failure when merkle_root parameter is not provided."""
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=test_setup['transactions']
        )
        multi_txns.set_digest()

        # Create simple proof
        merkle_tree = MerkleTree([multi_txns.digest])
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        # Call verify_proof_unit without merkle_root parameter
        is_valid, message = proof_unit.verify_proof_unit()

        assert not is_valid
        assert "Merkle root is required" in message

    def test_none_digest_multi_transactions(self, test_setup):
        """Test verification failure when MultiTransactions digest is None."""
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=test_setup['transactions']
        )
        # Don't set digest - it will be None

        # Create simple proof (this will fail anyway but we test the specific case)
        merkle_proof = MerkleTreeProof(["dummy_hash", "dummy_root"])

        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        # Verify should fail
        is_valid, message = proof_unit.verify_proof_unit(merkle_root="some_root")

        assert not is_valid
        assert "MultiTransactions digest is None" in message

    def test_multiple_proof_units_in_same_tree(self, test_setup):
        """Test verification of multiple ProofUnits from the same Merkle tree."""
        # Create multiple MultiTransactions with different owners
        owners = ["owner_001", "owner_002", "owner_003"]
        multi_txns_list = []

        for i, owner in enumerate(owners):
            # Create unique values for each owner
            values = [Value(f"0x{5000+i*100}", 50 + i*10, ValueState.UNSPENT)]

            # Create transaction
            txn = Transaction(
                sender=owner,
                recipient=f"recipient_{i}",
                nonce=i,
                signature=None,
                value=values,
                time=datetime.datetime.now().isoformat()
            )

            # Create MultiTransactions
            multi_txns = MultiTransactions(
                sender=owner,
                multi_txns=[txn]
            )
            multi_txns.set_digest()
            multi_txns_list.append(multi_txns)

        # Build Merkle tree with all MultiTransactions
        digest_list = [mt.digest for mt in multi_txns_list]
        merkle_tree = MerkleTree(digest_list)
        merkle_root = merkle_tree.get_root_hash()

        # Create and verify ProofUnit for each owner
        for i, multi_txns in enumerate(multi_txns_list):
            proof_data = merkle_tree.prf_list[i]
            merkle_proof = MerkleTreeProof(proof_data)

            proof_unit = ProofUnit(
                owner=owners[i],
                owner_multi_txns=multi_txns,
                owner_mt_proof=merkle_proof
            )

            is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

            assert is_valid, f"ProofUnit for owner {owners[i]} failed verification: {message}"

    def test_large_transaction_set(self, test_setup):
        """Test verification with a larger set of transactions."""
        # Create many transactions
        many_transactions = []
        for i in range(10):
            values = [Value(f"0x{6000+i*100}", 10 + i, ValueState.UNSPENT)]
            txn = Transaction(
                sender=test_setup['owner'],
                recipient=f"bulk_recipient_{i}",
                nonce=i + 100,
                signature=None,
                value=values,
                time=datetime.datetime.now().isoformat()
            )
            many_transactions.append(txn)

        # Create MultiTransactions with many transactions
        multi_txns = MultiTransactions(
            sender=test_setup['owner'],
            multi_txns=many_transactions
        )
        multi_txns.set_digest()

        # Create a tree with multiple MultiTransactions
        other_multi_txns = []
        for i in range(5):  # Add 5 other MultiTransactions
            other_values = [Value(f"0x700{i}", 20, ValueState.UNSPENT)]
            other_txn = Transaction(
                sender=f"other_bulk_owner_{i}",
                recipient=f"other_bulk_recipient_{i}",
                nonce=i + 200,
                signature=None,
                value=other_values,
                time=datetime.datetime.now().isoformat()
            )
            other_multi = MultiTransactions(
                sender=f"other_bulk_owner_{i}",
                multi_txns=[other_txn]
            )
            other_multi.set_digest()
            other_multi_txns.append(other_multi)

        # Build tree
        all_multi_txns = [multi_txns] + other_multi_txns
        digest_list = [mt.digest for mt in all_multi_txns]
        merkle_tree = MerkleTree(digest_list)
        merkle_root = merkle_tree.get_root_hash()

        # Get proof for our large MultiTransactions
        proof_data = merkle_tree.prf_list[0]
        merkle_proof = MerkleTreeProof(proof_data)

        # Create and verify ProofUnit
        proof_unit = ProofUnit(
            owner=test_setup['owner'],
            owner_multi_txns=multi_txns,
            owner_mt_proof=merkle_proof
        )

        is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

        assert is_valid, f"Large transaction set verification failed: {message}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])