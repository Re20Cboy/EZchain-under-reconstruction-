#!/usr/bin/env python3
"""
Hacker's Perspective: Advanced Bloom Filter Validator Test Suite (Standalone Version)

作为高级黑客，我的目标是找出BloomFilterValidator的所有漏洞和安全薄弱点。
这个测试套件包含了各种攻击场景，试图绕过或破坏验证器的安全机制。

注意：这是独立版本，不依赖复杂的项目结构，可以直接运行。
"""

import pytest
import logging
from typing import Dict, List, Set, Tuple
from unittest.mock import Mock, MagicMock, patch
import sys
import os
from dataclasses import dataclass
from enum import Enum


# ============================================================================
# 独立数据类型定义（避免复杂导入）
# ============================================================================

@dataclass
class BlockIndexSlice:
    """简化的区块索引切片"""
    index_lst: List[int]
    owner: List[Tuple[int, str]]


class VPBSlice:
    """简化的VPB切片"""
    def __init__(self, block_index_slice=None):
        self.block_index_slice = block_index_slice or BlockIndexSlice([], [])


class MockBloomFilter:
    """模拟布隆过滤器，支持假阳性和假阴性攻击"""

    def __init__(self, fake_positive_addresses=None, fake_negative_addresses=None):
        self.fake_positive_addresses = fake_positive_addresses or set()
        self.fake_negative_addresses = fake_negative_addresses or set()
        self.addresses = set()

    def check_address(self, address):
        """模拟布隆过滤器的检查，支持攻击者控制"""
        # 假阳性：地址不在但返回True
        if address in self.fake_positive_addresses:
            return True
        # 假阴性：地址在但返回False
        if address in self.fake_negative_addresses:
            return False
        # 正常逻辑：地址包含在已知地址中
        return address in self.addresses


class MockMainChainInfo:
    """模拟真实的主链信息（共识信息，不可被攻击者操控）"""

    def __init__(self):
        self.merkle_roots = {}
        self.bloom_filters = {}

    def add_block_with_bloom_filter(self, block_height, bloom_filter, has_root=True):
        """添加真实的区块和布隆过滤器记录"""
        if has_root:
            self.merkle_roots[block_height] = f"root_{block_height}"
        self.bloom_filters[block_height] = bloom_filter

    def add_real_transaction_record(self, block_height, sender_addresses):
        """添加真实的交易记录到布隆过滤器（这些记录攻击者无法篡改）"""
        if block_height not in self.bloom_filters:
            bf = MockBloomFilter()
            self.add_block_with_bloom_filter(block_height, bf)

        bf = self.bloom_filters[block_height]
        bf.addresses.update(sender_addresses)
        return bf

    def simulate_real_history(self):
        """模拟真实的区块链历史记录（攻击者无法修改）"""
        # 模拟注释中场景1的真实历史：
        # alice是首位所有者，bob、charlie、dave等人的真实交易记录

        # 创世块：alice从GOD处获得value（不需要在布隆过滤器中记录）
        self.add_block_with_bloom_filter(0, MockBloomFilter())

        # alice作为sender的交易记录
        self.add_real_transaction_record(8, ["alice"])

        # bob从alice处接收value，然后作为sender的交易
        self.add_block_with_bloom_filter(15, MockBloomFilter())
        self.add_real_transaction_record(16, ["bob"])
        self.add_real_transaction_record(25, ["bob"])
        # bob在区块27作为sender给charlie转移value
        self.add_real_transaction_record(27, ["bob"])

        # charlie作为sender的交易
        self.add_block_with_bloom_filter(55, MockBloomFilter())
        # charlie在区块56作为sender给dave转移value
        self.add_real_transaction_record(56, ["charlie"])

        # dave没有作为sender的交易记录
        # dave在区块58作为sender给eve转移value
        self.add_real_transaction_record(58, ["dave"])

    def get_block_height_range(self):
        """获取已知的区块高度范围"""
        if not self.merkle_roots:
            return (0, 0)
        return (min(self.merkle_roots.keys()), max(self.merkle_roots.keys()))


# ============================================================================
# 简化的验证器实现（独立版本）
# ============================================================================

