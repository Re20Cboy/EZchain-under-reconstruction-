"""
EZChain VPB Updater Package

VPB (Verifiable Proof Block) 更新器系统，用于分布式区块链节点中实时VPB数据维护和一致性管理。

主要组件:
- VPBUpdater: 核心VPB数据更新器
- AccountVPBUpdater: 账户VPB更新器（为Account类提供本地VPB更新接口）
- VPBServiceBuilder: VPB服务构建器（替代VPBUpdaterFactory）
- VPBUpdateRequest: VPB更新请求对象
- VPBUpdateResult: VPB更新结果对象

设计理念:
- 专注分布式架构：每个账户独立管理自己的VPB
- 清晰职责分离：Account类处理交易，AccountVPBUpdater更新VPB数据
- 轻量级接口：为单个账户提供简洁高效的VPB管理
- 准确命名：类名和函数名准确反映其功能

Author: EZChain Team
Version: 2.1.0
Date: 2025/11/21
"""

from .vpb_updater import (
    VPBUpdater,
    AccountVPBUpdater,          # 新的主要接口
    AccountNodeVPBIntegration,  # 向后兼容别名
    AccountVPBManager,          # 额外的向后兼容别名
    VPBServiceBuilder,          # 服务构建器
    VPBUpdateRequest,
    VPBUpdateResult,
    create_vpb_update_request
)

__version__ = "2.1.0"
__author__ = "EZChain Team"

__all__ = [
    'VPBUpdater',
    'AccountVPBUpdater',          # 新的主要接口 - 推荐使用
    'AccountNodeVPBIntegration',  # 向后兼容别名
    'AccountVPBManager',          # 额外的向后兼容别名
    'VPBServiceBuilder',          # 服务构建器 - 推荐使用
    'VPBUpdateRequest',
    'VPBUpdateResult',
    'create_vpb_update_request'
]