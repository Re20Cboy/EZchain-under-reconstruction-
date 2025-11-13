"""
Proof Validation Step

This module implements the fourth step of VPB validation: proof unit verification and double-spend detection.
"""

from typing import Tuple, List, Optional
from ..core.validator_base import ValidatorBase
from ..core.types import VPBSlice, VerificationError
from ..utils.value_intersection import ValueIntersectionDetector
from ..utils.epoch_extractor import EpochExtractor
from EZ_CheckPoint.CheckPoint import CheckPointRecord


class ProofValidator(ValidatorBase):
    """证明单元验证器"""

    def __init__(self, logger=None):
        """
        初始化证明验证器

        Args:
            logger: 日志记录器实例
        """
        super().__init__(logger)
        self.value_detector = ValueIntersectionDetector(logger)
        self.epoch_extractor = EpochExtractor(logger)

    def verify_proof_units_and_detect_double_spend(self, vpb_slice: VPBSlice, main_chain_info, checkpoint_used: Optional[CheckPointRecord] = None) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
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
                previous_owner = self.epoch_extractor.get_previous_owner_for_block(epochs, block_height)

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

    def _verify_genesis_block(self, vpb_slice: VPBSlice, main_chain_info) -> Tuple[bool, List[VerificationError], List[Tuple[str, List[int]]]]:
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

    def _find_proof_unit_for_block(self, proofs_slice: List, block_height: int, block_index_slice = None):
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

    def _detect_double_spend_in_epoch(self, value, epoch_proof_units: List[Tuple[int, any]], owner_address: str, previous_owner: Optional[str] = None) -> Tuple[bool, List[VerificationError]]:
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
            value_intersect_transactions = self.value_detector.find_value_intersect_transactions(proof_unit, value)

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
                valid_spend_transactions = self.value_detector.find_valid_value_spend_transactions(
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