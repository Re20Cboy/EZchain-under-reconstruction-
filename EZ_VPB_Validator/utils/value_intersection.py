"""
Value Intersection Detection Utilities

This module provides utilities for detecting value intersections in transactions.
"""

from typing import Any, List
from ..core.validator_base import ValidatorBase
from ..core.types import ValueIntersectionError


class ValueIntersectionDetector(ValidatorBase):
    """Value交集检测器"""

    def find_value_intersect_transactions(self, proof_unit, value) -> List[Any]:
        """
        查找proof unit中与目标value有交集的所有交易

        Args:
            proof_unit: ProofUnit对象
            value: 目标Value对象

        Returns:
            List[Any]: 与目标value有交集的交易列表
        """
        intersect_transactions = []

        if hasattr(proof_unit, 'owner_multi_txns') and proof_unit.owner_multi_txns:
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for transaction in proof_unit.owner_multi_txns.multi_txns:
                    try:
                        if self.transaction_intersects_value(transaction, value):
                            intersect_transactions.append(transaction)
                    except ValueIntersectionError as e:
                        # 遇到无效value对象的交易时，记录错误并停止处理该proof unit
                        # 这是因为包含无效value的交易可能导致验证结果不可信
                        block_height = getattr(proof_unit, 'block_height', 'unknown')
                        error_msg = f"Invalid value objects in transaction at block {block_height}: {e}"
                        self.logger.error(error_msg)
                        # 抛出异常让上层处理，这比忽略错误更安全
                        raise ValueError(f"Transaction validation failed at block {block_height}: {e}") from e

        return intersect_transactions

    def find_valid_value_spend_transactions(self, proof_unit, value, expected_sender: str, expected_receiver: str = None) -> List[Any]:
        """
        查找proof unit中有效的value花销交易

        Args:
            proof_unit: ProofUnit对象
            value: 目标Value对象
            expected_sender: 期望的发送者地址
            expected_receiver: 期望的接收者地址（可能为None）

        Returns:
            List[Any]: 有效的value花销交易列表
        """
        valid_transactions = []

        if hasattr(proof_unit, 'owner_multi_txns') and proof_unit.owner_multi_txns:
            if hasattr(proof_unit.owner_multi_txns, 'multi_txns'):
                for transaction in proof_unit.owner_multi_txns.multi_txns:
                    if self.is_valid_value_spend_transaction(transaction, value, expected_sender, expected_receiver):
                        valid_transactions.append(transaction)

        return valid_transactions

    def transaction_intersects_value(self, transaction: Any, value) -> bool:
        """
        检查交易是否与目标value有交集

        严格验证：所有value对象必须是有效的Value类型，遇到任何无效数据都会抛出异常

        Args:
            transaction: 交易对象（应符合项目的Transaction架构）
            value: 目标Value对象

        Returns:
            bool: True-有交集，False-无交集

        Raises:
            ValueIntersectionError: 当交易中的value对象无效时
        """
        # 验证目标value本身必须是有效的
        if not self.is_valid_value_object(value):
            raise ValueIntersectionError(f"Target value is not a valid Value object: {type(value)}")

        # 根据项目的Transaction架构，Transaction只有一个value属性（List[Value]）
        if hasattr(transaction, 'value'):
            if not isinstance(transaction.value, (list, tuple)):
                raise ValueIntersectionError(f"transaction.value must be a list or tuple, got {type(transaction.value)}")

            for i, tx_value in enumerate(transaction.value):
                if not self.is_valid_value_object(tx_value):
                    raise ValueIntersectionError(f"Invalid value at index {i}: {type(tx_value)}")
                if self.values_intersect(tx_value, value):
                    return True

        # 如果没有value属性或没有发现交集，返回False（确实无交集）
        return False

    def is_valid_value_spend_transaction(self, transaction: Any, value, expected_sender: str, expected_receiver: str = None) -> bool:
        """
        检查是否是有效的value花销交易

        Args:
            transaction: 交易对象（应符合项目的Transaction架构）
            value: 目标Value对象
            expected_sender: 期望的发送者地址
            expected_receiver: 期望的接收者地址

        Returns:
            bool: 是否是有效的花销交易
        """
        # 检查发送者（根据Transaction架构，使用sender属性）
        if not hasattr(transaction, 'sender') or transaction.sender != expected_sender:
            return False

        # 根据项目的Transaction架构，Transaction只有一个value属性（List[Value]）
        if hasattr(transaction, 'value'):
            for tx_value in transaction.value:
                if (hasattr(tx_value, 'begin_index') and hasattr(tx_value, 'end_index') and
                    hasattr(tx_value, 'value_num') and
                    tx_value.begin_index == value.begin_index and
                    tx_value.end_index == value.end_index and
                    tx_value.value_num == value.value_num):
                    # 检查接收者（根据Transaction架构，使用recipient属性）
                    if expected_receiver:
                        if hasattr(transaction, 'recipient') and transaction.recipient == expected_receiver:
                            return True
                    else:
                        return True

        return False

    def values_intersect(self, value1: Any, value2) -> bool:
        """
        检查两个value是否有交集

        严格类型检查：两个参数都必须是Value类型或具有begin_index/end_index属性的对象

        Args:
            value1: 第一个value对象，必须是Value类型或具有begin_index/end_index属性
            value2: 第二个Value对象，必须是Value类型或具有begin_index/end_index属性

        Returns:
            bool: 是否有交集

        Raises:
            ValueIntersectionError: 当任一参数不是有效的Value类型对象时
        """
        # 严格的类型检查
        if not self.is_valid_value_object(value1):
            raise ValueIntersectionError(f"First parameter is not a valid Value object: {type(value1)}")
        if not self.is_valid_value_object(value2):
            raise ValueIntersectionError(f"Second parameter is not a valid Value object: {type(value2)}")

        try:
            # 如果两个都是Value对象，优先使用Value类的is_intersect_value方法
            if (hasattr(value1, 'is_intersect_value') and callable(value1.is_intersect_value) and
                hasattr(value2, 'is_intersect_value') and callable(value2.is_intersect_value)):
                return value1.is_intersect_value(value2)

            # 如果value1有is_intersect_value方法，使用它
            elif hasattr(value1, 'is_intersect_value') and callable(value1.is_intersect_value):
                return value1.is_intersect_value(value2)
            # 如果value2有is_intersect_value方法，调转参数
            elif hasattr(value2, 'is_intersect_value') and callable(value2.is_intersect_value):
                return value2.is_intersect_value(value1)
            # 回退到手动计算
            else:
                v1_begin = int(value1.begin_index, 16)
                v1_end = int(value1.end_index, 16)
                v2_begin = int(value2.begin_index, 16)
                v2_end = int(value2.end_index, 16)
                # 检查是否有重叠
                return not (v1_end < v2_begin or v2_end < v1_begin)

        except ValueError as e:
            raise ValueIntersectionError(f"Invalid value index format: {e}")
        except AttributeError as e:
            raise ValueIntersectionError(f"Missing required value attributes: {e}")

    def is_valid_value_object(self, value_obj: Any) -> bool:
        """
        检查对象是否是有效的Value类型对象

        严格类型检查：必须是Value类型（from EZ_VPB.values.Value import Value）

        Args:
            value_obj: 要检查的对象

        Returns:
            bool: 是否是有效的Value对象
        """
        # 严格检查是否为Value类型
        from EZ_VPB.values.Value import Value
        return isinstance(value_obj, Value)

    def transaction_spends_value(self, transaction: Any, value) -> bool:
        """
        检查交易是否花销了指定的value

        严格验证：所有value对象必须是有效的Value类型，遇到任何无效数据都会抛出异常

        Args:
            transaction: 交易对象（应符合项目的Transaction架构）
            value: Value对象

        Returns:
            bool: True-花销了该value，False-未花销该value

        Raises:
            ValueIntersectionError: 当交易中的value对象无效时
        """
        # 验证目标value本身必须是有效的
        if not self.is_valid_value_object(value):
            raise ValueIntersectionError(f"Target value is not a valid Value object: {type(value)}")

        # 根据项目的Transaction架构，Transaction只有一个value属性（List[Value]）
        # 在当前的Transaction模型中，所有的value都在transaction.value列表中
        if hasattr(transaction, 'value'):
            if not isinstance(transaction.value, (list, tuple)):
                raise ValueIntersectionError(f"transaction.value must be a list or tuple, got {type(transaction.value)}")

            for i, tx_value in enumerate(transaction.value):
                if not self.is_valid_value_object(tx_value):
                    raise ValueIntersectionError(f"Invalid value at index {i}: {type(tx_value)}")
                # 严格检查value是否完全匹配
                if (tx_value.begin_index == value.begin_index and
                    tx_value.end_index == value.end_index and
                    tx_value.value_num == value.value_num):
                    return True

        # 如果没有value属性或未找到匹配的value，返回False（确实未花销该value）
        return False