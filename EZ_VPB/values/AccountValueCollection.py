from typing import List, Tuple, Optional, Dict
from collections import defaultdict
import uuid
import sqlite3
import json
import os

from .Value import Value, ValueState

class ValueNode:
    """链表节点，用于管理Value及其索引"""
    def __init__(self, value: Value, node_id: str = None):
        self.value = value
        self.node_id = node_id or str(uuid.uuid4())
        self.next = None
        self.prev = None

class AccountValueCollectionStorage:
    """
    AccountValueCollection的持久化存储管理器
    负责管理Account级别的Value数据的数据库存储和检索
    """

    def __init__(self, db_path: str = "ez_account_value_collection_storage.db"):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """初始化SQLite数据库和所需表结构"""
        with sqlite3.connect(self.db_path) as conn:
            # Accounts表 - 存储账户信息
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_address TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Values表 - 存储Value数据 (使用value_data作为表名避免SQL关键字冲突)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS value_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_address TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    begin_index TEXT NOT NULL,
                    value_num INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_address, node_id)
                )
            """)

            # 检查是否需要添加sequence字段（数据库迁移）
            self._check_and_migrate_sequence_column(conn)

            conn.commit()

    def _check_and_migrate_sequence_column(self, conn):
        """检查并迁移sequence字段"""
        try:
            # 先检查是否需要重命名旧的values表为value_data
            try:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='values'")
                old_table_exists = cursor.fetchone() is not None

                if old_table_exists:
                    # 重命名旧表
                    conn.execute("ALTER TABLE values RENAME TO value_data")
                    print("[AccountValueCollectionStorage] Renamed old 'values' table to 'value_data'")
            except Exception as rename_error:
                print(f"[AccountValueCollectionStorage] Table rename error: {rename_error}")

            # 检查value_data表是否有sequence字段
            cursor = conn.execute("PRAGMA table_info(value_data)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'sequence' not in columns:
                print("[AccountValueCollectionStorage] Migrating database: adding sequence column...")
                # 添加sequence字段
                conn.execute("ALTER TABLE value_data ADD COLUMN sequence INTEGER")

                # 为现有记录填充sequence值，按created_at排序
                cursor = conn.execute("""
                    SELECT account_address, node_id, created_at
                    FROM value_data
                    ORDER BY account_address, created_at
                """)

                current_account = None
                sequence = 0

                for row in cursor.fetchall():
                    account_address, node_id, created_at = row

                    # 如果切换到新的account，重置sequence
                    if current_account != account_address:
                        current_account = account_address
                        sequence = 0

                    sequence += 1
                    conn.execute("""
                        UPDATE value_data
                        SET sequence = ?
                        WHERE account_address = ? AND node_id = ?
                    """, (sequence, account_address, node_id))

                print("[AccountValueCollectionStorage] Database migration completed successfully")
        except Exception as e:
            print(f"[AccountValueCollectionStorage] Error during database migration: {e}")

    def ensure_account_exists(self, account_address: str) -> bool:
        """确保账户记录存在"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO accounts (account_address)
                    VALUES (?)
                """, (account_address,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error ensuring account exists: {e}")
            return False

    def store_value(self, account_address: str, node_id: str, value: Value, sequence: int = None) -> bool:
        """存储或更新Value到数据库"""
        try:
            # 确保账户存在
            if not self.ensure_account_exists(account_address):
                return False

            # 如果没有提供sequence，获取当前最大sequence值
            if sequence is None:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT COALESCE(MAX(sequence), 0) FROM value_data
                        WHERE account_address = ?
                    """, (account_address,))
                    max_sequence = cursor.fetchone()[0]
                    sequence = max_sequence + 1

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO value_data
                    (account_address, node_id, begin_index, value_num, state, sequence, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    account_address,
                    node_id,
                    value.begin_index,
                    value.value_num,
                    value.state.value if hasattr(value.state, 'value') else str(value.state),
                    sequence
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing Value: {e}")
            return False

    def load_value(self, account_address: str, node_id: str) -> Optional[Value]:
        """从数据库加载Value"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT begin_index, value_num, state FROM value_data
                    WHERE account_address = ? AND node_id = ?
                """, (account_address, node_id))

                row = cursor.fetchone()
                if row:
                    begin_index, value_num, state_str = row

                    # 将字符串状态转换回ValueState枚举
                    try:
                        if hasattr(ValueState, state_str):
                            state = getattr(ValueState, state_str)
                        else:
                            state = ValueState(state_str)  # 如果是枚举值字符串
                    except (ValueError, AttributeError):
                        state = ValueState.UNSPENT  # 默认状态

                    return Value(begin_index, value_num, state)
        except Exception as e:
            print(f"Error loading Value: {e}")
        return None

    def delete_value(self, account_address: str, node_id: str) -> bool:
        """从数据库删除Value"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM value_data
                    WHERE account_address = ? AND node_id = ?
                """, (account_address, node_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting Value: {e}")
            return False

    def get_all_values(self, account_address: str) -> List[Tuple[str, Value]]:
        """获取指定账户的所有Value（按添加顺序）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT node_id, begin_index, value_num, state FROM value_data
                    WHERE account_address = ?
                    ORDER BY sequence ASC
                """, (account_address,))

                result = []
                for row in cursor.fetchall():
                    node_id, begin_index, value_num, state_str = row
                    try:
                        # 将字符串状态转换回ValueState枚举
                        if hasattr(ValueState, state_str):
                            state = getattr(ValueState, state_str)
                        else:
                            state = ValueState(state_str)

                        value = Value(begin_index, value_num, state)
                        result.append((node_id, value))
                    except Exception as parse_error:
                        print(f"Warning: Failed to parse Value for node {node_id}: {parse_error}")
                        continue
                return result
        except Exception as e:
            print(f"Error getting all values: {e}")
            return []

    def get_values_by_state(self, account_address: str, state: ValueState) -> List[Tuple[str, Value]]:
        """获取指定账户和状态的所有Value"""
        try:
            state_str = state.value if hasattr(state, 'value') else str(state)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT node_id, begin_index, value_num, state FROM value_data
                    WHERE account_address = ? AND state = ?
                    ORDER BY sequence ASC
                """, (account_address, state_str))

                result = []
                for row in cursor.fetchall():
                    node_id, begin_index, value_num, _ = row
                    value = Value(begin_index, value_num, state)
                    result.append((node_id, value))
                return result
        except Exception as e:
            print(f"Error getting values by state: {e}")
            return []

    def remove_account_values(self, account_address: str) -> bool:
        """删除指定账户的所有Value数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM value_data
                    WHERE account_address = ?
                """, (account_address,))
                conn.commit()
                return cursor.rowcount >= 0  # 允许删除0条记录
        except Exception as e:
            print(f"Error removing account values: {e}")
            return False

    def get_statistics(self, account_address: str) -> Dict[str, int]:
        """获取指定账户的Value统计信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) as total_values,
                           COUNT(DISTINCT node_id) as unique_nodes,
                           SUM(CASE WHEN state = ? THEN 1 ELSE 0 END) as unspent_count,
                           SUM(CASE WHEN state = ? THEN 1 ELSE 0 END) as pending_count,
                           SUM(CASE WHEN state = ? THEN 1 ELSE 0 END) as onchain_count,
                           SUM(CASE WHEN state = ? THEN 1 ELSE 0 END) as confirmed_count
                    FROM value_data
                    WHERE account_address = ?
                """, (
                    ValueState.UNSPENT.value if hasattr(ValueState.UNSPENT, 'value') else str(ValueState.UNSPENT),
                    ValueState.PENDING.value if hasattr(ValueState.PENDING, 'value') else str(ValueState.PENDING),
                    ValueState.ONCHAIN.value if hasattr(ValueState.ONCHAIN, 'value') else str(ValueState.ONCHAIN),
                    ValueState.CONFIRMED.value if hasattr(ValueState.CONFIRMED, 'value') else str(ValueState.CONFIRMED),
                    account_address
                ))

                row = cursor.fetchone()
                if row:
                    total_values, unique_nodes, unspent_count, pending_count, onchain_count, confirmed_count = row
                    return {
                        'total_values': total_values,
                        'unique_nodes': unique_nodes,
                        'unspent_count': unspent_count,
                        'pending_count': pending_count,
                        'onchain_count': onchain_count,
                        'confirmed_count': confirmed_count
                    }
        except Exception as e:
            print(f"Error getting statistics: {e}")
            pass
        return {
            'total_values': 0,
            'unique_nodes': 0,
            'unspent_count': 0,
            'pending_count': 0,
            'onchain_count': 0,
            'confirmed_count': 0
        }

class AccountValueCollection:
    """账户Value集合管理类 - 使用链表结构解决index混乱问题，支持永久存储"""

    def __init__(self, account_address: str, storage: Optional[AccountValueCollectionStorage] = None, db_path: Optional[str] = None):
        self.account_address = account_address

        # 为每个AccountValueCollection创建独立的存储实例，避免对象共享
        if storage is not None:
            self.storage = storage
        else:
            # 使用唯一的数据库路径或创建新的存储实例
            if db_path:
                self.storage = AccountValueCollectionStorage(db_path)
            else:
                # 为每个账户创建独立的存储实例，使用账户名作为数据库名称的一部分
                unique_db_path = f"ez_account_value_collection_{account_address}.db"
                self.storage = AccountValueCollectionStorage(unique_db_path)

        # 内存数据结构
        self.head = None  # 链表头节点
        self.tail = None  # 链表尾节点
        self.size = 0
        self._index_map = {}  # node_id到节点的映射
        self._state_index = defaultdict(set)  # 按状态快速索引
        self._decimal_begin_map = {}  # 按起始十进制值映射，用于快速查找

        # 加载现有的Value数据
        self._load_existing_values()

    def _load_existing_values(self):
        """加载现有的Value数据到内存链表中"""
        try:
            all_values = self.storage.get_all_values(self.account_address)
            for node_id, value in all_values:
                # 创建ValueNode并添加到链表尾部
                node = ValueNode(value, node_id)

                # 添加到链表尾部，保持原有的顺序
                if self.tail is None:
                    self.head = node
                    self.tail = node
                else:
                    self.tail.next = node
                    node.prev = self.tail
                    self.tail = node

                # 更新索引
                self._index_map[node.node_id] = node
                self._state_index[value.state].add(node.node_id)
                self._decimal_begin_map[value.get_decimal_begin_index()] = node.node_id
                self.size += 1

        except Exception as e:
            print(f"Error loading existing values: {e}")

    def add_value(self, value: Value, position: str = "end") -> bool:
        """添加Value到集合中并持久化"""
        try:
            node = ValueNode(value)

            # 存储到数据库
            if not self.storage.store_value(self.account_address, node.node_id, value):
                return False

            # 更新内存链表
            if position == "end":
                if self.tail is None:
                    self.head = node
                    self.tail = node
                else:
                    self.tail.next = node
                    node.prev = self.tail
                    self.tail = node
            elif position == "beginning":
                if self.head is None:
                    self.head = node
                    self.tail = node
                else:
                    self.head.prev = node
                    node.next = self.head
                    self.head = node
            else:
                raise ValueError("position must be 'end' or 'beginning'")

            # 更新内存索引
            self._index_map[node.node_id] = node
            self._state_index[value.state].add(node.node_id)
            self._decimal_begin_map[value.get_decimal_begin_index()] = node.node_id
            self.size += 1

            return True
        except Exception as e:
            print(f"Error adding value: {e}")
            return False

    def batch_add_values(self, values: List[Value]) -> List[str]:
        """
        批量添加Value到集合中，返回对应的node_id列表

        Args:
            values: 要添加的Value列表

        Returns:
            List[str]: 对应的node_id列表，失败则为None
        """
        if not values:
            return []

        node_ids = []

        try:
            # 批量存储到数据库
            for value in values:
                node = ValueNode(value)

                # 存储到数据库
                if not self.storage.store_value(self.account_address, node.node_id, value):
                    print(f"Error: Failed to store value for node {node.node_id}")
                    return None

                # 添加到链表尾部
                if self.tail is None:
                    self.head = node
                    self.tail = node
                else:
                    self.tail.next = node
                    node.prev = self.tail
                    self.tail = node

                # 更新索引
                self._index_map[node.node_id] = node
                self._state_index[value.state].add(node.node_id)
                self._decimal_begin_map[value.get_decimal_begin_index()] = node.node_id

                node_ids.append(node.node_id)

            self.size += len(values)
            return node_ids

        except Exception as e:
            print(f"Error during batch add values: {e}")
            import traceback
            print(f"Batch add values traceback: {traceback.format_exc()}")
            return None
    
    def remove_value(self, node_id: str) -> bool:
        """根据node_id移除Value并从持久化存储中删除"""
        try:
            if node_id not in self._index_map:
                return False

            node = self._index_map[node_id]

            # 从数据库删除
            if not self.storage.delete_value(self.account_address, node_id):
                print(f"Warning: Failed to delete value from storage for node {node_id}")

            # 从状态索引中移除
            self._state_index[node.value.state].discard(node_id)

            # 从十进制索引中移除
            decimal_begin = node.value.get_decimal_begin_index()
            if decimal_begin in self._decimal_begin_map and self._decimal_begin_map[decimal_begin] == node_id:
                del self._decimal_begin_map[decimal_begin]

            # 从链表中移除节点
            if node.prev:
                node.prev.next = node.next
            else:
                self.head = node.next

            if node.next:
                node.next.prev = node.prev
            else:
                self.tail = node.prev

            # 从索引映射中移除
            del self._index_map[node_id]
            self.size -= 1

            return True
        except Exception as e:
            print(f"Error removing value: {e}")
            return False
    
    def find_by_state(self, state: ValueState) -> List[Value]:
        """根据状态查找所有Value"""
        node_ids = self._state_index.get(state, set())
        return [self._index_map[node_id].value for node_id in node_ids]
    
    def find_by_range(self, start_decimal: int, end_decimal: int) -> List[Value]:
        """根据十进制范围查找Value"""
        result = []
        current = self.head
        
        while current:
            value = current.value
            val_start = value.get_decimal_begin_index()
            val_end = value.get_decimal_end_index()
            
            if not (val_end < start_decimal or val_start > end_decimal):
                result.append(value)
                
            current = current.next
            
        return result
    
    def find_intersecting_values(self, target: Value) -> List[Value]:
        """查找与target有交集的所有Value"""
        result = []
        current = self.head
        
        while current:
            if current.value.is_intersect_value(target):
                result.append(current.value)
            current = current.next
            
        return result
    
    def split_value(self, node_id: str, change: int) -> Tuple[Optional[Value], Optional[Value]]:
        """分裂指定Value并持久化"""
        try:
            if node_id not in self._index_map:
                return None, None

            node = self._index_map[node_id]
            original_value = node.value

            if change <= 0 or change >= original_value.value_num:
                return None, None

            # 分裂Value
            v1, v2 = original_value.split_value(change)

            # 存储分裂后的值到数据库
            if not self.storage.store_value(self.account_address, node.node_id, v1):
                return None, None

            # 更新原节点为V1
            node.value = v1

            # 创建新节点存放V2
            new_node = ValueNode(v2)

            # 存储新值到数据库
            if not self.storage.store_value(self.account_address, new_node.node_id, v2):
                return None, None

            # 将新节点插入到原节点之后
            new_node.prev = node
            new_node.next = node.next
            if node.next:
                node.next.prev = new_node
            else:
                self.tail = new_node
            node.next = new_node

            # 更新索引
            self._index_map[new_node.node_id] = new_node
            self._state_index[v2.state].add(new_node.node_id)
            self._decimal_begin_map[v2.get_decimal_begin_index()] = new_node.node_id
            self.size += 1

            return v1, v2
        except Exception as e:
            print(f"Error splitting value: {e}")
            return None, None
    
    # 暂时不需要使用合并功能（EZchain系统暂不提供此功能）
    def merge_adjacent_values(self, node_id1: str, node_id2: str) -> Optional[Value]:
        """合并两个相邻的Value"""
        if node_id1 not in self._index_map or node_id2 not in self._index_map:
            return None
            
        node1 = self._index_map[node_id1]
        node2 = self._index_map[node_id2]
        
        # 检查是否相邻
        if node1.next != node2 or node1.value.state != node2.value.state:
            return None
            
        # 创建合并后的Value
        new_begin = node1.value.begin_index
        new_num = node1.value.value_num + node2.value.value_num
        merged_value = Value(new_begin, new_num, node1.value.state)
        
        # 更新第一个节点
        node1.value = merged_value
        
        # 移除第二个节点
        self.remove_value(node_id2)
        
        return merged_value
    
    def update_value_state(self, node_id: str, new_state: ValueState) -> bool:
        """更新Value状态并持久化"""
        try:
            if node_id not in self._index_map:
                return False

            node = self._index_map[node_id]
            old_state = node.value.state

            if old_state == new_state:
                return True

            # 更新内存中的状态
            self._state_index[old_state].discard(node_id)
            self._state_index[new_state].add(node_id)
            node.value.set_state(new_state)

            # 更新数据库中的状态
            if not self.storage.store_value(self.account_address, node_id, node.value):
                return False

            return True
        except Exception as e:
            print(f"Error updating value state: {e}")
            return False
    
    def get_all_values(self) -> List[Value]:
        """获取所有Value"""
        result = []
        current = self.head
        while current:
            result.append(current.value)
            current = current.next
        return result
    
    def get_values_sorted_by_begin_index(self) -> List[Value]:
        """按起始索引排序获取所有Value"""
        return sorted(self.get_all_values(), key=lambda v: v.get_decimal_begin_index())
    
    def get_balance_by_state(self, state: ValueState = ValueState.UNSPENT) -> int:
        """计算指定状态的总余额"""
        state_values = self.find_by_state(state)
        return sum(v.value_num for v in state_values)
    
    def get_total_balance(self) -> int:
        """计算总余额"""
        return sum(v.value_num for v in self.get_all_values())
    
    def clear_spent_values(self):
        """清除已确认的Value"""
        spent_node_ids = list(self._state_index[ValueState.CONFIRMED])
        for node_id in spent_node_ids:
            self.remove_value(node_id)
    
    def validate_no_overlap(self) -> bool:
        """验证所有Value之间没有重叠"""
        values = self.get_values_sorted_by_begin_index()
        for i in range(len(values) - 1):
            if values[i].get_decimal_end_index() >= values[i + 1].get_decimal_begin_index():
                return False
        return True
    
    def __len__(self) -> int:
        return self.size
    
    def __iter__(self):
        current = self.head
        while current:
            yield current.value
            current = current.next
    
    def __contains__(self, value: Value) -> bool:
        current = self.head
        while current:
            if current.value.is_same_value(value):
                return True
            current = current.next
        return False

    def revert_pending_to_unspent(self) -> int:
        """
        将所有PENDING状态的Value恢复为UNSPENT状态

        Returns:
            恢复的Value数量
        """
        reverted_count = 0
        pending_node_ids = list(self._state_index[ValueState.PENDING])

        for node_id in pending_node_ids:
            if self.update_value_state(node_id, ValueState.UNSPENT):
                reverted_count += 1

        return reverted_count

    def get_value_by_id(self, value_id: str) -> Optional[Value]:
        """
        根据Value ID获取Value对象

        Args:
            value_id: Value的唯一标识符（通常是begin_index）

        Returns:
            Value对象，如果不存在则返回None
        """
        # 首先尝试通过十进制映射查找
        try:
            decimal_begin = int(value_id, 16) if value_id.startswith('0x') else int(value_id)
            if decimal_begin in self._decimal_begin_map:
                node_id = self._decimal_begin_map[decimal_begin]
                node = self._index_map.get(node_id)
                if node:
                    return node.value
        except (ValueError, TypeError):
            pass

        # 如果十进制映射查找失败，遍历所有Value查找匹配的begin_index
        current = self.head
        while current:
            if current.value.begin_index == value_id:
                return current.value
            current = current.next

        return None

    def validate_integrity(self) -> bool:
        """
        验证AccountValueCollection的完整性

        Returns:
            True if integrity is valid
        """
        try:
            # 精简输出: print(f"[DEBUG] Starting integrity validation for account {self.account_address}")
            # 精简输出: print(f"[DEBUG] Collection size: {self.size}, Head: {self.head.node_id if self.head else None}")

            # 检查链表结构完整性
            current = self.head
            index = 0
            visited_nodes = set()

            while current:
                index += 1
                visited_nodes.add(current.node_id)

                # 验证前驱指针
                if current.prev is not None and current.prev.next != current:
                    print(f"[ERROR] Prev pointer inconsistency at node {current.node_id} (index {index})")
                    print(f"[ERROR] Current.prev.node_id: {current.prev.node_id if current.prev else None}")
                    print(f"[ERROR] Current.prev.next.node_id: {current.prev.next.node_id if current.prev and current.prev.next else None}")
                    return False

                # 验证后继指针
                if current.next is not None and current.next.prev != current:
                    print(f"[ERROR] Next pointer inconsistency at node {current.node_id} (index {index})")
                    print(f"[ERROR] Current.next.node_id: {current.next.node_id if current.next else None}")
                    print(f"[ERROR] Current.next.prev.node_id: {current.next.prev.node_id if current.next and current.next.prev else None}")
                    return False

                # 验证索引映射
                if current.node_id not in self._index_map:
                    print(f"[ERROR] Node {current.node_id} not found in _index_map (index {index})")
                    print(f"[ERROR] _index_map keys: {list(self._index_map.keys())}")
                    return False

                # 验证状态索引
                if current.node_id not in self._state_index[current.value.state]:
                    print(f"[ERROR] Node {current.node_id} not found in state index for state {current.value.state} (index {index})")
                    print(f"[ERROR] State index for {current.value.state}: {list(self._state_index[current.value.state])}")
                    return False

                current = current.next

            # 精简输出: print(f"[DEBUG] Traversed {index} nodes, visited nodes: {len(visited_nodes)}")

            # 检查size是否正确
            if index != self.size:
                print(f"[ERROR] Size mismatch: traversed {index} nodes vs size={self.size}")
                return False

            # 检查索引映射数量
            if len(self._index_map) != self.size:
                print(f"[ERROR] Index map size mismatch: {len(self._index_map)} vs size={self.size}")
                return False

            # 检查状态索引总数
            total_state_count = sum(len(state_set) for state_set in self._state_index.values())
            if total_state_count != self.size:
                print(f"[ERROR] State index count mismatch: total={total_state_count} vs size={self.size}")
                for state, state_set in self._state_index.items():
                    # 精简输出: print(f"[DEBUG] State {state}: {len(state_set)} nodes")
                    pass
                return False

            # 检查是否有重复访问的节点（循环检测）
            if len(visited_nodes) != index:
                print(f"[ERROR] Cycle detected: visited {len(visited_nodes)} unique nodes but traversed {index} nodes")
                return False

            # 检查无重叠
            # 精简输出: print(f"[DEBUG] Checking for value overlaps...")
            if not self.validate_no_overlap():
                print(f"[ERROR] Value overlap detected")
                values = self.get_values_sorted_by_begin_index()
                for i in range(len(values) - 1):
                    if values[i].get_decimal_end_index() >= values[i + 1].get_decimal_begin_index():
                        print(f"[ERROR] Overlap between values {i} and {i+1}:")
                        print(f"[ERROR]   Value {i}: begin={values[i].begin_index}, end={values[i].get_decimal_end_index()}, state={values[i].state}")
                        print(f"[ERROR]   Value {i+1}: begin={values[i+1].begin_index}, end={values[i+1].get_decimal_end_index()}, state={values[i+1].state}")
                return False

            # 精简输出: print(f"[DEBUG] Integrity validation passed for account {self.account_address}")
            return True

        except Exception as e:
            print(f"[ERROR] Exception during integrity validation: {e}")
            import traceback
            traceback.print_exc()
            return False

    def clear_all(self) -> bool:
        """
        清除所有Value数据

        Returns:
            bool: 清除是否成功
        """
        try:
            # 从数据库删除所有数据
            if not self.storage.remove_account_values(self.account_address):
                return False

            # 清空内存数据结构
            self.head = None
            self.tail = None
            self.size = 0
            self._index_map.clear()
            self._state_index.clear()
            self._decimal_begin_map.clear()

            return True
        except Exception as e:
            print(f"Error clearing all values: {e}")
            return False

    def get_statistics(self) -> Dict[str, int]:
        """
        获取集合的统计信息

        Returns:
            Dict[str, int]: 统计信息字典
        """
        try:
            # 获取存储的统计信息
            storage_stats = self.storage.get_statistics(self.account_address)

            # 合并内存统计信息
            memory_stats = {
                'memory_size': self.size,
                'memory_cached_nodes': len(self._index_map),
                'memory_state_index_size': sum(len(state_set) for state_set in self._state_index.values()),
                'memory_decimal_index_size': len(self._decimal_begin_map)
            }

            result = storage_stats.copy()
            result.update(memory_stats)

            return result
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {
                'total_values': 0,
                'unique_nodes': 0,
                'unspent_count': 0,
                'pending_count': 0,
                'onchain_count': 0,
                'confirmed_count': 0,
                'memory_size': self.size,
                'memory_cached_nodes': len(self._index_map),
                'memory_state_index_size': sum(len(state_set) for state_set in self._state_index.values()),
                'memory_decimal_index_size': len(self._decimal_begin_map)
            }

    def validate_integrity_with_storage(self) -> bool:
        """
        验证内存数据与存储数据的完整性

        Returns:
            bool: 完整性验证是否通过
        """
        try:
            # 获取存储中的所有Value
            stored_values = self.storage.get_all_values(self.account_address)
            stored_node_ids = {node_id for node_id, _ in stored_values}
            memory_node_ids = set(self._index_map.keys())

            # 检查是否缺少数据
            missing_in_memory = stored_node_ids - memory_node_ids
            missing_in_storage = memory_node_ids - stored_node_ids

            if missing_in_memory:
                print(f"Warning: {len(missing_in_memory)} values in storage but not in memory: {missing_in_memory}")
                # 尝试重新加载缺失的数据
                for node_id in missing_in_memory:
                    value = self.storage.load_value(self.account_address, node_id)
                    if value:
                        # 创建节点并添加到链表尾部
                        node = ValueNode(value, node_id)
                        if self.tail is None:
                            self.head = node
                            self.tail = node
                        else:
                            self.tail.next = node
                            node.prev = self.tail
                            self.tail = node

                        # 更新索引
                        self._index_map[node.node_id] = node
                        self._state_index[value.state].add(node.node_id)
                        self._decimal_begin_map[value.get_decimal_begin_index()] = node.node_id
                        self.size += 1

            if missing_in_storage:
                print(f"Warning: {len(missing_in_storage)} values in memory but not in storage: {missing_in_storage}")
                # 从内存中移除存储中不存在的数据
                for node_id in missing_in_storage:
                    self.remove_value(node_id)

            # 验证数据一致性
            for node_id, value in stored_values:
                if node_id in self._index_map:
                    memory_value = self._index_map[node_id].value
                    if (memory_value.begin_index != value.begin_index or
                        memory_value.value_num != value.value_num or
                        memory_value.state != value.state):
                        print(f"Warning: Data inconsistency for node {node_id}")
                        return False

            # 验证内存内部完整性
            return self.validate_integrity()

        except Exception as e:
            print(f"Error during integrity validation with storage: {e}")
            return False

    def reload_from_storage(self) -> bool:
        """
        从存储中重新加载所有数据，替换当前内存数据

        Returns:
            bool: 重新加载是否成功
        """
        try:
            # 清空内存数据
            self.head = None
            self.tail = None
            self.size = 0
            self._index_map.clear()
            self._state_index.clear()
            self._decimal_begin_map.clear()

            # 重新加载数据
            self._load_existing_values()
            return True
        except Exception as e:
            print(f"Error reloading from storage: {e}")
            return False