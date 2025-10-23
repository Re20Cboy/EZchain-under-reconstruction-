#!/usr/bin/env python3
"""
Demo script showcasing the Blockchain implementation features for real network deployment.
This demonstrates fork handling, consensus mechanisms, and blockchain validation.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import (
    Blockchain, ChainConfig, ConsensusStatus
)
from EZ_Main_Chain.Block import Block
from EZ_Units.MerkleTree import MerkleTree


def demo_basic_blockchain_functionality():
    """Demonstrate basic blockchain functionality."""
    print("=== Basic Blockchain Functionality Demo ===\n")

    # Create blockchain with default configuration
    config = ChainConfig(debug_mode=True)
    blockchain = Blockchain(config=config)

    print(f"Created blockchain: {blockchain}")
    print(f"Chain length: {len(blockchain)}")
    print(f"Latest block: #{blockchain.get_latest_block_index()}")
    print()

    # Add some blocks
    print("Adding blocks to the chain...")
    for i in range(1, 6):
        # Create test data for Merkle tree
        test_data = [f"transaction_{i}_{j}" for j in range(5)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        # Create block
        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # Add some data to Bloom filter
        block.add_item_to_bloom(f"account_{i}")
        block.add_item_to_bloom(f"payment_{i}")

        # Add block to blockchain
        main_chain_updated = blockchain.add_block(block)
        print(f"  Added Block #{i}: {block.get_miner()} (Hash: {block.get_hash()[:12]}...) "
              f"[Main chain updated: {main_chain_updated}]")

    print(f"\nChain length after adding blocks: {len(blockchain)}")
    print(f"Latest block: #{blockchain.get_latest_block_index()}")
    print(f"Chain validation: {blockchain.is_valid_chain()}")
    print()

    # Demonstrate block retrieval
    print("Block retrieval demonstration:")
    block_3 = blockchain.get_block_by_index(3)
    if block_3:
        print(f"  Block #3: {block_3.get_miner()}")
        print(f"  Contains 'account_3' in Bloom filter: {block_3.is_in_bloom('account_3')}")
        print(f"  Contains 'nonexistent' in Bloom filter: {block_3.is_in_bloom('nonexistent')}")

    print()


def demo_fork_handling():
    """Demonstrate blockchain fork handling."""
    print("=== Blockchain Fork Handling Demo ===\n")

    # Create blockchain with custom configuration
    config = ChainConfig(
        max_fork_height=4,
        confirmation_blocks=3,
        debug_mode=True
    )
    blockchain = Blockchain(config=config)

    print(f"Created blockchain: {blockchain}")
    print()

    # Build initial chain
    print("Building initial main chain...")
    main_chain_blocks = []
    for i in range(1, 4):
        test_data = [f"main_tx_{i}_{j}" for j in range(3)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"main_miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )
        block.add_item_to_bloom(f"main_account_{i}")

        blockchain.add_block(block)
        main_chain_blocks.append(block)
        print(f"  Added main chain Block #{i}: {block.get_miner()}")

    print(f"\nCurrent chain length: {len(blockchain)}")
    print(f"Latest block: #{blockchain.get_latest_block_index()} ({blockchain.get_latest_block().get_miner()})")
    print()

    # Create a fork
    print("Creating a fork at Block #2...")
    fork_blocks = []
    previous_hash = main_chain_blocks[0].get_hash()  # Fork from Block #1

    for i in range(2, 6):  # Fork blocks #2-5
        test_data = [f"fork_tx_{i}_{j}" for j in range(3)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        fork_block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"fork_miner_{i}",
            pre_hash=previous_hash
        )
        fork_block.add_item_to_bloom(f"fork_account_{i}")

        main_chain_updated = blockchain.add_block(fork_block)
        fork_blocks.append(fork_block)
        previous_hash = fork_block.get_hash()
        print(f"  Added fork Block #{i}: {fork_block.get_miner()} "
              f"[Main chain updated: {main_chain_updated}]")

    print()
    print("After adding fork:")
    print(f"  Chain length: {len(blockchain)}")
    print(f"  Latest block: #{blockchain.get_latest_block_index()} ({blockchain.get_latest_block().get_miner()})")

    # Show fork statistics
    stats = blockchain.get_fork_statistics()
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Main chain nodes: {stats['main_chain_nodes']}")
    print(f"  Fork nodes: {stats['fork_nodes']}")
    print(f"  Max forks at height: {stats['max_forks_at_height']}")
    print()

    # Show fork tree structure
    print("Fork tree structure:")
    blockchain.print_fork_tree()
    print()

    # Demonstrate fork retrieval
    print("Fork retrieval demonstration:")
    fork_block_2 = blockchain.get_fork_node_by_index(2)
    if fork_block_2:
        print(f"  Block #2 in main chain: {blockchain.get_block_by_index(2).get_miner()}")
        print(f"  Number of forks at height 2: {len(blockchain.get_all_forks_at_height(2))}")

    print()


def demo_consensus_and_validation():
    """Demonstrate consensus mechanisms and validation."""
    print("=== Consensus and Validation Demo ===\n")

    # Create blockchain with custom confirmation settings
    config = ChainConfig(
        confirmation_blocks=2,  # Shorter for demo
        debug_mode=True
    )
    blockchain = Blockchain(config=config)

    # Add blocks to reach confirmation threshold
    print("Adding blocks to demonstrate consensus...")
    for i in range(1, 8):
        test_data = [f"tx_{i}_{j}" for j in range(4)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )
        blockchain.add_block(block)

        confirmed_index = blockchain.get_latest_confirmed_block_index()
        print(f"  Block #{i} added, latest confirmed: #{confirmed_index or 'None'}")

    print()

    # Show confirmation status
    print("Block confirmation status:")
    for i in range(len(blockchain)):
        block = blockchain.get_block_by_index(i)
        is_confirmed = blockchain.is_block_confirmed(block.get_hash())
        status = "[+] CONFIRMED" if is_confirmed else "[o] PENDING"
        print(f"  Block #{i} ({block.get_miner()}): {status}")

    print()

    # Test chain validation
    print("Chain validation tests:")
    print(f"  Current chain valid: {blockchain.is_valid_chain()}")

    # Try to add invalid block
    try:
        invalid_block = Block(
            index=len(blockchain) + 2,  # Wrong index
            m_tree_root="invalid",
            miner="invalid_miner",
            pre_hash="invalid_hash"
        )
        blockchain.add_block(invalid_block)
        print("  Invalid block addition: UNEXPECTED SUCCESS")
    except ValueError:
        print("  Invalid block addition: CORRECTLY REJECTED")

    print()


def demo_performance_and_utilities():
    """Demonstrate performance features and utility methods."""
    print("=== Performance and Utilities Demo ===\n")

    blockchain = Blockchain(config=ChainConfig(debug_mode=True))

    # Create larger chain for performance testing
    print("Creating larger chain for performance testing...")
    for i in range(1, 51):  # 50 blocks
        test_data = [f"perf_tx_{i}_{j}" for j in range(10)]
        merkle_tree = MerkleTree(test_data)
        merkle_root = merkle_tree.get_root_hash()

        block = Block(
            index=i,
            m_tree_root=merkle_root,
            miner=f"perf_miner_{i % 10}",  # 10 different miners
            pre_hash=blockchain.get_latest_block_hash()
        )
        blockchain.add_block(block)

        if i % 10 == 0:
            print(f"  Added {i} blocks...")

    print(f"\nFinal chain length: {len(blockchain)}")
    print(f"Chain validation: {blockchain.is_valid_chain()}")
    print()

    # Demonstrate efficient lookups
    print("Demonstrating efficient block lookups:")
    import time

    # Test index-based lookup
    start_time = time.time()
    block_25 = blockchain.get_block_by_index(25)
    index_lookup_time = time.time() - start_time
    print(f"  Block #25 lookup by index: {index_lookup_time:.6f}s")

    # Test hash-based lookup
    if block_25:
        start_time = time.time()
        found_block = blockchain.get_block_by_hash(block_25.get_hash())
        hash_lookup_time = time.time() - start_time
        print(f"  Block lookup by hash: {hash_lookup_time:.6f}s")

    print()

    # Show blockchain information
    print("Blockchain information:")
    blockchain.print_chain_info(detailed=False)

    print()


def demo_integration_with_other_components():
    """Demonstrate integration with other EZchain components."""
    print("=== Integration with Other Components Demo ===\n")

    blockchain = Blockchain(config=ChainConfig(debug_mode=True))

    # Create blocks with realistic data
    print("Creating blocks with realistic transaction data...")

    # Block 1: User registrations
    user_registrations = ["alice_register", "bob_register", "charlie_register"]
    merkle_tree1 = MerkleTree(user_registrations)
    block1 = Block(
        index=1,
        m_tree_root=merkle_tree1.get_root_hash(),
        miner="registration_pool",
        pre_hash=blockchain.get_latest_block_hash()
    )
    for user in user_registrations:
        block1.add_item_to_bloom(user)
    blockchain.add_block(block1)

    # Block 2: Financial transactions
    transactions = ["alice_to_bob_10", "bob_to_charlie_5", "charlie_to_alice_3"]
    merkle_tree2 = MerkleTree(transactions)
    block2 = Block(
        index=2,
        m_tree_root=merkle_tree2.get_root_hash(),
        miner="transaction_pool",
        pre_hash=blockchain.get_latest_block_hash()
    )
    for tx in transactions:
        block2.add_item_to_bloom(tx)
        block2.add_item_to_bloom(f"account_{tx.split('_')[0]}")
    blockchain.add_block(block2)

    # Block 3: Smart contract deployments
    contracts = ["contract_deployment_1", "contract_deployment_2"]
    merkle_tree3 = MerkleTree(contracts)
    block3 = Block(
        index=3,
        m_tree_root=merkle_tree3.get_root_hash(),
        miner="contract_pool",
        pre_hash=blockchain.get_latest_block_hash()
    )
    for contract in contracts:
        block3.add_item_to_bloom(contract)
    blockchain.add_block(block3)

    print("Created 3 blocks with realistic data")
    print()

    # Demonstrate querying capabilities
    print("Demonstrating blockchain querying capabilities:")

    # Check if alice's registration is in the blockchain
    alice_reg_block = None
    for i in range(len(blockchain)):
        block = blockchain.get_block_by_index(i)
        if block.is_in_bloom("alice_register"):
            alice_reg_block = i
            break

    if alice_reg_block is not None:
        print(f"  Alice's registration found in Block #{alice_reg_block}")

    # Check for Bob's transactions
    bob_tx_blocks = []
    for i in range(len(blockchain)):
        block = blockchain.get_block_by_index(i)
        if block.is_in_bloom("account_bob"):
            bob_tx_blocks.append(i)

    print(f"  Blocks containing Bob's transactions: {bob_tx_blocks}")

    # Verify chain integrity
    print(f"  Chain integrity verified: {blockchain.is_valid_chain()}")
    print()

    # Show detailed blockchain information
    print("Detailed blockchain information:")
    blockchain.print_chain_info(detailed=True)


def demo_advanced_fork_scenarios():
    """Demonstrate advanced fork scenarios."""
    print("=== Advanced Fork Scenarios Demo ===\n")

    # Create blockchain with custom configuration
    config = ChainConfig(
        max_fork_height=6,
        confirmation_blocks=3,
        enable_fork_resolution=True,
        debug_mode=True
    )
    blockchain = Blockchain(config=config)

    # Build a complex fork scenario
    print("Building complex fork scenario...")

    # Main chain: Genesis -> A -> B -> C
    block_a = Block(
        index=1, m_tree_root="root_a", miner="miner_A",
        pre_hash=blockchain.get_latest_block_hash()
    )
    blockchain.add_block(block_a)

    block_b = Block(
        index=2, m_tree_root="root_b", miner="miner_B",
        pre_hash=blockchain.get_latest_block_hash()
    )
    blockchain.add_block(block_b)

    block_c = Block(
        index=3, m_tree_root="root_c", miner="miner_C",
        pre_hash=blockchain.get_latest_block_hash()
    )
    blockchain.add_block(block_c)

    print("  Created main chain: Genesis -> A -> B -> C")

    # Fork 1: Genesis -> A -> D -> E -> F (longer chain)
    block_d = Block(
        index=2, m_tree_root="root_d", miner="miner_D",
        pre_hash=block_a.get_hash()
    )
    blockchain.add_block(block_d)

    block_e = Block(
        index=3, m_tree_root="root_e", miner="miner_E",
        pre_hash=block_d.get_hash()
    )
    blockchain.add_block(block_e)

    block_f = Block(
        index=4, m_tree_root="root_f", miner="miner_F",
        pre_hash=block_e.get_hash()
    )
    blockchain.add_block(block_f)

    print("  Created longer fork: Genesis -> A -> D -> E -> F")

    # Fork 2: Another fork from block B
    block_g = Block(
        index=3, m_tree_root="root_g", miner="miner_G",
        pre_hash=block_b.get_hash()
    )
    blockchain.add_block(block_g)

    print("  Created additional fork: Genesis -> A -> B -> G")

    print(f"\nFinal main chain: length={len(blockchain)}, "
          f"latest=#{blockchain.get_latest_block_index()} "
          f"({blockchain.get_latest_block().get_miner()})")

    # Show fork statistics
    stats = blockchain.get_fork_statistics()
    print(f"Fork statistics: {stats['total_nodes']} total nodes, "
          f"{stats['fork_nodes']} fork nodes")

    print("\nFork tree structure:")
    blockchain.print_fork_tree()

    print()


if __name__ == "__main__":
    try:
        demo_basic_blockchain_functionality()
        demo_fork_handling()
        demo_consensus_and_validation()
        demo_performance_and_utilities()
        demo_integration_with_other_components()
        demo_advanced_fork_scenarios()

        print("=" * 70)
        print("All blockchain demos completed successfully!")
        print("The Blockchain implementation supports:")
        print("  [OK] Real network deployment with fork handling")
        print("  [OK] Efficient block validation and consensus")
        print("  [OK] Performance optimization with caching")
        print("  [OK] Integration with EZchain components")
        print("  [OK] Comprehensive error handling and logging")
        print("  [OK] Advanced fork scenarios and resolution")
        print("=" * 70)

    except Exception as e:
        print(f"\n[ERROR] Error running demos: {e}")
        import traceback
        traceback.print_exc()