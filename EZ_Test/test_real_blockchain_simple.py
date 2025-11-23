#!/usr/bin/env python3
"""
简化的真实区块链测试

避免Unicode编码问题的简化版本
"""

import sys
import os
import unittest
import tempfile
import shutil

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_Tool_Box.Hash import hash


class TestRealBlockchainSimple(unittest.TestCase):
    """简化的真实区块链测试"""

    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """测试后清理"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_real_account_creation(self):
        """测试真实账户创建"""
        print("\n测试真实账户创建...")

        # 生成真实密钥对
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        # 生成私钥
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        # 序列化为PEM格式
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        # 获取公钥
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # 生成地址
        public_hash = hash(public_pem.decode('utf-8'))
        address = f"addr_{public_hash[:16]}"

        # 创建Account实例
        account = Account(
            address=address,
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            name="test_account"
        )

        # 验证账户创建成功
        self.assertIsNotNone(account)
        self.assertEqual(account.address, address)
        self.assertEqual(account.name, "test_account")
        self.assertIsNotNone(account.value_collection)
        self.assertIsNotNone(account.signature_handler)

        print(f"账户创建成功: {address}")

        # 清理
        account.cleanup()

    def test_value_creation_and_balance(self):
        """测试Value创建和余额计算"""
        print("\n测试Value创建和余额计算...")

        # 创建账户
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        public_hash = hash(public_pem.decode('utf-8'))
        address = f"addr_{public_hash[:16]}"

        account = Account(
            address=address,
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            name="balance_test"
        )

        # 创建Value对象
        values = []
        start_index = "0x1000000000000000"

        for i in range(3):
            current_begin = hex(int(start_index, 16) + i * 1000)
            value = Value(
                beginIndex=current_begin,
                valueNum=500,
                state=ValueState.UNSPENT
            )
            values.append(value)

        # 添加Value到账户
        added_count = account.add_values(values)
        self.assertEqual(added_count, 3)

        # 验证余额
        balance = account.get_balance()
        self.assertEqual(balance, 1500)  # 3 * 500

        print(f"余额测试通过: {balance}")

        # 清理
        account.cleanup()

    def test_account_integrity(self):
        """测试账户完整性验证"""
        print("\n测试账户完整性验证...")

        # 创建账户
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        public_hash = hash(public_pem.decode('utf-8'))
        address = f"addr_{public_hash[:16]}"

        account = Account(
            address=address,
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            name="integrity_test"
        )

        # 验证完整性
        integrity = account.validate_integrity()
        self.assertTrue(integrity)

        print("完整性验证通过")

        # 清理
        account.cleanup()


def run_simple_tests():
    """运行简化测试"""
    print("=" * 60)
    print("EZchain 简化真实区块链测试")
    print("=" * 60)

    suite = unittest.TestSuite()
    suite.addTest(TestRealBlockchainSimple('test_real_account_creation'))
    suite.addTest(TestRealBlockchainSimple('test_value_creation_and_balance'))
    suite.addTest(TestRealBlockchainSimple('test_account_integrity'))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("测试结果摘要")
    print("=" * 60)
    print(f"运行测试数: {result.testsRun}")
    print(f"成功测试数: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败测试数: {len(result.failures)}")
    print(f"错误测试数: {len(result.errors)}")

    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}")

    if result.errors:
        print("\n错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}")

    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100
    print(f"\n测试成功率: {success_rate:.1f}%")

    if success_rate >= 100:
        print("所有简化测试通过！基础功能正常。")
    else:
        print("部分测试失败，需要进一步调试。")

    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_simple_tests()
    sys.exit(0 if success else 1)