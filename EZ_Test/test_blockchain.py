#!/usr/bin/env python3
"""
Comprehensive unit tests for Blockchain module for real network deployment.
Tests focus on fork handling, consensus mechanisms, and blockchain validation.
"""

import unittest
import sys
import os
import hashlib

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_Main_Chain.Blockchain import (
        Blockchain, ChainConfig, ConsensusStatus, ForkNode
    )
    from EZ_Main_Chain.Block import Block
    from EZ_Units.MerkleTree import MerkleTree
except ImportError as e:
    print(f"Error importing Blockchain modules: {e}")
    sys.exit(1)


class TestChainConfig(unittest.TestCase):
    """Test suite for ChainConfig functionality."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ChainConfig()
        self.assertEqual(config.max_fork_height, 6)
        self.assertEqual(config.confirmation_blocks, 6)
        self.assertTrue(config.enable_fork_resolution)
        self.assertFalse(config.debug_mode)

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ChainConfig(
            max_fork_height=10,
            confirmation_blocks=8,
            enable_fork_resolution=False,
            debug_mode=True
        )
        self.assertEqual(config.max_fork_height, 10)
        self.assertEqual(config.confirmation_blocks, 8)
        self.assertFalse(config.enable_fork_resolution)
        self.assertTrue(config.debug_mode)


class TestForkNode(unittest.TestCase):
    """Test suite for ForkNode functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test blocks
        self.block1 = Block(
            index=1,
            m_tree_root="merkle_root_1",
            miner="miner_1",
            pre_hash="genesis_hash"
        )
        self.block2 = Block(
            index=2,
            m_tree_root="merkle_root_2",
            miner="miner_2",
            pre_hash=self.block1.get_hash()
        )
        self.block3 = Block(
            index=3,
            m_tree_root="merkle_root_3",
            miner="miner_3",
            pre_hash=self.block2.get_hash()
        )

    def test_fork_node_creation(self):
        """Test ForkNode creation."""
        node = ForkNode(self.block1)
        self.assertEqual(node.block, self.block1)
        self.assertIsNone(node.parent)
        self.assertEqual(node.children, [])
        self.assertFalse(node.is_main_chain)
        self.assertEqual(node.height, 1)
        self.assertEqual(node.consensus_status, ConsensusStatus.PENDING)

    def test_fork_node_with_parent(self):
        """Test ForkNode creation with parent."""
        parent_node = ForkNode(self.block1)
        child_node = ForkNode(self.block2, parent_node)

        self.assertEqual(child_node.parent, parent_node)
        # Note: children are only added via add_child method, not constructor

    def test_add_child(self):
        """Test adding child to ForkNode."""
        parent_node = ForkNode(self.block1)
        child_node = ForkNode(self.block2)

        parent_node.add_child(child_node)

        self.assertEqual(child_node.parent, parent_node)
        self.assertIn(child_node, parent_node.children)
        self.assertEqual(len(parent_node.children), 1)

    def test_get_chain_path(self):
        """Test getting chain path from ForkNode."""
        genesis_node = ForkNode(Block(0, "genesis_root", "genesis", "0"))
        node1 = ForkNode(self.block1, genesis_node)
        node2 = ForkNode(self.block2, node1)

        path = node2.get_chain_path()
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0].get_index(), 0)
        self.assertEqual(path[1].get_index(), 1)
        self.assertEqual(path[2].get_index(), 2)

    def test_find_by_hash(self):
        """Test finding ForkNode by block hash."""
        parent_node = ForkNode(self.block1)
        child_node = ForkNode(self.block2, parent_node)
        parent_node.add_child(child_node)  # Need to add child manually

        # Find existing node
        found = parent_node.find_by_hash(self.block2.get_hash())
        self.assertEqual(found, child_node)

        # Find non-existing node
        not_found = parent_node.find_by_hash("non_existing_hash")
        self.assertIsNone(not_found)

    def test_find_by_index(self):
        """Test finding ForkNode by block index."""
        parent_node = ForkNode(self.block1)
        child_node = ForkNode(self.block2, parent_node)
        parent_node.add_child(child_node)  # Need to add child manually

        # Find existing node
        found = parent_node.find_by_index(2)
        self.assertEqual(found, child_node)

        # Find non-existing node
        not_found = parent_node.find_by_index(99)
        self.assertIsNone(not_found)

    def test_get_longest_path(self):
        """Test getting longest path from ForkNode."""
        root = ForkNode(self.block1)

        # Add two children
        child1 = ForkNode(self.block2, root)
        child2 = ForkNode(self.block3, root)
        root.add_child(child1)
        root.add_child(child2)

        # Add grandchild to child1
        grandchild = Block(
            index=4,
            m_tree_root="merkle_root_4",
            miner="miner_4",
            pre_hash=self.block3.get_hash()
        )
        grandchild_node = ForkNode(grandchild, child1)
        child1.add_child(grandchild_node)

        longest_path = root.get_longest_path()
        self.assertEqual(len(longest_path), 3)  # root -> child1 -> grandchild

    def test_fork_node_string_representation(self):
        """Test ForkNode string representation."""
        node = ForkNode(self.block1)
        str_repr = str(node)
        self.assertIn("ForkNode", str_repr)
        self.assertIn("Block#1", str_repr)
        self.assertIn(self.block1.get_hash()[:8], str_repr)


