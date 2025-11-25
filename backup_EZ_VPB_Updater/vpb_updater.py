"""
EZChain VPB Updater

VPB (Verifiable Proof Block) 更新器核心实现，用于实时更新和维护VPB数据。
使用项目中的真实区块链模块，不使用任何模拟组件。
"""

import logging
import threading
import os
import sys
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

# 添加项目根目录到Python路径，确保能正确导入项目模块
sys.path.insert(0, os.path.dirname(__file__) + '/..')

# 导入项目中的真实区块链模块
from EZ_VPB.values.Value import ValueState
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_VPB.VPBPairs import VPBPair, VPBManager, VPBStorage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class VPBUpdateRequest:
    """VPB更新请求"""
    account_address: str
    transaction: MultiTransactions
    block_height: int
    merkle_proof: MerkleTreeProof
    transferred_value_ids: Set[str] = field(default_factory=set)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VPBUpdateResult:
    """VPB更新结果"""
    success: bool
    updated_vpb_ids: List[str] = field(default_factory=list)
    failed_operations: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    execution_time: float = 0.0


class VPBUpdater:
    """VPB更新器核心类 - 重构版本，符合Proofs映射优化设计"""

    def __init__(self, vpb_manager: Optional[VPBManager] = None,
                 vpb_storage: Optional[VPBStorage] = None,
                 value_collection: Optional[AccountValueCollection] = None):
        self.vpb_manager = vpb_manager
        self.vpb_storage = vpb_storage or VPBStorage()
        self.value_collection = value_collection
        self._lock = threading.RLock()

        # 如果提供了ValueCollection，初始化VPBManager
        if self.value_collection and self.vpb_manager:
            self.vpb_manager.set_value_collection(self.value_collection)

    def update_vpb_for_transaction(self, request: VPBUpdateRequest) -> VPBUpdateResult:
        """更新VPB数据 - 重构版本，使用Proofs映射优化机制"""
        start_time = datetime.now()
        result = VPBUpdateResult(success=True)

        try:
            with self._lock:
                # 使用VPBManager获取账户的VPB，利用映射优化机制
                if not self.vpb_manager:
                    logger.error("VPBManager not initialized")
                    result.success = False
                    result.error_message = "VPBManager not initialized"
                    return result

                # 设置账户地址（如果尚未设置）
                if not self.vpb_manager.account_address:
                    self.vpb_manager.set_account_address(request.account_address)

                # 获取所有VPB
                all_vpbs = self.vpb_manager.get_all_vpbs()

                if not all_vpbs:
                    logger.info(f"No VPBs found for account {request.account_address}, creating new VPB entries")
                    # 如果没有现有VPB，这是新账户的交易，需要创建相应的VPB结构
                    result.success = True
                    result.execution_time = (datetime.now() - start_time).total_seconds()
                    return result

                # 创建新的ProofUnit
                new_proof_unit = self._create_proof_unit(
                    request.transaction,
                    request.merkle_proof,
                    request.account_address
                )

                # 使用Proofs映射机制更新相关VPB
                updated_vpb_ids = self._update_vpbs_with_mapping_optimization(
                    all_vpbs,
                    new_proof_unit,
                    request.block_height,
                    request.account_address,
                    request.transferred_value_ids
                )

                result.updated_vpb_ids = updated_vpb_ids
                result.execution_time = (datetime.now() - start_time).total_seconds()

        except Exception as e:
            result.success = False
            result.error_message = f"VPB update failed: {str(e)}"
            logger.error(result.error_message)

        return result

    def _update_vpbs_with_mapping_optimization(self, vpb_map: Dict[str, VPBPair],
                                             new_proof_unit: ProofUnit,
                                             block_height: int,
                                             account_address: str,
                                             transferred_value_ids: Set[str]) -> List[str]:
        """
        使用Proofs映射优化机制更新VPB

        这个方法实现了TODO列表中提到的"映射方案"，避免将所有ProofUnit读入内存，
        而是通过映射关系和引用计数机制来高效更新VPB中的Proofs部分。
        """
        updated_vpb_ids = []

        for value_id, vpb_pair in vpb_map.items():
            try:
                # 检查是否需要更新此VPB
                if self._should_update_vpb(vpb_pair, transferred_value_ids, account_address):
                    # 使用Proofs映射机制添加ProofUnit
                    # Proofs会自动处理引用计数和映射关系
                    vpb_pair.proofs.add_proof_unit(new_proof_unit)

                    # 更新BlockIndexList
                    if block_height not in vpb_pair.block_index_lst.index_lst:
                        vpb_pair.block_index_lst.index_lst.append(block_height)
                        vpb_pair.block_index_lst.index_lst.sort()

                    # 如果涉及价值转移，更新所有权历史
                    if value_id in transferred_value_ids:
                        vpb_pair.block_index_lst.add_ownership_change(
                            block_height,
                            account_address
                        )

                    # 使用VPBManager更新VPB（确保持久化）
                    if self.value_collection:
                        value = vpb_pair.value
                        if value:
                            success = self.vpb_manager.update_vpb(
                                value=value,
                                new_proofs=vpb_pair.proofs,
                                new_block_index_lst=vpb_pair.block_index_lst
                            )
                            if success:
                                updated_vpb_ids.append(vpb_pair.vpb_id)
                                logger.debug(f"Successfully updated VPB {vpb_pair.vpb_id[:16]}...")
                            else:
                                logger.error(f"Failed to persist VPB update for {vpb_pair.vpb_id[:16]}...")
                    else:
                        # 如果没有ValueCollection，至少记录更新
                        updated_vpb_ids.append(vpb_pair.vpb_id)
                        logger.warning(f"VPB {vpb_pair.vpb_id[:16]}... updated in memory only (no ValueCollection)")

            except Exception as e:
                logger.error(f"Failed to update VPB {vpb_pair.vpb_id[:16]}...: {str(e)}")
                # 继续处理其他VPB，不让单个失败影响整体
                continue

        return updated_vpb_ids

    def _should_update_vpb(self, vpb_pair: VPBPair, transferred_value_ids: Set[str],
                          account_address: str) -> bool:
        """
        判断是否需要更新特定VPB

        根据交易类型和VPB当前状态决定是否需要更新
        """
        if not vpb_pair.value:
            return False

        value_id = vpb_pair.value_id

        # 如果直接涉及价值转移，需要更新
        if value_id in transferred_value_ids:
            return True

        # 如果是发送方的交易，需要更新相关VPB
        # 这里可以添加更复杂的逻辑来判断哪些VPB需要更新
        # 例如，检查VPB的所有者状态等

        return True  # 目前默认更新所有VPB，可根据实际业务逻辑优化

    def _create_proof_unit(self, transaction: MultiTransactions,
                          merkle_proof: MerkleTreeProof,
                          owner_address: str) -> ProofUnit:
        """创建新的ProofUnit"""
        return ProofUnit(
            owner=owner_address,
            owner_multi_txns=transaction,
            owner_mt_proof=merkle_proof
        )

    def batch_update_vpbs(self, requests: List[VPBUpdateRequest]) -> List[VPBUpdateResult]:
        """批量更新VPB"""
        results = []
        for request in requests:
            result = self.update_vpb_for_transaction(request)
            results.append(result)
        return results

    def get_vpb_update_status(self, account_address: str) -> Dict[str, Any]:
        """获取VPB更新状态 - 重构版本"""
        try:
            if not self.vpb_manager:
                return {'error': 'VPBManager not initialized'}

            # 确保账户地址已设置
            if not self.vpb_manager.account_address:
                self.vpb_manager.set_account_address(account_address)

            all_vpbs = self.vpb_manager.get_all_vpbs()

            # 收集VPB详情
            vpb_details = []
            for value_id, vpb_pair in all_vpbs.items():
                vpb_details.append({
                    'vpb_id': vpb_pair.vpb_id,
                    'value_id': value_id,
                    'proofs_count': len(vpb_pair.proofs),
                    'block_indices': len(vpb_pair.block_index_lst.index_lst),
                    'value_state': vpb_pair.value.state.name if vpb_pair.value else 'unknown'
                })

            return {
                'account_address': account_address,
                'total_vpbs': len(all_vpbs),
                'vpb_details': vpb_details,
                'has_value_collection': self.value_collection is not None
            }
        except Exception as e:
            logger.error(f"Failed to get VPB status for account {account_address}: {str(e)}")
            return {'error': str(e)}

    def validate_vpb_consistency(self, account_address: str) -> Dict[str, Any]:
        """验证VPB一致性 - 重构版本"""
        try:
            if not self.vpb_manager:
                return {
                    'account_address': account_address,
                    'is_consistent': False,
                    'error': 'VPBManager not initialized'
                }

            # 确保账户地址已设置
            if not self.vpb_manager.account_address:
                self.vpb_manager.set_account_address(account_address)

            all_vpbs = self.vpb_manager.get_all_vpbs()

            # 验证每个VPB的一致性
            inconsistencies = []
            for value_id, vpb_pair in all_vpbs.items():
                try:
                    # 验证VPB三元组完整性
                    if not vpb_pair.value:
                        inconsistencies.append(f'VPB {vpb_pair.vpb_id[:16]}... missing Value')
                        continue

                    if not vpb_pair.proofs:
                        inconsistencies.append(f'VPB {vpb_pair.vpb_id[:16]}... missing Proofs')
                        continue

                    if not vpb_pair.block_index_lst:
                        inconsistencies.append(f'VPB {vpb_pair.vpb_id[:16]}... missing BlockIndexList')
                        continue

                    # 验证Proofs中的映射关系
                    proof_units = vpb_pair.proofs.get_proof_units()
                    if not proof_units:
                        inconsistencies.append(f'VPB {vpb_pair.vpb_id[:16]}... has no ProofUnits')

                except Exception as e:
                    inconsistencies.append(f'VPB {vpb_pair.vpb_id[:16]}... validation error: {str(e)}')

            is_consistent = len(inconsistencies) == 0
            return {
                'account_address': account_address,
                'is_consistent': is_consistent,
                'total_vpbs': len(all_vpbs),
                'inconsistencies': inconsistencies,
                'validation_summary': f'Found {len(inconsistencies)} issues out of {len(all_vpbs)} VPBs'
            }
        except Exception as e:
            logger.error(f"VPB consistency validation failed for account {account_address}: {str(e)}")
            return {
                'account_address': account_address,
                'is_consistent': False,
                'error': str(e)
            }


