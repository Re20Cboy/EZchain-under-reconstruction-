"""
VPB Slice Generation Step

This module implements the second step of VPB validation: checkpoint matching and slice generation.
"""

from typing import Tuple, Optional
from ..core.validator_base import ValidatorBase
from ..core.types import VPBSlice, MainChainInfo
from EZ_CheckPoint.CheckPoint import CheckPointRecord


class VPBSliceGenerator(ValidatorBase):
    """VPB切片生成器"""

    def __init__(self, checkpoint, logger=None):
        """
        初始化VPB切片生成器

        Args:
            checkpoint: 检查点管理器实例
            logger: 日志记录器实例
        """
        super().__init__(logger)
        self.checkpoint = checkpoint

    def generate_vpb_slice(self, value, proof_units, block_index_list, account_address: str) -> Tuple[VPBSlice, Optional[CheckPointRecord]]:
        """
        第二步：检查点匹配和历史切片生成

        Args:
            value: Value对象
            proof_units: ProofUnit列表
            block_index_list: BlockIndexList对象
            account_address: 进行验证的账户地址（value的接收方）

        Returns:
            Tuple[VPBSlice, Optional[CheckPointRecord]]: (VPB切片, 使用的检查点)
        """
        checkpoint_used = None
        start_height = 0  # 默认从创世块开始验证

        # 检查是否有可用的检查点
        if self.checkpoint:
            # 尝试触发检查点验证
            checkpoint_record = self.checkpoint.trigger_checkpoint_verification(value, account_address)
            if checkpoint_record:
                checkpoint_used = checkpoint_record
                start_height = checkpoint_record.block_height + 1  # 从检查点的下一个区块开始验证
                # 精简输出: self.logger.info(f"Using checkpoint at height {checkpoint_record.block_height}, starting verification from height {start_height} for value {value.begin_index}")
                value_short = value.begin_index[:10] if len(value.begin_index) > 10 else value.begin_index
                self.logger.info(f"⚡ Checkpoint triggered: height={checkpoint_record.block_height}, start_from={start_height}, value={value_short}...")

        # 验证检查点高度的合法性
        if checkpoint_used:
            max_block_height = max(block_index_list.index_lst) if block_index_list.index_lst else 0
            if checkpoint_used.block_height >= max_block_height:
                # 检查点高度 >= 最后一个区块高度，这是非法的VPB输入
                raise ValueError(
                    f"Invalid checkpoint: checkpoint height ({checkpoint_used.block_height}) "
                    f"must be less than last block height ({max_block_height}). "
                    f"This indicates corrupted or invalid VPB data."
                )

        # 根据start_height生成历史切片
        proofs_slice = []
        index_slice = []
        owner_slice = []

        # proof_units已经是传入的列表，无需转换

        if proof_units and block_index_list.index_lst:
            # 特殊处理创世块（height = 0）
            genesis_index = -1
            if 0 in block_index_list.index_lst:
                genesis_index = block_index_list.index_lst.index(0)

            # 找到start_height对应的起始索引
            start_index = 0
            for i, block_height in enumerate(block_index_list.index_lst):
                if block_height >= start_height:
                    start_index = i
                    break

            # 调试信息
            # 精简输出: self.logger.debug(f"Slice generation: start_height={start_height}, start_index={start_index}, total_indices={len(block_index_list.index_lst)}")
            # 精简输出: self.logger.debug(f"Original index_lst: {block_index_list.index_lst}")
            # 精简输出: self.logger.debug(f"Will include indices from: {block_index_list.index_lst[start_index:]}")
            self.logger.debug(f"🔪 Slice: start_idx={start_index}/{len(block_index_list.index_lst)}, heights={len(block_index_list.index_lst[start_index:])} blocks")

            # 创世块特殊处理说明：
            # 根据slice_generator_demo.md，如果start_height > 0（有checkpoint），
            # 且创世块高度小于start_height，则创世块会被正常截断掉
            # 不需要额外包含创世块，因为checkpoint已经保证了之前的验证状态
            if genesis_index >= 0 and start_height > 0 and genesis_index < start_index:
                # 精简输出: self.logger.debug(f"Genesis block at index {genesis_index} will be truncated due to checkpoint at {start_height-1}")
                self.logger.debug(f"✂️ Genesis truncated: checkpoint @height{start_height-1} skips genesis")

            # 生成切片
            proofs_slice = proof_units[start_index:] if start_index < len(proof_units) else []
            index_slice = block_index_list.index_lst[start_index:] if start_index < len(block_index_list.index_lst) else []

            # 检查截断后是否出现空数组的情况
            if checkpoint_used and not proofs_slice and not index_slice:
                # 有checkpoint但截断后为空，说明VPB数据异常
                raise ValueError(
                    f"Invalid VPB data: checkpoint at height {checkpoint_used.block_height} "
                    f"results in empty slice. This indicates the checkpoint height is too high "
                    f"or the VPB data is incomplete/invalid."
                )

            # 生成对应的owner切片
            if block_index_list.owner:
                owner_slice = []
                # 调试信息：检查owner的类型和内容
                self.logger.debug(f"block_index_list.owner type: {type(block_index_list.owner)}")
                self.logger.debug(f"block_index_list.owner value: {block_index_list.owner}")

                # 确保owner是可迭代的
                if hasattr(block_index_list.owner, '__iter__') and not isinstance(block_index_list.owner, str):
                    owner_dict = {height: owner for height, owner in block_index_list.owner}
                else:
                    # 如果owner不是预期的格式，尝试从_owner_history获取
                    if hasattr(block_index_list, '_owner_history'):
                        owner_dict = {height: owner for height, owner in block_index_list._owner_history}
                    else:
                        self.logger.error("Invalid owner format in block_index_list")
                        raise ValueError("Invalid owner format in block_index_list")

                for height in index_slice:
                    if height in owner_dict:
                        owner_slice.append((height, owner_dict[height]))

        # 创建切片后的BlockIndexList
        from EZ_VPB.block_index.BlockIndexList import BlockIndexList
        sliced_block_index_list = BlockIndexList(index_slice, owner_slice)

        # 获取checkpoint的owner信息
        previous_owner = None
        if checkpoint_used:
            # checkpoint_record应该包含owner信息，这里需要从checkpoint中获取
            # 假设checkpoint有account_address字段表示当时验证的owner
            if hasattr(checkpoint_used, 'account_address'):
                previous_owner = checkpoint_used.account_address
            elif hasattr(checkpoint_used, 'owner'):
                previous_owner = checkpoint_used.owner
            else:
                self.logger.warning("Checkpoint record doesn't contain owner information")

        # 创建VPB切片对象
        vpb_slice = VPBSlice(
            value=value,
            proofs_slice=proofs_slice,
            block_index_slice=sliced_block_index_list,
            start_block_height=start_height,
            end_block_height=index_slice[-1] if index_slice else start_height,
            checkpoint_used=checkpoint_used,
            previous_owner=previous_owner
        )

        self.logger.debug(f"Generated VPB slice: start_height={start_height}, end_height={vpb_slice.end_block_height}, proof_units={len(proofs_slice)}, previous_owner={previous_owner}")
        return vpb_slice, checkpoint_used

    def slice_main_chain_info(self, main_chain_info: MainChainInfo, start_height: int, end_height: int) -> MainChainInfo:
        """
        根据VPB切片的范围对MainChainInfo进行切片

        Args:
            main_chain_info: 原始的MainChainInfo对象
            start_height: VPB切片的起始区块高度
            end_height: VPB切片的结束区块高度

        Returns:
            MainChainInfo: 切片后的MainChainInfo对象
        """
        sliced_merkle_roots = {}
        sliced_bloom_filters = {}

        # 只保留VPB切片范围内的区块数据
        for block_height in range(start_height, end_height + 1):
            if block_height in main_chain_info.merkle_roots:
                sliced_merkle_roots[block_height] = main_chain_info.merkle_roots[block_height]
            if block_height in main_chain_info.bloom_filters:
                sliced_bloom_filters[block_height] = main_chain_info.bloom_filters[block_height]

        # 创建切片后的MainChainInfo
        return MainChainInfo(
            merkle_roots=sliced_merkle_roots,
            bloom_filters=sliced_bloom_filters,
            current_block_height=main_chain_info.current_block_height,
            genesis_block_height=main_chain_info.genesis_block_height
        )