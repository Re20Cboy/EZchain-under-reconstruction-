#!/usr/bin/env python3
"""
最终验证测试 - 验证AccountProofManager的顺序保持功能
"""

import os
import sys
import tempfile
import shutil

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.proofs.AccountProofManager import AccountProofStorage


def main():
    """验证顺序保持功能"""
    print("=== AccountProofManager顺序保持功能验证 ===")

    # 创建临时数据库
    test_db = "temp_test_ordering.db"

    try:
        # 创建存储管理器
        storage = AccountProofStorage(test_db)
        account_address = "test_account"
        value_id = "test_value"

        # 测试数据
        unit_ids = ["unit_A", "unit_B", "unit_C", "unit_D", "unit_E"]

        print("1. 按顺序添加映射关系:")
        for i, unit_id in enumerate(unit_ids, 1):
            success = storage.add_value_proof_mapping(account_address, value_id, unit_id)
            print(f"   {i}. 添加 {unit_id}: {'成功' if success else '失败'}")

        print("\n2. 验证数据库中的顺序:")
        import sqlite3
        with sqlite3.connect(test_db) as conn:
            cursor = conn.execute("""
                SELECT unit_id, sequence FROM account_value_proofs
                WHERE account_address = ? AND value_id = ?
                ORDER BY sequence ASC
            """, (account_address, value_id))

            rows = cursor.fetchall()
            retrieved_unit_ids = [row[0] for row in rows]
            sequences = [row[1] for row in rows]

        print(f"   原始顺序: {unit_ids}")
        print(f"   检索顺序: {retrieved_unit_ids}")
        print(f"   Sequences: {sequences}")

        # 验证顺序
        order_correct = (unit_ids == retrieved_unit_ids)
        print(f"   顺序正确: {'是' if order_correct else '否'}")

        print("\n3. 测试删除后重新添加:")
        # 删除unit_C
        storage.remove_value_proof_mapping(account_address, value_id, "unit_C")
        print("   删除 unit_C")

        # 重新添加unit_C_new
        storage.add_value_proof_mapping(account_address, value_id, "unit_C_new")
        print("   添加 unit_C_new")

        # 验证新顺序
        with sqlite3.connect(test_db) as conn:
            cursor = conn.execute("""
                SELECT unit_id FROM account_value_proofs
                WHERE account_address = ? AND value_id = ?
                ORDER BY sequence ASC
            """, (account_address, value_id))

            final_unit_ids = [row[0] for row in cursor]

        expected_final = ["unit_A", "unit_B", "unit_D", "unit_E", "unit_C_new"]
        print(f"   期望最终顺序: {expected_final}")
        print(f"   实际最终顺序: {final_unit_ids}")
        print(f"   删除重加顺序正确: {'是' if expected_final == final_unit_ids else '否'}")

        print("\n4. 测试内存数据结构:")
        from EZ_VPB.proofs.AccountProofManager import AccountProofManager
        manager = AccountProofManager("memory_test")
        manager.add_value("memory_value")

        # 验证内部数据结构
        mapping_type = type(manager._value_proof_mapping.get("memory_value", []))
        is_list = isinstance(manager._value_proof_mapping.get("memory_value", []), list)
        print(f"   内存数据结构类型: {mapping_type}")
        print(f"   是list类型: {'是' if is_list else '否'}")

        # 总结
        all_tests_pass = (
            order_correct and
            (expected_final == final_unit_ids) and
            is_list
        )

        print(f"\n=== 总结 ===")
        print(f"数据库顺序保持: {'通过' if order_correct else '失败'}")
        print(f"删除重加顺序: {'通过' if expected_final == final_unit_ids else '失败'}")
        print(f"内存数据结构: {'通过' if is_list else '失败'}")
        print(f"总体结果: {'所有测试通过!' if all_tests_pass else '部分测试失败'}")

        return all_tests_pass

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        return False

    finally:
        # 清理临时文件
        try:
            if os.path.exists(test_db):
                os.remove(test_db)
        except:
            pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)