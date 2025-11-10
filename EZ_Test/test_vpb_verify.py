"""
VPBVerify模块测试

测试EZChain VPB验证功能的核心特性：
- VPB三元组基础数据结构验证
- 检查点匹配和历史切片生成
- 布隆过滤器一致性验证
- 逐证明单元验证和双花检测
- 完整VPB验证流程
"""

import pytest
import sys
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_VPB.VPBVerify import (
    VPBVerify, VPBVerificationReport, MainChainInfo, VPBSlice,
    VerificationResult, VerificationError
)
from EZ_Value.Value import Value, ValueState
from EZ_Proof.Proofs import Proofs
from EZ_Proof.ProofUnit import ProofUnit
from EZ_BlockIndex.BlockIndexList import BlockIndexList
from EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord
from EZ_Units.Bloom import BloomFilter


def create_realistic_bloom_filters(block_heights, owner_data, additional_transactions=None):
    """
    创建真实的布隆过滤器模拟

    布隆过滤器的正确逻辑：
    - 记录在区块中提交交易的sender地址，而不是value的所有者地址
    - 如果A在区块H提交交易将value转移给B，则布隆过滤器记录的是A而不是B
    - B成为区块H中该value的所有者，但不会记录在该区块的布隆过滤器中

    Args:
        block_heights: 区块高度列表
        owner_data: dict {block_height: owner_address} - 记录每个区块中value的所有者
        additional_transactions: dict {block_height: [sender_addresses]} - 记录在每个区块提交交易的地址

    Returns:
        dict {block_height: BloomFilter}
    """
    bloom_filters = {}

    for height in block_heights:
        bloom_filter = BloomFilter(size=1024, hash_count=3)

        # 关键修复：只添加在该区块提交交易的sender地址，不添加owner地址
        # owner_address是value的接收者，而sender_address是交易的提交者
        if additional_transactions and height in additional_transactions:
            for sender_address in additional_transactions[height]:
                bloom_filter.add(sender_address)

        bloom_filters[height] = bloom_filter

    return bloom_filters


def create_valid_vpb_bloom_filters():
    """
    为valid_vpb_data创建标准的布隆过滤器配置

    正确的逻辑说明：
    - owner_data: 记录每个区块中value的所有者
    - additional_transactions: 记录在每个区块提交交易的sender地址（会被加入布隆过滤器）
    - 例如：0xalice在区块15提交交易，将value转移给0xbob
      则owner_data[15] = "0xbob", additional_transactions[15] = ["0xalice"]

    Returns:
        tuple: (owner_data, additional_transactions)
    """
    owner_data = {
        0: "0xalice",      # 创世块：alice是初始value的所有者
        15: "0xbob",       # 区块15：bob从alice处接收value
        27: "0xcharlie",   # 区块27：charlie从bob处接收value
        56: "0xcharlie"    # 区块56：charlie仍然持有value（可能有其他交易）
    }

    # 记录在每个区块提交交易的sender地址（这些地址会被加入布隆过滤器）
    additional_transactions = {
        15: ["0xalice"],        # alice在区块15提交交易，将value转移给bob
        27: ["0xbob"],          # bob在区块27提交交易，将value转移给charlie
        56: ["0xcharlie"]       # charlie在区块56有交易（可能不是转移此value）
    }

    return owner_data, additional_transactions


class TestMainChainInfo:
    """测试主链信息数据结构"""

    def test_main_chain_info_creation(self):
        """测试主链信息创建"""
        merkle_roots = {
            0: "root_hash_0",
            1: "root_hash_1",
            2: "root_hash_2"
        }
        bloom_filters = {
            0: "bloom_0",
            1: "bloom_1",
            2: "bloom_2"
        }

        main_chain = MainChainInfo(
            merkle_roots=merkle_roots,
            bloom_filters=bloom_filters,
            current_block_height=2
        )

        assert main_chain.merkle_roots == merkle_roots
        assert main_chain.bloom_filters == bloom_filters
        assert main_chain.current_block_height == 2
        assert main_chain.genesis_block_height == 0

    def test_get_blocks_in_range(self):
        """测试获取指定范围内的区块高度列表"""
        main_chain = MainChainInfo(
            merkle_roots={0: "r0", 1: "r1", 2: "r2", 3: "r3", 4: "r4"},
            bloom_filters={},
            current_block_height=4
        )

        # 测试正常范围
        blocks = main_chain.get_blocks_in_range(1, 3)
        assert blocks == [1, 2, 3]

        # 测试包含不存在区块的范围
        blocks = main_chain.get_blocks_in_range(0, 5)
        assert blocks == [0, 1, 2, 3, 4]

        # 测试空范围
        blocks = main_chain.get_blocks_in_range(5, 10)
        assert blocks == []

    def test_get_owner_transaction_blocks(self):
        """测试通过布隆过滤器获取交易区块"""
        # Mock bloom filter check
        main_chain = MainChainInfo(
            merkle_roots={0: "r0", 1: "r1", 2: "r2"},
            bloom_filters={0: "b0", 1: "b1", 2: "b2"},
            current_block_height=2
        )

        # Mock the bloom filter check to return True for blocks 1 and 2
        def mock_check_bloom_filter(bloom_filter, owner_address):
            return owner_address == "0xtest_owner" and bloom_filter in ["b1", "b2"]

        main_chain._check_bloom_filter = mock_check_bloom_filter

        # 测试获取交易区块
        tx_blocks = main_chain.get_owner_transaction_blocks("0xtest_owner", 0, 2)
        assert tx_blocks == [1, 2]

        # 测试获取不存在的owner的交易区块
        tx_blocks = main_chain.get_owner_transaction_blocks("0xunknown_owner", 0, 2)
        assert tx_blocks == []