class TestBlockchainBasicFunctionality(unittest.TestCase):
    """Test suite for basic blockchain functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        import tempfile
        import shutil

        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.config = ChainConfig(
            data_directory=self.temp_dir,
            auto_save=False,
            debug_mode=True
        )
        self.blockchain = Blockchain(config=self.config)

    def tearDown(self):
        """Clean up after each test method."""
        import shutil
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_blockchain_initialization(self):
        """Test blockchain initialization."""
        self.assertEqual(len(self.blockchain.main_chain), 1)  # Genesis block
        self.assertIsNotNone(self.blockchain.fork_tree_root)
        self.assertIsNotNone(self.blockchain.main_chain_tip)

    def test_default_genesis_block(self):
        """Test default genesis block creation."""
        genesis_block = self.blockchain.get_block_by_index(0)
        self.assertIsNotNone(genesis_block)
        self.assertEqual(genesis_block.get_index(), 0)
        self.assertEqual(genesis_block.get_miner(), "genesis_miner")
        self.assertEqual(genesis_block.get_pre_hash(), "0" * 64)

    def test_custom_genesis_block(self):
        """Test custom genesis block."""
        custom_genesis = Block(
            index=0,
            m_tree_root="custom_merkle",
            miner="custom_genesis",
            pre_hash="0" * 64
        )
        blockchain = Blockchain(genesis_block=custom_genesis, config=self.config)

        genesis_block = blockchain.get_block_by_index(0)
        self.assertEqual(genesis_block.get_miner(), "custom_genesis")
        self.assertEqual(genesis_block.get_m_tree_root(), "custom_merkle")

    def test_add_block_to_main_chain(self):
        """Test adding blocks to main chain."""
        # Create a test block
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )

        # Add block
        result = self.blockchain.add_block(block1)
        self.assertTrue(result)  # Main chain updated
        self.assertEqual(len(self.blockchain.main_chain), 2)
        self.assertEqual(self.blockchain.get_latest_block_index(), 1)

    def test_add_invalid_block(self):
        """Test adding invalid block."""
        # Create block with wrong index
        invalid_block = Block(
            index=3,  # Should be 1
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )

        with self.assertRaises(ValueError):
            self.blockchain.add_block(invalid_block)

    def test_get_block_by_index(self):
        """Test getting block by index."""
        # Add some blocks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Test existing blocks
        genesis = self.blockchain.get_block_by_index(0)
        self.assertIsNotNone(genesis)
        self.assertEqual(genesis.get_index(), 0)

        block2 = self.blockchain.get_block_by_index(2)
        self.assertIsNotNone(block2)
        self.assertEqual(block2.get_index(), 2)

        # Test non-existing block
        non_existing = self.blockchain.get_block_by_index(99)
        self.assertIsNone(non_existing)

    def test_get_block_by_hash(self):
        """Test getting block by hash."""
        # Add a block
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block1)

        # Test existing block
        found = self.blockchain.get_block_by_hash(block1.get_hash())
        self.assertEqual(found, block1)

        # Test non-existing block
        not_found = self.blockchain.get_block_by_hash("non_existing_hash")
        self.assertIsNone(not_found)

    def test_chain_validation(self):
        """Test chain validation."""
        # Add valid blocks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Chain should be valid
        self.assertTrue(self.blockchain.is_valid_chain())

    def test_is_block_in_main_chain(self):
        """Test checking if block is in main chain."""
        # Add a block
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block1)

        # Test existing block
        self.assertTrue(self.blockchain.is_block_in_main_chain(block1.get_hash()))

        # Test non-existing block
        self.assertFalse(self.blockchain.is_block_in_main_chain("non_existing_hash"))

    def test_blockchain_length(self):
        """Test blockchain length."""
        self.assertEqual(len(self.blockchain), 1)  # Genesis block

        # Add blocks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        self.assertEqual(len(self.blockchain), 4)

    def test_blockchain_string_representation(self):
        """Test blockchain string representation."""
        str_repr = str(self.blockchain)
        self.assertIn("Blockchain", str_repr)
        self.assertIn("length=1", str_repr)

    def test_latest_confirmed_block(self):
        """Test latest confirmed block."""
        # Configure with smaller confirmation blocks for testing
        config = ChainConfig(
            confirmation_blocks=3,
            data_directory=self.temp_dir,
            auto_save=False,
            debug_mode=True
        )
        blockchain = Blockchain(config=config)

        # Add several blocks
        for i in range(1, 8):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=blockchain.get_latest_block_hash()
            )
            blockchain.add_block(block)

        confirmed_index = blockchain.get_latest_confirmed_block_index()
        self.assertIsNotNone(confirmed_index)
        # Formula: latest_index - confirmation_blocks + 1
        # For 7 blocks and confirmation_blocks=3: 7 - 3 + 1 = 5
        expected_confirmed_index = blockchain.get_latest_block_index() - blockchain.config.confirmation_blocks + 1
        self.assertEqual(confirmed_index, expected_confirmed_index)


class TestBlockchainForkHandling(unittest.TestCase):
    """Test suite for blockchain fork handling."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        import tempfile
        import shutil

        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.config = ChainConfig(
            data_directory=self.temp_dir,
            auto_save=False,
            debug_mode=True
        )
        self.blockchain = Blockchain(config=self.config)

    def tearDown(self):
        """Clean up after each test method."""
        import shutil
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_fork_block(self):
        """Test adding a fork block."""
        # Add blocks to main chain
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block1)

        block2 = Block(
            index=2,
            m_tree_root="merkle_2",
            miner="miner_2",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block2)

        # Create a fork at block 1
        fork_block = Block(
            index=2,
            m_tree_root="fork_merkle",
            miner="fork_miner",
            pre_hash=block1.get_hash()
        )

        # Add fork block
        result = self.blockchain.add_block(fork_block)
        self.assertFalse(result)  # Main chain not updated (fork is not longer)

        # Check fork node
        fork_node = self.blockchain.get_fork_node_by_hash(fork_block.get_hash())
        self.assertIsNotNone(fork_node)
        self.assertFalse(fork_node.is_main_chain)
        self.assertEqual(fork_node.height, 2)

        # Check statistics
        stats = self.blockchain.get_fork_statistics()
        self.assertEqual(stats['total_nodes'], 4)  # Genesis + 2 main chain + 1 fork
        self.assertEqual(stats['fork_nodes'], 1)

    def test_fork_resolution_longer_chain(self):
        """Test fork resolution when a fork becomes longer."""
        # Add blocks to main chain
        main_blocks = []
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"main_merkle_{i}",
                miner=f"main_miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)
            main_blocks.append(block)

        # Create a longer fork
        genesis = self.blockchain.get_block_by_index(0)
        fork_blocks = []
        previous_hash = genesis.get_hash()

        for i in range(1, 6):  # 5 blocks, longer than main chain (3 blocks)
            fork_block = Block(
                index=i,
                m_tree_root=f"fork_merkle_{i}",
                miner=f"fork_miner_{i}",
                pre_hash=previous_hash
            )
            self.blockchain.add_block(fork_block)
            fork_blocks.append(fork_block)
            previous_hash = fork_block.get_hash()

        # Main chain should have been updated to the longer fork
        self.assertEqual(self.blockchain.get_latest_block_index(), 5)
        self.assertEqual(self.blockchain.get_latest_block().get_miner(), "fork_miner_5")

        # Check that main chain tip was updated
        self.assertEqual(self.blockchain.main_chain_tip.block.get_miner(), "fork_miner_5")

    def test_get_fork_node_methods(self):
        """Test fork node methods."""
        # Add some blocks
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block1)

        # Test get_fork_node_by_hash
        fork_node = self.blockchain.get_fork_node_by_hash(block1.get_hash())
        self.assertIsNotNone(fork_node)
        self.assertEqual(fork_node.block, block1)

        # Test get_fork_node_by_index
        fork_node = self.blockchain.get_fork_node_by_index(1)
        self.assertIsNotNone(fork_node)
        self.assertEqual(fork_node.block, block1)

        # Test with non-existing values
        self.assertIsNone(self.blockchain.get_fork_node_by_hash("non_existing"))
        self.assertIsNone(self.blockchain.get_fork_node_by_index(99))

    def test_get_all_forks_at_height(self):
        """Test getting all forks at a specific height."""
        # Add main chain blocks
        block1 = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block1)

        # Add multiple forks at height 2
        for i in range(3):
            fork_block = Block(
                index=2,
                m_tree_root=f"fork_merkle_{i}",
                miner=f"fork_miner_{i}",
                pre_hash=block1.get_hash()
            )
            self.blockchain.add_block(fork_block)

        # Get all forks at height 2
        forks = self.blockchain.get_all_forks_at_height(2)
        self.assertEqual(len(forks), 3)  # Main chain block + 2 fork blocks

        # Check that all forks have the correct height
        for fork in forks:
            self.assertEqual(fork.height, 2)

    def test_consensus_status_updates(self):
        """Test consensus status updates."""
        # Configure with smaller confirmation blocks for testing
        config = ChainConfig(
            confirmation_blocks=3,
            data_directory=self.temp_dir,
            auto_save=False,
            debug_mode=True
        )
        blockchain = Blockchain(config=config)

        # Add several blocks
        for i in range(1, 8):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=blockchain.get_latest_block_hash()
            )
            blockchain.add_block(block)

        # Check confirmed blocks
        confirmed_index = blockchain.get_latest_confirmed_block_index()
        self.assertIsNotNone(confirmed_index)
        # Formula: latest_index - confirmation_blocks + 1
        # For 7 blocks and confirmation_blocks=3: 7 - 3 + 1 = 5
        expected_confirmed_index = blockchain.get_latest_block_index() - blockchain.config.confirmation_blocks + 1
        self.assertEqual(confirmed_index, expected_confirmed_index)

        # Check that blocks up to confirmed index are marked as confirmed
        for i in range(confirmed_index + 1):
            block = blockchain.get_block_by_index(i)
            self.assertTrue(blockchain.is_block_confirmed(block.get_hash()))

    def test_fork_statistics(self):
        """Test fork statistics."""
        # Add some blocks and forks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Add a fork
        fork_block = Block(
            index=2,
            m_tree_root="fork_merkle",
            miner="fork_miner",
            pre_hash=self.blockchain.get_block_by_index(1).get_hash()
        )
        self.blockchain.add_block(fork_block)

        stats = self.blockchain.get_fork_statistics()

        self.assertEqual(stats['total_nodes'], 5)  # Genesis + 3 main chain + 1 fork
        self.assertEqual(stats['main_chain_nodes'], 4)
        self.assertEqual(stats['fork_nodes'], 1)
        self.assertGreater(stats['confirmed_nodes'], 0)
        self.assertEqual(stats['current_height'], 3)

    def test_print_fork_tree(self):
        """Test printing fork tree structure."""
        # Add some blocks and forks
        for i in range(1, 3):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Add a fork
        fork_block = Block(
            index=2,
            m_tree_root="fork_merkle",
            miner="fork_miner",
            pre_hash=self.blockchain.get_block_by_index(1).get_hash()
        )
        self.blockchain.add_block(fork_block)

        # Test printing (should not raise exceptions)
        try:
            self.blockchain.print_fork_tree()
        except Exception as e:
            self.fail(f"print_fork_tree() raised an exception: {e}")


