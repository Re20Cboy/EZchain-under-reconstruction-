#!/usr/bin/env python3
"""
调试VPB初始化问题 - 为什么创世初始化后可用余额为0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.values.AccountValueCollection import AccountValueCollection, ValueNode
from EZ_VPB.values.Value import Value, ValueState

def test_basic_value_collection():
    """测试基本的ValueCollection功能"""
    print("="*60)
    print("测试1: 基本的ValueCollection功能")
    print("="*60)

    collection = AccountValueCollection("test_account")

    # 创建几个测试Values
    values = []
    for i in range(5):
        value = Value(
            beginIndex=f"0x{i:04x}",
            valueNum=10,
            state=ValueState.UNSPENT
        )
        values.append(value)

    print(f"创建了 {len(values)} 个UNSPENT Values")
    for i, value in enumerate(values):
        print(f"  {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state.value}")

    # 逐个添加Values
    print("\n逐个添加Values...")
    for i, value in enumerate(values):
        success = collection.add_value(value)
        print(f"  添加Value {value.begin_index}: {'成功' if success else '失败'}")

    # 检查状态索引
    print(f"\n添加后_collection._state_index:")
    for state, node_ids in collection._state_index.items():
        print(f"  {state}: {len(node_ids)} 个nodes")

    # 查找UNSPENT的Values
    print(f"\nfind_by_state(UNSPENT)结果:")
    unspent_values = collection.find_by_state(ValueState.UNSPENT)
    print(f"  找到 {len(unspent_values)} 个UNSPENT Values")
    for value in unspent_values:
        print(f"    {value.begin_index} - amount={value.value_num} - state={value.state.value}")

    # 计算余额
    balance = collection.get_balance_by_state(ValueState.UNSPENT)
    print(f"\nget_balance_by_state(UNSPENT): {balance}")

def test_batch_add_values():
    """测试批量添加Values功能"""
    print("\n" + "="*60)
    print("测试2: 批量添加Values功能")
    print("="*60)

    collection = AccountValueCollection("test_batch_account")

    # 创建测试Values
    values = []
    for i in range(10):
        value = Value(
            beginIndex=f"0x{i:04x}",
            valueNum=10,
            state=ValueState.UNSPENT
        )
        values.append(value)

    print(f"创建了 {len(values)} 个UNSPENT Values")

    # 使用批量添加
    print("\n使用batch_add_values添加...")
    node_ids = collection.batch_add_values(values)
    print(f"  返回的node_ids: {len(node_ids)}")
    print(f"  collection.size: {collection.size}")

    # 检查状态索引
    print(f"\n批量添加后_collection._state_index:")
    for state, node_ids in collection._state_index.items():
        print(f"  {state}: {len(node_ids)} 个nodes")
        if state == ValueState.UNSPENT:
            print(f"    UNSPENT node_ids: {list(node_ids)}")

    # 查找UNSPENT的Values
    print(f"\nfind_by_state(UNSPENT)结果:")
    unspent_values = collection.find_by_state(ValueState.UNSPENT)
    print(f"  找到 {len(unspent_values)} 个UNSPENT Values")
    for i, value in enumerate(unspent_values[:3]):  # 只显示前3个
        print(f"    {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state.value}")

    # 计算余额
    balance = collection.get_balance_by_state(ValueState.UNSPENT)
    print(f"\nget_balance_by_state(UNSPENT): {balance}")

def test_vpb_manager_initialization():
    """测试VPBManager的初始化"""
    print("\n" + "="*60)
    print("测试3: VPBManager初始化测试")
    print("="*60)

    try:
        from EZ_VPB.VPBManager import VPBManager
        from EZ_VPB.block_index.BlockIndexList import BlockIndexList
        from EZ_VPB.proofs.ProofUnit import ProofUnit

        account_address = "debug_test_account"
        vpb_manager = VPBManager(account_address)

        # 创建测试Values
        genesis_values = []
        for i in range(10):
            value = Value(
                beginIndex=f"0x{i:04x}",
                valueNum=10,
                state=ValueState.UNSPENT
            )
            genesis_values.append(value)

        # 创建测试ProofUnits
        genesis_proof_units = []
        for i, value in enumerate(genesis_values):
            proof_unit = ProofUnit(
                owner=account_address,
                owner_multi_txns=None,  # 简化测试
                owner_mt_proof=None      # 简化测试
            )
            genesis_proof_units.append(proof_unit)

        # 创建BlockIndex
        genesis_block_index = BlockIndexList(
            index_lst=[0],
            owner=(0, account_address)
        )

        print(f"初始化数据准备完成:")
        print(f"  - genesis_values: {len(genesis_values)}")
        print(f"  - genesis_proof_units: {len(genesis_proof_units)}")
        print(f"  - block_index: {genesis_block_index.index_lst}")

        # 检查初始化前的状态
        print(f"\n初始化前VPB状态:")
        print(f"  - 总Values: {len(vpb_manager.get_all_values())}")
        print(f"  - 总余额: {vpb_manager.get_total_balance()}")
        print(f"  - 可用余额: {vpb_manager.get_unspent_balance()}")

        # 执行初始化
        print(f"\n执行initialize_from_genesis_batch...")
        success = vpb_manager.initialize_from_genesis_batch(
            genesis_values=genesis_values,
            genesis_proof_units=genesis_proof_units,
            genesis_block_index=genesis_block_index
        )
        print(f"初始化结果: {'成功' if success else '失败'}")

        # 检查初始化后的状态
        print(f"\n初始化后VPB状态:")
        all_values = vpb_manager.get_all_values()
        unspent_values = vpb_manager.get_unspent_values()
        print(f"  - 总Values: {len(all_values)}")
        print(f"  - 总余额: {vpb_manager.get_total_balance()}")
        print(f"  - 可用余额: {vpb_manager.get_unspent_balance()}")
        print(f"  - 未花销Values: {len(unspent_values)}")

        # 深入调试ValueCollection
        collection = vpb_manager.value_collection
        print(f"\nValueCollection内部状态:")
        print(f"  - size: {collection.size}")
        print(f"  - head is None: {collection.head is None}")
        print(f"  - _state_index: {dict(collection._state_index)}")
        print(f"  - _index_map size: {len(collection._index_map)}")

        # 直接调用find_by_state
        direct_unspent = collection.find_by_state(ValueState.UNSPENT)
        print(f"  - 直接find_by_state(UNSPENT): {len(direct_unspent)}")
        print(f"  - 直接计算UNSPENT余额: {sum(v.value_num for v in direct_unspent)}")

        # 检查Values的状态
        if all_values:
            print(f"\n前5个Values的状态:")
            for i, value in enumerate(all_values[:5]):
                print(f"    {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state} - is_unspent={value.is_unspent()}")

        if unspent_values:
            print(f"\n前3个未花销Values:")
            for i, value in enumerate(unspent_values[:3]):
                print(f"    {i+1}. {value.begin_index} - amount={value.value_num} - state={value.state}")
        else:
            print(f"\n❌ 警告: get_unspent_values()返回空列表!")

    except ImportError as e:
        print(f"导入错误: {e}")
        print("跳过VPBManager测试")
    except Exception as e:
        print(f"VPBManager测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_value_state_comparison():
    """测试Value状态比较"""
    print("\n" + "="*60)
    print("测试4: Value状态比较")
    print("="*60)

    values = [
        Value("0x0001", 10, ValueState.UNSPENT),
        Value("0x0002", 20, ValueState.SELECTED),
        Value("0x0003", 30, ValueState.LOCAL_COMMITTED),
        Value("0x0004", 40, ValueState.CONFIRMED),
        Value("0x0005", 50, ValueState.UNSPENT),
    ]

    print("Values状态检查:")
    for i, value in enumerate(values):
        print(f"  {i+1}. {value.begin_index} - state={value.state} - .value={value.state.value} - is_unspent={value.is_unspent()}")

    collection = AccountValueCollection("state_test")
    node_ids = collection.batch_add_values(values)

    print(f"\n批量添加后:")
    print(f"  size: {collection.size}")
    print(f"  _state_index: {dict(collection._state_index)}")

    for state in ValueState:
        found_values = collection.find_by_state(state)
        balance = collection.get_balance_by_state(state)
        print(f"  {state.value}: {len(found_values)} values, balance={balance}")

def main():
    """主测试函数"""
    print("VPB初始化问题调试")
    print("=" * 60)

    # 测试1: 基本功能
    test_basic_value_collection()

    # 测试2: 批量添加
    test_batch_add_values()

    # 测试3: VPBManager
    test_vpb_manager_initialization()

    # 测试4: 状态比较
    test_value_state_comparison()

    print("\n" + "="*60)
    print("调试完成")
    print("="*60)

if __name__ == "__main__":
    main()