#!/usr/bin/env python3
"""
EZ_Proof 新架构使用示例

这个示例展示了如何使用新的AccountProofManager来管理Account级别的Value和ProofUnit关系。
"""

import os
import sys
import tempfile
from typing import List, Tuple

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value.Value import Value, ValueState
from EZ_Proof import AccountProofManager, create_account_proof_manager

def create_sample_value(begin_index: str, value_num: int) -> Value:
    """创建示例Value"""
    return Value(begin_index, value_num, ValueState.UNSPENT)

def basic_usage_example():
    """基本使用示例"""
    print("=== EZ_Proof 新架构基本使用示例 ===\n")

    # 使用临时数据库
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_db:
        db_path = tmp_db.name

    try:
        # 1. 创建AccountProofManager
        account_address = "0x1234567890abcdef"
        manager = create_account_proof_manager(account_address, db_path)
        print(f"✓ 创建AccountProofManager，账户地址: {account_address}")

        # 2. 添加一些Values
        values = [
            create_sample_value("0x1000", 100),
            create_sample_value("0x2000", 200),
            create_sample_value("0x3000", 150)
        ]

        for value in values:
            success = manager.add_value(value)
            print(f"✓ 添加Value {value.begin_index}: {'成功' if success else '失败'}")

        # 3. 获取统计信息
        stats = manager.get_statistics()
        print(f"\n📊 统计信息:")
        print(f"   总Values: {stats['total_values']}")
        print(f"   总ProofUnits: {stats['total_proof_units']}")
        print(f"   每个Value平均ProofUnits: {stats['avg_proofs_per_value']:.2f}")

        # 4. 查询所有Values
        all_values = manager.get_all_values()
        print(f"\n📋 账户所有Values ({len(all_values)}个):")
        for value in all_values:
            print(f"   - {value.begin_index}: {value.value_num} ({value.state.value})")

        # 5. 演示ProofUnit管理（模拟）
        print(f"\n🔐 ProofUnit管理演示:")
        print(f"   由于ProofUnit需要复杂的MultiTransactions和MerkleTreeProof对象，")
        print(f"   这里仅演示基本的Value管理功能。")

        # 6. 清理演示
        print(f"\n🧹 清理演示:")
        removed_value_id = values[0].begin_index
        success = manager.remove_value(removed_value_id)
        print(f"   移除Value {removed_value_id}: {'成功' if success else '失败'}")

        # 7. 最终统计
        final_stats = manager.get_statistics()
        print(f"\n📊 最终统计:")
        print(f"   总Values: {final_stats['total_values']}")
        print(f"   总ProofUnits: {final_stats['total_proof_units']}")

    finally:
        # 清理临时数据库
        if os.path.exists(db_path):
            os.unlink(db_path)

def advanced_usage_example():
    """高级使用示例"""
    print("\n=== EZ_Proof 高级使用示例 ===\n")

    account_address = "0xabcdef1234567890"

    # 创建管理器
    manager = AccountProofManager(account_address)
    print(f"✓ 创建AccountProofManager: {account_address}")

    # 批量添加Values
    value_pairs = [
        ("0x10000", 500),
        ("0x20000", 300),
        ("0x30000", 800),
        ("0x40000", 200),
        ("0x50000", 600)
    ]

    print(f"\n📦 批量添加Values:")
    for begin_idx, value_num in value_pairs:
        value = create_sample_value(begin_idx, value_num)
        manager.add_value(value)
        print(f"   + {begin_idx}: {value_num}")

    # 演示Value查询
    print(f"\n🔍 Value查询演示:")
    all_values = manager.get_all_values()
    print(f"   账户总Values: {len(all_values)}")

    total_balance = sum(v.value_num for v in all_values)
    print(f"   总余额: {total_balance}")

    # 演示统计功能
    print(f"\n📈 详细统计:")
    stats = manager.get_statistics()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # 演示清理功能
    print(f"\n🧹 清理演示:")
    print(f"   清除所有数据...")
    success = manager.clear_all()
    print(f"   清理结果: {'成功' if success else '失败'}")

    # 验证清理结果
    final_stats = manager.get_statistics()
    print(f"   清理后统计: {final_stats}")

def comparison_example():
    """新旧架构对比示例"""
    print("\n=== 新旧架构对比示例 ===\n")

    # 这里演示新架构的便利性
    print("✨ 新架构优势:")
    print("   1. Account级别的统一管理")
    print("   2. 自动避免ProofUnit重复")
    print("   3. 更高效的存储和查询")
    print("   4. 更好的统计和分析功能")
    print("   5. 向后兼容，支持逐步迁移")

    # 创建示例管理器
    manager = AccountProofManager("demo_account")

    # 添加一些数据
    demo_values = [
        create_sample_value("0xA000", 1000),
        create_sample_value("0xB000", 2000),
    ]

    for value in demo_values:
        manager.add_value(value)

    print(f"\n📋 新架构使用示例:")
    print(f"   管理器长度 (Value数量): {len(manager)}")
    print(f"   账户地址: {manager.account_address}")
    print(f"   包含特定Value: {'0xA000' in manager}")

    print(f"\n🔄 迭代演示:")
    for value_id, proof_units in manager:
        print(f"   Value {value_id}: {len(proof_units)} 个ProofUnits")

def main():
    """主函数"""
    print("🚀 EZ_Proof 新架构演示程序")
    print("=" * 50)

    try:
        # 基本使用示例
        basic_usage_example()

        # 高级使用示例
        advanced_usage_example()

        # 对比示例
        comparison_example()

        print(f"\n✅ 所有示例执行完成！")
        print(f"\n💡 提示:")
        print(f"   - 新架构提供了更好的Account级别管理")
        print(f"   - 旧架构仍然可用但会显示弃用警告")
        print(f"   - 建议新项目使用AccountProofManager")
        print(f"   - 现有项目可以逐步迁移到新架构")

    except Exception as e:
        print(f"\n❌ 执行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()