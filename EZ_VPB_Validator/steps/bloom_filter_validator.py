"""
Bloom Filter Validation Step

This module implements the third step of VPB validation: bloom filter consistency verification.

布隆过滤器验证核心思想是：根据main_chain_info信息（这是一定正确的信息），
来判断外部提供的输入vpb_slice中的block_index_slice中的相应数据是否和布隆过滤器中的记录一一对应。

场景1：
假设目标value的真实的所有权转移历史如下（被记录进main_chain_info）：
创世块（区块0）：alice是目标value的首位所有者（从GOD处获得）
区块8：alice作为sender提交交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob作为sender提交交易（非目标value）
区块25：bob作为sender提交交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie作为sender提交交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58（当前待验证交易）：eve从dave处接收目标value（dave->eve交易）

验证者提供的vpb_slice.block_index_slice.index_lst是：[0,8,15,16,25,27,55,56,58]。
提供的vpb_slice.block_index_slice.owner是：[(0, alice), (15, bob), (27, charlie), (56, dave), (58, eve)]。
那么我们可提取出各个owner的epochs为：
alice: （0，14），表示alice在区块0到区块14期间是目标value的owner，且alice在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[8]
bob:   （15，26），表示bob在区块15到区块26期间是目标value的owner，且bob在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[16, 25]
charlie:（27，54），表示charlie在区块27到区块54期间是目标value的owner，且charlie在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[55]
dave:  （56，57），表示dave在区块56到区块57期间是目标value的owner，且dave在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[]（为空，因为dave没有作为sender的交易）
eve:   （58，当前区块高度），表示eve在区块58获得目标value。

现在需要验证的就是根据这些epochs，去main_chain_info中的布隆过滤器中检查，
看这些owner在其对应的epoch期间，是否在布隆过滤器中被正确记录。例如：
对于bob的epoch：（15，26）的验证：1）需要检查main_chain_info中区块15到区块26的布隆过滤器，输入bob的地址，检查是否为[16,25]?
2）逻辑上，bob一定在区块27的布隆过滤器中被记录，因为bob在区块27作为sender提交了目标value的交易。因此，验证时也需要检查区块27的布隆过滤器，输入bob的地址，检查是否为[27]?
依照上述逻辑对所有epoch都进行相应检查（最后一个eve的epoch无需验证），即可完成布隆过滤器验证。

由于main_chain_info中的布隆过滤器一定会记录所有在本块中提交交易的sender的地址，因此，
如果攻击者试图隐藏某些恶意区块（例如包含双花交易的区块，攻击者在这些区块中必是sender提交交易，且被记录在布隆过滤器中），
通过检查这些区块的布隆过滤器，可以检测到攻击者隐藏恶意区块的行为。
"""

from typing import Tuple, List
from ..core.validator_base import ValidatorBase
from ..core.types import VPBSlice