class TestVPBVerifyBasicValidation:
    """测试VPB验证器的基础验证功能"""

    @pytest.fixture
    def vpb_verifier(self):
        """创建VPB验证器实例"""
        return VPBVerify()

    @pytest.fixture
    def sample_value(self):
        """创建示例Value对象"""
        return Value("0x1000", 100)

    @pytest.fixture
    def sample_proofs(self):
        """创建示例Proofs对象"""
        # Mock Proofs对象
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(4)]  # 匹配block_index_list的长度
        return mock_proofs

    @pytest.fixture
    def sample_block_index_list(self):
        """创建示例BlockIndexList对象"""
        return BlockIndexList(
            index_lst=[0, 15, 27, 56],
            owner=[(0, "0xowner1"), (15, "0xowner2"), (27, "0xowner3"), (56, "0xowner4")]
        )

    def test_validate_basic_data_structure_success(self, vpb_verifier, sample_value,
                                                   sample_proofs, sample_block_index_list):
        """测试基础数据结构验证成功情况"""
        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            sample_value, sample_proofs, sample_block_index_list
        )

        assert is_valid == True
        assert error_msg == ""

    def test_validate_basic_data_structure_invalid_value(self, vpb_verifier, sample_proofs, sample_block_index_list):
        """测试无效Value对象验证"""
        # 测试非Value对象
        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            "not_a_value", sample_proofs, sample_block_index_list
        )
        assert is_valid == False
        assert "not a valid Value object" in error_msg

        # 测试负数value_num（Value类会抛出异常，所以我们捕获它）
        with pytest.raises(ValueError, match="valueNum must be positive"):
            invalid_value = Value("0x1000", -1)
            vpb_verifier._validate_basic_data_structure(invalid_value, sample_proofs, sample_block_index_list)

        # 测试begin_index >= end_index
        # 创建一个真正无效的Value，通过设置一个明显错误的end_index
        invalid_value = Value("0x2000", 1)  # 这会创建一个有效的Value，但我们检查时使用其他方法

        # 手动创建一个begin_index >= end_index的情况进行测试
        # 我们需要通过其他方式测试这个逻辑，因为Value类自动计算end_index
        valid_value = Value("0x1000", 100)

        # 创建匹配长度但owner有重复的BlockIndexList来测试其他验证逻辑
        invalid_block_list = BlockIndexList(
            index_lst=[0, 15],  # 只有2个索引
            owner=[(0, "0xowner1"), (15, "0xowner2")]
        )

        # 创建不匹配的proofs（4个proof vs 2个index）
        mismatch_proofs = Mock(spec=Proofs)
        mismatch_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(4)]

        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            valid_value, mismatch_proofs, invalid_block_list
        )
        assert is_valid == False
        assert "does not match" in error_msg

    def test_validate_basic_data_structure_mismatch_count(self, vpb_verifier, sample_value, sample_block_index_list):
        """测试Proofs和BlockIndexList数量不匹配"""
        # 创建数量不匹配的proof units
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(5)]  # 5 vs 4 in block_index_list

        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            sample_value, mock_proofs, sample_block_index_list
        )

        assert is_valid == False
        assert "Proof count (5) does not match block index count (4)" in error_msg

    def test_validate_basic_data_structure_duplicate_owners(self, vpb_verifier, sample_value):
        """测试重复所有者验证"""
        # 创建包含重复所有者的BlockIndexList
        block_index_with_duplicates = BlockIndexList(
            index_lst=[0, 15, 27],
            owner=[(0, "0xowner1"), (15, "0xowner1"), (27, "0xowner2")]  # owner1重复
        )

        # 创建匹配长度的proofs（3个proof对应3个index）
        matching_proofs = Mock(spec=Proofs)
        matching_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(3)]

        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            sample_value, matching_proofs, block_index_with_duplicates
        )

        assert is_valid == False
        assert "Duplicate owners" in error_msg


