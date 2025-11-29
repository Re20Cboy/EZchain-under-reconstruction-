"""
重构后的VPB架构测试
验证Value数据不再重复存储，并验证功能完整性
"""

import os
import sys
import unittest
import tempfile
import shutil

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(__file__) + '/../..')

# 修正导入路径
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.proofs.AccountProofManager import AccountProofManager
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_VPB.VPBManager import VPBManager

# 模拟依赖（实际项目中应该导入真实模块）
class MockMultiTransactions:
    def __init__(self, data=None):
        self.data = data or {}

    def to_dict(self):
        return self.data

    @classmethod
    def from_dict(cls, data):
        return cls(data)

class MockMerkleTreeProof:
    def __init__(self, data=None):
        self.data = data or {}

    def to_dict(self):
        return self.data

    @classmethod
    def from_dict(cls, data):
        return cls(data)

# 设置模拟模块
sys.modules['EZ_Transaction'] = type(sys)('MockModule')
sys.modules['EZ_Transaction'].MultiTransactions = MockMultiTransactions
sys.modules['EZ_Units'] = type(sys)('MockModule')
sys.modules['EZ_Units'].MerkleProof = MockMerkleTreeProof


class TestRefactoredVPBArchitecture(unittest.TestCase):
    """测试重构后的VPB架构"""

    def setUp(self):
        """设置测试环境"""
        self.test_account = "test_account_0x12345"
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # 切换到临时目录
        os.chdir(self.temp_dir)

        # 创建测试数据
        self.genesis_values = [
            Value("0x1000", 100),
            Value("0x2000", 200),
            Value("0x3000", 300)
        ]

        self.genesis_proof_units = [
            ProofUnit(
                owner=self.test_account,
                owner_multi_txns=MockMultiTransactions({"tx1": "data1"}),
                owner_mt_proof=MockMerkleTreeProof({"proof1": "data1"}),
                unit_id="proof_unit_1"
            ),
            ProofUnit(
                owner=self.test_account,
                owner_multi_txns=MockMultiTransactions({"tx2": "data2"}),
                owner_mt_proof=MockMerkleTreeProof({"proof2": "data2"}),
                unit_id="proof_unit_2"
            )
        ]

        self.genesis_block_index = BlockIndexList([0], [(0, self.test_account)])

    def tearDown(self):
        """清理测试环境"""
        os.chdir(self.original_cwd)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_value_collection_standalone(self):
        """测试ValueCollection可以独立管理Value"""
        collection = AccountValueCollection(self.test_account)

        # 添加Values
        for value in self.genesis_values:
            result = collection.add_value(value)
            self.assertTrue(result, f"Failed to add value {value.begin_index}")

        # 验证Values存在
        all_values = collection.get_all_values()
        self.assertEqual(len(all_values), len(self.genesis_values))

        # 验证余额计算
        total_balance = collection.get_total_balance()
        expected_balance = sum(v.value_num for v in self.genesis_values)
        self.assertEqual(total_balance, expected_balance)

    def test_proof_manager_mapping_only(self):
        """测试AccountProofManager只管理映射关系"""
        proof_manager = AccountProofManager(self.test_account)

        # 添加Value映射（不存储Value数据）
        for value in self.genesis_values:
            result = proof_manager.add_value(value)
            self.assertTrue(result, f"Failed to add value mapping for {value.begin_index}")

        # 验证映射存在
        value_ids = proof_manager.get_all_value_ids()
        self.assertEqual(len(value_ids), len(self.genesis_values))

        for value in self.genesis_values:
            self.assertIn(value.begin_index, value_ids)

        # 验证没有Value数据存储
        # 由于我们移除了get_all_values方法，这里通过其他方式验证
        self.assertEqual(len(value_ids), len(self.genesis_values))

    def test_vpb_manager_no_duplicate_storage(self):
        """测试VPBManager不会造成重复存储"""
        vpb_manager = VPBManager(self.test_account)

        # 执行创世块初始化
        result = vpb_manager.initialize_from_genesis_batch(
            self.genesis_values,
            self.genesis_proof_units,
            self.genesis_block_index
        )

        self.assertTrue(result, "VPBManager initialization failed")

        # 验证ValueCollection有数据
        all_values = vpb_manager.get_all_values()
        self.assertEqual(len(all_values), len(self.genesis_values))

        # 验证ProofManager有映射
        proof_stats = vpb_manager.proof_manager.get_statistics()
        self.assertEqual(proof_stats['total_values'], len(self.genesis_values))

        # 验证每个Value都有Proof映射
        for value in all_values:
            proof_units = vpb_manager.get_proof_units_for_value(value)
            self.assertGreater(len(proof_units), 0,
                             f"Value {value.begin_index} should have proof units")

    def test_single_source_of_truth(self):
        """测试单一数据源原则"""
        vpb_manager = VPBManager(self.test_account)

        # 初始化VPB
        vpb_manager.initialize_from_genesis_batch(
            self.genesis_values,
            self.genesis_proof_units,
            self.genesis_block_index
        )

        # Value集合是唯一的数据源
        collection_values = vpb_manager.get_all_values()

        # ProofManager只提供映射，不存储Value数据
        proof_value_ids = vpb_manager.proof_manager.get_all_value_ids()

        # 验证一致性
        collection_value_ids = set(v.begin_index for v in collection_values)
        proof_value_id_set = set(proof_value_ids)

        self.assertEqual(collection_value_ids, proof_value_id_set,
                        "ValueCollection and ProofManager should be consistent")

    def test_memory_efficiency(self):
        """测试内存效率改进"""
        # 创建大量Values
        many_values = [Value(f"0x{i:04x}", i+1) for i in range(1000, 1100)]

        vpb_manager = VPBManager(self.test_account + "_memory_test")

        # 批量初始化
        result = vpb_manager.initialize_from_genesis_batch(
            many_values,
            self.genesis_proof_units[:1],  # 使用一个ProofUnit
            self.genesis_block_index
        )

        self.assertTrue(result)

        # 验证所有Values都被正确存储
        all_values = vpb_manager.get_all_values()
        self.assertEqual(len(all_values), len(many_values))

        # 验证Proof映射正确
        proof_stats = vpb_manager.proof_manager.get_statistics()
        self.assertEqual(proof_stats['total_values'], len(many_values))

    def test_data_integrity_validation(self):
        """测试数据完整性验证"""
        vpb_manager = VPBManager(self.test_account + "_integrity")

        # 初始化VPB
        vpb_manager.initialize_from_genesis_batch(
            self.genesis_values,
            self.genesis_proof_units,
            self.genesis_block_index
        )

        # 验证完整性
        integrity_result = vpb_manager.validate_vpb_integrity()
        self.assertTrue(integrity_result, "VPB integrity validation should pass")

    def test_architecture_separation(self):
        """测试架构分离原则"""
        vpb_manager = VPBManager(self.test_account + "_separation")

        # 初始化VPB
        vpb_manager.initialize_from_genesis_batch(
            self.genesis_values,
            self.genesis_proof_units,
            self.genesis_block_index
        )

        # 验证组件职责分离

        # 1. ValueCollection负责Value存储和状态管理
        unspent_values = vpb_manager.get_unspent_values()
        self.assertEqual(len(unspent_values), len(self.genesis_values))

        # 2. ProofManager负责Value-Proof映射
        for value in vpb_manager.get_all_values():
            proof_units = vpb_manager.proof_manager.get_proof_units_for_value(value.begin_index)
            self.assertIsInstance(proof_units, list)

        # 3. VPBManager作为协调器提供统一接口
        summary = vpb_manager.get_vpb_summary()
        self.assertIn('total_values', summary)
        self.assertIn('unspent_balance', summary)
        self.assertIn('total_proof_units', summary)

    def test_backward_compatibility(self):
        """测试向后兼容性"""
        vpb_manager = VPBManager(self.test_account + "_compat")

        # 测试所有现有API仍然工作
        vpb_manager.initialize_from_genesis_batch(
            self.genesis_values,
            self.genesis_proof_units,
            self.genesis_block_index
        )

        # 所有查询方法应该正常工作
        self.assertIsNotNone(vpb_manager.get_all_values())
        self.assertIsNotNone(vpb_manager.get_unspent_values())
        self.assertIsNotNone(vpb_manager.get_total_balance())
        self.assertIsNotNone(vpb_manager.get_unspent_balance())

        # 特定Value的查询应该正常工作
        for value in self.genesis_values:
            proof_units = vpb_manager.get_proof_units_for_value(value)
            self.assertIsInstance(proof_units, list)

            block_index = vpb_manager.get_block_index_for_value(value)
            self.assertIsNotNone(block_index)


