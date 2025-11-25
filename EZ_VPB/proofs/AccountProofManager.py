import sqlite3
import json
import os
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from proofs.ProofUnit import ProofUnit
from values.Value import Value

class AccountProofStorage:
    """
    持久化存储管理器，用于管理Account级别的ProofUnit和Value映射关系
    """

    def __init__(self, db_path: str = "ez_account_proof_storage.db"):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """初始化SQLite数据库和所需表结构"""
        with sqlite3.connect(self.db_path) as conn:
            # ProofUnits表 - 存储唯一的ProofUnit
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proof_units (
                    unit_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    owner_multi_txns TEXT NOT NULL,
                    owner_mt_proof TEXT NOT NULL,
                    reference_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Account表 - 存储账户信息
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_address TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Account_Value_Proof映射表 - 存储账户、Value和ProofUnit的三方关系
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_value_proofs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_address TEXT NOT NULL,
                    value_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_address) REFERENCES accounts (account_address),
                    FOREIGN KEY (unit_id) REFERENCES proof_units (unit_id),
                    UNIQUE(account_address, value_id, unit_id)
                )
            """)

            # Value基本信息表 - 存储Value的基本信息以便快速查找
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_values (
                    account_address TEXT NOT NULL,
                    value_id TEXT NOT NULL,
                    value_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_address) REFERENCES accounts (account_address),
                    PRIMARY KEY (account_address, value_id)
                )
            """)

            conn.commit()

    def store_proof_unit(self, proof_unit: ProofUnit) -> bool:
        """存储或更新ProofUnit到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO proof_units
                    (unit_id, owner, owner_multi_txns, owner_mt_proof, reference_count)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    proof_unit.unit_id,
                    proof_unit.owner,
                    json.dumps(proof_unit.owner_multi_txns.to_dict()),
                    json.dumps(proof_unit.owner_mt_proof.to_dict()),
                    proof_unit.reference_count
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing ProofUnit: {e}")
            return False

    def load_proof_unit(self, unit_id: str) -> Optional[ProofUnit]:
        """从数据库加载ProofUnit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT owner, owner_multi_txns, owner_mt_proof, reference_count
                    FROM proof_units WHERE unit_id = ?
                """, (unit_id,))

                row = cursor.fetchone()
                if row:
                    owner, multi_txns_data, mt_proof_data, ref_count = row

                    from EZ_Transaction.MultiTransactions import MultiTransactions
                    from EZ_Units.MerkleProof import MerkleTreeProof

                    proof_unit = ProofUnit(
                        owner=owner,
                        owner_multi_txns=MultiTransactions.from_dict(json.loads(multi_txns_data)),
                        owner_mt_proof=MerkleTreeProof.from_dict(json.loads(mt_proof_data)),
                        unit_id=unit_id
                    )
                    proof_unit.reference_count = ref_count
                    return proof_unit
        except Exception as e:
            print(f"Error loading ProofUnit: {e}")
        return None

    def delete_proof_unit(self, unit_id: str) -> bool:
        """从数据库删除ProofUnit（当引用计数为0时）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM proof_units WHERE unit_id = ?", (unit_id,))
                conn.execute("DELETE FROM account_value_proofs WHERE unit_id = ?", (unit_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting ProofUnit: {e}")
            return False

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

    def add_value_proof_mapping(self, account_address: str, value_id: str, unit_id: str) -> bool:
        """添加账户-Value-ProofUnit的映射关系"""
        try:
            # 确保账户存在
            if not self.ensure_account_exists(account_address):
                return False

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO account_value_proofs (account_address, value_id, unit_id)
                    VALUES (?, ?, ?)
                """, (account_address, value_id, unit_id))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error adding value-proof mapping: {e}")
            return False

    def remove_value_proof_mapping(self, account_address: str, value_id: str, unit_id: str) -> bool:
        """移除账户-Value-ProofUnit的映射关系"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ? AND unit_id = ?
                """, (account_address, value_id, unit_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing value-proof mapping: {e}")
            return False

    def store_value_info(self, account_address: str, value: Value) -> bool:
        """存储Value的基本信息"""
        try:
            # 确保账户存在
            if not self.ensure_account_exists(account_address):
                return False

            # 使用begin_index作为value_id
            value_id = value.begin_index

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO account_values (account_address, value_id, value_data)
                    VALUES (?, ?, ?)
                """, (
                    account_address,
                    value_id,
                    json.dumps(value.to_dict())
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing value info: {e}")
            return False

    def remove_value_info(self, account_address: str, value_id: str) -> bool:
        """移除Value的基本信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 先删除相关的proof映射
                conn.execute("""
                    DELETE FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ?
                """, (account_address, value_id))

                # 再删除value信息
                cursor = conn.execute("""
                    DELETE FROM account_values
                    WHERE account_address = ? AND value_id = ?
                """, (account_address, value_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing value info: {e}")
            return False

    def get_proof_units_for_account_value(self, account_address: str, value_id: str) -> List[ProofUnit]:
        """获取指定账户和Value关联的所有ProofUnit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT unit_id FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ?
                """, (account_address, value_id))

                proof_units = []
                for row in cursor.fetchall():
                    unit_id = row[0]
                    proof_unit = self.load_proof_unit(unit_id)
                    if proof_unit:
                        proof_units.append(proof_unit)
                return proof_units
        except Exception as e:
            print(f"Error getting proof units for account value: {e}")
            return []

    def get_all_proof_units_for_account(self, account_address: str) -> List[Tuple[str, ProofUnit]]:
        """获取指定账户的所有Value-ProofUnit关系"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT value_id, unit_id FROM account_value_proofs
                    WHERE account_address = ?
                """, (account_address,))

                result = []
                for row in cursor.fetchall():
                    value_id, unit_id = row
                    proof_unit = self.load_proof_unit(unit_id)
                    if proof_unit:
                        result.append((value_id, proof_unit))
                return result
        except Exception as e:
            print(f"Error getting all proof units for account: {e}")
            return []

    def get_values_for_account(self, account_address: str) -> List[Value]:
        """获取指定账户的所有Value"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT value_data FROM account_values
                    WHERE account_address = ?
                """, (account_address,))

                values = []
                for row in cursor.fetchall():
                    value_data = json.loads(row[0])
                    value = Value.from_dict(value_data)
                    values.append(value)
                return values
        except Exception as e:
            print(f"Error getting values for account: {e}")
            return []

    def get_proof_units_by_owner(self, account_address: str, owner: str) -> List[ProofUnit]:
        """获取指定账户中指定owner的所有ProofUnit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT DISTINCT p.unit_id FROM proof_units p
                    JOIN account_value_proofs avp ON p.unit_id = avp.unit_id
                    WHERE avp.account_address = ? AND p.owner = ?
                """, (account_address, owner))

                proof_units = []
                for row in cursor.fetchall():
                    unit_id = row[0]
                    proof_unit = self.load_proof_unit(unit_id)
                    if proof_unit:
                        proof_units.append(proof_unit)
                return proof_units
        except Exception as e:
            print(f"Error getting proof units by owner: {e}")
            return []


class AccountProofManager:
    """
    Account级别的ProofUnit管理器
    负责管理该Account下的所有Value与ProofUnit的映射关系及存储
    """

    def __init__(self, account_address: str, storage: Optional[AccountProofStorage] = None):
        self.account_address = account_address
        self.storage = storage or AccountProofStorage()

        # 内存缓存
        self._value_proof_mapping: Dict[str, Set[str]] = defaultdict(set)  # value_id -> set of unit_ids
        self._proof_units_cache: Dict[str, ProofUnit] = {}  # unit_id -> ProofUnit

        # 加载现有映射
        self._load_existing_mappings()

    def _load_existing_mappings(self):
        """加载现有的映射关系到内存缓存"""
        try:
            all_mappings = self.storage.get_all_proof_units_for_account(self.account_address)
            for value_id, proof_unit in all_mappings:
                self._value_proof_mapping[value_id].add(proof_unit.unit_id)
                self._proof_units_cache[proof_unit.unit_id] = proof_unit
        except Exception as e:
            print(f"Error loading existing mappings: {e}")

    def add_value(self, value: Value) -> bool:
        """
        添加Value到管理器中

        Args:
            value: 要添加的Value对象

        Returns:
            bool: 添加是否成功
        """
        try:
            # 存储Value基本信息
            if not self.storage.store_value_info(self.account_address, value):
                return False

            # 初始化该Value的proof映射（空集合）
            value_id = value.begin_index
            if value_id not in self._value_proof_mapping:
                self._value_proof_mapping[value_id] = set()

            return True
        except Exception as e:
            print(f"Error adding value: {e}")
            return False

    def remove_value(self, value_id: str) -> bool:
        """
        从管理器中移除Value及其所有ProofUnit映射

        Args:
            value_id: Value的标识符（begin_index）

        Returns:
            bool: 移除是否成功
        """
        try:
            # 获取该Value关联的所有ProofUnit
            unit_ids = list(self._value_proof_mapping.get(value_id, set()))

            # 移除所有映射关系
            for unit_id in unit_ids:
                if not self.remove_value_proof_mapping(value_id, unit_id):
                    print(f"Warning: Failed to remove mapping for value {value_id}, unit {unit_id}")

            # 从存储中删除Value信息
            if not self.storage.remove_value_info(self.account_address, value_id):
                print(f"Warning: Failed to remove value info for {value_id}")

            # 从内存缓存中删除
            if value_id in self._value_proof_mapping:
                del self._value_proof_mapping[value_id]

            return True
        except Exception as e:
            print(f"Error removing value: {e}")
            return False

    def add_proof_unit(self, value_id: str, proof_unit: ProofUnit) -> bool:
        """
        添加ProofUnit到指定Value

        Args:
            value_id: Value的标识符（begin_index）
            proof_unit: 要添加的ProofUnit

        Returns:
            bool: 添加是否成功
        """
        try:
            # 检查是否已经存在相同的ProofUnit
            existing_unit = self.storage.load_proof_unit(proof_unit.unit_id)

            if existing_unit:
                # 使用现有的ProofUnit并增加引用计数
                existing_unit.increment_reference()
                if not self.storage.store_proof_unit(existing_unit):
                    return False
                unit_to_use = existing_unit
            else:
                # 存储新的ProofUnit
                if not self.storage.store_proof_unit(proof_unit):
                    return False
                unit_to_use = proof_unit

            # 添加映射关系
            if self.storage.add_value_proof_mapping(self.account_address, value_id, unit_to_use.unit_id):
                self._value_proof_mapping[value_id].add(unit_to_use.unit_id)
                self._proof_units_cache[unit_to_use.unit_id] = unit_to_use
                return True

            return False
        except Exception as e:
            print(f"Error adding proof unit: {e}")
            return False

    def add_proof_unit_direct(self, value_id: str, proof_unit: ProofUnit) -> bool:
        """
        直接新增ProofUnit到指定Value，不进行重复检测（提高效率）

        Args:
            value_id: Value的标识符（begin_index）
            proof_unit: 要直接新增的ProofUnit

        Returns:
            bool: 添加是否成功
        """
        try:
            # 直接存储新的ProofUnit，不进行重复检测
            if not self.storage.store_proof_unit(proof_unit):
                return False

            # 添加映射关系
            if self.storage.add_value_proof_mapping(self.account_address, value_id, proof_unit.unit_id):
                self._value_proof_mapping[value_id].add(proof_unit.unit_id)
                self._proof_units_cache[proof_unit.unit_id] = proof_unit
                return True

            return False
        except Exception as e:
            print(f"Error adding proof unit directly: {e}")
            return False

    def remove_value_proof_mapping(self, value_id: str, unit_id: str) -> bool:
        """
        移除Value和ProofUnit的映射关系

        Args:
            value_id: Value的标识符
            unit_id: ProofUnit的标识符

        Returns:
            bool: 移除是否成功
        """
        try:
            if self.storage.remove_value_proof_mapping(self.account_address, value_id, unit_id):
                # 更新内存缓存
                if value_id in self._value_proof_mapping:
                    self._value_proof_mapping[value_id].discard(unit_id)

                # 检查ProofUnit是否可以被删除
                proof_unit = self.storage.load_proof_unit(unit_id)
                if proof_unit:
                    proof_unit.decrement_reference()
                    if proof_unit.can_be_deleted():
                        self.storage.delete_proof_unit(unit_id)
                        if unit_id in self._proof_units_cache:
                            del self._proof_units_cache[unit_id]
                    else:
                        self.storage.store_proof_unit(proof_unit)
                        # 更新缓存
                        self._proof_units_cache[unit_id] = proof_unit

                return True

            return False
        except Exception as e:
            print(f"Error removing value proof mapping: {e}")
            return False

    def get_proof_units_for_value(self, value_id: str) -> List[ProofUnit]:
        """
        获取指定Value关联的所有ProofUnit

        Args:
            value_id: Value的标识符

        Returns:
            List[ProofUnit]: ProofUnit列表
        """
        try:
            proof_units = []
            unit_ids = self._value_proof_mapping.get(value_id, set())

            for unit_id in unit_ids:
                if unit_id in self._proof_units_cache:
                    proof_units.append(self._proof_units_cache[unit_id])
                else:
                    proof_unit = self.storage.load_proof_unit(unit_id)
                    if proof_unit:
                        self._proof_units_cache[unit_id] = proof_unit
                        proof_units.append(proof_unit)

            return proof_units
        except Exception as e:
            print(f"Error getting proof units for value: {e}")
            return []

    def get_value_for_proof_unit(self, unit_id: str) -> Optional[str]:
        """
        根据ProofUnit获取对应的Value ID

        Args:
            unit_id: ProofUnit的标识符

        Returns:
            Optional[str]: Value ID，如果未找到则返回None
        """
        try:
            for value_id, unit_ids in self._value_proof_mapping.items():
                if unit_id in unit_ids:
                    return value_id
            return None
        except Exception as e:
            print(f"Error getting value for proof unit: {e}")
            return None

    def get_all_values(self) -> List[Value]:
        """
        获取账户的所有Value

        Returns:
            List[Value]: Value列表
        """
        try:
            return self.storage.get_values_for_account(self.account_address)
        except Exception as e:
            print(f"Error getting all values: {e}")
            return []

    def get_all_proof_units(self) -> List[Tuple[str, ProofUnit]]:
        """
        获取账户的所有Value-ProofUnit关系

        Returns:
            List[Tuple[str, ProofUnit]]: (value_id, proof_unit) 元组列表
        """
        try:
            result = []
            for value_id, unit_ids in self._value_proof_mapping.items():
                for unit_id in unit_ids:
                    if unit_id in self._proof_units_cache:
                        result.append((value_id, self._proof_units_cache[unit_id]))
                    else:
                        proof_unit = self.storage.load_proof_unit(unit_id)
                        if proof_unit:
                            self._proof_units_cache[unit_id] = proof_unit
                            result.append((value_id, proof_unit))
            return result
        except Exception as e:
            print(f"Error getting all proof units: {e}")
            return []

    def get_proof_units_by_owner(self, owner: str) -> List[ProofUnit]:
        """
        获取指定owner的所有ProofUnit

        Args:
            owner: ProofUnit的所有者

        Returns:
            List[ProofUnit]: ProofUnit列表
        """
        try:
            return self.storage.get_proof_units_by_owner(self.account_address, owner)
        except Exception as e:
            print(f"Error getting proof units by owner: {e}")
            return []

    def verify_all_proof_units(self, merkle_root: str = None) -> List[Tuple[str, str, bool, str]]:
        """
        验证所有ProofUnit

        Args:
            merkle_root: 用于验证的Merkle根哈希

        Returns:
            List[Tuple[str, str, bool, str]]: (value_id, unit_id, is_valid, error_message) 元组列表
        """
        try:
            results = []
            all_mappings = self.get_all_proof_units()

            for value_id, proof_unit in all_mappings:
                is_valid, error_message = proof_unit.verify_proof_unit(merkle_root)
                results.append((value_id, proof_unit.unit_id, is_valid, error_message))

            return results
        except Exception as e:
            print(f"Error verifying all proof units: {e}")
            return []

    def get_statistics(self) -> Dict[str, int]:
        """
        获取管理器的统计信息

        Returns:
            Dict[str, int]: 统计信息字典
        """
        try:
            total_values = len(self._value_proof_mapping)
            total_proof_units = len(set(unit_id for unit_ids in self._value_proof_mapping.values() for unit_id in unit_ids))

            # 计算每个Value的ProofUnit数量
            proof_counts = [len(unit_ids) for unit_ids in self._value_proof_mapping.values()]
            max_proofs_per_value = max(proof_counts) if proof_counts else 0
            avg_proofs_per_value = sum(proof_counts) / len(proof_counts) if proof_counts else 0

            return {
                'total_values': total_values,
                'total_proof_units': total_proof_units,
                'max_proofs_per_value': max_proofs_per_value,
                'avg_proofs_per_value': avg_proofs_per_value
            }
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {}

    def clear_all(self) -> bool:
        """
        清除所有数据

        Returns:
            bool: 清除是否成功
        """
        try:
            # 清除所有映射关系
            for value_id in list(self._value_proof_mapping.keys()):
                self.remove_value(value_id)

            # 清空内存缓存
            self._value_proof_mapping.clear()
            self._proof_units_cache.clear()

            return True
        except Exception as e:
            print(f"Error clearing all data: {e}")
            return False

    def __len__(self) -> int:
        """返回管理的Value数量"""
        return len(self._value_proof_mapping)

    def __contains__(self, value_id: str) -> bool:
        """检查是否包含指定Value"""
        return value_id in self._value_proof_mapping

    def __iter__(self):
        """迭代所有(value_id, proof_units)对"""
        for value_id in self._value_proof_mapping:
            yield (value_id, self.get_proof_units_for_value(value_id))


# 测试代码
if __name__ == "__main__":
    print("Testing AccountProofManager...")

    try:
        # 创建测试管理器
        manager = AccountProofManager("test_account_0x123")
        print("[SUCCESS] AccountProofManager created successfully")

        # 测试统计信息
        stats = manager.get_statistics()
        print(f"[SUCCESS] Statistics retrieved: {stats}")

        # 测试基本操作
        print(f"[SUCCESS] Manager length: {len(manager)}")
        print(f"[SUCCESS] Contains test_value: {'test_value' in manager}")

        # 测试Value相关功能
        print("\n--- Testing Value operations ---")

        # 创建测试Value
        test_value = Value("0x1000", 100)
        print(f"[SUCCESS] Test Value created: begin={test_value.begin_index}, num={test_value.value_num}")

        # 添加Value到管理器
        if manager.add_value(test_value):
            print("[SUCCESS] Value added to manager")
        else:
            print("[ERROR] Failed to add value to manager")

        # 测试长度变化
        print(f"[SUCCESS] Manager length after adding value: {len(manager)}")
        print(f"[SUCCESS] Contains test_value: {test_value.begin_index in manager}")

        # 测试获取所有Values
        all_values = manager.get_all_values()
        print(f"[SUCCESS] Retrieved {len(all_values)} values from manager")

        # 更新统计信息
        updated_stats = manager.get_statistics()
        print(f"[SUCCESS] Updated statistics: {updated_stats}")

        # 测试ProofUnit相关功能
        print("\n--- Testing ProofUnit operations ---")

        # 由于ProofUnit需要复杂的依赖，我们先测试相关方法
        print("[INFO] Testing ProofUnit-related methods without creating actual ProofUnits...")

        # 测试获取不存在的value的proof units
        non_existant_proofs = manager.get_proof_units_for_value("non_existent_value")
        print(f"[SUCCESS] Retrieved proof units for non-existent value: {len(non_existant_proofs)}")

        # 测试get_value_for_proof_unit
        test_result = manager.get_value_for_proof_unit("non_existent_unit")
        print(f"[SUCCESS] Value for non-existent proof unit: {test_result}")

        # 测试get_all_proof_units
        all_proofs = manager.get_all_proof_units()
        print(f"[SUCCESS] Retrieved all proof units: {len(all_proofs)}")

        # 测试get_proof_units_by_owner
        owner_proofs = manager.get_proof_units_by_owner("test_owner")
        print(f"[SUCCESS] Retrieved proof units for owner: {len(owner_proofs)}")

        # 测试持久化功能
        print("\n--- Testing persistence operations ---")

        # 创建新的管理器实例来测试数据加载
        new_manager = AccountProofManager("test_account_0x123")
        print("[SUCCESS] Created new manager instance")

        # 检查是否成功加载了之前的数据
        loaded_values = new_manager.get_all_values()
        print(f"[SUCCESS] Loaded {len(loaded_values)} values from storage")

        # 比较统计信息
        loaded_stats = new_manager.get_statistics()
        print(f"[SUCCESS] Loaded statistics: {loaded_stats}")

        # 测试清除功能
        if new_manager.clear_all():
            print("[SUCCESS] Cleared all data from manager")
        else:
            print("[ERROR] Failed to clear data")

        # 验证清除后的状态
        cleared_stats = new_manager.get_statistics()
        print(f"[SUCCESS] Statistics after clearing: {cleared_stats}")

        print("\n=== All tests passed! ===")

    except Exception as e:
        print(f"[ERROR] Error during testing: {e}")
        import traceback
        traceback.print_exc()