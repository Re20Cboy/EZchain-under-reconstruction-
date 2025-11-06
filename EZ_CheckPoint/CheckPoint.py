"""
Checkpoint类是EZchain的核心优化组件, 基于"价值状态快照"设计理念。
其核心作用是记录Value的合法状态基准, 使交易验证时无需追溯完整历史, 仅需校验检查点之后的交易链路,
从而降低存储占用、通信开销和计算复杂度。

Checkpoint生成机制: 当Value完成一次合法交易且被主链确认后（例如区块高度为h）,
发送方（Value的旧持有者x）可创建/更新该Value的检查点, 记录信息为:
(Value; sender x's addr; block height h-1)
表明Value在区块高度h-1时最后由sender addr合法持有。

Checkpoint触发机制: 当此Value在后续未来交易中被再次支付给x时, 系统会自动触发检查点验证, 而非全历史遍历验证。

Checkpoint更新机制： 当Value再次被x支付后(交易确认高度为h_2), x可更新该Value的检查点为最新状态:
(Value; sender x's addr; new block height h_2-1)

Checkpoint生成、触发、更新等均需对外提供接口。

此外, Checkpoint类还需支持序列化与反序列化功能, 以便在存储时保持数据完整性；
支持永久存储与加载, 以确保系统重启后检查点数据不丢失；
支持快速查询与检索, 以提升交易验证效率（注意，用户视角下能操作input的只有vpb结构）。

"""

import sqlite3
import json
import threading
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value.Value import Value


@dataclass
class CheckPointRecord:
    """检查点记录数据结构"""
    value_begin_index: str  # Value的开始索引
    value_num: int  # Value的数量
    owner_address: str  # 持有者地址
    block_height: int  # 区块高度
    created_at: datetime  # 创建时间
    updated_at: datetime  # 更新时间

    @property
    def value_end_index(self) -> str:
        """计算Value的结束索引"""
        decimal_number = int(self.value_begin_index, 16)
        result = decimal_number + self.value_num - 1
        return hex(result)

    def matches_value(self, value: Value) -> bool:
        """检查检查点记录是否精确匹配给定的Value"""
        return (self.value_begin_index == value.begin_index and
                self.value_num == value.value_num)

    def contains_value(self, value: Value) -> bool:
        """检查给定的Value是否完全包含在此检查点记录的Value范围内"""
        checkpoint_end = int(self.value_begin_index, 16) + self.value_num - 1
        input_end = int(value.end_index, 16)

        return (int(self.value_begin_index, 16) <= int(value.begin_index, 16) and
                checkpoint_end >= input_end)

    def to_value(self) -> Value:
        """将检查点记录转换为Value对象"""
        return Value(self.value_begin_index, self.value_num)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'value_begin_index': self.value_begin_index,
            'value_num': self.value_num,
            'owner_address': self.owner_address,
            'block_height': self.block_height,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CheckPointRecord':
        """从字典创建记录"""
        return cls(
            value_begin_index=data['value_begin_index'],
            value_num=data['value_num'],
            owner_address=data['owner_address'],
            block_height=data['block_height'],
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at'])
        )


