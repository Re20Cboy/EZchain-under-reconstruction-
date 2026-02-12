import re
from enum import Enum
from typing import Optional
import time

class ValueState(Enum):
    UNSPENT = "unspent"  # 未花费状态，表示该value尚未被用于任何交易
    SELECTED = "pending"  # 兼容旧状态名：映射到PENDING
    PENDING = "pending"  # 待确认状态，表示该value已被用于交易，但交易尚未被区块链网络确认
    ONCHAIN = "onchain"  # 链上提交状态，表示该value已被用于交易，并且该交易已提交到区块链网络，但尚未被确认
    RECEIVED = "received"  # 已接收状态，表示该value已被交易的接收方成功接收到（暂未开始检测vpb合法性）
    VERIFIED = "verified"  # 已验证状态，表示该value已被交易的接收方成功验证通过（vpb合法性验证通过）
    CONFIRMED = "confirmed"  # 已确认状态，表示value已在主链上被确认超过制定区块数（e.g.,3块），表示该value已被用于交易

class Value:  # 针对VCB区块链的专门设计的值结构，总量2^259 = 16^65（总量暂未定）
    def __init__(self, beginIndex, valueNum, state=ValueState.UNSPENT, verified_timestamp: Optional[float] = None):  # beginIndex是16进制str，valueNum是10进制int，state是ValueState枚举
        # 输入参数验证
        if not isinstance(beginIndex, str):
            raise TypeError("beginIndex must be a string")
        if not isinstance(valueNum, int):
            raise TypeError("valueNum must be an integer")
        if not isinstance(state, ValueState):
            raise TypeError("state must be a ValueState enum")

        if valueNum <= 0:
            raise ValueError("valueNum must be positive")

        if not self._is_valid_hex(beginIndex):
            raise ValueError("beginIndex must be a valid hexadecimal string starting with '0x'")

        # 值的开始和结束index都包含在值内
        self.begin_index = beginIndex
        self.value_num = valueNum
        self.state = state
        self.end_index = self.get_end_index(beginIndex, valueNum)

        # 记录设置为VERIFIED状态的时间戳（用于自动转换为UNSPENT）
        # 如果状态为VERIFIED但没有提供时间戳，则使用当前时间
        if state == ValueState.VERIFIED and verified_timestamp is None:
            self.verified_timestamp = time.time()
        else:
            self.verified_timestamp = verified_timestamp

    def print_value(self):
        print('value #begin:' + str(self.begin_index))
        print('value #end:' + str(self.end_index))
        print('value num:' + str(self.value_num))
        print('value state:' + str(self.state.value))

    def get_decimal_begin_index(self):
        return int(self.begin_index, 16)

    def get_decimal_end_index(self):
        return int(self.end_index, 16)

    def split_value(self, change):  # 对此值进行分割
        # 边缘值检测
        if change <= 0 or change >= self.value_num:
            raise ValueError("Invalid change value")
        V1 = Value(self.begin_index, self.value_num - change, self.state)
        tmpIndex = hex(V1.get_decimal_end_index() + 1)
        V2 = Value(tmpIndex, change, self.state)
        return V1, V2  # V2是找零

    def get_end_index(self, begin_index, value_num):
        decimal_number = int(begin_index, 16)
        result = decimal_number + value_num - 1
        return hex(result)

    def _is_valid_hex(self, hex_string):
        return re.match(r"^0x[0-9A-Fa-f]+$", hex_string) is not None
        
    def check_value(self):  # 检测Value的合法性
        if self.value_num <= 0 or not self._is_valid_hex(self.begin_index) or not self._is_valid_hex(self.end_index):
            return False
        return self.end_index == self.get_end_index(self.begin_index, self.value_num)

    def set_state(self, new_state):  # 设置值的状态
        if not isinstance(new_state, ValueState):
            raise TypeError("new_state must be a ValueState enum")

        # 当状态设置为VERIFIED时，记录当前时间戳
        if new_state == ValueState.VERIFIED and self.state != ValueState.VERIFIED:
            self.verified_timestamp = time.time()
        elif new_state != ValueState.VERIFIED:
            # 如果状态从VERIFIED变为其他状态，清除时间戳
            self.verified_timestamp = None

        self.state = new_state

    def is_unspent(self):  # 检查值是否为未花费状态
        return self.state == ValueState.UNSPENT

    def is_pending(self):  # 检查值是否为待确认状态
        return self.state == ValueState.PENDING

    # Backward compatibility alias for legacy tests/callers.
    # LOCAL_COMMITTED was removed from the current state model.
    # Keep this method for old callers but always report False.
    def is_local_committed(self):
        return False

    def is_onchain(self):  # 检查值是否为链上提交状态
        return self.state == ValueState.ONCHAIN

    def is_received(self):  # 检查值是否为已接收状态
        return self.state == ValueState.RECEIVED

    def is_verified(self):  # 检查值是否为已验证状态
        return self.state == ValueState.VERIFIED

    def is_confirmed(self):  # 检查值是否为已确认状态
        return self.state == ValueState.CONFIRMED

    def can_be_selected(self):  # 检查值是否可以被选中（只有未花费状态可以）
        return self.is_unspent()

    '''def can_be_spent(self):  # 检查值是否可以被花费（只有未花销状态可以）
        return self.is_unspent()'''

    def get_intersect_value(self, target):  # target是Value类型, 获取和target有交集的值的部分
        decimal_begin = self.get_decimal_begin_index()
        decimal_end = self.get_decimal_end_index()
        decimal_target_begin = int(target.begin_index, 16)
        decimal_target_end = int(target.end_index, 16)
        
        intersect_begin = max(decimal_target_begin, decimal_begin)
        intersect_end = min(decimal_target_end, decimal_end)
        
        if intersect_begin > intersect_end:
            return None
            
        intersect_value = Value(hex(intersect_begin), intersect_end - intersect_begin + 1)
        
        rest_values = []
        if decimal_begin < intersect_begin:
            rest_values.append(Value(hex(decimal_begin), intersect_begin - decimal_begin))
        if intersect_end < decimal_end:
            rest_values.append(Value(hex(intersect_end + 1), decimal_end - intersect_end))
            
        return (intersect_value, rest_values)

    def is_intersect_value(self, target):  # target是Value类型, 判断target是否和本value有交集
        decimal_begin = self.get_decimal_begin_index()
        decimal_end = self.get_decimal_end_index()
        decimal_target_begin = int(target.begin_index, 16)
        decimal_target_end = int(target.end_index, 16)
        return decimal_end >= decimal_target_begin and decimal_target_end >= decimal_begin

    def is_in_value(self, target):  # target是Value类型, 判断target是否在本value内
        decimal_begin = self.get_decimal_begin_index()
        decimal_end = self.get_decimal_end_index()
        decimal_target_begin = int(target.begin_index, 16)
        decimal_target_end = int(target.end_index, 16)
        return decimal_target_begin >= decimal_begin and decimal_target_end <= decimal_end

    def is_same_value(self, target):  # target是Value类型, 判断target是否就是本value
        if not isinstance(target, Value):
            print('ERR: func isSameValue get illegal input!')
            return False
        return target.begin_index == self.begin_index and target.end_index == self.end_index and target.value_num == self.value_num
    
    def to_dict(self) -> dict:
        """Convert Value to dictionary for deterministic serialization."""
        return {
            "begin_index": self.begin_index,
            "end_index": self.end_index,
            "value_num": self.value_num,
            "state": self.state.value
        }
    
    def to_dict_for_signing(self) -> dict:
        """Convert Value to dictionary for signature serialization (excludes state)."""
        return {
            "begin_index": self.begin_index,
            "end_index": self.end_index,
            "value_num": self.value_num
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Value':
        """Create Value from dictionary"""
        return cls(
            beginIndex=data['begin_index'],
            valueNum=data['value_num'],
            state=ValueState(data['state'])
        )
