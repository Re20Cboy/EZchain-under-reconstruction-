import sqlite3
import json
import os
import hashlib
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from bitarray import bitarray
import math

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.proofs.ProofUnit import ProofUnit

class BloomFilter:
    """
    高效的布隆过滤器实现，用于快速检测ProofUnit是否已存在
    """

    def __init__(self, expected_items: int = 10000, false_positive_rate: float = 0.01):
        """
        初始化布隆过滤器

        Args:
            expected_items: 预期要存储的项目数量
            false_positive_rate: 期望的假阳性率
        """
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate

        # 计算最优的位数组大小和哈希函数数量
        self.size = self._calculate_size(expected_items, false_positive_rate)
        self.hash_count = self._calculate_hash_count(self.size, expected_items)

        # 初始化位数组
        self.bit_array = bitarray(self.size)
        self.bit_array.setall(0)

        # 已添加的项目计数
        self.item_count = 0

    def _calculate_size(self, n: int, p: float) -> int:
        """计算所需的位数组大小"""
        return int(-(n * math.log(p)) / (math.log(2) ** 2))

    def _calculate_hash_count(self, m: int, n: int) -> int:
        """计算最优的哈希函数数量"""
        return int((m / n) * math.log(2))

    def _get_hashes(self, item: str) -> List[int]:
        """生成项目的多个哈希值"""
        hashes = []
        # 使用双重哈希技术生成多个哈希值
        hash1 = int(hashlib.sha256(item.encode()).hexdigest(), 16)
        hash2 = int(hashlib.md5(item.encode()).hexdigest(), 16)

        for i in range(self.hash_count):
            combined_hash = (hash1 + i * hash2) % self.size
            hashes.append(combined_hash)

        return hashes

    def add(self, item: str) -> None:
        """添加项目到布隆过滤器"""
        hashes = self._get_hashes(item)
        for hash_val in hashes:
            self.bit_array[hash_val] = 1
        self.item_count += 1

    def __contains__(self, item: str) -> bool:
        """检查项目可能是否存在于过滤器中"""
        hashes = self._get_hashes(item)
        for hash_val in hashes:
            if not self.bit_array[hash_val]:
                return False
        return True

    def get_current_false_positive_rate(self) -> float:
        """获取当前假阳性率的估算值"""
        if self.item_count == 0:
            return 0.0
        return (1 - math.exp(-self.hash_count * self.item_count / self.size)) ** self.hash_count

    def reset(self) -> None:
        """重置布隆过滤器"""
        self.bit_array.setall(0)
        self.item_count = 0

    def __len__(self) -> int:
        """返回已添加的项目数量"""
        return self.item_count

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
            # value_id 存储的是ValueNode的node_id，不是begin_index
            # 添加sequence字段来维护proof unit的添加顺序
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_value_proofs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_address TEXT NOT NULL,
                    value_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_address) REFERENCES accounts (account_address),
                    FOREIGN KEY (unit_id) REFERENCES proof_units (unit_id),
                    UNIQUE(account_address, value_id, unit_id)
                )
            """)

            # 检查是否需要添加sequence字段（数据库迁移）
            self._check_and_migrate_sequence_column(conn)

            conn.commit()

    def _check_and_migrate_sequence_column(self, conn):
        """检查并迁移sequence字段"""
        try:
            cursor = conn.execute("PRAGMA table_info(account_value_proofs)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'sequence' not in columns:
                print("[AccountProofStorage] Migrating database: adding sequence column...")
                # 添加sequence字段
                conn.execute("ALTER TABLE account_value_proofs ADD COLUMN sequence INTEGER")

                # 为现有记录填充sequence值，按created_at排序
                cursor = conn.execute("""
                    SELECT account_address, value_id, unit_id, created_at
                    FROM account_value_proofs
                    ORDER BY account_address, value_id, created_at
                """)

                current_value = None
                sequence = 0

                for row in cursor.fetchall():
                    account_address, value_id, unit_id, created_at = row

                    # 如果切换到新的value，重置sequence
                    if current_value != (account_address, value_id):
                        current_value = (account_address, value_id)
                        sequence = 0

                    sequence += 1
                    conn.execute("""
                        UPDATE account_value_proofs
                        SET sequence = ?
                        WHERE account_address = ? AND value_id = ? AND unit_id = ?
                    """, (sequence, account_address, value_id, unit_id))

                print("[AccountProofStorage] Database migration completed successfully")
        except Exception as e:
            print(f"[AccountProofStorage] Error during database migration: {e}")

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

    def add_value_proof_mapping(self, account_address: str, value_id: str, unit_id: str) -> Tuple[bool, bool]:
        """添加账户-Value-ProofUnit的映射关系

        Returns:
            Tuple[bool, bool]: (操作是否成功, 映射是否是新增的)
        """
        try:
            # 确保账户存在
            if not self.ensure_account_exists(account_address):
                return False, False

            with sqlite3.connect(self.db_path) as conn:
                # 先检查是否已存在相同的映射
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ? AND unit_id = ?
                """, (account_address, value_id, unit_id))
                existing_count = cursor.fetchone()[0]

                # 如果已存在，返回成功但不是新增
                if existing_count > 0:
                    return True, False

                # 获取当前value的最大sequence值
                cursor = conn.execute("""
                    SELECT COALESCE(MAX(sequence), 0) FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ?
                """, (account_address, value_id))
                max_sequence = cursor.fetchone()[0]

                # 插入新的映射关系，sequence为最大值+1
                conn.execute("""
                    INSERT INTO account_value_proofs (account_address, value_id, unit_id, sequence)
                    VALUES (?, ?, ?, ?)
                """, (account_address, value_id, unit_id, max_sequence + 1))
                conn.commit()
                return True, True
        except Exception as e:
            print(f"Error adding value-proof mapping: {e}")
            return False, False

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

    def remove_value_info(self, account_address: str, value_id: str) -> bool:
        """移除Value相关的所有映射关系"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 删除相关的proof映射
                cursor = conn.execute("""
                    DELETE FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ?
                """, (account_address, value_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing value info: {e}")
            return False

    def get_proof_units_for_account_value(self, account_address: str, value_id: str) -> List[ProofUnit]:
        """获取指定账户和Value关联的所有ProofUnit（按添加顺序）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT unit_id FROM account_value_proofs
                    WHERE account_address = ? AND value_id = ?
                    ORDER BY sequence ASC
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
        """获取指定账户的所有Value-ProofUnit关系（按添加顺序）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT value_id, unit_id FROM account_value_proofs
                    WHERE account_address = ?
                    ORDER BY value_id, sequence ASC
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

    def __init__(self, account_address: str, storage: Optional[AccountProofStorage] = None,
                 bloom_filter_expected_items: int = 10000, bloom_filter_false_positive_rate: float = 0.01):
        self.account_address = account_address
        self.storage = storage or AccountProofStorage()

        # 内存缓存
        self._value_proof_mapping: Dict[str, List[str]] = defaultdict(list)  # value_id -> list of unit_ids (保持顺序)
        self._proof_units_cache: Dict[str, ProofUnit] = {}  # unit_id -> ProofUnit

        # 布隆过滤器用于快速重复检测
        self._proof_unit_bloom_filter = BloomFilter(
            expected_items=bloom_filter_expected_items,
            false_positive_rate=bloom_filter_false_positive_rate
        )

        # 加载现有映射
        self._load_existing_mappings()

    def _load_existing_mappings(self):
        """加载现有的映射关系到内存缓存（保持顺序）"""
        try:
            all_mappings = self.storage.get_all_proof_units_for_account(self.account_address)
            for value_id, proof_unit in all_mappings:
                self._value_proof_mapping[value_id].append(proof_unit.unit_id)
                self._proof_units_cache[proof_unit.unit_id] = proof_unit
                # 将已存在的ProofUnit添加到布隆过滤器
                self._proof_unit_bloom_filter.add(proof_unit.unit_id)
        except Exception as e:
            print(f"Error loading existing mappings: {e}")

    def add_value(self, node_id: str) -> bool:
        """
        添加Value到管理器中（仅建立映射，不存储Value数据）

        Args:
            node_id: ValueNode的node_id，唯一标识符

        Returns:
            bool: 添加是否成功
        """
        try:
            # 初始化该Value的proof映射（空列表）
            value_id = node_id
            if value_id not in self._value_proof_mapping:
                self._value_proof_mapping[value_id] = []

            # 精简输出: print(f"[AccountProofManager] Added value mapping for {value_id} (value data stored in ValueCollection)")
            return True
        except Exception as e:
            print(f"Error adding value: {e}")
            return False

    def remove_value(self, value_id: str) -> bool:
        """
        从管理器中移除Value及其所有ProofUnit映射

        Args:
            value_id: Value的标识符（应该是ValueNode的node_id）

        Returns:
            bool: 移除是否成功
        """
        try:
            # 获取该Value关联的所有ProofUnit
            unit_ids = list(self._value_proof_mapping.get(value_id, []))

            # 移除所有映射关系
            for unit_id in unit_ids:
                if not self.remove_value_proof_mapping(value_id, unit_id):
                    pass
                    # print(f"Warning: Failed to remove mapping for value {value_id}, unit {unit_id}")

            # 从存储中删除Value相关的映射关系
            if not self.storage.remove_value_info(self.account_address, value_id):
                pass
                # print(f"Warning: Failed to remove value mappings for {value_id}")

            # 从内存缓存中删除
            if value_id in self._value_proof_mapping:
                del self._value_proof_mapping[value_id]

            # print(f"[AccountProofManager] Removed value mapping for {value_id}")
            return True
        except Exception as e:
            print(f"Error removing value: {e}")
            return False

  
    def add_proof_unit_optimized(self, value_id: str, proof_unit: ProofUnit) -> bool:
        """
        优化的ProofUnit添加方法，使用布隆过滤器进行高效重复检测

        该方法结合了内存中布隆过滤器的快速检测和数据库的准确性验证：
        1. 首先使用布隆过滤器快速检测是否可能重复
        2. 如果布隆过滤器显示可能重复，才进行数据库查询确认
        3. 如果确认为新ProofUnit，则存储并添加到布隆过滤器

        Args:
            value_id: Value的标识符（应该是ValueNode的node_id）
            proof_unit: 要添加的ProofUnit

        Returns:
            bool: 添加是否成功
        """
        try:
            unit_id = proof_unit.unit_id

            # 第一步：布隆过滤器快速检测
            if unit_id in self._proof_unit_bloom_filter:
                # 布隆过滤器显示可能存在，需要进行数据库查询确认
                existing_unit = self.storage.load_proof_unit(unit_id)
                if existing_unit:
                    # 确认已存在，增加引用计数
                    existing_unit.increment_reference()
                    if not self.storage.store_proof_unit(existing_unit):
                        return False

                    unit_to_use = existing_unit
                    operation = "existing_proof_unit_updated"
                else:
                    # 布隆过滤器误报（假阳性），实际不存在，添加为新ProofUnit
                    if not self.storage.store_proof_unit(proof_unit):
                        return False

                    self._proof_unit_bloom_filter.add(unit_id)
                    unit_to_use = proof_unit
                    operation = "new_proof_unit_added_bloom_false_positive"
            else:
                # 布隆过滤器确认不存在，直接添加为新ProofUnit
                if not self.storage.store_proof_unit(proof_unit):
                    return False

                # 添加到布隆过滤器
                self._proof_unit_bloom_filter.add(unit_id)
                unit_to_use = proof_unit
                operation = "new_proof_unit_added"

            # 添加映射关系
            success, mapping_is_new = self.storage.add_value_proof_mapping(self.account_address, value_id, unit_to_use.unit_id)

            if not success:
                return False

            # 只有当映射是真正新增的时候，才更新内存缓存
            if mapping_is_new:
                # 检查unit_id是否已经在内存缓存中，避免重复添加
                if unit_to_use.unit_id not in self._value_proof_mapping[value_id]:
                    self._value_proof_mapping[value_id].append(unit_to_use.unit_id)
                    self._proof_units_cache[unit_to_use.unit_id] = unit_to_use
                    # 精简输出: print(f"[AccountProofManager] Optimized add proof unit: {operation} - {unit_id}")
            else:
                # 映射已存在，但需要更新reference_count（如果是existing_proof_unit_updated）
                if operation == "existing_proof_unit_updated":
                    self._proof_units_cache[unit_to_use.unit_id] = unit_to_use
                # 精简输出: print(f"[AccountProofManager] Optimized add proof unit: mapping already exists - {unit_id}")

            return True

        except Exception as e:
            print(f"Error adding proof unit optimized: {e}")
            return False

    def add_proof_unit_optimized_with_stats(self, value_id: str, proof_unit: ProofUnit) -> Tuple[bool, dict]:
        """
        优化的ProofUnit添加方法（带统计信息），使用布隆过滤器进行高效重复检测

        Args:
            value_id: Value的标识符（应该是ValueNode的node_id）
            proof_unit: 要添加的ProofUnit

        Returns:
            Tuple[bool, dict]: (是否成功, 统计信息字典)
        """
        stats = {
            'operation_type': '',
            'bloom_check_time': 0,
            'db_query_time': 0,
            'bloom_false_positive': False,
            'current_bloom_false_positive_rate': 0.0,
            'bloom_size': len(self._proof_unit_bloom_filter)
        }

        import time
        start_time = time.time()

        try:
            unit_id = proof_unit.unit_id

            # 布隆过滤器检测计时
            bloom_start = time.time()
            bloom_result = unit_id in self._proof_unit_bloom_filter
            stats['bloom_check_time'] = time.time() - bloom_start

            if bloom_result:
                # 布隆过滤器显示可能存在
                db_start = time.time()
                existing_unit = self.storage.load_proof_unit(unit_id)
                stats['db_query_time'] = time.time() - db_start

                if existing_unit:
                    # 确认已存在
                    existing_unit.increment_reference()
                    if not self.storage.store_proof_unit(existing_unit):
                        return False, stats

                    unit_to_use = existing_unit
                    stats['operation_type'] = 'existing_proof_unit_updated'
                else:
                    # 布隆过滤器误报
                    stats['bloom_false_positive'] = True
                    if not self.storage.store_proof_unit(proof_unit):
                        return False, stats

                    self._proof_unit_bloom_filter.add(unit_id)
                    unit_to_use = proof_unit
                    stats['operation_type'] = 'new_proof_unit_added_bloom_false_positive'
            else:
                # 布隆过滤器确认不存在
                stats['db_query_time'] = 0  # 无需数据库查询

                if not self.storage.store_proof_unit(proof_unit):
                    return False, stats

                self._proof_unit_bloom_filter.add(unit_id)
                unit_to_use = proof_unit
                stats['operation_type'] = 'new_proof_unit_added'

            # 添加映射关系
            if self.storage.add_value_proof_mapping(self.account_address, value_id, unit_to_use.unit_id):
                # 更新内存缓存
                self._value_proof_mapping[value_id].append(unit_to_use.unit_id)
                self._proof_units_cache[unit_to_use.unit_id] = unit_to_use

                # 更新统计信息
                stats['current_bloom_false_positive_rate'] = self._proof_unit_bloom_filter.get_current_false_positive_rate()
                stats['total_time'] = time.time() - start_time

                return True, stats

            return False, stats

        except Exception as e:
            print(f"Error adding proof unit optimized with stats: {e}")
            stats['total_time'] = time.time() - start_time
            return False, stats

    def get_bloom_filter_stats(self) -> dict:
        """
        获取布隆过滤器的统计信息

        Returns:
            dict: 布隆过滤器统计信息
        """
        return {
            'expected_items': self._proof_unit_bloom_filter.expected_items,
            'current_items': len(self._proof_unit_bloom_filter),
            'target_false_positive_rate': self._proof_unit_bloom_filter.false_positive_rate,
            'current_false_positive_rate': self._proof_unit_bloom_filter.get_current_false_positive_rate(),
            'bit_array_size': self._proof_unit_bloom_filter.size,
            'hash_count': self._proof_unit_bloom_filter.hash_count
        }

    def reset_bloom_filter(self) -> None:
        """
        重置布隆过滤器（谨慎使用，仅在确认需要时调用）
        重置后会重新从数据库加载所有现有的ProofUnit到新的布隆过滤器
        """
        self._proof_unit_bloom_filter.reset()

        # 重新加载所有现有的ProofUnit到布隆过滤器
        try:
            all_mappings = self.storage.get_all_proof_units_for_account(self.account_address)
            for value_id, proof_unit in all_mappings:
                self._proof_unit_bloom_filter.add(proof_unit.unit_id)
            # 精简输出: print(f"[AccountProofManager] Bloom filter reset and reloaded with {len(all_mappings)} proof units")
        except Exception as e:
            print(f"Error reloading bloom filter after reset: {e}")

    def batch_add_values(self, node_ids: List[str]) -> bool:
        """
        批量添加Values到管理器中（仅建立映射，不存储Value数据）

        Args:
            node_ids: 要添加的node_id列表

        Returns:
            bool: 批量添加是否成功
        """
        if not node_ids:
            return True

        try:
            # 批量初始化Value的proof映射
            for node_id in node_ids:
                value_id = node_id
                if value_id not in self._value_proof_mapping:
                    self._value_proof_mapping[value_id] = []

            # 精简输出: print(f"[AccountProofManager] Batch added value mappings for {len(node_ids)} values (data stored in ValueCollection)")
            return True
        except Exception as e:
            print(f"Error during batch add values: {e}")
            import traceback
            print(f"Batch add values traceback: {traceback.format_exc()}")
            return False

    def batch_add_proof_units(self, value_proof_pairs: List[Tuple[str, ProofUnit]]) -> bool:
        """
        批量添加ProofUnits到指定Values，不进行重复检测（提高效率）

        Args:
            value_proof_pairs: (value_id, proof_unit) 元组的列表

        Returns:
            bool: 批量添加是否成功
        """
        if not value_proof_pairs:
            return True

        try:
            # 批量存储ProofUnits
            for value_id, proof_unit in value_proof_pairs:
                # 直接存储新的ProofUnit，不进行重复检测
                if not self.storage.store_proof_unit(proof_unit):
                    print(f"Error: Failed to store proof unit {proof_unit.unit_id} for value {value_id}")
                    return False

                # 添加映射关系
                if not self.storage.add_value_proof_mapping(self.account_address, value_id, proof_unit.unit_id):
                    print(f"Error: Failed to add mapping for value {value_id}, proof {proof_unit.unit_id}")
                    return False

                # 更新内存缓存
                self._value_proof_mapping[value_id].append(proof_unit.unit_id)
                self._proof_units_cache[proof_unit.unit_id] = proof_unit

            return True
        except Exception as e:
            print(f"Error during batch add proof units: {e}")
            import traceback
            print(f"Batch add proof units traceback: {traceback.format_exc()}")
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
                    if unit_id in self._value_proof_mapping[value_id]:
                        self._value_proof_mapping[value_id].remove(unit_id)

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
            unit_ids = self._value_proof_mapping.get(value_id, [])

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

    
    def get_all_value_ids(self) -> List[str]:
        """
        获取账户的所有Value ID列表

        Returns:
            List[str]: Value ID列表
        """
        try:
            return list(self._value_proof_mapping.keys())
        except Exception as e:
            print(f"Error getting all value IDs: {e}")
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
    # 导入测试所需的Value类
    from EZ_VPB.values.Value import Value

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
        test_node_id = "test_node_123"
        if manager.add_value(test_node_id):
            print("[SUCCESS] Value added to manager")
        else:
            print("[ERROR] Failed to add value to manager")

        # 测试长度变化
        print(f"[SUCCESS] Manager length after adding value: {len(manager)}")
        print(f"[SUCCESS] Contains test_node_id: {test_node_id in manager}")

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