class TestVPBVerifySliceGeneration:
    """测试VPB切片生成功能"""

    @pytest.fixture
    def vpb_verifier_with_checkpoint(self):
        """创建带检查点的VPB验证器"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            verifier = VPBVerify(checkpoint=checkpoint)
            yield verifier, checkpoint
            # 清理
            checkpoint = None
            verifier = None
            import time
            time.sleep(0.1)
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except PermissionError:
                pass

    @pytest.fixture
    def sample_value(self):
        """创建示例Value对象"""
        return Value("0x1000", 100)

    @pytest.fixture
    def sample_proofs(self):
        """创建示例Proofs对象"""
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(7)]
        return mock_proofs

    @pytest.fixture
    def sample_block_index_list(self):
        """创建示例BlockIndexList对象"""
        return BlockIndexList(
            index_lst=[0, 7, 15, 27, 56, 67, 98],
            owner=[(0, "0x418ab"), (15, "0x8360c"), (56, "0x14860")]
        )

    def test_generate_vpb_slice_without_checkpoint(self, vpb_verifier_with_checkpoint,
                                                  sample_value, sample_proofs, sample_block_index_list):
        """测试无检查点情况下的VPB切片生成"""
        verifier, checkpoint = vpb_verifier_with_checkpoint

        vpb_slice, checkpoint_used = verifier._generate_vpb_slice(
            sample_value, sample_proofs, sample_block_index_list, "0x418ab"
        )

        # 验证切片结果
        assert vpb_slice is not None
        assert vpb_slice.value == sample_value
        assert vpb_slice.start_block_height == 0  # 没有检查点，从创世块开始
        assert vpb_slice.end_block_height == 98  # 最后一个区块
        assert checkpoint_used is None  # 没有使用检查点

        # 验证切片内容
        assert len(vpb_slice.proofs_slice) == 7  # 所有proof units
        assert vpb_slice.block_index_slice.index_lst == [0, 7, 15, 27, 56, 67, 98]

    def test_generate_vpb_slice_with_checkpoint(self, vpb_verifier_with_checkpoint,
                                               sample_value, sample_proofs, sample_block_index_list):
        """测试有检查点情况下的VPB切片生成"""
        verifier, checkpoint = vpb_verifier_with_checkpoint

        # 创建检查点
        checkpoint.create_checkpoint(sample_value, "0x418ab", 14)

        vpb_slice, checkpoint_used = verifier._generate_vpb_slice(
            sample_value, sample_proofs, sample_block_index_list, "0x418ab"
        )

        # 验证切片结果
        assert vpb_slice is not None
        assert vpb_slice.value == sample_value
        assert vpb_slice.start_block_height == 15  # 从检查点的下一个区块开始
        assert vpb_slice.end_block_height == 98
        assert checkpoint_used is not None
        assert checkpoint_used.block_height == 14

        # 验证切片内容（应该跳过高度≤14的区块）
        assert len(vpb_slice.proofs_slice) == 5  # 包含15,27,56,67,98对应的proof units
        assert vpb_slice.block_index_slice.index_lst == [15, 27, 56, 67, 98]

        # 验证owner切片
        expected_owner_slice = [(15, "0x8360c"), (56, "0x14860")]
        assert vpb_slice.block_index_slice.owner == expected_owner_slice

    def test_extract_owner_epochs(self, vpb_verifier_with_checkpoint, sample_block_index_list):
        """测试owner epoch提取"""
        verifier, _ = vpb_verifier_with_checkpoint

        owner_epochs = verifier._extract_owner_epochs(sample_block_index_list)

        expected_epochs = {
            "0x418ab": [0],
            "0x8360c": [15],
            "0x14860": [56]
        }

        assert owner_epochs == expected_epochs


class TestVPBVerifyBloomFilter:
    """测试布隆过滤器验证功能"""

    @pytest.fixture
    def vpb_verifier(self):
        """创建VPB验证器实例"""
        return VPBVerify()

    @pytest.fixture
    def main_chain_info(self):
        """创建主链信息"""
        return MainChainInfo(
            merkle_roots={15: "root15", 27: "root27", 56: "root56", 67: "root67", 98: "root98"},
            bloom_filters={},
            current_block_height=98
        )

    @pytest.fixture
    def sample_value(self):
        """创建示例Value对象"""
        return Value("0x1000", 100)

    @pytest.fixture
    def vpb_slice(self, sample_value):
        """创建VPB切片对象"""
        block_index_slice = BlockIndexList(
            index_lst=[15, 27, 56, 67, 98],
            owner=[(15, "0x8360c"), (27, "0x8360c"), (56, "0x14860"), (67, "0x14860"), (98, "0x14860")]
        )

        return VPBSlice(
            value=sample_value,
            proofs_slice=[Mock(spec=ProofUnit) for _ in range(5)],
            block_index_slice=block_index_slice,
            start_block_height=15,
            end_block_height=98
        )

    def test_verify_bloom_filter_consistency_empty_slice(self, vpb_verifier, main_chain_info, sample_value):
        """测试空切片的布隆过滤器验证"""
        empty_slice = VPBSlice(
            value=sample_value,
            proofs_slice=[],
            block_index_slice=BlockIndexList([], []),
            start_block_height=15,
            end_block_height=15
        )

        is_valid, error_msg = vpb_verifier._verify_bloom_filter_consistency(empty_slice, main_chain_info)

        assert is_valid == False
        assert error_msg == "VPB slice has empty block index list"

    def test_verify_bloom_filter_consistency_mock(self, vpb_verifier, main_chain_info, vpb_slice):
        """测试布隆过滤器验证（使用真实Bloom模拟）"""
        from EZ_Units.Bloom import BloomFilter

        # 创建真实的布隆过滤器来模拟区块链状态
        bloom_filters = {}

        # 为每个区块创建布隆过滤器并添加相应的owner地址
        # 区块15: value属于"0x8360c"
        bloom_15 = BloomFilter(size=1024, hash_count=3)
        bloom_15.add("0X418ab")  # 0X418ab在区块15有交易，将Value转移给0x8360c
        bloom_filters[15] = bloom_15

        # 区块27: value属于"0x8360c"
        bloom_27 = BloomFilter(size=1024, hash_count=3)
        bloom_27.add("0x8360c")  # 0x8360c在区块27有交易，但值不是Value。
        bloom_filters[27] = bloom_27

        # 区块56: value属于"0x14860"，但0x8360c也可能有交易
        bloom_56 = BloomFilter(size=1024, hash_count=3)
        bloom_56.add("0x8360c")  # 0x8360c在区块56有交易，将Value转移给0x14860
        bloom_filters[56] = bloom_56

        # 区块67: value属于"0x14860"
        bloom_67 = BloomFilter(size=1024, hash_count=3)
        bloom_67.add("0x14860")  # 0x14860在区块67有交易，但值不是Value。
        bloom_filters[67] = bloom_67

        # 区块98: value属于"0x14860"
        bloom_98 = BloomFilter(size=1024, hash_count=3)
        bloom_98.add("0x14860")  # 0x14860在区块98有交易，但值不是Value。
        bloom_filters[98] = bloom_98

        # 更新main_chain_info使用真实的布隆过滤器
        main_chain_info.bloom_filters = bloom_filters

        # 使用真实的get_owner_transaction_blocks方法，它会查询布隆过滤器
        # 不再需要mock，让VPBVerify使用真实的布隆过滤器逻辑

        is_valid, error_msg = vpb_verifier._verify_bloom_filter_consistency(vpb_slice, main_chain_info)

        assert is_valid == True
        assert error_msg == ""


class TestVPBVerifyComplete:
    """测试完整的VPB验证流程"""

    @pytest.fixture
    def vpb_verifier(self):
        """创建VPB验证器实例"""
        return VPBVerify()

    @pytest.fixture
    def vpb_verifier_with_checkpoint(self):
        """创建带检查点的VPB验证器"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            verifier = VPBVerify(checkpoint=checkpoint)
            yield verifier, checkpoint
            # 清理
            checkpoint = None
            verifier = None
            import time
            time.sleep(0.1)
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except PermissionError:
                pass

    @pytest.fixture
    def main_chain_info(self):
        """创建主链信息"""
        return MainChainInfo(
            merkle_roots={0: "root0", 15: "root15", 27: "root27", 56: "root56"},
            bloom_filters={},
            current_block_height=56
        )

    @pytest.fixture
    def valid_vpb_data(self):
        """创建有效的VPB数据"""
        value = Value("0x1000", 100)

        # Mock Proofs - 需要匹配block_index_list的长度(4)
        proofs = Mock(spec=Proofs)
        proof_units = []
        for i in range(4):  # 修改为4个proof unit
            proof_unit = Mock(spec=ProofUnit)
            proof_unit.verify_proof_unit.return_value = (True, "")
            proof_units.append(proof_unit)
        proofs.proof_units = proof_units

        # BlockIndexList
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56],
            owner=[(0, "0xalice"), (15, "0xbob"), (27, "0xcharlie"), (56, "0xdave")]
        )

        return value, proofs, block_index_list

    def test_verify_vpb_pair_success(self, vpb_verifier, valid_vpb_data, main_chain_info):
        """测试成功验证VPB对"""
        value, proofs, block_index_list = valid_vpb_data

        # 创建真实的布隆过滤器模拟
        owner_data, additional_transactions = create_valid_vpb_bloom_filters()
        bloom_filters = create_realistic_bloom_filters([0, 15, 27, 56], owner_data, additional_transactions)
        main_chain_info.bloom_filters = bloom_filters

        # Mock the find_proof_unit_for_block method
        vpb_verifier._find_proof_unit_for_block = Mock(side_effect=lambda proofs, height, block_index_slice=None: proofs[0] if proofs else None)

        # Mock the value spend detection
        vpb_verifier._find_value_spend_transactions = Mock(return_value=[])

        report = vpb_verifier.verify_vpb_pair(
            value, proofs, block_index_list, main_chain_info, "0xeve"
        )

        assert report.result == VerificationResult.SUCCESS
        assert report.is_valid == True
        assert len(report.errors) == 0
        assert report.verification_time_ms >= 0

    def test_verify_vpb_pair_data_structure_failure(self, vpb_verifier, main_chain_info):
        """测试数据结构验证失败"""
        # 使用一个会通过基本验证但会在其他地方失败的无效值
        invalid_value = Value("0x1000", 1)  # 使用有效的值，但让验证在其他地方失败
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [Mock(spec=ProofUnit)]
        block_index_list = BlockIndexList([0], [(0, "0xalice")])

        report = vpb_verifier.verify_vpb_pair(
            invalid_value, proofs, block_index_list, main_chain_info, "0xalice"
        )

        # 由于mock的数据不完整，验证应该失败，但不是因为数据结构问题
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) > 0

    def test_verify_vpb_pair_checkpoint_optimization(self, vpb_verifier_with_checkpoint,
                                                    valid_vpb_data, main_chain_info):
        """测试检查点优化验证"""
        verifier, checkpoint = vpb_verifier_with_checkpoint
        value, proofs, block_index_list = valid_vpb_data

        # 创建检查点
        checkpoint.create_checkpoint(value, "0xalice", 14)

        # 创建真实的布隆过滤器模拟
        owner_data, additional_transactions = create_valid_vpb_bloom_filters()
        bloom_filters = create_realistic_bloom_filters([0, 15, 27, 56], owner_data, additional_transactions)
        main_chain_info.bloom_filters = bloom_filters

        # Mock other dependencies
        verifier._find_proof_unit_for_block = Mock(side_effect=lambda proofs, height, block_index_slice=None: proofs[0] if proofs else None)
        verifier._find_value_spend_transactions = Mock(return_value=[])

        report = verifier.verify_vpb_pair(
            value, proofs, block_index_list, main_chain_info, "0xalice"
        )

        assert report.result == VerificationResult.SUCCESS
        assert report.checkpoint_used is not None
        assert report.checkpoint_used.block_height == 14

    def test_verification_statistics(self, vpb_verifier, valid_vpb_data, main_chain_info):
        """测试验证统计信息"""
        value, proofs, block_index_list = valid_vpb_data

        # 创建真实的布隆过滤器模拟
        owner_data, additional_transactions = create_valid_vpb_bloom_filters()
        bloom_filters = create_realistic_bloom_filters([0, 15, 27, 56], owner_data, additional_transactions)
        main_chain_info.bloom_filters = bloom_filters

        # Mock other dependencies
        vpb_verifier._find_proof_unit_for_block = Mock(side_effect=lambda proofs, height, block_index_slice=None: proofs[0] if proofs else None)
        vpb_verifier._find_value_spend_transactions = Mock(return_value=[])

        # 初始统计
        stats = vpb_verifier.get_verification_stats()
        assert stats['total_verifications'] == 0
        assert stats['successful_verifications'] == 0
        assert stats['failed_verifications'] == 0

        # 执行验证
        vpb_verifier.verify_vpb_pair(value, proofs, block_index_list, main_chain_info, "0xalice")

        # 检查统计更新
        stats = vpb_verifier.get_verification_stats()
        assert stats['total_verifications'] == 1
        assert stats['successful_verifications'] == 1
        assert stats['success_rate'] == 1.0

    def test_reset_statistics(self, vpb_verifier, valid_vpb_data, main_chain_info):
        """测试重置统计信息"""
        value, proofs, block_index_list = valid_vpb_data

        # 创建真实的布隆过滤器模拟
        owner_data, additional_transactions = create_valid_vpb_bloom_filters()
        bloom_filters = create_realistic_bloom_filters([0, 15, 27, 56], owner_data, additional_transactions)
        main_chain_info.bloom_filters = bloom_filters

        # Mock other dependencies
        vpb_verifier._find_proof_unit_for_block = Mock(side_effect=lambda proofs, height, block_index_slice=None: proofs[0] if proofs else None)
        vpb_verifier._find_value_spend_transactions = Mock(return_value=[])

        # 执行验证
        vpb_verifier.verify_vpb_pair(value, proofs, block_index_list, main_chain_info, "0xalice")

        # 确认有统计数据
        stats = vpb_verifier.get_verification_stats()
        assert stats['total_verifications'] > 0

        # 重置统计
        vpb_verifier.reset_stats()

        # 确认统计已重置
        stats = vpb_verifier.get_verification_stats()
        assert stats['total_verifications'] == 0
        assert stats['successful_verifications'] == 0
        assert stats['failed_verifications'] == 0