class MockValidatorBase:
    """模拟验证器基类"""
    def __init__(self, logger):
        self.logger = logger


class MockEpochExtractor(MockValidatorBase):
    """模拟Epoch提取器"""

    def extract_owner_epochs(self, block_index_slice) -> List[Tuple[int, str]]:
        """从BlockIndexSlice中提取epoch信息"""
        epochs = []

        if not block_index_slice.owner or not block_index_slice.index_lst:
            return epochs

        # 创建区块高度到owner的映射
        block_to_owner = {height: owner for height, owner in block_index_slice.owner}

        # 按区块高度排序构建epoch列表
        sorted_blocks = sorted(block_index_slice.index_lst)

        for block_height in sorted_blocks:
            if block_height in block_to_owner:
                owner = block_to_owner[block_height]
                epochs.append((block_height, owner))
            else:
                self.logger.warning(f"No owner found for block {block_height}")

        return epochs


class BloomFilterValidator(MockValidatorBase):
    """简化的布隆过滤器验证器（独立版本）"""

    def verify_bloom_filter_consistency(self, vpb_slice: VPBSlice, main_chain_info) -> Tuple[bool, str]:
        """
        第三步：布隆过滤器验证（简化版本）
        """
        if not vpb_slice.block_index_slice.index_lst:
            return False, "VPB slice has empty block index list"

        # 基本验证：确保提供的区块范围合理
        end_height = max(vpb_slice.block_index_slice.index_lst)

        # 提取owner的epochs信息
        extractor = MockEpochExtractor(self.logger)
        owner_epochs = extractor.extract_owner_epochs(vpb_slice.block_index_slice)

        if not owner_epochs:
            return False, "Failed to extract owner epochs from VPB slice"

        self.logger.debug(f"Extracted {len(owner_epochs)} owner epochs for bloom filter validation")

        # 验证第一个epoch之前的owner
        first_start_block, first_owner = owner_epochs[0]
        if first_start_block == 0:
            self.logger.debug(f"Genesis block detected: {first_owner} receives value from GOD at block {first_start_block}")
        else:
            # 非创世块：验证第一个epoch的前一个owner确实被记录在index_lst第一个块的布隆过滤器中
            self.logger.debug(f"First epoch starts at block {first_start_block}, owner: {first_owner}")

        # 核心验证逻辑：按照注释中的场景1要求进行验证
        for i, (start_block, owner_address) in enumerate(owner_epochs[:-1]):
            # 计算当前owner的epoch结束区块
            if i + 1 < len(owner_epochs):
                next_owner_start = owner_epochs[i + 1][0]
                epoch_end = next_owner_start - 1
            else:
                epoch_end = end_height

            epoch_range = (start_block, epoch_end)
            self.logger.debug(f"Validating owner {owner_address} epoch: {epoch_range}")

            # 验证1：检查epoch期间该owner作为sender的区块
            epoch_sender_blocks = []
            for block_height in range(start_block, epoch_end + 1):
                if block_height in main_chain_info.bloom_filters:
                    bloom_filter = main_chain_info.bloom_filters[block_height]
                    if self._check_bloom_filter(bloom_filter, owner_address):
                        epoch_sender_blocks.append(block_height)

            # 验证2：检查该owner在下一个区块作为sender发送目标value的交易
            next_block_for_value_transfer = epoch_end + 1
            value_transfer_recorded = False
            if next_block_for_value_transfer in main_chain_info.bloom_filters:
                next_bloom_filter = main_chain_info.bloom_filters[next_block_for_value_transfer]
                if self._check_bloom_filter(next_bloom_filter, owner_address):
                    value_transfer_recorded = True

            # 安全验证：如果epoch期间没有sender记录，且下一个区块也没有value transfer记录，可能存在问题
            if not epoch_sender_blocks and not value_transfer_recorded:
                self.logger.warning(
                    f"Owner {owner_address} has no transaction records in bloom filter "
                    f"during epoch {epoch_range} and no value transfer record in block {next_block_for_value_transfer}"
                )

            # 验证3：检查是否遗漏了任何应该包含的区块
            expected_blocks_in_vpb = set()

            # 添加epoch期间有sender记录的区块
            expected_blocks_in_vpb.update(epoch_sender_blocks)

            # 添加value transfer区块
            if value_transfer_recorded:
                expected_blocks_in_vpb.add(next_block_for_value_transfer)

            # 添加ownership change区块
            if start_block in vpb_slice.block_index_slice.index_lst:
                expected_blocks_in_vpb.add(start_block)

            # 检查VPB是否遗漏了这些重要区块
            provided_blocks = set(vpb_slice.block_index_slice.index_lst)
            missing_important_blocks = expected_blocks_in_vpb - provided_blocks

            if missing_important_blocks:
                self.logger.error(
                    f"SECURITY THREAT: VPB is missing important blocks that contain "
                    f"owner {owner_address} transactions: {sorted(missing_important_blocks)}"
                )
                return False, (
                    f"SECURITY THREAT DETECTED: VPB missing blocks {sorted(missing_important_blocks)} "
                    f"that contain transactions from owner {owner_address}. "
                    f"Attacker may be hiding malicious transactions."
                )

        self.logger.debug(f"Bloom filter consistency verification passed successfully")
        self.logger.debug(f"Validated epochs for {len(owner_epochs)-1} owners (excluding current owner)")

        return True, ""

    def _check_bloom_filter(self, bloom_filter, owner_address):
        """检查布隆过滤器是否包含指定地址"""
        if isinstance(bloom_filter, MockBloomFilter):
            return bloom_filter.check_address(owner_address)
        elif hasattr(bloom_filter, 'addresses'):
            return owner_address in bloom_filter.addresses
        else:
            # 其他类型，尝试直接检查
            try:
                return owner_address in bloom_filter
            except (TypeError, AttributeError):
                return False


