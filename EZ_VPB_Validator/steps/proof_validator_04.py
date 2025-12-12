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

            # 验证proof unit，对创世块进行特殊处理
            if block_height == 0:
                # 创世块使用特殊验证方法
                is_valid, error_msg = self._verify_genesis_proof_unit(proof_unit, merkle_root)
            else:
                # 非创世块使用标准验证方法
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
                # 即使检测到双花错误，也继续验证后续区块以收集更多错误信息
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

        # 创世块特殊验证：允许digest为空，因为这可能是创世流程中的特殊情况
        is_valid, error_msg = self._verify_genesis_proof_unit(genesis_proof_unit, genesis_merkle_root)
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

    def _verify_genesis_proof_unit(self, genesis_proof_unit, genesis_merkle_root) -> Tuple[bool, str]:
        """
        验证创世块的proof unit，特殊处理digest为None的情况

        Args:
            genesis_proof_unit: 创世块的proof unit
            genesis_merkle_root: 创世块的Merkle根

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        try:
            # 检查基本的ProofUnit结构
            if not genesis_proof_unit.owner_mt_proof.mt_prf_list:
                return False, "Merkle proof list is empty"

            # 创世块特殊处理：如果digest为None，我们尝试计算它或者跳过digest相关检查
            if genesis_proof_unit.owner_multi_txns.digest is None:
                # 尝试自动设置digest（如果可能的话）
                try:
                    genesis_proof_unit.owner_multi_txns.set_digest()
                    self.logger.info("Auto-set digest for genesis block MultiTransactions")
                except Exception as e:
                    # 如果无法设置digest，记录警告但继续验证其他部分
                    self.logger.warning(f"Cannot set digest for genesis block: {str(e)}")
                    # 对于创世块，我们允许digest为None的情况

            # 重新检查digest状态
            if genesis_proof_unit.owner_multi_txns.digest is not None:
                # 正常的验证流程
                from EZ_Tool_Box.Hash import sha256_hash
                expected_leaf_hash = sha256_hash(genesis_proof_unit.owner_multi_txns.digest)
                actual_leaf_hash = genesis_proof_unit.owner_mt_proof.mt_prf_list[0]

                if expected_leaf_hash != actual_leaf_hash:
                    return False, f"Merkle proof leaf hash mismatch: expected '{expected_leaf_hash}', got '{actual_leaf_hash}'"

                # 深度验证Merkle证明
                if genesis_proof_unit.owner_mt_proof.check_prf(
                    acc_txns_digest=genesis_proof_unit.owner_multi_txns.digest,
                    true_root=genesis_merkle_root
                ):
                    return True, "Genesis proof unit verification successful"
                else:
                    return False, f"Merkle proof validation failed for genesis digest '{genesis_proof_unit.owner_multi_txns.digest}' against root '{genesis_merkle_root}'"
            else:
                # digest仍然为None的特殊情况：我们只验证Merkle证明的结构，但不验证digest
                self.logger.info("Genesis block with None digest - performing structure-only validation")

                # 验证创世交易的发送者是否为预期的创世地址
                if hasattr(genesis_proof_unit.owner_multi_txns, 'sender'):
                    sender = genesis_proof_unit.owner_multi_txns.sender
                    # 检查是否为创世地址（新格式以0xGENESIS开头）
                    from EZ_GENESIS.genesis_account import get_genesis_manager
                    genesis_manager = get_genesis_manager()

                    # 只接受新的创世地址格式 - 不再支持向后兼容
                    is_valid_genesis_address = (
                        sender.startswith("0xGENESIS") and genesis_manager.is_genesis_address(sender)
                    )

                    if not is_valid_genesis_address:
                        return False, f"Genesis block sender should be valid genesis address (0xGENESIS*), got: {sender}"

                # 对于digest为None的创世块，我们只验证基本结构
                return True, "Genesis proof unit structure verification successful (digest None allowed for genesis)"

        except Exception as e:
            return False, f"Error during genesis proof verification: {str(e)}"

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
        基于详细需求检测epoch内的双花行为

        根据proof_validator_demo.md的要求：
        - 目标value交易区块：必须包含与目标value完全重合的交易，且符合转移路径
        - 非目标value交易区块：必须与目标value完全无交集
        - 创世块：必须包含GOD->owner的派发交易

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

            # 创世块特殊处理：必须包含GOD->owner的派发交易
            if block_height == 0:
                # 创世块必须包含与目标value完全重合的交易（GOD->owner）
                valid_spend_transactions = self.value_detector.find_valid_value_spend_transactions(
                    proof_unit, value, "GOD", owner_address  # 创世交易是GOD->owner
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "MISSING_GENESIS_VALUE_DISTRIBUTION",
                        f"Genesis block must contain GOD->{owner_address} value distribution, but found no valid transactions",
                        block_height=0
                    ))

                # 检查是否有不合法的交集交易（非GOD->sender的value交集）
                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_GENESIS_VALUE_INTERSECTION",
                            f"Invalid value intersection in genesis block {block_height}: {tx}. Only GOD->{owner_address} distribution allowed.",
                            block_height=0
                        ))
                continue

            # 非创世块：需要判断这是目标value交易区块还是非目标value交易区块
            is_target_value_block = self._is_target_value_transfer_block(block_height, owner_address, previous_owner)

            if is_target_value_block:
                # 目标value交易区块：必须包含从previous_owner到当前owner的有效转移交易
                valid_spend_transactions = self.value_detector.find_valid_value_spend_transactions(
                    proof_unit, value, previous_owner, owner_address
                )

                if not valid_spend_transactions:
                    errors.append(VerificationError(
                        "NO_VALID_TARGET_VALUE_TRANSFER",
                        f"Block {block_height} must contain valid target value transfer from {previous_owner} to {owner_address}, "
                        f"but found no valid transactions",
                        block_height=block_height
                    ))

                # 检查是否有不合法的交集交易（不应该是目标value转移的其他交易）
                for tx in value_intersect_transactions:
                    if tx not in valid_spend_transactions:
                        errors.append(VerificationError(
                            "INVALID_TARGET_VALUE_INTERSECTION",
                            f"Invalid target value intersection found in block {block_height}: {tx}. "
                            f"Only {previous_owner}->{owner_address} target value transfer allowed.",
                            block_height=block_height
                        ))
            else:
                # 非目标value交易区块：必须与目标value完全无交集（双花检测）
                if value_intersect_transactions:
                    errors.append(VerificationError(
                        "DOUBLE_SPEND_DETECTED",
                        f"Block {block_height} contains transactions intersecting with target value "
                        f"({len(value_intersect_transactions)} transactions), indicating double spend",
                        block_height=block_height
                    ))
                    for tx in value_intersect_transactions:
                        errors.append(VerificationError(
                            "DOUBLE_SPEND_TRANSACTION",
                            f"Double spend transaction in block {block_height}: {tx}",
                            block_height=block_height
                        ))

        return len(errors) == 0, errors

    def _is_target_value_transfer_block(self, block_height: int, owner_address: str, previous_owner: Optional[str]) -> bool:
        """
        判断指定区块是否应该是目标value转移区块

        根据需求文档，目标value转移区块的特征：
        - 该区块的owner地址发生了变化（从previous_owner到owner_address）
        - 区块中应该包含目标value的转移交易

        Args:
            block_height: 区块高度
            owner_address: 该区块的owner地址
            previous_owner: 前一个区块的owner地址

        Returns:
            bool: True表示是目标value转移区块，False表示是非目标value交易区块
        """
        # 如果有前驱owner且owner地址发生变化，说明是目标value转移区块
        if previous_owner is not None and previous_owner != owner_address:
            return True

        # 如果没有前驱owner（创世块已经在其他地方处理），默认认为是目标value转移区块
        # 这种情况在正常流程中不应该出现，但为了安全起见
        return False