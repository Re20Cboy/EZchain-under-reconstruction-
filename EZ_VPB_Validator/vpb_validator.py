"""
VPB Validator Main Interface

This module provides the main VPBValidator class that orchestrates
the entire VPB validation process using modular steps.
"""

import threading
import logging
import time
from typing import Dict, Any, Optional

from .core.types import VerificationResult, VerificationError, VPBVerificationReport, VPBSlice
from .core.validator_base import ValidatorBase
from .steps.data_structure_validator import DataStructureValidator
from .steps.slice_generator import VPBSliceGenerator
from .steps.bloom_filter_validator import BloomFilterValidator
from .steps.proof_validator import ProofValidator


class VPBValidator(ValidatorBase):
    """
    EZChain VPB验证器 - 模块化版本

    实现完整的VPB验证算法，支持检查点优化和内存高效的分块验证。
    采用模块化设计，将复杂的验证流程分解为独立的步骤。
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

        # 验证统计信息
        self.verification_stats = {
            'total_verifications': 0,
            'successful_verifications': 0,
            'failed_verifications': 0,
            'checkpoint_hits': 0
        }

    def verify_vpb_pair(self, value, proofs, block_index_list, main_chain_info, account_address: str) -> VPBVerificationReport:
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
        start_time = time.time()

        with self._lock:
            self.verification_stats['total_verifications'] += 1

            errors = []
            verified_epochs = []
            checkpoint_used = None

            try:
                # 第一步：基础数据结构合法性验证
                self.logger.info("Step 1: Validating basic data structure...")
                validation_result = self.data_structure_validator.validate_basic_data_structure(
                    value, proofs, block_index_list
                )
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
                self.logger.info("Step 2: Generating VPB slice...")
                vpb_slice, checkpoint_used = self.slice_generator.generate_vpb_slice(
                    value, proofs, block_index_list, account_address
                )

                # 第三步：布隆过滤器验证
                self.logger.info("Step 3: Verifying bloom filter consistency...")
                bloom_validation_result = self.bloom_filter_validator.verify_bloom_filter_consistency(
                    vpb_slice, main_chain_info
                )
                if not bloom_validation_result[0]:
                    errors.append(VerificationError(
                        "BLOOM_FILTER_VALIDATION_FAILED",
                        bloom_validation_result[1]
                    ))

                # 第四步：逐证明单元验证和双花检测
                self.logger.info("Step 4: Verifying proof units and detecting double spend...")
                epoch_verification_result = self.proof_validator.verify_proof_units_and_detect_double_spend(
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
                    self.logger.info("VPB validation completed successfully")
                else:
                    self.verification_stats['failed_verifications'] += 1
                    self.logger.warning(f"VPB validation failed with {len(errors)} errors")

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