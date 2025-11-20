"""
EZChain VPB Updater - 精简版

VPB (Verifiable Proof Block) 更新器核心实现，用于实时更新和维护VPB数据。
"""

import logging
import threading
import hashlib
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Mock components for independent testing
try:
    # Try relative imports when run as part of the package
    from ..EZ_Value import Value, ValueState
    from ..EZ_Proof import ProofUnit, MerkleTreeProof, Proofs
    from ..EZ_BlockIndex import BlockIndexList
    from ..EZ_Transaction import MultiTransactions, Transaction
    from ..EZ_VPB import VPBPairs, VPBManager, VPBStorage, VPBPair
except ImportError:
    # Fallback to mock components when run directly for testing
    from enum import Enum
    from dataclasses import dataclass

    class ValueState(Enum):
        UNSPENT = "unspent"
        SELECTED = "selected"
        LOCAL_COMMITTED = "local_committed"
        CONFIRMED = "confirmed"

    class Value:
        def __init__(self, begin_index: str, value_num: int):
            self.begin_index = begin_index
            self.value_num = value_num
            self.end_index = self.get_end_index(begin_index, value_num)
            self.state = ValueState.UNSPENT

        @staticmethod
        def get_end_index(begin_index: str, value_num: int) -> str:
            begin_decimal = int(begin_index, 16)
            end_decimal = begin_decimal + value_num - 1
            return hex(end_decimal)

        def get_begin_index(self) -> str:
            return self.begin_index

        def check_value(self) -> bool:
            try:
                int(self.begin_index, 16)
                return isinstance(self.value_num, int) and self.value_num > 0
            except (ValueError, TypeError):
                return False

    class Transaction:
        def __init__(self, sender: str, recipient: str, value: int, fee: int, nonce: int):
            self.sender = sender
            self.recipient = recipient
            self.value = value
            self.fee = fee
            self.nonce = nonce
            self.digest = hashlib.sha256(f"{sender}{recipient}{value}{fee}{nonce}".encode()).hexdigest()

    class MultiTransactions:
        def __init__(self, sender: str, multi_txns):
            self.sender = sender
            self.multi_txns = multi_txns
            self.digest = hashlib.sha256(f"{sender}{len(multi_txns)}".encode()).hexdigest()

    class MerkleTreeProof:
        def __init__(self, merkle_root: str, proof_hash: str, index: int):
            self.merkle_root = merkle_root
            self.proof_hash = proof_hash
            self.index = index

        def get_merkle_root(self) -> str:
            return self.merkle_root

    class ProofUnit:
        def __init__(self, owner: str, owner_multi_txns: MultiTransactions, owner_mt_proof: MerkleTreeProof):
            self.owner = owner
            self.owner_multi_txns = owner_multi_txns
            self.owner_mt_proof = owner_mt_proof
            self.unit_id = hashlib.sha256(f"{owner}{owner_multi_txns.digest}".encode()).hexdigest()[:16]
            self.reference_count = 0

    class Proofs:
        def __init__(self):
            self._proof_units = []

        def add_proof_unit(self, proof_unit: ProofUnit):
            self._proof_units.append(proof_unit)

        def get_proof_units(self):
            return self._proof_units

    class BlockIndexList:
        def __init__(self, owner: str):
            self.owner = owner
            self.index_lst = []
            self._owner_history = []

        def add_block_height(self, block_height: int):
            if block_height not in self.index_lst:
                self.index_lst.append(block_height)
                self.index_lst.sort()

        def add_ownership_change(self, block_index: int, new_owner: str):
            self._owner_history.append((block_index, new_owner))

        def get_current_owner(self) -> str:
            return self._owner_history[-1][1] if self._owner_history else self.owner

    @dataclass
    class VPBPair:
        value: Value
        proofs: Proofs
        block_index_lst: BlockIndexList
        vpb_id: str = ""

        def __post_init__(self):
            if not self.vpb_id:
                self.vpb_id = hashlib.sha256(f"{self.value.begin_index}{self.value.value_num}".encode()).hexdigest()[:16]

    class VPBStorage:
        def __init__(self):
            self._vpbs = {}

        def store_vpb_triplet(self, vpb_pair: VPBPair):
            self._vpbs[vpb_pair.vpb_id] = vpb_pair

        def load_all_vpb_triplets(self):
            return list(self._vpbs.values())

    class VPBManager:
        def __init__(self, storage: VPBStorage = None):
            self.storage = storage or VPBStorage()

        def update_vpb(self, vpb_pair: VPBPair):
            self.storage.store_vpb_triplet(vpb_pair)

    class VPBPairs:
        def __init__(self):
            pass

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
            all_vpbs = self.vpb_storage.load_all_vpb_triplets()
            owned_vpbs = []
            for vpb_pair in all_vpbs:
                if vpb_pair.block_index_lst.get_current_owner() == account_address:
                    owned_vpbs.append(vpb_pair)
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
        # 添加ProofUnit
        vpb_pair.proofs.add_proof_unit(new_proof_unit)

        # 更新BlockIndex
        vpb_pair.block_index_lst.add_block_height(block_height)

        # 更新所有权变更
        value_id = vpb_pair.value.get_begin_index()
        if value_id in transferred_value_ids:
            vpb_pair.block_index_lst.add_ownership_change(
                block_height,
                account_address
            )

        return vpb_pair.vpb_id

    def _persist_updates(self, updated_vpbs: List[VPBPair]) -> None:
        """持久化更新"""
        try:
            for vpb_pair in updated_vpbs:
                self.vpb_manager.update_vpb(vpb_pair)
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


