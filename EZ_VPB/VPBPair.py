from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from EZ_BlockIndex import BlockIndexList
from EZ_Proof import Proofs
from EZ_Value.Value import Value


class VPBpair:
    """
    Value-Proofs-BlockIndex 三元组数据结构。

    该类封装单个 Value 及其对应的证明和区块索引列表，
    并提供一个轻量级的完整性检查方法。
    """

    def __init__(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList):
        self.value = value
        self.proofs = proofs
        self.block_index_lst = block_index_lst

    @staticmethod
    def _component_length(component: Any) -> Optional[int]:
        """尝试获取组件长度，若不支持 __len__ 则返回 None。"""
        if component is None:
            return 0

        try:
            return len(component)  # type: ignore[arg-type]
        except TypeError:
            return None

    def is_valid_vpb(self) -> bool:
        """
        基础完整性验证：
        1. 三个组件必须全部存在。
        2. 若组件可获取长度，则要求长度一致。
        """
        if self.value is None or self.proofs is None or self.block_index_lst is None:
            return False

        lengths = []
        for component in (self.value, self.proofs, self.block_index_lst):
            length = self._component_length(component)
            if length is not None:
                lengths.append(length)

        if lengths and len(set(lengths)) > 1:
            return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """浅层字典表示，便于序列化或调试。"""
        return {
            "value": self.value,
            "proofs": self.proofs,
            "block_index_lst": self.block_index_lst,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VPBpair":
        """从字典构造 VPBpair 实例。"""
        return cls(
            value=data.get("value"),
            proofs=data.get("proofs"),
            block_index_lst=data.get("block_index_lst"),
        )


class VPBManager:
    """
    VPB 管理器：负责维护 Value 与其 VPBpair 的映射关系。
    """

    def __init__(self):
        self._value_to_vpb: Dict[str, VPBpair] = {}  # value_id -> VPBpair
        self._lock = None  # 由 Account 注入线程锁

    def set_lock(self, lock):
        """设置线程锁。"""
        self._lock = lock

    def _with_lock(self, func):
        """带锁执行的装饰器。"""

        def wrapper(*args, **kwargs):
            if self._lock:
                with self._lock:
                    return func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    def _get_value_id(self, value: Value) -> str:
        """生成 Value 的唯一标识符。"""
        return f"{value.begin_index}_{value.end_index}_{value.value_num}_{value.state.value}"

    @property
    def vpb_pairs(self) -> Dict[str, VPBpair]:
        """获取所有 VPBpair（只读副本）。"""
        return self._value_to_vpb.copy()

    def add_vpb(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList) -> bool:
        """
        添加 VPBpair。

        Args:
            value: Value 对象
            proofs: Proofs 对象
            block_index_lst: BlockIndexList 对象
        """

        def _add():
            value_id = self._get_value_id(value)
            self._value_to_vpb[value_id] = VPBpair(value, proofs, block_index_lst)
            return True

        return self._with_lock(_add)()

    def update_vpb(
        self,
        value: Value,
        new_proofs: Optional[Proofs] = None,
        new_block_index_lst: Optional[BlockIndexList] = None,
    ) -> bool:
        """
        更新指定 Value 的 VPBpair。
        """

        def _update():
            value_id = self._get_value_id(value)
            if value_id not in self._value_to_vpb:
                return False

            vpb_info = self._value_to_vpb[value_id]
            if new_proofs is not None:
                vpb_info.proofs = new_proofs
            if new_block_index_lst is not None:
                vpb_info.block_index_lst = new_block_index_lst
            return True

        return self._with_lock(_update)()

    def remove_vpb(self, value: Value) -> bool:
        """
        移除指定 Value 的 VPBpair。
        """

        def _remove():
            value_id = self._get_value_id(value)
            if value_id in self._value_to_vpb:
                del self._value_to_vpb[value_id]
                return True
            return False

        return self._with_lock(_remove)()

    def get_vpb(self, value: Value) -> Optional[VPBpair]:
        """获取指定 Value 的 VPBpair。"""
        value_id = self._get_value_id(value)
        return self._value_to_vpb.get(value_id)

    def get_all_vpbs(self) -> Dict[str, VPBpair]:
        """获取所有 VPBpair 的副本。"""
        return self.vpb_pairs

    def clear_all_vpbs(self) -> bool:
        """清空所有 VPBpair。"""

        def _clear():
            self._value_to_vpb.clear()
            return True

        return self._with_lock(_clear)()

    def validate_vpb_consistency(self) -> bool:
        """验证所有 VPBpair 的一致性。"""
        try:
            return all(self._is_valid_vpb_info(vpb_info) for vpb_info in self._value_to_vpb.values())
        except Exception:
            return False

    @staticmethod
    def _is_valid_vpb_info(vpb_info: VPBpair) -> bool:
        """检查 VPBpair 是否有效。"""
        try:
            return vpb_info.is_valid_vpb()
        except Exception:
            return False
