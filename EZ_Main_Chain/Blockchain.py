"""
EZchain Blockchain Implementation

This module provides a comprehensive blockchain implementation for real network deployment with support for:
- Main chain management
- Fork handling and resolution
- Block validation and consensus
- Efficient block retrieval and querying

The implementation follows modern Python practices and integrates seamlessly
with the EZchain ecosystem.
"""

import sys
import os
from typing import Optional, List, Dict, Set
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import hashlib
import json
import pickle
import threading
import datetime
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Main_Chain.Block import Block


class ConsensusStatus(Enum):
    """Block consensus status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ORPHANED = "orphaned"


@dataclass
class ChainConfig:
    """Blockchain configuration parameters."""
    max_fork_height: int = 6  # Maximum fork height before confirmation
    confirmation_blocks: int = 6  # Number of blocks needed for confirmation
    enable_fork_resolution: bool = True
    debug_mode: bool = False

    # Persistence configuration
    data_directory: str = "blockchain_data"  # Directory to store blockchain data
    auto_save: bool = True  # Automatically save after adding blocks
    backup_enabled: bool = True  # Enable automatic backups
    backup_interval: int = 100  # Create backup every N blocks
    max_backups: int = 10  # Maximum number of backup files to keep
    compression_enabled: bool = False  # Enable data compression
    integrity_check: bool = True  # Enable data integrity checks


class ForkNode:
    """
    Represents a node in the fork tree structure.

    Each ForkNode contains a block and references to its parent and children,
    enabling efficient fork traversal and resolution.
    """

    def __init__(self, block: Block, parent: Optional['ForkNode'] = None):
        self.block = block
        self.parent = parent
        self.children: List['ForkNode'] = []
        self.is_main_chain = False  # Flag indicating if this node is part of main chain
        self.height = block.get_index()
        self.consensus_status = ConsensusStatus.PENDING

    def add_child(self, child: 'ForkNode') -> None:
        """Add a child fork node."""
        self.children.append(child)
        child.parent = self

    def get_chain_path(self) -> List[Block]:
        """Get the chain path from genesis to this node."""
        path = []
        current = self
        while current:
            path.append(current.block)
            current = current.parent
        return list(reversed(path))

    def find_by_hash(self, block_hash: str) -> Optional['ForkNode']:
        """Find a fork node by block hash in this subtree."""
        if self.block.get_hash() == block_hash:
            return self

        for child in self.children:
            result = child.find_by_hash(block_hash)
            if result:
                return result
        return None

    def find_by_index(self, index: int) -> Optional['ForkNode']:
        """Find a fork node by block index in this subtree."""
        if self.block.get_index() == index:
            return self

        for child in self.children:
            result = child.find_by_index(index)
            if result:
                return result
        return None

    def get_longest_path(self) -> List['ForkNode']:
        """Get the longest path from this node to any leaf."""
        if not self.children:
            return [self]

        longest_child_path = []
        for child in self.children:
            child_path = child.get_longest_path()
            if len(child_path) > len(longest_child_path):
                longest_child_path = child_path

        return [self] + longest_child_path

    def __str__(self) -> str:
        return f"ForkNode(Block#{self.block.get_index()}, Hash:{self.block.get_hash()[:8]}...)"

    def __repr__(self) -> str:
        return self.__str__()


class Blockchain:
    """
    Main blockchain implementation with fork support for real network deployment.

    This class manages the blockchain state, handles forks, validates blocks,
    provides various querying capabilities, and supports persistent storage.
    """

    def __init__(self, genesis_block: Optional[Block] = None, config: Optional[ChainConfig] = None):
        """
        Initialize the blockchain.

        Args:
            genesis_block: Optional genesis block. If None, a default one will be created.
            config: Blockchain configuration. If None, default configuration will be used.
        """
        self.config = config or ChainConfig()
        self.logger = self._setup_logger()

        # Initialize storage
        self._initialize_storage()

        # Thread safety lock
        self._lock = threading.RLock()

        # Main chain (always stores the longest valid chain)
        self.main_chain: List[Block] = []

        # Fork tree structure
        self.fork_tree_root: Optional[ForkNode] = None
        self.main_chain_tip: Optional[ForkNode] = None

        # Block lookup caches for performance
        self.hash_to_fork_node: Dict[str, ForkNode] = {}
        self.index_to_fork_node: Dict[int, ForkNode] = {}

        # Consensus tracking
        self.confirmed_blocks: Set[str] = set()
        self.orphaned_blocks: Set[str] = set()

        # Try to load existing data or initialize with genesis block
        if not self._load_from_storage():
            self._initialize_genesis_block(genesis_block)

        self.logger.info("Blockchain initialized for real network deployment")

    def _initialize_storage(self) -> None:
        """Initialize storage directories and files."""
        self.data_dir = Path(self.config.data_directory)
        self.backup_dir = self.data_dir / "backups"

        # Create directories if they don't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.chain_file = self.data_dir / "blockchain_data.json"
        self.metadata_file = self.data_dir / "blockchain_metadata.json"
        self.chain_file_pkl = self.data_dir / "blockchain_data.pkl"
        self.metadata_file_pkl = self.data_dir / "blockchain_metadata.pkl"

        self.logger.info(f"Storage initialized at: {self.data_dir.absolute()}")

    def _calculate_data_checksum(self, data: dict) -> str:
        """
        Calculate checksum for data integrity verification.

        Args:
            data: Data dictionary to calculate checksum for

        Returns:
            SHA256 checksum as hex string
        """
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

    def _serialize_block(self, block: Block) -> dict:
        """
        Serialize a block to dictionary format for storage.

        Args:
            block: Block to serialize

        Returns:
            Serialized block data as dictionary
        """
        other_data, bloom_data = block.block_to_json()
        return {
            "block_data": json.loads(other_data),
            "bloom_filter": json.loads(bloom_data),
            "hash": block.get_hash()
        }

    def _deserialize_block(self, block_data: dict) -> Block:
        """
        Deserialize a block from dictionary format.

        Args:
            block_data: Serialized block data

        Returns:
            Deserialized Block object
        """
        from EZ_Units.Bloom import bloom_decoder

        block_dict = block_data["block_data"]
        bloom_dict = block_data["bloom_filter"]

        # Recreate block
        block = Block(
            index=block_dict["index"],
            m_tree_root=block_dict["m_tree_root"],
            miner=block_dict["miner"],
            pre_hash=block_dict["pre_hash"],
            nonce=block_dict["nonce"],
            version=block_dict["version"],
            time=datetime.datetime.fromisoformat(block_dict["time"]) if block_dict["time"] else None
        )

        # Set bloom filter using the decoder function
        block.bloom = bloom_decoder(bloom_dict)

        # Set signature
        block.sig = block_dict["sig"]

        return block

    def _serialize_fork_node(self, fork_node: ForkNode) -> dict:
        """
        Serialize a fork node to dictionary format.

        Args:
            fork_node: ForkNode to serialize

        Returns:
            Serialized ForkNode data
        """
        return {
            "block": self._serialize_block(fork_node.block),
            "parent_hash": fork_node.parent.block.get_hash() if fork_node.parent else None,
            "is_main_chain": fork_node.is_main_chain,
            "height": fork_node.height,
            "consensus_status": fork_node.consensus_status.value,
            "children_hashes": [child.block.get_hash() for child in fork_node.children]
        }

    def _setup_logger(self) -> logging.Logger:
        """Set up logging for the blockchain."""
        logger = logging.getLogger(f"Blockchain-{id(self)}")
        logger.setLevel(logging.DEBUG if self.config.debug_mode else logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _initialize_genesis_block(self, genesis_block: Optional[Block]) -> None:
        """Initialize the blockchain with a genesis block."""
        if genesis_block is None:
            # Don't auto-create genesis block - let the caller explicitly provide one
            self.logger.info("No genesis block provided - blockchain initialized empty")
            return

        self.logger.info(f"Using provided genesis block: {genesis_block.get_hash()[:8]}...")

        # Validate genesis block
        if genesis_block.get_index() != 0:
            raise ValueError("Genesis block must have index 0")

        # Add to main chain
        self.main_chain.append(genesis_block)

        # Create fork node
        genesis_node = ForkNode(genesis_block)
        genesis_node.is_main_chain = True
        genesis_node.consensus_status = ConsensusStatus.CONFIRMED

        self.fork_tree_root = genesis_node
        self.main_chain_tip = genesis_node

        # Update caches
        self.hash_to_fork_node[genesis_block.get_hash()] = genesis_node
        self.index_to_fork_node[0] = genesis_node

        self.confirmed_blocks.add(genesis_block.get_hash())

    def has_blocks(self) -> bool:
        """Check if the blockchain has any blocks."""
        return len(self.main_chain) > 0

    def _add_first_genesis_block(self, genesis_block: Block) -> bool:
        """
        Add the first genesis block to an empty blockchain.

        Args:
            genesis_block: The genesis block to add

        Returns:
            True if successfully added
        """
        # Validate genesis block
        if genesis_block.get_index() != 0:
            raise ValueError("Genesis block must have index 0")

        self.logger.info(f"Adding first genesis block: {genesis_block.get_hash()[:8]}...")

        # Add to main chain
        self.main_chain.append(genesis_block)

        # Create fork node
        genesis_node = ForkNode(genesis_block)
        genesis_node.is_main_chain = True
        genesis_node.consensus_status = ConsensusStatus.CONFIRMED

        # Set as root and tip
        self.fork_tree_root = genesis_node
        self.main_chain_tip = genesis_node

        # Update caches
        self.hash_to_fork_node[genesis_block.get_hash()] = genesis_node
        self.index_to_fork_node[0] = genesis_node

        # Mark as confirmed
        self.confirmed_blocks.add(genesis_block.get_hash())

        self.logger.info("First genesis block added successfully")
        return True

    def get_latest_block(self) -> Block:
        """Get the latest block in the main chain."""
        if not self.has_blocks():
            raise ValueError("Blockchain is empty - no blocks available")
        return self.main_chain[-1]

    def get_latest_block_hash(self) -> str:
        """Get the hash of the latest block in the main chain."""
        if not self.has_blocks():
            raise ValueError("Blockchain is empty - no block hash available")
        return self.get_latest_block().get_hash()

    def get_latest_block_index(self) -> int:
        """Get the index of the latest block in the main chain."""
        if not self.has_blocks():
            raise ValueError("Blockchain is empty - no block index available")
        return self.get_latest_block().get_index()

    def get_chain_length(self) -> int:
        """Get the total length of the main chain."""
        return len(self.main_chain)

    def get_block_by_index(self, index: int) -> Optional[Block]:
        """
        Get a block by its index from the main chain.

        Args:
            index: The block index to retrieve.

        Returns:
            The block if found, None otherwise.
        """
        if 0 <= index < len(self.main_chain):
            return self.main_chain[index]
        return None

    def get_block_by_hash(self, block_hash: str) -> Optional[Block]:
        """
        Get a block by its hash.

        Searches both the main chain and fork tree.

        Args:
            block_hash: The block hash to search for.

        Returns:
            The block if found, None otherwise.
        """
        # First search in main chain (most common case)
        for block in self.main_chain:
            if block.get_hash() == block_hash:
                return block

        # Search in fork tree
        if self.fork_tree_root:
            fork_node = self.fork_tree_root.find_by_hash(block_hash)
            if fork_node:
                return fork_node.block

        return None

    def get_fork_node_by_hash(self, block_hash: str) -> Optional[ForkNode]:
        """
        Get a fork node by block hash.

        Args:
            block_hash: The block hash to search for.

        Returns:
            The fork node if found, None otherwise.
        """
        return self.hash_to_fork_node.get(block_hash)

    def get_fork_node_by_index(self, index: int) -> Optional[ForkNode]:
        """
        Get a fork node by block index.

        Args:
            index: The block index to search for.

        Returns:
            The fork node if found, None otherwise.
        """
        return self.index_to_fork_node.get(index)

    def is_block_in_main_chain(self, block_hash: str) -> bool:
        """
        Check if a block is in the main chain.

        Args:
            block_hash: The block hash to check.

        Returns:
            True if the block is in the main chain, False otherwise.
        """
        for block in self.main_chain:
            if block.get_hash() == block_hash:
                return True
        return False

    def is_block_confirmed(self, block_hash: str) -> bool:
        """
        Check if a block is confirmed.

        Args:
            block_hash: The block hash to check.

        Returns:
            True if the block is confirmed, False otherwise.
        """
        return block_hash in self.confirmed_blocks

    def get_latest_confirmed_block_index(self) -> Optional[int]:
        """
        Get the index of the latest confirmed block.

        Returns:
            The index of the latest confirmed block, or None if no blocks are confirmed.
        """
        if not self.main_chain:
            return None

        latest_index = self.get_latest_block_index()
        confirmed_index = latest_index - self.config.confirmation_blocks + 1

        if confirmed_index > 0:
            return confirmed_index
        return None

    def _validate_block_for_addition(self, block: Block, parent_block: Block) -> bool:
        """
        Validate a block before adding it to the chain.

        Args:
            block: The block to validate.
            parent_block: The parent block.

        Returns:
            True if the block is valid, False otherwise.
        """
        # Check basic block properties
        if block.get_index() != parent_block.get_index() + 1:
            self.logger.error(
                f"Block index mismatch: expected {parent_block.get_index() + 1}, "
                f"got {block.get_index()}"
            )
            return False

        if block.get_pre_hash() != parent_block.get_hash():
            self.logger.error(
                f"Block hash mismatch: expected {parent_block.get_hash()}, "
                f"got {block.get_pre_hash()}"
            )
            return False

        # Validate block signature
        if not block.verify_signature():
            self.logger.error(f"Block signature verification failed: {block.get_hash()}")
            return False

        return True

    def _add_fork_node(self, block: Block, parent_fork_node: ForkNode) -> ForkNode:
        """
        Add a fork node to the fork tree.

        Args:
            block: The block to add.
            parent_fork_node: The parent fork node.

        Returns:
            The created fork node.
        """
        fork_node = ForkNode(block, parent_fork_node)
        parent_fork_node.add_child(fork_node)

        # Update caches
        self.hash_to_fork_node[block.get_hash()] = fork_node
        self.index_to_fork_node[block.get_index()] = fork_node

        return fork_node

    def _update_main_chain(self, new_tip: ForkNode) -> None:
        """
        Update the main chain to follow a new fork tip.

        Args:
            new_tip: The new fork node to set as main chain tip.
        """
        # Get the new main chain path
        new_chain = new_tip.get_chain_path()

        # Find the common ancestor
        common_ancestor_index = 0
        for i, (old_block, new_block) in enumerate(zip(self.main_chain, new_chain)):
            if old_block.get_hash() == new_block.get_hash():
                common_ancestor_index = i
            else:
                break

        # Update main chain
        self.main_chain = new_chain

        # Update main chain flags
        current = new_tip
        while current and current.block.get_index() > common_ancestor_index:
            current.is_main_chain = True
            # Mark old chain nodes as no longer main chain
            old_hash = self.main_chain[current.block.get_index()].get_hash() if current.block.get_index() < len(self.main_chain) else None
            if old_hash and old_hash != current.block.get_hash():
                old_node = self.hash_to_fork_node.get(old_hash)
                if old_node:
                    old_node.is_main_chain = False
            current = current.parent

        self.main_chain_tip = new_tip
        self.logger.info(f"Updated main chain to new tip: Block#{new_tip.block.get_index()}")

    def _process_fork_resolution(self, new_fork_node: ForkNode) -> bool:
        """
        Process fork resolution and update main chain if necessary.

        Args:
            new_fork_node: The new fork node to consider for main chain.

        Returns:
            True if the main chain was updated, False otherwise.
        """
        if not self.main_chain_tip:
            return False

        # Check if the new fork is longer than the current main chain
        if new_fork_node.height > self.main_chain_tip.height:
            self._update_main_chain(new_fork_node)
            return True
        elif new_fork_node.height == self.main_chain_tip.height:
            # In case of tie, prefer the current main chain (or implement tie-breaking logic)
            if not new_fork_node.is_main_chain:
                self.logger.info(
                    f"Fork tie at height {new_fork_node.height}, keeping current main chain"
                )
            return False

        return False

    def add_block(self, block: Block) -> bool:
        """
        Add a block to the blockchain.

        This method handles blocks with fork support.

        Args:
            block: The block to add.

        Returns:
            True if the main chain was updated, False otherwise.

        Raises:
            ValueError: If the block is invalid or cannot be added.
        """
        return self._add_block_with_fork_handling(block)

    def _add_block_with_fork_handling(self, block: Block) -> bool:
        """
        Add a block with fork handling.

        Args:
            block: The block to add.

        Returns:
            True if the main chain was updated, False otherwise.
        """
        # Handle genesis block - allow adding if blockchain is empty
        if block.get_index() == 0:
            if self.has_blocks():
                # Genesis block already exists
                self.logger.warning("Genesis block already exists, ignoring additional genesis block")
                return True
            else:
                # First genesis block - add it to empty blockchain
                return self._add_first_genesis_block(block)

        main_chain_updated = False

        # Check if block extends the current main chain
        if (self.main_chain_tip and
            block.get_pre_hash() == self.get_latest_block_hash() and
            block.get_index() == self.get_latest_block_index() + 1):

            parent_fork_node = self.main_chain_tip

            # Validate block
            if not self._validate_block_for_addition(block, parent_fork_node.block):
                raise ValueError(f"Block validation failed: {block.get_hash()}")

            # Add to main chain
            self.main_chain.append(block)

            # Add fork node
            new_fork_node = self._add_fork_node(block, parent_fork_node)
            new_fork_node.is_main_chain = True
            self.main_chain_tip = new_fork_node

            main_chain_updated = True
            self.logger.info(f"Added block #{block.get_index()} to main chain")

        else:
            # Block doesn't extend main chain, search for parent in fork tree
            parent_fork_node = self._find_parent_in_fork_tree(block)

            if parent_fork_node is None:
                self.logger.error(f"Cannot find parent for block #{block.get_index()}")
                raise ValueError(f"Parent block not found: {block.get_pre_hash()}")

            # Validate block
            if not self._validate_block_for_addition(block, parent_fork_node.block):
                raise ValueError(f"Block validation failed: {block.get_hash()}")

            # Add as fork
            new_fork_node = self._add_fork_node(block, parent_fork_node)

            self.logger.info(
                f"Added block #{block.get_index()} as fork at height {new_fork_node.height}"
            )

            # Process fork resolution
            if self.config.enable_fork_resolution:
                main_chain_updated = self._process_fork_resolution(new_fork_node)

        # Update consensus status
        self._update_consensus_status()

        # Auto save if enabled
        if self.config.auto_save:
            self.save_to_storage()

        # Periodic backup
        if (self.config.backup_enabled and
            len(self.main_chain) % self.config.backup_interval == 0):
            self.create_backup()
            self.cleanup_old_backups()

        return main_chain_updated

    def _find_parent_in_fork_tree(self, block: Block) -> Optional[ForkNode]:
        """
        Find the parent of a block in the fork tree.

        Args:
            block: The block whose parent to find.

        Returns:
            The parent fork node if found, None otherwise.
        """
        parent_hash = block.get_pre_hash()
        return self.hash_to_fork_node.get(parent_hash)

    def _update_consensus_status(self) -> None:
        """Update consensus status for blocks based on confirmation rules."""
        confirmed_index = self.get_latest_confirmed_block_index()
        if confirmed_index is None:
            return

        # Mark blocks up to confirmed index as confirmed
        for fork_node in self.hash_to_fork_node.values():
            if fork_node.block.get_index() <= confirmed_index:
                if fork_node.consensus_status != ConsensusStatus.CONFIRMED:
                    fork_node.consensus_status = ConsensusStatus.CONFIRMED
                    self.confirmed_blocks.add(fork_node.block.get_hash())

            # Mark orphaned blocks (blocks that are too far from main chain)
            elif (self.main_chain_tip and
                  fork_node.block.get_index() < self.main_chain_tip.height - self.config.max_fork_height):
                if fork_node.consensus_status != ConsensusStatus.ORPHANED:
                    fork_node.consensus_status = ConsensusStatus.ORPHANED
                    self.orphaned_blocks.add(fork_node.block.get_hash())

    def get_all_forks_at_height(self, height: int) -> List[ForkNode]:
        """
        Get all fork nodes at a specific height.

        Args:
            height: The height to search for.

        Returns:
            List of fork nodes at the specified height.
        """
        return [node for node in self.hash_to_fork_node.values() if node.height == height]

    def get_main_chain_blocks(self) -> List[Block]:
        """Get all blocks in the main chain."""
        return self.main_chain.copy()

    def get_fork_statistics(self) -> Dict[str, int]:
        """
        Get statistics about forks in the blockchain.

        Returns:
            Dictionary containing fork statistics.
        """
        total_nodes = len(self.hash_to_fork_node)
        main_chain_nodes = len(self.main_chain)
        fork_nodes = total_nodes - main_chain_nodes
        confirmed_nodes = len(self.confirmed_blocks)
        orphaned_nodes = len(self.orphaned_blocks)

        # Count forks by height
        height_counts = {}
        for node in self.hash_to_fork_node.values():
            height = node.height
            height_counts[height] = height_counts.get(height, 0) + 1

        max_forks_at_height = max(height_counts.values()) if height_counts else 0

        return {
            "total_nodes": total_nodes,
            "main_chain_nodes": main_chain_nodes,
            "fork_nodes": fork_nodes,
            "confirmed_nodes": confirmed_nodes,
            "orphaned_nodes": orphaned_nodes,
            "max_forks_at_height": max_forks_at_height,
            "current_height": self.get_latest_block_index(),
            "confirmed_height": self.get_latest_confirmed_block_index() or 0
        }

    def is_valid_chain(self) -> bool:
        """
        Validate the integrity of the main chain.

        Returns:
            True if the chain is valid, False otherwise.
        """
        for i in range(1, len(self.main_chain)):
            current_block = self.main_chain[i]
            previous_block = self.main_chain[i - 1]

            if current_block.get_pre_hash() != previous_block.get_hash():
                self.logger.error(
                    f"Chain validation failed at index {i}: "
                    f"hash mismatch between blocks {i-1} and {i}"
                )
                return False

            if current_block.get_index() != previous_block.get_index() + 1:
                self.logger.error(
                    f"Chain validation failed at index {i}: "
                    f"index sequence broken between blocks {i-1} and {i}"
                )
                return False

        # Validate all block signatures
        for block in self.main_chain:
            if not block.verify_signature():
                self.logger.error(f"Chain validation failed: invalid signature in block {block.get_index()}")
                return False

        return True

    def print_chain_info(self, detailed: bool = False) -> None:
        """
        Print information about the blockchain.

        Args:
            detailed: If True, print detailed information about each block.
        """
        print("=" * 60)
        print("Blockchain Information (Real Network Mode)")
        print("=" * 60)
        print(f"Chain length: {len(self.main_chain)}")
        print(f"Latest block: #{self.get_latest_block_index()} (Hash: {self.get_latest_block_hash()[:16]}...)")
        print(f"Latest confirmed block: #{self.get_latest_confirmed_block_index() or 'None'}")

        stats = self.get_fork_statistics()
        print(f"Total fork nodes: {stats['total_nodes']}")
        print(f"Fork nodes: {stats['fork_nodes']}")
        print(f"Confirmed nodes: {stats['confirmed_nodes']}")
        print(f"Orphaned nodes: {stats['orphaned_nodes']}")

        if detailed:
            print("\nDetailed Block Information:")
            print("-" * 40)
            for i, block in enumerate(self.main_chain):
                status = "+" if self.is_block_confirmed(block.get_hash()) else "o"
                print(f"{status} Block #{i}: {block.get_miner()} | {block.get_hash()[:16]}...")
                if detailed and i > 0:
                    print(f"    Previous: {block.get_pre_hash()[:16]}...")
                    print(f"    Merkle Root: {block.get_m_tree_root()[:16]}...")

        print("=" * 60)

    def print_fork_tree(self, start_node: Optional[ForkNode] = None, indent: int = 0) -> None:
        """
        Print the fork tree structure.

        Args:
            start_node: The node to start printing from. If None, starts from root.
            indent: The indentation level for printing.
        """
        if start_node is None:
            start_node = self.fork_tree_root

        if start_node is None:
            print("Fork tree is empty")
            return

        # Print current node
        main_chain_marker = "*" if start_node.is_main_chain else "o"
        status_marker = {
            ConsensusStatus.PENDING: "o",
            ConsensusStatus.CONFIRMED: "+",
            ConsensusStatus.ORPHANED: "x"
        }.get(start_node.consensus_status, "?")

        print(" " * indent + f"{main_chain_marker}{status_marker} "
              f"Block #{start_node.block.get_index()} "
              f"(Hash: {start_node.block.get_hash()[:8]}...) "
              f"Miner: {start_node.block.get_miner()}")

        # Print children
        for child in sorted(start_node.children, key=lambda x: x.block.get_index()):
            self.print_fork_tree(child, indent + 2)

    def __len__(self) -> int:
        """Return the length of the main chain."""
        return len(self.main_chain)

    def __str__(self) -> str:
        """String representation of the blockchain."""
        return (f"Blockchain(length={len(self.main_chain)}, "
                f"latest_block=#{self.get_latest_block_index()})")

    def __repr__(self) -> str:
        """Detailed string representation of the blockchain."""
        return self.__str__()

    # ==================== PERSISTENCE METHODS ====================

    def save_to_storage(self, backup: bool = False) -> bool:
        """
        Save the entire blockchain state to persistent storage.

        Args:
            backup: If True, create a backup instead of main save

        Returns:
            True if save was successful, False otherwise
        """
        with self._lock:
            try:
                # Prepare blockchain data
                blockchain_data = {
                    "version": "1.0",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "config": asdict(self.config),
                    "main_chain": [self._serialize_block(block) for block in self.main_chain],
                    "confirmed_blocks": list(self.confirmed_blocks),
                    "orphaned_blocks": list(self.orphaned_blocks),
                    "fork_tree_root": self._serialize_fork_node(self.fork_tree_root) if self.fork_tree_root else None,
                    "main_chain_tip_hash": self.main_chain_tip.block.get_hash() if self.main_chain_tip else None,
                    "hash_to_fork_node": {block_hash: self._serialize_fork_node(fork_node)
                                        for block_hash, fork_node in self.hash_to_fork_node.items()}
                }

                # Calculate checksum
                checksum = self._calculate_data_checksum(blockchain_data)
                blockchain_data["checksum"] = checksum

                # Save metadata
                metadata = {
                    "version": "1.0",
                    "saved_at": datetime.datetime.now().isoformat(),
                    "chain_length": len(self.main_chain),
                    "latest_block_hash": self.get_latest_block_hash() if self.main_chain else None,
                    "checksum": checksum,
                    "fork_statistics": self.get_fork_statistics()
                }

                # Choose file paths based on backup flag
                if backup:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    chain_file = self.backup_dir / f"blockchain_backup_{timestamp}.json"
                    metadata_file = self.backup_dir / f"metadata_backup_{timestamp}.json"
                    chain_file_pkl = self.backup_dir / f"blockchain_backup_{timestamp}.pkl"
                    metadata_file_pkl = self.backup_dir / f"metadata_backup_{timestamp}.pkl"
                else:
                    chain_file = self.chain_file
                    metadata_file = self.metadata_file
                    chain_file_pkl = self.chain_file_pkl
                    metadata_file_pkl = self.metadata_file_pkl

                # Save as JSON (human readable)
                with open(chain_file, 'w', encoding='utf-8') as f:
                    json.dump(blockchain_data, f, indent=2, default=str)

                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, default=str)

                # Also save as pickle for faster loading
                with open(chain_file_pkl, 'wb') as f:
                    pickle.dump(blockchain_data, f)

                with open(metadata_file_pkl, 'wb') as f:
                    pickle.dump(metadata, f)

                self.logger.info(f"Blockchain saved to {chain_file}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to save blockchain: {str(e)}")
                return False

    def _load_from_storage(self) -> bool:
        """
        Load blockchain state from persistent storage.

        Returns:
            True if load was successful, False otherwise
        """
        with self._lock:
            try:
                # Try pickle first (faster), fall back to JSON
                if self.chain_file_pkl.exists() and self.metadata_file_pkl.exists():
                    try:
                        with open(self.chain_file_pkl, 'rb') as f:
                            blockchain_data = pickle.load(f)
                        with open(self.metadata_file_pkl, 'rb') as f:
                            metadata = pickle.load(f)
                        self.logger.info("Loaded blockchain from pickle files")
                    except Exception:
                        # Fall back to JSON
                        with open(self.chain_file, 'r', encoding='utf-8') as f:
                            blockchain_data = json.load(f)
                        with open(self.metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        self.logger.info("Loaded blockchain from JSON files")

                elif self.chain_file.exists() and self.metadata_file.exists():
                    with open(self.chain_file, 'r', encoding='utf-8') as f:
                        blockchain_data = json.load(f)
                    with open(self.metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    self.logger.info("Loaded blockchain from JSON files")
                else:
                    self.logger.info("No existing blockchain data found, starting fresh")
                    return False

                # Verify data integrity
                if self.config.integrity_check:
                    stored_checksum = blockchain_data.get("checksum")
                    if stored_checksum:
                        # Temporarily remove checksum for verification
                        temp_checksum = blockchain_data.pop("checksum")
                        calculated_checksum = self._calculate_data_checksum(blockchain_data)
                        blockchain_data["checksum"] = temp_checksum

                        if stored_checksum != calculated_checksum:
                            self.logger.error("Data integrity check failed - checksum mismatch")
                            return False
                        self.logger.info("Data integrity check passed")

                # Load main chain
                self.main_chain = []
                for block_data in blockchain_data["main_chain"]:
                    block = self._deserialize_block(block_data)
                    self.main_chain.append(block)

                # Load sets
                self.confirmed_blocks = set(blockchain_data.get("confirmed_blocks", []))
                self.orphaned_blocks = set(blockchain_data.get("orphaned_blocks", []))

                # Rebuild fork tree from saved fork nodes
                self._rebuild_fork_tree_from_saved_data(blockchain_data)

                # Validate loaded chain
                if not self.is_valid_chain():
                    self.logger.error("Loaded chain failed validation")
                    return False

                self.logger.info(f"Successfully loaded blockchain with {len(self.main_chain)} blocks")
                return True

            except Exception as e:
                self.logger.error(f"Failed to load blockchain: {str(e)}")
                return False

    def _rebuild_fork_tree_from_saved_data(self, blockchain_data: dict) -> None:
        """
        Rebuild the fork tree structure from loaded saved data.

        Args:
            blockchain_data: Loaded blockchain data dictionary
        """
        # Rebuild all fork nodes from saved data
        saved_fork_nodes = blockchain_data.get("hash_to_fork_node", {})
        hash_to_fork_node = {}

        # First pass: recreate all fork nodes
        for block_hash, fork_node_data in saved_fork_nodes.items():
            block = self._deserialize_block(fork_node_data["block"])
            fork_node = ForkNode(block)
            fork_node.is_main_chain = fork_node_data["is_main_chain"]
            fork_node.height = fork_node_data["height"]
            fork_node.consensus_status = ConsensusStatus(fork_node_data["consensus_status"])
            hash_to_fork_node[block_hash] = fork_node

        # Second pass: rebuild relationships
        for block_hash, fork_node_data in saved_fork_nodes.items():
            fork_node = hash_to_fork_node[block_hash]
            parent_hash = fork_node_data.get("parent_hash")
            if parent_hash and parent_hash in hash_to_fork_node:
                parent_node = hash_to_fork_node[parent_hash]
                fork_node.parent = parent_node
                parent_node.children.append(fork_node)

        # Set root and main structures
        if self.main_chain:
            genesis_hash = self.main_chain[0].get_hash()
            self.fork_tree_root = hash_to_fork_node.get(genesis_hash)
        else:
            self.fork_tree_root = None

        # Update caches
        self.hash_to_fork_node = hash_to_fork_node
        self.index_to_fork_node = {}
        for fork_node in hash_to_fork_node.values():
            self.index_to_fork_node[fork_node.height] = fork_node

        # Set main chain tip
        tip_hash = blockchain_data.get("main_chain_tip_hash")
        if tip_hash and tip_hash in hash_to_fork_node:
            self.main_chain_tip = hash_to_fork_node[tip_hash]
        elif self.main_chain:
            # Find the tip from main chain
            latest_hash = self.main_chain[-1].get_hash()
            self.main_chain_tip = hash_to_fork_node.get(latest_hash)
        else:
            self.main_chain_tip = None

    def _rebuild_fork_tree(self, blockchain_data: dict) -> None:
        """
        Rebuild the fork tree structure from loaded data.

        Args:
            blockchain_data: Loaded blockchain data dictionary
        """
        # First pass: create all fork nodes from main chain
        hash_to_fork_node = {}

        # Build main chain nodes first
        if self.main_chain:
            # Genesis node
            genesis_node = ForkNode(self.main_chain[0])
            genesis_node.is_main_chain = True
            genesis_node.consensus_status = ConsensusStatus.CONFIRMED
            self.fork_tree_root = genesis_node
            hash_to_fork_node[genesis_node.block.get_hash()] = genesis_node

            # Build main chain
            current_node = genesis_node
            for block in self.main_chain[1:]:
                fork_node = ForkNode(block, current_node)
                fork_node.is_main_chain = True
                current_node.add_child(fork_node)
                hash_to_fork_node[block.get_hash()] = fork_node
                current_node = fork_node

        # Try to reconstruct additional fork structure if available
        root_data = blockchain_data.get("fork_tree_root")
        if root_data and root_data != hash_to_fork_node.get(self.main_chain[0].get_hash()):
            # If we have detailed fork tree data, we could rebuild it here
            # For now, we'll use the main chain reconstruction
            pass

        # Rebuild caches
        self.hash_to_fork_node = hash_to_fork_node
        self.index_to_fork_node = {}
        for fork_node in hash_to_fork_node.values():
            self.index_to_fork_node[fork_node.height] = fork_node

        # Set main chain tip
        if self.main_chain:
            # Find the tip from main chain
            latest_hash = self.main_chain[-1].get_hash()
            self.main_chain_tip = hash_to_fork_node.get(latest_hash)
        else:
            self.main_chain_tip = None

    def _rebuild_fork_node_recursive(self, node_data: dict, hash_to_fork_node: dict) -> ForkNode:
        """
        Recursively rebuild fork node and its children.

        Args:
            node_data: Serialized fork node data
            hash_to_fork_node: Dictionary mapping hashes to fork nodes

        Returns:
            Reconstructed ForkNode
        """
        block = self._deserialize_block(node_data["block"])
        fork_node = ForkNode(block)
        fork_node.is_main_chain = node_data["is_main_chain"]
        fork_node.height = node_data["height"]
        fork_node.consensus_status = ConsensusStatus(node_data["consensus_status"])

        # Store in dictionary
        hash_to_fork_node[block.get_hash()] = fork_node

        return fork_node

    def create_backup(self) -> bool:
        """
        Create a backup of the current blockchain state.

        Returns:
            True if backup was successful, False otherwise
        """
        return self.save_to_storage(backup=True)

    def auto_save(self) -> bool:
        """
        Perform automatic save if enabled.

        Returns:
            True if save was performed and successful, False otherwise
        """
        if self.config.auto_save:
            return self.save_to_storage()
        return False

    def cleanup_old_backups(self) -> int:
        """
        Clean up old backup files, keeping only the most recent ones.

        Returns:
            Number of files removed
        """
        if not self.backup_dir.exists():
            return 0

        # Get all backup files
        backup_files = list(self.backup_dir.glob("blockchain_backup_*.json"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # Remove excess backups
        removed_count = 0
        for backup_file in backup_files[self.config.max_backups:]:
            try:
                backup_file.unlink()
                # Also remove corresponding pickle file
                pkl_file = backup_file.with_suffix('.pkl')
                if pkl_file.exists():
                    pkl_file.unlink()
                removed_count += 1
                self.logger.info(f"Removed old backup: {backup_file}")
            except Exception as e:
                self.logger.error(f"Failed to remove backup {backup_file}: {str(e)}")

        return removed_count