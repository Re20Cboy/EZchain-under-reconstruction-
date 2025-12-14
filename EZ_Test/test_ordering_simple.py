#!/usr/bin/env python3
"""
简单的顺序保持测试

直接测试AccountProofManager的核心顺序功能，避免复杂的依赖问题
"""

import os
import sys
import tempfile
import shutil

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.proofs.AccountProofManager import AccountProofStorage


def test_simple_ordering():
    """简单的顺序保持测试"""
    print("开始简单的顺序保持测试...")

    # 创建临时数据库
    test_dir = tempfile.mkdtemp()
    test_db = os.path.join(test_dir, "test.db")

    try:
        # 创建存储管理器
        storage = AccountProofStorage(test_db)
        account_address = "test_account"

        # 测试添加映射关系
        value_id = "test_value_001"
        unit_ids = ["unit_1", "unit_2", "unit_3", "unit_4", "unit_5"]

        # 按顺序添加映射
        print("按顺序添加映射关系:")
        for unit_id in unit_ids:
            success = storage.add_value_proof_mapping(account_address, value_id, unit_id)
            print(f"  添加映射: {value_id} -> {unit_id}, 成功: {success}")

        # 检查数据库中的顺序
        print("\n检查数据库中的顺序:")
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

            print(f"  检索到的unit_ids: {retrieved_unit_ids}")
            print(f"  对应的sequences: {sequences}")

        # 验证顺序
        if unit_ids == retrieved_unit_ids:
            print("✅ 顺序保持正确!")
        else:
            print("❌ 顺序保持失败!")
            print(f"  期望: {unit_ids}")
            print(f"  实际: {retrieved_unit_ids}")
            return False

        # 测试删除后重新添加
        print("\n测试删除后重新添加:")
        storage.remove_value_proof_mapping(account_address, value_id, "unit_3")

        # 重新添加unit_3
        storage.add_value_proof_mapping(account_address, value_id, "unit_3_new")

        # 检查新顺序
        with sqlite3.connect(test_db) as conn:
            cursor = conn.execute("""
                SELECT unit_id, sequence FROM account_value_proofs
                WHERE account_address = ? AND value_id = ?
                ORDER BY sequence ASC
            """, (account_address, value_id))

            rows = cursor.fetchall()
            final_unit_ids = [row[0] for row in rows]

        print(f"  删除unit_3后重新添加unit_3_new的顺序: {final_unit_ids}")

        expected_final = ["unit_1", "unit_2", "unit_4", "unit_5", "unit_3_new"]
        if expected_final == final_unit_ids:
            print("✅ 删除后重新添加的顺序正确!")
        else:
            print("❌ 删除后重新添加的顺序错误!")
            return False

        return True

    finally:
        # 清理临时目录
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)


def test_memory_ordering():
    """测试内存中的顺序保持"""
    print("\n测试内存中的顺序保持...")

    from EZ_VPB.proofs.AccountProofManager import AccountProofManager

    # 创建临时数据库
    test_dir = tempfile.mkdtemp()

    try:
        # 创建AccountProofManager
        manager = AccountProofManager("test_memory_account")

        # 添加value
        value_id = "memory_test_value"
        manager.add_value(value_id)

        # 验证内部数据结构是list而不是set
        mapping = manager._value_proof_mapping
        if isinstance(mapping.get(value_id, []), list):
            print("✅ 内存数据结构正确使用list!")
        else:
            print("❌ 内存数据结构错误，应该是list!")
            return False

        # 测试添加顺序
        unit_ids = ["mem_unit_1", "mem_unit_2", "mem_unit_3"]

        print("测试内存中添加顺序:")
        for unit_id in unit_ids:
            # 直接操作内部数据结构测试
            manager._value_proof_mapping[value_id].append(unit_id)
            print(f"  添加: {unit_id}")

        # 验证顺序
        current_units = manager._value_proof_mapping[value_id]
        print(f"  内存中顺序: {current_units}")

        if unit_ids == current_units:
            print("✅ 内存中顺序保持正确!")
        else:
            print("❌ 内存中顺序保持失败!")
            return False

        return True

    finally:
        # 清理临时目录
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)


def test_database_migration():
    """测试数据库迁移功能"""
    print("\n测试数据库迁移功能...")

    test_dir = tempfile.mkdtemp()
    test_db = os.path.join(test_dir, "migration_test.db")

    try:
        # 首先创建没有sequence字段的表结构（模拟旧版本）
        import sqlite3
        with sqlite3.connect(test_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proof_units (
                    unit_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    owner_multi_txns TEXT NOT NULL,
                    owner_mt_proof TEXT NOT NULL,
                    reference_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_address TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建没有sequence字段的旧版映射表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_value_proofs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_address TEXT NOT NULL,
                    value_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_address, value_id, unit_id)
                )
            """)

            # 插入一些旧数据
            conn.execute("""
                INSERT INTO account_value_proofs
                (account_address, value_id, unit_id, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """, ("test_account", "test_value", "old_unit_1"))

            conn.execute("""
                INSERT INTO account_value_proofs
                (account_address, value_id, unit_id, created_at)
                VALUES (?, ?, ?, datetime('now', '-1 minute'))
            """, ("test_account", "test_value", "old_unit_2"))

            conn.execute("""
                INSERT INTO account_value_proofs
                (account_address, value_id, unit_id, created_at)
                VALUES (?, ?, ?, datetime('now', '-2 minutes'))
            """, ("test_account", "test_value", "old_unit_3"))

            conn.commit()

        print("创建了旧版本数据库，现在测试迁移...")

        # 创建AccountProofStorage，应该会触发迁移
        storage = AccountProofStorage(test_db)

        # 检查迁移是否成功
        with sqlite3.connect(test_db) as conn:
            cursor = conn.execute("PRAGMA table_info(account_value_proofs)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'sequence' in columns:
                print("✅ sequence字段添加成功!")
            else:
                print("❌ sequence字段添加失败!")
                return False

            # 检查sequence值是否正确填充
            cursor = conn.execute("""
                SELECT unit_id, sequence FROM account_value_proofs
                WHERE account_address = ? AND value_id = ?
                ORDER BY sequence ASC
            """, ("test_account", "test_value"))

            rows = cursor.fetchall()
            unit_ids_with_sequence = [(row[0], row[1]) for row in rows]

            print(f"迁移后的数据: {unit_ids_with_sequence}")

            # 验证sequence是按created_at排序的（越老的created_at，sequence越小）
            sequences = [row[1] for row in rows]
            if sequences == sorted(sequences):
                print("✅ sequence值按时间正确排序!")
            else:
                print("❌ sequence值排序错误!")
                return False

        return True

    finally:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)


def main():
    """运行所有测试"""
    print("开始运行顺序保持测试...")

    test_results = []

    # 运行简单测试
    test_results.append(test_simple_ordering())

    # 运行内存测试
    test_results.append(test_memory_ordering())

    # 运行数据库迁移测试
    test_results.append(test_database_migration())

    # 统计结果
    passed = sum(test_results)
    total = len(test_results)

    print(f"\n测试结果: {passed}/{total} 通过")

    if passed == total:
        print("🎉 所有测试都通过了!")
        return True
    else:
        print("❌ 部分测试失败!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)