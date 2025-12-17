import sqlite3
import json
import os
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from .BlockIndexList import BlockIndexList


class AccountBlockIndexStorage:
    """
    BlockIndex的持久化存储管理器
    负责管理Account级别的BlockIndex数据的数据库存储和检索
    """

    def __init__(self, db_path: str = "ez_account_block_index_storage.db"):
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

            # BlockIndices表 - 存储BlockIndexList对象
            conn.execute("""
                CREATE TABLE IF NOT EXISTS block_indices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_address TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    index_list TEXT NOT NULL,
                    owner_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_address, node_id)
                )
            """)

            conn.commit()

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

    def store_block_index(self, account_address: str, node_id: str, block_index: BlockIndexList) -> bool:
        """存储或更新BlockIndex到数据库"""
        try:
            # 确保账户存在
            if not self.ensure_account_exists(account_address):
                return False

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO block_indices
                    (account_address, node_id, index_list, owner_data, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    account_address,
                    node_id,
                    json.dumps(block_index.index_lst),
                    json.dumps(block_index.owner) if block_index.owner is not None else None
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing BlockIndex: {e}")
            return False

    def load_block_index(self, account_address: str, node_id: str) -> Optional[BlockIndexList]:
        """从数据库加载BlockIndex"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT index_list, owner_data FROM block_indices
                    WHERE account_address = ? AND node_id = ?
                """, (account_address, node_id))

                row = cursor.fetchone()
                if row:
                    index_list_data, owner_data = row
                    index_list = json.loads(index_list_data) if index_list_data else []
                    owner = json.loads(owner_data) if owner_data else None

                    return BlockIndexList(index_lst=index_list, owner=owner)
        except Exception as e:
            print(f"Error loading BlockIndex: {e}")
        return None

    def delete_block_index(self, account_address: str, node_id: str) -> bool:
        """从数据库删除BlockIndex"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM block_indices
                    WHERE account_address = ? AND node_id = ?
                """, (account_address, node_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting BlockIndex: {e}")
            return False

    def get_all_block_indices(self, account_address: str) -> List[Tuple[str, BlockIndexList]]:
        """获取指定账户的所有BlockIndex"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT node_id, index_list, owner_data FROM block_indices
                    WHERE account_address = ?
                    ORDER BY created_at ASC
                """, (account_address,))

                result = []
                for row in cursor.fetchall():
                    node_id, index_list_data, owner_data = row
                    try:
                        index_list = json.loads(index_list_data) if index_list_data else []
                        owner = json.loads(owner_data) if owner_data else None
                        block_index = BlockIndexList(index_lst=index_list, owner=owner)
                        result.append((node_id, block_index))
                    except Exception as parse_error:
                        print(f"Warning: Failed to parse BlockIndex for node {node_id}: {parse_error}")
                        continue
                return result
        except Exception as e:
            print(f"Error getting all block indices: {e}")
            return []

    def remove_account_indices(self, account_address: str) -> bool:
        """删除指定账户的所有BlockIndex数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM block_indices
                    WHERE account_address = ?
                """, (account_address,))
                conn.commit()
                return cursor.rowcount >= 0  # 允许删除0条记录
        except Exception as e:
            print(f"Error removing account indices: {e}")
            return False

    def get_statistics(self, account_address: str) -> Dict[str, int]:
        """获取指定账户的BlockIndex统计信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) as total_indices,
                           COUNT(DISTINCT node_id) as unique_nodes
                    FROM block_indices
                    WHERE account_address = ?
                """, (account_address,))

                row = cursor.fetchone()
                if row:
                    total_indices, unique_nodes = row
                    return {
                        'total_indices': total_indices,
                        'unique_nodes': unique_nodes
                    }
        except Exception as e:
            print(f"Error getting statistics: {e}")
        return {'total_indices': 0, 'unique_nodes': 0}