class CheckPointStorage:
    """检查点永久存储管理器，使用SQLite提供持久化存储"""

    def __init__(self, db_path: str = "ez_checkpoint_storage.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_database()

    def _init_database(self):
        """初始化SQLite数据库表结构"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        value_begin_index TEXT NOT NULL,
                        value_num INTEGER NOT NULL,
                        owner_address TEXT NOT NULL,
                        block_height INTEGER NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        UNIQUE(value_begin_index, value_num)
                    )
                """)

                # 创建索引以提升查询性能
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_checkpoints_value_composite
                    ON checkpoints(value_begin_index, value_num)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_checkpoints_owner_address
                    ON checkpoints(owner_address)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_checkpoints_block_height
                    ON checkpoints(block_height)
                """)

                conn.commit()

    def store_checkpoint(self, checkpoint: CheckPointRecord) -> bool:
        """存储或更新检查点记录"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO checkpoints
                        (value_begin_index, value_num, owner_address, block_height, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        checkpoint.value_begin_index,
                        checkpoint.value_num,
                        checkpoint.owner_address,
                        checkpoint.block_height,
                        checkpoint.created_at,
                        checkpoint.updated_at
                    ))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"存储检查点失败: {e}")
            return False

    def load_checkpoint(self, value_begin_index: str, value_num: int) -> Optional[CheckPointRecord]:
        """加载特定Value的检查点记录"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT value_begin_index, value_num, owner_address, block_height, created_at, updated_at
                        FROM checkpoints
                        WHERE value_begin_index = ? AND value_num = ?
                    """, (value_begin_index, value_num))
                    row = cursor.fetchone()

                    if row:
                        return CheckPointRecord(
                            value_begin_index=row[0],
                            value_num=row[1],
                            owner_address=row[2],
                            block_height=row[3],
                            created_at=datetime.fromisoformat(row[4]),
                            updated_at=datetime.fromisoformat(row[5])
                        )
                    return None
        except Exception as e:
            print(f"加载检查点失败: {e}")
            return None

    def load_checkpoints_by_owner(self, owner_address: str) -> List[CheckPointRecord]:
        """加载特定地址的所有检查点记录"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT value_begin_index, value_num, owner_address, block_height, created_at, updated_at
                        FROM checkpoints
                        WHERE owner_address = ?
                        ORDER BY block_height DESC
                    """, (owner_address,))

                    checkpoints = []
                    for row in cursor.fetchall():
                        checkpoints.append(CheckPointRecord(
                            value_begin_index=row[0],
                            value_num=row[1],
                            owner_address=row[2],
                            block_height=row[3],
                            created_at=datetime.fromisoformat(row[4]),
                            updated_at=datetime.fromisoformat(row[5])
                        ))
                    return checkpoints
        except Exception as e:
            print(f"按所有者加载检查点失败: {e}")
            return []

    def delete_checkpoint(self, value_begin_index: str, value_num: int) -> bool:
        """删除特定Value的检查点记录"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        DELETE FROM checkpoints WHERE value_begin_index = ? AND value_num = ?
                    """, (value_begin_index, value_num))
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            print(f"删除检查点失败: {e}")
            return False

    def load_all_checkpoints(self) -> List[CheckPointRecord]:
        """加载所有检查点记录"""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        SELECT value_begin_index, value_num, owner_address, block_height, created_at, updated_at
                        FROM checkpoints
                        ORDER BY block_height DESC
                    """)

                    checkpoints = []
                    for row in cursor.fetchall():
                        checkpoints.append(CheckPointRecord(
                            value_begin_index=row[0],
                            value_num=row[1],
                            owner_address=row[2],
                            block_height=row[3],
                            created_at=datetime.fromisoformat(row[4]),
                            updated_at=datetime.fromisoformat(row[5])
                        ))
                    return checkpoints
        except Exception as e:
            print(f"加载所有检查点失败: {e}")
            return []

    def find_checkpoint_containing_value(self, value: Value) -> Optional[CheckPointRecord]:
        """
        查找包含给定Value的检查点记录

        Args:
            value: Value对象（可能是拆分后的子Value）

        Returns:
            CheckPointRecord: 包含该Value的检查点记录，不存在返回None
        """
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    # 计算输入Value的范围
                    input_begin = int(value.begin_index, 16)
                    input_end = int(value.end_index, 16)

                    # 查找所有可能的包含检查点
                    cursor = conn.execute("""
                        SELECT value_begin_index, value_num, owner_address, block_height, created_at, updated_at
                        FROM checkpoints
                        ORDER BY block_height DESC
                    """)

                    for row in cursor.fetchall():
                        checkpoint = CheckPointRecord(
                            value_begin_index=row[0],
                            value_num=row[1],
                            owner_address=row[2],
                            block_height=row[3],
                            created_at=datetime.fromisoformat(row[4]),
                            updated_at=datetime.fromisoformat(row[5])
                        )

                        # 检查是否包含输入Value
                        if checkpoint.contains_value(value):
                            return checkpoint

                    return None
        except Exception as e:
            print(f"查找包含检查点失败: {e}")
            return None


class CheckPoint:
    """
    EZchain Checkpoint管理器

    基于价值状态快照设计理念，提供检查点的创建、更新、查询和验证功能。
    检查点作为Value合法状态的基准，显著降低交易验证时的存储和计算开销。
    """

    def __init__(self, storage_path: str = "ez_checkpoint_storage.db"):
        self.storage = CheckPointStorage(storage_path)
        self._lock = threading.RLock()

        # 缓存热点检查点数据以提升查询性能
        # 缓存键使用 (begin_index, value_num) 元组
        self._checkpoint_cache: Dict[Tuple[str, int], CheckPointRecord] = {}

    def create_checkpoint(self, value: Value, owner_address: str, block_height: int) -> bool:
        """
        创建新的检查点记录

        Args:
            value: Value对象
            owner_address: 持有者地址
            block_height: 区块高度（交易确认高度-1）

        Returns:
            bool: 创建成功返回True
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        if not isinstance(owner_address, str) or not owner_address.strip():
            raise ValueError("owner_address必须是非空字符串")

        if not isinstance(block_height, int) or block_height < 0:
            raise ValueError("block_height必须是非负整数")

        current_time = datetime.now(timezone.utc)
        cache_key = (value.begin_index, value.value_num)

        checkpoint = CheckPointRecord(
            value_begin_index=value.begin_index,
            value_num=value.value_num,
            owner_address=owner_address,
            block_height=block_height,
            created_at=current_time,
            updated_at=current_time
        )

        # 存储到数据库
        success = self.storage.store_checkpoint(checkpoint)

        if success:
            # 更新缓存
            with self._lock:
                self._checkpoint_cache[cache_key] = checkpoint

        return success

    def update_checkpoint(self, value: Value, new_owner_address: str, new_block_height: int) -> bool:
        """
        更新现有的检查点记录

        Args:
            value: Value对象
            new_owner_address: 新的持有者地址
            new_block_height: 新的区块高度（交易确认高度-1）

        Returns:
            bool: 更新成功返回True，检查点不存在返回False
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        if not isinstance(new_owner_address, str) or not new_owner_address.strip():
            raise ValueError("new_owner_address必须是非空字符串")

        if not isinstance(new_block_height, int) or new_block_height < 0:
            raise ValueError("new_block_height必须是非负整数")

        cache_key = (value.begin_index, value.value_num)
        current_time = datetime.now(timezone.utc)

        # 检查检查点是否存在
        existing_checkpoint = self.get_checkpoint(value)
        if not existing_checkpoint:
            return False

        # 创建更新后的检查点
        updated_checkpoint = CheckPointRecord(
            value_begin_index=value.begin_index,
            value_num=value.value_num,
            owner_address=new_owner_address,
            block_height=new_block_height,
            created_at=existing_checkpoint.created_at,
            updated_at=current_time
        )

        # 存储到数据库
        success = self.storage.store_checkpoint(updated_checkpoint)

        if success:
            # 更新缓存
            with self._lock:
                self._checkpoint_cache[cache_key] = updated_checkpoint

        return success

    def get_checkpoint(self, value: Value) -> Optional[CheckPointRecord]:
        """
        获取Value的检查点记录（精确匹配）

        Args:
            value: Value对象

        Returns:
            CheckPointRecord: 检查点记录，不存在返回None
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        cache_key = (value.begin_index, value.value_num)

        # 首先检查缓存
        with self._lock:
            if cache_key in self._checkpoint_cache:
                return self._checkpoint_cache[cache_key]

        # 从数据库加载
        checkpoint = self.storage.load_checkpoint(value.begin_index, value.value_num)

        # 更新缓存
        if checkpoint:
            with self._lock:
                self._checkpoint_cache[cache_key] = checkpoint

        return checkpoint

    def find_containing_checkpoint(self, value: Value) -> Optional[CheckPointRecord]:
        """
        查找包含给定Value的检查点记录（包含匹配）

        用于处理Value被拆分后的检查点验证场景

        Args:
            value: Value对象（可能是拆分后的子Value）

        Returns:
            CheckPointRecord: 包含该Value的检查点记录，不存在返回None
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        # 首先尝试精确匹配
        exact_match = self.get_checkpoint(value)
        if exact_match:
            return exact_match

        # 如果没有精确匹配，查找包含关系的检查点
        return self.storage.find_checkpoint_containing_value(value)

    def trigger_checkpoint_verification(self, value: Value, expected_owner: str) -> Optional[CheckPointRecord]:
        """
        触发检查点验证机制

        当Value在交易中被支付给特定地址时，自动触发检查点验证。
        支持包含匹配，适用于Value被拆分后的验证场景。

        Args:
            value: Value对象（可能是拆分后的子Value）
            expected_owner: 期望的持有者地址

        Returns:
            CheckPointRecord: 匹配的检查点记录，不匹配或不存在返回None
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        # 使用包含匹配查找检查点
        checkpoint = self.find_containing_checkpoint(value)

        if checkpoint and checkpoint.owner_address == expected_owner:
            return checkpoint

        return None

    def find_checkpoints_by_owner(self, owner_address: str) -> List[CheckPointRecord]:
        """
        查找特定地址的所有检查点

        Args:
            owner_address: 持有者地址

        Returns:
            List[CheckPointRecord]: 检查点记录列表
        """
        if not isinstance(owner_address, str) or not owner_address.strip():
            raise ValueError("owner_address必须是非空字符串")

        return self.storage.load_checkpoints_by_owner(owner_address)

    def delete_checkpoint(self, value: Value) -> bool:
        """
        删除Value的检查点记录

        Args:
            value: Value对象

        Returns:
            bool: 删除成功返回True，不存在返回False
        """
        if not isinstance(value, Value):
            raise TypeError("value必须是Value对象")

        cache_key = (value.begin_index, value.value_num)

        # 从数据库删除
        success = self.storage.delete_checkpoint(value.begin_index, value.value_num)

        if success:
            # 从缓存删除
            with self._lock:
                self._checkpoint_cache.pop(cache_key, None)

        return success

    def list_all_checkpoints(self) -> List[CheckPointRecord]:
        """
        列出所有检查点记录

        Returns:
            List[CheckPointRecord]: 所有检查点记录列表
        """
        return self.storage.load_all_checkpoints()

    def clear_cache(self):
        """清空检查点缓存"""
        with self._lock:
            self._checkpoint_cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            return {
                'cache_size': len(self._checkpoint_cache),
                'cached_value_keys': [f"({begin_index}, {value_num})" for begin_index, value_num in self._checkpoint_cache.keys()]
            }

    def serialize_to_json(self, checkpoint: CheckPointRecord) -> str:
        """
        将检查点记录序列化为JSON字符串

        Args:
            checkpoint: 检查点记录

        Returns:
            str: JSON字符串
        """
        return json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2)

    def deserialize_from_json(self, json_str: str) -> CheckPointRecord:
        """
        从JSON字符串反序列化检查点记录

        Args:
            json_str: JSON字符串

        Returns:
            CheckPointRecord: 检查点记录
        """
        data = json.loads(json_str)
        return CheckPointRecord.from_dict(data)

    def export_checkpoints(self, file_path: str) -> bool:
        """
        导出所有检查点到文件

        Args:
            file_path: 导出文件路径

        Returns:
            bool: 导出成功返回True
        """
        try:
            checkpoints = self.list_all_checkpoints()
            export_data = {
                'export_time': datetime.now(timezone.utc).isoformat(),
                'total_checkpoints': len(checkpoints),
                'checkpoints': [cp.to_dict() for cp in checkpoints]
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"导出检查点失败: {e}")
            return False

    def import_checkpoints(self, file_path: str, overwrite: bool = False) -> int:
        """
        从文件导入检查点

        Args:
            file_path: 导入文件路径
            overwrite: 是否覆盖已存在的检查点

        Returns:
            int: 成功导入的检查点数量
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            imported_count = 0
            checkpoints_data = import_data.get('checkpoints', [])

            for cp_data in checkpoints_data:
                checkpoint = CheckPointRecord.from_dict(cp_data)

                if not overwrite:
                    existing = self.storage.load_checkpoint(checkpoint.value_begin_index, checkpoint.value_num)
                    if existing:
                        continue

                if self.storage.store_checkpoint(checkpoint):
                    imported_count += 1

                    # 更新缓存
                    cache_key = (checkpoint.value_begin_index, checkpoint.value_num)
                    with self._lock:
                        self._checkpoint_cache[cache_key] = checkpoint

            return imported_count
        except Exception as e:
            print(f"导入检查点失败: {e}")
            return 0