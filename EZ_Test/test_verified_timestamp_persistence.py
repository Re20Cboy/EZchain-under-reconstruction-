#!/usr/bin/env python3
"""
测试verified_timestamp的持久化功能

验证：
1. verified_timestamp被正确保存到数据库
2. Account重新初始化后能从数据库恢复verified_timestamp
3. VERIFIED到UNSPENT的自动转换在Account重启后仍能正常工作
"""

import sys
import os
import time
import shutil

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_Tool_Box.SecureSignature import secure_signature_handler


def test_verified_timestamp_persistence():
    """测试verified_timestamp的持久化"""
    print("=" * 60)
    print("[TEST] VERIFIED时间戳持久化测试")
    print("=" * 60)

    temp_dir = "temp_test_persistence"
    test_address = "0xtestpersistenceverified"

    try:
        # 清理旧的测试数据
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)

        # 第一步：创建Account并添加一个VERIFIED状态的value
        print("\n[STEP 1] 创建Account并添加VERIFIED value...")

        private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()

        account1 = Account(
            address=test_address,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            name="test_account",
            data_directory=temp_dir
        )

        # 创建一个Value并设置为VERIFIED
        test_value = Value("0x500", 500, ValueState.UNSPENT)
        added = account1.vpb_manager.value_collection.add_value(test_value)
        print(f"  - Value添加到数据库: {added}")

        node_id = account1.vpb_manager._get_node_id_for_value(test_value)
        print(f"  - node_id: {node_id}")

        # 更新数据库（这会设置VERIFIED状态和时间戳）
        updated = account1.vpb_manager.value_collection.update_value_state(node_id, ValueState.VERIFIED)
        print(f"  - 数据库状态更新: {updated}")

        # 获取更新后的value以读取时间戳
        updated_value = account1.vpb_manager.value_collection.storage.load_value(test_address, node_id)
        if updated_value and updated_value.verified_timestamp:
            original_timestamp = updated_value.verified_timestamp
            print(f"  - 设置为VERIFIED，时间戳: {original_timestamp}")
        else:
            print(f"  [FAIL] 时间戳未设置")
            return False

        # 验证数据已保存到数据库
        print(f"  - 尝试从数据库加载value...")
        saved_value = account1.vpb_manager.value_collection.storage.load_value(test_address, node_id)
        if saved_value:
            print(f"  - 从数据库加载成功")
            print(f"    状态: {saved_value.state}")
            print(f"    时间戳: {saved_value.verified_timestamp}")
            if saved_value.verified_timestamp:
                print(f"  - [OK] 数据库保存成功")
            else:
                print(f"  - [WARN] 时间戳为None，可能是数据库未迁移")
        else:
            print(f"  - [FAIL] 无法从数据库加载value")
            return False

        # 注意：不要调用cleanup()，因为它会删除数据库数据
        # 直接删除Account对象
        del account1
        print(f"  - Account对象已销毁（数据库保留）")

        # 第二步：重新创建Account，验证verified_timestamp被正确恢复
        print("\n[STEP 2] 重新创建Account，验证时间戳恢复...")

        account2 = Account(
            address=test_address,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            name="test_account_reloaded",
            data_directory=temp_dir
        )

        # 从数据库加载value（直接使用storage）
        loaded_value = account2.vpb_manager.value_collection.storage.load_value(test_address, node_id)
        if loaded_value:
            print(f"  - 从数据库加载value成功")
            print(f"  - 状态: {loaded_value.state}")
            print(f"  - 时间戳: {loaded_value.verified_timestamp}")

            if loaded_value.verified_timestamp == original_timestamp:
                print(f"  [OK] 时间戳正确恢复！")
            else:
                print(f"  [FAIL] 时间戳不匹配！原始: {original_timestamp}, 恢复: {loaded_value.verified_timestamp}")
                return False
        else:
            print(f"  [FAIL] 无法从数据库加载value")
            return False

        # 第三步：等待超时并验证自动转换
        print("\n[STEP 3] 测试Account重启后的自动转换...")

        # 修改延迟时间为2秒
        Account.VERIFIED_TO_UNSPENT_DELAY = 2
        print(f"  - 设置延迟时间为{Account.VERIFIED_TO_UNSPENT_DELAY}秒")
        print(f"  - 等待{Account.VERIFIED_TO_UNSPENT_DELAY + 0.5}秒...")

        time.sleep(Account.VERIFIED_TO_UNSPENT_DELAY + 0.5)

        # 检查并转换
        converted_count = account2._check_and_convert_verified_to_unspent()
        print(f"  - 转换了{converted_count}个value")

        if converted_count == 1:
            print(f"  [OK] Account重启后自动转换功能正常！")
        else:
            print(f"  [FAIL] Account重启后自动转换失败")
            return False

        print("\n" + "=" * 60)
        print("[SUCCESS] 所有测试通过！")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # 清理测试数据
        try:
            if 'account2' in locals():
                account2.cleanup()
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except:
            pass


if __name__ == "__main__":
    success = test_verified_timestamp_persistence()
    sys.exit(0 if success else 1)