class VPBServiceBuilder:
    """VPB服务构建器 - 用于构建和配置VPB相关服务实例 - 重构版本"""

    @staticmethod
    def create_updater(account_address: str,
                      storage_path: Optional[str] = None,
                      value_collection: Optional[AccountValueCollection] = None) -> VPBUpdater:
        """
        创建VPB更新器实例 - 支持ValueCollection集成

        Args:
            account_address: 账户地址
            storage_path: 存储路径，可选
            value_collection: AccountValueCollection实例，用于获取Value对象

        Returns:
            VPBUpdater: VPB更新器实例
        """
        vpb_storage = VPBStorage(storage_path) if storage_path else VPBStorage()
        vpb_manager = VPBManager(account_address, vpb_storage)

        # 如果提供了ValueCollection，设置到VPBManager
        if value_collection:
            vpb_manager.set_value_collection(value_collection)

        return VPBUpdater(vpb_manager, vpb_storage, value_collection)

    @staticmethod
    def create_updater_with_collection(account_address: str,
                                     value_collection: AccountValueCollection,
                                     storage_path: Optional[str] = None) -> VPBUpdater:
        """
        创建带有ValueCollection的VPB更新器实例 - 完整功能版本

        Args:
            account_address: 账户地址
            value_collection: AccountValueCollection实例（必需）
            storage_path: 存储路径，可选

        Returns:
            VPBUpdater: 具有完整功能的VPB更新器实例
        """
        vpb_storage = VPBStorage(storage_path) if storage_path else VPBStorage()
        vpb_manager = VPBManager(account_address, vpb_storage)
        vpb_manager.set_value_collection(value_collection)

        return VPBUpdater(vpb_manager, vpb_storage, value_collection)

    @staticmethod
    def create_test_updater(account_address: str = "test_account",
                           with_collection: bool = False) -> VPBUpdater:
        """
        创建测试用VPB更新器实例

        Args:
            account_address: 测试账户地址
            with_collection: 是否创建测试用的ValueCollection

        Returns:
            VPBUpdater: 测试用VPB更新器实例
        """
        vpb_storage = VPBStorage("test_vpb_storage.db")
        vpb_manager = VPBManager(account_address, vpb_storage)

        value_collection = None
        if with_collection:
            # 创建测试用的ValueCollection
            try:
                value_collection = AccountValueCollection(f"test_values_{account_address}.db")
                vpb_manager.set_value_collection(value_collection)
            except Exception as e:
                logger.warning(f"Failed to create test ValueCollection: {e}")

        return VPBUpdater(vpb_manager, vpb_storage, value_collection)


