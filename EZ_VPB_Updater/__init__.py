"""
EZChain VPB Updater Package

VPB (Verifiable Proof Block) 更新器系统，用于实时VPB数据维护和一致性管理。

主要组件:
- VPBUpdater: 核心VPB数据更新器
- AccountNodeVPBIntegration: 账户节点集成
- BlockchainVPBIntegration: 区块链级集成
- VPBUpdateRequest: VPB更新请求对象
- VPBUpdaterFactory: VPB更新器工厂

Author: EZChain Team
Version: 1.0.0
Date: 2025/11/20
"""

from .vpb_updater import (
    VPBUpdater,
    AccountNodeVPBIntegration,
    BlockchainVPBIntegration,
    VPBUpdateRequest,
    VPBUpdateResult,
    VPBUpdaterFactory,
    create_vpb_update_request
)

__version__ = "1.0.0"
__author__ = "EZChain Team"

__all__ = [
    'VPBUpdater',
    'AccountNodeVPBIntegration',
    'BlockchainVPBIntegration',
    'VPBUpdateRequest',
    'VPBUpdateResult',
    'VPBUpdaterFactory',
    'create_vpb_update_request'
]