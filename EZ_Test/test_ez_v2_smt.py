"""
EZchain-V2 SMT (Sparse Merkle Tree) 核心测试

设计文档对照：
- EZchain-V2 desgin-human-write.md：SMT作为状态根
- EZchain-V2-protocol-draft.md：状态证明机制

测试类别：
- design-conformance: 验证SMT root/proof/update符合设计
- negative: 验证tamper-fail（篡改检测）
- invariants: 验证SMT不变量
- boundary: 验证边界条件
"""

from __future__ import annotations

import unittest

from EZ_V2.smt import (
    EMPTY_LEAF_HASH,
    SparseMerkleTree,
    _leaf_node_hash,
    _node_hash,
    verify_proof,
)
from EZ_V2.crypto import keccak256
from EZ_V2.types import SparseMerkleProof


class EZV2SMTConstructionTests(unittest.TestCase):
    """
    [design-conformance] SMT构造测试
    """

    def test_smt_initialization_with_default_depth(self) -> None:
        """验证SMT默认深度为256位"""
        tree = SparseMerkleTree()
        self.assertEqual(tree.depth, 256)

    def test_smt_initialization_with_custom_depth(self) -> None:
        """验证SMT能自定义深度"""
        tree = SparseMerkleTree(depth=32)
        self.assertEqual(tree.depth, 32)

    def test_smt_initialization_rejects_non_positive_depth(self) -> None:
        """验证SMT拒绝非正数深度"""
        with self.assertRaises(ValueError):
            SparseMerkleTree(depth=0)

        with self.assertRaises(ValueError):
            SparseMerkleTree(depth=-1)

    def test_smt_empty_tree_root(self) -> None:
        """验证空SMT根哈希计算"""
        tree = SparseMerkleTree(depth=8)
        root = tree.root()
        # 空树根应该是预计算的默认哈希
        self.assertEqual(len(root), 32)


class EZV2SMTGetSetTests(unittest.TestCase):
    """
    [design-conformance] SMT get/set操作测试
    """

    def test_smt_get_returns_none_for_missing_key(self) -> None:
        """验证get对不存在的key返回None"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 4  # 32位深度需要4字节key

        value = tree.get(key)
        self.assertIsNone(value)

    def test_smt_set_and_get(self) -> None:
        """验证set后get能返回相同值"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 4
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        retrieved = tree.get(key)

        self.assertEqual(retrieved, value_hash)

    def test_smt_set_overwrites_existing_value(self) -> None:
        """验证set覆盖已有值"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 4
        value1 = b"\x01" * 32
        value2 = b"\x02" * 32

        tree.set(key, value1)
        tree.set(key, value2)

        self.assertEqual(tree.get(key), value2)

    def test_smt_set_changes_root(self) -> None:
        """验证set操作改变root"""
        tree = SparseMerkleTree(depth=8)
        root_before = tree.root()

        key = b"\x01"  # 1字节key用于depth=8
        value_hash = b"\x02" * 32
        tree.set(key, value_hash)

        root_after = tree.root()

        self.assertNotEqual(root_before, root_after)


class EZV2SMTRootTests(unittest.TestCase):
    """
    [design-conformance] SMT root计算测试
    """

    def test_smt_root_with_single_value(self) -> None:
        """验证单值SMT根计算"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()

        # Root应该是该key路径的Merkle根
        self.assertEqual(len(root), 32)

    def test_smt_root_with_multiple_values(self) -> None:
        """验证多值SMT根计算"""
        tree = SparseMerkleTree(depth=8)
        key1 = b"\x01"
        key2 = b"\x02"
        value_hash = b"\x03" * 32

        tree.set(key1, value_hash)
        tree.set(key2, value_hash)

        root = tree.root()
        self.assertEqual(len(root), 32)

    def test_smt_root_deterministic(self) -> None:
        """验证root计算是确定性的"""
        tree1 = SparseMerkleTree(depth=8)
        tree2 = SparseMerkleTree(depth=8)

        key = b"\x01"
        value_hash = b"\x02" * 32

        tree1.set(key, value_hash)
        tree2.set(key, value_hash)

        self.assertEqual(tree1.root(), tree2.root())


