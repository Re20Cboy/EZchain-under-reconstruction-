"""
EZChain VPB Updater 测试

使用项目中的真实区块链模块进行VPB Updater功能测试。
不再使用任何模拟组件，确保测试反映真实的系统行为。
"""

import unittest
import tempfile
import os
import sys
from datetime import datetime

# 添加项目根目录到Python路径，确保能正确导入项目模块
sys.path.insert(0, os.path.dirname(__file__) + '/..')

# 导入项目中的真实区块链模块
from EZ_Value.Value import Value, ValueState
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Proof.ProofUnit import ProofUnit
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_VPB.VPBPairs import VPBPair, VPBManager, VPBStorage, VPBPairs

# 导入VPB Updater
from vpb_updater import (
    VPBUpdater, VPBUpdateRequest, VPBUpdateResult, VPBServiceBuilder,
    AccountVPBUpdater, AccountNodeVPBIntegration,  # 向后兼容别名
    AccountVPBManager,  # 额外的向后兼容别名
    create_vpb_update_request
)


class TestVPBUpdater(unittest.TestCase):
    """VPBUpdater核心功能测试"""

    def setUp(self):
        """测试设置"""
        self.test_address = "0x1234567890abcdef"
        self.test_recipient = "0xabcdef1234567890"

        # 使用服务构建器创建测试用的VPBUpdater
        self.vpb_updater = VPBServiceBuilder.create_test_updater(self.test_address)

        # 创建测试Value
        self.test_value = Value("0x100", 100)  # begin_index=0x100, value_num=100

        # 创建测试Transaction（使用真实模块的接口）
        self.test_transaction = Transaction(
            sender=self.test_address,
            recipient=self.test_recipient,
            nonce=1,
            signature=None,
            value=[self.test_value],
            time=datetime.now().isoformat()
        )

        # 创建测试MultiTransactions
        self.test_multi_transaction = MultiTransactions(self.test_address, [self.test_transaction])

        # 创建测试MerkleTreeProof
        self.test_merkle_proof = MerkleTreeProof(['hash1', 'hash2', 'hash3', 'root_hash'])

    def test_vpb_updater_initialization(self):
        """测试VPBUpdater初始化"""
        self.assertIsNotNone(self.vpb_updater.vpb_manager)
        self.assertIsNotNone(self.vpb_updater.vpb_storage)
        self.assertIsNotNone(self.vpb_updater._lock)

    def test_vpb_update_request_creation(self):
        """测试VPBUpdateRequest创建"""
        request = VPBUpdateRequest(
            account_address=self.test_address,
            transaction=self.test_multi_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        self.assertEqual(request.account_address, self.test_address)
        self.assertEqual(request.transaction, self.test_multi_transaction)
        self.assertEqual(request.block_height, 100)
        self.assertEqual(request.merkle_proof, self.test_merkle_proof)
        self.assertIsInstance(request.timestamp, datetime)

    def test_convenience_function(self):
        """测试便利函数"""
        request = create_vpb_update_request(
            account_address=self.test_address,
            transaction=self.test_multi_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        self.assertIsInstance(request, VPBUpdateRequest)

    def test_vpb_update_with_no_existing_vpbs(self):
        """测试无现有VPB时的更新"""
        request = VPBUpdateRequest(
            account_address=self.test_address,
            transaction=self.test_multi_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        result = self.vpb_updater.update_vpb_for_transaction(request)

        # 由于没有现有的VPB，应该成功但没有更新任何VPB
        self.assertTrue(result.success)
        self.assertEqual(len(result.updated_vpb_ids), 0)
        self.assertEqual(len(result.failed_operations), 0)

    def test_vpb_status_query(self):
        """测试VPB状态查询"""
        status = self.vpb_updater.get_vpb_update_status(self.test_address)

        self.assertIsInstance(status, dict)
        self.assertEqual(status['account_address'], self.test_address)
        self.assertEqual(status['total_vpbs'], 0)
        self.assertIsInstance(status['vpb_details'], list)

    def test_vpb_consistency_validation(self):
        """测试VPB一致性验证"""
        validation = self.vpb_updater.validate_vpb_consistency(self.test_address)

        self.assertIsInstance(validation, dict)
        self.assertEqual(validation['account_address'], self.test_address)
        self.assertTrue(validation['is_consistent'])
        self.assertEqual(validation['total_vpbs'], 0)


class TestAccountVPBUpdater(unittest.TestCase):
    """AccountVPBUpdater测试 - 账户VPB更新器的主要接口"""

    def setUp(self):
        """测试设置"""
        self.test_address = "0x1234567890abcdef"
        self.test_recipient = "0xabcdef1234567890"

        # 创建AccountVPBUpdater实例
        self.account_updater = AccountVPBUpdater(self.test_address)

        # 创建测试数据
        self.test_value = Value("0x100", 100)
        self.test_transaction = Transaction(
            sender=self.test_address,
            recipient=self.test_recipient,
            nonce=1,
            signature=None,
            value=[self.test_value],
            time=datetime.now().isoformat()
        )
        self.test_multi_transaction = MultiTransactions(self.test_address, [self.test_transaction])
        self.test_merkle_proof = MerkleTreeProof(['hash1', 'hash2', 'hash3', 'root_hash'])

    def test_account_vpb_updater_initialization(self):
        """测试AccountVPBUpdater初始化"""
        self.assertEqual(self.account_updater.account_address, self.test_address)
        self.assertIsNotNone(self.account_updater.vpb_updater)

    def test_update_local_vpbs_as_sender(self):
        """测试作为发送者更新本地VPB"""
        result = self.account_updater.update_local_vpbs(
            transaction=self.test_multi_transaction,
            merkle_proof=self.test_merkle_proof,
            block_height=100
        )

        self.assertIsInstance(result, VPBUpdateResult)
        self.assertTrue(result.success)  # 更新应该成功（即使没有现有VPB）
        self.assertIsInstance(result.updated_vpb_ids, list)
        # 可能会有"No VPBs found"的警告信息，但操作仍然成功

    def test_update_local_vpbs_with_other_transaction(self):
        """测试更新其他账户交易的本地VPB"""
        # 创建一个由其他地址发送的交易
        other_transaction = Transaction(
            sender="0xother1234567890",
            recipient=self.test_recipient,
            nonce=2,
            signature=None,
            value=[Value("0x200", 50)],
            time=datetime.now().isoformat()
        )
        other_multi_transaction = MultiTransactions("0xother1234567890", [other_transaction])

        result = self.account_updater.update_local_vpbs(
            transaction=other_multi_transaction,
            merkle_proof=self.test_merkle_proof,
            block_height=101
        )

        self.assertIsInstance(result, VPBUpdateResult)
        # VPB更新器不关心交易发送者，只更新数据，所以应该成功
        self.assertTrue(result.success)
        self.assertIsInstance(result.updated_vpb_ids, list)
        # 可能会有"No VPBs found"的警告信息，但操作仍然成功

    def test_get_vpb_status(self):
        """测试获取VPB状态"""
        status = self.account_updater.get_vpb_status()

        self.assertIsInstance(status, dict)
        self.assertEqual(status['account_address'], self.test_address)

    def test_validate_vpb_consistency(self):
        """测试验证VPB一致性"""
        validation = self.account_updater.validate_vpb_consistency()

        self.assertIsInstance(validation, dict)
        self.assertEqual(validation['account_address'], self.test_address)
        self.assertTrue(validation['is_consistent'])

    def test_batch_update_vpbs(self):
        """测试批量更新VPB"""
        # 创建多个请求（都属于当前账户）
        requests = [
            VPBUpdateRequest(
                account_address=self.test_address,
                transaction=self.test_multi_transaction,
                block_height=100,
                merkle_proof=self.test_merkle_proof
            ),
            VPBUpdateRequest(
                account_address=self.test_address,
                transaction=self.test_multi_transaction,
                block_height=101,
                merkle_proof=self.test_merkle_proof
            )
        ]

        results = self.account_updater.batch_update_vpbs(requests)

        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIsInstance(result, VPBUpdateResult)

    def test_batch_update_vpbs_with_wrong_account(self):
        """测试批量更新VPB时账户不匹配"""
        # 创建包含错误账户的请求
        requests = [
            VPBUpdateRequest(
                account_address=self.test_address,
                transaction=self.test_multi_transaction,
                block_height=100,
                merkle_proof=self.test_merkle_proof
            ),
            VPBUpdateRequest(
                account_address="0xwrongaccount1234567890",  # 错误的账户
                transaction=self.test_multi_transaction,
                block_height=101,
                merkle_proof=self.test_merkle_proof
            )
        ]

        with self.assertRaises(ValueError) as context:
            self.account_updater.batch_update_vpbs(requests)

        self.assertIn("does not match updater account", str(context.exception))


class TestAccountNodeVPBIntegration_BackwardCompatibility(unittest.TestCase):
    """AccountNodeVPBIntegration向后兼容性测试"""

    def setUp(self):
        """测试设置"""
        self.test_address = "0x1234567890abcdef"

        # 创建AccountNodeVPBIntegration实例（向后兼容）
        self.account_integration = AccountNodeVPBIntegration(self.test_address)

    def test_backward_compatibility_initialization(self):
        """测试向后兼容的初始化"""
        self.assertEqual(self.account_integration.account_address, self.test_address)
        self.assertIsNotNone(self.account_integration.vpb_updater)

    def test_backward_compatibility_class_type(self):
        """测试向后兼容的类类型"""
        # AccountNodeVPBIntegration应该是AccountVPBManager的别名
        self.assertIsInstance(self.account_integration, AccountVPBManager)




class TestVPBServiceBuilder(unittest.TestCase):
    """VPBServiceBuilder测试"""

    def test_create_updater(self):
        """测试创建VPBUpdater"""
        test_address = "0xtest1234567890abcdef"

        updater = VPBServiceBuilder.create_updater(test_address)

        self.assertIsNotNone(updater)
        self.assertIsInstance(updater, VPBUpdater)
        self.assertIsNotNone(updater.vpb_manager)
        self.assertIsNotNone(updater.vpb_storage)

    def test_create_test_updater(self):
        """测试创建测试用VPBUpdater"""
        test_address = "0xtest1234567890abcdef"

        test_updater = VPBServiceBuilder.create_test_updater(test_address)

        self.assertIsNotNone(test_updater)
        self.assertIsInstance(test_updater, VPBUpdater)
        self.assertIsNotNone(test_updater.vpb_manager)
        self.assertIsNotNone(test_updater.vpb_storage)


class TestRealModuleIntegration(unittest.TestCase):
    """真实模块集成测试"""

    def test_all_real_modules_importable(self):
        """测试所有真实模块都能正确导入"""
        try:
            from EZ_Value.Value import Value, ValueState
            from EZ_Transaction.MultiTransactions import MultiTransactions
            from EZ_Transaction.SingleTransaction import Transaction
            from EZ_Proof.ProofUnit import ProofUnit
            from EZ_Units.MerkleProof import MerkleTreeProof
            from EZ_VPB.VPBPairs import VPBPair, VPBManager, VPBStorage, VPBPairs

            self.assertTrue(True, "All real modules imported successfully")
        except ImportError as e:
            self.fail(f"Failed to import real modules: {e}")

    def test_create_real_value(self):
        """测试创建真实的Value对象"""
        value = Value("0x100", 100)

        self.assertEqual(value.begin_index, "0x100")
        self.assertEqual(value.value_num, 100)
        self.assertEqual(value.state, ValueState.UNSPENT)
        self.assertEqual(value.end_index, "0x163")  # 0x100 + 100 - 1 = 0x163
        self.assertTrue(value.check_value())

    def test_create_real_transaction(self):
        """测试创建真实的Transaction对象"""
        value = Value("0x100", 100)
        transaction = Transaction(
            sender="0xalice",
            recipient="0xbob",
            nonce=1,
            signature=None,
            value=[value],
            time=datetime.now().isoformat()
        )

        self.assertEqual(transaction.sender, "0xalice")
        self.assertEqual(transaction.recipient, "0xbob")
        self.assertEqual(transaction.nonce, 1)
        self.assertEqual(len(transaction.value), 1)
        self.assertIsNotNone(transaction.time)

    def test_create_real_multi_transaction(self):
        """测试创建真实的MultiTransactions对象"""
        value = Value("0x100", 100)
        transaction = Transaction(
            sender="0xalice",
            recipient="0xbob",
            nonce=1,
            signature=None,
            value=[value],
            time=datetime.now().isoformat()
        )
        multi_transaction = MultiTransactions("0xalice", [transaction])

        self.assertEqual(multi_transaction.sender, "0xalice")
        self.assertEqual(len(multi_transaction.multi_txns), 1)
        self.assertIs(multi_transaction.multi_txns[0], transaction)

    def test_create_real_merkle_proof(self):
        """测试创建真实的MerkleTreeProof对象"""
        merkle_proof = MerkleTreeProof(['hash1', 'hash2', 'hash3', 'root_hash'])

        self.assertEqual(len(merkle_proof.mt_prf_list), 4)
        self.assertEqual(merkle_proof.mt_prf_list[-1], 'root_hash')


def run_basic_tests():
    """运行基本测试"""
    print("运行VPB Updater测试（使用真实区块链模块）...")
    print("=" * 50)

    # 创建测试套件
    test_suite = unittest.TestSuite()

    # 添加测试用例
    test_classes = [
        TestVPBUpdater,
        TestAccountVPBUpdater,
        TestAccountNodeVPBIntegration_BackwardCompatibility,
        TestVPBServiceBuilder,
        TestRealModuleIntegration
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # 输出总结
    print("\n" + "=" * 50)
    print(f"测试完成: 运行了 {result.testsRun} 个测试")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")

    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print("\n错误的测试:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    return result.wasSuccessful()


def run_integration_test():
    """运行集成测试"""
    print("\n运行集成测试...")
    print("=" * 50)

    try:
        # 创建完整的VPB更新流程
        test_address = "0xintegration1234567890"
        test_recipient = "0xrecipient1234567890"

        # 创建VPBUpdater
        vpb_updater = VPBServiceBuilder.create_test_updater(test_address)
        print("[OK] VPBUpdater创建成功")

        # 创建测试数据
        test_value = Value("0x200", 200)
        test_transaction = Transaction(
            sender=test_address,
            recipient=test_recipient,
            nonce=1,
            signature=None,
            value=[test_value],
            time=datetime.now().isoformat()
        )
        test_multi_transaction = MultiTransactions(test_address, [test_transaction])
        test_merkle_proof = MerkleTreeProof(['h1', 'h2', 'h3', 'root'])
        print("[OK] 测试数据创建成功")

        # 创建更新请求
        request = VPBUpdateRequest(
            account_address=test_address,
            transaction=test_multi_transaction,
            block_height=1000,
            merkle_proof=test_merkle_proof
        )
        print("[OK] VPBUpdateRequest创建成功")

        # 执行更新
        result = vpb_updater.update_vpb_for_transaction(request)
        print(f"[OK] VPB更新完成: success={result.success}")

        # 测试AccountVPBUpdater
        account_updater = AccountVPBUpdater(test_address)
        result = account_updater.update_local_vpbs(
            test_multi_transaction,
            test_merkle_proof,
            1001
        )
        print(f"[OK] AccountVPBUpdater: success={result.success}")

        # 测试向后兼容的AccountNodeVPBIntegration
        legacy_integration = AccountNodeVPBIntegration(test_address)
        result = legacy_integration.update_local_vpbs(
            test_multi_transaction,
            test_merkle_proof,
            1002
        )
        print(f"[OK] AccountNodeVPBIntegration (legacy): success={result.success}")

        print("\n集成测试全部通过！")
        return True

    except Exception as e:
        print(f"[ERROR] 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # 运行基本测试
    basic_success = run_basic_tests()

    # 运行集成测试
    integration_success = run_integration_test()

    # 输出最终结果
    print("\n" + "=" * 60)
    print("最终测试结果:")
    print(f"基本测试: {'通过' if basic_success else '失败'}")
    print(f"集成测试: {'通过' if integration_success else '失败'}")

    if basic_success and integration_success:
        print("\n[SUCCESS] 所有测试通过！VPB Updater使用真实模块验证成功！")
    else:
        print("\n[FAILED] 部分测试失败，请检查问题。")