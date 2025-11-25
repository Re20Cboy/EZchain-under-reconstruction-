import os
import sys
from typing import List, Optional, Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from values.Value import Value, ValueState
from values.AccountValueCollection import AccountValueCollection
from proofs.AccountProofManager import AccountProofManager
from proofs.ProofUnit import ProofUnit
from block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof


class VPBManager:
    """
    VPB管理器 - Account进行Value-Proofs-BlockIndex管理的唯一接口

    根据设计文档，VPB管理器为Account提供统一的存储、操作V、P、B的接口。
    VPB在逻辑上是一一对应的：一个Value对应一组Proofs和一个BlockIndex。
    """

    def __init__(self, account_address: str):
        """
        初始化VPB管理器

        Args:
            account_address: 账户地址
        """
        self.account_address = account_address

        # 初始化三个核心组件
        self.value_collection = AccountValueCollection(account_address)
        self.proof_manager = AccountProofManager(account_address)

        # BlockIndex管理器 - 使用字典存储node_id到BlockIndexList的映射
        self._block_indices: Dict[str, BlockIndexList] = {}

        # 维护node_id到value_id的映射关系
        self._node_id_to_value_id: Dict[str, str] = {}

        print(f"VPBManager initialized for account: {account_address}")

    # ==================== 操作1：从创世块初始化 ====================

    def initialize_from_genesis(self, genesis_value: Value, genesis_proof_units: List[ProofUnit],
                                genesis_block_index: BlockIndexList) -> bool:
        """
        从创世块处获得最初始的Value、Proofs、BlockIndex

        Args:
            genesis_value: 创世Value
            genesis_proof_units: 创世Proofs列表
            genesis_block_index: 创世BlockIndex（块高度为0，owner为当前账户）

        Returns:
            bool: 初始化是否成功
        """
        try:
            print(f"Initializing VPB for {self.account_address} from genesis block...")

            # 1. 添加Value到本地数据库，获取node_id
            if not self.value_collection.add_value(genesis_value):
                return False

            # 获取添加后生成的node_id
            node_id = self._get_node_id_for_value(genesis_value)
            if not node_id:
                print("Error: Failed to get node_id for genesis value")
                return False

            value_id = genesis_value.begin_index
            self._node_id_to_value_id[node_id] = value_id

            # 2. 添加Value到ProofManager中，然后添加ProofUnits
            if not self.proof_manager.add_value(genesis_value):
                return False

            # 为每个ProofUnit建立映射
            for proof_unit in genesis_proof_units:
                if not self.proof_manager.add_proof_unit(value_id, proof_unit):
                    print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for genesis value {value_id}")

            # 3. 添加BlockIndex到本地数据库（使用node_id作为key）
            self._block_indices[node_id] = genesis_block_index

            print(f"Genesis initialization completed successfully for {self.account_address}")
            return True

        except Exception as e:
            print(f"Error during genesis initialization: {e}")
            return False

    # ==================== 操作2：作为sender发起交易后的修改 ====================

    def update_after_transaction_sent(self, target_value: Value,
                                     confirmed_multi_txns: MultiTransactions,
                                     mt_proof: MerkleTreeProof,
                                     block_height: int, recipient_address: str) -> bool:
        """
        account作为sender发起交易给Bob转移目标value后，对本地vpb进行相关修改操作

        Args:
            target_value: 目标Value（被转移的Value）
            confirmed_multi_txns: 已确认的MultiTransactions
            mt_proof: 默克尔树证明
            block_height: 区块高度
            recipient_address: 接收者地址

        Returns:
            bool: 更新是否成功
        """
        try:
            print(f"Updating VPB for {self.account_address} after sending transaction...")

            # 1. 获取目标Value的node_id（通过AccountValueCollection）
            target_node_id = self._get_node_id_for_value(target_value)
            if not target_node_id:
                print(f"Error: Target value not found in collection")
                return False

            target_value_id = target_value.begin_index

            # 2. 获取目标Value对应的BlockIndex
            target_block_index = self._block_indices.get(target_node_id)
            if not target_block_index:
                print(f"Error: BlockIndex for target value node {target_node_id} not found")
                return False

            # 3. 在目标BlockIndex中对index_lst添加高度h，对owner添加(h, recipient_address)
            if block_height not in target_block_index.index_lst:
                target_block_index.index_lst.append(block_height)
            target_block_index.add_ownership_change(block_height, recipient_address)

            # 4. 向本地数据库中直接新增proof unit（基于提交的MultiTransactions+默克尔树证明生成）
            new_proof_unit = ProofUnit(
                owner=self.account_address,
                owner_multi_txns=confirmed_multi_txns,
                owner_mt_proof=mt_proof
            )

            if not self.proof_manager.add_proof_unit_direct(target_value_id, new_proof_unit):
                print(f"Error: Failed to add new proof unit for target value {target_value_id}")
                return False

            # 5. 对于本地所有非目标且状态为"未花销"的value，仅在BlockIndex中添加高度h
            unspent_values = self.value_collection.find_by_state(ValueState.UNSPENT)
            for value in unspent_values:
                value_node_id = self._get_node_id_for_value(value)
                if value_node_id and value_node_id != target_node_id:  # 非目标value
                    value_block_index = self._block_indices.get(value_node_id)
                    if value_block_index and block_height not in value_block_index.index_lst:
                        value_block_index.index_lst.append(block_height)

            # 6. 对于本地所有状态为"未花销"的value（包括目标和非目标），
            # 对其proof映射新增一个对前述proof unit的映射
            all_unspent_values = self.value_collection.find_by_state(ValueState.UNSPENT)
            for value in all_unspent_values:
                value_id = value.begin_index
                self.proof_manager.add_proof_unit(value_id, new_proof_unit)

            # 7. 对目标Value进行标记为"已花销"状态更新（通过AccountValueCollection）
            if not self.value_collection.update_value_state(target_node_id, ValueState.CONFIRMED):
                print(f"Warning: Could not update target value state to CONFIRMED")

            print(f"VPB update after transaction sent completed successfully")
            return True

        except Exception as e:
            print(f"Error during VPB update after transaction sent: {e}")
            return False

    # ==================== 操作3：作为recipient接收其他account发送的vpb ====================

    def receive_vpb_from_others(self, received_value: Value, received_proof_units: List[ProofUnit],
                               received_block_index: BlockIndexList) -> bool:
        """
        account作为recipient接收其他account发送过来的vpb，将接收到的vpb添加进本地数据库

        Args:
            received_value: 接收到的Value
            received_proof_units: 接收到的Proofs列表
            received_block_index: 接收到的BlockIndex

        Returns:
            bool: 接收是否成功
        """
        try:
            print(f"Receiving VPB for {self.account_address} from other account...")

            received_node_id = self._get_node_id_for_value(received_value)
            received_value_id = received_value.begin_index

            if received_node_id:
                print(f"Value {received_value_id} already exists, merging with existing data...")

                # 1. 对proofs的proof unit挨个添加到本地数据库中，进行本地化查重
                for proof_unit in received_proof_units:
                    if not self.proof_manager.add_proof_unit(received_value_id, proof_unit):
                        print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for existing value {received_value_id}")

                # 2. 对blockIndex进行添加操作
                existing_block_index = self._block_indices.get(received_node_id)
                if existing_block_index:
                    # 合并index_lst
                    for idx in received_block_index.index_lst:
                        if idx not in existing_block_index.index_lst:
                            existing_block_index.index_lst.append(idx)

                    # 合并owner信息
                    received_owner_history = received_block_index.get_ownership_history()
                    for block_idx, owner_addr in received_owner_history:
                        existing_block_index.add_ownership_change(block_idx, owner_addr)
                else:
                    self._block_indices[received_node_id] = received_block_index

                # 3. 将此value的状态更新为"未花销"状态（通过AccountValueCollection）
                if not self.value_collection.update_value_state(received_node_id, ValueState.UNSPENT):
                    print(f"Warning: Could not update existing value state to UNSPENT")

            else:
                print(f"Value {received_value_id} does not exist, adding new value...")

                # 1. 直接添加value到本地数据库中（通过AccountValueCollection）
                if not self.value_collection.add_value(received_value):
                    return False

                # 获取添加后生成的node_id
                new_node_id = self._get_node_id_for_value(received_value)
                if not new_node_id:
                    print("Error: Failed to get node_id for new received value")
                    return False

                self._node_id_to_value_id[new_node_id] = received_value_id

                # 2. 将value添加到ProofManager中
                if not self.proof_manager.add_value(received_value):
                    return False

                # 3. 将proofs的proof unit挨个添加到本地数据库中，进行本地化查重
                for proof_unit in received_proof_units:
                    if not self.proof_manager.add_proof_unit(received_value_id, proof_unit):
                        print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for new value {received_value_id}")

                # 4. 对blockIndex进行添加操作
                self._block_indices[new_node_id] = received_block_index

                # 5. 将此value的状态更新为"未花销"状态（通过AccountValueCollection）
                if not self.value_collection.update_value_state(new_node_id, ValueState.UNSPENT):
                    print(f"Warning: Could not update new value state to UNSPENT")

            print(f"VPB reception completed successfully for value {received_value_id}")
            return True

        except Exception as e:
            print(f"Error during VPB reception: {e}")
            return False

    # ==================== 辅助方法 ====================

    def _get_node_id_for_value(self, value: Value) -> Optional[str]:
        """
        通过Value获取对应的node_id（通过AccountValueCollection）

        Args:
            value: 要查找的Value对象

        Returns:
            node_id: Value对应的node_id，如果不存在则返回None
        """
        try:
            # 通过ValueCollection的内部映射查找node_id
            for node_id, node in self.value_collection._index_map.items():
                if node.value.begin_index == value.begin_index:
                    return node_id
            return None
        except Exception as e:
            print(f"Error getting node_id for value: {e}")
            return None

    
    # ==================== 查询和管理方法 ====================

    def get_all_values(self) -> List[Value]:
        """获取账户的所有Value"""
        return self.value_collection.get_all_values()

    def get_unspent_values(self) -> List[Value]:
        """获取所有未花销的Value"""
        return self.value_collection.find_by_state(ValueState.UNSPENT)

    def get_proof_units_for_value(self, value: Value) -> List[ProofUnit]:
        """获取指定Value的所有ProofUnits"""
        value_id = value.begin_index
        return self.proof_manager.get_proof_units_for_value(value_id)

    def get_block_index_for_value(self, value: Value) -> Optional[BlockIndexList]:
        """获取指定Value的BlockIndex"""
        node_id = self._get_node_id_for_value(value)
        if node_id:
            return self._block_indices.get(node_id)
        return None

    def get_total_balance(self) -> int:
        """获取账户总余额"""
        return self.value_collection.get_total_balance()

    def get_unspent_balance(self) -> int:
        """获取账户未花销余额"""
        return self.value_collection.get_balance_by_state(ValueState.UNSPENT)

    def get_vpb_summary(self) -> Dict[str, Any]:
        """获取VPB管理器的摘要信息"""
        try:
            all_values = self.get_all_values()
            unspent_values = self.get_unspent_values()

            proof_stats = self.proof_manager.get_statistics()

            return {
                'account_address': self.account_address,
                'total_values': len(all_values),
                'unspent_values': len(unspent_values),
                'total_balance': self.get_total_balance(),
                'unspent_balance': self.get_unspent_balance(),
                'total_proof_units': proof_stats.get('total_proof_units', 0),
                'block_indices_count': len(self._block_indices)
            }
        except Exception as e:
            print(f"Error getting VPB summary: {e}")
            return {}

    def validate_vpb_integrity(self) -> bool:
        """验证VPB数据的完整性"""
        try:
            # 验证ValueCollection的完整性
            if not self.value_collection.validate_integrity():
                print("ValueCollection integrity validation failed")
                return False

            # 验证Value和BlockIndex的一致性
            for value in self.get_all_values():
                node_id = self._get_node_id_for_value(value)
                if node_id and node_id not in self._block_indices:
                    print(f"Warning: BlockIndex missing for value node {node_id}")
                    # 不强制失败，因为某些情况下可能没有BlockIndex

            # 验证node_id到value_id映射的一致性
            for node_id, value_id in self._node_id_to_value_id.items():
                if node_id not in self.value_collection._index_map:
                    print(f"Warning: node_id {node_id} mapping refers to non-existent value")
                    return False

            # 验证ProofManager的完整性（通过检查统计信息）
            proof_stats = self.proof_manager.get_statistics()
            if proof_stats.get('total_values', 0) != len(self.get_all_values()):
                print(f"Warning: ProofManager value count ({proof_stats.get('total_values', 0)}) "
                      f"does not match ValueCollection count ({len(self.get_all_values())})")

            print("VPB integrity validation completed")
            return True

        except Exception as e:
            print(f"Error during VPB integrity validation: {e}")
            return False

    def clear_all_data(self) -> bool:
        """清除所有VPB数据"""
        try:
            print(f"Clearing all VPB data for account {self.account_address}...")

            # 清除ValueCollection数据
            self.value_collection = AccountValueCollection(self.account_address)

            # 清除ProofManager数据
            if not self.proof_manager.clear_all():
                print("Warning: Failed to clear all proof manager data")
                return False
            self.proof_manager = AccountProofManager(self.account_address)

            # 清除BlockIndex数据
            self._block_indices.clear()
            self._node_id_to_value_id.clear()

            print(f"All VPB data cleared for account {self.account_address}")
            return True

        except Exception as e:
            print(f"Error clearing VPB data: {e}")
            return False

    def __str__(self) -> str:
        """字符串表示"""
        summary = self.get_vpb_summary()
        return (f"VPBManager(account={self.account_address}, "
                f"values={summary.get('total_values', 0)}, "
                f"balance={summary.get('unspent_balance', 0)})")

    def __repr__(self) -> str:
        """详细字符串表示"""
        return self.__str__()