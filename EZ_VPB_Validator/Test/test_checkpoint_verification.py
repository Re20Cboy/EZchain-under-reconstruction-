#!/usr/bin/env python3
"""
简单测试checkpoint previous owner验证功能
"""

import logging
import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_VPB_Validator.steps.bloom_filter_validator_03 import BloomFilterValidator

# 模拟需要的类型
class MockBlockIndexSlice:
    def __init__(self, index_lst, owner):
        self.index_lst = index_lst
        self.owner = owner

class MockVPBSlice:
    def __init__(self, block_index_slice, previous_owner=None):
        self.block_index_slice = block_index_slice
        self.previous_owner = previous_owner

class MockBloomFilter:
    def __init__(self, addresses):
        self.addresses = set(addresses)

class MockMainChainInfo:
    def __init__(self):
        self.bloom_filters = {}

def test_checkpoint_previous_owner_verification():
    """测试checkpoint previous owner验证功能"""

    logger = logging.getLogger("test_checkpoint")
    validator = BloomFilterValidator(logger)

    # 测试场景1：正确的previous owner
    print("=" * 60)
    print("测试1: 正确的previous owner应该通过验证")
    print("=" * 60)

    main_chain = MockMainChainInfo()

    # 在区块15的布隆过滤器中添加alice
    main_chain.bloom_filters[15] = MockBloomFilter(["alice"])
    main_chain.bloom_filters[27] = MockBloomFilter([])  # 空的布隆过滤器

    vpb_slice = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner="alice"  # 正确的previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice, main_chain)
    print(f"结果: {result}, 错误: {error}")

    # 测试场景2：错误的previous owner
    print("\n" + "=" * 60)
    print("测试2: 错误的previous owner应该失败验证")
    print("=" * 60)

    vpb_slice_wrong = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner="wrong_owner"  # 错误的previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice_wrong, main_chain)
    print(f"结果: {result}, 错误: {error}")

    # 测试场景3：没有previous owner信息
    print("\n" + "=" * 60)
    print("测试3: 没有previous owner信息应该给出警告")
    print("=" * 60)

    vpb_slice_no_prev = MockVPBSlice(
        MockBlockIndexSlice([15, 27], [(15, "bob"), (27, "charlie")]),
        previous_owner=None  # 没有previous owner
    )

    result, error = validator.verify_bloom_filter_consistency(vpb_slice_no_prev, main_chain)
    print(f"结果: {result}, 错误: {error}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_checkpoint_previous_owner_verification()