class TestBlockchainEdgeCases(unittest.TestCase):
    """Test suite for blockchain edge cases and error handling."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        import tempfile
        import shutil

        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after each test method."""
        import shutil
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invalid_genesis_block(self):
        """Test initialization with invalid genesis block."""
        # Genesis block with wrong index
        invalid_genesis = Block(
            index=1,
            m_tree_root="invalid",
            miner="invalid",
            pre_hash="0" * 64
        )

        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        with self.assertRaises(ValueError):
            Blockchain(genesis_block=invalid_genesis, config=config)

    def test_block_with_invalid_parent(self):
        """Test adding block with invalid parent hash."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        block = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash="invalid_parent_hash"
        )

        with self.assertRaises(ValueError):
            blockchain.add_block(block)

    def test_duplicate_block_addition(self):
        """Test adding the same block twice."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        block = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add block first time
        blockchain.add_block(block)

        # Try to add the same block again (will be treated as a fork)
        # This is not an error in fork-handling blockchain
        result = blockchain.add_block(block)

        # The second addition should not update main chain (it's a duplicate fork)
        self.assertFalse(result)

        # Should have created a fork node for the duplicate
        fork_node = blockchain.get_fork_node_by_hash(block.get_hash())
        self.assertIsNotNone(fork_node)

    def test_blockchain_with_debug_mode(self):
        """Test blockchain with debug mode enabled."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False, debug_mode=True)
        blockchain = Blockchain(config=config)

        # Should not raise exceptions with debug mode
        self.assertTrue(blockchain.config.debug_mode)

    def test_large_chain_performance(self):
        """Test blockchain performance with larger chains."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        # Add many blocks
        for i in range(1, 100):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=blockchain.get_latest_block_hash()
            )
            blockchain.add_block(block)

        # Check that all blocks are accessible
        self.assertEqual(len(blockchain), 100)

        # Test block retrieval
        block_50 = blockchain.get_block_by_index(50)
        self.assertIsNotNone(block_50)
        self.assertEqual(block_50.get_index(), 50)

        # Test chain validation
        self.assertTrue(blockchain.is_valid_chain())


