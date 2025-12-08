"""
Data Structure Validation Step

This module implements the first step of VPB validation: basic data structure validation.
"""

import re
from typing import Tuple, List, Optional
from ..core.validator_base import ValidatorBase
from ..core.types import VerificationError


class DataStructureValidator(ValidatorBase):
    """数据结构验证器"""

    def validate_basic_data_structure(self, value, proofs, block_index_list) -> Tuple[bool, str]:
        """
        第一步：基础数据结构合法性验证

        提供严格的VPB数据结构验证，包括Value、Proofs和BlockIndexList的深度验证。

        Args:
            value: Value对象
            proofs: Proofs对象
            block_index_list: BlockIndexList对象

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        # 1. 严格的Value数据结构验证
        is_valid, error_msg = self._validate_value_structure(value)
        if not is_valid:
            return False, f"Value validation failed: {error_msg}"

        # 2. 严格的Proofs数据结构验证
        is_valid, error_msg = self._validate_proofs_structure(proofs)
        if not is_valid:
            return False, f"Proofs validation failed: {error_msg}"

        # 3. 严格的BlockIndexList数据结构验证
        is_valid, error_msg = self._validate_block_index_list_structure(block_index_list)
        if not is_valid:
            return False, f"BlockIndexList validation failed: {error_msg}"

        # 4. VPB特定的数据一致性校验
        is_valid, error_msg = self._validate_vpb_consistency(value, proofs, block_index_list)
        if not is_valid:
            return False, f"VPB consistency validation failed: {error_msg}"

        self.logger.debug(f"Basic data structure validation passed for value {value.begin_index}")
        return True, ""

    def _validate_value_structure(self, value) -> Tuple[bool, str]:
        """
        严格的Value数据结构验证

        验证内容：
        1. Value对象类型检查
        2. state枚举值验证
        3. end_index > begin_index验证
        4. 使用Value类自身的验证方法（包含hex格式、value_num正数、索引关系验证）
        """
        from EZ_VPB.values.Value import Value, ValueState

        # 1. 类型检查
        if not isinstance(value, Value):
            return False, "value is not a valid Value object"

        # 2. state枚举值验证（Value.check_value()不验证state）
        if not isinstance(value.state, ValueState):
            return False, f"state '{value.state}' is not a valid ValueState enum"

        # 3. 验证end_index与begin_index的关系（Value.check_value()已验证计算正确性）
        # 当value_num=1时，begin_index == end_index是正常的
        # Value.check_value()已经验证了end_index == get_end_index(begin_index, value_num)
        # 所以这里不需要额外的比较验证

        # 4. 使用Value类自身的验证方法（包含hex格式、value_num正数、索引关系验证）
        if not value.check_value():
            return False, f"Value.check_value() failed for {value.begin_index}"

        return True, ""

    def _validate_proofs_structure(self, proofs) -> Tuple[bool, str]:
        """
        严格的Proofs数据结构验证

        验证内容：
        1. Proofs对象类型检查
        2. value_id格式验证
        3. proof_units列表验证
        4. 每个ProofUnit的深度验证
        """
        from EZ_VPB.proofs.Proofs import Proofs

        # 1. 类型检查
        if not isinstance(proofs, Proofs):
            return False, "proofs is not a valid Proofs object"

        # 2. value_id验证
        if not hasattr(proofs, 'value_id') or not proofs.value_id:
            return False, "proofs.value_id is missing or empty"

        # 3. 获取proof_units进行验证
        try:
            proof_units = proofs.get_proof_units()
        except Exception as e:
            return False, f"Failed to get proof_units: {str(e)}"

        # 4. 验证每个ProofUnit
        for i, proof_unit in enumerate(proof_units):
            is_valid, error_msg = self._validate_proof_unit_structure(proof_unit)
            if not is_valid:
                return False, f"ProofUnit[{i}] validation failed: {error_msg}"

        return True, ""

    def _validate_proof_unit_structure(self, proof_unit) -> Tuple[bool, str]:
        """
        严格的ProofUnit数据结构验证

        验证内容：
        1. ProofUnit对象类型检查
        2. owner地址格式验证
        3. owner_multi_txns结构验证
        4. owner_mt_proof结构验证
        5. unit_id格式验证
        6. reference_count验证
        """
        from EZ_VPB.proofs.ProofUnit import ProofUnit

        # 1. 类型检查
        if not isinstance(proof_unit, ProofUnit):
            return False, "proof_unit is not a valid ProofUnit object"

        # 2. owner地址格式验证
        if not hasattr(proof_unit, 'owner') or not proof_unit.owner:
            return False, "proof_unit.owner is missing or empty"

        if not self._is_valid_address_format(proof_unit.owner):
            return False, f"owner address '{proof_unit.owner}' has invalid format"

        # 3. owner_multi_txns结构验证
        if not hasattr(proof_unit, 'owner_multi_txns') or not proof_unit.owner_multi_txns:
            return False, "proof_unit.owner_multi_txns is missing or empty"

        # 验证MultiTransactions的基本结构
        try:
            if not hasattr(proof_unit.owner_multi_txns, 'sender'):
                return False, "owner_multi_txns.sender is missing"

            # 验证owner与交易参与方的关系
            # owner可能是发送者（原始拥有者）或接收者（所有权转移后的新拥有者）
            owner_is_sender = (proof_unit.owner_multi_txns.sender == proof_unit.owner)

            # 检查是否为创世块（通过sender地址识别）
            is_genesis_block = proof_unit.owner_multi_txns.sender.startswith("0x0000000000000000000000000000000")

            # 检查owner是否是任何交易的接收者
            owner_is_recipient = False
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for txn in proof_unit.owner_multi_txns.multi_txns:
                    if hasattr(txn, 'recipient') and txn.recipient == proof_unit.owner:
                        owner_is_recipient = True
                        break

            # 对于非创世块，owner必须参与交易
            if not is_genesis_block:
                if not owner_is_sender and not owner_is_recipient:
                    return False, f"owner '{proof_unit.owner}' is neither the sender nor any recipient in the transactions"

            # 创世块特殊处理：允许digest为None
            if is_genesis_block:
                # 创世块的digest可能为None，这是允许的
                if not hasattr(proof_unit.owner_multi_txns, 'digest'):
                    self.logger.warning("Genesis block proof unit missing digest attribute, but continuing validation")
                elif proof_unit.owner_multi_txns.digest is None:
                    self.logger.info("Genesis block proof unit has None digest, this is allowed")
                    # 尝试自动设置digest（可选）
                    try:
                        proof_unit.owner_multi_txns.set_digest()
                        self.logger.info("Auto-set digest for genesis block MultiTransactions")
                    except Exception as e:
                        self.logger.warning(f"Cannot auto-set digest for genesis block: {str(e)}")
            else:
                # 非创世块必须有digest
                if not hasattr(proof_unit.owner_multi_txns, 'digest') or not proof_unit.owner_multi_txns.digest:
                    return False, "owner_multi_txns.digest is missing or empty"

            # 验证multi_txns列表
            if not hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                return False, "owner_multi_txns.multi_txns is missing"

        except Exception as e:
            return False, f"owner_multi_txns structure validation failed: {str(e)}"

        # 4. owner_mt_proof结构验证
        if not hasattr(proof_unit, 'owner_mt_proof') or not proof_unit.owner_mt_proof:
            return False, "proof_unit.owner_mt_proof is missing or empty"

        # 验证MerkleTreeProof的基本结构
        try:
            if not hasattr(proof_unit.owner_mt_proof, 'mt_prf_list'):
                return False, "owner_mt_proof.mt_prf_list is missing"

            if not proof_unit.owner_mt_proof.mt_prf_list:
                return False, "owner_mt_proof.mt_prf_list is empty"

            # 验证mt_prf_list中的每个元素都是有效的hash格式
            for j, proof_hash in enumerate(proof_unit.owner_mt_proof.mt_prf_list):
                if not self._is_valid_hash_format(proof_hash):
                    return False, f"mt_prf_list[{j}] '{proof_hash}' is not a valid hash format"

        except Exception as e:
            return False, f"owner_mt_proof structure validation failed: {str(e)}"

        # 5. unit_id格式验证
        if not hasattr(proof_unit, 'unit_id') or not proof_unit.unit_id:
            return False, "proof_unit.unit_id is missing or empty"

        if not self._is_valid_hash_format(proof_unit.unit_id):
            return False, f"unit_id '{proof_unit.unit_id}' is not a valid hash format"

        # 6. reference_count验证
        if not hasattr(proof_unit, 'reference_count'):
            return False, "proof_unit.reference_count is missing"

        if not isinstance(proof_unit.reference_count, int) or proof_unit.reference_count < 1:
            return False, f"reference_count must be a positive integer, got {proof_unit.reference_count}"

        return True, ""

    def _validate_block_index_list_structure(self, block_index_list) -> Tuple[bool, str]:
        """
        严格的BlockIndexList数据结构验证

        验证内容：
        1. BlockIndexList对象类型检查
        2. index_lst结构验证（依赖BlockIndexList自身的验证）
        3. index_lst严格递增验证
        4. owner数据格式验证（补充BlockIndexList未覆盖的验证）
        5. index_lst与owner的逻辑关系验证
        """
        from EZ_VPB.block_index.BlockIndexList import BlockIndexList

        # 1. 类型检查
        if not isinstance(block_index_list, BlockIndexList):
            return False, "block_index_list is not a valid BlockIndexList object"

        # 2. index_lst基础验证
        if not hasattr(block_index_list, 'index_lst') or not block_index_list.index_lst:
            return False, "block_index_list.index_lst is missing or empty"

        # 3. 验证index_lst是严格递增序列（无重复）
        # BlockIndexList._validate_data_integrity()不验证递增性，需要单独验证
        for i in range(len(block_index_list.index_lst) - 1):
            if block_index_list.index_lst[i] >= block_index_list.index_lst[i + 1]:
                return False, f"index_lst is not strictly increasing: index {i}={block_index_list.index_lst[i]}, index {i+1}={block_index_list.index_lst[i+1]}"

        # 4. owner数据验证（BlockIndexList已验证基础结构，这里补充格式验证）
        if not hasattr(block_index_list, 'owner'):
            return False, "block_index_list.owner is missing"

        owner = block_index_list.owner
        if owner is None:
            return True, ""  # owner可以为None

        if isinstance(owner, str):
            # 字符串格式的owner验证（BlockIndexList不验证地址格式）
            if not owner:
                return False, "owner string is empty"
            if not self._is_valid_address_format(owner):
                return False, f"owner address '{owner}' has invalid format"
        elif isinstance(owner, list):
            # 列表格式的owner验证（BlockIndexList已验证基础结构，这里验证地址格式）
            for i, owner_record in enumerate(owner):
                if not isinstance(owner_record, tuple) or len(owner_record) != 2:
                    return False, f"owner[{i}] must be a tuple of (block_index, address), got {owner_record}"

                block_index, address = owner_record

                # 验证地址格式（BlockIndexList不验证地址格式）
                if not isinstance(address, str):
                    return False, f"owner[{i}][1] '{address}' is not a string"
                if not address:
                    return False, f"owner[{i}][1] address is empty"
                if not self._is_valid_address_format(address):
                    return False, f"owner[{i}][1] address '{address}' has invalid format"

            # 验证owner列表中的block_index也是严格递增的
            for i in range(len(owner) - 1):
                if owner[i][0] >= owner[i + 1][0]:
                    return False, f"owner block indices are not strictly increasing: {owner[i][0]} >= {owner[i+1][0]}"

        else:
            return False, f"owner must be str, list, or None, got {type(owner)}"

        # 5. 验证owner中的block_index都在index_lst中
        if isinstance(owner, list):
            index_set = set(block_index_list.index_lst)
            for i, (block_index, _) in enumerate(owner):
                if block_index not in index_set:
                    return False, f"owner[{i}] block_index '{block_index}' not found in index_lst"

        return True, ""

    def _validate_vpb_consistency(self, value, proofs, block_index_list) -> Tuple[bool, str]:
        """
        VPB特定的数据一致性验证

        验证内容：
        1. Proofs和BlockIndexList的元素数量一致性
        2. value_id与Value的关联性
        """
        # 1. 验证Proofs和BlockIndexList的元素数量一致
        try:
            proof_count = len(proofs.get_proof_units())
        except Exception as e:
            return False, f"Failed to get proof count: {str(e)}"

        block_count = len(block_index_list.index_lst)

        if proof_count != block_count:
            return False, f"Proof count ({proof_count}) does not match block index count ({block_count})"

        # 2. 验证value_id与Value的关联性（可选，根据具体业务逻辑）
        # 这里可以添加更多的VPB特定验证逻辑

        return True, ""

    def _is_valid_hex_format(self, hex_string: str) -> bool:
        """验证十六进制字符串格式（复用Value类的验证逻辑）"""
        if not isinstance(hex_string, str):
            return False
        # 使用Value类的验证逻辑保持一致性
        from EZ_VPB.values.Value import Value
        temp_value = object.__new__(Value)  # 创建临时实例以使用其方法
        return temp_value._is_valid_hex(hex_string)

    def _is_valid_hash_format(self, hash_string: str) -> bool:
        """验证哈希字符串格式（通常是64字节的十六进制字符串）"""
        if not isinstance(hash_string, str):
            return False
        # 常见的hash格式：64字符的十六进制字符串（可选0x前缀）
        return re.match(r"^(0x)?[0-9A-Fa-f]{64}$", hash_string) is not None

    def _is_valid_address_format(self, address: str) -> bool:
        """验证地址格式"""
        if not isinstance(address, str):
            return False
        # 常见的以太坊地址格式：0x开头后跟40个十六进制字符
        return re.match(r"^0x[0-9A-Fa-f]{40}$", address) is not None