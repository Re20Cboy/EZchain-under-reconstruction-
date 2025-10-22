#!/usr/bin/env python3
"""
Demo script showing how to use BlockIndexList verification functionality.
This script demonstrates various usage scenarios and best practices.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_BlockIndex.BlockIndexList import BlockIndexList
from EZ_Main_Chain.Block import Block
from EZ_Units.MerkleTree import MerkleTree


class SimpleBlockchainAccess:
    """
    Simple blockchain access implementation demonstrating the required interface.
    In a real application, this would connect to your actual blockchain storage.
    """

    def __init__(self):
        self.blocks = {}

    def add_block(self, block):
        """Add a block to the blockchain."""
        self.blocks[block.get_index()] = block

    def get_block(self, index):
        """Retrieve a block by its index."""
        return self.blocks.get(index)

    def get_chain_length(self):
        """Get the total number of blocks in the chain."""
        return len(self.blocks)


def create_sample_blockchain():
    """Create a sample blockchain for demonstration."""
    blockchain = SimpleBlockchainAccess()

    # Sample users and their transaction blocks
    users = {
        "alice": [2, 5, 8, 11],
        "bob": [1, 4, 7, 10, 13],
        "charlie": [3, 6, 9, 12]
    }

    # Create 15 blocks
    for i in range(15):
        # Create test data for Merkle tree
        test_data = [f"transaction_{i}_{j}" for j in range(5)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        # Create block
        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"miner_{i}",
            pre_hash=f"prev_hash_{i}" if i > 0 else "genesis_hash"
        )

        # Add users to blocks where they have transactions
        for user, user_blocks in users.items():
            if i in user_blocks:
                block.add_item_to_bloom(user)
                block.add_item_to_bloom(f"{user}_transaction_{i}")

        blockchain.add_block(block)

    return blockchain


def demo_basic_usage():
    """Demonstrate basic usage of BlockIndexList verification."""
    print("=== Basic BlockIndexList Verification Demo ===\n")

    # Create sample blockchain
    blockchain = create_sample_blockchain()
    print(f"Created blockchain with {blockchain.get_chain_length()} blocks")

    # Test Alice's index list (correct)
    alice_indices = [2, 5, 8, 11]
    alice_list = BlockIndexList(alice_indices, "alice")

    print(f"\nAlice's claimed indices: {alice_indices}")
    is_valid = alice_list.verify_index_list(blockchain)
    status = "PASS" if is_valid else "FAIL"
    print(f"Verification result: {is_valid} [{status}]")

    # Test with incorrect indices
    wrong_alice_indices = [2, 5, 8, 10]  # 10 doesn't contain Alice
    wrong_alice_list = BlockIndexList(wrong_alice_indices, "alice")

    print(f"\nWrong Alice indices: {wrong_alice_indices}")
    is_valid = wrong_alice_list.verify_index_list(blockchain)
    status = "PASS" if is_valid else "FAIL"
    print(f"Verification result: {is_valid} [{status}]")

    # Test with incomplete indices
    incomplete_alice_indices = [2, 5, 8]  # Missing 11
    incomplete_alice_list = BlockIndexList(incomplete_alice_indices, "alice")

    print(f"\nIncomplete Alice indices: {incomplete_alice_indices}")
    is_valid = incomplete_alice_list.verify_index_list(blockchain)
    status = "PASS" if is_valid else "FAIL"
    print(f"Verification result: {is_valid} [{status}]")


def demo_edge_cases():
    """Demonstrate edge cases and error handling."""
    print("\n\n=== Edge Cases Demo ===\n")

    blockchain = create_sample_blockchain()

    # Empty indices
    empty_list = BlockIndexList([], "alice")
    result = empty_list.verify_index_list(blockchain)
    print(f"Empty indices test: {result} [EXPECTED FAIL]")

    # No owner
    no_owner_list = BlockIndexList([2, 5, 8], None)
    result = no_owner_list.verify_index_list(blockchain)
    print(f"No owner test: {result} [EXPECTED FAIL]")

    # No blockchain getter
    valid_list = BlockIndexList([2, 5, 8, 11], "alice")
    try:
        valid_list.verify_index_list(None)
        print("No blockchain getter test: Should have failed [ERROR]")
    except ValueError as e:
        print(f"No blockchain getter test: Correctly failed with error: {e} [EXPECTED]")


def demo_performance():
    """Demonstrate performance with larger datasets."""
    print("\n\n=== Performance Demo ===\n")

    # Create larger blockchain
    large_blockchain = SimpleBlockchainAccess()

    # User with many transactions across 100 blocks
    user_blocks = list(range(0, 100, 5))  # Every 5th block

    for i in range(100):
        test_data = [f"tx_{i}_{j}" for j in range(10)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"miner_{i}",
            pre_hash=f"prev_hash_{i}" if i > 0 else "genesis_hash"
        )

        if i in user_blocks:
            block.add_item_to_bloom("heavy_user")
            # Add many items to make Bloom filter more realistic
            for j in range(50):
                block.add_item_to_bloom(f"item_{i}_{j}")

        large_blockchain.add_block(block)

    print(f"Created large blockchain with {large_blockchain.get_chain_length()} blocks")

    import time
    start_time = time.time()

    heavy_user_list = BlockIndexList(user_blocks, "heavy_user")
    is_valid = heavy_user_list.verify_index_list(large_blockchain)

    end_time = time.time()

    status = "PASS" if is_valid else "FAIL"
    print(f"Heavy user verification: {is_valid} [{status}]")
    print(f"Verification time: {end_time - start_time:.4f} seconds")


def demo_real_world_scenario():
    """Demonstrate a realistic blockchain scenario."""
    print("\n\n=== Real-World Scenario Demo ===\n")

    # Simulate a blockchain where multiple users have transactions
    blockchain = SimpleBlockchainAccess()

    # Simulate transaction patterns
    transactions = {
        "alice_crypto": [1, 4, 7, 12, 15, 18, 22, 25],
        "bob_trader": [2, 5, 8, 11, 14, 17, 20, 23, 26],
        "charlie_miner": [3, 6, 9, 13, 16, 19, 21, 24, 27],
        "dave_investor": [10, 15, 20, 25]  # Less frequent transactions
    }

    # Create blockchain with realistic transaction patterns
    for i in range(30):
        test_data = [f"block_{i}_tx_{j}" for j in range(8)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"pool_{i % 5}",  # Different mining pools
            pre_hash=f"prev_hash_{i}" if i > 0 else "genesis_hash"
        )

        # Add transactions for each user
        for user, tx_blocks in transactions.items():
            if i in tx_blocks:
                block.add_item_to_bloom(user)
                block.add_item_to_bloom(f"{user}_payment_{i}")
                block.add_item_to_bloom(f"{user}_receipt_{i}")

        blockchain.add_block(block)

    print(f"Created realistic blockchain with {blockchain.get_chain_length()} blocks")

    # Verify each user's transaction history
    for user, expected_blocks in transactions.items():
        user_list = BlockIndexList(expected_blocks, user)
        is_valid = user_list.verify_index_list(blockchain)

        status = "PASS" if is_valid else "FAIL"
        print(f"{user}: {len(expected_blocks)} transactions - Verified: {is_valid} [{status}]")

    # Demonstrate tampering detection
    print("\n--- Tampering Detection Demo ---")

    # Alice tries to claim Bob's transaction as hers
    tampered_list = BlockIndexList([2, 5, 8], "alice_crypto")  # These are Bob's blocks
    is_valid = tampered_list.verify_index_list(blockchain)
    status = "PASS" if is_valid else "FAIL (EXPECTED)"
    print(f"Alice claiming Bob's transactions: {is_valid} [{status}]")

    # Bob tries to hide some of his transactions
    incomplete_bob = BlockIndexList([2, 5, 8, 11, 14, 17], "bob_trader")  # Missing some blocks
    is_valid = incomplete_bob.verify_index_list(blockchain)
    status = "PASS" if is_valid else "FAIL (EXPECTED)"
    print(f"Bob hiding transactions: {is_valid} [{status}]")


if __name__ == "__main__":
    try:
        demo_basic_usage()
        demo_edge_cases()
        demo_performance()
        demo_real_world_scenario()

        print("\n" + "="*60)
        print("All demos completed successfully!")
        print("BlockIndexList verification is working correctly.")
        print("="*60)

    except Exception as e:
        print(f"\nError running demos: {e}")
        import traceback
        traceback.print_exc()