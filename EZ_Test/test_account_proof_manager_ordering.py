#!/usr/bin/env python3
"""
AccountProofManager顺序保持测试

测试修改后的AccountProofManager是否能正确保持proof unit的添加顺序
"""

import os
import sys
import unittest
import tempfile
import shutil

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_VPB.proofs.AccountProofManager import AccountProofManager, AccountProofStorage
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof


class TestAccountProofManagerOrdering(unittest.TestCase):
    """测试AccountProofManager的顺序保持功能"""

    def setUp(self):
        """设置测试环境"""
        # 创建临时数据库文件
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_account_proof_storage.db")

        # 创建测试账户地址
        self.test_account = "test_account_0x12345"

        # 初始化AccountProofManager
        self.proof_manager = AccountProofManager(self.test_account)

        # 创建模拟的ProofUnit用于测试
        self.create_mock_proof_units()

    def tearDown(self):
        """清理测试环境"""
        # 删除临时目录
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def create_mock_proof_units(self):
        """创建模拟的ProofUnit用于测试"""
        self.mock_proof_units = []

        for i in range(5):
            # 创建模拟的MultiTransactions和MerkleTreeProof
            mock_multi_txns = self._create_mock_multi_transactions(f"owner_{i}")
            mock_mt_proof = self._create_mock_merkle_proof(f"proof_{i}")

            proof_unit = ProofUnit(
                owner=f"owner_{i}",
                owner_multi_txns=mock_multi_txns,
                owner_mt_proof=mock_mt_proof,
                unit_id=f"unit_{i}"
            )

            self.mock_proof_units.append(proof_unit)

    def _create_mock_multi_transactions(self, owner: str):
        """创建模拟的MultiTransactions"""
        # 创建一个简单的模拟对象
        class MockMultiTransactions:
            def __init__(self, owner):
                self.owner = owner

            def to_dict(self):
                return {"owner": self.owner, "type": "mock_multi_txns"}

            @classmethod
            def from_dict(cls, data):
                return cls(data["owner"])

        return MockMultiTransactions(owner)

    def _create_mock_merkle_proof(self, proof_id: str):
        """创建模拟的MerkleTreeProof"""
        # 创建一个简单的模拟对象
        class MockMerkleTreeProof:
            def __init__(self, proof_id):
                self.proof_id = proof_id

            def to_dict(self):
                return {"proof_id": self.proof_id, "type": "mock_merkle_proof"}

            @classmethod
            def from_dict(cls, data):
                return cls(data["proof_id"])

        return MockMerkleTreeProof(proof_id)

    def test_proof_units_order_preservation(self):
        """测试proof unit的顺序是否正确保持"""
        print("\n=== 测试proof unit顺序保持 ===")

        # 添加测试value
        test_value_id = "test_value_node_001"
        self.assertTrue(self.proof_manager.add_value(test_value_id))

        # 按顺序添加proof units
        added_units = []
        for i, proof_unit in enumerate(self.mock_proof_units):
            print(f"添加第{i+1}个proof unit: {proof_unit.unit_id}")
            success = self.proof_manager.add_proof_unit_optimized(test_value_id, proof_unit)
            self.assertTrue(success)
            added_units.append(proof_unit.unit_id)

        # 获取该value的所有proof units
        retrieved_proofs = self.proof_manager.get_proof_units_for_value(test_value_id)
        retrieved_unit_ids = [proof.unit_id for proof in retrieved_proofs]

        print(f"添加顺序: {added_units}")
        print(f"检索顺序: {retrieved_unit_ids}")

        # 验证顺序是否一致
        self.assertEqual(added_units, retrieved_unit_ids,
                        "检索到的proof unit顺序应该与添加顺序一致")

    def test_multiple_values_order_isolation(self):
        """测试不同value之间的顺序隔离"""
        print("\n=== 测试多个value的顺序隔离 ===")

        # 添加两个不同的value
        value1_id = "test_value_node_001"
        value2_id = "test_value_node_002"

        self.assertTrue(self.proof_manager.add_value(value1_id))
        self.assertTrue(self.proof_manager.add_value(value2_id))

        # 为value1添加proof units
        value1_units = []
        for i in range(3):
            proof_unit = self.mock_proof_units[i]
            self.proof_manager.add_proof_unit_optimized(value1_id, proof_unit)
            value1_units.append(proof_unit.unit_id)

        # 为value2添加proof units
        value2_units = []
        for i in range(2, 5):
            proof_unit = self.mock_proof_units[i]
            self.proof_manager.add_proof_unit_optimized(value2_id, proof_unit)
            value2_units.append(proof_unit.unit_id)

        # 分别获取两个value的proof units并验证顺序
        value1_proofs = self.proof_manager.get_proof_units_for_value(value1_id)
        value1_retrieved = [proof.unit_id for proof in value1_proofs]

        value2_proofs = self.proof_manager.get_proof_units_for_value(value2_id)
        value2_retrieved = [proof.unit_id for proof in value2_proofs]

        print(f"Value1添加顺序: {value1_units}")
        print(f"Value1检索顺序: {value1_retrieved}")
        print(f"Value2添加顺序: {value2_units}")
        print(f"Value2检索顺序: {value2_retrieved}")

        self.assertEqual(value1_units, value1_retrieved)
        self.assertEqual(value2_units, value2_retrieved)

    def test_batch_add_proof_units_order(self):
        """测试批量添加proof units时的顺序保持"""
        print("\n=== 测试批量添加proof units顺序 ===")

        test_value_id = "test_value_batch_001"
        self.assertTrue(self.proof_manager.add_value(test_value_id))

        # 准备批量添加的数据
        value_proof_pairs = []
        expected_order = []

        for i, proof_unit in enumerate(self.mock_proof_units):
            value_proof_pairs.append((test_value_id, proof_unit))
            expected_order.append(proof_unit.unit_id)

        # 批量添加
        success = self.proof_manager.batch_add_proof_units(value_proof_pairs)
        self.assertTrue(success)

        # 验证顺序
        retrieved_proofs = self.proof_manager.get_proof_units_for_value(test_value_id)
        retrieved_order = [proof.unit_id for proof in retrieved_proofs]

        print(f"批量添加顺序: {expected_order}")
        print(f"批量检索顺序: {retrieved_order}")

        self.assertEqual(expected_order, retrieved_order)

    def test_persistence_order_preservation(self):
        """测试持久化后顺序是否保持"""
        print("\n=== 测试持久化顺序保持 ===")

        test_value_id = "test_value_persistence_001"

        # 第一个manager实例：添加数据
        manager1 = AccountProofManager(self.test_account)
        manager1.add_value(test_value_id)

        added_units = []
        for proof_unit in self.mock_proof_units:
            manager1.add_proof_unit_optimized(test_value_id, proof_unit)
            added_units.append(proof_unit.unit_id)

        # 创建新的manager实例（模拟重启）
        manager2 = AccountProofManager(self.test_account)

        # 验证数据是否正确加载且顺序保持
        retrieved_proofs = manager2.get_proof_units_for_value(test_value_id)
        retrieved_order = [proof.unit_id for proof in retrieved_proofs]

        print(f"原始添加顺序: {added_units}")
        print(f"持久化后顺序: {retrieved_order}")

        self.assertEqual(added_units, retrieved_order)

    def test_remove_and_add_order(self):
        """测试删除后重新添加的顺序行为"""
        print("\n=== 测试删除后重新添加的顺序 ===")

        test_value_id = "test_value_remove_add_001"
        self.assertTrue(self.proof_manager.add_value(test_value_id))

        # 添加初始proof units
        initial_units = []
        for i in range(3):
            proof_unit = self.mock_proof_units[i]
            self.proof_manager.add_proof_unit_optimized(test_value_id, proof_unit)
            initial_units.append(proof_unit.unit_id)

        # 移除中间的proof unit
        removed_unit = self.mock_proof_units[1].unit_id
        self.proof_manager.remove_value_proof_mapping(test_value_id, removed_unit)

        # 添加新的proof unit
        new_proof_unit = self.mock_proof_units[3]
        self.proof_manager.add_proof_unit_optimized(test_value_id, new_proof_unit)

        # 验证最终顺序
        retrieved_proofs = self.proof_manager.get_proof_units_for_value(test_value_id)
        final_order = [proof.unit_id for proof in retrieved_proofs]

        expected_order = [self.mock_proof_units[0].unit_id,
                         self.mock_proof_units[2].unit_id,
                         self.mock_proof_units[3].unit_id]

        print(f"初始顺序: {initial_units}")
        print(f"移除: {removed_unit}")
        print(f"添加新: {new_proof_unit.unit_id}")
        print(f"最终顺序: {final_order}")
        print(f"期望顺序: {expected_order}")

        self.assertEqual(final_order, expected_order)

    def test_database_migration_order_preservation(self):
        """测试数据库迁移时顺序保持"""
        print("\n=== 测试数据库迁移顺序保持 ===")

        # 这里我们主要测试新增的sequence字段是否正确工作
        # 由于已经使用了sequence字段，这个测试主要是验证没有兼容性问题

        test_value_id = "test_migration_001"
        self.assertTrue(self.proof_manager.add_value(test_value_id))

        # 添加一些proof units
        for proof_unit in self.mock_proof_units[:3]:
            self.proof_manager.add_proof_unit_optimized(test_value_id, proof_unit)

        # 验证能够正常检索
        retrieved_proofs = self.proof_manager.get_proof_units_for_value(test_value_id)
        self.assertEqual(len(retrieved_proofs), 3)

        # 验证检索顺序就是添加顺序
        retrieved_order = [proof.unit_id for proof in retrieved_proofs]
        expected_order = [proof.unit_id for proof in self.mock_proof_units[:3]]

        self.assertEqual(retrieved_order, expected_order)
        print("数据库迁移测试通过，sequence字段正常工作")

    def test_all_proof_units_order(self):
        """测试获取所有proof units时的顺序"""
        print("\n=== 测试所有proof units顺序 ===")

        # 添加多个values
        value1_id = "value_all_001"
        value2_id = "value_all_002"

        self.proof_manager.add_value(value1_id)
        self.proof_manager.add_value(value2_id)

        # 为不同的values添加proof units
        for i in range(3):
            self.proof_manager.add_proof_unit_optimized(value1_id, self.mock_proof_units[i])

        for i in range(2, 5):
            self.proof_manager.add_proof_unit_optimized(value2_id, self.mock_proof_units[i])

        # 获取所有proof units
        all_proofs = self.proof_manager.get_all_proof_units()

        # 验证顺序：应该按value_id和sequence排序
        value1_proofs = [pair for pair in all_proofs if pair[0] == value1_id]
        value2_proofs = [pair for pair in all_proofs if pair[0] == value2_id]

        value1_order = [proof.unit_id for _, proof in value1_proofs]
        value2_order = [proof.unit_id for _, proof in value2_proofs]

        expected_value1_order = [self.mock_proof_units[i].unit_id for i in range(3)]
        expected_value2_order = [self.mock_proof_units[i].unit_id for i in range(2, 5)]

        print(f"Value1所有proofs顺序: {value1_order}")
        print(f"Value2所有proofs顺序: {value2_order}")

        self.assertEqual(value1_order, expected_value1_order)
        self.assertEqual(value2_order, expected_value2_order)


def run_ordering_tests():
    """运行顺序测试"""
    print("开始AccountProofManager顺序保持测试...")

    # 创建测试套件
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAccountProofManagerOrdering)

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出测试结果
    if result.wasSuccessful():
        print("\n✅ 所有顺序保持测试通过！")
    else:
        print(f"\n❌ 测试失败: {len(result.failures)} 个失败, {len(result.errors)} 个错误")

        for test, error in result.failures + result.errors:
            print(f"失败的测试: {test}")
            print(f"错误信息: {error}")

    return result.wasSuccessful()


if __name__ == "__main__":
    run_ordering_tests()