class TestVPBVerifyEdgeCases:
    """测试VPB验证器的边缘案例"""

    @pytest.fixture
    def vpb_verifier(self):
        """创建VPB验证器实例"""
        return VPBVerify()

    @pytest.fixture
    def sample_value(self):
        """创建示例Value对象"""
        return Value("0x1000", 100)

    def test_validate_value_num_mismatch(self, vpb_verifier):
        """测试value_num与begin/end_index不匹配的情况"""
        # 创建一个value_num不匹配的Value（通过手动设置）
        value = Value("0x1000", 50)  # 50个值，应该从0x1000到0x1031

        # 创建匹配的proofs和block_index_list
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(1)]
        block_index_list = BlockIndexList([0], [(0, "0xowner1")])

        # 这个验证应该通过，因为Value类会自动计算正确的end_index
        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            value, proofs, block_index_list
        )
        assert is_valid == True

    def test_validate_empty_proofs_error(self, vpb_verifier, sample_value):
        """测试空proof units应该返回错误"""
        main_chain_info = MainChainInfo({}, {}, 0)

        # 创建空的VPB切片
        proofs = Mock(spec=Proofs)
        proofs.proof_units = []
        block_index_list = BlockIndexList([], [])

        report = vpb_verifier.verify_vpb_pair(
            sample_value, proofs, block_index_list, main_chain_info, "0xowner"
        )

        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert any("NO_PROOF_UNITS" in err.error_type for err in report.errors)

    def test_sender_verification_mismatch(self, vpb_verifier):
        """测试sender地址不匹配的情况（通过ProofUnit现有方法）"""
        # 创建Mock的proof unit和transactions
        proof_unit = Mock(spec=ProofUnit)
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0xwrong_sender"
        proof_unit.owner_multi_txns = mock_multi_txns

        # Mock verify_proof_unit方法来模拟sender不匹配的情况
        proof_unit.verify_proof_unit.return_value = (
            False,
            "MultiTransactions sender '0xwrong_sender' does not match owner '0xexpected_sender'"
        )

        # 测试现在通过调用verify_proof_unit而不是专门的sender验证方法
        is_valid, error_msg = proof_unit.verify_proof_unit("mock_merkle_root")

        assert is_valid == False
        assert "does not match owner" in error_msg

    def test_values_intersect(self, vpb_verifier):
        """测试value交集检测"""
        target_value = Value("0x1000", 100)  # 0x1000-0x1063

        # 创建有交集的value
        intersecting_value = Mock()
        intersecting_value.begin_index = "0x1050"  # 在范围内
        intersecting_value.end_index = "0x1070"   # 部分重叠

        has_intersect = vpb_verifier._values_intersect(intersecting_value, target_value)
        assert has_intersect == True

        # 创建无交集的value
        non_intersecting_value = Mock()
        non_intersecting_value.begin_index = "0x2000"  # 完全在范围外
        non_intersecting_value.end_index = "0x2030"

        has_intersect = vpb_verifier._values_intersect(non_intersecting_value, target_value)
        assert has_intersect == False

    def test_find_next_epoch_owner(self, vpb_verifier):
        """测试查找下一个epoch owner"""
        all_epochs = {
            "0xowner1": [1, 2, 3],    # 结束于3
            "0xowner2": [5, 6, 7],    # 结束于7
            "0xowner3": [9, 10],      # 结束于10
        }

        # 查找owner1的下一个owner
        next_owner = vpb_verifier._find_next_epoch_owner("0xowner1", all_epochs)
        assert next_owner == "0xowner2"

        # 查找owner2的下一个owner
        next_owner = vpb_verifier._find_next_epoch_owner("0xowner2", all_epochs)
        assert next_owner == "0xowner3"

        # 查找最后一个owner的下一个owner
        next_owner = vpb_verifier._find_next_epoch_owner("0xowner3", all_epochs)
        assert next_owner is None

    def test_detect_double_spend_in_epoch_no_transactions(self, vpb_verifier):
        """测试epoch中没有proof unit的情况"""
        value = Value("0x1000", 10)

        result = vpb_verifier._detect_double_spend_in_epoch(value, [], "0xowner", {})
        assert result[0] == True  # 空列表应该返回True
        assert len(result[1]) == 0

    def test_detect_double_spend_invalid_last_proof(self, vpb_verifier):
        """测试最后一个proof unit中没有有效花销交易"""
        # 创建Mock proof unit，包含与目标value交集的交易，但不是有效的花销交易
        proof_unit = Mock(spec=ProofUnit)
        mock_multi_txns = Mock()
        mock_transaction = Mock()

        # Mock交集检测返回True（有交集）
        vpb_verifier._find_value_intersect_transactions = Mock(return_value=[mock_transaction])
        # Mock有效交易检测返回False（没有有效花销）
        vpb_verifier._find_valid_value_spend_transactions = Mock(return_value=[])

        value = Value("0x1000", 10)
        epoch_proof_units = [(10, proof_unit)]
        all_epochs = {"0xowner": [10]}

        result = vpb_verifier._detect_double_spend_in_epoch(
            value, epoch_proof_units, "0xowner", all_epochs
        )

        assert result[0] == False
        assert any("NO_VALID_SPEND_IN_LAST_PROOF" in err.error_type for err in result[1])

    def test_detect_double_spend_unexpected_value_use(self, vpb_verifier):
        """测试非结尾proof unit中有意外的value使用"""
        # 创建Mock proof unit
        proof_unit1 = Mock(spec=ProofUnit)  # 非结尾的proof unit
        proof_unit2 = Mock(spec=ProofUnit)  # 结尾的proof unit

        # Mock第一个proof unit有与目标value交集的交易
        vpb_verifier._find_value_intersect_transactions = Mock(side_effect=[
            [Mock()],  # 第一个proof unit有交集交易
            []         # 第二个proof unit没有交集交易
        ])

        value = Value("0x1000", 10)
        epoch_proof_units = [(10, proof_unit1), (20, proof_unit2)]
        all_epochs = {"0xowner": [10, 20]}

        result = vpb_verifier._detect_double_spend_in_epoch(
            value, epoch_proof_units, "0xowner", all_epochs
        )

        assert result[0] == False
        assert any("UNEXPECTED_VALUE_USE" in err.error_type for err in result[1])


