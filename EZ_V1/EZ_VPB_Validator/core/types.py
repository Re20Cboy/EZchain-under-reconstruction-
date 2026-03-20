"""
VPB Validator Core Types

This module defines the core data types used throughout the VPB validation system.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING
from EZ_CheckPoint.CheckPoint import CheckPointRecord

if TYPE_CHECKING:
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
    """
    主链信息数据结构

    包含VPB验证所需的主链核心信息：
    - Merkle根哈希：用于验证区块的Merkle证明
    - 布隆过滤器：用于快速检测地址是否在区块中提交过交易
    - 区块高度信息：用于验证区块范围的合法性
    """
    merkle_roots: Dict[int, str]        # block_height -> merkle_root_hash
    bloom_filters: Dict[int, 'BloomFilter']  # block_height -> bloom_filter_object
    current_block_height: int
    genesis_block_height: int = 0

    def get_blocks_in_range(self, start_height: int, end_height: int) -> List[int]:
        """
        获取指定范围内的区块高度列表

        Args:
            start_height: 起始区块高度
            end_height: 结束区块高度

        Returns:
            List[int]: 范围内存在的区块高度列表
        """
        return [h for h in range(start_height, end_height + 1) if h in self.merkle_roots]

    def has_block_data(self, block_height: int) -> bool:
        """
        检查指定区块是否有完整的验证数据

        Args:
            block_height: 区块高度

        Returns:
            bool: 是否同时有Merkle根和布隆过滤器
        """
        return (block_height in self.merkle_roots and
                block_height in self.bloom_filters)

    def validate_data_consistency(self) -> List[str]:
        """
        验证数据一致性

        Returns:
            List[str]: 发现的问题列表，空列表表示没有问题
        """
        issues = []

        # 检查merkle_roots和bloom_filters的区块高度是否一致
        merkle_heights = set(self.merkle_roots.keys())
        bloom_heights = set(self.bloom_filters.keys())

        # 只在merkle_roots中的区块
        merkle_only = merkle_heights - bloom_heights
        if merkle_only:
            issues.append(f"区块缺少布隆过滤器: {sorted(merkle_only)}")

        # 只在bloom_filters中的区块
        bloom_only = bloom_heights - merkle_heights
        if bloom_only:
            issues.append(f"区块缺少Merkle根: {sorted(bloom_only)}")

        return issues

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取主链信息统计

        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            'total_blocks_with_merkle': len(self.merkle_roots),
            'total_blocks_with_bloom': len(self.bloom_filters),
            'current_block_height': self.current_block_height,
            'genesis_block_height': self.genesis_block_height,
            'block_range': f"{self.genesis_block_height}-{self.current_block_height}",
            'data_consistency_issues': len(self.validate_data_consistency())
        }

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