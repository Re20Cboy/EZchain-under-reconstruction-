"""
Epoch Extraction Utilities

This module provides utilities for extracting epoch information from BlockIndexList.
"""

from typing import List, Tuple, Optional
from ..core.validator_base import ValidatorBase


class EpochExtractor(ValidatorBase):
    """Epoch信息提取器"""

    def extract_owner_epochs(self, block_index_list) -> List[Tuple[int, str]]:
        """
        从BlockIndexList中提取epoch信息（修复版本）

        新的epoch概念：
        - 每个区块代表一个独立的epoch
        - 每个epoch包含：区块高度、该区块的owner、前驱owner
        - 按照转移链的时间顺序组织epoch
        - 对于没有owner记录的区块，使用上一个已知owner

        Args:
            block_index_list: 区块索引列表

        Returns:
            List[Tuple[int, str]]: 按区块高度排序的epoch列表 [(block_height, owner_address), ...]
        """
        epochs = []

        if not block_index_list.owner or not block_index_list.index_lst:
            return epochs

        # 调试信息
        self.logger.debug(f"Extract owner epochs: owner type: {type(block_index_list.owner)}")
        self.logger.debug(f"Extract owner epochs: owner value: {block_index_list.owner}")

        # 确保owner数据格式正确
        if not hasattr(block_index_list.owner, '__iter__') or isinstance(block_index_list.owner, str):
            self.logger.error("Invalid owner format in block_index_list for epoch extraction")
            raise ValueError("Invalid owner format in block_index_list for epoch extraction")

        # 创建区块高度到owner的映射
        block_to_owner = {height: owner for height, owner in block_index_list.owner}

        # 按区块高度排序构建epoch列表
        sorted_blocks = sorted(block_index_list.index_lst)

        # 修复：为每个区块确定owner，包括没有显式记录的区块
        current_owner = None
        for block_height in sorted_blocks:
            if block_height in block_to_owner:
                owner = block_to_owner[block_height]
                current_owner = owner
                self.logger.debug(f"Found explicit owner for block {block_height}: {owner}")
            else:
                # 如果该区块没有owner记录，使用上一个owner
                if current_owner is None:
                    # 第一个区块但没有owner记录，这是数据结构问题
                    # 根据前面步骤的保证，这种情况不应该发生
                    self.logger.error(f"No owner available for block {block_height} and no previous owner")
                    continue
                owner = current_owner
                self.logger.debug(f"Using previous owner for block {block_height}: {owner}")

            epochs.append((block_height, owner))

        self.logger.debug(f"Extracted epochs: {epochs}")
        return epochs

    def get_previous_owner_for_block(self, epochs: List[Tuple[int, str]], target_block: int) -> Optional[str]:
        """
        获取指定区块的前驱owner地址

        Args:
            epochs: 按时间顺序的epoch列表 [(block_height, owner_address), ...]
            target_block: 目标区块高度

        Returns:
            Optional[str]: 前驱owner地址，如果没有前驱（创世块）返回None
        """
        # 找到目标区块在epoch列表中的位置
        target_index = -1
        for i, (block_height, owner) in enumerate(epochs):
            if block_height == target_block:
                target_index = i
                break

        if target_index == -1:
            self.logger.warning(f"Block {target_block} not found in epochs")
            return None

        # 如果是第一个epoch（创世块），没有前驱
        if target_index == 0:
            return None

        # 返回前一个epoch的owner
        previous_block, previous_owner = epochs[target_index - 1]
        self.logger.debug(f"Previous owner for block {target_block}: {previous_owner} (from block {previous_block})")
        return previous_owner

    def find_next_epoch_owner(self, epochs: List[Tuple[int, str]], current_block: int) -> Optional[str]:
        """
        找到当前区块之后的下一个epoch的owner地址（重构版本）

        Args:
            epochs: 按时间顺序的epoch列表 [(block_height, owner_address), ...]
            current_block: 当前区块高度

        Returns:
            Optional[str]: 下一个epoch的owner地址，如果不存在则返回None
        """
        # 找到当前区块在epoch列表中的位置
        current_index = -1
        for i, (block_height, owner) in enumerate(epochs):
            if block_height == current_block:
                current_index = i
                break

        if current_index == -1:
            return None

        # 如果是最后一个epoch，没有下一个
        if current_index >= len(epochs) - 1:
            return None

        # 返回下一个epoch的owner
        next_block, next_owner = epochs[current_index + 1]
        return next_owner