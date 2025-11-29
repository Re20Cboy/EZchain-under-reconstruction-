#!/usr/bin/env python3
"""
调试余额计算问题 - 为什么get_balance_by_state返回0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.values.Value import Value, ValueState

def debug_balance_calculation():
    """调试余额计算问题"""
    print("="*60)
    print("调试余额计算问题")
    print("="*60)

    collection = AccountValueCollection("debug_balance_account")

    # 创建测试Values
    values = []
    amounts = [1000, 500, 100, 100, 100, 50]  # 对应创世块的面额

    for i, amount in enumerate(amounts):
        value = Value(
            beginIndex=f"0x{i:04x}",
            valueNum=amount,
            state=ValueState.UNSPENT
        )
        values.append(value)

    print(f"创建了 {len(values)} 个测试Values:")
    for i, value in enumerate(values):
        print(f"  {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state.value}")

    # 使用批量添加
    print(f"\n使用batch_add_values添加Values...")
    node_ids = collection.batch_add_values(values)
    print(f"  返回node_ids: {len(node_ids)}")
    print(f"  collection.size: {collection.size}")

    # 检查状态索引
    print(f"\n添加后的状态索引:")
    for state, node_ids in collection._state_index.items():
        print(f"  {state.value}: {len(node_ids)} 个nodes")

    # 使用find_by_state获取UNSPENT Values
    print(f"\n使用find_by_state(UNSPENT):")
    unspent_values = collection.find_by_state(ValueState.UNSPENT)
    print(f"  找到 {len(unspent_values)} 个UNSPENT Values")

    if unspent_values:
        print(f"  前3个Values详情:")
        for i, value in enumerate(unspent_values[:3]):
            print(f"    {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state.value}")

        # 手动计算余额
        manual_total = sum(value.value_num for value in unspent_values)
        print(f"  手动计算总余额: {manual_total}")

    # 使用get_balance_by_state
    print(f"\n使用get_balance_by_state(UNSPENT):")
    calculated_balance = collection.get_balance_by_state(ValueState.UNSPENT)
    print(f"  计算得到的余额: {calculated_balance}")

    # 调试get_balance_by_state内部逻辑
    print(f"\n调试get_balance_by_state内部逻辑:")
    print(f"  调用collection.find_by_state(ValueState.UNSPENT)返回: {len(unspent_values)} 个Values")
    if unspent_values:
        values_list = list(unspent_values)  # 确保是list
        print(f"  转换为list后长度: {len(values_list)}")

        # 逐个检查value_num
        print(f"  检查每个value的value_num:")
        for i, value in enumerate(values_list[:5]):  # 只检查前5个
            print(f"    {i+1}. value_num: {value.value_num}, 类型: {type(value.value_num)}")

        # 尝试计算总和
        try:
            total = 0
            for i, value in enumerate(values_list):
                total += value.value_num
                if i < 5:  # 显示前5次的累加
                    print(f"    第{i+1}次累加: {total}")
            print(f"  循环累加总和: {total}")
        except Exception as e:
            print(f"  循环累加错误: {e}")

        # 使用sum函数
        try:
            sum_result = sum(values_list, key=lambda v: v.value_num)
            print(f"  sum() with key: {sum_result}")
        except Exception as e:
            print(f"  sum() with key 错误: {e}")

        try:
            sum_result = sum(v.value_num for v in values_list)
            print(f"  sum() with generator: {sum_result}")
        except Exception as e:
            print(f"  sum() with generator 错误: {e}")

    # 比较结果
    print(f"\n结果比较:")
    print(f"  手动计算: {manual_total if unspent_values else 0}")
    print(f"  get_balance_by_state: {calculated_balance}")
    print(f"  是否相等: {manual_total == calculated_balance if unspent_values else calculated_balance == 0}")

if __name__ == "__main__":
    debug_balance_calculation()