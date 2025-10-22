import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

class BlockIndexList:
    def __init__(self, index_lst, owner=None):
        self.index_lst = index_lst
        self.owner = owner  # to be set later

    def verify_index_list(self, blockchain_getter) -> bool:
        """
        Verify the integrity of the BlockIndexList by checking if the owner's address
        appears in the Bloom filters of the specified blocks, and ensuring no blocks are missed.

        This function implements an optimized two-phase verification algorithm:
        1. Phase 1: Verify all indices in self.index_lst contain the owner's address
        2. Phase 2: Check for any additional blocks that should be included but are missing

        Args:
            blockchain_getter: A callable that can retrieve blocks by index or
                             provide information about the blockchain length
                             Expected methods:
                             - get_block(index) -> Block object or None
                             - get_chain_length() -> int (total number of blocks)

        Returns:
            bool: True if the index list is valid and complete, False otherwise
        """
        if not self.index_lst:
            return False

        if not self.owner:
            return False

        if not blockchain_getter:
            raise ValueError("blockchain_getter is required for verification")

        # Phase 1: Verify all indices in self.index_lst contain the owner's address
        # Sort indices for efficient processing
        sorted_indices = sorted(self.index_lst)

        for block_index in sorted_indices:
            # Get the block (will raise exception if blockchain_getter doesn't have this method)
            try:
                block = blockchain_getter.get_block(block_index)
            except AttributeError:
                raise ValueError("blockchain_getter must implement get_block(index) method")

            # Check if block exists
            if block is None:
                return False

            # Check if owner's address is in the block's Bloom filter
            if not block.is_in_bloom(self.owner):
                return False

        # Phase 2: Check for any additional blocks that should be included but are missing
        # This ensures completeness - no blocks containing the owner are missed

        try:
            chain_length = blockchain_getter.get_chain_length()
        except AttributeError:
            # If get_chain_length is not available, we can't check for missing blocks
            # In this case, we only verify the provided indices
            return True

        # Convert self.index_lst to a set for O(1) lookup
        index_set = set(self.index_lst)

        # Check blocks in batches to manage memory usage
        batch_size = 1000  # Process blocks in batches to avoid memory overload

        for start_idx in range(0, chain_length, batch_size):
            end_idx = min(start_idx + batch_size, chain_length)

            for block_index in range(start_idx, end_idx):
                # Skip blocks already in self.index_lst
                if block_index in index_set:
                    continue

                # Get the block
                block = blockchain_getter.get_block(block_index)
                if block is None:
                    continue

                # Check if this block contains the owner's address
                if block.is_in_bloom(self.owner):
                    # Found a block that contains the owner but is not in self.index_lst
                    return False

        # All checks passed
        return True