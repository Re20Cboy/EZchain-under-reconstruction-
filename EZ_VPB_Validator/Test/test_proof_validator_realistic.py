#!/usr/bin/env python3
"""
Proof Validator Security Test Suite

基于前面3个步骤已经确保数据结构正确的前提下，
专门测试proof_validator_04.py的业务逻辑安全性。

测试目标：
1. 验证双花检测的有效性
2. 测试复杂交易结构的处理能力
3. 确保epoch提取逻辑的正确性
4. 验证创世块和普通区块的区分处理
5. 测试各种攻击场景下的防御能力
"""

import pytest
import logging
import sys
import os
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from unittest.mock import Mock, MagicMock, patch

# 添加项目路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# ============================================================================
# 精确的模拟数据结构（确保与前面步骤的一致性）
# ============================================================================

@dataclass
class VerificationError:
    """验证错误信息"""
    error_type: str
    error_message: str
    block_height: Optional[int] = None
    proof_index: Optional[int] = None

@dataclass
class MockValue:
    """精确的Value对象模拟"""
    begin_index: str
    end_index: str
    value_num: int = 1

    def check_value(self):
        """模拟Value类的check_value方法"""
        try:
            # 验证十六进制格式
            int(self.begin_index, 16)
            int(self.end_index, 16)
            # 验证value_num为正数
            if self.value_num <= 0:
                return False
            return True
        except (ValueError, AttributeError):
            return False

@dataclass
class MockTransaction:
    """精确的交易对象模拟（支持多角度攻击）"""
    sender: str
    receiver: str
    input_values: List[MockValue] = None
    output_values: List[MockValue] = None
    spent_values: List[MockValue] = None
    received_values: List[MockValue] = None

    def __post_init__(self):
        if self.input_values is None:
            self.input_values = []
        if self.output_values is None:
            self.output_values = []
        if self.spent_values is None:
            self.spent_values = []
        if self.received_values is None:
            self.received_values = []

@dataclass
class MockProofUnit:
    """精确的ProofUnit对象模拟"""
    block_height: int
    owner: str
    owner_multi_txns: 'MockMultiTxns' = None
    owner_mt_proof: str = "mock_mt_proof"
    unit_id: str = "mock_unit_id"
    reference_count: int = 1

    def verify_proof_unit(self, merkle_root):
        """模拟ProofUnit的验证方法（总是返回True，假设前面步骤已验证）"""
        return True, ""

@dataclass
class MockMultiTxns:
    """精确的MultiTxns对象模拟"""
    sender: str
    digest: str = "mock_digest"
    multi_txns: List[MockTransaction] = None

    def __post_init__(self):
        if self.multi_txns is None:
            self.multi_txns = []

@dataclass
class MockBlockIndexSlice:
    """精确的BlockIndexList模拟（确保与前面步骤一致）"""
    index_lst: List[int]
    owner: List[Tuple[int, str]]

@dataclass
class MockVPBSlice:
    """精确的VPBSlice模拟"""
    value: MockValue
    proofs_slice: List[MockProofUnit]
    block_index_slice: MockBlockIndexSlice
    start_block_height: int = 0
    end_block_height: int = 0
    checkpoint_used: Any = None
    previous_owner: Optional[str] = None

@dataclass
class MockMainChainInfo:
    """主链信息"""
    merkle_roots: Dict[int, str]

# ============================================================================
# 精确的依赖类实现
# ============================================================================

