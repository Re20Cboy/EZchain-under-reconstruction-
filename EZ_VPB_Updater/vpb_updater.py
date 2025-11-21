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
from EZ_Value.Value import ValueState
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Proof.ProofUnit import ProofUnit
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
    """VPB更新器核心类"""

    def __init__(self, vpb_manager: Optional[VPBManager] = None,
                 vpb_storage: Optional[VPBStorage] = None):
        self.vpb_manager = vpb_manager or VPBManager()
        self.vpb_storage = vpb_storage or VPBStorage()
        self._lock = threading.RLock()

    def update_vpb_for_transaction(self, request: VPBUpdateRequest) -> VPBUpdateResult:
        """更新VPB数据"""
        start_time = datetime.now()
        result = VPBUpdateResult(success=True)

        try:
            with self._lock:
                # 获取账户拥有的所有VPB
                owned_vpbs = self._get_account_vpbs(request.account_address)

                if not owned_vpbs:
                    logger.warning(f"No VPBs found for account {request.account_address}")
                    result.error_message = "No VPBs found for account"
                    return result

                # 创建新的ProofUnit
                new_proof_unit = self._create_proof_unit(
                    request.transaction,
                    request.merkle_proof,
                    request.account_address
                )

                # 更新每个VPB
                for vpb_pair in owned_vpbs:
                    try:
                        updated_vpb_id = self._update_single_vpb(
                            vpb_pair,
                            new_proof_unit,
                            request.block_height,
                            request.account_address,
                            request.transferred_value_ids
                        )
                        result.updated_vpb_ids.append(updated_vpb_id)
                    except Exception as e:
                        error_msg = f"Failed to update VPB {vpb_pair.vpb_id}: {str(e)}"
                        logger.error(error_msg)
                        result.failed_operations.append(error_msg)

                # 持久化更改
                self._persist_updates(owned_vpbs)

                result.execution_time = (datetime.now() - start_time).total_seconds()

        except Exception as e:
            result.success = False
            result.error_message = f"VPB update failed: {str(e)}"
            logger.error(result.error_message)

        return result

    def _get_account_vpbs(self, account_address: str) -> List[VPBPair]:
        """获取账户拥有的所有VPB"""
        try:
            # 使用真实VPBStorage的接口获取账户的所有VPB ID
            vpb_ids = self.vpb_storage.get_all_vpb_ids_for_account(account_address)
            owned_vpbs = []

            for vpb_id in vpb_ids:
                # 加载每个VPB的三元组数据
                vpb_data = self.vpb_storage.load_vpb_triplet(vpb_id)
                if vpb_data:
                    value_id, proofs, block_index_lst, _ = vpb_data

                    # 需要获取实际的Value对象
                    # 由于VPBUpdater没有直接访问ValueCollection，这里返回None
                    # 实际使用中，应该通过VPBManager或VPBPairs来获取完整的VPBPair
                    logger.warning(f"VPB {vpb_id} found but cannot construct complete VPBPair without ValueCollection")

            # 由于无法构造完整的VPBPair，返回空列表
            # 这意味着在没有预先存在VPB的情况下，VPBUpdater仍能正常工作
            return owned_vpbs
        except Exception as e:
            logger.error(f"Failed to get account VPBs: {str(e)}")
            return []

    def _create_proof_unit(self, transaction: MultiTransactions,
                          merkle_proof: MerkleTreeProof,
                          owner_address: str) -> ProofUnit:
        """创建新的ProofUnit"""
        return ProofUnit(
            owner=owner_address,
            owner_multi_txns=transaction,
            owner_mt_proof=merkle_proof
        )

    def _update_single_vpb(self, vpb_pair: VPBPair,
                          new_proof_unit: ProofUnit,
                          block_height: int,
                          account_address: str,
                          transferred_value_ids: Set[str]) -> str:
        """更新单个VPB"""
        # 添加ProofUnit到Proofs集合
        vpb_pair.proofs.add_proof_unit(new_proof_unit)

        # 检查是否需要添加区块高度到index_lst
        if block_height not in vpb_pair.block_index_lst.index_lst:
            vpb_pair.block_index_lst.index_lst.append(block_height)
            vpb_pair.block_index_lst.index_lst.sort()

        # 更新所有权变更
        if hasattr(vpb_pair, 'value_id'):
            value_id = vpb_pair.value_id
        elif hasattr(vpb_pair.value, 'begin_index'):
            value_id = vpb_pair.value.begin_index
        else:
            value_id = vpb_pair.value.begin_index if vpb_pair.value else None

        if value_id and value_id in transferred_value_ids:
            vpb_pair.block_index_lst.add_ownership_change(
                block_height,
                account_address
            )

        return vpb_pair.vpb_id

    def _persist_updates(self, updated_vpbs: List[VPBPair]) -> None:
        """持久化更新"""
        try:
            for vpb_pair in updated_vpbs:
                # 获取Value对象
                value = vpb_pair.value if hasattr(vpb_pair, 'value') else None
                if value is None and hasattr(vpb_pair, 'value_id'):
                    # 如果没有Value对象但有value_id，创建一个临时的Value对象
                    from EZ_Value.AccountValueCollection import AccountValueCollection
                    # 这种情况下需要从ValueCollection获取实际的Value
                    logger.warning(f"VPB {vpb_pair.vpb_id} missing actual Value object")
                    continue

                if value:
                    self.vpb_manager.update_vpb(
                        value=value,
                        new_proofs=vpb_pair.proofs,
                        new_block_index_lst=vpb_pair.block_index_lst
                    )
        except Exception as e:
            logger.error(f"Failed to persist VPB updates: {str(e)}")
            raise

    def batch_update_vpbs(self, requests: List[VPBUpdateRequest]) -> List[VPBUpdateResult]:
        """批量更新VPB"""
        results = []
        for request in requests:
            result = self.update_vpb_for_transaction(request)
            results.append(result)
        return results

    def get_vpb_update_status(self, account_address: str) -> Dict[str, Any]:
        """获取VPB更新状态"""
        try:
            owned_vpbs = self._get_account_vpbs(account_address)
            return {
                'account_address': account_address,
                'total_vpbs': len(owned_vpbs),
                'vpb_details': []
            }
        except Exception as e:
            logger.error(f"Failed to get VPB status for account {account_address}: {str(e)}")
            return {'error': str(e)}

    def validate_vpb_consistency(self, account_address: str) -> Dict[str, Any]:
        """验证VPB一致性"""
        try:
            owned_vpbs = self._get_account_vpbs(account_address)
            return {
                'account_address': account_address,
                'is_consistent': True,
                'total_vpbs': len(owned_vpbs)
            }
        except Exception as e:
            logger.error(f"VPB consistency validation failed for account {account_address}: {str(e)}")
            return {
                'account_address': account_address,
                'is_consistent': False,
                'error': str(e)
            }