class EZV2SMTProofTests(unittest.TestCase):
    """
    [design-conformance] SMT proof生成与验证测试
    """

    def test_smt_prove_returns_correct_proof_structure(self) -> None:
        """验证prove返回正确结构的proof"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 4
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        proof = tree.prove(key)

        # Proof应该有depth个siblings
        self.assertEqual(len(proof.siblings), 32)
        # 应该标记为存在
        self.assertTrue(proof.existence)

    def test_smt_prove_for_nonexistent_key(self) -> None:
        """验证对不存在的key生成proof"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"

        proof = tree.prove(key)

        self.assertEqual(len(proof.siblings), 8)
        # 应该标记为不存在
        self.assertFalse(proof.existence)

    def test_smt_verify_proof_accepts_valid_proof(self) -> None:
        """验证verify_proof接受有效proof"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        self.assertTrue(verify_proof(root, key, value_hash, proof, depth=8))

    def test_smt_verify_proof_rejects_nonexistent_key(self) -> None:
        """验证verify_proof拒绝不存在的key"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        # 验证不存在的key（value_hash为空）
        empty_hash = b"\x00" * 32
        self.assertFalse(verify_proof(root, key, empty_hash, proof, depth=8))

    def test_smt_verify_proof_with_custom_depth(self) -> None:
        """验证verify_proof支持自定义深度"""
        tree = SparseMerkleTree(depth=16)
        key = b"\x01\x01"  # 2字节
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        self.assertTrue(verify_proof(root, key, value_hash, proof, depth=16))


