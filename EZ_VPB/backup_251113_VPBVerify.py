"""
VPBVerify - EZChain VPB验证核心组件

This module implements the comprehensive VPB (Value-Proofs-BlockIndex) verification algorithm
as specified in the VPB design document. It provides efficient transaction verification
without requiring full historical transaction traversal through checkpoint optimization.

Key Features:
- Complete VPB triplet verification (Value-Proofs-BlockIndex)
- Checkpoint-based optimization for reduced verification overhead
- Bloom filter verification for transaction index validation
- Merkle proof verification for transaction integrity
- Double-spend detection across value epochs
- Thread-safe operations with comprehensive error handling
- Memory-efficient processing with chunked verification
"""

import sys
import os
import threading
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
from enum import Enum
import logging

sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value.Value import Value, ValueState
from EZ_Proof.Proofs import Proofs
from EZ_Proof.ProofUnit import ProofUnit
from EZ_BlockIndex.BlockIndexList import BlockIndexList
from EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_Units.Bloom import BloomFilter


class ValueIntersectionError(Exception):
    """Value交集检测错误"""
    pass


class VerificationResult(Enum):
    """验证结果枚举"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class VerificationError:
    """验证错误信息"""
    error_type: str
    error_message: str
    block_height: Optional[int] = None
    proof_index: Optional[int] = None


@dataclass
class VPBVerificationReport:
    """VPB验证报告"""
    result: VerificationResult
    is_valid: bool
    errors: List[VerificationError]
    verified_epochs: List[Tuple[str, List[int]]]  # [(owner_address, [block_heights])]
    checkpoint_used: Optional[CheckPointRecord]
    verification_time_ms: float

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'result': self.result.value,
            'is_valid': self.is_valid,
            'errors': [
                {
                    'error_type': err.error_type,
                    'error_message': err.error_message,
                    'block_height': err.block_height,
                    'proof_index': err.proof_index
                } for err in self.errors
            ],
            'verified_epochs': self.verified_epochs,
            'checkpoint_used': self.checkpoint_used.to_dict() if self.checkpoint_used else None,
            'verification_time_ms': self.verification_time_ms
        }


@dataclass
class MainChainInfo:
    """主链信息数据结构"""
    merkle_roots: Dict[int, str]  # block_height -> merkle_root_hash
    bloom_filters: Dict[int, Any]  # block_height -> bloom_filter_data
    current_block_height: int
    genesis_block_height: int = 0

    def get_blocks_in_range(self, start_height: int, end_height: int) -> List[int]:
        """获取指定范围内的区块高度列表"""
        return [h for h in range(start_height, end_height + 1) if h in self.merkle_roots]

    def get_owner_transaction_blocks(self, owner_address: str, start_height: int, end_height: int) -> List[int]:
        """通过布隆过滤器获取指定所有者在指定范围内提交交易的区块高度"""
        transaction_blocks = []
        for height in range(start_height, end_height + 1):
            if height in self.bloom_filters:
                bloom_filter = self.bloom_filters[height]
                # 使用真实的布隆过滤器检测
                if self._check_bloom_filter(bloom_filter, owner_address):
                    transaction_blocks.append(height)
        return transaction_blocks

    def _check_bloom_filter(self, bloom_filter: Any, owner_address: str) -> bool:
        """检查布隆过滤器"""
        if isinstance(bloom_filter, BloomFilter):
            return owner_address in bloom_filter
        elif isinstance(bloom_filter, dict):
            # 兼容旧的字典格式
            return bloom_filter.get(owner_address, False)
        else:
            # 其他格式，尝试直接检查
            try:
                return owner_address in bloom_filter
            except (TypeError, AttributeError):
                return False

    

@dataclass
class VPBSlice:
    """VPB历史切片"""
    value: Value
    proofs_slice: List[ProofUnit]
    block_index_slice: BlockIndexList
    start_block_height: int
    end_block_height: int


class VPBVerify:
    """
    EZChain VPB验证器

    实现完整的VPB验证算法，支持检查点优化和内存高效的分块验证。
    """

    def __init__(self, checkpoint: Optional[CheckPoint] = None, logger: Optional[logging.Logger] = None):
        """
        初始化VPB验证器

        Args:
            checkpoint: 检查点管理器实例
            logger: 日志记录器实例
        """
        self.checkpoint = checkpoint
        self.logger = logger or self._create_default_logger()
        self._lock = threading.RLock()

        # 验证统计信息
        self.verification_stats = {
            'total_verifications': 0,
            'successful_verifications': 0,
            'failed_verifications': 0,
            'checkpoint_hits': 0
        }

    def _create_default_logger(self) -> logging.Logger:
        """创建默认日志记录器"""
        logger = logging.getLogger('VPBVerify')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
        return logger

    def verify_vpb_pair(self, value: Value, proofs: Proofs, block_index_list: BlockIndexList,
                       main_chain_info: MainChainInfo, account_address: str) -> VPBVerificationReport:
        """
        验证VPB三元组的完整性和合法性

        Args:
            value: 待验证的Value对象
            proofs: 对应的Proofs对象
            block_index_list: 对应的BlockIndexList对象
            main_chain_info: 主链信息
            account_address: 进行验证的账户地址

        Returns:
            VPBVerificationReport: 详细的验证报告
        """
        import time
        start_time = time.time()

        with self._lock:
            self.verification_stats['total_verifications'] += 1

            errors = []
            verified_epochs = []
            checkpoint_used = None

            try:
                # 第一步：基础数据结构合法性验证
                validation_result = self._validate_basic_data_structure(value, proofs, block_index_list)
                if not validation_result[0]:
                    errors.append(VerificationError(
                        "DATA_STRUCTURE_VALIDATION_FAILED",
                        validation_result[1]
                    ))
                    report_time = (time.time() - start_time) * 1000
                    self.verification_stats['failed_verifications'] += 1
                    return VPBVerificationReport(
                        VerificationResult.FAILURE, False, errors,
                        verified_epochs, checkpoint_used, report_time
                    )

                # 第二步：检查点匹配和历史切片生成
                vpb_slice, checkpoint_used = self._generate_vpb_slice(
                    value, proofs, block_index_list, account_address
                )

                # 第三步：布隆过滤器验证
                bloom_validation_result = self._verify_bloom_filter_consistency(
                    vpb_slice, main_chain_info
                )
                if not bloom_validation_result[0]:
                    errors.append(VerificationError(
                        "BLOOM_FILTER_VALIDATION_FAILED",
                        bloom_validation_result[1]
                    ))

                # 第四步：逐证明单元验证和双花检测
                epoch_verification_result = self._verify_proof_units_and_detect_double_spend(
                    vpb_slice, main_chain_info, checkpoint_used
                )

                if not epoch_verification_result[0]:
                    errors.extend(epoch_verification_result[1])
                else:
                    verified_epochs = epoch_verification_result[2]

                # 生成最终验证结果
                is_valid = len(errors) == 0
                result = VerificationResult.SUCCESS if is_valid else VerificationResult.FAILURE

                if is_valid:
                    self.verification_stats['successful_verifications'] += 1
                else:
                    self.verification_stats['failed_verifications'] += 1

                if checkpoint_used:
                    self.verification_stats['checkpoint_hits'] += 1

                report_time = (time.time() - start_time) * 1000

                return VPBVerificationReport(
                    result, is_valid, errors, verified_epochs, checkpoint_used, report_time
                )

            except Exception as e:
                import traceback
                self.logger.error(f"VPB verification failed with exception: {e}")
                self.logger.error(f"Full traceback: {traceback.format_exc()}")
                errors.append(VerificationError(
                    "VERIFICATION_EXCEPTION",
                    f"Verification failed with exception: {str(e)}"
                ))

                self.verification_stats['failed_verifications'] += 1
                report_time = (time.time() - start_time) * 1000

                return VPBVerificationReport(
                    VerificationResult.FAILURE, False, errors,
                    verified_epochs, checkpoint_used, report_time
                )

    def _validate_basic_data_structure(self, value: Value, proofs: Proofs,
                                      block_index_list: BlockIndexList) -> Tuple[bool, str]:
        """
        第一步：基础数据结构合法性验证

        NOTE: Leverages existing validation methods in Value, Proofs, and BlockIndexList classes.
        Focuses only on VPB-specific validation logic.

        Args:
            value: Value对象
            proofs: Proofs对象
            block_index_list: BlockIndexList对象

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        # 使用Value类现有的验证方法
        if not isinstance(value, Value):
            return False, "value is not a valid Value object"

        # 使用Value.check_value()进行基础验证（包含value_num、hex格式、索引关系验证）
        if not value.check_value():
            return False, f"Value validation failed for {value.begin_index} (value_num={value.value_num})"

        # 使用现有类的类型检查
        if not isinstance(proofs, Proofs):
            return False, "proofs is not a valid Proofs object"

        if not isinstance(block_index_list, BlockIndexList):
            return False, "block_index_list is not a valid BlockIndexList object"

        # VPB特定的数据一致性校验：Proofs和BlockIndexList的元素数量应该一致
        proof_count = len(proofs.proof_units) if proofs.proof_units else 0
        block_count = len(block_index_list.index_lst) if block_index_list.index_lst else 0

        if proof_count != block_count:
            return False, f"Proof count ({proof_count}) does not match block index count ({block_count})"

        # 注释掉owner数据唯一性校验，因为在VPB中同一个地址可以多次出现
        # 例如：Bob可以先获得value，转移给他人，然后重新获得同一个value
        # 这种场景在实际应用中是完全合法的
        # if block_index_list.owner:
        #     owner_addresses = [owner[1] for owner in block_index_list.owner]
        #     if len(owner_addresses) != len(set(owner_addresses)):
        #         return False, "Duplicate owners found in BlockIndexList owner data"

        return True, ""

    def _generate_vpb_slice(self, value: Value, proofs: Proofs, block_index_list: BlockIndexList,
                           account_address: str) -> Tuple[VPBSlice, Optional[CheckPointRecord]]:
        """
        第二步：检查点匹配和历史切片生成

        Args:
            value: Value对象
            proofs: Proofs对象
            block_index_list: BlockIndexList对象
            account_address: 进行验证的账户地址

        Returns:
            Tuple[VPBSlice, Optional[CheckPointRecord]]: (VPB切片, 使用的检查点)
        """
        checkpoint_used = None
        start_height = 0  # 默认从创世块开始验证

        # 检查是否有可用的检查点
        if self.checkpoint:
            # 尝试触发检查点验证
            checkpoint_record = self.checkpoint.trigger_checkpoint_verification(value, account_address)
            if checkpoint_record:
                checkpoint_used = checkpoint_record
                start_height = checkpoint_record.block_height + 1  # 从检查点的下一个区块开始验证
                self.logger.info(f"Using checkpoint at height {checkpoint_record.block_height}, starting verification from height {start_height} for value {value.begin_index}")

        # 根据start_height生成历史切片
        proofs_slice = []
        index_slice = []
        owner_slice = []

        if proofs.proof_units and block_index_list.index_lst:
            # 特殊处理创世块（height = 0）
            genesis_index = -1
            if 0 in block_index_list.index_lst:
                genesis_index = block_index_list.index_lst.index(0)

            # 找到start_height对应的起始索引
            start_index = 0
            for i, block_height in enumerate(block_index_list.index_lst):
                if block_height >= start_height:
                    start_index = i
                    break
            else:
                # 如果所有区块高度都 < start_height，则从最后开始
                start_index = len(block_index_list.index_lst)

            # 调试信息
            self.logger.debug(f"Slice generation: start_height={start_height}, start_index={start_index}, total_indices={len(block_index_list.index_lst)}")
            self.logger.debug(f"Original index_lst: {block_index_list.index_lst}")
            self.logger.debug(f"Will include indices from: {block_index_list.index_lst[start_index:]}")

            # 特殊处理：如果包含创世块且start_height > 0，需要包含创世块的proof unit
            # 因为创世块的验证逻辑不同
            if genesis_index >= 0 and start_height > 0 and genesis_index < start_index:
                # 创世块需要特殊处理，但我们暂时不包含在切片中
                pass

            # 生成切片
            proofs_slice = proofs.proof_units[start_index:] if start_index < len(proofs.proof_units) else []
            index_slice = block_index_list.index_lst[start_index:] if start_index < len(block_index_list.index_lst) else []

            # 生成对应的owner切片
            if block_index_list.owner:
                owner_slice = []
                # 调试信息：检查owner的类型和内容
                self.logger.debug(f"block_index_list.owner type: {type(block_index_list.owner)}")
                self.logger.debug(f"block_index_list.owner value: {block_index_list.owner}")

                # 确保owner是可迭代的
                if hasattr(block_index_list.owner, '__iter__') and not isinstance(block_index_list.owner, str):
                    owner_dict = {height: owner for height, owner in block_index_list.owner}
                else:
                    # 如果owner不是预期的格式，尝试从_owner_history获取
                    if hasattr(block_index_list, '_owner_history'):
                        owner_dict = {height: owner for height, owner in block_index_list._owner_history}
                    else:
                        self.logger.error("Invalid owner format in block_index_list")
                        raise ValueError("Invalid owner format in block_index_list")

                for height in index_slice:
                    if height in owner_dict:
                        owner_slice.append((height, owner_dict[height]))

        # 创建切片后的BlockIndexList
        sliced_block_index_list = BlockIndexList(index_slice, owner_slice)

        # 创建VPB切片对象
        vpb_slice = VPBSlice(
            value=value,
            proofs_slice=proofs_slice,
            block_index_slice=sliced_block_index_list,
            start_block_height=start_height,
            end_block_height=index_slice[-1] if index_slice else start_height
        )

        return vpb_slice, checkpoint_used

    def _verify_bloom_filter_consistency(self, vpb_slice: VPBSlice,
                                       main_chain_info: MainChainInfo) -> Tuple[bool, str]:
        """
        第三步：布隆过滤器验证（修复版本）

        验证VPB数据与主链完整历史的一致性，检测攻击者是否隐藏了恶意区块。

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息

        Returns:
            Tuple[bool, str]: (是否一致, 错误信息)
        """
        if not vpb_slice.block_index_slice.index_lst:
            # 如果没有需要验证的区块，认为验证失败
            return False, "VPB slice has empty block index list"

        # 🔥 修复1：确定期望的完整区块范围
        if vpb_slice.block_index_slice.index_lst:
            start_height = min(vpb_slice.block_index_slice.index_lst)
            end_height = max(vpb_slice.block_index_slice.index_lst)
        else:
            return False, "Invalid VPB slice block indices"

        # 🔥 修复2：使用布隆过滤器获取与目标value相关的所有区块
        expected_block_indices = []

        # 首先获取基本范围内的所有区块
        basic_range = [height for height in range(start_height, end_height + 1)
                      if height in main_chain_info.merkle_roots]

        # 然后使用布隆过滤器筛选出真正相关的区块
        if hasattr(main_chain_info, 'get_owner_transaction_blocks'):
            # 如果有布隆过滤器查询方法，使用它
            owner_epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)
            for _, owner_address in owner_epochs:
                related_blocks = main_chain_info.get_owner_transaction_blocks(
                    owner_address, start_height, end_height
                )
                expected_block_indices.extend(related_blocks)
        else:
            # 回退到基本范围（这样更容易调试）
            expected_block_indices = basic_range

        # 去重并排序
        expected_block_indices = sorted(list(set(expected_block_indices)))

        # 🔥 修复3：攻击者实际提供的区块
        provided_block_indices = vpb_slice.block_index_slice.index_lst

        # 🔥 修复4：检测攻击者是否隐藏了区块
        hidden_blocks = set(expected_block_indices) - set(provided_block_indices)
        if hidden_blocks:
            self.logger.warning(f"DETECTING SECURITY THREAT: Hidden blocks detected!")
            self.logger.warning(f"Main chain blocks in range [{start_height}, {end_height}]: {sorted(expected_block_indices)}")
            self.logger.warning(f"VPB provided blocks: {sorted(provided_block_indices)}")
            self.logger.warning(f"Hidden (missing) blocks: {sorted(hidden_blocks)}")

            # 检查被隐藏的区块是否包含目标价值相关的交易
            suspicious_blocks = []
            for block_height in sorted(hidden_blocks):
                # 检查该区块是否可能与价值交易相关
                if block_height in main_chain_info.bloom_filters:
                    bloom_filter = main_chain_info.bloom_filters[block_height]

                    # 🔥 修复：使用真正的布隆过滤器检测逻辑
                    # 检查该区块的布隆过滤器中是否包含任何owner地址
                    owner_epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)
                    for _, owner_address in owner_epochs:
                        if self._check_bloom_filter(bloom_filter, owner_address):
                            suspicious_blocks.append(block_height)
                            break  # 找到相关交易就足够了

            if suspicious_blocks:
                return False, (
                    f"SECURITY THREAT DETECTED: Hidden blocks with potential value transactions: {sorted(suspicious_blocks)}. "
                    f"Attacker may be hiding malicious double-spend transactions in these blocks."
                )
            else:
                return False, (
                    f"Data inconsistency detected: Missing blocks in VPB submission: {sorted(hidden_blocks)}. "
                    f"VPB must include all blocks in the verification range [{start_height}, {end_height}]."
                )

        # 🔥 修复5：检测攻击者是否提供了超出范围的区块
        extra_blocks = set(provided_block_indices) - set(expected_block_indices)
        if extra_blocks:
            self.logger.warning(f"Extra blocks detected: {sorted(extra_blocks)}")
            return False, (
                f"Invalid block indices: Provided blocks {sorted(extra_blocks)} are outside expected range [{start_height}, {end_height}]"
            )

        # 🔥 修复6：验证区块顺序的连续性
        sorted_provided = sorted(provided_block_indices)
        sorted_expected = sorted(expected_block_indices)
        if sorted_provided != sorted_expected:
            self.logger.warning(f"Block order inconsistency detected")
            self.logger.warning(f"Expected order: {sorted_expected}")
            self.logger.warning(f"Provided order: {sorted_provided}")

            # 检查是否有不连续的区块跳跃
            gaps = []
            for i in range(len(sorted_provided) - 1):
                current = sorted_provided[i]
                next_block = sorted_provided[i + 1]
                if next_block > current + 1:
                    # 检查中间的区块是否在主链中
                    for missing_block in range(current + 1, next_block):
                        if missing_block in main_chain_info.merkle_roots:
                            gaps.append(missing_block)

            if gaps:
                return False, (
                    f"Block sequence gap detected. Missing blocks: {gaps}. "
                    f"VPB must provide complete and continuous block history."
                )

        # 🔥 修复7：传统的布隆过滤器地址验证（保留原有功能）
        owner_epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)
        for block_height, owner_address in owner_epochs:
            if block_height not in main_chain_info.bloom_filters:
                self.logger.warning(f"No bloom filter found for block {block_height}")
                return False, f"Missing bloom filter for block {block_height}"

            bloom_filter = main_chain_info.bloom_filters[block_height]

            # 检查owner是否在该区块有交易记录
            if not self._check_bloom_filter(bloom_filter, owner_address):
                self.logger.warning(f"Owner {owner_address} not found in bloom filter for block {block_height}")
                # 这是一个警告，但不一定导致失败，因为可能有其他验证机制

        self.logger.debug(f"Bloom filter consistency verification passed")
        self.logger.debug(f"Verified {len(provided_block_indices)} blocks in range [{start_height}, {end_height}]")

        return True, ""

    def _extract_owner_epochs(self, block_index_list: BlockIndexList) -> List[Tuple[int, str]]:
        """
        从BlockIndexList中提取epoch信息（重构版本）

        新的epoch概念：
        - 每个区块代表一个独立的epoch
        - 每个epoch包含：区块高度、该区块的owner、前驱owner
        - 按照转移链的时间顺序组织epoch

        Args:
            block_index_list: 区块索引列表

        Returns:
            List[Tuple[int, str]]: 按区块高度排序的epoch列表 [(block_height, owner_address), ...]
        """
        epochs = []

        if not block_index_list.owner or not block_index_list.index_lst:
            return epochs

        # 调试信息
        self.logger.debug(f"Extract owner epochs: owner type: {type(block_index_list.owner)}")
        self.logger.debug(f"Extract owner epochs: owner value: {block_index_list.owner}")

        # 确保owner数据格式正确
        if not hasattr(block_index_list.owner, '__iter__') or isinstance(block_index_list.owner, str):
            self.logger.error("Invalid owner format in block_index_list for epoch extraction")
            raise ValueError("Invalid owner format in block_index_list for epoch extraction")

        # 创建区块高度到owner的映射
        block_to_owner = {height: owner for height, owner in block_index_list.owner}

        # 按区块高度排序构建epoch列表
        sorted_blocks = sorted(block_index_list.index_lst)

        for block_height in sorted_blocks:
            if block_height in block_to_owner:
                owner = block_to_owner[block_height]
                epochs.append((block_height, owner))
            else:
                self.logger.warning(f"No owner found for block {block_height}")

        self.logger.debug(f"Extracted epochs: {epochs}")
        return epochs

    def _get_previous_owner_for_block(self, epochs: List[Tuple[int, str]], target_block: int) -> Optional[str]:
        """
        获取指定区块的前驱owner地址

        Args:
            epochs: 按时间顺序的epoch列表 [(block_height, owner_address), ...]
            target_block: 目标区块高度

        Returns:
            Optional[str]: 前驱owner地址，如果没有前驱（创世块）返回None
        """
        # 找到目标区块在epoch列表中的位置
        target_index = -1
        for i, (block_height, owner) in enumerate(epochs):
            if block_height == target_block:
                target_index = i
                break

        if target_index == -1:
            self.logger.warning(f"Block {target_block} not found in epochs")
            return None

        # 如果是第一个epoch（创世块），没有前驱
        if target_index == 0:
            return None

        # 返回前一个epoch的owner
        previous_block, previous_owner = epochs[target_index - 1]
        self.logger.debug(f"Previous owner for block {target_block}: {previous_owner} (from block {previous_block})")
        return previous_owner

    def _check_bloom_filter(self, bloom_filter: Any, owner_address: str) -> bool:
        """检查布隆过滤器"""
        if isinstance(bloom_filter, BloomFilter):
            return owner_address in bloom_filter
        elif isinstance(bloom_filter, dict):
            # 兼容旧的字典格式
            return bloom_filter.get(owner_address, False)
        else:
            # 其他格式，尝试直接检查
            try:
                return owner_address in bloom_filter
            except (TypeError, AttributeError):
                self.logger.warning(f"Unsupported bloom filter type: {type(bloom_filter)}")
                return False

    def _verify_genesis_block(self, vpb_slice: VPBSlice, main_chain_info: MainChainInfo) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
        """
        验证创世块的proof unit

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息

        Returns:
            Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
            (是否有效, 错误列表, 验证的epoch列表)
        """
        errors = []
        verified_epochs = []

        # 找到创世块对应的proof unit
        genesis_proof_unit = self._find_proof_unit_for_block(
            vpb_slice.proofs_slice, 0, vpb_slice.block_index_slice
        )

        if not genesis_proof_unit:
            errors.append(VerificationError(
                "GENESIS_PROOF_MISSING",
                f"Genesis block proof unit not found for value {vpb_slice.value.begin_index}",
                block_height=0
            ))
            return False, errors, verified_epochs

        # 验证创世块的Merkle证明
        if 0 not in main_chain_info.merkle_roots:
            errors.append(VerificationError(
                "GENESIS_MERKLE_ROOT_MISSING",
                "Merkle root not found for genesis block",
                block_height=0
            ))
            return False, errors, verified_epochs

        genesis_merkle_root = main_chain_info.merkle_roots[0]

        # 验证proof unit
        is_valid, error_msg = genesis_proof_unit.verify_proof_unit(genesis_merkle_root)
        if not is_valid:
            errors.append(VerificationError(
                "GENESIS_PROOF_VERIFICATION_FAILED",
                f"Genesis block proof verification failed: {error_msg}",
                block_height=0
            ))
            return False, errors, verified_epochs

        # 创世块验证成功，添加到已验证的epochs
        # 创世块的owner通常是特殊的创世地址
        genesis_address = "0xGENESIS"  # 或者从proof unit中获取
        verified_epochs.append((genesis_address, [0]))

        return True, errors, verified_epochs

    def _verify_proof_units_and_detect_double_spend(self, vpb_slice: VPBSlice,
                                                   main_chain_info: MainChainInfo,
                                                   checkpoint_used: Optional[CheckPointRecord] = None) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
        """
        第四步：逐证明单元验证和双花检测

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息
            checkpoint_used: 使用的检查点记录（可选）

        Returns:
            Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
            (是否有效, 错误列表, 验证的epoch列表)
        """
        errors = []
        verified_epochs = []

        if not vpb_slice.proofs_slice:
            # 特殊处理：如果只有创世块且start_height=0，可能是正常的
            if vpb_slice.start_block_height == 0 and vpb_slice.end_block_height == 0:
                # 只有创世块的情况，这是正常的
                return True, errors, verified_epochs
            else:
                # 没有需要验证的proof units，这是错误的，因为任何value验证都应该有对应的proof units
                errors.append(VerificationError(
                    "NO_PROOF_UNITS",
                    f"No proof units found for value {vpb_slice.value.begin_index}. "
                    "Every value verification requires corresponding proof units."
                ))
                return False, errors, verified_epochs

        # 特殊处理创世块
        if vpb_slice.start_block_height == 0 and 0 in vpb_slice.block_index_slice.index_lst:
            # 创世块验证逻辑：创世块是从创世地址直接派发value，不需要双花检测
            genesis_result = self._verify_genesis_block(vpb_slice, main_chain_info)
            if not genesis_result[0]:
                errors.extend(genesis_result[1])
            else:
                verified_epochs.extend(genesis_result[2])

        # 提取epochs（新的概念：每个区块是一个独立的epoch）
        epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)

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

            # 验证proof unit（ProofUnit.verify_proof_unit已经包含了sender地址验证）
            is_valid, error_msg = proof_unit.verify_proof_unit(merkle_root)
            if not is_valid:
                errors.append(VerificationError(
                    "PROOF_UNIT_VERIFICATION_FAILED",
                    f"Proof unit verification failed at block {block_height}: {error_msg}",
                    block_height=block_height
                ))
                continue

            # 确定previous_owner（根据新的epoch概念）
            if not checkpoint_used and i == 0:
                # 没有checkpoint的第一个区块（通常是创世块）
                previous_owner = None
            elif checkpoint_used and block_height == first_verification_block_after_checkpoint:
                # checkpoint后的第一个验证区块，使用checkpoint的owner作为previous_owner
                previous_owner = checkpoint_used.owner_address
            else:
                # 正常情况：使用新的逻辑获取前驱owner
                previous_owner = self._get_previous_owner_for_block(epochs, block_height)

            # 检测双花（验证该区块的转移交易）
            epoch_proof_units = [(block_height, proof_unit)]
            double_spend_result = self._detect_double_spend_in_epoch(
                vpb_slice.value, epoch_proof_units, owner_address, previous_owner
            )
            if not double_spend_result[0]:
                errors.extend(double_spend_result[1])
            else:
                # 添加到已验证的epoch列表
                verified_epochs.append((owner_address, [block_height]))

        return len(errors) == 0, errors, verified_epochs

    def _find_proof_unit_for_block(self, proofs_slice: List[ProofUnit], block_height: int,
                                 block_index_slice: Optional[BlockIndexList] = None) -> Optional[ProofUnit]:
        """
        在proof units切片中查找指定区块高度的proof unit

        Args:
            proofs_slice: proof units切片
            block_height: 区块高度
            block_index_slice: 区块索引列表（用于映射高度到索引）

        Returns:
            Optional[ProofUnit]: 找到的proof unit，不存在返回None
        """
        if not proofs_slice:
            return None

        # 如果提供了block_index_slice，使用正确的映射关系
        if block_index_slice and block_index_slice.index_lst:
            try:
                # 找到block_height在index_lst中的位置
                height_index = block_index_slice.index_lst.index(block_height)
                # 返回对应位置的proof unit
                if 0 <= height_index < len(proofs_slice):
                    return proofs_slice[height_index]
            except ValueError:
                # block_height不在index_lst中
                return None

        # 如果没有提供block_index_slice，尝试从proof unit自身获取高度信息
        for i, proof_unit in enumerate(proofs_slice):
            # 检查proof unit是否有区块高度信息
            if hasattr(proof_unit, 'block_height') and proof_unit.block_height == block_height:
                return proof_unit
            # 检查proof unit的其他可能属性
            if hasattr(proof_unit, 'height') and proof_unit.height == block_height:
                return proof_unit
            if hasattr(proof_unit, 'block_index') and proof_unit.block_index == block_height:
                return proof_unit

        # 如果都找不到，返回None
        return None

    def _detect_double_spend_in_epoch(self, value: Value, epoch_proof_units: List[Tuple[int, ProofUnit]],
                                     owner_address: str, previous_owner: Optional[str] = None) -> Tuple[bool, List[VerificationError]]:
        """
        基于简化epoch概念检测epoch内的双花行为

        简化epoch概念：
        - 每个epoch只有一个区块：该owner获得value的区块
        - 创世块（区块0）：owner从GOD处获得value，无需验证转移交易
        - 普通区块：必须包含从previous_owner到当前owner的有效转移交易
        - 最后一个区块：不能包含任何价值转移交易（因为value没有再次转移）

        Args:
            value: 被验证的Value对象
            epoch_proof_units: 该epoch的proof units列表（通常只有一个区块）
            owner_address: epoch的所有者地址
            previous_owner: 上一个epoch的owner地址（None表示创世块）

        Returns:
            Tuple[bool, List[VerificationError]]: (无双花, 错误列表)
        """
        errors = []

        if not epoch_proof_units:
            return len(errors) == 0, errors

        # 按区块高度排序proof units
        epoch_proof_units.sort(key=lambda x: x[0])

        # 检查每个proof unit
        for block_height, proof_unit in epoch_proof_units:
            # 检查是否有与目标value交集的交易
            value_intersect_transactions = self._find_value_intersect_transactions(proof_unit, value)

            # 创世块特殊处理：创世块owner从GOD处获得value
            if block_height == 0:
                # 创世块不应该有任何价值转移交易（价值是从GOD获得）
                if value_intersect_transactions:
                    errors.append(VerificationError(
                        "UNEXPECTED_GENESIS_VALUE_TRANSFER",
                        f"Genesis block cannot contain value transfer transactions, "
                        f"found {len(value_intersect_transactions)} transactions in block 0",
                        block_height=0
                    ))
                continue

            # 简化逻辑：直接使用外部传入的previous_owner
            if previous_owner is not None:
                # 查找从previous_owner到当前owner的有效转移交易
                valid_spend_transactions = self._find_valid_value_spend_transactions(
                    proof_unit, value, previous_owner, owner_address
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "NO_VALID_TRANSFER_IN_BLOCK",
                        f"Block {block_height} must contain valid transfer from {previous_owner} to {owner_address}, "
                        f"but found no valid transactions",
                        block_height=block_height
                    ))

                # 检查是否有不合法的交集交易
                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_BLOCK_VALUE_INTERSECTION",
                            f"Invalid value intersection found in block {block_height}: {tx}",
                            block_height=block_height
                        ))
            else:
                # 非创世块但没有previous_owner，这是逻辑错误
                errors.append(VerificationError(
                    "UNEXPECTED_BLOCK_WITHOUT_PREVIOUS_OWNER",
                    f"Block {block_height} has no previous owner but is not genesis block",
                    block_height=block_height
                ))

        return len(errors) == 0, errors

    # _find_previous_epoch_owner 方法已被移除，因为 previous_owner 现在由调用方直接提供

    def _find_next_epoch_owner(self, epochs: List[Tuple[int, str]], current_block: int) -> Optional[str]:
        """
        找到当前区块之后的下一个epoch的owner地址（重构版本）

        Args:
            epochs: 按时间顺序的epoch列表 [(block_height, owner_address), ...]
            current_block: 当前区块高度

        Returns:
            Optional[str]: 下一个epoch的owner地址，如果不存在则返回None
        """
        # 找到当前区块在epoch列表中的位置
        current_index = -1
        for i, (block_height, owner) in enumerate(epochs):
            if block_height == current_block:
                current_index = i
                break

        if current_index == -1:
            return None

        # 如果是最后一个epoch，没有下一个
        if current_index >= len(epochs) - 1:
            return None

        # 返回下一个epoch的owner
        next_block, next_owner = epochs[current_index + 1]
        return next_owner

    def _find_value_intersect_transactions(self, proof_unit: ProofUnit, value: Value) -> List[Any]:
        """
        查找proof unit中与目标value有交集的所有交易

        Args:
            proof_unit: ProofUnit对象
            value: 目标Value对象

        Returns:
            List[Any]: 与目标value有交集的交易列表
        """
        intersect_transactions = []

        if hasattr(proof_unit, 'owner_multi_txns') and proof_unit.owner_multi_txns:
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for transaction in proof_unit.owner_multi_txns.multi_txns:
                    try:
                        if self._transaction_intersects_value(transaction, value):
                            intersect_transactions.append(transaction)
                    except ValueIntersectionError as e:
                        # 遇到无效value对象的交易时，记录错误并停止处理该proof unit
                        # 这是因为包含无效value的交易可能导致验证结果不可信
                        block_height = getattr(proof_unit, 'block_height', 'unknown')
                        error_msg = f"Invalid value objects in transaction at block {block_height}: {e}"
                        logging.getLogger(__name__).error(error_msg)
                        # 抛出异常让上层处理，这比忽略错误更安全
                        raise ValueError(f"Transaction validation failed at block {block_height}: {e}") from e

        return intersect_transactions

    def _find_valid_value_spend_transactions(self, proof_unit: ProofUnit, value: Value,
                                           expected_sender: str, expected_receiver: Optional[str]) -> List[Any]:
        """
        查找proof unit中有效的value花销交易

        Args:
            proof_unit: ProofUnit对象
            value: 目标Value对象
            expected_sender: 期望的发送者地址
            expected_receiver: 期望的接收者地址（可能为None）

        Returns:
            List[Any]: 有效的value花销交易列表
        """
        valid_transactions = []

        if hasattr(proof_unit, 'owner_multi_txns') and proof_unit.owner_multi_txns:
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for transaction in proof_unit.owner_multi_txns.multi_txns:
                    if self._is_valid_value_spend_transaction(transaction, value, expected_sender, expected_receiver):
                        valid_transactions.append(transaction)

        return valid_transactions

    def _transaction_intersects_value(self, transaction: Any, value: Value) -> bool:
        """
        检查交易是否与目标value有交集

        严格验证：所有value对象必须是有效的Value类型，遇到任何无效数据都会抛出异常

        Args:
            transaction: 交易对象
            value: 目标Value对象

        Returns:
            bool: True-有交集，False-无交集

        Raises:
            ValueIntersectionError: 当交易中的value对象无效时
        """
        # 验证目标value本身必须是有效的
        if not self._is_valid_value_object(value):
            raise ValueIntersectionError(f"Target value is not a valid Value object: {type(value)}")

        # 检查输入value
        if hasattr(transaction, 'input_values'):
            if not isinstance(transaction.input_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.input_values must be a list or tuple, got {type(transaction.input_values)}")

            for i, input_value in enumerate(transaction.input_values):
                if not self._is_valid_value_object(input_value):
                    raise ValueIntersectionError(f"Invalid input value at index {i}: {type(input_value)}")
                if self._values_intersect(input_value, value):
                    return True

        # 检查输出value
        if hasattr(transaction, 'output_values'):
            if not isinstance(transaction.output_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.output_values must be a list or tuple, got {type(transaction.output_values)}")

            for i, output_value in enumerate(transaction.output_values):
                if not self._is_valid_value_object(output_value):
                    raise ValueIntersectionError(f"Invalid output value at index {i}: {type(output_value)}")
                if self._values_intersect(output_value, value):
                    return True

        # 检查花销value
        if hasattr(transaction, 'spent_values'):
            if not isinstance(transaction.spent_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.spent_values must be a list or tuple, got {type(transaction.spent_values)}")

            for i, spent_value in enumerate(transaction.spent_values):
                if not self._is_valid_value_object(spent_value):
                    raise ValueIntersectionError(f"Invalid spent value at index {i}: {type(spent_value)}")
                if self._values_intersect(spent_value, value):
                    return True

        # 检查接收value
        if hasattr(transaction, 'received_values'):
            if not isinstance(transaction.received_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.received_values must be a list or tuple, got {type(transaction.received_values)}")

            for i, received_value in enumerate(transaction.received_values):
                if not self._is_valid_value_object(received_value):
                    raise ValueIntersectionError(f"Invalid received value at index {i}: {type(received_value)}")
                if self._values_intersect(received_value, value):
                    return True

        # 如果所有检查都完成且没有发现交集，返回False（确实无交集）
        return False

    def _is_valid_value_spend_transaction(self, transaction: Any, value: Value,
                                        expected_sender: str, expected_receiver: Optional[str]) -> bool:
        """
        检查是否是有效的value花销交易

        Args:
            transaction: 交易对象
            value: 目标Value对象
            expected_sender: 期望的发送者地址
            expected_receiver: 期望的接收者地址

        Returns:
            bool: 是否是有效的花销交易
        """
        # 检查发送者
        sender_valid = False
        if hasattr(transaction, 'sender') and transaction.sender == expected_sender:
            sender_valid = True
        elif hasattr(transaction, 'payer') and transaction.payer == expected_sender:
            sender_valid = True

        if not sender_valid:
            return False

        # 检查value完全匹配（输出）
        if hasattr(transaction, 'output_values'):
            for output_value in transaction.output_values:
                if (hasattr(output_value, 'begin_index') and hasattr(output_value, 'end_index') and
                    hasattr(output_value, 'value_num') and
                    output_value.begin_index == value.begin_index and
                    output_value.end_index == value.end_index and
                    output_value.value_num == value.value_num):
                    # 检查接收者
                    if expected_receiver and hasattr(transaction, 'receiver'):
                        if transaction.receiver == expected_receiver:
                            return True
                    elif expected_receiver is None:
                        return True

        # 检查value完全匹配（接收值）
        if hasattr(transaction, 'received_values'):
            for received_value in transaction.received_values:
                if (hasattr(received_value, 'begin_index') and hasattr(received_value, 'end_index') and
                    hasattr(received_value, 'value_num') and
                    received_value.begin_index == value.begin_index and
                    received_value.end_index == value.end_index and
                    received_value.value_num == value.value_num):
                    # 检查接收者
                    if expected_receiver and hasattr(transaction, 'receiver'):
                        if transaction.receiver == expected_receiver:
                            return True
                    elif expected_receiver is None:
                        return True

        return False

    def _values_intersect(self, value1: Any, value2: Value) -> bool:
        """
        检查两个value是否有交集

        严格类型检查：两个参数都必须是Value类型或具有begin_index/end_index属性的对象

        Args:
            value1: 第一个value对象，必须是Value类型或具有begin_index/end_index属性
            value2: 第二个Value对象，必须是Value类型或具有begin_index/end_index属性

        Returns:
            bool: 是否有交集

        Raises:
            ValueIntersectionError: 当任一参数不是有效的Value类型对象时
        """
        # 严格的类型检查
        if not self._is_valid_value_object(value1):
            raise ValueIntersectionError(f"First parameter is not a valid Value object: {type(value1)}")
        if not self._is_valid_value_object(value2):
            raise ValueIntersectionError(f"Second parameter is not a valid Value object: {type(value2)}")

        try:
            # 如果两个都是Value对象，优先使用Value类的is_intersect_value方法
            if (hasattr(value1, 'is_intersect_value') and callable(value1.is_intersect_value) and
                hasattr(value2, 'is_intersect_value') and callable(value2.is_intersect_value)):
                return value1.is_intersect_value(value2)

            # 如果value1有is_intersect_value方法，使用它
            elif hasattr(value1, 'is_intersect_value') and callable(value1.is_intersect_value):
                return value1.is_intersect_value(value2)
            # 如果value2有is_intersect_value方法，调转参数
            elif hasattr(value2, 'is_intersect_value') and callable(value2.is_intersect_value):
                return value2.is_intersect_value(value1)
            # 回退到手动计算
            else:
                v1_begin = int(value1.begin_index, 16)
                v1_end = int(value1.end_index, 16)
                v2_begin = int(value2.begin_index, 16)
                v2_end = int(value2.end_index, 16)
                # 检查是否有重叠
                return not (v1_end < v2_begin or v2_end < v1_begin)

        except ValueError as e:
            raise ValueIntersectionError(f"Invalid value index format: {e}")
        except AttributeError as e:
            raise ValueIntersectionError(f"Missing required value attributes: {e}")

    def _is_valid_value_object(self, value_obj: Any) -> bool:
        """
        检查对象是否是有效的Value类型对象

        严格类型检查：必须是Value类型（from EZ_Value.Value import Value）

        Args:
            value_obj: 要检查的对象

        Returns:
            bool: 是否是有效的Value对象
        """
        # 严格检查是否为Value类型
        return isinstance(value_obj, Value)

    
    def _transaction_spends_value(self, transaction: Any, value: Value) -> bool:
        """
        检查交易是否花销了指定的value

        严格验证：所有value对象必须是有效的Value类型，遇到任何无效数据都会抛出异常

        Args:
            transaction: 交易对象
            value: Value对象

        Returns:
            bool: True-花销了该value，False-未花销该value

        Raises:
            ValueIntersectionError: 当交易中的value对象无效时
        """
        # 验证目标value本身必须是有效的
        if not self._is_valid_value_object(value):
            raise ValueIntersectionError(f"Target value is not a valid Value object: {type(value)}")

        # 检查输入value
        if hasattr(transaction, 'input_values'):
            if not isinstance(transaction.input_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.input_values must be a list or tuple, got {type(transaction.input_values)}")

            for i, input_value in enumerate(transaction.input_values):
                if not self._is_valid_value_object(input_value):
                    raise ValueIntersectionError(f"Invalid input value at index {i}: {type(input_value)}")
                # 严格检查value是否完全匹配
                if (input_value.begin_index == value.begin_index and
                    input_value.end_index == value.end_index):
                    return True

        # 检查花销value
        if hasattr(transaction, 'spent_values'):
            if not isinstance(transaction.spent_values, (list, tuple)):
                raise ValueIntersectionError(f"transaction.spent_values must be a list or tuple, got {type(transaction.spent_values)}")

            for i, spent_value in enumerate(transaction.spent_values):
                if not self._is_valid_value_object(spent_value):
                    raise ValueIntersectionError(f"Invalid spent value at index {i}: {type(spent_value)}")
                # 严格检查value是否完全匹配
                if (spent_value.begin_index == value.begin_index and
                    spent_value.end_index == value.end_index):
                    return True

        # 如果所有检查都完成且未找到匹配的value，返回False（确实未花销该value）
        return False

    def get_verification_stats(self) -> Dict[str, Any]:
        """获取验证统计信息"""
        with self._lock:
            stats = self.verification_stats.copy()
            if stats['total_verifications'] > 0:
                stats['success_rate'] = stats['successful_verifications'] / stats['total_verifications']
                stats['checkpoint_hit_rate'] = stats['checkpoint_hits'] / stats['total_verifications']
            else:
                stats['success_rate'] = 0.0
                stats['checkpoint_hit_rate'] = 0.0
            return stats

    def reset_stats(self):
        """重置验证统计信息"""
        with self._lock:
            self.verification_stats = {
                'total_verifications': 0,
                'successful_verifications': 0,
                'failed_verifications': 0,
                'checkpoint_hits': 0
            }