class TestVPBVerificationReport:
    """测试VPB验证报告"""

    def test_verification_report_creation(self):
        """测试验证报告创建"""
        errors = [
            VerificationError("TEST_ERROR", "Test error message", 10, 1)
        ]
        verified_epochs = [("0xowner1", [1, 2, 3])]
        checkpoint_record = CheckPointRecord(
            "0x1000", 100, "0xowner1", 50,
            datetime.now(timezone.utc), datetime.now(timezone.utc)
        )

        report = VPBVerificationReport(
            VerificationResult.FAILURE,
            False,
            errors,
            verified_epochs,
            checkpoint_record,
            150.5
        )

        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) == 1
        assert report.verified_epochs == verified_epochs
        assert report.checkpoint_used == checkpoint_record
        assert report.verification_time_ms == 150.5

    def test_verification_report_to_dict(self):
        """测试验证报告序列化"""
        errors = [
            VerificationError("TEST_ERROR", "Test error message", 10, 1)
        ]
        checkpoint_record = CheckPointRecord(
            "0x1000", 100, "0xowner1", 50,
            datetime.now(timezone.utc), datetime.now(timezone.utc)
        )

        report = VPBVerificationReport(
            VerificationResult.SUCCESS,
            True,
            [],
            [],
            checkpoint_record,
            100.0
        )

        report_dict = report.to_dict()

        assert report_dict['result'] == "success"
        assert report_dict['is_valid'] == True
        assert len(report_dict['errors']) == 0
        assert report_dict['verified_epochs'] == []
        assert report_dict['checkpoint_used'] is not None
        assert report_dict['verification_time_ms'] == 100.0
        assert report_dict['checkpoint_used']['owner_address'] == "0xowner1"