# ============================================================================
# 黑客测试套件
# ============================================================================

class TestBloomFilterValidatorHacker:
    """黑客视角的布隆过滤器验证器测试"""

    @pytest.fixture
    def validator(self):
        """创建验证器实例"""
        logger = logging.getLogger("test_hacker")
        return BloomFilterValidator(logger)

    @pytest.fixture
    def mock_main_chain(self):
        """创建可被操控的主链模拟"""
        return MockMainChainInfo()

    def test_hacker_case_1_genesis_block_spoofing(self, validator, mock_main_chain):
        """
        黑客测试1：创世块伪造攻击

        攻击思路：攻击者在VPB中声称创世块是区块5，
        但主链信息显示真正的创世块是区块0，且alice在区块0就拥有了value。
        """
        print("\n[!] HACKER TEST 1: Genesis Block Spoofing Attack")

        # 设置真实的主链历史（不可操控）
        mock_main_chain.simulate_real_history()

        # 攻击者构造恶意VPB：声称创世块是区块5
        malicious_vpb = VPBSlice()
        malicious_vpb.block_index_slice = BlockIndexSlice(
            index_lst=[5, 15, 27, 56, 58],
            owner=[(5, "alice"), (15, "bob"), (27, "charlie"), (56, "dave"), (58, "eve")]
        )

        # 攻击者隐藏了真正的创世块0和区块8（alice的sender交易）
        result, error = validator.verify_bloom_filter_consistency(malicious_vpb, mock_main_chain)

        print(f"[!] Result: {result}, Error: {error}")

        if result:
            print("[SUCCESS] HACKER SUCCESS: Genesis block spoofing bypassed!")
        else:
            print("[FAILED] Hacker attack failed - validator detected missing blocks")

        return result, error

    def test_hacker_case_2_malicious_transaction_hiding(self, validator, mock_main_chain):
        """
        黑客测试2：恶意交易隐藏攻击

        攻击思路：攻击者在VPB中隐藏某些区块，这些区块包含攻击者的恶意交易（如双花）。
        验证器应该通过主链信息发现这些被隐藏的区块。
        """
        print("\n[!] HACKER TEST 2: Malicious Transaction Hiding Attack")

        # 设置真实的主链历史（包含攻击者的恶意交易）
        mock_main_chain.simulate_real_history()

        # 攻击者在区块20有恶意双花交易，被记录在主链中
        mock_main_chain.add_real_transaction_record(20, ["malicious_user"])

        # 攻击者构造VPB，故意隐藏包含恶意交易的区块20
        malicious_vpb = VPBSlice()
        malicious_vpb.block_index_slice = BlockIndexSlice(
            index_lst=[0, 15, 27, 56, 58],  # 故意遗漏区块20
            owner=[(0, "alice"), (15, "bob"), (27, "charlie"), (56, "dave"), (58, "eve")]
        )

        result, error = validator.verify_bloom_filter_consistency(malicious_vpb, mock_main_chain)

        print(f"[!] Result: {result}, Error: {error}")

        if not result and "SECURITY THREAT" in error:
            print("[VALIDATOR WINS] Malicious transaction hiding detected!")
        else:
            print("[HACKER SUCCESS] Successfully hid malicious transaction!")

        return result, error

    def test_hacker_case_3_epoch_manipulation(self, validator, mock_main_chain):
        """
        黑客测试3：Epoch边界操纵攻击

        攻击思路：攻击者故意提供错误的epoch边界，
        试图让验证器误判某个owner的epoch范围，从而隐藏恶意交易。
        """
        print("\n[!] HACKER TEST 3: Epoch Boundary Manipulation Attack")

        # 设置真实的主链历史
        mock_main_chain.simulate_real_history()

        # 攻击者在区块30有恶意交易
        mock_main_chain.add_real_transaction_record(30, ["bob"])

        # 攻击者构造VPB，声称bob的epoch在区块27就结束了
        malicious_vpb = VPBSlice()
        malicious_vpb.block_index_slice = BlockIndexSlice(
            index_lst=[0, 15, 27, 56, 58],
            owner=[(0, "alice"), (15, "bob"), (27, "charlie"), (56, "dave"), (58, "eve")]
        )

        result, error = validator.verify_bloom_filter_consistency(malicious_vpb, mock_main_chain)

        print(f"[!] Result: {result}, Error: {error}")

        if not result and "SECURITY THREAT" in error:
            print("[VALIDATOR WINS] Epoch manipulation detected - found hidden block 30!")
        else:
            print("[HACKER SUCCESS] Successfully manipulated epoch boundaries!")

        return result, error

    def test_hacker_case_4_double_spend_hiding(self, validator, mock_main_chain):
        """
        黑客测试4：双花交易隐藏攻击

        攻击思路：攻击者在某区块有双花交易，但在VPB中隐藏该区块。
        验证器应该通过检查主链的布隆过滤器发现被隐藏的恶意交易。
        """
        print("\n[!] HACKER TEST 4: Double-Spend Hiding Attack")

        # 设置真实的主链历史
        mock_main_chain.simulate_real_history()

        # 攻击者dave在区块57有双花交易（在主链中被记录）
        # 注意：dave原本没有sender交易，但现在有了恶意的双花交易
        malicious_block_57 = MockBloomFilter()
        malicious_block_57.addresses = {"dave"}  # dave的双花交易
        mock_main_chain.add_block_with_bloom_filter(57, malicious_block_57)

        # 攻击者构造VPB，隐藏包含双花交易的区块57
        malicious_vpb = VPBSlice()
        malicious_vpb.block_index_slice = BlockIndexSlice(
            index_lst=[0, 15, 27, 56, 58],  # 隐藏了区块57
            owner=[(0, "alice"), (15, "bob"), (27, "charlie"), (56, "dave"), (58, "eve")]
        )

        result, error = validator.verify_bloom_filter_consistency(malicious_vpb, mock_main_chain)

        print(f"[!] Result: {result}, Error: {error}")

        if not result and "SECURITY THREAT" in error:
            print("[VALIDATOR WINS] Double-spend transaction in hidden block 57 detected!")
        else:
            print("[HACKER SUCCESS] Successfully hid double-spend transaction!")

        return result, error

    def test_hacker_case_5_single_epoch_attack(self, validator, mock_main_chain):
        """
        黑客测试5：单Epoch攻击

        攻击思路：攻击者构造只有一个epoch的VPB，
        试图绕过验证器的核心循环逻辑。
        """
        print("\n[!] HACKER TEST 5: Single Epoch Attack")

        # 设置真实的主链历史（包括攻击者的恶意交易）
        mock_main_chain.simulate_real_history()

        # 攻击者只有一个区块，试图绕过验证逻辑
        malicious_vpb = VPBSlice()
        malicious_vpb.block_index_slice = BlockIndexSlice(
            index_lst=[42],
            owner=[(42, "malicious_user")]
        )

        # 攻击者在之前的一些区块有恶意交易，但在VPB中完全隐藏
        mock_main_chain.add_real_transaction_record(10, ["malicious_user"])
        mock_main_chain.add_real_transaction_record(20, ["malicious_user"])

        # 在区块42，攻击者声称获得value
        mock_main_chain.add_block_with_bloom_filter(42, MockBloomFilter())

        result, error = validator.verify_bloom_filter_consistency(malicious_vpb, mock_main_chain)

        print(f"[!] Result: {result}, Error: {error}")

        # 由于只有一个owner，验证器的核心循环被跳过
        if result:
            print("[HACKER SUCCESS] Single epoch bypass worked!")
        else:
            print("[VALIDATOR WINS] Single epoch attack detected!")

        return result, error