class AccountBlockIndexManager:
    """
    Account级别的BlockIndex管理器
    负责管理该Account下的所有node_id与BlockIndexList的映射关系及存储
    """

    def __init__(self, account_address: str, storage: Optional[AccountBlockIndexStorage] = None):
        self.account_address = account_address
        self.storage = storage or AccountBlockIndexStorage()

        # 内存缓存：node_id -> BlockIndexList
        self._block_index_cache: Dict[str, BlockIndexList] = {}

        # 加载现有的BlockIndex数据
        self._load_existing_indices()

    def _load_existing_indices(self):
        """加载现有的BlockIndex数据到内存缓存"""
        try:
            all_indices = self.storage.get_all_block_indices(self.account_address)
            for node_id, block_index in all_indices:
                self._block_index_cache[node_id] = block_index
        except Exception as e:
            print(f"Error loading existing block indices: {e}")

    def add_block_index(self, node_id: str, block_index: BlockIndexList) -> bool:
        """
        添加或更新BlockIndex

        Args:
            node_id: ValueNode的node_id，唯一标识符
            block_index: BlockIndexList对象

        Returns:
            bool: 操作是否成功
        """
        try:
            # 存储到数据库
            if not self.storage.store_block_index(self.account_address, node_id, block_index):
                return False

            # 更新内存缓存
            self._block_index_cache[node_id] = block_index

            return True
        except Exception as e:
            print(f"Error adding block index: {e}")
            return False

    def get_block_index(self, node_id: str) -> Optional[BlockIndexList]:
        """
        获取指定node_id的BlockIndex

        Args:
            node_id: ValueNode的node_id

        Returns:
            BlockIndexList对象，如果不存在则返回None
        """
        try:
            # 首先检查内存缓存
            if node_id in self._block_index_cache:
                return self._block_index_cache[node_id]

            # 如果缓存中没有，从数据库加载
            block_index = self.storage.load_block_index(self.account_address, node_id)
            if block_index:
                self._block_index_cache[node_id] = block_index

            return block_index
        except Exception as e:
            print(f"Error getting block index: {e}")
            return None

    def remove_block_index(self, node_id: str) -> bool:
        """
        移除指定node_id的BlockIndex

        Args:
            node_id: ValueNode的node_id

        Returns:
            bool: 移除是否成功
        """
        try:
            # 从数据库删除
            if not self.storage.delete_block_index(self.account_address, node_id):
                return False

            # 从内存缓存删除
            if node_id in self._block_index_cache:
                del self._block_index_cache[node_id]

            return True
        except Exception as e:
            print(f"Error removing block index: {e}")
            return False

    def update_block_index_merge(self, node_id: str, new_block_index: BlockIndexList) -> bool:
        """
        合并更新BlockIndex（将新的index_lst和owner信息合并到现有记录中）

        Args:
            node_id: ValueNode的node_id
            new_block_index: 要合并的新BlockIndexList

        Returns:
            bool: 更新是否成功
        """
        try:
            # 获取现有的BlockIndex
            existing_block_index = self.get_block_index(node_id)

            if existing_block_index:
                # 合并index_lst（去重并保持有序）
                existing_indices = set(existing_block_index.index_lst)
                new_indices = set(new_block_index.index_lst)
                merged_indices = list(existing_indices | new_indices)
                merged_indices.sort()  # 保持递增顺序

                # 合并owner信息
                existing_owner_history = existing_block_index.get_ownership_history()
                new_owner_history = new_block_index.get_ownership_history()

                # 合并所有权历史，去重并保持有序
                owner_dict = {block_idx: owner_addr for block_idx, owner_addr in existing_owner_history}
                owner_dict.update({block_idx: owner_addr for block_idx, owner_addr in new_owner_history})
                merged_owner_history = sorted(owner_dict.items())

                # 创建合并后的BlockIndexList
                merged_block_index = BlockIndexList(index_lst=merged_indices, owner=merged_owner_history)

                # 存储合并后的结果
                return self.add_block_index(node_id, merged_block_index)
            else:
                # 如果不存在现有的BlockIndex，直接添加新的
                return self.add_block_index(node_id, new_block_index)

        except Exception as e:
            print(f"Error updating block index merge: {e}")
            return False

    def add_block_height_to_index(self, node_id: str, block_height: int, owner_address: str = None) -> bool:
        """
        向指定node_id的BlockIndex添加区块高度（可选地添加所有权变更）

        Args:
            node_id: ValueNode的node_id
            block_height: 要添加的区块高度
            owner_address: 新的所有者地址（可选）

        Returns:
            bool: 添加是否成功
        """
        try:
            # 获取现有的BlockIndex
            existing_block_index = self.get_block_index(node_id)

            if existing_block_index:
                # 检查block_height是否已存在
                if block_height not in existing_block_index.index_lst:
                    # 添加新的区块高度
                    existing_block_index.index_lst.append(block_height)
                    existing_block_index.index_lst.sort()  # 保持有序

                    # 如果提供了owner_address，添加所有权变更
                    if owner_address:
                        existing_block_index.add_ownership_change(block_height, owner_address)

                    # 保存更新
                    return self.add_block_index(node_id, existing_block_index)
                else:
                    # 如果区块高度已存在，只需要更新所有权（如果提供了）
                    if owner_address:
                        existing_block_index.add_ownership_change(block_height, owner_address)
                        return self.add_block_index(node_id, existing_block_index)
                    return True
            else:
                # 如果不存在现有的BlockIndex，创建新的
                new_block_index = BlockIndexList(index_lst=[block_height])
                if owner_address:
                    new_block_index.add_ownership_change(block_height, owner_address)
                return self.add_block_index(node_id, new_block_index)

        except Exception as e:
            print(f"Error adding block height to index: {e}")
            return False

    def get_all_node_ids(self) -> List[str]:
        """
        获取账户的所有node_id列表

        Returns:
            List[str]: node_id列表
        """
        try:
            return list(self._block_index_cache.keys())
        except Exception as e:
            print(f"Error getting all node IDs: {e}")
            return []

    def get_all_block_indices(self) -> List[Tuple[str, BlockIndexList]]:
        """
        获取账户的所有BlockIndex

        Returns:
            List[Tuple[str, BlockIndexList]]: (node_id, BlockIndexList) 元组列表
        """
        try:
            result = []
            for node_id in self._block_index_cache.keys():
                block_index = self.get_block_index(node_id)
                if block_index:
                    result.append((node_id, block_index))
            return result
        except Exception as e:
            print(f"Error getting all block indices: {e}")
            return []

    def has_block_index(self, node_id: str) -> bool:
        """
        检查是否存在指定node_id的BlockIndex

        Args:
            node_id: ValueNode的node_id

        Returns:
            bool: 是否存在
        """
        return node_id in self._block_index_cache

    def clear_all(self) -> bool:
        """
        清除所有BlockIndex数据

        Returns:
            bool: 清除是否成功
        """
        try:
            # 从数据库删除所有数据
            if not self.storage.remove_account_indices(self.account_address):
                return False

            # 清空内存缓存
            self._block_index_cache.clear()

            return True
        except Exception as e:
            print(f"Error clearing all block indices: {e}")
            return False

    def get_statistics(self) -> Dict[str, int]:
        """
        获取管理器的统计信息

        Returns:
            Dict[str, int]: 统计信息字典
        """
        try:
            storage_stats = self.storage.get_statistics(self.account_address)
            cache_stats = {
                'cached_indices': len(self._block_index_cache)
            }

            # 合并统计信息
            result = storage_stats.copy()
            result.update(cache_stats)

            return result
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {}

    def validate_integrity(self) -> bool:
        """
        验证BlockIndex数据的完整性

        Returns:
            bool: 完整性验证是否通过
        """
        try:
            # 检查内存缓存与数据库的一致性
            db_indices = self.storage.get_all_block_indices(self.account_address)
            db_node_ids = {node_id for node_id, _ in db_indices}
            cache_node_ids = set(self._block_index_cache.keys())

            # 检查是否缺少数据
            missing_in_cache = db_node_ids - cache_node_ids
            missing_in_db = cache_node_ids - db_node_ids

            if missing_in_cache:
                print(f"Warning: {len(missing_in_cache)} block indices in DB but not in cache")
                # 尝试重新加载缺失的数据
                for node_id in missing_in_cache:
                    block_index = self.storage.load_block_index(self.account_address, node_id)
                    if block_index:
                        self._block_index_cache[node_id] = block_index

            if missing_in_db:
                print(f"Warning: {len(missing_in_db)} block indices in cache but not in DB")
                # 从缓存中移除数据库中不存在的数据
                for node_id in missing_in_db:
                    if node_id in self._block_index_cache:
                        del self._block_index_cache[node_id]

            # 验证每个BlockIndex的内部完整性
            for node_id, block_index in list(self._block_index_cache.items()):
                try:
                    # 验证index_lst是否为有效的整数列表
                    if not isinstance(block_index.index_lst, list):
                        print(f"Invalid index_lst type for node {node_id}")
                        return False

                    if not all(isinstance(idx, int) for idx in block_index.index_lst):
                        print(f"Non-integer value in index_lst for node {node_id}")
                        return False

                    # 验证owner数据的合理性
                    if block_index.owner is not None:
                        if isinstance(block_index.owner, list):
                            for item in block_index.owner:
                                if not isinstance(item, tuple) or len(item) != 2:
                                    print(f"Invalid owner history format for node {node_id}")
                                    return False
                                if not isinstance(item[0], int) or not isinstance(item[1], str):
                                    print(f"Invalid owner history item type for node {node_id}")
                                    return False
                        elif not isinstance(block_index.owner, str):
                            print(f"Invalid owner type for node {node_id}")
                            return False

                except Exception as validation_error:
                    print(f"Validation error for node {node_id}: {validation_error}")
                    return False

            return True

        except Exception as e:
            print(f"Error during integrity validation: {e}")
            return False

    def __len__(self) -> int:
        """返回管理的BlockIndex数量"""
        return len(self._block_index_cache)

    def __contains__(self, node_id: str) -> bool:
        """检查是否包含指定node_id的BlockIndex"""
        return node_id in self._block_index_cache

    def __iter__(self):
        """迭代所有(node_id, BlockIndexList)对"""
        for node_id in self._block_index_cache:
            yield (node_id, self.get_block_index(node_id))


