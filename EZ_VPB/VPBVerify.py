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
                self.logger.warning(f"Unsupported bloom filter type: {type(bloom_filter)}")
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
                    vpb_slice, main_chain_info
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
                self.logger.error(f"VPB verification failed with exception: {e}")
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

        # VPB特定的owner数据唯一性校验
        if block_index_list.owner:
            owner_addresses = [owner[1] for owner in block_index_list.owner]
            if len(owner_addresses) != len(set(owner_addresses)):
                return False, "Duplicate owners found in BlockIndexList owner data"

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
                self.logger.info(f"Using checkpoint at height {checkpoint_record.block_height} for value {value.begin_index}")

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
                owner_dict = {height: owner for height, owner in block_index_list.owner}
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
        第三步：布隆过滤器验证

        验证block_index_lst_切片信息与主链的布隆过滤器声明相吻合。

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息

        Returns:
            Tuple[bool, str]: (是否一致, 错误信息)
        """
        if not vpb_slice.block_index_slice.index_lst:
            # 如果没有需要验证的区块，认为验证失败
            return False, "VPB slice has empty block index list"

        # 提取owner信息
        owner_epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)

        expected_block_indices = set()
        # 找到最早的一个epoch_start_block
        if owner_epochs:
            # owner_epochs中的顺序已经排好，第一个item的epoch_blocks第一个元素就是earliest_block
            first_owner = list(owner_epochs.keys())[0]
            first_epoch_blocks = owner_epochs[first_owner]
            if first_epoch_blocks:
                expected_block_indices.add(first_epoch_blocks[0])

        # 对每个owner的epoch进行验证
        for owner_address, epoch_blocks in owner_epochs.items():

            # epoch_start_block: 获得value的区块
            # epoch_end_block: 花费value的区块（注意，花费的区块index并非是此Owner的epoch的最后一个index，而是下一个owner的epoch_start_block）
            epoch_start_block = epoch_blocks[0]

            # 找到下一个epoch的owner来确定epoch_end_block
            next_epoch_owner = self._find_next_epoch_owner(owner_address, owner_epochs)
            if next_epoch_owner and next_epoch_owner in owner_epochs:
                # epoch_end_block是下一个owner的epoch_start_block
                epoch_end_block = owner_epochs[next_epoch_owner][0]
            else:
                # 如果没有下一个owner，则使用当前epoch的最后一个区块
                epoch_end_block = epoch_blocks[-1]

            # 通过布隆过滤器获取该owner在此期间提交交易的区块
            transaction_blocks = main_chain_info.get_owner_transaction_blocks(
                owner_address, epoch_start_block + 1, epoch_end_block
            )

            # 将交易区块加入期望的索引
            expected_block_indices.update(transaction_blocks)

        # 将期望的区块索引转换为排序列表
        expected_indices = sorted(list(expected_block_indices))
        actual_indices = vpb_slice.block_index_slice.index_lst

        # 比较期望的索引和实际的索引
        if expected_indices != actual_indices:
            self.logger.debug(f"Bloom filter verification details:")
            self.logger.debug(f"Owner epochs: {owner_epochs}")
            self.logger.debug(f"Expected indices: {expected_indices}")
            self.logger.debug(f"Actual indices: {actual_indices}")
            return False, (
                f"Bloom filter verification failed. "
                f"Expected block indices: {expected_indices}, "
                f"Actual block indices: {actual_indices}"
            )

        return True, ""

    def _extract_owner_epochs(self, block_index_list: BlockIndexList) -> Dict[str, List[int]]:
        """
        从BlockIndexList中提取每个owner的epoch信息

        Args:
            block_index_list: 区块索引列表

        Returns:
            Dict[str, List[int]]: owner_address -> [block_heights]
        """
        owner_epochs = {}

        if not block_index_list.owner:
            return owner_epochs

        # 按owner分组区块高度
        for height, owner_address in block_index_list.owner:
            if owner_address not in owner_epochs:
                owner_epochs[owner_address] = []
            owner_epochs[owner_address].append(height)

        # 对每个owner的区块高度进行排序
        for owner_address in owner_epochs:
            owner_epochs[owner_address].sort()

        return owner_epochs

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
                                                   main_chain_info: MainChainInfo) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
        """
        第四步：逐证明单元验证和双花检测

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息

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

        # 提取owner epochs
        owner_epochs = self._extract_owner_epochs(vpb_slice.block_index_slice)

        # 对每个epoch进行验证
        for owner_address, epoch_blocks in owner_epochs.items():
            if len(epoch_blocks) < 1:
                continue

            # 验证这个epoch的proof units
            epoch_proof_units = []
            for block_height in epoch_blocks:
                # 找到对应的proof unit
                proof_unit = self._find_proof_unit_for_block(vpb_slice.proofs_slice, block_height, vpb_slice.block_index_slice)
                if proof_unit:
                    epoch_proof_units.append((block_height, proof_unit))
                else:
                    errors.append(VerificationError(
                        "PROOF_UNIT_MISSING",
                        f"Proof unit not found for block {block_height} in epoch of owner {owner_address}",
                        block_height=block_height
                    ))

            # 验证proof units的默克尔证明和sender地址
            epoch_valid = True
            for block_height, proof_unit in epoch_proof_units:
                # 检查Merkle根
                if block_height not in main_chain_info.merkle_roots:
                    errors.append(VerificationError(
                        "MERKLE_ROOT_MISSING",
                        f"Merkle root not found for block {block_height}",
                        block_height=block_height
                    ))
                    epoch_valid = False
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
                    epoch_valid = False

            # 检测双花
            if epoch_valid and epoch_proof_units:
                double_spend_result = self._detect_double_spend_in_epoch(
                    vpb_slice.value, epoch_proof_units, owner_address, owner_epochs
                )
                if not double_spend_result[0]:
                    errors.extend(double_spend_result[1])
                else:
                    verified_epochs.append((owner_address, epoch_blocks))

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
                                     owner_address: str, all_owner_epochs: Dict[str, List[int]]) -> Tuple[bool, List[VerificationError]]:
        """
        检测epoch内的双花行为

        正确的验证逻辑：
        - 在一个epoch内，非结尾的pu中，所有的交易均不能包含此目标value（有交集也不行）
        - 在结尾的pu中，则必须包含正确的转移目标value的交易（value完全符合、发送者和接收者也均符合epoch和下个epoch的owner地址）

        Args:
            value: 被验证的Value对象
            epoch_proof_units: 该epoch的proof units列表
            owner_address: epoch的所有者地址
            all_owner_epochs: 所有owner的epoch信息

        Returns:
            Tuple[bool, List[VerificationError]]: (无双花, 错误列表)
        """
        errors = []

        if not epoch_proof_units:
            return len(errors) == 0, errors

        # 按区块高度排序proof units
        epoch_proof_units.sort(key=lambda x: x[0])

        # 找到下一个epoch的owner地址（如果存在）
        next_epoch_owner = self._find_next_epoch_owner(owner_address, all_owner_epochs)

        # 检查每个proof unit
        for i, (block_height, proof_unit) in enumerate(epoch_proof_units):
            is_last_proof_unit = (i == len(epoch_proof_units) - 1)

            # 检查是否有与目标value交集的交易
            value_intersect_transactions = self._find_value_intersect_transactions(proof_unit, value)

            if is_last_proof_unit:
                # 最后一个proof unit：必须包含正确的value转移交易
                valid_spend_transactions = self._find_valid_value_spend_transactions(
                    proof_unit, value, owner_address, next_epoch_owner
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "NO_VALID_SPEND_IN_LAST_PROOF",
                        f"No valid spend transaction found for value {value.begin_index} "
                        f"in last proof unit at block {block_height}. "
                        f"Expected transfer from {owner_address} to {next_epoch_owner or 'new owner'}",
                        block_height=block_height
                    ))

                # 检查是否有不合法的交集交易
                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_VALUE_INTERSECTION",
                            f"Invalid value intersection found in last proof unit at block {block_height}: {tx}",
                            block_height=block_height
                        ))

            else:
                # 非结尾的proof unit：不能包含任何与目标value有交集的交易
                if value_intersect_transactions:
                    for tx in value_intersect_transactions:
                        errors.append(VerificationError(
                            "UNEXPECTED_VALUE_USE",
                            f"Unexpected value use found in non-last proof unit at block {block_height}: {tx}",
                            block_height=block_height
                        ))

        return len(errors) == 0, errors

    def _find_next_epoch_owner(self, current_owner: str, all_owner_epochs: Dict[str, List[int]]) -> Optional[str]:
        """
        找到当前epoch之后的下一个epoch的owner地址

        Args:
            current_owner: 当前epoch的owner地址
            all_owner_epochs: 所有owner的epoch信息

        Returns:
            Optional[str]: 下一个epoch的owner地址，如果不存在则返回None
        """
        if current_owner not in all_owner_epochs:
            return None

        current_epoch_blocks = all_owner_epochs[current_owner]
        if not current_epoch_blocks:
            return None

        current_epoch_end = max(current_epoch_blocks)

        # 查找下一个epoch
        next_owner = None
        next_epoch_start = float('inf')

        for owner, blocks in all_owner_epochs.items():
            if owner == current_owner:
                continue
            if not blocks:
                continue

            epoch_start = min(blocks)
            if epoch_start > current_epoch_end and epoch_start < next_epoch_start:
                next_epoch_start = epoch_start
                next_owner = owner

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
                    if self._transaction_intersects_value(transaction, value):
                        intersect_transactions.append(transaction)

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

        Args:
            transaction: 交易对象
            value: 目标Value对象

        Returns:
            bool: 是否有交集
        """
        if hasattr(transaction, 'input_values'):
            for input_value in transaction.input_values:
                if self._values_intersect(input_value, value):
                    return True

        if hasattr(transaction, 'output_values'):
            for output_value in transaction.output_values:
                if self._values_intersect(output_value, value):
                    return True

        if hasattr(transaction, 'spent_values'):
            for spent_value in transaction.spent_values:
                if self._values_intersect(spent_value, value):
                    return True

        if hasattr(transaction, 'received_values'):
            for received_value in transaction.received_values:
                if self._values_intersect(received_value, value):
                    return True

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

        Args:
            value1: 第一个value对象
            value2: 第二个Value对象

        Returns:
            bool: 是否有交集
        """
        try:
            if not (hasattr(value1, 'begin_index') and hasattr(value1, 'end_index')):
                return False

            v1_begin = int(value1.begin_index, 16)
            v1_end = int(value1.end_index, 16)
            v2_begin = int(value2.begin_index, 16)
            v2_end = int(value2.end_index, 16)

            # 检查是否有重叠
            return not (v1_end < v2_begin or v2_end < v1_begin)
        except (ValueError, AttributeError):
            return False

    def _find_value_spend_transactions(self, proof_unit: ProofUnit, value: Value) -> List[Any]:
        """
        在proof unit中查找花销指定value的交易

        Args:
            proof_unit: ProofUnit对象
            value: Value对象

        Returns:
            List[Any]: 花销该value的交易列表
        """
        spend_transactions = []

        if hasattr(proof_unit, 'owner_multi_txns') and proof_unit.owner_multi_txns:
            # 检查MultiTransactions中的每个交易
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for transaction in proof_unit.owner_multi_txns.multi_txns:
                    # 检查交易是否花销了该value
                    if self._transaction_spends_value(transaction, value):
                        spend_transactions.append(transaction)

        return spend_transactions

    def _transaction_spends_value(self, transaction: Any, value: Value) -> bool:
        """
        检查交易是否花销了指定的value

        Args:
            transaction: 交易对象
            value: Value对象

        Returns:
            bool: 是否花销了该value
        """
        # 这里需要根据实际的交易结构来实现
        # 暂时使用基本的属性检查
        if hasattr(transaction, 'input_values'):
            for input_value in transaction.input_values:
                if (hasattr(input_value, 'begin_index') and
                    hasattr(input_value, 'end_index') and
                    input_value.begin_index == value.begin_index and
                    input_value.end_index == value.end_index):
                    return True

        if hasattr(transaction, 'spent_values'):
            for spent_value in transaction.spent_values:
                if (hasattr(spent_value, 'begin_index') and
                    hasattr(spent_value, 'end_index') and
                    spent_value.begin_index == value.begin_index and
                    spent_value.end_index == value.end_index):
                    return True

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
