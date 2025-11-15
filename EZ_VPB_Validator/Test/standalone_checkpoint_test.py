#!/usr/bin/env python3
"""
独立测试checkpoint previous owner验证功能
"""

import logging
from typing import Tuple, List
from dataclasses import dataclass
from typing import Optional

# 模拟数据结构
@dataclass
class MockBlockIndexSlice:
    index_lst: List[int]
    owner: List[Tuple[int, str]]

@dataclass
class MockVPBSlice:
    block_index_slice: MockBlockIndexSlice
    previous_owner: Optional[str] = None

class MockBloomFilter:
    def __init__(self, addresses):
        self.addresses = set(addresses)

class MockMainChainInfo:
    def __init__(self):
        self.bloom_filters = {}

class MockValidatorBase:
    def __init__(self, logger):
        self.logger = logger

class MockEpochExtractor(MockValidatorBase):
    def extract_owner_epochs(self, block_index_slice) -> List[Tuple[int, str]]:
        epochs = []
        if not block_index_slice.owner or not block_index_slice.index_lst:
            return epochs

        block_to_owner = {height: owner for height, owner in block_index_slice.owner}
        sorted_blocks = sorted(block_index_slice.index_lst)

        for block_height in sorted_blocks:
            if block_height in block_to_owner:
                owner = block_to_owner[block_height]
                epochs.append((block_height, owner))
            else:
                self.logger.warning(f"No owner found for block {block_height}")

        return epochs

class TestBloomFilterValidator(MockValidatorBase):
    """简化的布隆过滤器验证器"""

    def verify_bloom_filter_consistency(self, vpb_slice: MockVPBSlice, main_chain_info) -> Tuple[bool, str]:
        """验证布隆过滤器一致性"""
        if not vpb_slice.block_index_slice.index_lst:
            return False, "VPB slice has empty block index list"

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
            previous_owner = getattr(vpb_slice, 'previous_owner', None)

            if previous_owner:
                self.logger.debug(f"Non-genesis block detected: previous_owner={previous_owner}, first_owner={first_owner}")

                if first_start_block in main_chain_info.bloom_filters:
                    first_block_bloom_filter = main_chain_info.bloom_filters[first_start_block]
                    previous_owner_recorded = self._check_bloom_filter(first_block_bloom_filter, previous_owner)

                    if previous_owner_recorded:
                        self.logger.debug(f"Previous owner {previous_owner} correctly recorded in bloom filter at block {first_start_block}")
                    else:
                        error_msg = (
                            f"SECURITY THREAT DETECTED: Checkpoint previous owner {previous_owner} "
                            f"not recorded in bloom filter at block {first_start_block}. "
                            f"Potential checkpoint tampering detected."
                        )
                        self.logger.error(error_msg)
                        return False, error_msg
                else:
                    self.logger.warning(f"No bloom filter available for block {first_start_block}, cannot verify previous owner")
            else:
                self.logger.warning(
                    f"Non-genesis block detected but no previous owner information available. "
                    f"First epoch starts at block {first_start_block}, owner: {first_owner}"
                )

        # 核心验证逻辑
        for i, (start_block, owner_address) in enumerate(owner_epochs[:-1]):
            # 简化验证逻辑
            epoch_end = owner_epochs[i + 1][0] - 1 if i + 1 < len(owner_epochs) else end_height
            self.logger.debug(f"Validating owner {owner_address} epoch: ({start_block}, {epoch_end})")

            # 检查epoch期间该owner作为sender的区块
            epoch_sender_blocks = []
            for block_height in range(start_block, epoch_end + 1):
                if block_height in main_chain_info.bloom_filters:
                    bloom_filter = main_chain_info.bloom_filters[block_height]
                    if self._check_bloom_filter(bloom_filter, owner_address):
                        epoch_sender_blocks.append(block_height)

            # 检查是否遗漏了重要区块
            expected_blocks_in_vpb = set(epoch_sender_blocks)
            expected_blocks_in_vpb.add(start_block)

            provided_blocks = set(vpb_slice.block_index_slice.index_lst)
            missing_important_blocks = expected_blocks_in_vpb - provided_blocks

            if missing_important_blocks:
                error_msg = (
                    f"SECURITY THREAT DETECTED: VPB missing blocks {sorted(missing_important_blocks)} "
                    f"that contain transactions from owner {owner_address}. "
                    f"Attacker may be hiding malicious transactions."
                )
                self.logger.error(error_msg)
                return False, error_msg

        return True, ""

    def _check_bloom_filter(self, bloom_filter, owner_address):
        """检查布隆过滤器是否包含指定地址"""
        if isinstance(bloom_filter, MockBloomFilter):
            return owner_address in bloom_filter.addresses
        elif hasattr(bloom_filter, 'addresses'):
            return owner_address in bloom_filter.addresses
        else:
            try:
                return owner_address in bloom_filter
            except (TypeError, AttributeError):
                return False

def test_checkpoint_previous_owner_verification():
    """测试checkpoint previous owner验证功能"""

    logger = logging.getLogger("test_checkpoint")
    validator = TestBloomFilterValidator(logger)

    # 测试场景1：正确的previous owner
    print("=" * 60)
    print("测试1: 正确的previous owner应该通过验证")
    print("=" * 60)

    main_chain = MockMainChainInfo()
    main_chain.bloom_filters[15] = MockBloomFilter(["alice"])
    main_chain.bloom_filters[27] = MockBloomFilter(["bob"])  # bob在区块27作为sender

    vpb_slice = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner="alice"  # 正确的previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice, main_chain)
    print(f"结果: {result}")
    print(f"错误: {error}")
    print(f"预期: True (验证通过)")

    # 测试场景2：错误的previous owner
    print("\n" + "=" * 60)
    print("测试2: 错误的previous owner应该失败验证")
    print("=" * 60)

    vpb_slice_wrong = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner="wrong_owner"  # 错误的previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice_wrong, main_chain)
    print(f"结果: {result}")
    print(f"错误: {error}")
    print(f"预期: False (验证失败)")

    # 测试场景3：没有previous owner信息
    print("\n" + "=" * 60)
    print("测试3: 没有previous owner信息应该给出警告")
    print("=" * 60)

    vpb_slice_no_prev = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner=None  # 没有previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice_no_prev, main_chain)
    print(f"结果: {result}")
    print(f"错误: {error}")
    print(f"预期: True (有警告但验证通过)")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_checkpoint_previous_owner_verification()