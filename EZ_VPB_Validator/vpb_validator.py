"""
VPB Validator Main Interface

Refactored modular VPB validation system with streamlined step integration.
"""

import threading
import logging
import time
from typing import Dict, Any, Optional

from .core.types import VerificationResult, VerificationError, VPBVerificationReport, VPBSlice
from .core.validator_base import ValidatorBase
from .steps.data_structure_validator_01 import DataStructureValidator
from .steps.slice_generator_02 import VPBSliceGenerator
from .steps.bloom_filter_validator_03 import BloomFilterValidator
from .steps.proof_validator_04 import ProofValidator


class VPBValidator(ValidatorBase):
    """
    EZChain VPB验证器 - 精简重构版本

    实现完整的VPB验证算法，采用模块化设计，确保各步骤无缝连接。
    """

    def __init__(self, checkpoint=None, logger: Optional[logging.Logger] = None):
        """
        初始化VPB验证器

        Args:
            checkpoint: 检查点管理器实例
            logger: 日志记录器实例
        """
        super().__init__(logger)

        # 初始化各个验证步骤
        self.data_structure_validator = DataStructureValidator(logger)
        self.slice_generator = VPBSliceGenerator(checkpoint, logger)
        self.bloom_filter_validator = BloomFilterValidator(logger)
        self.proof_validator = ProofValidator(logger)

        # 精简的验证统计信息
        self.verification_stats = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'checkpoint_used': 0
        }

    def verify_vpb_pair(self, value, proof_units, block_index_list, main_chain_info, account_address: str) -> VPBVerificationReport:
        """
        验证VPB三元组的完整性和合法性

        Args:
            value: 待验证的Value对象
            proof_units: 对应的ProofUnit列表 (List[ProofUnit])
            block_index_list: 对应的BlockIndexList对象
            main_chain_info: 主链信息
            account_address: 进行验证的账户地址

        Returns:
            VPBVerificationReport: 详细的验证报告
        """
        start_time = time.time()
        errors = []
        verified_epochs = []
        checkpoint_used = None

        with self._lock:
            self.verification_stats['total'] += 1

            try:
                # 将List[ProofUnit]转换为Proofs对象以兼容验证步骤
                self.logger.info("Converting List[ProofUnit] to Proofs object")
                proofs = self._convert_proof_units_to_proofs(proof_units, value, account_address)
                if proofs is None:
                    errors.append(VerificationError("PROOFS_CONVERSION_FAILED", "Failed to convert ProofUnit list to Proofs object"))
                    return self._create_failure_report(errors, verified_epochs, checkpoint_used, start_time)

                # Step 1: 基础数据结构验证
                self.logger.info("Step 1: Basic data structure validation")
                is_valid, error_msg = self.data_structure_validator.validate_basic_data_structure(
                    value, proofs, block_index_list
                )
                if not is_valid:
                    errors.append(VerificationError("DATA_STRUCTURE_VALIDATION_FAILED", error_msg))
                    return self._create_failure_report(errors, verified_epochs, checkpoint_used, start_time)

                # Step 2: VPB切片生成（含检查点处理）
                self.logger.info("Step 2: VPB slice generation")
                vpb_slice, checkpoint_used = self.slice_generator.generate_vpb_slice(
                    value, proofs, block_index_list, account_address
                )

                # Step 3: 布隆过滤器一致性验证
                self.logger.info("Step 3: Bloom filter consistency verification")
                is_valid, error_msg = self.bloom_filter_validator.verify_bloom_filter_consistency(
                    vpb_slice, main_chain_info
                )
                if not is_valid:
                    errors.append(VerificationError("BLOOM_FILTER_VALIDATION_FAILED", error_msg))

                # Step 4: 证明单元验证和双花检测
                self.logger.info("Step 4: Proof verification and double-spend detection")
                is_valid, proof_errors, verified_epochs = self.proof_validator.verify_proof_units_and_detect_double_spend(
                    vpb_slice, main_chain_info, checkpoint_used
                )
                if not is_valid:
                    errors.extend(proof_errors)

                # 统计检查点使用情况
                if checkpoint_used:
                    self.verification_stats['checkpoint_used'] += 1

                # 生成最终验证报告
                return self._create_final_report(errors, verified_epochs, checkpoint_used, start_time)

            except Exception as e:
                self.logger.error(f"VPB verification exception: {e}")
                errors.append(VerificationError("VERIFICATION_EXCEPTION", str(e)))
                return self._create_failure_report(errors, verified_epochs, checkpoint_used, start_time)

    def _create_failure_report(self, errors, verified_epochs, checkpoint_used, start_time) -> VPBVerificationReport:
        """创建失败报告的辅助方法"""
        with self._lock:
            self.verification_stats['failed'] += 1
        report_time = (time.time() - start_time) * 1000
        return VPBVerificationReport(
            VerificationResult.FAILURE, False, errors, verified_epochs, checkpoint_used, report_time
        )

    def _convert_proof_units_to_proofs(self, proof_units, value, account_address: str):
        """
        将List[ProofUnit]转换为Proofs对象以兼容验证步骤

        Args:
            proof_units: ProofUnit列表
            value: Value对象
            account_address: 账户地址

        Returns:
            Proofs: 转换后的Proofs对象，失败返回None
        """
        try:
            from EZ_VPB.proofs.Proofs import Proofs
            from EZ_VPB.proofs.AccountProofManager import AccountProofManager

            # 创建临时的AccountProofManager来持有ProofUnits
            temp_proof_manager = AccountProofManager(f"temp_{account_address}")

            # 将每个ProofUnit添加到临时管理器中
            for proof_unit in proof_units:
                temp_proof_manager.add_proof_unit(value.begin_index, proof_unit)

            # 创建Proofs对象，使用临时的AccountProofManager
            proofs = Proofs(
                value_id=value.begin_index,
                account_address=account_address,
                account_proof_manager=temp_proof_manager
            )

            self.logger.info(f"Successfully converted {len(proof_units)} ProofUnits to Proofs object")
            return proofs

        except Exception as e:
            self.logger.error(f"Failed to convert ProofUnits to Proofs: {e}")
            return None

    def _create_final_report(self, errors, verified_epochs, checkpoint_used, start_time) -> VPBVerificationReport:
        """创建最终验证报告的辅助方法"""
        is_valid = len(errors) == 0
        result = VerificationResult.SUCCESS if is_valid else VerificationResult.FAILURE

        with self._lock:
            if is_valid:
                self.verification_stats['successful'] += 1
                self.logger.info("VPB validation completed successfully")
            else:
                self.verification_stats['failed'] += 1
                self.logger.warning(f"VPB validation failed with {len(errors)} errors")

        report_time = (time.time() - start_time) * 1000
        return VPBVerificationReport(
            result, is_valid, errors, verified_epochs, checkpoint_used, report_time
        )

    def get_verification_stats(self) -> Dict[str, Any]:
        """获取验证统计信息"""
        with self._lock:
            stats = self.verification_stats.copy()
            if stats['total'] > 0:
                stats['success_rate'] = stats['successful'] / stats['total']
                stats['checkpoint_hit_rate'] = stats['checkpoint_used'] / stats['total']
            else:
                stats['success_rate'] = 0.0
                stats['checkpoint_hit_rate'] = 0.0
            return stats

    def reset_stats(self):
        """重置验证统计信息"""
        with self._lock:
            self.verification_stats = {
                'total': 0,
                'successful': 0,
                'failed': 0,
                'checkpoint_used': 0
            }