#!/usr/bin/env python3
"""
Comprehensive unit tests for BlockIndexList module with verify_index_list functionality.
"""

import unittest
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_BlockIndex.BlockIndexList import BlockIndexList
    from EZ_Main_Chain.Block import Block
    from EZ_Units.MerkleTree import MerkleTree
except ImportError as e:
    print(f"Error importing required modules: {e}")
    sys.exit(1)


class MockBlockchainAccess:
    """
    Mock blockchain access class for testing BlockIndexList verification.
    Simulates a blockchain with configurable blocks and owner addresses.
    """

    def __init__(self):
        self.blocks = {}
        self.chain_length = 0

    def add_block(self, block):
        """Add a block to the mock blockchain."""
        self.blocks[block.get_index()] = block
        self.chain_length = max(self.chain_length, block.get_index() + 1)

    def get_block(self, index):
        """Get a block by index, return None if not found."""
        return self.blocks.get(index, None)

    def get_chain_length(self):
        """Get the total length of the blockchain."""
        return self.chain_length

    def clear(self):
        """Clear all blocks from the mock blockchain."""
        self.blocks.clear()
        self.chain_length = 0


class TestBlockIndexListBasic(unittest.TestCase):
    """Test suite for basic BlockIndexList functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_blockchain = MockBlockchainAccess()
        self.test_owner = "alice_address_123"
        self.test_indices = [1, 3, 5, 7]

        # Create test blockchain with owner's address in specific blocks
        self._create_test_blockchain()

    def _create_test_blockchain(self):
        """Create a test blockchain with blocks containing the owner's address."""
        self.mock_blockchain.clear()

        # Create blocks at indices 0-9
        for i in range(10):
            # Create test data for Merkle tree
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            # Create block
            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            # Add owner's address to Bloom filter for specific blocks
            if i in self.test_indices:
                block.add_item_to_bloom(self.test_owner)
                # Also add some other items to make it more realistic
                block.add_item_to_bloom(f"transaction_{i}")
                block.add_item_to_bloom(f"account_{i}")

            self.mock_blockchain.add_block(block)

    def test_block_index_list_initialization(self):
        """Test BlockIndexList initialization."""
        block_index_list = BlockIndexList(self.test_indices, self.test_owner)

        self.assertEqual(block_index_list.index_lst, self.test_indices)
        self.assertEqual(block_index_list.owner, self.test_owner)

    def test_block_index_list_initialization_without_owner(self):
        """Test BlockIndexList initialization without owner."""
        block_index_list = BlockIndexList(self.test_indices)

        self.assertEqual(block_index_list.index_lst, self.test_indices)
        self.assertIsNone(block_index_list.owner)

    def test_verify_index_list_valid_case(self):
        """Test verify_index_list with valid indices."""
        block_index_list = BlockIndexList(self.test_indices, self.test_owner)

        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)

    def test_verify_index_list_empty_indices(self):
        """Test verify_index_list with empty indices list."""
        block_index_list = BlockIndexList([], self.test_owner)

        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_no_owner(self):
        """Test verify_index_list without owner."""
        block_index_list = BlockIndexList(self.test_indices, None)

        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_no_blockchain_getter(self):
        """Test verify_index_list without blockchain getter."""
        block_index_list = BlockIndexList(self.test_indices, self.test_owner)

        with self.assertRaises(ValueError):
            block_index_list.verify_index_list(None)