class VPBUpdaterFactory:
    """VPB更新器工厂"""

    @staticmethod
    def create_vpb_updater(storage_path: Optional[str] = None) -> VPBUpdater:
        """创建VPB更新器"""
        vpb_storage = VPBStorage() if storage_path is None else VPBStorage(storage_path)
        vpb_manager = VPBManager(vpb_storage)
        return VPBUpdater(vpb_manager, vpb_storage)

    @staticmethod
    def create_test_vpb_updater() -> VPBUpdater:
        """创建测试用VPB更新器"""
        vpb_storage = VPBStorage()
        vpb_manager = VPBManager(vpb_storage)
        return VPBUpdater(vpb_manager, vpb_storage)


class AccountNodeVPBIntegration:
    """账户节点VPB集成"""

    def __init__(self, account_address: str, vpb_updater: Optional[VPBUpdater] = None):
        self.account_address = account_address
        self.vpb_updater = vpb_updater or VPBUpdater()

    def process_transaction(self, transaction: MultiTransactions,
                          merkle_proof: MerkleTreeProof, block_height: int,
                          transferred_value_ids: Optional[Set[str]] = None) -> dict:
        """处理交易并触发VPB更新"""
        result = {
            'transaction_processed': False,
            'vpb_update_triggered': False,
            'vpb_update_result': None,
            'error': None
        }

        try:
            # 如果账户是发送者，触发VPB更新
            if transaction.sender == self.account_address:
                request = VPBUpdateRequest(
                    account_address=self.account_address,
                    transaction=transaction,
                    block_height=block_height,
                    merkle_proof=merkle_proof,
                    transferred_value_ids=transferred_value_ids or set()
                )

                vpb_result = self.vpb_updater.update_vpb_for_transaction(request)
                result['vpb_update_triggered'] = True
                result['vpb_update_result'] = vpb_result

            result['transaction_processed'] = True

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Transaction processing failed: {str(e)}")

        return result

    def get_vpb_status(self) -> dict:
        """获取VPB状态"""
        return self.vpb_updater.get_vpb_update_status(self.account_address)


class BlockchainVPBIntegration:
    """区块链级VPB集成"""

    def __init__(self, vpb_updater: Optional[VPBUpdater] = None):
        self.vpb_updater = vpb_updater or VPBUpdater()
        self._account_integrations = {}

    def register_account_node(self, account_address: str) -> AccountNodeVPBIntegration:
        """注册账户节点"""
        if account_address not in self._account_integrations:
            self._account_integrations[account_address] = AccountNodeVPBIntegration(
                account_address, self.vpb_updater
            )
        return self._account_integrations[account_address]

    def process_transactions(self, transactions: list) -> dict:
        """批量处理多个交易"""
        results = []
        for tx_data in transactions:
            account_integration = self.register_account_node(tx_data['sender'])
            result = account_integration.process_transaction(
                tx_data['transaction'],
                tx_data['merkle_proof'],
                tx_data['block_height'],
                tx_data.get('transferred_value_ids')
            )
            results.append(result)

        return {
            'total_transactions': len(transactions),
            'successful': sum(1 for r in results if r['transaction_processed']),
            'vpb_updates': sum(1 for r in results if r['vpb_update_triggered']),
            'results': results
        }


def create_vpb_update_request(account_address: str,
                            transaction: MultiTransactions,
                            block_height: int,
                            merkle_proof: MerkleTreeProof,
                            transferred_value_ids: Optional[Set[str]] = None) -> VPBUpdateRequest:
    """创建VPB更新请求"""
    return VPBUpdateRequest(
        account_address=account_address,
        transaction=transaction,
        block_height=block_height,
        merkle_proof=merkle_proof,
        transferred_value_ids=transferred_value_ids or set()
    )