"""
测试新的 AccountPickValues 实现

测试内容：
1. 不支持找零的新方法
2. 检查点优先级逻辑
3. 旧方法的向后兼容性
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.values.AccountPickValues import AccountPickValues
from EZ_CheckPoint.CheckPoint import CheckPointRecord
from datetime import datetime, timezone


def test_new_pick_values_without_change():
    """测试新的不支持找零的方法"""
    print("=" * 80)
    print("测试 1: 新方法不支持找零 - 应该在无法精确凑出金额时抛出异常")
    print("=" * 80)

    # 创建测试账户
    account_address = "0xTestAccount1"
    db_path = "test_temp_account_collection.db"
    collection = AccountValueCollection(account_address, db_path=db_path)

    # 添加一些测试 values
    value1 = Value("0x100", 50)  # 50 units
    value2 = Value("0x200", 30)  # 30 units
    value3 = Value("0x300", 20)  # 20 units

    collection.add_value(value1)
    collection.add_value(value2)
    collection.add_value(value3)

    picker = AccountPickValues(account_address, collection)

    # 测试场景 1: 可以精确凑出金额
    print("\n场景 1a: 尝试凑出 50 单位（精确匹配）")
    try:
        selected_values, main_transaction = picker.pick_values_for_transaction(
            required_amount=50,
            sender=account_address,
            recipient="0xRecipient1",
            nonce=1,
            time="2024-01-01T00:00:00",
            checkpoint=None
        )
        total = sum(v.value_num for v in selected_values)
        print(f"[OK] 成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
        print(f"  选中的 values: {[f'{v.begin_index}({v.value_num})' for v in selected_values]}")
    except ValueError as e:
        print(f"[FAIL] 失败: {e}")

    # 测试场景 2: 可以组合凑出金额
    print("\n场景 1b: 尝试凑出 80 单位（50+30）")
    try:
        selected_values, main_transaction = picker.pick_values_for_transaction(
            required_amount=80,
            sender=account_address,
            recipient="0xRecipient2",
            nonce=2,
            time="2024-01-01T00:00:00",
            checkpoint=None
        )
        total = sum(v.value_num for v in selected_values)
        print(f"[OK] 成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
        print(f"  选中的 values: {[f'{v.begin_index}({v.value_num})' for v in selected_values]}")
    except ValueError as e:
        print(f"[FAIL] 失败: {e}")

    # 测试场景 3: 无法精确凑出金额（应该失败）
    print("\n场景 1c: 尝试凑出 55 单位（无法精确凑出，应该失败）")
    try:
        selected_values, main_transaction = picker.pick_values_for_transaction(
            required_amount=55,
            sender=account_address,
            recipient="0xRecipient3",
            nonce=3,
            time="2024-01-01T00:00:00",
            checkpoint=None
        )
        total = sum(v.value_num for v in selected_values)
        print(f"[UNEXPECTED] 不应该成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
    except ValueError as e:
        print(f"[OK] 预期的失败: {e}")


def test_checkpoint_prioritization():
    """测试检查点优先级逻辑"""
    print("\n" + "=" * 80)
    print("测试 2: 检查点优先级逻辑")
    print("=" * 80)

    # 创建测试账户
    account_address = "0xTestAccount2"
    collection = AccountValueCollection(account_address, ":memory:")

    # 添加一些测试 values
    value1 = Value("0x100", 50)  # 50 units
    value2 = Value("0x200", 30)  # 30 units
    value3 = Value("0x300", 20)  # 20 units

    collection.add_value(value1)
    collection.add_value(value2)
    collection.add_value(value3)

    picker = AccountPickValues(account_address, collection)

    # 创建一个检查点：value1 在区块高度 100 时由 0xCheckpointOwner 持有
    checkpoint = CheckPointRecord(
        value_begin_index="0x100",
        value_num=50,
        owner_address="0xCheckpointOwner",
        block_height=100,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    # 测试场景: 当 recipient 是检查点的 owner 时，应该优先选择匹配的 value
    print("\n场景 2a: recipient 是检查点的历史 owner，应该优先选择 value1 (50)")
    try:
        selected_values, main_transaction = picker.pick_values_for_transaction(
            required_amount=50,
            sender=account_address,
            recipient="0xCheckpointOwner",  # 与检查点的 owner 匹配
            nonce=1,
            time="2024-01-01T00:00:00",
            checkpoint=checkpoint
        )
        total = sum(v.value_num for v in selected_values)
        print(f"✓ 成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
        print(f"  选中的 values: {[f'{v.begin_index}({v.value_num})' for v in selected_values]}")

        # 验证是否优先选择了匹配检查点的 value
        if selected_values and selected_values[0].begin_index == "0x100":
            print("  ✓ 确认: 优先选择了匹配检查点的 value")
        else:
            print("  ✗ 警告: 没有优先选择匹配检查点的 value")
    except ValueError as e:
        print(f"✗ 失败: {e}")

    # 测试场景: recipient 不是检查点的 owner，不应该有优先级
    print("\n场景 2b: recipient 不是检查点的历史 owner，使用常规贪婪策略")
    try:
        selected_values, main_transaction = picker.pick_values_for_transaction(
            required_amount=50,
            sender=account_address,
            recipient="0xOtherRecipient",  # 不匹配检查点的 owner
            nonce=2,
            time="2024-01-01T00:00:00",
            checkpoint=checkpoint
        )
        total = sum(v.value_num for v in selected_values)
        print(f"✓ 成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
        print(f"  选中的 values: {[f'{v.begin_index}({v.value_num})' for v in selected_values]}")
    except ValueError as e:
        print(f"✗ 失败: {e}")


def test_legacy_method():
    """测试旧方法的向后兼容性"""
    print("\n" + "=" * 80)
    print("测试 3: 旧方法的向后兼容性（支持找零）")
    print("=" * 80)

    # 创建测试账户
    account_address = "0xTestAccount3"
    collection = AccountValueCollection(account_address, ":memory:")

    # 添加一些测试 values
    value1 = Value("0x100", 50)  # 50 units
    value2 = Value("0x200", 30)  # 30 units

    collection.add_value(value1)
    collection.add_value(value2)

    picker = AccountPickValues(account_address, collection)

    # 测试旧方法：应该支持找零
    print("\n场景 3a: 使用旧方法凑出 55 单位（50+30，应该找零 25）")
    try:
        selected_values, change_value, change_transaction, main_transaction = \
            picker.pick_values_for_transaction_with_change_legacy(
                required_amount=55,
                sender=account_address,
                recipient="0xRecipient1",
                nonce=1,
                time="2024-01-01T00:00:00"
            )
        total = sum(v.value_num for v in selected_values)
        print(f"✓ 成功: 选中了 {len(selected_values)} 个 values, 总金额: {total}")
        print(f"  选中的 values: {[f'{v.begin_index}({v.value_num})' for v in selected_values]}")
        if change_value:
            print(f"  找零: {change_value.value_num} 单位")
    except ValueError as e:
        print(f"✗ 失败: {e}")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("开始测试新的 AccountPickValues 实现")
    print("=" * 80)

    try:
        test_new_pick_values_without_change()
        test_checkpoint_prioritization()
        test_legacy_method()

        print("\n" + "=" * 80)
        print("所有测试完成！")
        print("=" * 80)
    except Exception as e:
        print(f"\n测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