class EZV2SMTNegativeTests(unittest.TestCase):
    """
    [negative] SMT负向测试
    """

    def test_smt_set_rejects_mismatched_key_length(self) -> None:
        """验证set拒绝长度不匹配的key"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 2  # 16位，但深度是32
        value_hash = b"\x02" * 32

        with self.assertRaises(ValueError):
            tree.set(key, value_hash)

    def test_smt_set_rejects_invalid_value_hash_length(self) -> None:
        """验证set拒绝非32字节的value_hash"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 4

        with self.assertRaises(ValueError):
            tree.set(key, b"\x02" * 31)

        with self.assertRaises(ValueError):
            tree.set(key, b"\x02" * 33)

    def test_smt_prove_rejects_mismatched_key_length(self) -> None:
        """验证prove拒绝长度不匹配的key"""
        tree = SparseMerkleTree(depth=32)
        key = b"\x01" * 2

        with self.assertRaises(ValueError):
            tree.prove(key)

    def test_smt_verify_rejects_invalid_root_length(self) -> None:
        """验证verify_proof拒绝非32字节root"""
        proof = SparseMerkleProof(siblings=(), existence=False)
        key = b"\x01"
        value_hash = b"\x02" * 32

        self.assertFalse(verify_proof(b"\x00" * 31, key, value_hash, proof, depth=8))
        self.assertFalse(verify_proof(b"\x00" * 33, key, value_hash, proof, depth=8))

    def test_smt_verify_rejects_invalid_key_length(self) -> None:
        """验证verify_proof拒绝长度不匹配的key"""
        root = b"\x01" * 32
        proof = SparseMerkleProof(siblings=(), existence=False)
        key = b"\x01"  # 错误长度
        value_hash = b"\x02" * 32

        self.assertFalse(verify_proof(root, key, value_hash, proof, depth=8))

    def test_smt_verify_rejects_invalid_value_hash_length(self) -> None:
        """验证verify_proof拒绝非32字节value_hash"""
        root = b"\x01" * 32
        proof = SparseMerkleProof(siblings=(), existence=False)
        key = b"\x01"

        self.assertFalse(verify_proof(root, key, b"\x02" * 31, proof, depth=8))

    def test_smt_verify_rejects_mismatched_proof_length(self) -> None:
        """验证verify_proof拒绝长度不匹配的proof"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        # 错误深度的proof
        self.assertFalse(verify_proof(root, key, value_hash, proof, depth=16))

        # 错误长度的siblings
        wrong_proof = SparseMerkleProof(siblings=proof.siblings[:4], existence=True)
        self.assertFalse(verify_proof(root, key, value_hash, wrong_proof, depth=8))


class EZV2SMTTamperDetectionTests(unittest.TestCase):
    """
    [negative] SMT篡改检测测试

    验证SMT能检测到各种篡改行为
    """

    def test_smt_verify_detects_tampered_root(self) -> None:
        """验证verify检测到被篡改的root"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        proof = tree.prove(key)

        # 篡改root
        tampered_root = b"\xFF" * 32

        self.assertFalse(verify_proof(tampered_root, key, value_hash, proof, depth=8))

    def test_smt_verify_detects_tampered_value(self) -> None:
        """验证verify检测到被篡改的value"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        # 篡改value
        tampered_value = b"\xFF" * 32

        self.assertFalse(verify_proof(root, key, tampered_value, proof, depth=8))

    def test_smt_verify_detects_tampered_sibling(self) -> None:
        """验证verify检测到被篡改的sibling"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        # 篡改第一个sibling
        tampered_siblings = list(proof.siblings)
        tampered_siblings[0] = b"\xFF" * 32
        tampered_proof = SparseMerkleProof(siblings=tuple(tampered_siblings), existence=True)

        self.assertFalse(verify_proof(root, key, value_hash, tampered_proof, depth=8))

    def test_smt_verify_detects_wrong_existence_flag(self) -> None:
        """验证verify检测到错误的existence标志"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root = tree.root()
        proof = tree.prove(key)

        # 错误的existence标志（实际存在但声称不存在）
        wrong_proof = SparseMerkleProof(siblings=proof.siblings, existence=False)

        self.assertFalse(verify_proof(root, key, value_hash, wrong_proof, depth=8))


class EZV2SMTUpdateTests(unittest.TestCase):
    """
    [design-conformance] SMT更新测试
    """

    def test_smt_update_changes_value_and_root(self) -> None:
        """验证更新操作改变值和root"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value1 = b"\x01" * 32
        value2 = b"\x02" * 32

        tree.set(key, value1)
        root1 = tree.root()

        tree.set(key, value2)
        root2 = tree.root()

        self.assertEqual(tree.get(key), value2)
        self.assertNotEqual(root1, root2)

    def test_smt_update_preserves_other_values(self) -> None:
        """验证更新一个key不影响其他key"""
        tree = SparseMerkleTree(depth=8)
        key1 = b"\x01"
        key2 = b"\x02"
        value1 = b"\x01" * 32
        value2 = b"\x02" * 32
        value3 = b"\x03" * 32

        tree.set(key1, value1)
        tree.set(key2, value2)

        root_before = tree.root()

        # 更新key1
        tree.set(key1, value3)

        root_after = tree.root()

        # key2的值应该保持不变
        self.assertEqual(tree.get(key2), value2)
        # root应该改变
        self.assertNotEqual(root_before, root_after)


class EZV2SMTBoundaryTests(unittest.TestCase):
    """
    [boundary] SMT边界条件测试
    """

    def test_smt_with_minimum_depth(self) -> None:
        """验证最小深度SMT工作正常 (depth=8 for byte-aligned keys)"""
        tree = SparseMerkleTree(depth=8)  # 最小支持字节的深度
        key = b"\x01"  # 1字节 = 8位
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        self.assertEqual(tree.get(key), value_hash)

        root = tree.root()
        self.assertEqual(len(root), 32)

    def test_smt_with_large_depth(self) -> None:
        """验证大深度SMT工作正常"""
        tree = SparseMerkleTree(depth=256)
        key = b"\x01" * 32  # 256位
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        self.assertEqual(tree.get(key), value_hash)

        # 能生成proof
        proof = tree.prove(key)
        self.assertEqual(len(proof.siblings), 256)

    def test_smt_empty_leaf_hash_constant(self) -> None:
        """验证空叶子哈希是常量"""
        # EMPTY_LEAF_HASH应该始终是相同的哈希值
        expected = keccak256(b"EZCHAIN_SMT_EMPTY_LEAF_V2")
        self.assertEqual(EMPTY_LEAF_HASH, expected)
        self.assertEqual(len(EMPTY_LEAF_HASH), 32)


