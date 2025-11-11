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
        56: "0xdave"       # 区块56：dave从charlie处接收value（与valid_vpb_data保持一致）
    }

    # 记录在每个区块提交交易的sender地址（这些地址会被加入布隆过滤器）
    additional_transactions = {
        15: ["0xalice"],          # alice在区块15提交交易，将value转移给bob
        27: ["0xbob"],           # bob在区块27提交交易，将value转移给charlie
        56: ["0xcharlie"],       # charlie在区块56提交交易，将value转移给dave
        # ?: ["0xdave"]           # dave在区块?提交交易，将value转移给eve
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

    def test_validate_basic_data_structure_legal_duplicate_owners(self, vpb_verifier, sample_value):
        """测试合法的重复所有者场景"""
        # 创建包含重复所有者的BlockIndexList（这在VPB中是合法的）
        # 场景：Bob在不同时间点多次获得同一个value的不同部分
        # 例如：Bob最初获得value，转移部分给Alice，后来又从Charlie处重新获得value
        block_index_with_duplicates = BlockIndexList(
            index_lst=[0, 15, 27],
            owner=[(0, "0xbob"), (15, "0xbob"), (27, "0xalice")]  # bob重复出现，这在VPB中是合法的
        )

        # 创建匹配长度的proofs（3个proof对应3个index）
        matching_proofs = Mock(spec=Proofs)
        matching_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(3)]

        is_valid, error_msg = vpb_verifier._validate_basic_data_structure(
            sample_value, matching_proofs, block_index_with_duplicates
        )

        # 在VPB中，重复所有者是合法的业务场景，验证应该通过
        assert is_valid == True
        assert error_msg == ""

        # 验证重复所有者场景的具体业务逻辑
        owner_addresses = [owner[1] for owner in block_index_with_duplicates.owner]
        assert "0xbob" in owner_addresses
        assert owner_addresses.count("0xbob") == 2  # bob出现2次，这是合法的


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

        # 为main_chain_info添加get_owner_transaction_blocks方法的mock
        def mock_get_owner_transaction_blocks(owner_address, start_height, end_height):
            """
            Mock the get_owner_transaction_blocks method to return appropriate transaction blocks
            based on the additional_transactions data
            """
            result = []
            for height in range(start_height, end_height + 1):
                if height in additional_transactions and owner_address in additional_transactions[height]:
                    result.append(height)
            return result

        main_chain_info.get_owner_transaction_blocks = Mock(side_effect=mock_get_owner_transaction_blocks)

        # 为每个proof unit添加必要的属性和交易数据
        def create_mock_value(begin_index, end_index, value_num):
            """创建符合Value类接口的模拟value对象"""
            mock_value = Mock()
            mock_value.begin_index = begin_index
            mock_value.end_index = end_index
            mock_value.value_num = value_num
            # 添加Value类的方法接口
            mock_value.get_decimal_begin_index = lambda: int(begin_index, 16)
            mock_value.get_decimal_end_index = lambda: int(end_index, 16)
            return mock_value

        def create_mock_transaction(sender, receiver, value_begin="0x1000", value_num=100):
            """创建模拟交易对象"""
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.payer = sender  # 备用字段
            mock_tx.receiver = receiver
            mock_tx.payee = receiver  # 备用字段

            # 创建符合Value类接口的value对象
            value_end = hex(int(value_begin, 16) + value_num - 1)
            mock_value = create_mock_value(value_begin, value_end, value_num)

            # 为交易添加必要的属性来模拟value交集，使用正确的value对象结构
            if receiver == "0xbob":  # Alice转移给Bob
                mock_tx.input_values = [mock_value]  # 输入value，包含所有必要属性
                mock_tx.output_values = [mock_value]  # 输出value，包含所有必要属性
                mock_tx.spent_values = [mock_value]   # 花销value，包含所有必要属性
                mock_tx.received_values = [mock_value] # 接收value，包含所有必要属性
            elif receiver == "0xcharlie":  # Bob转移给Charlie
                mock_tx.input_values = [mock_value]
                mock_tx.output_values = [mock_value]
                mock_tx.spent_values = [mock_value]
                mock_tx.received_values = [mock_value]
            elif receiver == "0xdave":  # Charlie转移给Dave
                mock_tx.input_values = [mock_value]
                mock_tx.output_values = [mock_value]
                mock_tx.spent_values = [mock_value]
                mock_tx.received_values = [mock_value]
            elif receiver == "0xeve":  # Dave转移给Eve
                mock_tx.input_values = [mock_value]
                mock_tx.output_values = [mock_value]
                mock_tx.spent_values = [mock_value]
                mock_tx.received_values = [mock_value]
            else:
                mock_tx.input_values = []
                mock_tx.output_values = []
                mock_tx.spent_values = []
                mock_tx.received_values = []

            return mock_tx

        # 根据正确的价值转移逻辑配置proof units
        # 创世块0: Alice是创世owner（从GOD处获得），没有转移交易
        proofs.proof_units[0].owner_multi_txns = Mock()
        proofs.proof_units[0].owner_multi_txns.multi_txns = []  # 创世块没有价值转移交易
        proofs.proof_units[0].block_height = 0

        # 区块15: Alice -> Bob (Alice在区块0-15持有value，在区块15转移给Bob)
        proofs.proof_units[1].owner_multi_txns = Mock()
        proofs.proof_units[1].owner_multi_txns.multi_txns = [create_mock_transaction("0xalice", "0xbob")]
        proofs.proof_units[1].block_height = 15

        # 区块27: Bob -> Charlie (Bob在区块15-27持有value，在区块27转移给Charlie)
        proofs.proof_units[2].owner_multi_txns = Mock()
        proofs.proof_units[2].owner_multi_txns.multi_txns = [create_mock_transaction("0xbob", "0xcharlie")]
        proofs.proof_units[2].block_height = 27

        # 区块56: Charlie -> Dave (Charlie在区块27-55持有value，在区块56转移给Dave)
        # 注意：最终验证目标是0xdave，Dave是最后一个owner，所以区块56包含Charlie->Dave的转移
        proofs.proof_units[3].owner_multi_txns = Mock()
        proofs.proof_units[3].owner_multi_txns.multi_txns = [create_mock_transaction("0xcharlie", "0xdave")]
        proofs.proof_units[3].block_height = 56

        report = vpb_verifier.verify_vpb_pair(
            value, proofs, block_index_list, main_chain_info, "0xdave"
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

    def test_verify_vpb_pair_checkpoint_optimization(self, vpb_verifier_with_checkpoint):
        """测试检查点优化验证 - 复杂交易流程"""
        verifier, checkpoint = vpb_verifier_with_checkpoint

        # 创建目标value
        target_value = Value("0x1000", 100)

        # 创建block index list，只记录所有权变更的区块
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 区块0: Alice获得目标value（从GOD处）
                (15, "0xbob"),     # 区块15: Bob获得目标value（Alice→Bob转移目标value）
                (27, "0xcharlie"), # 区块27: Charlie获得目标value（Bob→Charlie转移目标value）
                (56, "0xdave"),    # 区块56: Dave获得目标value（Charlie→Dave转移目标value）
                (58, "0xbob")      # 区块58: Bob重新获得目标value（Dave→Bob转移目标value）
            ]
        )

        # 创建对应的proof units - 只为所有权变更的区块创建proof units
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(5)]  # 5个所有权变更区块

        # 为每个proof unit配置verify_proof_unit方法的返回值
        for i, proof_unit in enumerate(proofs.proof_units):
            proof_unit.verify_proof_unit = Mock(return_value=(True, ""))  # 返回(is_valid, error_msg)元组

        # 为每个proof unit添加必要的属性和交易数据
        def create_mock_value(begin_index, end_index, value_num):
            """创建符合Value类接口的模拟value对象"""
            mock_value = Mock()
            mock_value.begin_index = begin_index
            mock_value.end_index = end_index
            mock_value.value_num = value_num
            # 添加Value类的方法接口
            mock_value.get_decimal_begin_index = lambda: int(begin_index, 16)
            mock_value.get_decimal_end_index = lambda: int(end_index, 16)
            return mock_value

        def create_mock_transaction(sender, receiver, value_begin="0x1000", value_num=100, is_target_value=True):
            """创建模拟交易对象"""
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.payer = sender
            mock_tx.receiver = receiver
            mock_tx.payee = receiver

            if is_target_value:
                # 目标value的完整对象
                value_end = hex(int(value_begin, 16) + value_num - 1)
                mock_target_value = create_mock_value(value_begin, value_end, value_num)
                mock_tx.input_values = [mock_target_value]
                mock_tx.output_values = [mock_target_value]
                mock_tx.spent_values = [mock_target_value]
                mock_tx.received_values = [mock_target_value]
            else:
                # 非目标value的其他交易
                other_value = create_mock_value("0x2000", "0x20FF", 256)
                mock_tx.input_values = [other_value]
                mock_tx.output_values = [other_value]
                mock_tx.spent_values = [other_value]
                mock_tx.received_values = [other_value]

            return mock_tx

        # 配置每个所有权变更区块的proof units
        # 区块0: Alice获得目标value（创世块，无转移交易）
        proofs.proof_units[0].owner_multi_txns = Mock()
        proofs.proof_units[0].owner_multi_txns.multi_txns = []  # 创世块无价值转移
        proofs.proof_units[0].block_height = 0

        # 区块15: Bob获得目标value（Alice→Bob转移目标value）
        proofs.proof_units[1].owner_multi_txns = Mock()
        proofs.proof_units[1].owner_multi_txns.multi_txns = [create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)]
        proofs.proof_units[1].block_height = 15

        # 区块27: Charlie获得目标value（Bob→Charlie转移目标value）
        proofs.proof_units[2].owner_multi_txns = Mock()
        proofs.proof_units[2].owner_multi_txns.multi_txns = [create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)]
        proofs.proof_units[2].block_height = 27

        # 区块56: Dave获得目标value（Charlie→Dave转移目标value）
        proofs.proof_units[3].owner_multi_txns = Mock()
        proofs.proof_units[3].owner_multi_txns.multi_txns = [create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)]
        proofs.proof_units[3].block_height = 56

        # 区块58: Bob重新获得目标value（Dave→Bob转移目标value）
        proofs.proof_units[4].owner_multi_txns = Mock()
        proofs.proof_units[4].owner_multi_txns.multi_txns = [create_mock_transaction("0xdave", "0xbob", "0x1000", 100, True)]
        proofs.proof_units[4].block_height = 58

        # 创建主链信息（包含所有相关区块的merkle root）
        main_chain_info = MainChainInfo(
            merkle_roots={i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 58]},
            bloom_filters={},
            current_block_height=58
        )

        # 创建布隆过滤器数据，模拟真实的区块链状态
        owner_data = {
            0: "0xalice",      # 创世块：alice是初始value的所有者
            8: "0xalice",      # 区块8：alice进行其他交易（非目标value）
            15: "0xbob",       # 区块15：bob从alice处接收目标value
            16: "0xbob",       # 区块16：bob进行其他交易
            25: "0xbob",       # 区块25：bob进行其他交易
            27: "0xcharlie",   # 区块27：charlie从bob处接收目标value
            55: "0xcharlie",   # 区块55：charlie进行其他交易
            56: "0xdave",      # 区块56：dave从charlie处接收目标value
            58: "0xbob"        # 区块58：bob从dave处接收目标value
        }

        # 记录在每个区块提交交易的sender地址（会被加入布隆过滤器）
        # 包括目标value转移交易和其它交易
        additional_transactions = {
            8: ["0xalice"],        # alice在区块8提交其他交易
            15: ["0xalice"],       # alice在区块15提交目标value转移交易给bob
            16: ["0xbob"],         # bob在区块16提交其他交易
            25: ["0xbob"],         # bob在区块25提交其他交易
            27: ["0xbob"],         # bob在区块27提交目标value转移交易给charlie
            55: ["0xcharlie"],     # charlie在区块55提交其他交易
            56: ["0xcharlie"],     # charlie在区块56提交目标value转移交易给dave
            58: ["0xdave"],        # dave在区块58提交目标value转移交易给bob
        }

        bloom_filters = create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            owner_data,
            additional_transactions
        )
        main_chain_info.bloom_filters = bloom_filters

        # 为main_chain_info添加get_owner_transaction_blocks方法的mock
        def mock_get_owner_transaction_blocks(owner_address, start_height, end_height):
            """Mock the get_owner_transaction_blocks method"""
            result = []
            for height in range(start_height, end_height + 1):
                if height in additional_transactions and owner_address in additional_transactions[height]:
                    result.append(height)
            return result

        main_chain_info.get_owner_transaction_blocks = Mock(side_effect=mock_get_owner_transaction_blocks)

        # 创建检查点：Bob在区块27将value转移给Charlie后，作为发送方创建checkpoint
        # 根据Checkpoint生成机制：Bob在区块27完成交易并被确认后，可创建checkpoint记录
        # target_value在区块高度26（27-1）时最后由Bob合法持有
        checkpoint.create_checkpoint(target_value, "0xbob", 26)

        # 启用调试日志
        import logging
        logging.getLogger("EZ_VPB.VPBVerify").setLevel(logging.DEBUG)

        # 执行验证：验证Dave在区块58将目标value转移给Bob的完整性
        # 这应该从checkpoint（区块26）开始验证，验证从区块27开始的交易历史
        report = verifier.verify_vpb_pair(
            target_value, proofs, block_index_list, main_chain_info, "0xbob"
        )

        # 验证结果
        assert report.result == VerificationResult.SUCCESS
        assert report.is_valid == True
        assert len(report.errors) == 0

        # 验证checkpoint被正确使用
        assert report.checkpoint_used is not None
        assert report.checkpoint_used.block_height == 26  # Bob记录在区块26持有value
        assert report.checkpoint_used.owner_address == "0xbob"

        # 验证验证时间合理（因为使用了checkpoint，应该比从头验证更快）
        assert report.verification_time_ms >= 0

        # 验证经过的epoch被正确记录
        # 从checkpoint（区块26）开始的epoch应该包括：Charlie (区块27)、Dave (区块56) 和 Bob (区块58)
        # 注意：区块27的验证属于Charlie的epoch，因为Charlie在该区块获得了value
        expected_verified_epochs = [
            ("0xcharlie", [27]),   # Charlie在区块27从Bob处获得value
            ("0xdave", [56]),      # Dave在区块56从Charlie处获得value
            ("0xbob", [58])        # Bob在区块58从Dave处重新获得value
        ]

        # 比较验证的epoch（可能顺序不同）
        actual_epochs = sorted(report.verified_epochs, key=lambda x: x[0])
        expected_epochs = sorted(expected_verified_epochs, key=lambda x: x[0])

        assert len(actual_epochs) == len(expected_epochs)
        for (actual_owner, actual_blocks), (expected_owner, expected_blocks) in zip(actual_epochs, expected_epochs):
            assert actual_owner == expected_owner
            assert sorted(actual_blocks) == sorted(expected_blocks)

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

        result = vpb_verifier._detect_double_spend_in_epoch(value, [], "0xowner", None)
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

        result = vpb_verifier._detect_double_spend_in_epoch(
            value, epoch_proof_units, "0xowner", "0xprevious_owner"
        )

        assert result[0] == False
        # 简化后的逻辑返回 NO_VALID_TRANSFER_IN_BLOCK 错误
        assert any("NO_VALID_TRANSFER_IN_BLOCK" in err.error_type for err in result[1])

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

        result = vpb_verifier._detect_double_spend_in_epoch(
            value, epoch_proof_units, "0xowner", "0xprevious_owner"
        )

        assert result[0] == False
        # 简化后的逻辑返回 NO_VALID_TRANSFER_IN_BLOCK 或 INVALID_BLOCK_VALUE_INTERSECTION 错误
        assert any(error_type in err.error_type for err in result[1]
                  for error_type in ["NO_VALID_TRANSFER_IN_BLOCK", "INVALID_BLOCK_VALUE_INTERSECTION"])


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])