# 测试代码
if __name__ == "__main__":
    print("Testing AccountBlockIndexManager...")

    try:
        # 创建测试管理器
        manager = AccountBlockIndexManager("test_account_0x456")
        print("[SUCCESS] AccountBlockIndexManager created successfully")

        # 测试统计信息
        stats = manager.get_statistics()
        print(f"[SUCCESS] Statistics retrieved: {stats}")

        # 测试基本操作
        print(f"[SUCCESS] Manager length: {len(manager)}")
        print(f"[SUCCESS] Contains test_node: {'test_node' in manager}")

        # 测试BlockIndex相关功能
        print("\n--- Testing BlockIndex operations ---")

        # 创建测试BlockIndexList
        test_block_index = BlockIndexList(index_lst=[0, 1, 2], owner="0x123abc")
        print(f"[SUCCESS] Test BlockIndexList created: {test_block_index}")

        # 添加BlockIndex到管理器
        test_node_id = "test_node_456"
        if manager.add_block_index(test_node_id, test_block_index):
            print("[SUCCESS] BlockIndex added to manager")
        else:
            print("[ERROR] Failed to add BlockIndex to manager")

        # 测试长度变化
        print(f"[SUCCESS] Manager length after adding: {len(manager)}")
        print(f"[SUCCESS] Contains test_node_id: {test_node_id in manager}")

        # 测试获取BlockIndex
        retrieved_block_index = manager.get_block_index(test_node_id)
        if retrieved_block_index:
            print(f"[SUCCESS] Retrieved BlockIndex: {retrieved_block_index}")
        else:
            print("[ERROR] Failed to retrieve BlockIndex")

        # 测试添加区块高度
        if manager.add_block_height_to_index(test_node_id, 3, "0x789def"):
            print("[SUCCESS] Block height added to index")
        else:
            print("[ERROR] Failed to add block height")

        # 验证更新后的BlockIndex
        updated_block_index = manager.get_block_index(test_node_id)
        if updated_block_index and 3 in updated_block_index.index_lst:
            print("[SUCCESS] Block height update verified")
        else:
            print("[ERROR] Block height update failed")

        # 测试获取所有BlockIndex
        all_indices = manager.get_all_block_indices()
        print(f"[SUCCESS] Retrieved {len(all_indices)} block indices from manager")

        # 更新统计信息
        updated_stats = manager.get_statistics()
        print(f"[SUCCESS] Updated statistics: {updated_stats}")

        # 测试完整性验证
        if manager.validate_integrity():
            print("[SUCCESS] Integrity validation passed")
        else:
            print("[ERROR] Integrity validation failed")

        # 测试持久化功能
        print("\n--- Testing persistence operations ---")

        # 创建新的管理器实例来测试数据加载
        new_manager = AccountBlockIndexManager("test_account_0x456")
        print("[SUCCESS] Created new manager instance")

        # 检查是否成功加载了之前的数据
        loaded_length = len(new_manager)
        print(f"[SUCCESS] Loaded {loaded_length} block indices from storage")

        # 比较统计信息
        loaded_stats = new_manager.get_statistics()
        print(f"[SUCCESS] Loaded statistics: {loaded_stats}")

        # 验证加载的数据
        loaded_block_index = new_manager.get_block_index(test_node_id)
        if loaded_block_index and loaded_block_index.index_lst == [0, 1, 2, 3]:
            print("[SUCCESS] Data persistence verified")
        else:
            print("[ERROR] Data persistence failed")

        # 测试清除功能
        if new_manager.clear_all():
            print("[SUCCESS] Cleared all data from manager")
        else:
            print("[ERROR] Failed to clear data")

        # 验证清除后的状态
        cleared_length = len(new_manager)
        print(f"[SUCCESS] Manager length after clearing: {cleared_length}")

        print("\n=== All tests passed! ===")

    except Exception as e:
        print(f"[ERROR] Error during testing: {e}")
        import traceback
        traceback.print_exc()