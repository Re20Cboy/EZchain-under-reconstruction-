"""
VPBPairs Module - EZChain VPB管理核心组件

This module implements the VPB (Value-Proofs-BlockIndex) management system
as specified in the VPB design document. It establishes one-to-one mappings
between Values, Proofs, and BlockIndexLists, providing comprehensive
VPB lifecycle management with persistent storage.

Key Features:
- One-to-one V-P-B correspondence management
- Persistent storage with SQLite backend
- Integration with AccountPickValues for value selection
- Complete VPB lifecycle management (add, remove, update, query)
- Thread-safe operations with proper locking
- Integrity validation and verification
"""

import sqlite3
import json
import os
import threading
from typing import Dict, List, Optional, Tuple, Any, TYPE_CHECKING
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from .values.Value import Value, ValueState
from .values.AccountValueCollection import AccountValueCollection
from .values.AccountPickValues import AccountPickValues
from .proofs.Proofs import Proofs, LegacyProofsStorage as ProofsStorage
from .block_index.BlockIndexList import BlockIndexList
# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions

def _get_create_multi_transactions_class():
    """延迟导入CreateMultiTransactions类以避免循环依赖"""
    from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
    return CreateMultiTransactions

class VPBStorage:
    """VPB永久存储管理器，使用SQLite提供持久化存储

    重构说明：集成ProofsStorage，确保Proofs数据的完整存储和加载。
    """

    def __init__(self, db_path: str = "ez_vpb_storage.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        # 集成ProofsStorage，复用其存储能力
        self.proofs_storage = ProofsStorage(db_path)
        self._init_database()

    def _init_database(self):
        """初始化SQLite数据库表结构"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # VPB三元组主表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vpb_triplets (
                        vpb_id TEXT PRIMARY KEY,
                        value_id TEXT NOT NULL,
                        proofs_id TEXT NOT NULL,
                        block_index_list_id TEXT NOT NULL,
                        account_address TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Value数据表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vpb_values (
                        value_id TEXT PRIMARY KEY,
                        begin_index TEXT NOT NULL,
                        end_index TEXT NOT NULL,
                        value_num INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        vpb_id TEXT NOT NULL,
                        FOREIGN KEY (vpb_id) REFERENCES vpb_triplets (vpb_id)
                    )
                """)

                # BlockIndexList数据表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vpb_block_index_lists (
                        list_id TEXT PRIMARY KEY,
                        index_lst TEXT NOT NULL,
                        owner_data TEXT NOT NULL,
                        vpb_id TEXT NOT NULL,
                        FOREIGN KEY (vpb_id) REFERENCES vpb_triplets (vpb_id)
                    )
                """)

                # 创建索引
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vpb_account ON vpb_triplets(account_address)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_value_state ON vpb_values(state)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vpb_created ON vpb_triplets(created_at)")

                conn.commit()

    def store_vpb_triplet(self, vpb_id: str, value: Value, proofs: Proofs,
                         block_index_lst: BlockIndexList, account_address: str) -> bool:
        """存储完整的VPB三元组"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    # 存储VPB三元组关系
                    conn.execute("""
                        INSERT OR REPLACE INTO vpb_triplets
                        (vpb_id, value_id, proofs_id, block_index_list_id, account_address, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (vpb_id, value.begin_index, proofs.value_id,
                          f"block_list_{vpb_id}", account_address, datetime.now()))

                    # 存储Value数据
                    conn.execute("""
                        INSERT OR REPLACE INTO vpb_values
                        (value_id, begin_index, end_index, value_num, state, vpb_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (value.begin_index, value.begin_index, value.end_index,
                          value.value_num, value.state.value, vpb_id))

                    # 存储BlockIndexList数据
                    conn.execute("""
                        INSERT OR REPLACE INTO vpb_block_index_lists
                        (list_id, index_lst, owner_data, vpb_id)
                        VALUES (?, ?, ?, ?)
                    """, (f"block_list_{vpb_id}", json.dumps(block_index_lst.index_lst),
                          json.dumps(block_index_lst.owner), vpb_id))

                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error storing VPB triplet: {e}")
            return False

    def load_vpb_triplet(self, vpb_id: str) -> Optional[Tuple[str, Proofs, BlockIndexList, str]]:
        """从数据库加载VPB三元组

        重构说明：返回Value ID而不是Value对象，由VPBManager负责获取Value对象。
        """
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    # 获取VPB基本信息
                    cursor = conn.execute("""
                        SELECT value_id, proofs_id, account_address
                        FROM vpb_triplets WHERE vpb_id = ?
                    """, (vpb_id,))

                    vpb_data = cursor.fetchone()
                    if not vpb_data:
                        return None

                    value_id, _, account_address = vpb_data

                    # 加载Proofs（通过集成的ProofsStorage，确保数据完整性）
                    proofs = Proofs(value_id, self.proofs_storage)

                    # 加载BlockIndexList数据
                    cursor = conn.execute("""
                        SELECT index_lst, owner_data
                        FROM vpb_block_index_lists WHERE vpb_id = ?
                    """, (vpb_id,))

                    block_data = cursor.fetchone()
                    if not block_data:
                        return None

                    index_lst_json, owner_data_json = block_data
                    index_lst = json.loads(index_lst_json)
                    owner_data = json.loads(owner_data_json)

                    # 确保owner_data格式正确
                    if not isinstance(owner_data, list):
                        owner_data = []

                    # 验证每个owner条目的格式
                    valid_owner_data = []
                    for item in owner_data:
                        if (isinstance(item, list) and len(item) == 2 and
                            isinstance(item[0], int) and isinstance(item[1], str)):
                            valid_owner_data.append((item[0], item[1]))
                        elif (isinstance(item, tuple) and len(item) == 2 and
                              isinstance(item[0], int) and isinstance(item[1], str)):
                            valid_owner_data.append(item)

                    block_index_lst = BlockIndexList(index_lst, valid_owner_data)

                    return (value_id, proofs, block_index_lst, account_address)

        except Exception as e:
            print(f"Error loading VPB triplet: {e}")
            return None

    def delete_vpb_triplet(self, vpb_id: str) -> bool:
        """删除VPB三元组"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    # 删除相关的所有数据
                    conn.execute("DELETE FROM vpb_values WHERE vpb_id = ?", (vpb_id,))
                    conn.execute("DELETE FROM vpb_block_index_lists WHERE vpb_id = ?", (vpb_id,))
                    cursor = conn.execute("DELETE FROM vpb_triplets WHERE vpb_id = ?", (vpb_id,))
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting VPB triplet: {e}")
            return False

    def get_all_vpb_ids_for_account(self, account_address: str) -> List[str]:
        """获取指定账户的所有VPB ID"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT vpb_id FROM vpb_triplets
                        WHERE account_address = ? ORDER BY created_at
                    """, (account_address,))
                    return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting VPB IDs for account: {e}")
            return []

    def get_vpbs_by_value_state(self, account_address: str, state: ValueState) -> List[str]:
        """根据Value状态获取VPB ID列表"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT v.vpb_id FROM vpb_triplets v
                        JOIN vpb_values val ON v.value_id = val.value_id
                        WHERE v.account_address = ? AND val.state = ?
                        ORDER BY val.begin_index
                    """, (account_address, state.value))
                    return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting VPBs by value state: {e}")
            return []


class VPBPair:
    """VPB三元组对象，表示Value-Proofs-BlockIndexList的一一对应关系

    重构说明：不再直接存储Value对象，而是通过Value ID和ValueCollection
    动态获取Value，确保数据一致性。
    """

    def __init__(self, value_id: str, proofs: Proofs, block_index_lst: BlockIndexList,
                 value_collection: AccountValueCollection, vpb_id: str = None):
        """初始化VPB三元组

        Args:
            value_id: Value的唯一标识符（通常是begin_index）
            proofs: Proofs对象
            block_index_lst: BlockIndexList对象
            value_collection: AccountValueCollection的引用，用于动态获取Value
            vpb_id: 可选的VPB ID，如果不提供则自动生成
        """
        self.value_id = value_id
        self.proofs = proofs
        self.block_index_lst = block_index_lst
        self.value_collection = value_collection
        self.vpb_id = vpb_id or self._generate_vpb_id()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    @property
    def value(self) -> Optional[Value]:
        """动态获取Value对象，确保数据一致性"""
        return self.value_collection.get_value_by_id(self.value_id)

    def _generate_vpb_id(self) -> str:
        """生成唯一的VPB ID"""
        import hashlib
        content = f"{self.value_id}_{datetime.now().isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def update_proofs(self, new_proofs: Proofs) -> bool:
        """更新Proofs组件"""
        if new_proofs.value_id != self.proofs.value_id:
            return False
        self.proofs = new_proofs
        self.updated_at = datetime.now()
        return True

    def update_block_index_list(self, new_block_index_lst: BlockIndexList) -> bool:
        """更新BlockIndexList组件"""
        self.block_index_lst = new_block_index_lst
        self.updated_at = datetime.now()
        return True

    def is_valid_vpb(self) -> bool:
        """验证VPB三元组的一致性"""
        # 检查各组件是否存在（使用is None而不是布尔值）
        if self.value_collection is None or self.proofs is None or self.block_index_lst is None:
            return False

        # 检查Value是否存在
        value = self.value
        if value is None:
            return False

        # 检查Value状态
        if not isinstance(value.state, ValueState):
            return False

        # 检查Proofs是否与Value匹配
        if self.proofs.value_id != self.value_id:
            return False

        # 检查BlockIndexList数据完整性
        if not self.block_index_lst.index_lst:
            return False

        return True

    def to_dict(self) -> dict:
        """转换为字典格式"""
        value = self.value
        value_data = value.to_dict() if value else None

        try:
            proofs_count = len(self.proofs.get_proof_units())
        except:
            proofs_count = 0

        return {
            'vpb_id': self.vpb_id,
            'value_id': self.value_id,
            'value': value_data,
            'proofs_count': proofs_count,
            'block_index_list': self.block_index_lst.to_dict(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class VPBManager:
    """VPB管理器 - 管理VPB的渠道

    重构说明：统一VPB管理入口，确保Value和Proofs数据的一致性。
    """

    def __init__(self, account_address: str = None, storage: Optional[VPBStorage] = None,
                 value_collection: Optional[AccountValueCollection] = None):
        self.account_address = account_address
        self.storage = storage or VPBStorage()
        self._lock = threading.RLock()

        # VPB映射表：value_id -> VPBPair
        self._vpb_map: Dict[str, VPBPair] = {}

        # AccountValueCollection（统一管理入口）
        self._value_collection = value_collection

        # AccountPickValues实例
        self._value_selector: Optional[AccountPickValues] = None

        # 初始化AccountPickValues（使用is not None而不是布尔值检查）
        try:
            if self._value_collection is not None and account_address:
                self._value_selector = AccountPickValues(account_address, self._value_collection)
                # 加载现有VPB数据
                self._load_existing_vpbs()
            elif self._value_collection is not None:
                # 即使没有account_address，也应该初始化_value_selector
                self._value_selector = AccountPickValues("", self._value_collection)
                print("Warning: VPBManager initialized without account_address")
        except Exception as e:
            print(f"Warning: Failed to initialize AccountPickValues: {e}")
            self._value_selector = None

    def set_account_address(self, address: str):
        """设置账户地址并加载现有VPB"""
        self.account_address = address
        if self._value_collection:
            self._value_selector = AccountPickValues(address, self._value_collection)
            self._load_existing_vpbs()

    def set_value_collection(self, collection: AccountValueCollection):
        """设置AccountValueCollection"""
        self._value_collection = collection
        if self.account_address:
            self._value_selector = AccountPickValues(self.account_address, self._value_collection)
            self._load_existing_vpbs()

    def set_lock(self, lock: threading.RLock):
        """设置外部锁（用于与Account同步）"""
        self._lock = lock

    def _load_existing_vpbs(self):
        """从存储中加载现有的VPB数据"""
        if not self.account_address or not self._value_collection:
            return

        vpb_ids = self.storage.get_all_vpb_ids_for_account(self.account_address)

        for vpb_id in vpb_ids:
            vpb_data = self.storage.load_vpb_triplet(vpb_id)
            if vpb_data:
                value_id, proofs, block_index_lst, _ = vpb_data
                vpb_pair = VPBPair(value_id, proofs, block_index_lst, self._value_collection, vpb_id)
                self._vpb_map[value_id] = vpb_pair

    def add_vpb(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList) -> bool:
        """添加新的VPB对"""
        if not self.account_address or not self._value_collection:
            print("Account address or value collection not set")
            return False

        try:
            with self._lock:
                # 检查是否已存在相同Value的VPB
                if value.begin_index in self._vpb_map:
                    print(f"VPB for value {value.begin_index} already exists")
                    return False

                # 创建VPB对象（使用新的构造函数）
                vpb_pair = VPBPair(value.begin_index, proofs, block_index_lst, self._value_collection)

                # 存储到数据库
                if self.storage.store_vpb_triplet(
                    vpb_pair.vpb_id, value, proofs, block_index_lst, self.account_address
                ):
                    # 添加到内存映射
                    self._vpb_map[value.begin_index] = vpb_pair
                    print(f"VPB added: {vpb_pair.vpb_id[:16]}...")
                    return True
                else:
                    print(f"Failed to store VPB: {vpb_pair.vpb_id[:16]}...")
                    return False

        except Exception as e:
            print(f"Error adding VPB: {e}")
            return False

    def remove_vpb(self, value: Value) -> bool:
        """删除VPB对"""
        try:
            with self._lock:
                if value.begin_index not in self._vpb_map:
                    return False

                vpb_pair = self._vpb_map[value.begin_index]

                # 从数据库删除
                if self.storage.delete_vpb_triplet(vpb_pair.vpb_id):
                    # 从内存映射删除
                    del self._vpb_map[value.begin_index]
                    print(f"VPB removed: {vpb_pair.vpb_id[:16]}...")
                    return True
                else:
                    print(f"Failed to remove VPB: {vpb_pair.vpb_id[:16]}...")
                    return False

        except Exception as e:
            print(f"Error removing VPB: {e}")
            return False

    def get_vpb(self, value: Value) -> Optional[VPBPair]:
        """查询特定Value的VPB"""
        return self._vpb_map.get(value.begin_index)

    def get_vpb_by_id(self, value_id: str) -> Optional[VPBPair]:
        """根据Value ID查询VPB"""
        return self._vpb_map.get(value_id)

    def get_all_vpbs(self) -> Dict[str, VPBPair]:
        """获取所有VPB"""
        return dict(self._vpb_map)

    def get_vpbs_by_state(self, state: ValueState) -> List[VPBPair]:
        """根据Value状态获取VPB列表"""
        result = []
        for vpb in self._vpb_map.values():
            value = vpb.value
            if value and value.state == state:
                result.append(vpb)
        return result

    def update_vpb(self, value: Value, new_proofs: Optional[Proofs] = None,
                   new_block_index_lst: Optional[BlockIndexList] = None) -> bool:
        """编辑VPB对"""
        try:
            with self._lock:
                if value.begin_index not in self._vpb_map:
                    return False

                vpb_pair = self._vpb_map[value.begin_index]

                # 更新Proofs
                if new_proofs:
                    if not vpb_pair.update_proofs(new_proofs):
                        return False

                # 更新BlockIndexList
                if new_block_index_lst:
                    if not vpb_pair.update_block_index_list(new_block_index_lst):
                        return False

                # 重新存储到数据库
                success = self.storage.store_vpb_triplet(
                    vpb_pair.vpb_id, value, vpb_pair.proofs,
                    vpb_pair.block_index_lst, self.account_address
                )

                if success:
                    print(f"VPB updated: {vpb_pair.vpb_id[:16]}...")

                return success

        except Exception as e:
            print(f"Error updating VPB: {e}")
            return False

    def pick_values_for_transaction(self, required_amount: int, sender: str,
                                  recipient: str, nonce: int, time: str) -> Optional[Dict]:
        """集成AccountPickValues的值选择功能"""
        if not self._value_selector:
            print("Value selector not initialized")
            return None

        try:
            # 使用AccountPickValues选择值
            selected_values, change_value, change_txn, main_txn = self._value_selector.pick_values_for_transaction(
                required_amount, sender, recipient, nonce, time
            )

            # 获取选中值的VPB信息
            selected_vpbs = {}
            for value in selected_values:
                vpb = self.get_vpb(value)
                if vpb:
                    selected_vpbs[value.begin_index] = vpb

            return {
                'selected_values': selected_values,
                'change_value': change_value,
                'change_transaction': change_txn,
                'main_transaction': main_txn,
                'selected_vpbs': selected_vpbs
            }

        except Exception as e:
            print(f"Error picking values for transaction: {e}")
            return None

    def commit_transaction_values(self, selected_values: List[Value]) -> bool:
        """提交交易值状态"""
        if not self._value_selector:
            return False
        return self._value_selector.commit_transaction_values(selected_values)

    def rollback_transaction_selection(self, selected_values: List[Value]) -> bool:
        """回滚交易选择"""
        if not self._value_selector:
            return False
        return self._value_selector.rollback_transaction_selection(selected_values)

    def validate_vpb_consistency(self) -> bool:
        """验证所有VPB的一致性"""
        try:
            with self._lock:
                for vpb_pair in self._vpb_map.values():
                    if not vpb_pair.is_valid_vpb():
                        print(f"Invalid VPB found: {vpb_pair.vpb_id[:16]}...")
                        return False
                return True
        except Exception as e:
            print(f"Error validating VPB consistency: {e}")
            return False

    def clear_all_vpbs(self) -> bool:
        """清除所有VPB"""
        try:
            with self._lock:
                success = True
                for vpb_pair in list(self._vpb_map.values()):
                    if not self.storage.delete_vpb_triplet(vpb_pair.vpb_id):
                        success = False

                self._vpb_map.clear()
                return success
        except Exception as e:
            print(f"Error clearing all VPBs: {e}")
            return False

    def get_vpb_statistics(self) -> Dict[str, int]:
        """获取VPB统计信息"""
        stats = {}
        for state in ValueState:
            stats[state.value] = len(self.get_vpbs_by_state(state))
        stats['total'] = len(self._vpb_map)
        return stats

    def export_vpbs_to_dict(self) -> Dict[str, Any]:
        """导出所有VPB为字典格式（用于备份/迁移）"""
        return {
            'account_address': self.account_address,
            'export_timestamp': datetime.now().isoformat(),
            'vpbs': {vpb_id: vpb.to_dict() for vpb_id, vpb in self._vpb_map.items()},
            'statistics': self.get_vpb_statistics()
        }


class VPBPairs:
    """
    VPBPairs主类 - Account管理VPB的统一接口

    这是Account与VPB系统交互的唯一入口点，提供完整的VPB生命周期管理、
    交易支持、持久化存储和状态查询功能。

    核心职责：
    1. 作为Account的统一VPB管理接口
    2. 协调VPBManager进行具体业务逻辑处理
    3. 提供简洁一致的API供Account调用
    4. 确保VPB数据的完整性和一致性
    """

    def __init__(self, account_address: str, value_collection: Optional[AccountValueCollection] = None):
        """
        初始化VPBPairs

        Args:
            account_address: 账户地址，用于标识VPB的所有者
            value_collection: 可选的AccountValueCollection实例，如果不提供则自动创建
        """
        self.account_address = account_address
        self.storage = VPBStorage()

        # 如果没有提供ValueCollection，则创建一个
        if value_collection is None:
            from .values.AccountValueCollection import AccountValueCollection
            value_collection = AccountValueCollection(account_address)

        self.manager = VPBManager(account_address, self.storage, value_collection)

        print(f"VPBPairs initialized for account: {account_address[:16]}...")

    # ========== VPB生命周期管理接口 ==========

    def add_vpb(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList) -> bool:
        """
        添加新的VPB三元组

        建立Value-Proofs-BlockIndexList的一一对应关系并持久化存储

        Args:
            value: Value对象
            proofs: 对应的Proofs对象
            block_index_lst: 对应的BlockIndexList对象

        Returns:
            bool: 添加成功返回True，失败返回False
        """
        return self.manager.add_vpb(value, proofs, block_index_lst)

    def remove_vpb(self, value: Value) -> bool:
        """
        删除指定的VPB三元组

        Args:
            value: 要删除的Value对象

        Returns:
            bool: 删除成功返回True，失败返回False
        """
        return self.manager.remove_vpb(value)

    def get_vpb(self, value: Value) -> Optional[VPBPair]:
        """
        获取指定Value对应的VPB三元组

        Args:
            value: Value对象

        Returns:
            Optional[VPBPair]: VPB三元组，如果不存在返回None
        """
        return self.manager.get_vpb(value)

    def get_vpb_by_id(self, value_id: str) -> Optional[VPBPair]:
        """
        根据Value ID获取VPB三元组

        Args:
            value_id: Value的唯一标识符（begin_index）

        Returns:
            Optional[VPBPair]: VPB三元组，如果不存在返回None
        """
        return self.manager.get_vpb_by_id(value_id)

    def update_vpb(self, value: Value, new_proofs: Optional[Proofs] = None,
                   new_block_index_lst: Optional[BlockIndexList] = None) -> bool:
        """
        更新VPB三元组中的Proofs或BlockIndexList组件

        在交易过程中，Value对应的Proofs和BlockIndexList会不断变化，
        此接口提供更新功能以保持数据一致性。

        Args:
            value: 要更新的Value对象
            new_proofs: 新的Proofs对象（可选）
            new_block_index_lst: 新的BlockIndexList对象（可选）

        Returns:
            bool: 更新成功返回True，失败返回False
        """
        return self.manager.update_vpb(value, new_proofs, new_block_index_lst)

    # ========== 批量查询和状态管理接口 ==========

    def get_all_vpbs(self) -> Dict[str, VPBPair]:
        """
        获取账户的所有VPB三元组

        Returns:
            Dict[str, VPBPair]: 所有VPB的字典，key为value_id
        """
        return self.manager.get_all_vpbs()

    def get_vpbs_by_state(self, state: ValueState) -> List[VPBPair]:
        """
        根据Value状态获取VPB列表

        Args:
            state: Value状态枚举

        Returns:
            List[VPBPair]: 指定状态的VPB列表
        """
        return self.manager.get_vpbs_by_state(state)

    def validate_all_vpbs(self) -> bool:
        """
        验证所有VPB的完整性和一致性

        检查每个VPB的三元组关系是否正确，数据是否完整

        Returns:
            bool: 所有VPB都有效返回True，否则返回False
        """
        return self.manager.validate_vpb_consistency()

    # ========== 交易支持接口 ==========

    def pick_values_for_transaction(self, required_amount: int, sender: str,
                                  recipient: str, nonce: int, time: str) -> Optional[Dict]:
        """
        为交易选择最优的Value组合

        集成AccountPickValues算法，为交易选择合适的Value，
        并返回对应的VPB信息和交易数据。

        Args:
            required_amount: 交易需要的金额
            sender: 发送方地址
            recipient: 接收方地址
            nonce: 交易随机数
            time: 交易时间戳

        Returns:
            Optional[Dict]: 包含选中Value、VPB信息和交易数据的字典，
                          如果选择失败返回None
        """
        return self.manager.pick_values_for_transaction(
            required_amount, sender, recipient, nonce, time
        )

    def commit_transaction(self, selected_values: List[Value]) -> bool:
        """
        提交交易，更新Value状态

        在交易确认后调用，更新相关Value的状态为已消费

        Args:
            selected_values: 交易中使用的Value列表

        Returns:
            bool: 提交成功返回True，失败返回False
        """
        return self.manager.commit_transaction_values(selected_values)

    def rollback_transaction(self, selected_values: List[Value]) -> bool:
        """
        回滚交易选择，恢复Value状态

        在交易失败时调用，恢复选中Value的状态为可用

        Args:
            selected_values: 之前选择的Value列表

        Returns:
            bool: 回滚成功返回True，失败返回False
        """
        return self.manager.rollback_transaction_selection(selected_values)

    # ========== 统计和导出接口 ==========

    def get_statistics(self) -> Dict[str, int]:
        """
        获取VPB统计信息

        Returns:
            Dict[str, int]: 包含各状态VPB数量和总数的统计字典
        """
        return self.manager.get_vpb_statistics()

    def export_data(self) -> Dict[str, Any]:
        """
        导出所有VPB数据

        用于备份、迁移或数据分析

        Returns:
            Dict[str, Any]: 包含所有VPB数据的完整字典
        """
        return self.manager.export_vpbs_to_dict()

    # ========== 资源管理接口 ==========

    def cleanup(self):
        """清理资源，删除所有VPB数据"""
        self.manager.clear_all_vpbs()
        print("VPBPairs cleaned up")

    # ========== 直接访问管理器接口（高级用法） ==========

    @property
    def vpb_manager(self) -> VPBManager:
        """
        获取底层VPBManager实例

        供需要更精细控制的场景使用，一般情况下不建议直接调用
        """
        return self.manager

    def set_external_lock(self, lock: threading.RLock):
        """
        设置外部锁，与Account的锁机制同步

        Args:
            lock: 外部提供的RLock实例
        """
        self.manager.set_lock(lock)

    # ========== Value管理接口（通过VPBPairs统一管理） ==========

    def get_value_collection(self) -> AccountValueCollection:
        """
        获取底层ValueCollection实例（只读访问）

        Returns:
            AccountValueCollection实例
        """
        return self.manager._value_collection

    def add_value(self, value: Value, proofs: Optional[Proofs] = None,
                  block_index_lst: Optional[BlockIndexList] = None,
                  position: str = "end") -> bool:
        """
        添加Value到ValueCollection，可选择同时创建VPB

        Args:
            value: Value对象
            proofs: 可选的Proofs对象
            block_index_lst: 可选的BlockIndexList对象
            position: 添加位置 ("start" 或 "end")

        Returns:
            bool: 添加成功返回True
        """
        # 首先添加到ValueCollection
        success = self.manager._value_collection.add_value(value, position)

        # 如果提供了VPB信息，同时创建VPB
        if success and proofs is not None and block_index_lst is not None:
            return self.add_vpb(value, proofs, block_index_lst)

        return success

    def get_values(self, state: Optional[ValueState] = None) -> List[Value]:
        """
        获取ValueCollection中的Value

        Args:
            state: 可选的状态过滤器

        Returns:
            List of Value objects
        """
        if state is None:
            return self.manager._value_collection.get_all_values()
        return self.manager._value_collection.find_by_state(state)

    def get_balance(self, state: ValueState = ValueState.UNSPENT) -> int:
        """
        获取指定状态的Value余额

        Args:
            state: Value状态

        Returns:
            int: 总余额
        """
        values = self.get_values(state)
        return sum(value.value_num for value in values)

    def get_all_balances(self) -> Dict[str, int]:
        """
        获取所有状态的余额

        Returns:
            Dict[str, int]: 各状态的余额字典
        """
        balances = {}
        for state in ValueState:
            balances[state.name] = self.get_balance(state)
        return balances

    # ========== 交易相关组件访问 ==========

    def get_transaction_creator(self) -> 'CreateMultiTransactions':
        """
        获取CreateMultiTransactions实例

        Returns:
            CreateMultiTransactions实例
        """
        # 通过VPBManager获取transaction_creator
        if hasattr(self.manager, '_value_selector') and self.manager._value_selector:
            # 通过value_selector间接访问transaction_creator的逻辑
            pass

        # 如果VPBManager没有直接暴露transaction_creator，我们需要创建一个新的
        if not hasattr(self, '_transaction_creator'):
            self._transaction_creator = CreateMultiTransactions(
                self.account_address,
                self.manager._value_collection
            )

        return self._transaction_creator


# 向后兼容性别名
VPBpair = VPBPair


# ========== 使用示例 ==========
"""
Account使用VPBPairs的典型示例：

```python
class Account:
    def __init__(self, address: str):
        self.address = address
        self.value_collection = AccountValueCollection()

        # VPBPairs作为Account管理VPB的唯一入口
        self.vpb_pairs = VPBPairs(address, self.value_collection)

        # 设置共享锁确保线程安全
        self._lock = threading.RLock()
        self.vpb_pairs.set_external_lock(self._lock)

    def add_new_value(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList):
        # 添加新的VPB三元组
        return self.vpb_pairs.add_vpb(value, proofs, block_index_lst)

    def create_transaction(self, amount: int, recipient: str):
        # 使用VPBPairs选择交易值
        result = self.vpb_pairs.pick_values_for_transaction(
            amount, self.address, recipient, self.get_next_nonce(),
            datetime.now().isoformat()
        )

        if result:
            # 提交交易
            self.vpb_pairs.commit_transaction(result['selected_values'])
            return result['main_transaction']
        return None

    def get_available_balance(self) -> int:
        # 获取可用余额
        available_vpbs = self.vpb_pairs.get_vpbs_by_state(ValueState.AVAILABLE)
        return sum(vpb.value.value_num for vpb in available_vpbs if vpb.value)

    def validate_account_data(self) -> bool:
        # 验证账户所有VPB的完整性
        return self.vpb_pairs.validate_all_vpbs()
```

VPBPairs设计总结：

1. **统一接口**：VPBPairs作为Account与VPB系统交互的唯一入口
2. **完整功能**：提供VPB生命周期管理、交易支持、状态查询等全部功能
3. **清晰分层**：VPBPairs(接口层) → VPBManager(业务层) → VPBStorage(数据层)
4. **线程安全**：支持外部锁机制，确保与Account的并发安全
5. **持久化**：内置SQLite存储，支持数据恢复和迁移
6. **易用性**：提供简洁一致的API，降低使用复杂度

这样的设计完全符合VPB design.md的要求，为Account提供了强大而易用的VPB管理能力。
"""