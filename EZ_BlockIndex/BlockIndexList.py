from __future__ import annotations

import os
import sys
from typing import Iterable, List, Optional, Sequence, Tuple, Union

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')


OwnerHistory = List[Tuple[int, str]]
OwnerInput = Optional[Union[str, Sequence[Tuple[int, str]], Tuple[int, str]]]


class BlockIndexList:
    """
    BlockIndexList用于管理Value的所有权历史和相关区块索引

    index_lst和owner的逻辑关系如下: 
    1)index_lst是一个整数列表, 里面的元素均为整数(本质上是部分区块的区块号)。
    2)owner表示在某个区块号的区块中, 此value属于哪个节点(owner), 因此owner是(区块号, owner用户地址)的一个二元列表。
    3)举个例子: index_lst= [0,2,7,14,15,27,56]（这是一个严格递增序列，不存在重复区块号）
    owner=[(0, 0X418ab...), (15, 0X8360c...), (56, 0X14860...)]。（标记了目标value的所有权变更历史，其第一个数字也是递增无重复的序列，且必然是index_lst的子集）
    其表示节点(0X418ab..)在Block#0时获得(拥有)此value, 即, 节点(0X418ab..)在Block#0时是此value的owner;
    节点(0X418ab..)在Block#15时交易了此value给节点(0X8360c...), 即, 节点(0X8360c...)在Block#15时成为了此value的owner;
    节点(0X8360c...)在Block#56时交易了此value给节点(0X14860...), 即, 节点(0X14860...)在Block#56时成为了此value的owner;
    4)正如3)所述, owner列表并非与index_lst一一对应, 但owner中的区块号一般是index_lst的子集。
    """

    def __init__(self, index_lst: Iterable[int], owner: OwnerInput = None):
        """
        初始化BlockIndexList

        Args:
            index_lst: 包含所有相关区块号的整数列表
            owner: 包含(区块号, owner地址)的二元列表, 记录所有权变更历史
        """
        self.index_lst: List[int] = list(index_lst)
        self.owner: Optional[Union[str, OwnerHistory]] = self._normalise_owner_input(owner)
        self._owner_history: OwnerHistory = self._extract_owner_history()
        self._validate_data_integrity()

    def _validate_data_integrity(self):
        """验证数据的完整性和一致性"""
        # 确保index_lst中的元素都是整数
        if not all(isinstance(idx, int) for idx in self.index_lst):
            raise ValueError("index_lst中的所有元素必须是整数")

        # 确保owner数据有效
        if self.owner is None:
            return

        if isinstance(self.owner, str):
            return

        # 归一化元组形式
        normalised_history: OwnerHistory = []
        for item in self.owner:
            if (not isinstance(item, tuple) or len(item) != 2 or
                    not isinstance(item[0], int) or not isinstance(item[1], str)):
                raise ValueError("owner中的所有元素必须是(区块号, 地址)的元组")
            normalised_history.append((item[0], item[1]))

        self.owner = normalised_history
        self._owner_history = normalised_history.copy()

    @staticmethod
    def _normalise_owner_input(owner: OwnerInput) -> Optional[Union[str, OwnerHistory]]:
        """根据输入类型整理owner字段."""
        if owner is None or isinstance(owner, str):
            return owner

        # 支持传入单个二元组
        if isinstance(owner, tuple) and len(owner) == 2:
            block_index, address = owner
            if isinstance(block_index, int) and isinstance(address, str):
                return [(block_index, address)]

        # 其余情况视作可迭代的历史记录
        return [tuple(item) for item in owner]  # type: ignore[arg-type]

    def _extract_owner_history(self) -> OwnerHistory:
        """生成规范化的所有权历史列表."""
        if isinstance(self.owner, list):
            return list(self.owner)
        return []

    def get_owner_at_block(self, block_index: int) -> Optional[str]:
        """
        获取指定区块号时的owner地址

        Args:
            block_index: 区块号

        Returns:
            在该区块时的owner地址, 如果不存在则返回None
        """
        if isinstance(self.owner, str):
            return self.owner if block_index in self.index_lst else None

        if not self._owner_history:
            return None

        sorted_owner = sorted(self._owner_history, key=lambda x: x[0])
        current_owner: Optional[str] = None
        for idx, owner_addr in sorted_owner:
            if idx <= block_index:
                current_owner = owner_addr
            else:
                break
        return current_owner

    def get_ownership_history(self) -> List[Tuple[int, str]]:
        """
        获取完整的所有权变更历史

        Returns:
            按区块号排序的所有权变更历史
        """
        if self._owner_history:
            return sorted(self._owner_history, key=lambda x: x[0])

        if isinstance(self.owner, str) and self.index_lst:
            first_block = min(self.index_lst)
            return [(first_block, self.owner)]

        return []

    def get_current_owner(self) -> Optional[str]:
        """
        获取当前的owner(最新区块中的owner)

        Returns:
            当前owner地址, 如果没有owner记录则返回None
        """
        if isinstance(self.owner, str):
            return self.owner

        if not self._owner_history:
            return None

        # 返回区块号最大的owner
        return max(self._owner_history, key=lambda x: x[0])[1]

    def add_ownership_change(self, block_index: int, new_owner: str) -> bool:
        """
        添加所有权变更记录

        Args:
            block_index: 区块号
            new_owner: 新的owner地址

        Returns:
            添加成功返回True
        """
        # 确保区块号在index_lst中
        if block_index not in self.index_lst:
            self.index_lst.append(block_index)

        if isinstance(self.owner, str):
            # 将现有字符串owner转换为历史记录, 保留原owner作为最早记录
            initial_history: OwnerHistory = []
            if self.index_lst:
                initial_history.append((min(self.index_lst), self.owner))
            self.owner = initial_history
            self._owner_history = initial_history

        if self.owner is None:
            self.owner = []
            self._owner_history = []

        if isinstance(self.owner, list):
            # 检查是否已存在该区块号的记录
            for i, (idx, _) in enumerate(self.owner):
                if idx == block_index:
                    self.owner[i] = (block_index, new_owner)
                    self._owner_history[i] = (block_index, new_owner)
                    return True

            record = (block_index, new_owner)
            self.owner.append(record)
            self._owner_history.append(record)
            return True

        raise ValueError("owner信息不可更新")

    @staticmethod
    def _get_block(blockchain_getter, block_index: int):
        try:
            return blockchain_getter.get_block(block_index)
        except AttributeError as exc:
            raise ValueError("blockchain_getter must implement get_block(index) method") from exc

    @staticmethod
    def _block_contains_owner(block, owner_addr: str) -> bool:
        try:
            return bool(block.is_in_bloom(owner_addr))
        except AttributeError as exc:
            raise ValueError("block对象必须实现 is_in_bloom(address) 方法") from exc

    @staticmethod
    def _get_chain_length(blockchain_getter) -> Optional[int]:
        length_getter = getattr(blockchain_getter, "get_chain_length", None)
        if callable(length_getter):
            try:
                length = length_getter()
                return int(length)
            except Exception:
                return None
        return None

    def verify_index_list(self, blockchain_getter) -> bool:
        """
        验证BlockIndexList的完整性

        验证逻辑: 
        1. 验证每个所有权变更记录都在对应的区块中
        2. 验证owner中的区块号都在index_lst中

        Args:
            blockchain_getter: 用于获取区块信息的对象

        Returns:
            验证通过返回True
        """
        if not self.index_lst:
            return False

        if self.owner is None or (isinstance(self.owner, str) and not self.owner):
            return False

        if not blockchain_getter:
            raise ValueError("blockchain_getter is required for verification")

        unique_indices = list(dict.fromkeys(self.index_lst))
        index_set = set(unique_indices)

        # 单一owner字符串的验证逻辑
        if isinstance(self.owner, str):
            owner_addr = self.owner
            for block_index in unique_indices:
                block = self._get_block(blockchain_getter, block_index)
                if block is None:
                    return False
                if not self._block_contains_owner(block, owner_addr):
                    return False

            chain_length = self._get_chain_length(blockchain_getter)
            if chain_length is not None:
                for idx in range(chain_length):
                    block = self._get_block(blockchain_getter, idx)
                    if block is None:
                        continue
                    if self._block_contains_owner(block, owner_addr) and idx not in index_set:
                        return False

            return True

        # 历史记录场景的验证逻辑
        for block_index, owner_addr in self._owner_history:
            block = self._get_block(blockchain_getter, block_index)
            if block is None:
                return False
            if block_index not in index_set:
                return False
            if not self._block_contains_owner(block, owner_addr):
                return False

        return True

    def __str__(self) -> str:
        """字符串表示"""
        return f"BlockIndexList(index_lst={self.index_lst}, owner={self.owner})"

    def __repr__(self) -> str:
        """详细字符串表示"""
        return self.__str__()

    def __eq__(self, other) -> bool:
        """比较两个BlockIndexList是否相等"""
        if not isinstance(other, BlockIndexList):
            return False

        owners_equal: bool
        if isinstance(self.owner, list) and isinstance(other.owner, list):
            owners_equal = sorted(self.owner) == sorted(other.owner)
        else:
            owners_equal = self.owner == other.owner

        return self.index_lst == other.index_lst and owners_equal

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            包含所有信息的字典
        """
        return {
            'index_lst': self.index_lst,
            'owner': self.owner
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BlockIndexList':
        """
        从字典创建BlockIndexList

        Args:
            data: 包含index_lst和owner的字典

        Returns:
            BlockIndexList实例
        """
        return cls(
            index_lst=data.get('index_lst', []),
            owner=data.get('owner')
        )
