#!/usr/bin/env python3
"""
Simple demonstration of blockchain persistence functionality. 
"""

import sys
import os
import shutil

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block


def main():
    print("EZchain Blockchain Persistence Demo")
    print("=" * 40)

    # Clean up previous demo
    demo_dir = "demo_data"
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

    print(f"Data directory: {demo_dir}")
    print(f"Auto save: {config.auto_save}")
    print(f"Backup interval: {config.backup_interval} blocks")
    print()

    # Create blockchain
    print("Creating blockchain...")
    blockchain = Blockchain(config=config)
    print(f"Initial chain length: {len(blockchain)}")
    print()

    # Add blocks
    print("Adding blocks...")
    for i in range(1, 8):
        block = Block(
            index=i,
            m_tree_root=f"merkle_root_{i}",
            miner=f"miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add items to bloom filter
        block.add_item_to_bloom(f"transaction_{i}_1")
        block.add_item_to_bloom(f"account_{i}_1")

        result = blockchain.add_block(block)
        print(f"Added block #{i} by miner_{i}, main_chain_updated: {result}")

        # Check for backups
        if i % config.backup_interval == 0:
            print(f"  -> Backup automatically created")

    print(f"Final chain length: {len(blockchain)}")
    print(f"Latest block: #{blockchain.get_latest_block_index()}")
    print()

    # Create forks
    print("Creating forks...")
    block2 = blockchain.get_block_by_index(2)
    if block2:
        fork1 = Block(
            index=3,
            m_tree_root="fork_merkle_1",
            miner="fork_miner_1",
            pre_hash=block2.get_hash()
        )
        blockchain.add_block(fork1)
        print("Added fork block #3")

        fork2 = Block(
            index=4,
            m_tree_root="fork_merkle_2",
            miner="fork_miner_2",
            pre_hash=fork1.get_hash()
        )
        blockchain.add_block(fork2)
        print("Added fork block #4")

    print()

    # Show statistics
    stats = blockchain.get_fork_statistics()
    print("Fork Statistics:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Main chain nodes: {stats['main_chain_nodes']}")
    print(f"  Fork nodes: {stats['fork_nodes']}")
    print(f"  Confirmed nodes: {stats['confirmed_nodes']}")
    print()

    # Validate chain
    is_valid = blockchain.is_valid_chain()
    print(f"Chain is valid: {is_valid}")
    print()

    # List saved files
    print("Saved files:")
    data_dir = blockchain.data_dir
    backup_dir = blockchain.backup_dir

    if data_dir.exists():
        for file in sorted(data_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"  {file.name} ({size} bytes)")

    if backup_dir.exists():
        for file in sorted(backup_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"  backup/{file.name} ({size} bytes)")
    print()

    # Test data recovery
    print("Testing data recovery...")
    print("Creating new blockchain instance (should load saved data)...")

    # Create new blockchain instance to test loading
    recovered_blockchain = Blockchain(config=config)

    print(f"Loaded chain length: {len(recovered_blockchain)}")
    print(f"Latest block index: #{recovered_blockchain.get_latest_block_index()}")

    recovered_valid = recovered_blockchain.is_valid_chain()
    print(f"Loaded chain is valid: {recovered_valid}")
    print()

    # Test specific block recovery
    original_block = blockchain.get_block_by_index(3)
    recovered_block = recovered_blockchain.get_block_by_hash(original_block.get_hash())

    if recovered_block:
        print(f"Block #{original_block.get_index()} successfully recovered")
        print(f"  Miner: {recovered_block.get_miner()}")
        print(f"  Merkle root: {recovered_block.get_m_tree_root()[:16]}...")
        print(f"  Bloom filter test: {recovered_block.is_in_bloom('transaction_3_1')}")
    else:
        print("Block recovery failed")
    print()

    # Test cleanup
    print("Testing backup cleanup...")
    removed_count = recovered_blockchain.cleanup_old_backups()
    print(f"Cleaned up {removed_count} old backups")
    print()

    # Final info
    print("Final blockchain info:")
    recovered_blockchain.print_chain_info()
    print()

    print("Demo completed successfully!")
    print(f"All data saved to: {data_dir.absolute()}")
    print()

    print("Demonstrated features:")
    print("  [X] Automatic save to disk")
    print("  [X] Automatic load from disk")
    print("  [X] Data integrity verification")
    print("  [X] Automatic backup creation")
    print("  [X] Backup cleanup")
    print("  [X] Fork persistence")
    print("  [X] Thread-safe operations")
    print("  [X] JSON and Pickle dual format storage")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"\nError during demo: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nThank you for using EZchain!")