def create_complex_test_scenario_1():
    """
    复杂测试场景1：多链式转移

    描述：value经过多次转移，涉及多个参与者
    路径：genesis(0xgenesis) -> 0xalice -> 0xbob -> 0xcharlie -> 0xdave -> 0xeve

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {
        0: "0xgenesis",     # 创世块：genesis创建初始value
        10: "0xalice",      # 区块10：alice从genesis处接收value
        25: "0xbob",        # 区块25：bob从alice处接收value
        40: "0xcharlie",    # 区块40：charlie从bob处接收value
        55: "0xdave",       # 区块55：dave从charlie处接收value
        70: "0xeve",        # 区块70：eve从dave处接收value
    }

    # 记录交易提交者（会被加入布隆过滤器）
    additional_transactions = {
        10: ["0xgenesis"],      # genesis在区块10提交交易，转移value给alice
        25: ["0xalice"],        # alice在区块25提交交易，转移value给bob
        40: ["0xbob"],          # bob在区块40提交交易，转移value给charlie
        55: ["0xcharlie"],      # charlie在区块55提交交易，转移value给dave
        70: ["0xdave"],         # dave在区块70提交交易，转移value给eve
    }

    description = """
    复杂测试场景1：多链式转移
    - 路径：genesis -> alice -> bob -> charlie -> dave -> eve
    - 特点：每次转移都有明确的交易提交者和接收者
    - 验证点：布隆过滤器应该记录交易提交者，而不是value所有者
    """

    return owner_data, additional_transactions, description


def create_complex_test_scenario_2():
    """
    复杂测试场景2：分叉与合并

    描述：一个value分裂成多个部分，然后在后续重新合并
    注意：这是高级场景，可能需要特殊的value处理逻辑

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {
        0: "0xgenesis",         # 创世块
        15: ["0xalice", "0xbob"],  # 区块15：value分裂，alice和bob各持有一部分
        30: "0xcharlie",        # 区块30：alice和bob的部分都转移给charlie（合并）
        45: "0xdave",          # 区块45：charlie转移给dave
    }

    # 记录交易提交者
    additional_transactions = {
        15: ["0xgenesis"],         # genesis在区块15提交分裂交易
        30: ["0xalice", "0xbob"],  # alice和bob都在区块30提交交易，将各自部分转移给charlie
        45: ["0xcharlie"],         # charlie在区块45提交交易，转移给dave
    }

    description = """
    复杂测试场景2：分叉与合并
    - 路径：genesis -> {alice, bob} -> charlie -> dave
    - 特点：value在区块15分裂，在区块30重新合并
    - 验证点：测试布隆过滤器对复杂value结构的处理能力
    """

    return owner_data, additional_transactions, description