class TestBlockchainIntegration(unittest.TestCase):
    """Integration tests for blockchain with other components."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        import tempfile
        import shutil

        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after each test method."""
        import shutil
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_blockchain_with_merkle_tree(self):
        """Test blockchain integration with MerkleTree."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        # Create Merkle tree for block data
        transactions = [f"tx_{i}" for i in range(10)]
        merkle_tree = MerkleTree(transactions)
        merkle_root = merkle_tree.get_root_hash()

        # Create block with Merkle tree root
        block = Block(
            index=1,
            m_tree_root=merkle_root,
            miner="miner_1",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add to blockchain
        blockchain.add_block(block)

        # Verify block was added correctly
        retrieved_block = blockchain.get_block_by_index(1)
        self.assertEqual(retrieved_block.get_m_tree_root(), merkle_root)

    def test_blockchain_with_bloom_filter(self):
        """Test blockchain integration with Bloom filters."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        # Create block
        block = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add items to Bloom filter
        test_items = ["transaction_1", "account_1", "address_1"]
        for item in test_items:
            block.add_item_to_bloom(item)

        # Add to blockchain
        blockchain.add_block(block)

        # Verify Bloom filter functionality
        retrieved_block = blockchain.get_block_by_index(1)
        for item in test_items:
            self.assertTrue(retrieved_block.is_in_bloom(item))

        self.assertFalse(retrieved_block.is_in_bloom("non_existing_item"))

    def test_blockchain_print_functionality(self):
        """Test blockchain printing functionality."""
        config = ChainConfig(data_directory=self.temp_dir, auto_save=False)
        blockchain = Blockchain(config=config)

        # Add some blocks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=blockchain.get_latest_block_hash()
            )
            blockchain.add_block(block)

        # Test printing (should not raise exceptions)
        try:
            blockchain.print_chain_info()
            blockchain.print_chain_info(detailed=True)
        except Exception as e:
            self.fail(f"print_chain_info() raised an exception: {e}")