def run_hacker_test_suite():
    """运行完整的黑客测试套件"""
    print("=" * 80)
    print("BLOOM FILTER VALIDATOR - HACKER PERSPECTIVE TEST SUITE (Standalone)")
    print("=" * 80)

    logger = logging.getLogger("hacker_test")
    validator = BloomFilterValidator(logger)
    mock_main_chain = MockMainChainInfo()
    test_instance = TestBloomFilterValidatorHacker()

    test_results = []

    # 运行所有黑客测试
    hacker_tests = [
        ("Genesis Block Spoofing", test_instance.test_hacker_case_1_genesis_block_spoofing),
        ("Malicious Transaction Hiding", test_instance.test_hacker_case_2_malicious_transaction_hiding),
        ("Epoch Boundary Manipulation", test_instance.test_hacker_case_3_epoch_manipulation),
        ("Double-Spend Hiding", test_instance.test_hacker_case_4_double_spend_hiding),
        ("Single Epoch Attack", test_instance.test_hacker_case_5_single_epoch_attack),
    ]

    for test_name, test_func in hacker_tests:
        try:
            print(f"\n[!] Running: {test_name}")
            result, error = test_func(validator, mock_main_chain)

            if result:
                print(f"[SUCCESS] HACKER SUCCESS in {test_name}!")
                successful_attacks = 1
            else:
                print(f"[FAILED] Hacker failed in {test_name}")
                successful_attacks = 0

            test_results.append((test_name, successful_attacks))

        except Exception as e:
            print(f"[ERROR] Exception in {test_name}: {e}")
            test_results.append((test_name, "ERROR"))

    # 汇总结果
    print("\n" + "=" * 80)
    print("HACKER ATTACK SUMMARY")
    print("=" * 80)

    successful_attacks = 0
    failed_attacks = 0
    errors = 0

    for test_name, result in test_results:
        if result == "ERROR":
            print(f"[ERROR] {test_name}: ERROR (Exception)")
            errors += 1
        elif result == 1:
            print(f"[SUCCESS] {test_name}: HACKER SUCCESS")
            successful_attacks += 1
        else:
            print(f"[FAILED] {test_name}: Hacker Failed (Validator Won)")
            failed_attacks += 1

    print(f"\nSTATISTICS:")
    print(f"   Successful Attacks: {successful_attacks}")
    print(f"   Failed Attacks: {failed_attacks}")
    print(f"   Errors: {errors}")
    print(f"   Total Tests: {len(test_results)}")

    if successful_attacks > 0:
        print(f"\nCRITICAL: {successful_attacks} vulnerabilities found!")
        print("   The validator needs immediate security improvements.")
    else:
        print(f"\nGood: No successful attacks detected.")
        print("   The validator appears to be secure against these test cases.")

    return test_results


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.WARNING)

    # 运行黑客测试套件
    results = run_hacker_test_suite()

    # 根据结果设置退出代码
    successful_attacks = sum(1 for _, result in results if result == 1)
    exit_code = 1 if successful_attacks > 0 else 0
    exit(exit_code)