class TestBlockIndexListVerification(unittest.TestCase):
    """Test suite for BlockIndexList verification scenarios."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_blockchain = MockBlockchainAccess()
        self.test_owner = "bob_address_456"

    def test_verify_index_list_missing_block(self):
        """Test verify_index_list when a block is missing."""
        # Create blockchain with only some blocks
        for i in [1, 2, 4]:  # Missing block 3
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )
            block.add_item_to_bloom(self.test_owner)
            self.mock_blockchain.add_block(block)

        block_index_list = BlockIndexList([1, 2, 3, 4], self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_owner_not_in_bloom(self):
        """Test verify_index_list when owner is not in block's Bloom filter."""
        # Create blockchain where owner is not in any Bloom filter
        for i in range(5):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )
            # Add other items but NOT the owner
            block.add_item_to_bloom(f"other_address_{i}")
            self.mock_blockchain.add_block(block)

        block_index_list = BlockIndexList([1, 2, 3], self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_missing_blocks(self):
        """Test verify_index_list when some blocks containing owner are missing."""
        # Create blockchain where owner is in blocks 2, 4, 6
        owner_blocks = [2, 4, 6]
        for i in range(8):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in owner_blocks:
                block.add_item_to_bloom(self.test_owner)

            self.mock_blockchain.add_block(block)

        # Test with incomplete index list (missing block 6)
        block_index_list = BlockIndexList([2, 4], self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_extra_blocks(self):
        """Test verify_index_list when index list contains blocks without owner."""
        # Create blockchain where owner is only in blocks 2 and 4
        owner_blocks = [2, 4]
        for i in range(6):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in owner_blocks:
                block.add_item_to_bloom(self.test_owner)

            self.mock_blockchain.add_block(block)

        # Test with index list containing extra block (3) without owner
        block_index_list = BlockIndexList([2, 3, 4], self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

    def test_verify_index_list_complete_match(self):
        """Test verify_index_list with perfect match."""
        # Create blockchain where owner is in blocks 1, 3, 5, 7
        owner_blocks = [1, 3, 5, 7]
        for i in range(10):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in owner_blocks:
                block.add_item_to_bloom(self.test_owner)

            self.mock_blockchain.add_block(block)

        # Test with correct index list
        block_index_list = BlockIndexList(owner_blocks, self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)


class TestBlockIndexListEdgeCases(unittest.TestCase):
    """Test suite for BlockIndexList edge cases."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_blockchain = MockBlockchainAccess()
        self.test_owner = "edge_case_owner"

    def test_verify_index_list_unsorted_indices(self):
        """Test verify_index_list with unsorted indices."""
        # Create blockchain with owner in blocks 5, 2, 8
        indices = [2, 5, 8]
        unsorted_indices = [8, 2, 5]  # Unsorted version

        for i in range(10):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in indices:
                block.add_item_to_bloom(self.test_owner)

            self.mock_blockchain.add_block(block)

        block_index_list = BlockIndexList(unsorted_indices, self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)

    def test_verify_index_list_duplicate_indices(self):
        """Test verify_index_list with duplicate indices."""
        # Create blockchain with owner in block 3
        test_data = [f"tx3_{j}" for j in range(4)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=3,
            m_tree_root=merkle_root,
            miner="miner_3",
            pre_hash="prev_hash_3"
        )
        block.add_item_to_bloom(self.test_owner)
        self.mock_blockchain.add_block(block)

        # Test with duplicate indices
        block_index_list = BlockIndexList([3, 3, 3], self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)  # Should still work, as all indices are valid

    def test_verify_index_list_no_chain_length_method(self):
        """Test verify_index_list when blockchain getter doesn't have get_chain_length."""
        class LimitedBlockchainAccess:
            def __init__(self):
                self.blocks = {}

            def add_block(self, block):
                self.blocks[block.get_index()] = block

            def get_block(self, index):
                return self.blocks.get(index, None)
            # Note: No get_chain_length method

        limited_blockchain = LimitedBlockchainAccess()

        # Add a block with owner
        test_data = [f"tx1_{j}" for j in range(4)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=1,
            m_tree_root=merkle_root,
            miner="miner_1",
            pre_hash="prev_hash_1"
        )
        block.add_item_to_bloom(self.test_owner)
        limited_blockchain.add_block(block)

        block_index_list = BlockIndexList([1], self.test_owner)
        result = block_index_list.verify_index_list(limited_blockchain)
        self.assertTrue(result)  # Should work without get_chain_length

    def test_verify_index_list_invalid_blockchain_getter(self):
        """Test verify_index_list with invalid blockchain getter."""
        class InvalidBlockchainAccess:
            def get_block(self, index):
                return None  # Always returns None

        invalid_blockchain = InvalidBlockchainAccess()
        block_index_list = BlockIndexList([1, 2, 3], self.test_owner)

        result = block_index_list.verify_index_list(invalid_blockchain)
        self.assertFalse(result)  # Should return False when blocks don't exist

    def test_verify_index_list_large_blockchain(self):
        """Test verify_index_list with a large blockchain (performance test)."""
        owner_blocks = list(range(0, 1000, 10))  # Every 10th block

        # Create a large blockchain
        for i in range(1000):
            test_data = [f"tx{i}_{j}" for j in range(4)]
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in owner_blocks:
                block.add_item_to_bloom(self.test_owner)

            self.mock_blockchain.add_block(block)

        block_index_list = BlockIndexList(owner_blocks, self.test_owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)

    def test_verify_index_list_bloom_filter_false_positive(self):
        """Test verify_index_list with Bloom filter false positive."""
        # Create a block that might have false positive
        test_data = [f"tx1_{j}" for j in range(4)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=1,
            m_tree_root=merkle_root,
            miner="miner_1",
            pre_hash="prev_hash_1"
        )

        # Add many items to potentially cause false positives
        for i in range(100):
            block.add_item_to_bloom(f"item_{i}")

        self.mock_blockchain.add_block(block)

        # Test with owner that wasn't explicitly added (might be false positive)
        block_index_list = BlockIndexList([1], "potential_false_positive")

        # Result depends on Bloom filter behavior - we just test it doesn't crash
        try:
            result = block_index_list.verify_index_list(self.mock_blockchain)
            # Could be True (false positive) or False (correct negative)
            self.assertIsInstance(result, bool)
        except Exception as e:
            self.fail(f"verify_index_list raised an exception: {e}")


class TestBlockIndexListIntegration(unittest.TestCase):
    """Integration tests for BlockIndexList with real-world scenarios."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_blockchain = MockBlockchainAccess()

    def test_realistic_transaction_scenario(self):
        """Test with a realistic scenario of user transactions across multiple blocks."""
        owner = "alice_crypto_address"

        # Simulate a blockchain where Alice has transactions in blocks 5, 8, 12, 15, 20
        alice_blocks = [5, 8, 12, 15, 20]

        for i in range(25):
            test_data = [f"tx_{i}_{j}" for j in range(10)]  # More transactions per block
            merkle_tree = MerkleTree(test_data)
            merkle_root = merkle_tree.get_root_hash()

            block = Block(
                index=i,
                m_tree_root=merkle_root,
                miner=f"miner_{i}",
                pre_hash=f"prev_hash_{i}" if i > 0 else "0"
            )

            if i in alice_blocks:
                # Add Alice's address and related transaction data
                block.add_item_to_bloom(owner)
                block.add_item_to_bloom(f"alice_tx_{i}")
                block.add_item_to_bloom(f"alice_account_{i}")
            elif i % 5 == 0:  # Some blocks have other users' data
                block.add_item_to_bloom(f"bob_tx_{i}")
                block.add_item_to_bloom(f"charlie_tx_{i}")

            self.mock_blockchain.add_block(block)

        # Test correct index list
        block_index_list = BlockIndexList(alice_blocks, owner)
        result = block_index_list.verify_index_list(self.mock_blockchain)
        self.assertTrue(result)

        # Test incomplete index list
        incomplete_list = BlockIndexList([5, 8, 12, 15], owner)  # Missing block 20
        result = incomplete_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)

        # Test index list with extra blocks
        extra_list = BlockIndexList([5, 8, 12, 15, 20, 22], owner)  # Block 22 doesn't contain owner
        result = extra_list.verify_index_list(self.mock_blockchain)
        self.assertFalse(result)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)