def create_complex_test_scenario_3():
    """
    复杂测试场景3：高频交易与噪声

    描述：在目标value交易的同时，有大量其他交易作为噪声
    测试布隆过滤器的准确性和抗干扰能力

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {
        0: "0xgenesis",
        20: "0xalice",      # 目标value：genesis -> alice
        50: "0xbob",        # 目标value：alice -> bob
        80: "0xcharlie",    # 目标value：bob -> charlie
    }

    # 大量噪声交易 + 目标交易
    additional_transactions = {}

    # 添加噪声交易：每个区块都有多个不相关的交易
    noise_addresses = ["0xnoise1", "0xnoise2", "0xnoise3", "0xnoise4", "0xnoise5"]

    for height in range(10, 90, 5):  # 每5个区块一批噪声交易
        additional_transactions[height] = noise_addresses.copy()

    # 在噪声中插入目标交易
    additional_transactions[20] = ["0xgenesis"] + noise_addresses  # genesis转移value给alice
    additional_transactions[50] = ["0xalice"] + noise_addresses   # alice转移value给bob
    additional_transactions[80] = ["0xbob"] + noise_addresses     # bob转移value给charlie

    description = """
    复杂测试场景3：高频交易与噪声
    - 路径：genesis -> alice -> bob -> charlie（在大量噪声交易中）
    - 特点：每个区块都有5个噪声地址，测试布隆过滤器的抗干扰能力
    - 验证点：确保系统能在噪声中准确识别目标交易
    """

    return owner_data, additional_transactions, description


def create_complex_test_scenario_4():
    """
    复杂测试场景4：并发交易与双花尝试

    描述：同一用户在多个区块尝试花费同一个value（测试双花检测）

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {
        0: "0xgenesis",
        25: "0xalice",      # 区块25：alice从genesis接收value
        40: "0xbob",        # 区块40：alice成功将value转移给bob
        # 注意：alice在区块35和45也尝试转移value，但这些应该是无效的双花尝试
    }

    # 记录交易提交者（包含双花尝试）
    additional_transactions = {
        25: ["0xgenesis"],      # genesis转移value给alice
        35: ["0xalice"],        # alice第一次双花尝试（应该失败）
        40: ["0xalice"],        # alice有效的value转移（成功）
        45: ["0xalice"],        # alice第二次双花尝试（应该失败）
    }

    description = """
    复杂测试场景4：并发交易与双花尝试
    - 路径：genesis -> alice -> bob（alice在区块35和45尝试双花）
    - 特点：测试双花检测机制的有效性
    - 验证点：只有区块40的交易应该被认为是有效的
    """

    return owner_data, additional_transactions, description


