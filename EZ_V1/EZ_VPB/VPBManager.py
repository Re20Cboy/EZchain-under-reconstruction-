import os
import sys
from typing import List, Optional, Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.proofs.AccountProofManager import AccountProofManager
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.AccountBlockIndexManager import AccountBlockIndexManager
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof


class VPBManager:
    """
    VPB管理器 - Account进行Value-Proofs-BlockIndex管理的唯一接口

    根据设计文档，VPB管理器为Account提供统一的存储、操作V、P、B的接口。
    VPB在逻辑上是一一对应的：一个Value对应一组Proofs和一个BlockIndex。
    """

    def __init__(self, account_address: str, data_directory: str = None):
        """
        初始化VPB管理器

        Args:
            account_address: 账户地址
            data_directory: 可选的自定义数据目录路径
        """
        self.account_address = account_address
        self.data_directory = data_directory

        # 为各个组件准备自定义数据库路径
        value_db_path = f"{data_directory}/ez_account_value_collection_{account_address}.db" if data_directory else None
        proof_db_path = f"{data_directory}/ez_account_proof_{account_address}.db" if data_directory else None
        block_index_db_path = f"{data_directory}/ez_account_block_index_{account_address}.db" if data_directory else None

        # 初始化三个核心组件
        self.value_collection = AccountValueCollection(account_address, db_path=value_db_path)
        self.proof_manager = AccountProofManager(account_address, db_path=proof_db_path)
        # BlockIndex管理器 - 使用专门的AccountBlockIndexManager进行持久化管理
        self.block_index_manager = AccountBlockIndexManager(account_address, db_path=block_index_db_path)

        # 维护node_id到value_id的映射关系
        self._node_id_to_value_id: Dict[str, str] = {}

        # 精简输出: print(f"VPBManager initialized for account: {account_address}")

    # ==================== 操作1：从创世块初始化 ====================

    def initialize_from_genesis_batch(self, genesis_values: List[Value], genesis_proof_units: List[ProofUnit],
                                    genesis_block_index: BlockIndexList) -> bool:
        """
        从创世块处批量获得最初始的Values、Proofs、BlockIndex

        优化版本：移除了冗余的检查，提升批量操作性能

        Args:
            genesis_values: 创世Values列表
            genesis_proof_units: 创世Proofs列表（对应所有Values）
            genesis_block_index: 创世BlockIndex（块高度为0，owner为当前账户）

        Returns:
            bool: 批量初始化是否成功
        """
        try:
            # 精简输出: print(f"Initializing VPB for {self.account_address} from genesis block with {len(genesis_values)} values...")

            if not genesis_values:
                print("Error: No genesis values provided for batch initialization")
                return False

            # 1. 批量添加所有Values到ValueCollection，直接获取node_id
            added_nodes = []
            # 在VPBManager内部直接获取添加后的node_id映射，避免重复查询
            batch_node_ids = self.value_collection.batch_add_values(genesis_values)

            # 精简输出: print(f"Batch add values returned {len(batch_node_ids)} node_ids for {len(genesis_values)} values")

            for i, genesis_value in enumerate(genesis_values):
                node_id = batch_node_ids[i] if i < len(batch_node_ids) else None
                if not node_id:
                    print(f"Error: Failed to add genesis value {genesis_value.begin_index} to collection")
                    return False

                # 直接建立映射关系
                self._node_id_to_value_id[node_id] = genesis_value.begin_index
                added_nodes.append((genesis_value, node_id))

            # 精简输出: print(f"Successfully added {len(added_nodes)} genesis values to ValueCollection")

            # 2. 批量将Value映射添加到ProofManager中（仅建立映射关系，不重复存储Value）
            # ProofManager现在只管理Value-Proof映射，Value数据由ValueCollection统一管理
            # 构建node_ids列表用于批量添加（ProofManager只需要node_id，不需要Value对象）
            node_ids = []
            for genesis_value, node_id in added_nodes:
                node_ids.append(node_id)

            if not self.proof_manager.batch_add_values(node_ids):
                print("Error: Failed to batch add value mappings to proof manager")
                return False

            # 精简输出: print(f"Successfully added value mappings to ProofManager for {len(genesis_values)} values")

            # 3. 优化ProofUnits添加 - 使用批量操作避免不必要的嵌套循环
            # 构建value_proof_pairs列表用于批量添加，使用node_id作为value_id
            value_proof_pairs = []
            if len(genesis_proof_units) == len(added_nodes):
                # 一对一映射的情况（最常见）
                for (genesis_value, node_id), proof_unit in zip(added_nodes, genesis_proof_units):
                    value_proof_pairs.append((node_id, proof_unit))
            elif len(genesis_proof_units) == 1:
                # 单个ProofUnit对应所有Values的情况
                proof_unit = genesis_proof_units[0]
                for _, node_id in added_nodes:
                    value_proof_pairs.append((node_id, proof_unit))
            else:
                # 其他情况 - 构建所有组合但使用批量添加
                for proof_unit in genesis_proof_units:
                    for _, node_id in added_nodes:
                        value_proof_pairs.append((node_id, proof_unit))

            # 使用批量添加方法提升性能
            if not self.proof_manager.batch_add_proof_units(value_proof_pairs):
                print("Error: Failed to batch add proof units to proof manager")
                return False

            # 4. 优化BlockIndex处理 - 使用AccountBlockIndexManager进行持久化管理
            for _, node_id in added_nodes:
                # 对于创世块初始化，为每个node_id添加相同的BlockIndex
                if not self.block_index_manager.add_block_index(node_id, genesis_block_index):
                    print(f"Error: Failed to add genesis block index for node {node_id}")
                    return False

            # 精简输出: print(f"Genesis batch initialization completed successfully for {self.account_address}")
            # print(f"  - Added {len(added_nodes)} values")
            # print(f"  - Added {len(genesis_proof_units)} proof units")
            # print(f"  - Created block indices for all values")
            return True

        except Exception as e:
            print(f"Error during genesis batch initialization: {e}")
            import traceback
            print(f"Detailed error: {traceback.format_exc()}")
            return False

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
            # 精简输出: print(f"Initializing VPB for {self.account_address} from genesis block...")

            # 1. 检查Value是否已存在
            existing_node_id = self._get_node_id_for_value(genesis_value)
            if existing_node_id:
                # 精简输出: print(f"Genesis value {genesis_value.begin_index} already exists, updating...")
                node_id = existing_node_id
            else:
                # 2. 添加Value到本地数据库，获取node_id
                if not self.value_collection.add_value(genesis_value):
                    print("Error: Failed to add genesis value to collection")
                    return False

                # 获取添加后生成的node_id
                node_id = self._get_node_id_for_value(genesis_value)
                if not node_id:
                    print("Error: Failed to get node_id for genesis value")
                    return False

                # 精简输出: print(f"Added genesis value with node_id: {node_id}")

            self._node_id_to_value_id[node_id] = genesis_value.begin_index

            # 3. 添加Value映射到ProofManager中（仅建立映射关系，不重复存储Value）
            if not self.proof_manager.add_value(node_id):
                print("Error: Failed to add genesis value mapping to proof manager")
                return False

            # 精简输出: print(f"Added genesis value mapping to ProofManager for node_id: {node_id}")

            # 为每个ProofUnit建立映射（使用优化的添加方法，使用node_id作为value_id）
            for proof_unit in genesis_proof_units:
                if not self.proof_manager.add_proof_unit_optimized(node_id, proof_unit):
                    # 精简输出: print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for genesis node {node_id}")
                    pass

            # 4. 添加BlockIndex到本地数据库（使用AccountBlockIndexManager）
            if self.block_index_manager.has_block_index(node_id):
                # 精简输出: print(f"Merging BlockIndex for existing node_id: {node_id}")
                # 使用AccountBlockIndexManager的合并功能
                if not self.block_index_manager.update_block_index_merge(node_id, genesis_block_index):
                    print(f"Error: Failed to merge genesis block index for existing node {node_id}")
                    return False
            else:
                if not self.block_index_manager.add_block_index(node_id, genesis_block_index):
                    print(f"Error: Failed to add genesis block index for new node {node_id}")
                    return False

            # 精简输出: print(f"Genesis initialization completed successfully for {self.account_address}")
            return True

        except Exception as e:
            print(f"Error during genesis initialization: {e}")
            return False

    # ==================== 操作2：作为sender发起交易后的修改 ====================

    def update_after_transaction_sent(self,
                                     confirmed_multi_txns: MultiTransactions,
                                     mt_proof: MerkleTreeProof,
                                     block_height: int, recipient_address: str,
                                     target_value: Optional[Value] = None) -> bool:
        """
        account作为sender发起多笔交易给recipient(s)后，对本地vpb进行批量更新操作

        根据每笔交易中的values（每笔交易中转移的value列表），统一批量更新本地vpb
        confirmed_multi_txns中有若干笔交易（txn1, txn2, ...），每笔交(如, txn1)中有若干目标值value被转移（v1, v2, ...）

        Args:
            confirmed_multi_txns: 已确认的多笔交易集合
            mt_proof: 默克尔树证明
            block_height: 区块高度
            recipient_address: 主要接收者地址（单接收者场景）或默认接收者

        Returns:
            bool: 批量更新是否成功
        """
        try:
            # 历史兼容路径：旧测试仍按单 target_value 签名调用
            if target_value is not None:
                return self._old_update_after_transaction_sent(
                    target_value=target_value,
                    confirmed_multi_txns=confirmed_multi_txns,
                    mt_proof=mt_proof,
                    block_height=block_height,
                    recipient_address=recipient_address,
                )

            # 精简输出: print(f"Updating VPB for {self.account_address} after sending {len(confirmed_multi_txns.multi_txns)} transactions...")

            # 收集所有交易中的目标值
            all_target_values = []
            txn_recipients = []

            for txn in confirmed_multi_txns.multi_txns:
                all_target_values.extend(txn.value)
                # 每笔交易可能有不同的recipient，记录下来
                txn_recipients.append(txn.recipient)

            if not all_target_values:
                # 精简输出: print("Warning: No target values found in transactions")
                return True  # 没有目标值也算成功

            # 精简输出: print(f"Found {len(all_target_values)} target values across {len(confirmed_multi_txns.multi_txns)} transactions")

            # 获取所有目标值的node_id
            target_node_ids = []
            for target_value in all_target_values:
                target_node_id = self._get_node_id_for_value(target_value)
                if target_node_id:
                    target_node_ids.append(target_node_id)
                else:
                    # 精简输出: print(f"Warning: Target value {target_value.begin_index} not found in local collection")
                    pass

            if not target_node_ids:
                print("Error: No target values found in local collection")
                return False

            target_node_ids_set = set(target_node_ids)  # 使用集合提高查找效率

            # 1. 将所有交易中的所有目标值标记为"已花销"状态
            '''for target_node_id in target_node_ids:
                if not self.value_collection.update_value_state(target_node_id, ValueState.CONFIRMED):
                    # 精简输出: print(f"Warning: Could not update target value state to CONFIRMED for node {target_node_id}")
                    pass'''

            # 精简输出: print(f"Marked {len(target_node_ids)} target values as CONFIRMED (spent)")

            # 2. 将本地VPB中的所有非目标且状态为"未花销"的值，仅在BlockIndex中添加区块高度h
            all_unspent_values = self.value_collection.find_by_state(ValueState.UNSPENT)
            non_target_count = 0

            for value in all_unspent_values:
                value_node_id = self._get_node_id_for_value(value)
                if value_node_id and value_node_id not in target_node_ids_set:
                    # 非目标未花销值，仅添加区块高度
                    if not self.block_index_manager.add_block_height_to_index(value_node_id, block_height):
                        # 精简输出: print(f"Warning: Failed to add block height to non-target value {value_node_id}")
                        pass
                    else:
                        non_target_count += 1

            # 精简输出: print(f"Added block height to {non_target_count} non-target unspent values")

            # 3. 对本地所有状态为"已花销"的目标值，通过管理器对其BlockIndex添加高度h和所有权信息
            target_updated_count = 0
            for i, target_node_id in enumerate(target_node_ids):
                # 获取对应交易的recipient（如果有多笔交易且不同recipient）
                current_recipient = txn_recipients[i] if i < len(txn_recipients) else recipient_address

                if not self.block_index_manager.add_block_height_to_index(target_node_id, block_height, current_recipient):
                    # 精简输出: print(f"Warning: Failed to add block height and ownership to target value {target_node_id}")
                    pass
                else:
                    target_updated_count += 1

            # 精简输出: print(f"Updated block index for {target_updated_count} target values with ownership changes")

            # 4. 向本地数据库中新增proof unit（基于提交的MultiTransactions+默克尔树证明生成）
            new_proof_unit = ProofUnit(
                owner=self.account_address,
                owner_multi_txns=confirmed_multi_txns,
                owner_mt_proof=mt_proof
            )

            # 为所有目标值添加新的proof unit
            proof_added_count = 0
            for target_node_id in target_node_ids:
                if self.proof_manager.add_proof_unit_optimized(target_node_id, new_proof_unit):
                    proof_added_count += 1
                else:
                    # 精简输出: print(f"Warning: Failed to add new proof unit for target value node {target_node_id}")
                    pass

            if proof_added_count == 0:
                print("Error: Failed to add proof unit to any target value")
                return False

            # 精简输出: print(f"Added new proof unit to {proof_added_count} target values")

            # 5. 对于本地所有的value，对其proof映射新增一个对上述proof unit的映射（使用优化的添加方法）
            all_values = self.value_collection.get_all_values()
            mapping_added_count = 0

            for value in all_values:
                value_node_id = self._get_node_id_for_value(value)
                if value_node_id:  # 确保找到了对应的node_id
                    if self.proof_manager.add_proof_unit_optimized(value_node_id, new_proof_unit):
                        mapping_added_count += 1
                    # 注意：这里不打印警告，因为有些值可能已经有这个proof unit，add_proof_unit_optimized会自动处理重复

            # 精简输出: print(f"Added proof unit mappings to {mapping_added_count} total values")

            # 精简输出: print(f"VPB batch update completed successfully for {self.account_address}")
            # 精简输出: print(f"  - Processed {len(confirmed_multi_txns.multi_txns)} transactions")
            # 精简输出: print(f"  - Updated {len(target_node_ids)} target values")
            # 精简输出: print(f"  - Updated {non_target_count} non-target unspent values")
            # 精简输出: print(f"  - Added proof mappings to {mapping_added_count} values")
            return True

        except Exception as e:
            print(f"Error during VPB update after transaction sent: {e}")
            import traceback
            # 精简输出: print(f"Detailed error: {traceback.format_exc()}")
            return False
        

    def _old_update_after_transaction_sent(self, target_value: Value,
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
            # 精简输出: print(f"Updating VPB for {self.account_address} after sending transaction...")

            # 1. 获取目标Value的node_id（通过AccountValueCollection）
            target_node_id = self._get_node_id_for_value(target_value)
            if not target_node_id:
                print(f"Error: Target value not found in collection")
                return False

            # 使用target_node_id作为value_id，而不是begin_index
            target_value_id = target_node_id

            # 2. 获取目标Value对应的BlockIndex
            target_block_index = self.block_index_manager.get_block_index(target_node_id)
            if not target_block_index:
                print(f"Error: BlockIndex for target value node {target_node_id} not found")
                return False

            # 3. 在目标BlockIndex中对index_lst添加高度h，对owner添加(h, recipient_address)
            # 使用AccountBlockIndexManager的专门方法添加区块高度和所有权变更
            if not self.block_index_manager.add_block_height_to_index(target_node_id, block_height, recipient_address):
                print(f"Error: Failed to add block height to target value's BlockIndex")
                return False

            # 4. 向本地数据库中直接新增proof unit（基于提交的MultiTransactions+默克尔树证明生成）
            new_proof_unit = ProofUnit(
                owner=self.account_address,
                owner_multi_txns=confirmed_multi_txns,
                owner_mt_proof=mt_proof
            )

            if not self.proof_manager.add_proof_unit_optimized(target_value_id, new_proof_unit):
                print(f"Error: Failed to add new proof unit for target value with node_id={target_value_id}")
                return False

            # 5. 对于本地所有非目标且状态为"未花销"的value，仅在BlockIndex中添加高度h
            unspent_values = self.value_collection.find_by_state(ValueState.UNSPENT)
            for value in unspent_values:
                value_node_id = self._get_node_id_for_value(value)
                if value_node_id and value_node_id != target_node_id:  # 非目标value
                    # 使用AccountBlockIndexManager添加区块高度（不改变所有权）
                    if not self.block_index_manager.add_block_height_to_index(value_node_id, block_height):
                        print(f"Warning: Failed to add block height to non-target value {value_node_id}")

            # 6. 对于本地所有状态为"未花销"的value（包括目标和非目标），
            # 对其proof映射新增一个对前述proof unit的映射（使用优化的添加方法，使用node_id作为value_id）
            all_unspent_values = self.value_collection.find_by_state(ValueState.UNSPENT)
            for value in all_unspent_values:
                value_node_id = self._get_node_id_for_value(value)
                if value_node_id:  # 确保找到了对应的node_id
                    self.proof_manager.add_proof_unit_optimized(value_node_id, new_proof_unit)

            # 7. 对目标Value进行标记为"已花销"状态更新（通过AccountValueCollection）
            if not self.value_collection.update_value_state(target_node_id, ValueState.CONFIRMED):
                print(f"Warning: Could not update target value state to CONFIRMED")

            # 精简输出: print(f"VPB update after transaction sent completed successfully")
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
            # 精简输出: print(f"Receiving VPB for {self.account_address} from other account...")

            received_node_id = self._get_node_id_for_value(received_value)

            if received_node_id:
                # 精简输出: print(f"Value {received_value.begin_index} already exists with node_id: {received_node_id}, merging with existing data...")

                # 1. 对proofs的proof unit挨个添加到本地数据库中，进行本地化查重（使用优化的添加方法）
                # 使用node_id作为value_id
                for proof_unit in received_proof_units:
                    if not self.proof_manager.add_proof_unit_optimized(received_node_id, proof_unit):
                        # 精简输出: print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for existing node {received_node_id}")
                        pass

                # 2. 对blockIndex进行添加操作
                if self.block_index_manager.has_block_index(received_node_id):
                    # 使用AccountBlockIndexManager的合并功能
                    if not self.block_index_manager.update_block_index_merge(received_node_id, received_block_index):
                        # 精简输出: print(f"Warning: Failed to merge received block index for existing node {received_node_id}")
                        pass
                else:
                    if not self.block_index_manager.add_block_index(received_node_id, received_block_index):
                        # 精简输出: print(f"Warning: Failed to add received block index for new node {received_node_id}")
                        pass

                # 3. 将此value的状态更新为"未花销"状态（通过AccountValueCollection）
                if not self.value_collection.update_value_state(received_node_id, ValueState.UNSPENT):
                    # 精简输出: print(f"Warning: Could not update existing value state to UNSPENT")
                    pass

            else:
                # 精简输出: print(f"Value {received_value.begin_index} does not exist, adding new value...")

                # 1. 直接添加value到本地数据库中（通过AccountValueCollection）
                if not self.value_collection.add_value(received_value):
                    return False

                # 获取添加后生成的node_id
                new_node_id = self._get_node_id_for_value(received_value)
                if not new_node_id:
                    print("Error: Failed to get node_id for new received value")
                    return False

                self._node_id_to_value_id[new_node_id] = received_value.begin_index

                # 2. 将value映射添加到ProofManager中（仅建立映射关系，不重复存储Value）
                if not self.proof_manager.add_value(new_node_id):
                    return False

                # 精简输出: print(f"Added received value mapping to ProofManager for node_id: {new_node_id}")

                # 3. 将proofs的proof unit挨个添加到本地数据库中，进行本地化查重（使用优化的添加方法）
                # 使用node_id作为value_id
                for proof_unit in received_proof_units:
                    if not self.proof_manager.add_proof_unit_optimized(new_node_id, proof_unit):
                        # 精简输出: print(f"Warning: Failed to add proof unit {proof_unit.unit_id} for new node {new_node_id}")
                        pass

                # 4. 对blockIndex进行添加操作
                if not self.block_index_manager.add_block_index(new_node_id, received_block_index):
                    # 精简输出: print(f"Warning: Failed to add received block index for new node {new_node_id}")
                    pass

                # 5. 将此value的状态更新为"未花销"状态（通过AccountValueCollection）
                if not self.value_collection.update_value_state(new_node_id, ValueState.UNSPENT):
                    # 精简输出: print(f"Warning: Could not update new value state to UNSPENT")
                    pass

            # 精简输出: print(f"VPB reception completed successfully for value {received_value.begin_index}")
            return True

        except Exception as e:
            print(f"Error during VPB reception: {e}")
            return False

    # ==================== 辅助方法 ====================

    def update_value_state(self, value: Value, new_state: ValueState) -> bool:
        """
        更新Value的状态（通过ValueCollection更新索引）

        Args:
            value: 要更新状态的Value对象
            new_state: 新的状态

        Returns:
            bool: 更新是否成功
        """
        try:
            node_id = self._get_node_id_for_value(value)
            if node_id:
                return self.value_collection.update_value_state(node_id, new_state)
            else:
                # 如果找不到node_id，直接更新Value对象的状态（fallback）
                value.set_state(new_state)
                return True
        except Exception as e:
            print(f"Error updating value state: {e}")
            return False

    def update_values_state(self, values: List[Value], new_state: ValueState) -> int:
        """
        批量更新多个Value的状态（通过ValueCollection更新索引）

        Args:
            values: 要更新状态的Value列表
            new_state: 新的状态

        Returns:
            int: 成功更新的Value数量
        """
        updated_count = 0
        for value in values:
            if self.update_value_state(value, new_state):
                updated_count += 1
        return updated_count

    def _get_node_id_for_value(self, value: Value) -> Optional[str]:
        """
        通过Value获取对应的node_id（通过AccountValueCollection）

        Args:
            value: 要查找的Value对象

        Returns:
            node_id: Value对应的node_id，如果不存在则返回None
        """
        try:
            # 首先尝试通过AccountValueCollection的get_value_by_id方法查找
            found_value = self.value_collection.get_value_by_id(value.begin_index)
            if found_value:
                # 如果找到了Value，通过遍历找到对应的node_id
                for node_id, node in self.value_collection._index_map.items():
                    if node.value.is_same_value(found_value):
                        return node_id

            # 如果没找到，通过遍历所有节点查找
            for node_id, node in self.value_collection._index_map.items():
                if node.value.is_same_value(value):
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
        node_id = self._get_node_id_for_value(value)
        if not node_id:
            return []
        return self.proof_manager.get_proof_units_for_value(node_id)

    def get_block_index_for_value(self, value: Value) -> Optional[BlockIndexList]:
        """获取指定Value的BlockIndex"""
        node_id = self._get_node_id_for_value(value)
        if node_id:
            return self.block_index_manager.get_block_index(node_id)
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
            block_index_stats = self.block_index_manager.get_statistics()

            return {
                'account_address': self.account_address,
                'total_values': len(all_values),
                'unspent_values': len(unspent_values),
                'total_balance': self.get_total_balance(),
                'unspent_balance': self.get_unspent_balance(),
                'total_proof_units': proof_stats.get('total_proof_units', 0),
                'block_indices_count': block_index_stats.get('total_indices', 0)
            }
        except Exception as e:
            print(f"Error getting VPB summary: {e}")
            return {}

    def print_all_values_summary(self, title: str = "Values Summary") -> None:
        """
        简洁美观地打印所有Value信息摘要

        Args:
            title: 打印标题
        """
        try:
            print(f"\n💎 {title}")
            print(f"Account: {self.account_address[:12]}...{self.account_address[-6:]}")
            print("=" * 50)

            all_values = self.get_all_values()
            if not all_values:
                print("   📝 No values found in this account")
                print("=" * 50)
                return

            # 按状态分组统计
            state_counts = {}
            state_amounts = {}
            value_details = []

            for value in all_values:
                state_name = value.state.name if hasattr(value.state, 'name') else str(value.state)
                state_counts[state_name] = state_counts.get(state_name, 0) + 1
                state_amounts[state_name] = state_amounts.get(state_name, 0) + value.value_num

                # 收集前5个和后5个Value的详细信息
                if len(value_details) < 5 or len(value_details) >= len(all_values) - 5:
                    value_details.append((state_name[0], value.value_num))

            # 打印状态统计
            print("📊 Status Distribution:")
            for state_name in sorted(state_counts.keys()):
                count = state_counts[state_name]
                amount = state_amounts[state_name]
                icon = {"UNSPENT": "🟢", "CONFIRMED": "🔴", "SPENT": "⚫"}.get(state_name, "🔵")
                print(f"   {icon} {state_name}: {count:2d} values, Amount: {amount:6d}")

            # 打印余额信息
            total_balance = self.get_total_balance()
            unspent_balance = self.get_unspent_balance()
            print(f"\n💰 Balance: Total={total_balance}, Available={unspent_balance}")

            # 打印Value样本（前3个+后3个，或全部如果少于6个）
            print(f"\n🔍 Value Samples (showing {len(value_details)} of {len(all_values)}):")
            for i, (state_char, amount) in enumerate(value_details):
                if i < 3 or i >= len(value_details) - 3:
                    print(f"   [{state_char}] {amount:4d}")
                elif i == 3:
                    print(f"   ... ({len(all_values) - len(value_details)} more) ...")

            print("=" * 50)

        except Exception as e:
            print(f"Error printing values summary: {e}")

    def visualize_confirmed_values(self, title: str = "Confirmed Values Visualization", force_show: bool = False) -> None:
        """
        可视化当前账户所有已确认状态的Value

        Args:
            title: 可视化图表的标题
            force_show: 是否强制显示，忽略环境变量设置
        """
        # 检查是否应该显示可视化输出
        if not force_show and os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() != 'true':
            return
        try:
            print(f"\n🔒 {title}")
            print(f"Account: {self.account_address}")
            print("=" * 60)

            all_values = self.get_all_values()
            confirmed_values = [v for v in all_values if v.state == ValueState.CONFIRMED]

            if not confirmed_values:
                print("   📝 No confirmed (spent) values found in this account")
                print("=" * 60)
                return

            total_confirmed_balance = sum(v.value_num for v in confirmed_values)

            print(f"🔒 Confirmed Values: {len(confirmed_values)} out of {len(all_values)} total values")
            print(f"💰 Confirmed Balance: {total_confirmed_balance}")
            print(f"📊 Percentage: {len(confirmed_values)/len(all_values)*100:.1f}% of values are confirmed")
            print()

            # 按金额排序显示
            confirmed_values_sorted = sorted(confirmed_values, key=lambda v: v.value_num, reverse=True)

            for i, value in enumerate(confirmed_values_sorted):
                print(f"🔴 Confirmed Value[{i+1:2d}]: {value.begin_index}")
                print(f"    💰 Amount: {value.value_num}")
                print(f"    📅 Status: CONFIRMED (spent)")

                # 获取关联的ProofUnits
                proof_units = self.get_proof_units_for_value(value)
                if proof_units:
                    print(f"    📜 Proof Units: {len(proof_units)} total")
                    # 显示前3个ProofUnit的信息
                    for j, proof_unit in enumerate(proof_units[:3]):
                        digest_short = (proof_unit.owner_multi_txns.digest or "None")[:12] + "..."
                        print(f"       └─ Proof[{j+1}]: {digest_short}")
                    if len(proof_units) > 3:
                        print(f"       └─ ... and {len(proof_units)-3} more proof(s)")
                else:
                    print(f"    📜 Proof Units: None")

                # 获取关联的BlockIndex
                block_index = self.get_block_index_for_value(value)
                if block_index and block_index.index_lst:
                    # 显示区块高度信息
                    heights = sorted(list(set(block_index.index_lst)))
                    print(f"    🏗️  Block Heights: {len(heights)} entries")

                    # 显示所有者历史信息
                    if hasattr(block_index, 'owner') and block_index.owner:
                        if isinstance(block_index.owner, list):
                            # 显示最近的所有者变更
                            recent_owners = block_index.owner[-3:] if len(block_index.owner) > 3 else block_index.owner
                            print(f"    👤 Recent Owners:")
                            for height, owner in recent_owners:
                                owner_short = (owner or "Unknown")[:15] + "..."
                                print(f"       └─ h{height}: {owner_short}")
                        else:
                            owner_short = str(block_index.owner)[:20] + "..."
                            print(f"    👤 Owner: {owner_short}")
                    else:
                        print(f"    👤 Owner: No owner info")
                else:
                    print(f"    🏗️  BlockIndex: Not found")

                print()  # 值与值之间的间隔

            # 显示统计信息
            avg_proof_units = sum(len(self.get_proof_units_for_value(v)) for v in confirmed_values) / len(confirmed_values)
            print(f"📈 Summary Statistics:")
            print(f"    └─ Total confirmed values: {len(confirmed_values)}")
            print(f"    └─ Total confirmed balance: {total_confirmed_balance}")
            print(f"    └─ Average proof units per confirmed value: {avg_proof_units:.1f}")
            print(f"    └─ Values with BlockIndex: {sum(1 for v in confirmed_values if self.get_block_index_for_value(v))}")
            print("=" * 60)

        except Exception as e:
            print(f"❌ Error visualizing confirmed values: {e}")
            import traceback
            traceback.print_exc()

    def visualize_vpb_mapping(self, title: str = "VPB Mapping Visualization", force_show: bool = False) -> None:
        """
        可视化当前账户的Value-Proofs-BlockIndex映射关系

        Args:
            title: 可视化图表的标题
            force_show: 是否强制显示，忽略环境变量设置
        """
        # 检查是否应该显示可视化输出
        if not force_show and os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() != 'true':
            return
        try:
            print(f"\n📊 {title}")
            print(f"Account: {self.account_address}")
            print("=" * 60)

            all_values = self.get_all_values()

            if not all_values:
                print("   📝 No values found in this account")
                print("=" * 60)
                return

            # 按状态分组Values
            unspent_values = [v for v in all_values if v.state == ValueState.UNSPENT]
            spent_values = [v for v in all_values if v.state == ValueState.CONFIRMED]

            print(f"💰 Total Values: {len(all_values)} (Unspent: {len(unspent_values)}, Spent: {len(spent_values)})")
            print(f"💎 Total Balance: {self.get_total_balance()} (Available: {self.get_unspent_balance()})")
            print()

            # 显示前N个值的详细信息，避免输出过多
            max_display = min(5, len(all_values))  # 最多显示5个值
            displayed_values = all_values[:max_display]

            for i, value in enumerate(displayed_values):
                # 获取状态图标
                status_icon = "🟢" if value.state == ValueState.UNSPENT else "🔴"
                status_text = "UNSPENT" if value.state == ValueState.UNSPENT else "CONFIRMED"

                print(f"{status_icon} Value[{i+1:2d}]: {value.begin_index} | Amount: {value.value_num:3d} | Status: {status_text}")

                # 获取关联的ProofUnits
                proof_units = self.get_proof_units_for_value(value)
                if proof_units:
                    # 只显示前4个ProofUnit的信息，避免输出过多
                    for j, proof_unit in enumerate(proof_units[:4]):
                        digest_short = (proof_unit.owner_multi_txns.digest or "None")[:16] + "..."
                        proof_length = len(proof_unit.owner_mt_proof.mt_prf_list) if proof_unit.owner_mt_proof else 0
                        print(f"    📜 Proof[{j+1}]: digest={digest_short}, proof_size={proof_length}")

                    if len(proof_units) > 4:
                        print(f"    ... and {len(proof_units)-4} more proof(s)")
                else:
                    print(f"    📜 No proofs found")

                # 获取关联的BlockIndex
                block_index = self.get_block_index_for_value(value)
                if block_index and block_index.index_lst:
                    # 显示区块高度和所有者信息
                    heights = sorted(list(set(block_index.index_lst)))  # 去重并排序
                    heights_str = ", ".join(f"h{h}" for h in heights[:5])  # 最多显示5个高度
                    if len(heights) > 5:
                        heights_str += f" ... +{len(heights)-5}"

                    # 显示所有者信息
                    if hasattr(block_index, 'owner') and block_index.owner:
                        if isinstance(block_index.owner, list):
                            owners_info = []
                            for height, owner in block_index.owner[:3]:  # 最多显示3个所有者
                                owner_short = (owner or "Unknown")[:12] + "..."
                                owners_info.append(f"h{height}:{owner_short}")
                            if len(block_index.owner) > 3:
                                owners_info.append("...")
                            owners_str = ", ".join(owners_info)
                        else:
                            owners_str = str(block_index.owner)[:20] + "..."
                    else:
                        owners_str = "No owner info"

                    print(f"    🏗️  BlockIndex: heights=[{heights_str}] | owners=[{owners_str}]")
                else:
                    print(f"    🏗️  BlockIndex: Not found")

                print()  # 值与值之间的间隔

            if len(all_values) > max_display:
                print(f"   ... and {len(all_values) - max_display} more values (not displayed)")

            # 显示统计信息
            block_index_stats = self.block_index_manager.get_statistics()
            print(f"📈 Summary: {block_index_stats.get('total_indices', 0)} BlockIndex entries, "
                  f"{sum(len(pu) for pu in [self.get_proof_units_for_value(v) for v in all_values])} total ProofUnits")
            print("=" * 60)

        except Exception as e:
            print(f"❌ Error visualizing VPB mapping: {e}")
            import traceback
            traceback.print_exc()

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
                if node_id and not self.block_index_manager.has_block_index(node_id):
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
                print(f"Warning: ProofManager value mapping count ({proof_stats.get('total_values', 0)}) "
                      f"does not match ValueCollection count ({len(self.get_all_values())})")
                # 这不是严重错误，因为ProofManager现在只管理映射关系

            # 验证映射关系的一致性
            if not self._validate_value_proof_mapping_consistency():
                print("Value-Proof mapping consistency validation failed")
                return False

            print("VPB integrity validation completed")
            return True

        except Exception as e:
            print(f"Error during VPB integrity validation: {e}")
            return False

    def _validate_value_proof_mapping_consistency(self) -> bool:
        """验证Value-Proof映射关系的一致性"""
        try:
            # 获取ValueCollection中的所有node_id
            collection_node_ids = set()
            for value in self.get_all_values():
                node_id = self._get_node_id_for_value(value)
                if node_id:
                    collection_node_ids.add(node_id)

            # 获取ProofManager中的所有Value ID (现在应该是node_id)
            proof_manager_node_ids = set(self.proof_manager.get_all_value_ids())

            # 检查一致性
            missing_in_proof_manager = collection_node_ids - proof_manager_node_ids
            extra_in_proof_manager = proof_manager_node_ids - collection_node_ids

            if missing_in_proof_manager:
                print(f"Warning: {len(missing_in_proof_manager)} values in ValueCollection but not in ProofManager")
                # 自动修复：添加缺失的映射
                for node_id in missing_in_proof_manager:
                    # 通过node_id找到对应的value
                    if node_id in self.value_collection._index_map:
                        value = self.value_collection._index_map[node_id].value
                        if value and not self.proof_manager.add_value(node_id):
                            print(f"Error: Failed to add missing mapping for node {node_id}")
                            return False
                print(f"Auto-repaired {len(missing_in_proof_manager)} missing value mappings")

            if extra_in_proof_manager:
                print(f"Warning: {len(extra_in_proof_manager)} value mappings in ProofManager but not in ValueCollection")
                # 这些可能是孤立的映射，可以清理
                for node_id in extra_in_proof_manager:
                    if not self.proof_manager.remove_value(node_id):
                        print(f"Error: Failed to remove orphan mapping for node {node_id}")
                        return False
                print(f"Auto-cleaned {len(extra_in_proof_manager)} orphan value mappings")

            return True

        except Exception as e:
            print(f"Error validating value-proof mapping consistency: {e}")
            return False

    def clear_all_data(self) -> bool:
        """清除所有VPB数据"""
        try:
            print(f"Clearing all VPB data for account {self.account_address}...")

            # 清除ValueCollection数据
            if not self.value_collection.clear_all():
                print("Warning: Failed to clear all value collection data")
                return False

            # 清除ProofManager数据
            if not self.proof_manager.clear_all():
                print("Warning: Failed to clear all proof manager data")
                return False

            # 清除BlockIndex数据
            if not self.block_index_manager.clear_all():
                print("Warning: Failed to clear all block index data")
                return False

            # 清除node_id映射
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
