#!/usr/bin/env python3
"""
Example usage of ProofUnit verification function.
This demonstrates how to create and verify ProofUnits in a real scenario.
"""

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


def create_example_scenario():
    """Create an example scenario with transactions and proofs."""
    print("=== ProofUnit Verification Example ===\n")

    # 1. Create test values
    print("1. Creating test values...")
    value1 = Value("0x1000", 100, ValueState.UNSPENT)
    value2 = Value("0x2000", 50, ValueState.UNSPENT)
    print(f"   Created value1: {value1.begin_index} with amount {value1.value_num}")
    print(f"   Created value2: {value2.begin_index} with amount {value2.value_num}")

    # 2. Define owner
    owner = "alice_blockchain_address"
    print(f"\n2. Owner address: {owner}")

    # 3. Create transactions
    print("\n3. Creating transactions...")
    txn1 = Transaction(
        sender=owner,
        recipient="bob_address",
        nonce=1,
        signature=None,
        value=[value1],
        time=datetime.datetime.now().isoformat()
    )
    txn2 = Transaction(
        sender=owner,
        recipient="charlie_address",
        nonce=2,
        signature=None,
        value=[value2],
        time=datetime.datetime.now().isoformat()
    )
    print(f"   Created transaction 1: {owner} -> bob_address")
    print(f"   Created transaction 2: {owner} -> charlie_address")

    # 4. Create MultiTransactions
    print("\n4. Creating MultiTransactions...")
    multi_txns = MultiTransactions(
        sender=owner,
        multi_txns=[txn1, txn2]
    )
    multi_txns.set_digest()
    print(f"   MultiTransactions digest: {multi_txns.digest}")

    # 5. Create additional MultiTransactions for realistic Merkle tree
    print("\n5. Creating additional MultiTransactions for Merkle tree...")
    all_multi_txns = [multi_txns]

    for i in range(3):
        other_values = [Value(f"0x300{i}", 30 + i*10, ValueState.UNSPENT)]
        other_txn = Transaction(
            sender=f"other_user_{i}",
            recipient=f"recipient_{i}",
            nonce=10 + i,
            signature=None,
            value=other_values,
            time=datetime.datetime.now().isoformat()
        )
        other_multi = MultiTransactions(
            sender=f"other_user_{i}",
            multi_txns=[other_txn]
        )
        other_multi.set_digest()
        all_multi_txns.append(other_multi)
        print(f"   Created MultiTransactions for other_user_{i}")

    # 6. Build Merkle tree
    print("\n6. Building Merkle tree...")
    digest_list = [mt.digest for mt in all_multi_txns]
    merkle_tree = MerkleTree(digest_list)
    merkle_root = merkle_tree.get_root_hash()
    print(f"   Merkle root: {merkle_root}")

    # 7. Create Merkle proof for our MultiTransactions (index 0)
    print("\n7. Creating Merkle proof...")
    proof_data = merkle_tree.prf_list[0]
    merkle_proof = MerkleTreeProof(proof_data)
    print(f"   Merkle proof elements: {len(merkle_proof.mt_prf_list)}")

    # 8. Create ProofUnit
    print("\n8. Creating ProofUnit...")
    proof_unit = ProofUnit(
        owner=owner,
        owner_multi_txns=multi_txns,
        owner_mt_proof=merkle_proof
    )
    print("   ProofUnit created successfully")

    # 9. Verify the ProofUnit
    print("\n9. Verifying ProofUnit...")
    is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_root)

    # 10. Display results
    print(f"\n=== Verification Results ===")
    print(f"Valid: {is_valid}")
    print(f"Message: {message}")

    if is_valid:
        print("\n[PASSED] ProofUnit verification PASSED!")
        print("   - Owner matches MultiTransactions sender")
        print("   - All individual transactions have correct sender")
        print("   - Merkle proof is correctly structured")
        print("   - Merkle proof validates against the Merkle root")
    else:
        print("\n[FAILED] ProofUnit verification FAILED!")
        print(f"   Error: {message}")

    return proof_unit, merkle_root


def test_failure_scenarios():
    """Test various failure scenarios."""
    print("\n\n=== Testing Failure Scenarios ===")

    # Create basic setup
    value = Value("0x4000", 25, ValueState.UNSPENT)
    owner = "test_owner"

    txn = Transaction(
        sender=owner,
        recipient="recipient",
        nonce=1,
        signature=None,
        value=[value],
        time=datetime.datetime.now().isoformat()
    )

    # Test 1: Wrong owner
    print("\n1. Testing wrong owner...")
    multi_txns = MultiTransactions(sender=owner, multi_txns=[txn])
    multi_txns.set_digest()

    merkle_tree = MerkleTree([multi_txns.digest])
    merkle_proof = MerkleTreeProof(merkle_tree.prf_list[0])

    proof_unit = ProofUnit(
        owner="wrong_owner",  # Wrong owner
        owner_multi_txns=multi_txns,
        owner_mt_proof=merkle_proof
    )

    is_valid, message = proof_unit.verify_proof_unit(merkle_root=merkle_tree.get_root_hash())
    print(f"   Result: {is_valid} - {message}")

    # Test 2: Missing Merkle root parameter
    print("\n2. Testing missing Merkle root parameter...")
    proof_unit2 = ProofUnit(
        owner=owner,
        owner_multi_txns=multi_txns,
        owner_mt_proof=merkle_proof
    )

    is_valid, message = proof_unit2.verify_proof_unit()  # No merkle_root provided
    print(f"   Result: {is_valid} - {message}")


if __name__ == "__main__":
    try:
        # Run main example
        proof_unit, merkle_root = create_example_scenario()

        # Test failure scenarios
        test_failure_scenarios()

        print("\n\n=== Example completed successfully! ===")

    except Exception as e:
        print(f"\n[ERROR] Error in example: {e}")
        import traceback
        traceback.print_exc()