#!/usr/bin/env python3
"""
更详细的余额计算调试 - 针对get_balance_by_state返回0的问题
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.values.Value import Value, ValueState

def debug_balance_calculation_detailed():
    """详细调试余额计算问题"""
    print("="*60)
    print("详细余额计算调试")
    print("="*60)

    collection = AccountValueCollection("debug_detailed_account")

    # 创建测试Values
    values = []
    amounts = [1000, 500, 100, 100, 50]  # 对应创世块的面额

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
        if state == ValueState.UNSPENT:
            print(f"    UNSPENT node_ids: {list(node_ids)[:5]}...")  # 只显示前5个

    # 方法1: 直接调用find_by_state
    print(f"\n方法1: 直接调用find_by_state(UNSPENT)")
    unspent_values = collection.find_by_state(ValueState.UNSPENT)
    print(f"  找到 {len(unspent_values)} 个UNSPENT Values")
    print(f"  前3个Values详情:")
    for i, value in enumerate(unspent_values[:3]):
        print(f"    {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state.value}")

    # 方法2: 调用get_balance_by_state
    print(f"\n方法2: 调用get_balance_by_state(UNSPENT)")
    calculated_balance = collection.get_balance_by_state(ValueState.UNSPENT)
    print(f"  计算得到的余额: {calculated_balance}")

    # 方法3: 手动计算
    print(f"\n方法3: 手动计算相同Values的总和")
    if unspent_values:
        manual_total = sum(value.value_num for value in unspent_values)
        print(f"  手动计算总和: {manual_total}")
    else:
        manual_total = 0
        print(f"  手动计算总和: 0")

    # 方法4: 重新调用find_by_state并再次检查
    print(f"\n方法4: 重新调用find_by_state(UNSPENT)验证")
    unspent_values_2 = collection.find_by_state(ValueState.UNSPENT)
    print(f"  第二次找到 {len(unspent_values_2)} 个UNSPENT Values")
    if unspent_values_2 != unspent_values:
        print(f"  ⚠️  警告: 两次find_by_state结果不一致！")
    else:
        print(f"  ✅ 两次find_by_state结果一致")

    # 方法5: 直接检查_values列表方法
    print(f"\n方法5: 直接调用get_all_values并检查")
    all_values = collection.get_all_values()
    print(f"  总Values数量: {len(all_values)}")

    # 筛选UNSPENT状态的Values
    unspent_from_all = [v for v in all_values if v.state == ValueState.UNSPENT]
    print(f"  从all_values筛选出的UNSPENT Values: {len(unspent_from_all)}")

    if unspent_from_all:
        total_from_all = sum(v.value_num for v in unspent_from_all)
        print(f"  从all_values计算的总和: {total_from_all}")
    else:
        print(f"  从all_values计算的总和: 0")

    # 方法6: 检查collection的内部状态一致性
    print(f"\n方法6: 检查ValueCollection内部状态一致性")
    print(f"  _state_index[UNSPENT] size: {len(collection._state_index.get(ValueState.UNSPENT, set()))}")
    print(f"  _index_map size: {len(collection._index_map)}")
    print(f"  collection.size: {collection.size}")

    # 验证每个node在两个索引中是否存在
    if hasattr(collection, '_index_map'):
        print(f"  验证node索引一致性:")
        unspent_node_ids = collection._state_index.get(ValueState.UNSPENT, set())
        for i, node_id in enumerate(list(unspent_node_ids)[:3]):
            if node_id in collection._index_map:
                node = collection._index_map[node_id]
                print(f"    {i+1}. node_id={node_id}, value={node.value.begin_index}, state={node.state.value}")
            else:
                print(f"    {i+1}. ⚠️  node_id={node_id} 在_index_map中不存在!")

    # 对比不同方法的结果
    print(f"\n结果对比:")
    print(f"  find_by_state count: {len(unspent_values)}")
    print(f"  find_by_state balance: {sum(v.value_num for v in unspent_values) if unspent_values else 0}")
    print(f"  get_balance_by_state: {calculated_balance}")
    print(f"  get_all_values filter: {len(unspent_from_all)}")
    print(f"  get_all_values balance: {sum(v.value_num for v in unspent_from_all) if unspent_from_all else 0}")

    # 检查是否所有方法都返回一致的结果
    results = {
        'find_by_state': len(unspent_values),
        'find_by_state_balance': sum(v.value_num for v in unspent_values) if unspent_values else 0,
        'get_balance_by_state': calculated_balance,
        'get_all_values_filter': len(unspent_from_all),
        'get_all_values_balance': sum(v.value_num for v in unspent_from_all) if unspent_from_all else 0
    }

    print(f"\n所有方法结果: {results}")

    # 检查是否有不一致
    unique_results = set(results.values())
    if len(unique_results) == 1:
        print("✅ 所有方法返回一致的结果")
    else:
        print("❌ 发现不一致的结果！")
        for method, result in results.items():
            print(f"  {method}: {result}")

if __name__ == "__main__":
    debug_balance_calculation_detailed()