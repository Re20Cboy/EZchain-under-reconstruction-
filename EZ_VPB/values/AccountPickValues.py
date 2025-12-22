from typing import List, Tuple, Optional, TYPE_CHECKING
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .Value import Value, ValueState
from .AccountValueCollection import AccountValueCollection

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from EZ_Transaction.SingleTransaction import Transaction

def _get_transaction_class():
    """延迟导入Transaction类以避免循环依赖"""
    from EZ_Transaction.SingleTransaction import Transaction
    return Transaction

class AccountPickValues:
    """增强版Value选择器，基于AccountValueCollection实现高效调度"""
    
    def __init__(self, account_address: str, existing_collection: AccountValueCollection):
        """初始化AccountPickValues
        Args:
            account_address: 账户地址
            existing_collection: 现有的ValueCollection，必须提供用于交易的Value选择
        """
        if existing_collection is None:
            raise ValueError("必须提供existing_collection参数用于交易Value选择，不能为空")

        # 验证传入的collection与账户地址是否匹配
        if existing_collection.account_address != account_address:
            raise ValueError(f"提供的AccountValueCollection账户地址({existing_collection.account_address})与指定账户地址({account_address})不匹配")

        self.account_collection = existing_collection
        
    def add_values_from_list(self, values: List[Value]) -> int:
        """从Value列表批量添加Value"""
        added_count = 0
        for value in values:
            if self.account_collection.add_value(value):
                added_count += 1
        return added_count
    
    def pick_values_for_transaction(self, required_amount: int, sender: str, recipient: str,
                                 nonce: int, time: str) -> Tuple[List[Value], Optional[Value], Optional['Transaction'], Optional['Transaction']]:
        """为交易选择Value，返回选中的值、找零、找零交易、主交易"""
        if required_amount < 1:
            raise ValueError("交易金额必须大于等于1")
            
        selected_values = []
        total_selected = 0
        change_value = None
        
        # 获取可用的未花销Value
        available_values = self.account_collection.find_by_state(ValueState.UNSPENT)

        # 智能选择Value：优先寻找精确匹配
        exact_match_value = None
        for value in available_values:
            if value.value_num == required_amount:
                exact_match_value = value
                break

        if exact_match_value:
            # 找到精确匹配的值，直接使用
            selected_values.append(exact_match_value)
            total_selected = exact_match_value.value_num
        else:
            # 没有精确匹配，使用优化的贪心算法
            # 按值大小排序，优先使用较大的值以减少找零
            sorted_values = sorted(available_values, key=lambda v: v.value_num, reverse=True)

            for value in sorted_values:
                if total_selected >= required_amount:
                    break
                selected_values.append(value)
                total_selected += value.value_num

        # 检查余额是否足够
        if total_selected < required_amount:
            raise ValueError("余额不足！")
        
        # 计算找零
        change_amount = total_selected - required_amount
        
        # 创建交易
        change_transaction = None
        main_transaction = None
        
        #TODO: 未实现交易签名
        #判断是否需要找零
        if change_amount > 0 and selected_values != []:
            # 选择最后一个Value进行分裂
            last_value = selected_values[-1]
            
            # 在AccountValueCollection中找到对应的节点并分裂
            node_id = self._find_node_by_value(last_value)
            if node_id:
                v1, v2 = self.account_collection.split_value(node_id, change_amount)
                
                if v1 and v2:
                    # 更新选中值列表
                    selected_values[-1] = v1
                    change_value = v2
                    
                    # 将找零v2状态设置为SELECTED
                    self._update_value_state(v2, ValueState.SELECTED)
                    
                    # 创建（给sender自己）找零交易
                    Transaction = _get_transaction_class()
                    change_transaction = Transaction(
                        sender=sender,
                        recipient=sender,
                        nonce=nonce,
                        signature=None,
                        value=[v2],
                        time=time
                    )
                    
                    # 创建主交易
                    Transaction = _get_transaction_class()
                    main_transaction = Transaction(
                        sender=sender,
                        recipient=recipient,
                        nonce=nonce,
                        signature=None,
                        value=[v1] + selected_values[:-1],
                        time=time
                    )
        else:
            # 不需要找零，直接使用所有选中的值
            Transaction = _get_transaction_class()
            main_transaction = Transaction(
                sender=sender,
                recipient=recipient,
                nonce=nonce,
                signature=None,
                value=selected_values,
                time=time
            )
        
        # 将选中的Value状态更新为SELECTED
        for value in selected_values:
            self._update_value_state(value, ValueState.SELECTED)
            
        return selected_values, change_value, change_transaction, main_transaction
    
    def commit_transaction_values(self, selected_values: List[Value]) -> bool:
        """将选中的Value状态更新为LOCAL_COMMITTED"""
        for value in selected_values:
            self._update_value_state(value, ValueState.LOCAL_COMMITTED)
        return True
    
    def confirm_transaction_values(self, confirmed_values: List[Value]) -> bool:
        """确认交易，将Value状态更新为CONFIRMED"""
        for value in confirmed_values:
            self._update_value_state(value, ValueState.CONFIRMED)
        return True
    
    def rollback_transaction_selection(self, selected_values: List[Value]) -> bool:
        """回滚交易选择，将Value状态恢复为UNSPENT"""
        for value in selected_values:
            self._update_value_state(value, ValueState.UNSPENT)
        return True
    
    def get_account_balance(self, state: ValueState = ValueState.UNSPENT) -> int:
        """获取账户指定状态的余额"""
        return self.account_collection.get_balance_by_state(state)
    
    def get_total_account_balance(self) -> int:
        """获取账户总余额"""
        return self.account_collection.get_total_balance()
    
    def get_account_values(self, state: Optional[ValueState] = None) -> List[Value]:
        """获取账户Value列表"""
        if state is None:
            return self.account_collection.get_all_values()
        return self.account_collection.find_by_state(state)
    
    def cleanup_confirmed_values(self) -> int:
        """清除已确认的Value"""
        count = len(self.account_collection._state_index[ValueState.CONFIRMED])
        self.account_collection.clear_spent_values()
        return count
    
    def validate_account_integrity(self) -> bool:
        """验证账户完整性"""
        return self.account_collection.validate_no_overlap()
    
    def _find_node_by_value(self, target_value: Value) -> Optional[str]:
        """根据Value找到对应的node_id"""
        for node_id, node in self.account_collection._index_map.items():
            if node.value.is_same_value(target_value):
                return node_id
        return None
    
    def _update_value_state(self, value: Value, new_state: ValueState) -> bool:
        """更新Value状态"""
        node_id = self._find_node_by_value(value)
        if node_id:
            return self.account_collection.update_value_state(node_id, new_state)
        return False
