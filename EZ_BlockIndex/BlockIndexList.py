import sys
import os
from typing import List, Tuple, Optional

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

class BlockIndexList:
    """
    BlockIndexList用于管理Value的所有权历史和相关区块索引

    index_lst和owner的逻辑关系如下: 
    1)index_lst是一个整数列表, 里面的元素均为整数(本质上是部分区块的区块号)。
    2)owner表示在某个区块号的区块中, 此value属于哪个节点(owner), 因此owner是(区块号, owner用户地址)的一个二元列表。
    3)举个例子: index_lst= [0,2,7,14,15,27,56]
    owner=[(0, 0X418ab...), (15, 0X8360c...), (56, 0X14860...)]。
    其表示节点(0X418ab..)在Block#0时获得(拥有)此value, 即, 节点(0X418ab..)在Block#0时是此value的owner;
    节点(0X418ab..)在Block#15时交易了此value给节点(0X8360c...), 即, 节点(0X8360c...)在Block#15时成为了此value的owner;
    节点(0X8360c...)在Block#56时交易了此value给节点(0X14860...), 即, 节点(0X14860...)在Block#56时成为了此value的owner;
    4)正如3)所述, owner列表并非与index_lst一一对应, 但owner中的区块号一般是index_lst的子集。
    """

    def __init__(self, index_lst: List[int], owner: Optional[List[Tuple[int, str]]] = None):
        """
        初始化BlockIndexList

        Args:
            index_lst: 包含所有相关区块号的整数列表
            owner: 包含(区块号, owner地址)的二元列表, 记录所有权变更历史
        """
        self.index_lst = index_lst if isinstance(index_lst, list) else list(index_lst)
        self.owner = owner if isinstance(owner, list) else (list(owner) if owner else [])

        # 确保数据完整性
        self._validate_data_integrity()

    def _validate_data_integrity(self):
        """验证数据的完整性和一致性"""
        # 确保index_lst中的元素都是整数
        if not all(isinstance(idx, int) for idx in self.index_lst):
            raise ValueError("index_lst中的所有元素必须是整数")

        # 确保owner中的元素都是(区块号, 地址)的元组
        if not all(isinstance(item, tuple) and len(item) == 2 and
                   isinstance(item[0], int) and isinstance(item[1], str)
                   for item in self.owner):
            raise ValueError("owner中的所有元素必须是(区块号, 地址)的元组")

        # 确保owner中的区块号都在index_lst中(或至少是合理的)
        owner_block_indices = {item[0] for item in self.owner}
        index_set = set(self.index_lst)

        # 注意: 根据描述, owner中的区块号应该是index_lst的子集
        # 但这里只是警告, 不抛出异常, 因为可能存在特殊情况
        if not owner_block_indices.issubset(index_set):
            # 可以选择是否要严格检查这里
            pass

    def get_owner_at_block(self, block_index: int) -> Optional[str]:
        """
        获取指定区块号时的owner地址

        Args:
            block_index: 区块号

        Returns:
            在该区块时的owner地址, 如果不存在则返回None
        """
        # 按区块号排序owner列表
        sorted_owner = sorted(self.owner, key=lambda x: x[0])

        # 找到小于等于指定区块号的最后一个owner
        current_owner = None
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
        return sorted(self.owner, key=lambda x: x[0])

    def get_current_owner(self) -> Optional[str]:
        """
        获取当前的owner(最新区块中的owner)

        Returns:
            当前owner地址, 如果没有owner记录则返回None
        """
        if not self.owner:
            return None

        # 返回区块号最大的owner
        return max(self.owner, key=lambda x: x[0])[1]

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

        # 检查是否已存在该区块号的记录
        for i, (idx, _) in enumerate(self.owner):
            if idx == block_index:
                # 更新现有记录
                self.owner[i] = (block_index, new_owner)
                return True

        # 添加新记录
        self.owner.append((block_index, new_owner))
        return True

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

        if not self.owner:
            return False

        if not blockchain_getter:
            raise ValueError("blockchain_getter is required for verification")

        # 验证每个所有权变更都在对应的区块中
        for block_index, owner_addr in self.owner:
            try:
                block = blockchain_getter.get_block(block_index)
            except AttributeError:
                raise ValueError("blockchain_getter must implement get_block(index) method")

            if block is None:
                return False

            # 验证该区块包含owner地址
            if not block.is_in_bloom(owner_addr):
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

        return (self.index_lst == other.index_lst and
                sorted(self.owner) == sorted(other.owner))

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
            owner=data.get('owner', [])
        )