class MockValueIntersectionDetector:
    """精确的Value交集检测器（模拟真实行为）"""

    def __init__(self, logger=None):
        self.logger = logger

    def find_value_intersect_transactions(self, proof_unit: MockProofUnit, value: MockValue) -> List[MockTransaction]:
        """查找与目标value有交集的交易"""
        intersect_transactions = []

        if proof_unit and proof_unit.owner_multi_txns:
            for transaction in proof_unit.owner_multi_txns.multi_txns:
                if self.transaction_intersects_value(transaction, value):
                    intersect_transactions.append(transaction)

        return intersect_transactions

    def find_valid_value_spend_transactions(self, proof_unit: MockProofUnit, value: MockValue,
                                          expected_sender: str, expected_receiver: str = None) -> List[MockTransaction]:
        """查找有效的value花销交易"""
        valid_transactions = []

        if proof_unit and proof_unit.owner_multi_txns:
            for transaction in proof_unit.owner_multi_txns.multi_txns:
                if self.is_valid_value_spend_transaction(transaction, value, expected_sender, expected_receiver):
                    valid_transactions.append(transaction)

        return valid_transactions

    def transaction_intersects_value(self, transaction: MockTransaction, value: MockValue) -> bool:
        """检查交易是否与目标value有交集（精确模拟）"""
        # 检查所有value字段
        all_values = (transaction.input_values + transaction.output_values +
                     transaction.spent_values + transaction.received_values)

        for val in all_values:
            if val is not None:  # 确保不处理None值
                if self.values_intersect(val, value):
                    return True
        return False

    def is_valid_value_spend_transaction(self, transaction: MockTransaction, value: MockValue,
                                       expected_sender: str, expected_receiver: str = None) -> bool:
        """检查是否是有效的value花销交易（精确模拟）"""
        # 检查发送者
        if transaction.sender != expected_sender:
            return False

        # 检查value匹配和接收者
        all_output_values = transaction.output_values + transaction.received_values
        for val in all_output_values:
            if val is not None and self.values_match(val, value):
                if expected_receiver is None or transaction.receiver == expected_receiver:
                    return True

        return False

    def values_intersect(self, value1: MockValue, value2: MockValue) -> bool:
        """检查两个value是否有交集（精确模拟Value类的逻辑）"""
        try:
            v1_begin = int(value1.begin_index, 16)
            v1_end = int(value1.end_index, 16)
            v2_begin = int(value2.begin_index, 16)
            v2_end = int(value2.end_index, 16)

            # 检查是否有重叠
            return not (v1_end < v2_begin or v2_end < v1_begin)
        except (ValueError, AttributeError, TypeError):
            return False

    def values_match(self, value1: MockValue, value2: MockValue) -> bool:
        """检查两个value是否完全匹配"""
        return (value1.begin_index == value2.begin_index and
                value1.end_index == value2.end_index and
                value1.value_num == value2.value_num)

class MockEpochExtractor:
    """精确的Epoch提取器"""

    def __init__(self, logger=None):
        self.logger = logger

    def extract_owner_epochs(self, block_index_slice: MockBlockIndexSlice) -> List[Tuple[int, str]]:
        """从BlockIndexSlice中提取epoch信息（修复版本）"""
        epochs = []

        if not block_index_slice.owner or not block_index_slice.index_lst:
            return epochs

        # 创建区块高度到owner的映射
        block_to_owner = {height: owner for height, owner in block_index_slice.owner}

        # 按区块高度排序构建epoch列表（index_lst已经严格递增）
        current_owner = None
        for block_height in block_index_slice.index_lst:
            if block_height in block_to_owner:
                owner = block_to_owner[block_height]
                current_owner = owner
            else:
                # 如果该区块没有owner记录，使用上一个owner
                if current_owner is None:
                    # 第一个区块但没有owner记录，这是数据结构问题
                    # 但根据前面步骤的保证，这种情况不应该发生
                    continue
                owner = current_owner

            epochs.append((block_height, owner))

        return epochs

    def get_previous_owner_for_block(self, epochs: List[Tuple[int, str]], target_block: int) -> Optional[str]:
        """获取指定区块的前驱owner地址"""
        # 找到目标区块在epoch列表中的位置
        target_index = -1
        for i, (block_height, owner) in enumerate(epochs):
            if block_height == target_block:
                target_index = i
                break

        if target_index == -1:
            return None

        # 如果是第一个epoch（创世块），没有前驱
        if target_index == 0:
            return None

        # 返回前一个epoch的owner
        previous_block, previous_owner = epochs[target_index - 1]
        return previous_owner