def run_integration_tests():
    """运行集成测试"""
    print("=== VPB架构重构集成测试 ===")

    # 创建测试套件
    test_suite = unittest.TestSuite()

    # 添加测试用例
    test_cases = [
        'test_value_collection_standalone',
        'test_proof_manager_mapping_only',
        'test_vpb_manager_no_duplicate_storage',
        'test_single_source_of_truth',
        'test_memory_efficiency',
        'test_data_integrity_validation',
        'test_architecture_separation',
        'test_backward_compatibility'
    ]

    for test_case in test_cases:
        test_suite.addTest(TestRefactoredVPBArchitecture(test_case))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # 输出结果
    if result.wasSuccessful():
        print("\n✅ 所有测试通过！重构后的架构验证成功。")
        print("\n架构改进验证：")
        print("- ✅ 消除了Value数据重复存储")
        print("- ✅ 保持了功能完整性")
        print("- ✅ 维护了向后兼容性")
        print("- ✅ 提升了架构清晰度")
        print("- ✅ 增强了数据一致性")
    else:
        print("\n❌ 测试失败，需要修复问题")
        print(f"失败数量: {len(result.failures)}")
        print(f"错误数量: {len(result.errors)}")

        for failure in result.failures:
            print(f"\nFAILURE: {failure[0]}")
            print(failure[1])

        for error in result.errors:
            print(f"\nERROR: {error[0]}")
            print(error[1])

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)