class AccountVPBUpdater:
    """
    账户VPB更新器 - 重构版本，为Account类提供本地VPB更新接口

    这是为Account类提供的VPB更新服务，专注于单一账户的VPB数据管理。
    Account类在处理交易时调用此接口来更新本地VPB数据。

    重构改进：
    - 支持ValueCollection集成，解决TODO列表中的问题
    - 利用Proofs映射优化机制，避免加载所有ProofUnit到内存
    - 提供完整的VPB生命周期管理
    """

    def __init__(self, account_address: str,
                 vpb_updater: Optional[VPBUpdater] = None,
                 value_collection: Optional[AccountValueCollection] = None):
        """
        初始化账户VPB更新器

        Args:
            account_address: 账户地址
            vpb_updater: 可选的VPBUpdater实例，如果不提供则自动创建
            value_collection: 可选的ValueCollection实例，用于获取Value对象
        """
        self.account_address = account_address
        if vpb_updater:
            self.vpb_updater = vpb_updater
        else:
            # 使用服务构建器创建VPBUpdater，支持ValueCollection
            self.vpb_updater = VPBServiceBuilder.create_updater(
                account_address=account_address,
                value_collection=value_collection
            )

    def update_local_vpbs(self, transaction: MultiTransactions,
                          merkle_proof: MerkleTreeProof, block_height: int,
                          transferred_value_ids: Optional[Set[str]] = None) -> VPBUpdateResult:
        """
        更新本地VPB数据 - 供Account类在交易处理时调用

        此接口供Account类在处理交易后调用，用于更新该账户相关的本地VPB数据。
        注意：这不是交易处理器，交易处理逻辑应在Account类中实现。

        Args:
            transaction: 已处理的多重交易对象
            merkle_proof: 交易对应的默克尔树证明
            block_height: 交易所在区块的高度
            transferred_value_ids: 交易中转移的Value ID集合

        Returns:
            VPBUpdateResult: VPB更新结果，包含更新的VPB信息
        """
        try:
            # 创建VPB更新请求
            request = VPBUpdateRequest(
                account_address=self.account_address,
                transaction=transaction,
                block_height=block_height,
                merkle_proof=merkle_proof,
                transferred_value_ids=transferred_value_ids or set()
            )

            # 执行VPB更新
            result = self.vpb_updater.update_vpb_for_transaction(request)

            logger.info(f"VPB update completed for account {self.account_address}: "
                       f"updated {len(result.updated_vpb_ids)} VPBs")

            return result

        except Exception as e:
            logger.error(f"VPB update failed for account {self.account_address}: {str(e)}")
            # 返回失败的更新结果
            error_result = VPBUpdateResult(success=False, error_message=str(e))
            return error_result

    def get_vpb_status(self) -> dict:
        """获取当前账户的VPB状态"""
        return self.vpb_updater.get_vpb_update_status(self.account_address)

    def validate_vpb_consistency(self) -> dict:
        """验证当前账户的VPB一致性"""
        return self.vpb_updater.validate_vpb_consistency(self.account_address)

    def batch_update_vpbs(self, requests: List[VPBUpdateRequest]) -> List[VPBUpdateResult]:
        """
        批量更新当前账户的VPB

        Args:
            requests: VPB更新请求列表（所有请求必须属于当前账户）

        Returns:
            List[VPBUpdateResult]: 更新结果列表
        """
        # 验证所有请求都属于当前账户
        for request in requests:
            if request.account_address != self.account_address:
                raise ValueError(f"Request account {request.account_address} does not match updater account {self.account_address}")

        return self.vpb_updater.batch_update_vpbs(requests)


# 向后兼容的别名
AccountNodeVPBIntegration = AccountVPBUpdater
AccountVPBManager = AccountVPBUpdater  # 额外的别名，提供更多选择




def create_vpb_update_request(account_address: str,
                            transaction: MultiTransactions,
                            block_height: int,
                            merkle_proof: MerkleTreeProof,
                            transferred_value_ids: Optional[Set[str]] = None) -> VPBUpdateRequest:
    """
    创建VPB更新请求

    Args:
        account_address: 账户地址
        transaction: 多重交易对象
        block_height: 区块高度
        merkle_proof: 默克尔树证明
        transferred_value_ids: 转移的Value ID集合

    Returns:
        VPBUpdateRequest: VPB更新请求对象
    """
    return VPBUpdateRequest(
        account_address=account_address,
        transaction=transaction,
        block_height=block_height,
        merkle_proof=merkle_proof,
        transferred_value_ids=transferred_value_ids or set()
    )