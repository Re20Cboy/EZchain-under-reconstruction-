#!/usr/bin/env python3
"""
Core Test Suite for VPBSliceGenerator

This test focuses on the fundamental functionality of slice_generator.py,
testing the two expected behaviors:
1. Without checkpoint: return original v-p-b slice unchanged
2. With checkpoint: truncate p and b from checkpoint point onwards
"""

import sys
import os
import unittest
from unittest.mock import Mock, MagicMock
from typing import List, Tuple

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from EZ_VPB_Validator.steps.slice_generator import VPBSliceGenerator
from EZ_VPB_Validator.core.types import VPBSlice


class TestVPBSliceGeneratorCore(unittest.TestCase):
    """
    Core functionality tests for VPBSliceGenerator
    """

    def setUp(self):
        """Set up test environment"""
        self.mock_checkpoint = Mock()
        self.mock_logger = Mock()
        self.slice_generator = VPBSliceGenerator(self.mock_checkpoint, self.mock_logger)
        self.enable_visualization = False  # 可视化开关

    def print_separator(self, title: str = ""):
        """打印分隔线和标题"""
        print(f"\n{'='*60}")
        if title:
            print(f"  {title}")
        print(f"{'='*60}")

    def visualize_vpb_data(self, title: str, value, proofs, block_index_list, checkpoint_height: int = None):
        """可视化 VPB 数据结构"""
        if not self.enable_visualization:
            return

        self.print_separator(title)

        # 显示 Value 信息
        print(f"Value:")
        print(f"   └── begin_index: {value.begin_index}")
        print(f"   └── value_num: {value.value_num}")

        # 显示检查点信息
        if checkpoint_height is not None:
            print(f"Checkpoint: height {checkpoint_height}")
            print(f"   └── Start slice from: height {checkpoint_height + 1}")
        else:
            print(f"Checkpoint: None (start from genesis)")
            print(f"   └── Start slice from: height 0")

        # 显示 Proofs 信息
        print(f"Proofs ({len(proofs.proof_units)} units):")
        for i, proof in enumerate(proofs.proof_units):
            # 检查对应的区块高度是否大于检查点
            if i < len(block_index_list.index_lst):
                block_height = block_index_list.index_lst[i]
                status = "INCLUDE" if checkpoint_height is None or block_height > checkpoint_height else "EXCLUDE"
            else:
                status = "INCLUDE"  # 如果没有对应的区块，默认包含
            print(f"   └── Proof[{i}]: {status} proof_unit_{i}")

        # 显示 BlockIndexList 信息
        print(f"BlockIndexList ({len(block_index_list.index_lst)} indices):")
        for i, height in enumerate(block_index_list.index_lst):
            status = "INCLUDE" if checkpoint_height is None or height > checkpoint_height else "EXCLUDE"
            owner_name = f"owner{height}" if hasattr(block_index_list, 'owner') and block_index_list.owner else "unknown"
            print(f"   └── Block[{height}]: {status} {owner_name}")

        # 显示预期结果
        if checkpoint_height is not None:
            remaining_indices = [h for h in block_index_list.index_lst if h > checkpoint_height]
            remaining_proofs = len([p for i, p in enumerate(proofs.proof_units)
                                 if i < len(block_index_list.index_lst) and block_index_list.index_lst[i] > checkpoint_height])
            print(f"\nExpected Result:")
            print(f"   └── start_block_height: {checkpoint_height + 1}")
            print(f"   └── remaining proofs: {remaining_proofs}")
            print(f"   └── remaining indices: {remaining_indices}")
        else:
            print(f"\nExpected Result:")
            print(f"   └── start_block_height: 0")
            print(f"   └── remaining proofs: {len(proofs.proof_units)}")
            print(f"   └── remaining indices: {block_index_list.index_lst}")

    def visualize_result_slice(self, result_slice, used_checkpoint):
        """可视化生成的切片结果"""
        if not self.enable_visualization:
            return

        self.print_separator("SLICE GENERATION RESULT")

        print(f"VPBSlice Object:")
        print(f"   └── start_block_height: {result_slice.start_block_height}")
        print(f"   └── end_block_height: {result_slice.end_block_height}")

        print(f"Proofs Slice ({len(result_slice.proofs_slice)} units):")
        for i, proof in enumerate(result_slice.proofs_slice):
            print(f"   └── Proof[{i}]: {type(proof).__name__}")

        print(f"BlockIndex Slice ({len(result_slice.block_index_slice.index_lst)} indices):")
        if hasattr(result_slice.block_index_slice, 'index_lst'):
            for i, height in enumerate(result_slice.block_index_slice.index_lst):
                owner_info = ""
                if hasattr(result_slice.block_index_slice, 'owner') and result_slice.block_index_slice.owner:
                    # 查找对应的 owner
                    owner_match = [o for o in result_slice.block_index_slice.owner if o[0] == height]
                    if owner_match:
                        owner_info = f" ({owner_match[0][1]})"
                print(f"   └── Block[{height}]:{owner_info}")

        print(f"Used Checkpoint: {used_checkpoint.block_height if used_checkpoint else 'None'}")

    def print_test_result(self, test_name: str, success: bool, message: str = ""):
        """打印测试结果"""
        if not self.enable_visualization:
            return

        status = "PASS" if success else "FAIL"
        print(f"\n{status}: {test_name}")
        if message:
            print(f"   └── {message}")

    def create_mock_checkpoint_record(self, block_height=5):
        """Create a mock CheckPointRecord with proper arithmetic support"""
        mock_checkpoint_record = Mock()
        # 确保是整数类型，支持所有算术运算
        mock_checkpoint_record.block_height = int(block_height)
        return mock_checkpoint_record

    def test_without_checkpoint_returns_original_data(self):
        """Test: Without checkpoint, should return original v-p-b slice unchanged"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 10

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(5)]  # 5 proof units

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3, 4, 5]
        block_index_list.owner = [(1, "owner1"), (2, "owner2"), (3, "owner3"), (4, "owner4"), (5, "owner5")]
        block_index_list._owner_history = [(1, "owner1"), (2, "owner2"), (3, "owner3"), (4, "owner4"), (5, "owner5")]

        # 可视化输入数据
        self.visualize_vpb_data("TEST 1: No Checkpoint - Return Original Data",
                               value, proofs, block_index_list, None)

        # Mock checkpoint to return None (no checkpoint available)
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = None

        # Generate slice
        result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify behavior
        try:
            self.assertIsNone(used_checkpoint)
            self.assertEqual(result_slice.start_block_height, 0)  # Start from genesis
            self.assertEqual(result_slice.end_block_height, 5)   # End at last block
            self.assertEqual(len(result_slice.proofs_slice), 5)  # All proofs included
            self.assertEqual(result_slice.block_index_slice.index_lst, [1, 2, 3, 4, 5])  # All indices included
            self.assertEqual(result_slice.value, value)  # Value unchanged

            self.print_test_result("No Checkpoint Test", True, "All data preserved as expected")
        except AssertionError as e:
            self.print_test_result("No Checkpoint Test", False, str(e))
            raise

    def test_with_checkpoint_truncates_data_correctly(self):
        """Test: With checkpoint, should truncate p and b from checkpoint onwards"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 10

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(10)]  # 10 proof units

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        block_index_list.owner = [(i, f"owner{i}") for i in range(1, 11)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(1, 11)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 2: Checkpoint at Height 5 - Data Truncation",
                               value, proofs, block_index_list, 5)

        # Mock checkpoint at height 5
        mock_checkpoint_record = Mock()
        mock_checkpoint_record.block_height = 5
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = mock_checkpoint_record

        # Generate slice
        result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify truncation behavior
        try:
            self.assertIsNotNone(used_checkpoint)
            self.assertEqual(used_checkpoint.block_height, 5)
            self.assertEqual(result_slice.start_block_height, 6)  # Start from checkpoint + 1
            self.assertEqual(result_slice.end_block_height, 10)  # End at last block
            self.assertEqual(len(result_slice.proofs_slice), 5)  # Only 5 proofs remaining (indices 6-10)
            self.assertEqual(result_slice.block_index_slice.index_lst, [6, 7, 8, 9, 10])  # Truncated indices
            self.assertEqual(result_slice.value, value)  # Value unchanged

            self.print_test_result("Checkpoint Truncation Test", True, "Data correctly truncated from height 6")
        except AssertionError as e:
            self.print_test_result("Checkpoint Truncation Test", False, str(e))
            raise

    def test_invalid_checkpoint_at_last_block_should_raise_error(self):
        """Test: Checkpoint at last block height should raise ValueError (invalid VPB input)"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 5

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(5)]

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3, 4, 5]
        block_index_list.owner = [(i, f"owner{i}") for i in range(1, 6)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(1, 6)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 3: Invalid Checkpoint at Last Block - Should Raise Error",
                               value, proofs, block_index_list, 5)

        # Mock checkpoint at last block height (INVALID!)
        mock_checkpoint_record = Mock()
        mock_checkpoint_record.block_height = 5
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = mock_checkpoint_record

        # 生成预期结果展示（实际不会执行到这里）
        print(f"\nExpected Error:")
        print(f"   └── ValueError: Invalid checkpoint height (5) >= last block height (5)")
        print(f"   └── This indicates corrupted or invalid VPB data")

        # Generate slice - should raise ValueError
        try:
            self.slice_generator.generate_vpb_slice(
                value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
            )
            self.fail("Expected ValueError for checkpoint at last block height")
        except ValueError as e:
            print(f"\nActual Error:")
            print(f"   └── {type(e).__name__}: {str(e)}")
            self.assertIn("Invalid checkpoint", str(e))
            self.assertIn("must be less than last block height", str(e))
            self.print_test_result("Invalid Last Block Checkpoint Test", True, f"Correctly raised error")
        except Exception as e:
            print(f"\nUnexpected Error:")
            print(f"   └── {type(e).__name__}: {str(e)}")
            self.print_test_result("Invalid Last Block Checkpoint Test", False, f"Unexpected error type: {type(e).__name__}")
            raise

    def test_invalid_checkpoint_beyond_last_block_should_raise_error(self):
        """Test: Checkpoint beyond last block should raise ValueError (invalid VPB input)"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 3

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(3)]

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3]
        block_index_list.owner = [(i, f"owner{i}") for i in range(1, 4)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(1, 4)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 4: Invalid Checkpoint Beyond Last Block - Should Raise Error",
                               value, proofs, block_index_list, 10)

        # Mock checkpoint beyond last block (INVALID!)
        mock_checkpoint_record = Mock()
        mock_checkpoint_record.block_height = 10
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = mock_checkpoint_record

        # 生成预期结果展示（实际不会执行到这里）
        print(f"\nExpected Error:")
        print(f"   └── ValueError: Invalid checkpoint height (10) >= last block height (3)")
        print(f"   └── This indicates corrupted or invalid VPB data")

        # Generate slice - should raise ValueError
        try:
            self.slice_generator.generate_vpb_slice(
                value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
            )
            self.fail("Expected ValueError for checkpoint beyond last block height")
        except ValueError as e:
            print(f"\nActual Error:")
            print(f"   └── {type(e).__name__}: {str(e)}")
            self.assertIn("Invalid checkpoint", str(e))
            self.assertIn("must be less than last block height", str(e))
            self.print_test_result("Invalid Beyond Last Block Test", True, f"Correctly raised error")
        except Exception as e:
            print(f"\nUnexpected Error:")
            print(f"   └── {type(e).__name__}: {str(e)}")
            self.print_test_result("Invalid Beyond Last Block Test", False, f"Unexpected error type: {type(e).__name__}")
            raise

    def test_checkpoint_at_genesis_block(self):
        """Test: Checkpoint at genesis block (height 0)"""
        # Create test data with genesis block
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 5

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(5)]

        block_index_list = Mock()
        block_index_list.index_lst = [0, 1, 2, 3, 4]  # Includes genesis block (0)
        block_index_list.owner = [(i, f"owner{i}") for i in range(5)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(5)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 5: Checkpoint at Genesis Block - Special Handling",
                               value, proofs, block_index_list, 0)

        # Mock checkpoint at genesis block
        mock_checkpoint_record = Mock()
        mock_checkpoint_record.block_height = 0
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = mock_checkpoint_record

        # Generate slice
        result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify truncation from genesis
        try:
            self.assertIsNotNone(used_checkpoint)
            self.assertEqual(used_checkpoint.block_height, 0)
            self.assertEqual(result_slice.start_block_height, 1)  # Start from block 1
            self.assertEqual(len(result_slice.proofs_slice), 4)  # 4 proofs remaining (indices 1-4)
            self.assertEqual(result_slice.block_index_slice.index_lst, [1, 2, 3, 4])  # Exclude genesis

            self.print_test_result("Genesis Block Checkpoint Test", True, "Genesis block handled correctly")
        except AssertionError as e:
            self.print_test_result("Genesis Block Checkpoint Test", False, str(e))
            raise

    def test_no_checkpoint_available(self):
        """Test: When checkpoint is None, should start from height 0"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 3

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(3)]

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3]
        block_index_list.owner = [(i, f"owner{i}") for i in range(1, 4)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(1, 4)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST: No Available Checkpoint",
                               value, proofs, block_index_list, None)

        # Create generator with None checkpoint
        generator_no_checkpoint = VPBSliceGenerator(None, self.mock_logger)

        # Generate slice
        result_slice, used_checkpoint = generator_no_checkpoint.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify behavior
        try:
            self.assertIsNone(used_checkpoint)
            self.assertEqual(result_slice.start_block_height, 0)  # Start from genesis
            self.assertEqual(len(result_slice.proofs_slice), 3)  # All proofs included
            self.assertEqual(result_slice.block_index_slice.index_lst, [1, 2, 3])  # All indices included

            self.print_test_result("No Available Checkpoint Test", True, "Started from genesis as expected")
        except AssertionError as e:
            self.print_test_result("No Available Checkpoint Test", False, str(e))
            raise

    def test_empty_data_handling(self):
        """Test: Handling of empty proofs and block index list"""
        # Create empty test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 0

        proofs = Mock()
        proofs.proof_units = []  # Empty proofs

        block_index_list = Mock()
        block_index_list.index_lst = []  # Empty indices
        block_index_list.owner = []
        block_index_list._owner_history = []

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST: Empty Data Handling",
                               value, proofs, block_index_list, None)

        # Mock checkpoint returns None
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = None

        # Generate slice
        result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify empty slice handling
        try:
            self.assertIsNone(used_checkpoint)
            self.assertEqual(result_slice.start_block_height, 0)
            self.assertEqual(len(result_slice.proofs_slice), 0)
            self.assertEqual(len(result_slice.block_index_slice.index_lst), 0)

            self.print_test_result("Empty Data Handling Test", True, "Empty slice created correctly")
        except AssertionError as e:
            self.print_test_result("Empty Data Handling Test", False, str(e))
            raise

    def test_owner_slice_generation(self):
        """Test: Owner slice generation matches index slice"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 5

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(5)]

        block_index_list = Mock()
        block_index_list.index_lst = [10, 20, 30, 40, 50]  # 非连续的区块高度
        # Owner as list of tuples (height, owner) format that slice_generator expects
        block_index_list.owner = [(10, "owner10"), (20, "owner20"), (30, "owner30"), (40, "owner40"), (50, "owner50")]
        block_index_list._owner_history = [(10, "owner10"), (20, "owner20"), (30, "owner30"), (40, "owner40"), (50, "owner50")]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 6: Owner Slice Generation - Non-sequential Blocks",
                               value, proofs, block_index_list, 20)

        # Mock checkpoint at height 20
        mock_checkpoint_record = Mock()
        mock_checkpoint_record.block_height = 20
        self.mock_checkpoint.trigger_checkpoint_verification.return_value = mock_checkpoint_record

        # Generate slice
        result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify owner slice matches index slice
        try:
            self.assertEqual(result_slice.start_block_height, 21)  # Start from checkpoint + 1
            self.assertEqual(result_slice.block_index_slice.index_lst, [30, 40, 50])

            # Verify owner slice was generated correctly (should have owners for remaining indices)
            self.assertEqual(len(result_slice.block_index_slice.owner), 3)  # 3 owners for 3 indices

            self.print_test_result("Owner Slice Generation Test", True, "Owner information correctly preserved")
        except AssertionError as e:
            self.print_test_result("Owner Slice Generation Test", False, str(e))
            raise

    def test_none_checkpoint_generator(self):
        """Test: Generator with None checkpoint should not call checkpoint verification"""
        # Create test data
        value = Mock()
        value.begin_index = "0x100"
        value.value_num = 3

        proofs = Mock()
        proofs.proof_units = [Mock() for _ in range(3)]

        block_index_list = Mock()
        block_index_list.index_lst = [1, 2, 3]
        block_index_list.owner = [(i, f"owner{i}") for i in range(1, 4)]
        block_index_list._owner_history = [(i, f"owner{i}") for i in range(1, 4)]

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 7: Generator with None Checkpoint",
                               value, proofs, block_index_list, None)

        # Create generator with None checkpoint
        generator_no_checkpoint = VPBSliceGenerator(None, self.mock_logger)

        # Generate slice
        result_slice, used_checkpoint = generator_no_checkpoint.generate_vpb_slice(
            value, proofs, block_index_list, "0x1234567890123456789012345678901234567890"
        )

        # 可视化结果
        self.visualize_result_slice(result_slice, used_checkpoint)

        # Verify checkpoint was not called
        try:
            self.mock_checkpoint.trigger_checkpoint_verification.assert_not_called()

            # Verify behavior
            self.assertIsNone(used_checkpoint)
            self.assertEqual(result_slice.start_block_height, 0)
            self.assertEqual(len(result_slice.proofs_slice), 3)

            self.print_test_result("None Checkpoint Generator Test", True, "No checkpoint calls made")
        except AssertionError as e:
            self.print_test_result("None Checkpoint Generator Test", False, str(e))
            raise

    # ========== ADVANCED TEST CASES FROM HACKER SUITE ==========

    def create_mock_value(self, begin_index="0x100", value_num=10):
        """Create a mock Value object for advanced tests"""
        value = Mock()
        value.begin_index = begin_index
        value.value_num = value_num
        return value

    def create_mock_proofs(self, proof_count=5, start_height=1):
        """Create mock Proofs object with specified number of proof units"""
        mock_proofs = Mock()
        mock_proofs.proof_units = [Mock() for _ in range(proof_count)]
        return mock_proofs

    def create_mock_block_index_list(self, indices, owners=None):
        """Create mock BlockIndexList with specified indices and owners"""
        mock_block_list = Mock()
        mock_block_list.index_lst = indices
        mock_block_list.owner = owners if owners is not None else [(height, f"owner_{height}") for height in indices]
        mock_block_list._owner_history = owners if owners is not None else [(height, f"owner_{height}") for height in indices]
        return mock_block_list

    def test_checkpoint_boundary_conditions_comprehensive(self):
        """
        测试：边界高度检查点条件（来自hacker测试）
        输入：不同高度的检查点，包括边界值
        期望：有效高度正确处理，无效高度抛出ValueError
        """
        value = self.create_mock_value("0x100", 10)
        proofs = self.create_mock_proofs(5, 1)
        block_list = self.create_mock_block_index_list([1, 2, 3, 4, 5])

        # 可视化测试
        self.visualize_vpb_data("🔬 TEST 8: Comprehensive Checkpoint Boundary Conditions",
                               value, proofs, block_list, None)

        # Valid heights (should work correctly)
        valid_heights = [-1, 0, 1, 2, 3, 4]  # 4 is second to last block (valid)

        # Invalid heights (should raise ValueError)
        invalid_heights = [5, 6, 999]

        # Test valid heights
        for height in valid_heights:
            with self.subTest(height=height, expected="valid"):
                if height < 0:
                    # Negative height should return None (no checkpoint)
                    self.mock_checkpoint.trigger_checkpoint_verification.return_value = None
                else:
                    self.mock_checkpoint.trigger_checkpoint_verification.return_value = self.create_mock_checkpoint_record(height)

                try:
                    result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
                        value, proofs, block_list, "0x1234567890123456789012345678901234567890"
                    )

                    if height < 0:
                        # Negative height - no checkpoint
                        self.assertIsNone(used_checkpoint)
                        self.assertEqual(result_slice.start_block_height, 0)
                        self.assertEqual(len(result_slice.proofs_slice), 5)
                        self.assertEqual(len(result_slice.block_index_slice.index_lst), 5)
                    else:
                        # Valid height
                        expected_start_height = height + 1
                        expected_remaining = max(0, 5 - height)
                        self.assertEqual(result_slice.start_block_height, expected_start_height)
                        self.assertEqual(len(result_slice.proofs_slice), expected_remaining)
                        self.assertEqual(len(result_slice.block_index_slice.index_lst), expected_remaining)
                        self.assertEqual(used_checkpoint.block_height, height)

                except Exception as e:
                    self.fail(f"Unexpected exception for valid height {height}: {e}")

        # Test invalid heights (should raise ValueError)
        for height in invalid_heights:
            with self.subTest(height=height, expected="invalid"):
                self.mock_checkpoint.trigger_checkpoint_verification.return_value = self.create_mock_checkpoint_record(height)

                with self.assertRaises(ValueError) as cm:
                    result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
                        value, proofs, block_list, "0x1234567890123456789012345678901234567890"
                    )

                error_msg = str(cm.exception)
                self.assertIn("Invalid checkpoint", error_msg)
                self.assertIn("must be less than last block height", error_msg)

        self.print_test_result("Comprehensive Boundary Conditions Test", True, "All checkpoint scenarios handled correctly")

    def test_genesis_block_various_positions(self):
        """
        测试：创世区块各种位置处理（来自hacker测试）
        输入：创世区块在不同位置的合法数据
        期望：正确处理创世区块的切片生成逻辑
        """
        # 合法的创世区块情况
        genesis_cases = [
            # Genesis at start
            ([0, 1, 2, 3, 4], "genesis_at_start"),
            # Genesis in middle (仍然有效，索引顺序不影响VPB逻辑)
            ([1, 2, 0, 3, 4], "genesis_in_middle"),
            # Genesis at end
            ([1, 2, 3, 4, 0], "genesis_at_end"),
            # Only genesis with next block
            ([0, 1], "genesis_with_next_block"),
        ]

        for indices, case_name in genesis_cases:
            with self.subTest(case=case_name):
                value = self.create_mock_value("0x100", len(indices))
                proofs = self.create_mock_proofs(len(indices), 0)
                block_list = self.create_mock_block_index_list(indices)

                # 可视化输入数据
                self.visualize_vpb_data(f"🔬 TEST 9: Genesis Block - {case_name}",
                                       value, proofs, block_list, None)

                # Mock checkpoint to return None (no checkpoint available)
                self.mock_checkpoint.trigger_checkpoint_verification.return_value = None

                result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
                    value, proofs, block_list, "0x1234567890123456789012345678901234567890"
                )

                # 可视化结果
                self.visualize_result_slice(result_slice, used_checkpoint)

                # Should handle genesis appropriately
                self.assertIsInstance(result_slice, VPBSlice)
                self.assertEqual(len(result_slice.proofs_slice), len(indices))
                self.assertEqual(result_slice.block_index_slice.index_lst, indices)

        self.print_test_result("Genesis Block Positions Test", True, "All genesis positions handled correctly")

    def test_various_block_index_sequences(self):
        """
        测试：各种区块索引序列（来自hacker测试）
        输入：非连续、大间隔等合法区块索引序列
        期望：正确生成切片，保留所有有效索引
        """
        # 合法的区块索引序列
        valid_sequences = [
            # Non-sequential but increasing (合法)
            ([1, 5, 10, 15], "non_sequential_increasing"),
            # Large gaps (合法)
            ([1, 100, 1000], "large_gaps"),
            # Sequential indices
            ([1, 2, 3, 4, 5], "sequential"),
            # Single index
            ([42], "single_index"),
        ]

        for indices, case_name in valid_sequences:
            with self.subTest(case=case_name):
                # 创建对应数量的proofs，确保proof数量与indices数量一致
                value = self.create_mock_value("0x100", len(indices))
                proofs = self.create_mock_proofs(len(indices), 1)
                block_list = self.create_mock_block_index_list(indices)

                # 可视化输入数据
                self.visualize_vpb_data(f"🔬 TEST 10: Block Index Sequences - {case_name}",
                                       value, proofs, block_list, None)

                # Mock checkpoint to return None (no checkpoint available)
                self.mock_checkpoint.trigger_checkpoint_verification.return_value = None

                result_slice, used_checkpoint = self.slice_generator.generate_vpb_slice(
                    value, proofs, block_list, "0x1234567890123456789012345678901234567890"
                )

                # 可视化结果
                self.visualize_result_slice(result_slice, used_checkpoint)

                # Should handle valid sequences correctly
                self.assertIsInstance(result_slice, VPBSlice)
                self.assertEqual(result_slice.block_index_slice.index_lst, indices)
                self.assertEqual(len(result_slice.proofs_slice), len(indices))

        self.print_test_result("Various Block Index Sequences Test", True, "All index sequences handled correctly")

    def test_checkpoint_race_condition_simulation(self):
        """
        测试：检查点竞态条件模拟（来自hacker测试）
        输入：多次调用检查点，每次返回不同高度
        期望：系统应该正确处理每次调用
        """
        value = self.create_mock_value("0x100", 10)
        proofs = self.create_mock_proofs(5, 1)
        block_list = self.create_mock_block_index_list([1, 2, 3, 4, 5])

        # 可视化输入数据
        self.visualize_vpb_data("🔬 TEST 11: Checkpoint Race Condition Simulation",
                               value, proofs, block_list, None)

        # Mock checkpoint to return different heights on subsequent calls
        call_count = 0
        dynamic_checkpoint = Mock()
        def dynamic_trigger(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self.create_mock_checkpoint_record(2)
            else:
                return self.create_mock_checkpoint_record(4)

        dynamic_checkpoint.trigger_checkpoint_verification.side_effect = dynamic_trigger

        generator = VPBSliceGenerator(dynamic_checkpoint, self.mock_logger)

        # Make multiple calls rapidly
        results = []
        for i in range(3):
            result_slice, used_checkpoint = generator.generate_vpb_slice(
                value, proofs, block_list, "0x1234567890123456789012345678901234567890"
            )
            results.append((result_slice.start_block_height, used_checkpoint.block_height))

        # Should get different results due to different checkpoint heights
        self.assertEqual(results[0][0], 3)  # First call: height 2 + 1
        self.assertEqual(results[0][1], 2)  # Used checkpoint height 2
        self.assertEqual(results[1][0], 5)  # Second call: height 4 + 1
        self.assertEqual(results[1][1], 4)  # Used checkpoint height 4

        # 可视化最后一次结果
        self.visualize_result_slice(results[-1][0], results[-1][1])

        self.print_test_result("Checkpoint Race Condition Test", True, "Race conditions handled correctly")


if __name__ == '__main__':
    print("=" * 80)
    print("RUNNING CORE FUNCTIONALITY TESTS FOR VPBSliceGenerator")
    print("=" * 80)
    print("Testing the core VPB slice generation logic:")
    print("   1. Without checkpoint: return original v-p-b slice unchanged")
    print("   2. With checkpoint: truncate p and b from checkpoint onwards")
    print("   3. Invalid checkpoint: raise ValueError (BUG FIX!)")
    print("")
    print("Important Bug Fix:")
    print("   Checkpoint height >= last block height is INVALID VPB input")
    print("   Previously: Generated empty slices (incorrect)")
    print("   Now: Raises ValueError with clear error message")
    print("")
    print("Visualization Features:")
    print("   Green checkmarks: Data included in slice")
    print("   Red crosses: Data excluded by checkpoint")
    print("   Target: Checkpoint position")
    print("   Expected: Calculated results")
    print("   Result: Actual generated slice")
    print("   Error: Expected/Actual error messages")
    print("=" * 80)

    # 运行测试
    unittest.main(verbosity=2)