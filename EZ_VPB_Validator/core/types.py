"""
VPB Validator Core Types

This module defines the core data types used throughout the VPB validation system.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from EZ_CheckPoint.CheckPoint import CheckPointRecord


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

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'error_type': self.error_type,
            'error_message': self.error_message,
            'block_height': self.block_height,
            'proof_index': self.proof_index
        }


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
            'errors': [err.to_dict() for err in self.errors],
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
        from EZ_Units.Bloom import BloomFilter

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
    from EZ_VPB.values.Value import Value
    from EZ_VPB.proofs.ProofUnit import ProofUnit
    from EZ_VPB.block_index.BlockIndexList import BlockIndexList
    from EZ_CheckPoint.CheckPoint import CheckPointRecord

    value: Value
    proofs_slice: List[ProofUnit]
    block_index_slice: BlockIndexList
    start_block_height: int
    end_block_height: int
    checkpoint_used: Optional[CheckPointRecord] = None
    previous_owner: Optional[str] = None  # checkpoint触发时的owner地址


class ValueIntersectionError(Exception):
    """Value交集检测错误"""
    pass