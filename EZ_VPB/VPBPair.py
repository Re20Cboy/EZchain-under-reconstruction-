import sys
import os
from typing import Dict, Optional, Any, NamedTuple

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value import Value
from EZ_Proof import Proofs
from EZ_BlockIndex import BlockIndexList

class VPBInfo(NamedTuple):
    """VPB信息数据结构，用于存储Value-Proofs-block_index_lst三元组"""
    value: Value
    proofs: Proofs
    block_index_lst: BlockIndexList

class VPBManager:
    """
    VPB管理器，负责管理Value-Proofs-block_index_lst的对应关系
    每个Value都有唯一对应的Proofs和block_index_lst
    """

    def __init__(self):
        self._value_to_vpb: Dict[str, VPBInfo] = {}  # value_id -> VPBInfo
        self._lock = None  # 将由Account提供线程锁

    def set_lock(self, lock):
        """设置线程锁"""
        self._lock = lock

    def _with_lock(self, func):
        """带锁执行的装饰器"""
        def wrapper(*args, **kwargs):
            if self._lock:
                with self._lock:
                    return func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        return wrapper

    def _get_value_id(self, value: Value) -> str:
        """生成Value的唯一标识符"""
        return f"{value.begin_index}_{value.end_index}_{value.value_num}_{value.state.value}"

    @property
    def vpb_pairs(self) -> Dict[str, VPBInfo]:
        """获取所有VPB对（只读）"""
        return self._value_to_vpb.copy()

    def add_vpb(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList) -> bool:
        """
        添加VPB三元组

        Args:
            value: Value对象
            proofs: Proofs对象
            block_index_lst: BlockIndexList对象

        Returns:
            bool: 添加成功返回True
        """
        def _add():
            value_id = self._get_value_id(value)
            vpb_info = VPBInfo(value, proofs, block_index_lst)
            self._value_to_vpb[value_id] = vpb_info
            return True

        return self._with_lock(_add)()

    def update_vpb(self, value: Value, new_proofs: Optional[Proofs] = None,
                   new_block_index_lst: Optional[BlockIndexList] = None) -> bool:
        """
        更新指定Value的VPB信息

        Args:
            value: 要更新的Value对象
            new_proofs: 新的Proofs对象（可选）
            new_block_index_lst: 新的BlockIndexList对象（可选）

        Returns:
            bool: 更新成功返回True
        """
        def _update():
            value_id = self._get_value_id(value)
            if value_id not in self._value_to_vpb:
                return False

            vpb_info = self._value_to_vpb[value_id]

            # 创建新的VPBInfo替换旧的
            updated_proofs = new_proofs if new_proofs is not None else vpb_info.proofs
            updated_block_index_lst = new_block_index_lst if new_block_index_lst is not None else vpb_info.block_index_lst

            self._value_to_vpb[value_id] = VPBInfo(
                vpb_info.value,
                updated_proofs,
                updated_block_index_lst
            )

            return True

        return self._with_lock(_update)()

    def remove_vpb(self, value: Value) -> bool:
        """
        移除指定Value的VPB信息

        Args:
            value: 要移除的Value对象

        Returns:
            bool: 移除成功返回True
        """
        def _remove():
            value_id = self._get_value_id(value)
            if value_id in self._value_to_vpb:
                del self._value_to_vpb[value_id]
                return True
            return False

        return self._with_lock(_remove)()

    def get_vpb(self, value: Value) -> Optional[VPBInfo]:
        """
        获取指定Value的VPB信息

        Args:
            value: Value对象

        Returns:
            VPBInfo: VPB信息对象，不存在返回None
        """
        value_id = self._get_value_id(value)
        return self._value_to_vpb.get(value_id)

    def get_all_vpbs(self) -> Dict[str, VPBInfo]:
        """
        获取所有VPB信息

        Returns:
            Dict[str, VPBInfo]: value_id到VPB的映射
        """
        return self.vpb_pairs

    def clear_all_vpbs(self) -> bool:
        """
        清空所有VPB信息

        Returns:
            bool: 清空成功返回True
        """
        def _clear():
            self._value_to_vpb.clear()
            return True

        return self._with_lock(_clear)()

    def validate_vpb_consistency(self) -> bool:
        """
        验证VPB数据一致性

        Returns:
            bool: 验证通过返回True
        """
        try:
            for value_id, vpb_info in self._value_to_vpb.items():
                if not self._is_valid_vpb_info(vpb_info):
                    return False
            return True
        except Exception:
            return False

    def _is_valid_vpb_info(self, vpb_info: VPBInfo) -> bool:
        """
        检查VPBInfo是否有效

        Args:
            vpb_info: VPB信息对象

        Returns:
            bool: VPB信息有效返回True
        """
        try:
            return (vpb_info.value is not None and
                   vpb_info.proofs is not None and
                   vpb_info.block_index_lst is not None)
        except Exception:
            return False