class BloomFilterValidator(ValidatorBase):
    """布隆过滤器验证器"""

    def verify_bloom_filter_consistency(self, vpb_slice: VPBSlice, main_chain_info) -> Tuple[bool, str]:
        """
        第三步：布隆过滤器验证（符合核心思想的实现）

        根据注释中的场景1验证逻辑，验证每个owner在其epoch期间作为sender的交易记录。
        检测攻击者是否隐藏了恶意区块（如双花交易的区块）。

        Args:
            vpb_slice: VPB切片对象
            main_chain_info: 主链信息

        Returns:
            Tuple[bool, str]: (是否一致, 错误信息)
        """
        if not vpb_slice.block_index_slice.index_lst:
            # 如果没有需要验证的区块，认为验证失败
            return False, "VPB slice has empty block index list"

        # 基本验证：确保提供的区块范围合理
        end_height = max(vpb_slice.block_index_slice.index_lst)

        # 提取owner的epochs信息
        from ..utils.epoch_extractor import EpochExtractor
        extractor = EpochExtractor(self.logger)
        owner_epochs = extractor.extract_owner_epochs(vpb_slice.block_index_slice)

        if not owner_epochs:
            return False, "Failed to extract owner epochs from VPB slice"

        self.logger.debug(f"Extracted {len(owner_epochs)} owner epochs for bloom filter validation")

        # 验证第一个epoch之前的owner
        first_start_block, first_owner = owner_epochs[0]
        if first_start_block == 0:
            # 创世块特殊情况：GOD向第一个owner转移value，不需要检查前一个owner的sender记录
            self.logger.debug(f"Genesis block detected: {first_owner} receives value from GOD at block {first_start_block}")
        else:
            # 非创世块：验证第一个epoch的前一个owner确实被记录在index_lst第一个块的布隆过滤器中
            #TODO 这里需要从其他信息推断前一个owner，暂时跳过这个验证，因为需要更多的上下文信息
            self.logger.debug(f"First epoch starts at block {first_start_block}, owner: {first_owner}")

        # 核心验证逻辑：按照注释中的场景1要求进行验证
        # 对每个owner（除最后一个）验证其epoch期间作为sender的交易记录
        for i, (start_block, owner_address) in enumerate(owner_epochs[:-1]):  # 排除最后一个owner（eve）
            # 计算当前owner的epoch结束区块
            if i + 1 < len(owner_epochs):
                next_owner_start = owner_epochs[i + 1][0]
                epoch_end = next_owner_start - 1
            else:
                epoch_end = end_height

            epoch_range = (start_block, epoch_end)
            self.logger.debug(f"Validating owner {owner_address} epoch: {epoch_range}")

            # 验证1：检查epoch期间该owner作为sender的区块
            # 根据注释中场景1的逻辑，需要检查main_chain_info中区块start_block到epoch_end的布隆过滤器
            epoch_sender_blocks = []
            for block_height in range(start_block, epoch_end + 1):
                if block_height in main_chain_info.bloom_filters:
                    bloom_filter = main_chain_info.bloom_filters[block_height]
                    if self._check_bloom_filter(bloom_filter, owner_address):
                        epoch_sender_blocks.append(block_height)

            # 验证2：检查该owner在下一个区块作为sender发送目标value的交易
            # 根据注释，bob一定在区块27的布隆过滤器中被记录，因为bob在区块27作为sender提交了目标value的交易
            next_block_for_value_transfer = epoch_end + 1
            value_transfer_recorded = False
            if next_block_for_value_transfer in main_chain_info.bloom_filters:
                next_bloom_filter = main_chain_info.bloom_filters[next_block_for_value_transfer]
                if self._check_bloom_filter(next_bloom_filter, owner_address):
                    value_transfer_recorded = True

            # 安全验证：如果epoch期间没有sender记录，且下一个区块也没有value transfer记录，可能存在问题
            if not epoch_sender_blocks and not value_transfer_recorded:
                self.logger.warning(
                    f"Owner {owner_address} has no transaction records in bloom filter "
                    f"during epoch {epoch_range} and no value transfer record in block {next_block_for_value_transfer}"
                )
                # 这可能是正常的（如dave的例子），也可能是隐藏区块的迹象
                # 需要进一步检查是否被隐藏了恶意区块

            # 验证3：检查是否遗漏了任何应该包含的区块
            # 根据注释中的思想，攻击者可能隐藏某些区块中的恶意交易
            expected_blocks_in_vpb = set()

            # 添加epoch期间有sender记录的区块
            expected_blocks_in_vpb.update(epoch_sender_blocks)

            # 添加value transfer区块
            if value_transfer_recorded:
                expected_blocks_in_vpb.add(next_block_for_value_transfer)

            # 添加ownership change区块（start_block本身应该被包含）
            if start_block in vpb_slice.block_index_slice.index_lst:
                expected_blocks_in_vpb.add(start_block)

            # 检查VPB是否遗漏了这些重要区块
            provided_blocks = set(vpb_slice.block_index_slice.index_lst)
            missing_important_blocks = expected_blocks_in_vpb - provided_blocks

            if missing_important_blocks:
                self.logger.error(
                    f"SECURITY THREAT: VPB is missing important blocks that contain "
                    f"owner {owner_address} transactions: {sorted(missing_important_blocks)}"
                )
                return False, (
                    f"SECURITY THREAT DETECTED: VPB missing blocks {sorted(missing_important_blocks)} "
                    f"that contain transactions from owner {owner_address}. "
                    f"Attacker may be hiding malicious transactions."
                )

        self.logger.debug(f"Bloom filter consistency verification passed successfully")
        self.logger.debug(f"Validated epochs for {len(owner_epochs)-1} owners (excluding current owner)")

        return True, ""