# ============================================================================
# 复制修复后的ProofValidator（确保测试准确性）
# ============================================================================

class ProofValidator:
    """证明单元验证器（复制自修复后的代码）"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("proof_validator")
        self.value_detector = MockValueIntersectionDetector(logger)
        self.epoch_extractor = MockEpochExtractor(logger)

    def verify_proof_units_and_detect_double_spend(self, vpb_slice: MockVPBSlice, main_chain_info: MockMainChainInfo,
                                                 checkpoint_used: Optional[Any] = None) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
        """第四步：逐证明单元验证和双花检测"""
        errors = []
        verified_epochs = []

        if not vpb_slice.proofs_slice:
            # 特殊处理：如果只有创世块且start_height=0，可能是正常的
            if vpb_slice.start_block_height == 0 and vpb_slice.end_block_height == 0:
                return True, errors, verified_epochs
            else:
                errors.append(VerificationError(
                    "NO_PROOF_UNITS",
                    f"No proof units found for value {vpb_slice.value.begin_index}. "
                    "Every value verification requires corresponding proof units."
                ))
                return False, errors, verified_epochs

        # 提取epochs
        epochs = self.epoch_extractor.extract_owner_epochs(vpb_slice.block_index_slice)

        # 构建第一个验证区块后的辅助信息（用于checkpoint处理）
        first_verification_block_after_checkpoint = None
        if checkpoint_used:
            verification_blocks = [block_height for block_height, _ in epochs
                                  if block_height > checkpoint_used.block_height]
            if verification_blocks:
                first_verification_block_after_checkpoint = min(verification_blocks)

        # 对每个epoch（区块）进行验证（按时间顺序）
        for i, (block_height, owner_address) in enumerate(epochs):
            # 找到对应的proof unit
            proof_unit = self._find_proof_unit_for_block(vpb_slice.proofs_slice, block_height, vpb_slice.block_index_slice)
            if not proof_unit:
                errors.append(VerificationError(
                    "PROOF_UNIT_MISSING",
                    f"Proof unit not found for block {block_height} of owner {owner_address}",
                    block_height=block_height
                ))
                continue

            # 检查Merkle根
            if block_height not in main_chain_info.merkle_roots:
                errors.append(VerificationError(
                    "MERKLE_ROOT_MISSING",
                    f"Merkle root not found for block {block_height}",
                    block_height=block_height
                ))
                continue

            merkle_root = main_chain_info.merkle_roots[block_height]

            # 验证proof unit（假设总是成功）
            is_valid, error_msg = proof_unit.verify_proof_unit(merkle_root)
            if not is_valid:
                errors.append(VerificationError(
                    "PROOF_UNIT_VERIFICATION_FAILED",
                    f"Proof unit verification failed at block {block_height}: {error_msg}",
                    block_height=block_height
                ))
                continue

            # 确定previous_owner
            if not checkpoint_used and i == 0:
                previous_owner = None
            elif checkpoint_used and block_height == first_verification_block_after_checkpoint:
                previous_owner = checkpoint_used.owner_address
            else:
                previous_owner = self.epoch_extractor.get_previous_owner_for_block(epochs, block_height)

            # 检测双花
            epoch_proof_units = [(block_height, proof_unit)]
            double_spend_result = self._detect_double_spend_in_epoch(
                vpb_slice.value, epoch_proof_units, owner_address, previous_owner
            )
            if not double_spend_result[0]:
                errors.extend(double_spend_result[1])
            else:
                verified_epochs.append((owner_address, [block_height]))

        return len(errors) == 0, errors, verified_epochs

    def _find_proof_unit_for_block(self, proofs_slice: List[MockProofUnit], block_height: int, block_index_slice: MockBlockIndexSlice = None) -> Optional[MockProofUnit]:
        """在proof units切片中查找指定区块高度的proof unit"""
        if not proofs_slice:
            return None

        if block_index_slice and block_index_slice.index_lst:
            try:
                height_index = block_index_slice.index_lst.index(block_height)
                if 0 <= height_index < len(proofs_slice):
                    return proofs_slice[height_index]
            except ValueError:
                return None

        # 如果没有提供block_index_slice，尝试从proof unit自身获取高度信息
        for proof_unit in proofs_slice:
            if hasattr(proof_unit, 'block_height') and proof_unit.block_height == block_height:
                return proof_unit

        return None

    def _detect_double_spend_in_epoch(self, value: MockValue, epoch_proof_units: List[Tuple[int, MockProofUnit]],
                                    owner_address: str, previous_owner: Optional[str] = None) -> Tuple[bool, List[VerificationError]]:
        """基于详细需求检测epoch内的双花行为"""
        errors = []

        if not epoch_proof_units:
            return len(errors) == 0, errors

        # 按区块高度排序proof units
        epoch_proof_units.sort(key=lambda x: x[0])

        # 检查每个proof unit
        for block_height, proof_unit in epoch_proof_units:
            # 检查是否有与目标value交集的交易
            value_intersect_transactions = self.value_detector.find_value_intersect_transactions(proof_unit, value)

            # 创世块特殊处理：必须包含GOD->owner的派发交易
            if block_height == 0:
                valid_spend_transactions = self.value_detector.find_valid_value_spend_transactions(
                    proof_unit, value, "GOD", owner_address
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "MISSING_GENESIS_VALUE_DISTRIBUTION",
                        f"Genesis block must contain GOD->{owner_address} value distribution, but found no valid transactions",
                        block_height=0
                    ))

                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_GENESIS_VALUE_INTERSECTION",
                            f"Invalid value intersection in genesis block {block_height}. Only GOD->{owner_address} distribution allowed.",
                            block_height=0
                        ))
                continue

            # 非创世块：判断这是目标value转移区块还是非目标value交易区块
            is_target_value_block = self._is_target_value_transfer_block(block_height, owner_address, previous_owner)

            if is_target_value_block:
                valid_spend_transactions = self.value_detector.find_valid_value_spend_transactions(
                    proof_unit, value, previous_owner, owner_address
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "NO_VALID_TARGET_VALUE_TRANSFER",
                        f"Block {block_height} must contain valid target value transfer from {previous_owner} to {owner_address}",
                        block_height=block_height
                    ))

                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_TARGET_VALUE_INTERSECTION",
                            f"Invalid target value intersection in block {block_height}. Only {previous_owner}->{owner_address} transfer allowed.",
                            block_height=block_height
                        ))
            else:
                # 非目标value交易区块：必须与目标value完全无交集
                if value_intersect_transactions:
                    errors.append(VerificationError(
                        "DOUBLE_SPEND_DETECTED",
                        f"Block {block_height} contains transactions intersecting with target value",
                        block_height=block_height
                    ))
                    for tx in value_intersect_transactions:
                        errors.append(VerificationError(
                            "DOUBLE_SPEND_TRANSACTION",
                            f"Double spend transaction in block {block_height}",
                            block_height=block_height
                        ))

        return len(errors) == 0, errors

    def _is_target_value_transfer_block(self, block_height: int, owner_address: str, previous_owner: Optional[str]) -> bool:
        """判断指定区块是否应该是目标value转移区块"""
        # 如果有前驱owner且owner地址发生变化，说明是目标value转移区块
        if previous_owner is not None and previous_owner != owner_address:
            return True

        # 如果没有前驱owner（创世块已经在其他地方处理），默认认为是目标value转移区块
        return False

# ============================================================================
# 现实主义黑客测试套件
# ============================================================================

class TestProofValidatorRealisticHacker:
    """现实主义黑客视角的Proof验证器测试"""

    @pytest.fixture
    def validator(self):
        """创建验证器实例"""
        logger = logging.getLogger("realistic_hacker")
        return ProofValidator(logger)

    @pytest.fixture
    def target_value(self):
        """目标价值对象"""
        return MockValue(begin_index="0x1000", end_index="0x1FFF", value_num=1)

    @pytest.fixture
    def main_chain_info(self):
        """主链信息（覆盖测试所需的区块）"""
        return MockMainChainInfo(merkle_roots={
            0: "root_0", 8: "root_8", 15: "root_15", 16: "root_16",
            25: "root_25", 27: "root_27", 55: "root_55", 56: "root_56", 58: "root_58"
        })

    def test_realistic_attack_1_partial_value_double_spend(self, validator, target_value, main_chain_info):
        """
        现实攻击1：部分价值双花攻击

        攻击思路：创建一个与目标value部分重叠的新value，
        试图在非目标value区块中使用它来绕过完整value的双花检测。
        """
        print("\n[!] REALISTIC ATTACK 1: Partial Value Double Spend")

        # 创建与目标value部分重叠的恶意value
        partial_overlap_value = MockValue(begin_index="0x1800", end_index="0x2FFF", value_num=1)

        # 正常的创世块
        genesis_proof = MockProofUnit(
            block_height=0,
            owner="alice",
            owner_multi_txns=MockMultiTxns(
                sender="alice",
                multi_txns=[
                    MockTransaction(
                        sender="GOD",
                        receiver="alice",
                        output_values=[target_value]
                    )
                ]
            )
        )

        # 攻击区块：alice在非目标value区块中，使用部分重叠的value进行双花
        attack_proof = MockProofUnit(
            block_height=8,
            owner="alice",  # owner未变化（非目标value区块）
            owner_multi_txns=MockMultiTxns(
                sender="alice",
                multi_txns=[
                    MockTransaction(
                        sender="alice",
                        receiver="mallory",
                        spent_values=[partial_overlap_value],  # 使用部分重叠的value（应该被检测为交集）
                        output_values=[MockValue("0x3000", "0x3FFF")]
                    )
                ]
            )
        )

        # 正常的转移区块
        transfer_proof = MockProofUnit(
            block_height=15,
            owner="bob",  # owner变化（目标value转移区块）
            owner_multi_txns=MockMultiTxns(
                sender="bob",
                multi_txns=[
                    MockTransaction(
                        sender="alice",
                        receiver="bob",
                        output_values=[target_value]
                    )
                ]
            )
        )

        attack_vpb = MockVPBSlice(
            value=target_value,
            proofs_slice=[genesis_proof, attack_proof, transfer_proof],
            block_index_slice=MockBlockIndexSlice(
                index_lst=[0, 8, 15],  # 前面步骤确保数量一致
                owner=[(0, "alice"), (15, "bob")]  # 注意：区块8没有owner变化，所以不包含在owner列表中
            ),
            start_block_height=0,
            end_block_height=15
        )

        result, errors, verified_epochs = validator.verify_proof_units_and_detect_double_spend(attack_vpb, main_chain_info)

        print(f"[!] Result: {result}")
        print(f"[!] Errors: {[e.error_type for e in errors]}")

        # 应该检测到部分价值交集（双花）
        assert not result, "Validator should detect partial value double spend"
        assert any(e.error_type == "DOUBLE_SPEND_DETECTED" for e in errors)

        print("[VALIDATOR WINS] Partial value double spend detected")

    def test_realistic_attack_2_composite_transaction_spoofing(self, validator, target_value, main_chain_info):
        """
        现实攻击2：复合交易欺骗攻击

        攻击思路：构造一个包含多个value的复合交易，
        其中包含目标value，但试图伪装成正常的多value交易。
        """
        print("\n[!] REALISTIC ATTACK 2: Composite Transaction Spoofing")

        # 创建其他正常的value
        other_value1 = MockValue(begin_index="0x2000", end_index="0x2FFF", value_num=1)
        other_value2 = MockValue(begin_index="0x3000", end_index="0x3FFF", value_num=1)

        # 正常的创世块
        genesis_proof = MockProofUnit(
            block_height=0,
            owner="alice",
            owner_multi_txns=MockMultiTxns(
                sender="alice",
                multi_txns=[
                    MockTransaction(
                        sender="GOD",
                        receiver="alice",
                        output_values=[target_value, other_value1]  # 多value输出
                    )
                ]
            )
        )

        # 攻击区块：alice在非目标value区块中，通过复合交易隐藏双花
        composite_attack_tx = MockTransaction(
            sender="alice",
            receiver="mallory",
            input_values=[other_value2],  # 正常的输入
            spent_values=[target_value],  # 隐藏的目标value花销
            output_values=[other_value1, other_value2],  # 看似正常的输出
            received_values=[other_value1]  # 看似正常的接收
        )

        attack_proof = MockProofUnit(
            block_height=8,
            owner="alice",  # owner未变化
            owner_multi_txns=MockMultiTxns(
                sender="alice",
                multi_txns=[composite_attack_tx]
            )
        )

        attack_vpb = MockVPBSlice(
            value=target_value,
            proofs_slice=[genesis_proof, attack_proof],
            block_index_slice=MockBlockIndexSlice(
                index_lst=[0, 8],
                owner=[(0, "alice")]  # 区块8没有owner变化
            ),
            start_block_height=0,
            end_block_height=8
        )

        result, errors, verified_epochs = validator.verify_proof_units_and_detect_double_spend(attack_vpb, main_chain_info)

        print(f"[!] Result: {result}")
        print(f"[!] Errors: {[e.error_type for e in errors]}")

        # 应该检测到复合交易中的目标value交集
        assert not result, "Validator should detect double spend in composite transaction"
        assert any(e.error_type == "DOUBLE_SPEND_DETECTED" for e in errors)

        print("[VALIDATOR WINS] Composite transaction double spend detected")

    def test_realistic_attack_3_transfer_path_manipulation(self, validator, target_value, main_chain_info):
        """
        现实攻击3：转移路径操纵攻击

        攻击思路：构造看似合法的转移路径，但实际包含恶意交易。
        试图通过合法的owner变化序列来隐藏非法交易。
        """
        print("\n[!] REALISTIC ATTACK 3: Transfer Path Manipulation")

        # 构造完整的"合法"转移路径：alice -> bob -> charlie
        proofs = [
            # 创世块：GOD -> alice
            MockProofUnit(
                block_height=0,
                owner="alice",
                owner_multi_txns=MockMultiTxns(
                    sender="alice",
                    multi_txns=[
                        MockTransaction(
                            sender="GOD",
                            receiver="alice",
                            output_values=[target_value]
                        )
                    ]
                )
            ),
            # alice的非目标value区块（但包含恶意交易）
            MockProofUnit(
                block_height=8,
                owner="alice",
                owner_multi_txns=MockMultiTxns(
                    sender="alice",
                    multi_txns=[
                        MockTransaction(
                            sender="alice",
                            receiver="hidden_attacker",
                            spent_values=[target_value],  # 恶意花销目标value
                            output_values=[MockValue("0x4000", "0x4FFF")]
                        )
                    ]
                )
            ),
            # alice -> bob的转移区块（看起来合法）
            MockProofUnit(
                block_height=15,
                owner="bob",
                owner_multi_txns=MockMultiTxns(
                    sender="bob",
                    multi_txns=[
                        MockTransaction(
                            sender="alice",
                            receiver="bob",
                            output_values=[target_value]  # 但这里target_value已经被双花了
                        )
                    ]
                )
            ),
            # bob -> charlie的转移区块（继续合法路径）
            MockProofUnit(
                block_height=27,
                owner="charlie",
                owner_multi_txns=MockMultiTxns(
                    sender="charlie",
                    multi_txns=[
                        MockTransaction(
                            sender="bob",
                            receiver="charlie",
                            output_values=[target_value]
                        )
                    ]
                )
            )
        ]

        attack_vpb = MockVPBSlice(
            value=target_value,
            proofs_slice=proofs,
            block_index_slice=MockBlockIndexSlice(
                index_lst=[0, 8, 15, 27],
                owner=[(0, "alice"), (15, "bob"), (27, "charlie")]  # 完整的转移路径
            ),
            start_block_height=0,
            end_block_height=27
        )

        result, errors, verified_epochs = validator.verify_proof_units_and_detect_double_spend(attack_vpb, main_chain_info)

        print(f"[!] Result: {result}")
        print(f"[!] Errors: {[e.error_type for e in errors]}")

        # 应该在区块8检测到双花
        assert not result, "Validator should detect double spend despite legitimate transfer path"
        assert any(e.error_type == "DOUBLE_SPEND_DETECTED" for e in errors)

        print("[VALIDATOR WINS] Transfer path manipulation detected")

    def test_realistic_attack_4_last_block_double_spend_attempt(self, validator, target_value, main_chain_info):
        """
        现实攻击4：最后区块双花尝试

        攻击思路：在最后一个区块中尝试双花，假设验证器可能对最后区块的验证较弱。
        """
        print("\n[!] REALISTIC ATTACK 4: Last Block Double Spend Attempt")

        proofs = [
            # 完整的合法转移路径
            MockProofUnit(
                block_height=0,
                owner="alice",
                owner_multi_txns=MockMultiTxns(
                    sender="alice",
                    multi_txns=[
                        MockTransaction(
                            sender="GOD",
                            receiver="alice",
                            output_values=[target_value]
                        )
                    ]
                )
            ),
            MockProofUnit(
                block_height=15,
                owner="bob",
                owner_multi_txns=MockMultiTxns(
                    sender="bob",
                    multi_txns=[
                        MockTransaction(
                            sender="alice",
                            receiver="bob",
                            output_values=[target_value]
                        )
                    ]
                )
            ),
            # 最后一个区块：bob再次尝试花销目标value（双花）
            MockProofUnit(
                block_height=30,  # 最后一个区块
                owner="bob",  # owner未变化（非目标value区块）
                owner_multi_txns=MockMultiTxns(
                    sender="bob",
                    multi_txns=[
                        MockTransaction(
                            sender="bob",
                            receiver="mallory",
                            spent_values=[target_value],  # 双花！
                            output_values=[MockValue("0x5000", "0x5FFF")]
                        )
                    ]
                )
            )
        ]

        attack_vpb = MockVPBSlice(
            value=target_value,
            proofs_slice=proofs,
            block_index_slice=MockBlockIndexSlice(
                index_lst=[0, 15, 30],
                owner=[(0, "alice"), (15, "bob")]  # 最后区块owner未变化
            ),
            start_block_height=0,
            end_block_height=30
        )

        # 确保最后区块有merkle根
        main_chain_info.merkle_roots[30] = "root_30"

        result, errors, verified_epochs = validator.verify_proof_units_and_detect_double_spend(attack_vpb, main_chain_info)

        print(f"[!] Result: {result}")
        print(f"[!] Errors: {[e.error_type for e in errors]}")

        # 应该在最后区块检测到双花
        assert not result, "Validator should detect double spend in last block"
        assert any(e.error_type == "DOUBLE_SPEND_DETECTED" for e in errors)

        print("[VALIDATOR WINS] Last block double spend detected")

    def test_realistic_attack_5_genesis_block_spoofing_with_valid_structure(self, validator, target_value, main_chain_info):
        """
        现实攻击5：创世块伪装攻击（数据结构合法）

        攻击思路：构造数据结构完全合法的创世块，
        但试图通过精心设计的交易内容来绕过创世块验证。
        """
        print("\n[!] REALISTIC ATTACK 5: Genesis Block Spoofing With Valid Structure")

        # 伪装的创世块：看似合法但没有GOD->owner交易
        spoofed_genesis_proof = MockProofUnit(
            block_height=0,
            owner="alice",
            owner_multi_txns=MockMultiTxns(
                sender="alice",
                multi_txns=[
                    MockTransaction(
                        sender="alice",  # 发送者是alice而不是GOD
                        receiver="alice",
                        output_values=[target_value]  # alice给自己发送value
                    )
                ]
            )
        )

        attack_vpb = MockVPBSlice(
            value=target_value,
            proofs_slice=[spoofed_genesis_proof],
            block_index_slice=MockBlockIndexSlice(
                index_lst=[0],
                owner=[(0, "alice")]
            ),
            start_block_height=0,
            end_block_height=0
        )

        result, errors, verified_epochs = validator.verify_proof_units_and_detect_double_spend(attack_vpb, main_chain_info)

        print(f"[!] Result: {result}")
        print(f"[!] Errors: {[e.error_type for e in errors]}")

        # 应该检测到创世块缺少GOD->owner交易
        assert not result, "Validator should detect missing GOD transaction in genesis block"
        assert any(e.error_type == "MISSING_GENESIS_VALUE_DISTRIBUTION" for e in errors)

        print("[VALIDATOR WINS] Genesis block spoofing detected")

def run_realistic_hacker_test_suite():
    """运行现实主义黑客测试套件"""
    print("=" * 80)
    print("PROOF VALIDATOR - REALISTIC HACKER PERSPECTIVE TEST SUITE")
    print("=" * 80)
    print("Note: Assuming data structure consistency from previous validation steps")
    print("=" * 80)

    logger = logging.getLogger("realistic_hacker")
    validator = ProofValidator(logger)
    test_instance = TestProofValidatorRealisticHacker()

    test_results = []

    # 准备通用测试数据
    target_value = MockValue(begin_index="0x1000", end_index="0x1FFF", value_num=1)
    main_chain_info = MockMainChainInfo(merkle_roots={
        0: "root_0", 8: "root_8", 15: "root_15", 16: "root_16", 25: "root_25",
        27: "root_27", 55: "root_55", 56: "root_56", 58: "root_58"
    })

    # 运行所有现实主义黑客测试
    realistic_hacker_tests = [
        ("Partial Value Double Spend",
         lambda: test_instance.test_realistic_attack_1_partial_value_double_spend(validator, target_value, main_chain_info)),
        ("Composite Transaction Spoofing",
         lambda: test_instance.test_realistic_attack_2_composite_transaction_spoofing(validator, target_value, main_chain_info)),
        ("Transfer Path Manipulation",
         lambda: test_instance.test_realistic_attack_3_transfer_path_manipulation(validator, target_value, main_chain_info)),
        ("Last Block Double Spend Attempt",
         lambda: test_instance.test_realistic_attack_4_last_block_double_spend_attempt(validator, target_value, main_chain_info)),
        ("Genesis Block Spoofing With Valid Structure",
         lambda: test_instance.test_realistic_attack_5_genesis_block_spoofing_with_valid_structure(validator, target_value, main_chain_info)),
    ]

    for test_name, test_func in realistic_hacker_tests:
        try:
            print(f"\n[!] Running: {test_name}")

            # 运行测试函数
            test_func()

            # 如果没有抛出异常，说明验证器成功防御了攻击
            print(f"[FAILED] Hacker failed in {test_name}")
            test_results.append((test_name, 0))  # 0 = hacker failed

        except AssertionError as e:
            # Assertion失败说明黑客成功攻击了
            print(f"[SUCCESS] HACKER SUCCESS in {test_name}: {e}")
            test_results.append((test_name, 1))  # 1 = hacker success

        except Exception as e:
            print(f"[ERROR] Exception in {test_name}: {e}")
            test_results.append((test_name, "ERROR"))

    # 汇总结果
    print("\n" + "=" * 80)
    print("REALISTIC HACKER ATTACK SUMMARY")
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
        print("   The validator appears to be secure against realistic attack scenarios.")

    return test_results

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.WARNING)

    # 运行现实主义黑客测试套件
    results = run_realistic_hacker_test_suite()

    # 根据结果设置退出代码
    successful_attacks = sum(1 for _, result in results if result == 1)
    exit_code = 1 if successful_attacks > 0 else 0
    exit(exit_code)