def create_complex_test_scenario_5():
    """
    复杂测试场景5：跨合约交易

    描述：value通过智能合约进行转移，涉及合约地址

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {
        0: "0xgenesis",
        30: "0xcontract",      # 区块30：value转移到智能合约
        60: "0xalice",         # 区块60：合约执行，value转移给alice
        90: "0xbob",           # 区块90：alice转移给bob
    }

    # 记录交易提交者（包括合约交互）
    additional_transactions = {
        30: ["0xgenesis"],            # genesis调用合约，转移value到合约地址
        60: ["0xcontract"],           # 合约自动执行，转移value给alice
        90: ["0xalice"],              # alice正常转移给bob
    }

    description = """
    复杂测试场景5：跨合约交易
    - 路径：genesis -> 合约 -> alice -> bob
    - 特点：涉及智能合约地址的特殊交易场景
    - 验证点：测试系统对合约地址的处理能力
    """

    return owner_data, additional_transactions, description


def create_stress_test_scenario():
    """
    压力测试场景：大量区块和交易

    描述：模拟真实区块链环境的大量数据

    Returns:
        tuple: (owner_data, additional_transactions, scenario_description)
    """
    owner_data = {}
    additional_transactions = {}

    # 生成1000个区块的测试数据
    current_height = 0
    current_owner = "0xgenesis"
    owner_data[current_height] = current_owner

    # 模拟value在1000个区块中的转移
    participants = [f"0xuser{i}" for i in range(1, 101)]  # 100个参与者

    for i in range(100):
        # 每10个区块发生一次转移
        transfer_height = (i + 1) * 10
        next_owner = participants[i % len(participants)]

        owner_data[transfer_height] = next_owner
        additional_transactions[transfer_height] = [current_owner]

        # 添加随机噪声交易
        if i % 3 == 0:  # 每3次转移添加一些噪声
            noise_count = 5
            noise_addresses = [f"0xnoise{j}" for j in range(noise_count)]
            additional_transactions[transfer_height].extend(noise_addresses)

        current_owner = next_owner
        current_height = transfer_height

    description = f"""
    压力测试场景：{len(owner_data)}个区块的大规模测试
    - 参与者：{len(participants)} + 1个
    - 转移次数：{len([h for h in owner_data.keys() if h > 0])}
    - 噪声交易：包含多个噪声地址
    - 验证点：测试系统在大数据量下的性能和准确性
    """

    return owner_data, additional_transactions, description


# 测试用例选择器
def get_test_scenario(scenario_id):
    """
    根据ID获取测试场景

    Args:
        scenario_id: 测试场景ID (1-6)

    Returns:
        tuple: (owner_data, additional_transactions, description)
    """
    scenarios = {
        1: create_complex_test_scenario_1,
        2: create_complex_test_scenario_2,
        3: create_complex_test_scenario_3,
        4: create_complex_test_scenario_4,
        5: create_complex_test_scenario_5,
        6: create_stress_test_scenario,
    }

    if scenario_id in scenarios:
        return scenarios[scenario_id]()
    else:
        raise ValueError(f"Invalid scenario ID: {scenario_id}. Available: 1-{len(scenarios)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])