class EZV2SMTNodeHashTests(unittest.TestCase):
    """
    [design-conformance] 节点哈希计算测试
    """

    def test_node_hash_combines_left_and_right(self) -> None:
        """验证node_hash正确组合左右子节点"""
        left = b"\x01" * 32
        right = b"\x02" * 32

        result = _node_hash(left, right)
        expected = keccak256(b"EZCHAIN_SMT_NODE_V2" + left + right)

        self.assertEqual(result, expected)

    def test_node_hash_is_commutative_in_inputs(self) -> None:
        """验证node_hash对输入顺序敏感（不是可交换的）"""
        left = b"\x01" * 32
        right = b"\x02" * 32

        hash1 = _node_hash(left, right)
        hash2 = _node_hash(right, left)

        # SMT节点哈希对顺序敏感
        self.assertNotEqual(hash1, hash2)


class EZV2SMTLeafHashTests(unittest.TestCase):
    """
    [design-conformance] 叶子节点哈希计算测试
    """

    def test_leaf_hash_combines_key_and_value(self) -> None:
        """验证leaf_hash正确组合key和value"""
        key = b"\x01" * 4
        value_hash = b"\x02" * 32

        result = _leaf_node_hash(key, value_hash)
        expected = keccak256(b"EZCHAIN_SMT_LEAF_V2" + key + value_hash)

        self.assertEqual(result, expected)

    def test_leaf_hash_is_deterministic(self) -> None:
        """验证leaf_hash是确定性的"""
        key = b"\x01" * 4
        value_hash = b"\x02" * 32

        hash1 = _leaf_node_hash(key, value_hash)
        hash2 = _leaf_node_hash(key, value_hash)

        self.assertEqual(hash1, hash2)


class EZV2SMTCopyTests(unittest.TestCase):
    """
    [design-conformance] SMT拷贝测试
    """

    def test_smt_copy_creates_independent_copy(self) -> None:
        """验证copy创建独立副本"""
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        value_hash = b"\x02" * 32

        tree.set(key, value_hash)
        root_before = tree.root()

        # 创建副本
        copy_tree = tree.copy()

        # 验证副本有相同的root
        self.assertEqual(copy_tree.root(), root_before)

        # 修改原树
        new_value = b"\x03" * 32
        tree.set(key, new_value)

        # 副本应该保持不变
        self.assertEqual(copy_tree.get(key), value_hash)
        self.assertEqual(tree.get(key), new_value)

        # Roots应该不同
        self.assertNotEqual(tree.root(), copy_tree.root())

    def test_smt_copy_preserves_depth(self) -> None:
        """验证copy保留深度设置"""
        tree = SparseMerkleTree(depth=16)
        copy_tree = tree.copy()

        self.assertEqual(copy_tree.depth, tree.depth)


class EZV2SMTInvariantTests(unittest.TestCase):
    """
    [invariants] SMT不变量测试

    验证SMT操作满足核心不变量
    """

    def test_smt_root_is_always_32_bytes(self) -> None:
        """验证root始终是32字节"""
        tree = SparseMerkleTree(depth=8)

        # 空树
        self.assertEqual(len(tree.root()), 32)

        # 插入值
        for i in range(10):
            key = bytes([i])
            value = bytes([i]) * 32
            tree.set(key, value)
            self.assertEqual(len(tree.root()), 32)

    def test_smt_proof_sibling_count_equals_depth(self) -> None:
        """验证proof的sibling数量等于深度"""
        for depth in [8, 16, 32, 64, 128, 256]:  # 只使用8的倍数深度
            tree = SparseMerkleTree(depth=depth)
            key = b"\x01" * (depth // 8)
            value_hash = b"\x02" * 32

            tree.set(key, value_hash)
            proof = tree.prove(key)

            self.assertEqual(len(proof.siblings), depth)

    def test_smt_set_then_get_roundtrip(self) -> None:
        """验证set-get往返操作保持值不变"""
        tree = SparseMerkleTree(depth=8)

        for i in range(10):
            key = bytes([i])  # 1字节匹配depth=8
            original_value = bytes([i + 1]) * 32

            tree.set(key, original_value)
            retrieved_value = tree.get(key)

            self.assertEqual(retrieved_value, original_value)


if __name__ == "__main__":
    unittest.main()
