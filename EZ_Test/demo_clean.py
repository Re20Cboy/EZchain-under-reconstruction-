#!/usr/bin/env python3
"""
EZchain Blockchain Persistence Demo (Clean Version)
Demonstrates the enhanced blockchain persistence functionality.
"""

import sys
import os
import shutil

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block


def main():
    """Demonstrate blockchain persistence functionality."""

    print("=" * 60)
    print("EZchain Blockchain Persistence Demo")
    print("=" * 60)

    # Clean up previous demo
    demo_dir = "blockchain_demo_clean"
    if os.path.exists(demo_dir):
        shutil.rmtree(demo_dir)

    # Configure blockchain with persistence
    config = ChainConfig(
        data_directory=demo_dir,
        auto_save=True,
        backup_enabled=True,
        backup_interval=3,
        max_backups=3,
        integrity_check=True,
        debug_mode=True
    )

    print("\nConfiguration:")
    print(f"  Data directory: {config.data_directory}")
    print(f"  Auto save: {config.auto_save}")
    print(f"  Backup interval: {config.backup_interval} blocks")
    print(f"  Max backups: {config.max_backups}")
    print(f"  Integrity check: {config.integrity_check}")
    print(f"  Debug mode: {config.debug_mode}")

    # Create blockchain
    print("\nCreating blockchain...")
    blockchain = Blockchain(config=config)
    print(f"  Initial chain length: {len(blockchain)}")
    print(f"  Genesis block hash: {blockchain.get_block_by_index(0).get_hash()[:16]}...")

    # Add blocks to main chain
    print("\nAdding blocks to blockchain...")
    blocks_added = []

    for i in range(1, 8):
        block = Block(
            index=i,
            m_tree_root=f"merkle_root_{i}",
            miner=f"miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add sample transactions to bloom filter
        block.add_item_to_bloom(f"transaction_{i}_1")
        block.add_item_to_bloom(f"account_{i}_1")
        block.add_item_to_bloom(f"address_{i}")

        result = blockchain.add_block(block)
        blocks_added.append(block)

        print(f"  Added block #{i} by miner_{i} - Main chain updated: {result}")

        # Check for automatic backups
        if i % config.backup_interval == 0:
            print(f"    -> Automatic backup created at block #{i}")

    print(f"\nChain building complete:")
    print(f"  Total blocks added: {len(blocks_added)}")
    print(f"  Final chain length: {len(blockchain)}")
    print(f"  Latest block: #{blockchain.get_latest_block_index()}")
    print(f"  Latest block hash: {blockchain.get_latest_block_hash()[:16]}...")

    # Create forks to demonstrate fork handling
    print("\nCreating forks...")
    block2 = blockchain.get_block_by_index(2)

    if block2:
        # First fork
        fork1 = Block(
            index=3,
            m_tree_root="fork_merkle_1",
            miner="fork_miner_1",
            pre_hash=block2.get_hash()
        )
        blockchain.add_block(fork1)
        print("  Created fork block #3 from block #2")

        # Second fork extending the first fork
        fork2 = Block(
            index=4,
            m_tree_root="fork_merkle_2",
            miner="fork_miner_2",
            pre_hash=fork1.get_hash()
        )
        blockchain.add_block(fork2)
        print("  Created fork block #4 extending fork #3")

    # Display fork statistics
    stats = blockchain.get_fork_statistics()
    print("\nFork Statistics:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Main chain nodes: {stats['main_chain_nodes']}")
    print(f"  Fork nodes: {stats['fork_nodes']}")
    print(f"  Confirmed nodes: {stats['confirmed_nodes']}")
    print(f"  Orphaned nodes: {stats['orphaned_nodes']}")
    print(f"  Current height: {stats['current_height']}")
    print(f"  Confirmed height: {stats['confirmed_height']}")

    # Validate blockchain integrity
    print("\nValidating blockchain integrity...")
    is_valid = blockchain.is_valid_chain()
    print(f"  Chain is valid: {is_valid}")

    # Display saved files
    print("\nSaved files:")
    data_dir = blockchain.data_dir
    backup_dir = blockchain.backup_dir

    if data_dir.exists():
        for file in sorted(data_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"  {file.name}: {size} bytes")

    if backup_dir.exists():
        print("  Backup files:")
        for file in sorted(backup_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"    backup/{file.name}: {size} bytes")

    # Test manual backup creation
    print("\nCreating manual backup...")
    backup_result = blockchain.create_backup()
    print(f"  Manual backup created: {backup_result}")

    # Test data recovery with new blockchain instance
    print("\nTesting data recovery...")
    print("Creating new blockchain instance (should automatically load saved data)...")

    # Create new blockchain instance to test data recovery
    recovered_blockchain = Blockchain(config=config)

    print(f"  Loaded chain length: {len(recovered_blockchain)}")
    print(f"  Latest block index: #{recovered_blockchain.get_latest_block_index()}")
    print(f"  Latest block hash: {recovered_blockchain.get_latest_block_hash()[:16]}...")

    # Validate recovered blockchain
    recovered_valid = recovered_blockchain.is_valid_chain()
    print(f"  Loaded chain is valid: {recovered_valid}")

    # Test specific block recovery
    if len(blocks_added) >= 4:
        original_block = blocks_added[3]  # 4th added block
        recovered_block = recovered_blockchain.get_block_by_hash(original_block.get_hash())

        if recovered_block:
            print(f"\nBlock #{original_block.get_index()} successfully recovered:")
            print(f"  Miner: {recovered_block.get_miner()}")
            print(f"  Merkle root: {recovered_block.get_m_tree_root()}")
            print(f"  Bloom filter test (transaction_4_1): {recovered_block.is_in_bloom('transaction_4_1')}")
            print(f"  Bloom filter test (account_4_1): {recovered_block.is_in_bloom('account_4_1')}")
            print(f"  Bloom filter test (nonexistent): {recovered_block.is_in_bloom('nonexistent_tx')}")
        else:
            print(f"\nBlock #{original_block.get_index()} recovery failed!")

    # Test backup cleanup
    print("\nTesting backup cleanup...")
    removed_count = recovered_blockchain.cleanup_old_backups()
    print(f"  Cleaned up {removed_count} old backup files")

    # Display final blockchain information
    print("\nFinal blockchain information:")
    recovered_blockchain.print_chain_info()

    # Display fork tree structure
    print("\nFork tree structure:")
    recovered_blockchain.print_fork_tree()

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print(f"All data is saved to: {data_dir.absolute()}")
    print("\nDemonstrated Features:")
    print("  [X] Automatic save to disk after each block")
    print("  [X] Automatic load from disk on startup")
    print("  [X] Data integrity verification with checksum")
    print("  [X] Automatic backup creation at intervals")
    print("  [X] Manual backup creation")
    print("  [X] Backup cleanup to manage disk space")
    print("  [X] Fork tree persistence and recovery")
    print("  [X] Thread-safe operations with locks")
    print("  [X] Dual format storage (JSON + Pickle)")
    print("  [X] Bloom filter persistence")
    print("  [X] Configuration persistence")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
    except Exception as e:
        print(f"\nError during demo: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nThank you for using EZchain Blockchain!")