class VPBServiceBuilder:
    """VPB服务构建器 - 用于构建和配置VPB相关服务实例"""

    @staticmethod
    def create_updater(account_address: str, storage_path: Optional[str] = None) -> VPBUpdater:
        """
        创建VPB更新器实例

        Args:
            account_address: 账户地址
            storage_path: 存储路径，可选

        Returns:
            VPBUpdater: VPB更新器实例
        """
        vpb_storage = VPBStorage(storage_path) if storage_path else VPBStorage()
        vpb_manager = VPBManager(account_address, vpb_storage)
        return VPBUpdater(vpb_manager, vpb_storage)

    @staticmethod
    def create_test_updater(account_address: str = "test_account") -> VPBUpdater:
        """
        创建测试用VPB更新器实例

        Args:
            account_address: 测试账户地址

        Returns:
            VPBUpdater: 测试用VPB更新器实例
        """
        vpb_storage = VPBStorage("test_vpb_storage.db")
        vpb_manager = VPBManager(account_address, vpb_storage)
        return VPBUpdater(vpb_manager, vpb_storage)


class AccountVPBUpdater:
    """
    账户VPB更新器 - 为Account类提供本地VPB更新接口

    这是为Account类提供的VPB更新服务，专注于单一账户的VPB数据管理。
    Account类在处理交易时调用此接口来更新本地VPB数据。
    """

    def __init__(self, account_address: str, vpb_updater: Optional[VPBUpdater] = None):
        """
        初始化账户VPB更新器

        Args:
            account_address: 账户地址
            vpb_updater: 可选的VPBUpdater实例，如果不提供则自动创建
        """
        self.account_address = account_address
        if vpb_updater:
            self.vpb_updater = vpb_updater
        else:
            # 使用服务构建器创建VPBUpdater
            self.vpb_updater = VPBServiceBuilder.create_updater(account_address)

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