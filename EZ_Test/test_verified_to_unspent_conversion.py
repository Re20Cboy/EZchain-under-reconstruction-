#!/usr/bin/env python3
"""
测试VERIFIED到UNSPENT的自动转换功能

此测试验证：
1. Value在设置为VERIFIED状态时会记录时间戳
2. 超过配置的延迟时间后，VERIFIED状态的value会自动转换为UNSPENT
3. Account离线后重新上线时，会检查并转换超时的VERIFIED values
"""

import sys
import os
import time
import unittest

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Tool_Box.SecureSignature import secure_signature_handler


class TestVerifiedToUnspentConversion(unittest.TestCase):
    """测试VERIFIED到UNSPENT的自动转换功能"""

    def setUp(self):
        """测试前准备"""
        # 创建临时数据目录
        self.temp_dir = "temp_test_verified_conversion"
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

        # 创建测试账户
        private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
        self.test_address = "0xtestverifiedconversion"

        self.account = Account(
            address=self.test_address,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            name="test_account",
            data_directory=self.temp_dir
        )

    def tearDown(self):
        """测试后清理"""
        try:
            self.account.cleanup()
        except:
            pass

        # 清理临时文件
        import shutil
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_value_verified_timestamp_recording(self):
        """测试Value在设置为VERIFIED时记录时间戳"""
        print("\n[TEST] 测试VERIFIED状态的时间戳记录...")

        # 创建一个Value
        test_value = Value("0x100", 100, ValueState.UNSPENT)

        # 检查初始状态没有时间戳
        self.assertIsNone(test_value.verified_timestamp)

        # 设置为VERIFIED状态
        test_value.set_state(ValueState.VERIFIED)

        # 检查时间戳被记录
        self.assertIsNotNone(test_value.verified_timestamp)
        self.assertIsInstance(test_value.verified_timestamp, float)

        print(f"[OK] VERIFIED时间戳已记录: {test_value.verified_timestamp}")

    def test_value_verified_timestamp_cleared_on_state_change(self):
        """测试状态从VERIFIED改变时时间戳被清除"""
        print("\n[TEST] 测试VERIFIED状态改变时清除时间戳...")

        # 创建一个VERIFIED状态的Value
        test_value = Value("0x200", 200, ValueState.VERIFIED)
        original_timestamp = test_value.verified_timestamp
        self.assertIsNotNone(original_timestamp)

        # 改变状态为UNSPENT
        test_value.set_state(ValueState.UNSPENT)

        # 检查时间戳被清除
        self.assertIsNone(test_value.verified_timestamp)

        print(f"[OK] 状态改变后时间戳已清除")

    def test_auto_convert_verified_to_unspent_after_delay(self):
        """测试超过延迟时间后自动转换为UNSPENT"""
        print("\n[TEST] 测试自动转换VERIFIED到UNSPENT...")

        # 修改Account的延迟时间为2秒（用于测试）
        original_delay = Account.VERIFIED_TO_UNSPENT_DELAY
        Account.VERIFIED_TO_UNSPENT_DELAY = 2

        try:
            # 创建一个Value并设置为VERIFIED
            test_value = Value("0x300", 300, ValueState.UNSPENT)

            # 手动添加到Account的ValueCollection
            added = self.account.vpb_manager.value_collection.add_value(test_value)
            print(f"  - Value添加到数据库: {added}")

            # 获取node_id
            node_id = self.account.vpb_manager._get_node_id_for_value(test_value)
            print(f"  - 获取node_id: {node_id}")

            # 设置为VERIFIED状态（这会记录时间戳）
            test_value.set_state(ValueState.VERIFIED)
            print(f"  - Value设置为VERIFIED，时间戳: {test_value.verified_timestamp}")

            # 更新数据库中的状态
            updated = self.account.vpb_manager.value_collection.update_value_state(node_id, ValueState.VERIFIED)
            print(f"  - 数据库状态更新: {updated}")

            # 等待超过延迟时间
            print(f"  - 等待{Account.VERIFIED_TO_UNSPENT_DELAY}秒...")
            time.sleep(Account.VERIFIED_TO_UNSPENT_DELAY + 0.5)

            # 检查并转换超时的VERIFIED values
            print(f"  - 开始检查并转换...")
            converted_count = self.account._check_and_convert_verified_to_unspent()

            print(f"  - 转换了{converted_count}个value")

            # 验证value被转换为UNSPENT
            self.assertEqual(converted_count, 1)

            # 重新从数据库获取value并检查状态
            all_values = self.account.get_values()
            verified_values = [v for v in all_values if v.is_verified()]
            unspent_values = [v for v in all_values if v.is_unspent()]

            self.assertEqual(len(verified_values), 0, "应该没有VERIFIED状态的values")
            self.assertEqual(len(unspent_values), 1, "应该有1个UNSPENT状态的value")

            print(f"[OK] Value已自动转换为UNSPENT")

        finally:
            # 恢复原始延迟时间
            Account.VERIFIED_TO_UNSPENT_DELAY = original_delay

    def test_no_conversion_before_delay(self):
        """测试在延迟时间内不转换"""
        print("\n[TEST] 测试延迟时间内不转换...")

        # 修改Account的延迟时间为10秒
        original_delay = Account.VERIFIED_TO_UNSPENT_DELAY
        Account.VERIFIED_TO_UNSPENT_DELAY = 10

        try:
            # 创建一个Value并设置为VERIFIED
            test_value = Value("0x400", 400, ValueState.UNSPENT)

            # 手动添加到Account的ValueCollection
            self.account.vpb_manager.value_collection.add_value(test_value)
            test_value.set_state(ValueState.VERIFIED)
            self.account.vpb_manager.value_collection.update_value_state(
                self.account.vpb_manager._get_node_id_for_value(test_value),
                ValueState.VERIFIED
            )

            print(f"  - Value设置为VERIFIED")
            print(f"  - 等待1秒（小于延迟时间{Account.VERIFIED_TO_UNSPENT_DELAY}秒）...")

            # 等待1秒（小于延迟时间）
            time.sleep(1)

            # 检查并转换超时的VERIFIED values
            converted_count = self.account._check_and_convert_verified_to_unspent()

            print(f"  - 转换了{converted_count}个value")

            # 验证value没有被转换
            self.assertEqual(converted_count, 0)

            # 重新从数据库获取value并检查状态
            all_values = self.account.get_values()
            verified_values = [v for v in all_values if v.is_verified()]

            self.assertEqual(len(verified_values), 1, "应该仍有1个VERIFIED状态的value")

            print(f"✓ Value在延迟时间内未转换")

        finally:
            # 恢复原始延迟时间
            Account.VERIFIED_TO_UNSPENT_DELAY = original_delay


def run_conversion_tests():
    """运行VERIFIED到UNSPENT转换测试"""
    print("=" * 60)
    print("[TEST] VERIFIED到UNSPENT自动转换功能测试")
    print("=" * 60)

    # 创建测试套件
    suite = unittest.TestSuite()
    suite.addTest(TestVerifiedToUnspentConversion('test_value_verified_timestamp_recording'))
    suite.addTest(TestVerifiedToUnspentConversion('test_value_verified_timestamp_cleared_on_state_change'))
    suite.addTest(TestVerifiedToUnspentConversion('test_auto_convert_verified_to_unspent_after_delay'))
    suite.addTest(TestVerifiedToUnspentConversion('test_no_conversion_before_delay'))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("[SUMMARY] 测试结果摘要")
    print("=" * 60)
    print(f"运行:{result.testsRun} | 成功:{result.testsRun - len(result.failures) - len(result.errors)} | 失败:{len(result.failures)} | 错误:{len(result.errors)}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_conversion_tests()
    sys.exit(0 if success else 1)
