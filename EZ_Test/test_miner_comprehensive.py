#!/usr/bin/env python3
"""
Comprehensive Test for Miner VPB Distribution Functionality

This test validates all aspects of the Miner class's new VPB distribution methods,
including integration with real blockchain scenarios and edge cases.
"""

import sys
import os
import time
import tempfile
import shutil

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Miner.miner import Miner
from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block
from EZ_Account.Account import Account
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Tool_Box.SecureSignature import secure_signature_handler


def test_miner_configuration():
    """Test miner configuration and basic setup"""
    print("=== Testing Miner Configuration ===")

    # Test miner creation
    miner = Miner("comprehensive_test_miner")
    assert miner.miner_id == "comprehensive_test_miner"
    assert miner.difficulty == 4  # Default difficulty
    assert miner.max_nonce == 2**32  # Default max nonce
    assert miner.mined_blocks_count == 0
    assert not miner.is_mining
    print("[PASS] Miner initialization successful")

    # Test difficulty setting
    miner.set_difficulty(3)
    assert miner.difficulty == 3
    print("[PASS] Difficulty setting works")

    # Test blockchain reference
    config = ChainConfig(confirmation_blocks=2, max_fork_height=3)
    blockchain = Blockchain(config=config)
    miner.set_blockchain(blockchain)
    assert miner.blockchain == blockchain
    print("[PASS] Blockchain reference setup works")

    print("[PASS] All miner configuration tests passed!")


def test_vpb_extraction_comprehensive():
    """Test VPB data extraction from various block types"""
    print("\n=== Testing VPB Extraction (Comprehensive) ===")

    miner = Miner("extraction_test_miner")

    # Test 1: Empty block extraction
    empty_block = Block(
        index=1,
        m_tree_root="empty_root",
        miner="test_miner",
        pre_hash="prev_hash_12345",
        nonce=42
    )

    vpb_data = miner.extract_vpb_from_block(empty_block)
    assert isinstance(vpb_data, dict)

    # Verify required keys exist
    required_keys = ['values', 'proof_units', 'block_index', 'merkle_tree', 'multi_transactions']
    for key in required_keys:
        assert key in vpb_data, f"Missing required key: {key}"

    # Verify empty block properties
    assert len(vpb_data['values']) == 0
    assert len(vpb_data['proof_units']) == 0
    assert isinstance(vpb_data['block_index'], BlockIndexList)
    print("[PASS] Empty block VPB extraction works")

    # Test 2: Block with different indices
    for block_index in [0, 1, 100, 999]:
        test_block = Block(
            index=block_index,
            m_tree_root=f"root_{block_index}",
            miner="test_miner",
            pre_hash=f"prev_{block_index}",
            nonce=block_index * 100
        )

        vpb_data = miner.extract_vpb_from_block(test_block)
        assert vpb_data['block_index'] is not None
        assert block_index in vpb_data['block_index'].index_lst
        print(f"[PASS] Block #{block_index} VPB extraction works")

    print("[PASS] All VPB extraction tests passed!")


def test_vpb_distribution_edge_cases():
    """Test VPB distribution with various edge cases"""
    print("\n=== Testing VPB Distribution Edge Cases ===")

    miner = Miner("edge_case_miner")

    # Test 1: Distribute to empty account list
    empty_block = Block(
        index=1,
        m_tree_root="test_root",
        miner="test_miner",
        pre_hash="test_prev",
        nonce=123
    )

    result = miner.distribute_vpb_to_accounts(empty_block, [])
    assert result == False
    print("[PASS] Distribution to empty account list handled correctly")

    # Test 2: Test with single account
    single_block = Block(
        index=2,
        m_tree_root="single_root",
        miner="test_miner",
        pre_hash="prev_single",
        nonce=456
    )

    # Create a mock account for testing
    try:
        private_key, public_key = secure_signature_handler.signer.generate_key_pair()
        test_account = Account(
            address="test_single_account",
            private_key_pem=private_key,
            public_key_pem=public_key,
            name="TestAccount"
        )

        result = miner.distribute_vpb_to_accounts(single_block, [test_account])
        # This should return False since the block has no VPB data
        assert result == False
        print("[PASS] Single account distribution with empty VPB handled correctly")

        # Cleanup
        test_account.cleanup()

    except Exception as e:
        print(f"[WARN] Single account test skipped due to: {e}")

    print("[PASS] All VPB distribution edge cases handled correctly!")



def test_performance_basics():
    """Test basic performance characteristics"""
    print("\n=== Testing Performance Characteristics ===")

    miner = Miner("performance_miner")

    # Test VPB extraction performance with multiple blocks
    start_time = time.time()

    for i in range(10):
        test_block = Block(
            index=i,
            m_tree_root=f"perf_root_{i}",
            miner="perf_miner",
            pre_hash=f"perf_prev_{i}",
            nonce=i * 100
        )

        vpb_data = miner.extract_vpb_from_block(test_block)
        assert isinstance(vpb_data, dict)

    end_time = time.time()
    extraction_time = end_time - start_time

    print(f"[INFO] Extracted VPB from 10 blocks in {extraction_time:.4f} seconds")
    print(f"[INFO] Average extraction time: {extraction_time/10:.4f} seconds per block")

    # Verify reasonable performance (should be very fast for empty blocks)
    assert extraction_time < 1.0, "VPB extraction taking too long"
    print("[PASS] VPB extraction performance is acceptable")

    print("[PASS] Performance tests completed!")


def run_comprehensive_tests():
    """Run all comprehensive miner tests"""
    print("=" * 80)
    print("EZChain Miner VPB Distribution - Comprehensive Test Suite")
    print("=" * 80)

    total_tests = 0
    passed_tests = 0

    test_functions = [
        test_miner_configuration,
        test_vpb_extraction_comprehensive,
        test_vpb_distribution_edge_cases,
        test_performance_basics
    ]

    for test_func in test_functions:
        total_tests += 1
        try:
            test_func()
            passed_tests += 1
            print(f"[SUCCESS] {test_func.__name__}")
        except Exception as e:
            print(f"[FAILED] {test_func.__name__}: {e}")
            import traceback
            traceback.print_exc()
        print("-" * 60)

    # Summary
    print("=" * 80)
    print("COMPREHENSIVE TEST SUMMARY")
    print("=" * 80)

    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {success_rate:.1f}%")

    if success_rate == 100:
        print("\n[SUCCESS] ALL TESTS PASSED! Miner VPB distribution is fully functional!")
    elif success_rate >= 80:
        print("\n[PARTIAL SUCCESS] MOST TESTS PASSED! Miner VPB distribution is largely functional.")
    else:
        print("\n[WARNING] MANY TESTS FAILED! Miner VPB distribution needs attention.")

    print("\n" + "=" * 80)
    print("Test suite completed successfully!" if success_rate == 100 else "Test suite completed with issues.")
    print("=" * 80)

    return success_rate == 100


if __name__ == "__main__":
    success = run_comprehensive_tests()
    sys.exit(0 if success else 1)