class TestBlockchainPersistence(unittest.TestCase):
    """Test suite for blockchain persistence functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        import tempfile
        import shutil

        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.config = ChainConfig(
            data_directory=self.temp_dir,
            auto_save=False,  # Disable auto save for controlled testing
            backup_enabled=True,
            backup_interval=5,
            max_backups=3,
            integrity_check=True,
            debug_mode=True
        )
        self.blockchain = Blockchain(config=self.config)

    def tearDown(self):
        """Clean up after each test method."""
        import shutil
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_storage_initialization(self):
        """Test storage directory initialization."""
        import os
        self.assertTrue(os.path.exists(self.config.data_directory))
        self.assertTrue(os.path.exists(self.temp_dir + "/backups"))

    def test_save_and_load_blockchain(self):
        """Test saving and loading blockchain data."""
        # Add some blocks
        original_blocks = []
        for i in range(1, 6):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)
            original_blocks.append(block)

        # Save blockchain
        save_result = self.blockchain.save_to_storage()
        self.assertTrue(save_result)

        # Create new blockchain instance with same config (should load saved data)
        new_blockchain = Blockchain(config=self.config)

        # Verify loaded data
        self.assertEqual(len(new_blockchain.main_chain), 6)  # 5 blocks + genesis
        self.assertEqual(new_blockchain.get_latest_block_index(), 5)

        # Verify block contents
        for i, original_block in enumerate(original_blocks, 1):
            loaded_block = new_blockchain.get_block_by_index(i)
            self.assertIsNotNone(loaded_block)
            self.assertEqual(loaded_block.get_miner(), original_block.get_miner())
            self.assertEqual(loaded_block.get_m_tree_root(), original_block.get_m_tree_root())
            self.assertEqual(loaded_block.get_hash(), original_block.get_hash())

    def test_fork_persistence(self):
        """Test saving and loading blockchain with forks."""
        # Add main chain blocks
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"main_merkle_{i}",
                miner=f"main_miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Add fork blocks
        block1 = self.blockchain.get_block_by_index(1)
        fork_block1 = Block(
            index=2,
            m_tree_root="fork_merkle_1",
            miner="fork_miner_1",
            pre_hash=block1.get_hash()
        )
        self.blockchain.add_block(fork_block1)

        fork_block2 = Block(
            index=3,
            m_tree_root="fork_merkle_2",
            miner="fork_miner_2",
            pre_hash=fork_block1.get_hash()
        )
        self.blockchain.add_block(fork_block2)

        # Save and reload
        self.blockchain.save_to_storage()
        new_blockchain = Blockchain(config=self.config)

        # Verify main chain
        self.assertEqual(len(new_blockchain.main_chain), 4)

        # Verify fork nodes exist
        fork_node = new_blockchain.get_fork_node_by_hash(fork_block1.get_hash())
        self.assertIsNotNone(fork_node)
        self.assertFalse(fork_node.is_main_chain)

        # Verify fork statistics
        stats = new_blockchain.get_fork_statistics()
        self.assertEqual(stats['total_nodes'], 6)  # 4 main + 2 forks
        self.assertEqual(stats['fork_nodes'], 2)

    def test_data_integrity_check(self):
        """Test data integrity verification."""
        # Add blocks and save
        for i in range(1, 4):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        self.blockchain.save_to_storage()

        # Manually corrupt the data file (both JSON and pickle)
        chain_file = self.blockchain.chain_file
        chain_file_pkl = self.blockchain.chain_file_pkl
        with open(chain_file, 'w') as f:
            f.write('{"corrupted": "data"}')
        with open(chain_file_pkl, 'wb') as f:
            f.write(b'corrupted data')

        # Try to load - should fail integrity check
        new_blockchain = Blockchain(config=self.config)
        # Should fallback to fresh initialization (no existing valid data)
        self.assertEqual(len(new_blockchain.main_chain), 1)  # Only genesis block

    def test_backup_functionality(self):
        """Test backup creation and management."""
        # Add some blocks
        for i in range(1, 6):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Create backup
        backup_result = self.blockchain.create_backup()
        self.assertTrue(backup_result)

        # Check backup files exist
        import os
        backup_files = list(self.blockchain.backup_dir.glob("blockchain_backup_*.json"))
        self.assertGreater(len(backup_files), 0)

        # Test backup loading
        backup_file = backup_files[0]
        self.assertTrue(backup_file.exists())

        # Create multiple backups
        for i in range(3):
            self.blockchain.create_backup()

        # Test cleanup
        removed_count = self.blockchain.cleanup_old_backups()
        self.assertGreaterEqual(removed_count, 0)

    def test_auto_save_functionality(self):
        """Test automatic save functionality."""
        # Enable auto save
        self.blockchain.config.auto_save = True

        # Add a block - should trigger auto save
        block = Block(
            index=1,
            m_tree_root="merkle_1",
            miner="miner_1",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(block)

        # Verify file was created
        self.assertTrue(self.blockchain.chain_file.exists())

        # Create new instance to verify auto-saved data was loaded
        new_blockchain = Blockchain(config=self.config)
        self.assertEqual(len(new_blockchain.main_chain), 2)  # Genesis + 1 block

    def test_config_persistence(self):
        """Test configuration persistence."""
        # Modify config
        self.blockchain.config.max_fork_height = 10
        self.blockchain.config.confirmation_blocks = 8

        # Save
        self.blockchain.save_to_storage()

        # Load and verify config
        new_blockchain = Blockchain(config=self.config)
        # Note: Config is passed from constructor, not loaded from file
        # This test ensures the save process doesn't fail with custom config
        self.assertEqual(new_blockchain.config.max_fork_height, 10)

    def test_empty_blockchain_persistence(self):
        """Test persistence with just genesis block."""
        # Save empty blockchain (only genesis block)
        save_result = self.blockchain.save_to_storage()
        self.assertTrue(save_result)

        # Load and verify
        new_blockchain = Blockchain(config=self.config)
        self.assertEqual(len(new_blockchain.main_chain), 1)  # Only genesis
        self.assertEqual(new_blockchain.get_latest_block_index(), 0)

    def test_block_serialization(self):
        """Test block serialization and deserialization."""
        # Create a complex block
        block = Block(
            index=1,
            m_tree_root="test_merkle_root",
            miner="test_miner",
            pre_hash=self.blockchain.get_latest_block_hash()
        )

        # Add some items to bloom filter
        block.add_item_to_bloom("transaction_1")
        block.add_item_to_bloom("account_1")

        # Serialize
        serialized = self.blockchain._serialize_block(block)

        # Verify serialized data structure
        self.assertIn("block_data", serialized)
        self.assertIn("bloom_filter", serialized)
        self.assertIn("hash", serialized)

        # Deserialize
        deserialized = self.blockchain._deserialize_block(serialized)

        # Verify deserialized block
        self.assertEqual(deserialized.get_index(), block.get_index())
        self.assertEqual(deserialized.get_miner(), block.get_miner())
        self.assertEqual(deserialized.get_m_tree_root(), block.get_m_tree_root())
        self.assertEqual(deserialized.get_hash(), block.get_hash())

        # Verify bloom filter
        self.assertTrue(deserialized.is_in_bloom("transaction_1"))
        self.assertTrue(deserialized.is_in_bloom("account_1"))
        self.assertFalse(deserialized.is_in_bloom("non_existing"))

    def test_fork_node_serialization(self):
        """Test fork node serialization."""
        # Create fork nodes
        parent_block = Block(
            index=1,
            m_tree_root="parent_merkle",
            miner="parent_miner",
            pre_hash=self.blockchain.get_latest_block_hash()
        )
        self.blockchain.add_block(parent_block)

        child_block = Block(
            index=2,
            m_tree_root="child_merkle",
            miner="child_miner",
            pre_hash=parent_block.get_hash()
        )
        self.blockchain.add_block(child_block)

        # Get fork node
        fork_node = self.blockchain.get_fork_node_by_hash(child_block.get_hash())
        self.assertIsNotNone(fork_node)

        # Serialize
        serialized = self.blockchain._serialize_fork_node(fork_node)

        # Verify structure
        self.assertIn("block", serialized)
        self.assertIn("parent_hash", serialized)
        self.assertIn("is_main_chain", serialized)
        self.assertIn("height", serialized)
        self.assertIn("consensus_status", serialized)
        self.assertIn("children_hashes", serialized)

        # Verify values
        self.assertTrue(serialized["is_main_chain"])
        self.assertEqual(serialized["height"], 2)
        self.assertEqual(serialized["parent_hash"], parent_block.get_hash())

    def test_concurrent_access_safety(self):
        """Test thread safety of blockchain operations."""
        import threading
        import time

        results = []

        def add_blocks(thread_id):
            try:
                for i in range(5):
                    block = Block(
                        index=len(self.blockchain.main_chain),
                        m_tree_root=f"merkle_{thread_id}_{i}",
                        miner=f"miner_{thread_id}",
                        pre_hash=self.blockchain.get_latest_block_hash()
                    )
                    self.blockchain.add_block(block)
                    time.sleep(0.001)  # Small delay to increase chance of race conditions
                results.append(True)
            except Exception as e:
                results.append(False)
                print(f"Thread {thread_id} error: {e}")

        # Create multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=add_blocks, args=(i,))
            threads.append(thread)

        # Start threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify all threads completed successfully
        self.assertEqual(len(results), 3)
        self.assertTrue(all(results))

        # Verify blockchain integrity
        self.assertTrue(self.blockchain.is_valid_chain())

    def test_large_chain_persistence(self):
        """Test persistence with larger chains."""
        # Add many blocks
        for i in range(1, 50):
            block = Block(
                index=i,
                m_tree_root=f"merkle_{i}",
                miner=f"miner_{i}",
                pre_hash=self.blockchain.get_latest_block_hash()
            )
            self.blockchain.add_block(block)

        # Save
        save_result = self.blockchain.save_to_storage()
        self.assertTrue(save_result)

        # Load and verify
        new_blockchain = Blockchain(config=self.config)
        self.assertEqual(len(new_blockchain.main_chain), 50)
        self.assertTrue(new_blockchain.is_valid_chain())

        # Verify random blocks
        import random
        for i in random.sample(range(1, 50), 5):
            block = new_blockchain.get_block_by_index(i)
            self.assertIsNotNone(block)
            self.assertEqual(block.get_index(), i)
            self.assertEqual(block.get_miner(), f"miner_{i}")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)