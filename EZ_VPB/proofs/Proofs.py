import sqlite3
import json
import os
from typing import Dict, List, Set, Optional, Tuple
import warnings

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from .ProofUnit import ProofUnit
from .AccountProofManager import AccountProofManager

class LegacyProofsStorage:
    """
    Legacy storage for backward compatibility.
    已弃用：建议使用AccountProofStorage
    """

    def __init__(self, db_path: str = "ez_proof_storage.db"):
        warnings.warn(
            "LegacyProofsStorage is deprecated. Use AccountProofStorage instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS value_proofs_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    value_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (unit_id) REFERENCES proof_units (unit_id),
                    UNIQUE(value_id, unit_id)
                )
            """)
            conn.commit()

    def store_proof_unit(self, proof_unit: ProofUnit) -> bool:
        """Store or update a ProofUnit in the database"""
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
        """Load a ProofUnit from the database by unit_id"""
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
        """Delete a ProofUnit from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM proof_units WHERE unit_id = ?", (unit_id,))
                conn.execute("DELETE FROM value_proofs_mapping WHERE unit_id = ?", (unit_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting ProofUnit: {e}")
            return False

    def add_value_mapping(self, value_id: str, unit_id: str) -> bool:
        """Add mapping between a Value and a ProofUnit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO value_proofs_mapping (value_id, unit_id)
                    VALUES (?, ?)
                """, (value_id, unit_id))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error adding value mapping: {e}")
            return False

    def remove_value_mapping(self, value_id: str, unit_id: str) -> bool:
        """Remove mapping between a Value and a ProofUnit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM value_proofs_mapping
                    WHERE value_id = ? AND unit_id = ?
                """, (value_id, unit_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing value mapping: {e}")
            return False

    def get_proof_units_for_value(self, value_id: str) -> List[ProofUnit]:
        """Get all ProofUnits associated with a specific Value"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT unit_id FROM value_proofs_mapping WHERE value_id = ?
                """, (value_id,))

                proof_units = []
                for row in cursor.fetchall():
                    unit_id = row[0]
                    proof_unit = self.load_proof_unit(unit_id)
                    if proof_unit:
                        proof_units.append(proof_unit)
                return proof_units
        except Exception as e:
            print(f"Error getting proof units for value: {e}")
            return []

class Proofs:
    """
    Legacy Proofs class for backward compatibility.
    已弃用：建议使用AccountProofManager作为Account级别的统一管理接口

    这个类是以单个Value为视角的proof unit映射，设计上存在局限性。
    新的架构推荐使用AccountProofManager来管理Account级别的所有Value和ProofUnit关系。
    """

    def __init__(self, value_id: str, account_address: Optional[str] = None,
                 storage: Optional[LegacyProofsStorage] = None,
                 account_proof_manager: Optional[AccountProofManager] = None):
        """
        初始化Proofs对象

        Args:
            value_id: Value的标识符
            account_address: 账户地址（可选，用于兼容性）
            storage: Legacy存储对象（已弃用）
            account_proof_manager: 新的AccountProofManager对象（推荐使用）
        """
        warnings.warn(
            "Proofs class is deprecated. Use AccountProofManager for better architecture.",
            DeprecationWarning,
            stacklevel=2
        )

        self.value_id = value_id
        self.account_address = account_address or "default_account"

        # 优先使用新的AccountProofManager
        if account_proof_manager is not None:
            self.account_proof_manager = account_proof_manager
            self.use_legacy_storage = False
        else:
            # 回退到旧的存储系统
            self.storage = storage or LegacyProofsStorage()
            self.use_legacy_storage = True
            self._proof_unit_ids: Set[str] = set()
            self._proof_units_cache: Dict[str, ProofUnit] = {}
            self._load_existing_mappings()

    def _load_existing_mappings(self):
        """Load existing proof unit mappings for this value (legacy method)"""
        if self.use_legacy_storage:
            proof_units = self.storage.get_proof_units_for_value(self.value_id)
            for pu in proof_units:
                self._proof_unit_ids.add(pu.unit_id)
                self._proof_units_cache[pu.unit_id] = pu

    def add_proof_unit(self, proof_unit: ProofUnit) -> bool:
        """
        Add a ProofUnit to this Proofs collection

        Args:
            proof_unit: 要添加的ProofUnit

        Returns:
            bool: 添加是否成功
        """
        if self.use_legacy_storage:
            # Legacy implementation
            try:
                # Check if similar ProofUnit already exists in storage
                existing_unit = self.storage.load_proof_unit(proof_unit.unit_id)

                if existing_unit:
                    # Use existing ProofUnit and increment reference
                    existing_unit.increment_reference()
                    self.storage.store_proof_unit(existing_unit)
                    proof_unit_id = existing_unit.unit_id
                else:
                    # Store new ProofUnit
                    self.storage.store_proof_unit(proof_unit)
                    proof_unit_id = proof_unit.unit_id

                # Add mapping
                if self.storage.add_value_mapping(self.value_id, proof_unit_id):
                    self._proof_unit_ids.add(proof_unit_id)
                    if proof_unit_id in self._proof_units_cache:
                        del self._proof_units_cache[proof_unit_id]
                    return True

                return False
            except Exception as e:
                print(f"Error adding proof unit: {e}")
                return False
        else:
            # New implementation using AccountProofManager
            return self.account_proof_manager.add_proof_unit(self.value_id, proof_unit)

    def remove_proof_unit(self, unit_id: str) -> bool:
        """
        Remove a ProofUnit from this Proofs collection

        Args:
            unit_id: 要移除的ProofUnit ID

        Returns:
            bool: 移除是否成功
        """
        if self.use_legacy_storage:
            # Legacy implementation
            try:
                if self.storage.remove_value_mapping(self.value_id, unit_id):
                    self._proof_unit_ids.discard(unit_id)
                    if unit_id in self._proof_units_cache:
                        del self._proof_units_cache[unit_id]

                    # Check if ProofUnit can be deleted from storage
                    proof_unit = self.storage.load_proof_unit(unit_id)
                    if proof_unit:
                        proof_unit.decrement_reference()
                        if proof_unit.can_be_deleted():
                            self.storage.delete_proof_unit(unit_id)
                        else:
                            self.storage.store_proof_unit(proof_unit)

                    return True
                return False
            except Exception as e:
                print(f"Error removing proof unit: {e}")
                return False
        else:
            # New implementation using AccountProofManager
            return self.account_proof_manager.remove_value_proof_mapping(self.value_id, unit_id)

    def get_proof_units(self) -> List[ProofUnit]:
        """
        Get all ProofUnits in this collection

        Returns:
            List[ProofUnit]: ProofUnit列表
        """
        if self.use_legacy_storage:
            # Legacy implementation
            proof_units = []
            for unit_id in self._proof_unit_ids:
                if unit_id in self._proof_units_cache:
                    proof_units.append(self._proof_units_cache[unit_id])
                else:
                    proof_unit = self.storage.load_proof_unit(unit_id)
                    if proof_unit:
                        self._proof_units_cache[unit_id] = proof_unit
                        proof_units.append(proof_unit)
            return proof_units
        else:
            # New implementation using AccountProofManager
            return self.account_proof_manager.get_proof_units_for_value(self.value_id)

    def verify_all_proof_units(self, merkle_root: str = None) -> List[Tuple[bool, str]]:
        """
        Verify all ProofUnits in the collection.

        Args:
            merkle_root: The Merkle root hash to verify against (optional)

        Returns:
            List[Tuple[bool, str]]: A list of tuples containing the verification result
            and an error message (if any) for each ProofUnit.
        """
        proof_units = self.get_proof_units()
        results = []

        for pu in proof_units:
            is_valid, error_message = pu.verify_proof_unit(merkle_root)
            results.append((is_valid, error_message))

        return results

    def get_proof_unit_count(self) -> int:
        """
        Get the number of ProofUnits in this collection

        Returns:
            int: ProofUnit数量
        """
        if self.use_legacy_storage:
            return len(self._proof_unit_ids)
        else:
            return len(self.account_proof_manager.get_proof_units_for_value(self.value_id))

    def clear_all(self) -> bool:
        """
        Remove all ProofUnits from this collection

        Returns:
            bool: 清除是否成功
        """
        if self.use_legacy_storage:
            success = True
            for unit_id in list(self._proof_unit_ids):
                if not self.remove_proof_unit(unit_id):
                    success = False
            return success
        else:
            # For AccountProofManager, we need to remove the value entirely
            return self.account_proof_manager.remove_value(self.value_id)

    def migrate_to_account_proof_manager(self, account_address: str) -> AccountProofManager:
        """
        迁移到新的AccountProofManager架构

        Args:
            account_address: 目标账户地址

        Returns:
            AccountProofManager: 新的管理器实例
        """
        try:
            # 创建新的AccountProofManager
            new_manager = AccountProofManager(account_address)

            if self.use_legacy_storage:
                # 从旧系统迁移数据
                for proof_unit in self.get_proof_units():
                    new_manager.add_proof_unit(self.value_id, proof_unit)

            # 切换到新系统
            self.account_proof_manager = new_manager
            self.use_legacy_storage = False
            self.account_address = account_address

            return new_manager
        except Exception as e:
            print(f"Error migrating to AccountProofManager: {e}")
            return None

    def __len__(self):
        return self.get_proof_unit_count()

    def __contains__(self, unit_id: str) -> bool:
        if self.use_legacy_storage:
            return unit_id in self._proof_unit_ids
        else:
            proof_units = self.account_proof_manager.get_proof_units_for_value(self.value_id)
            return any(pu.unit_id == unit_id for pu in proof_units)

    def __iter__(self):
        return iter(self.get_proof_units())
