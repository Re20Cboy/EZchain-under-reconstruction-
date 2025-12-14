#!/usr/bin/env python3
"""
验证AccountProofManager修复后的效果
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_VPB.proofs.AccountProofManager import AccountProofManager, AccountProofStorage
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof

def test_fixed_duplicate_prevention():
    """测试修复后的重复防护机制"""

    print("=" * 60)
    print("测试修复后的重复防护机制")
    print("=" * 60)

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()

    try:
        # 创建AccountProofManager实例
        account_address = "0x134599aeb1582bde22b7a2e410f817989c57595f"
        db_path = os.path.join(temp_dir, "test.db")
        storage = AccountProofStorage(db_path)
        manager = AccountProofManager(
            account_address=account_address,
            storage=storage
        )

        # 创建相同的proof unit数据
        owner = "alice"
        digest = "a1fdd1828b170f1a..."

        # 创建第一个proof unit
        mt_proof1 = MerkleTreeProof()
        mt_proof1.mt_prf_list = [digest, "other_hash1"]

        multi_txns1 = MultiTransactions(sender=owner, multi_txns=[])
        multi_txns1.digest = digest

        proof_unit1 = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns1,
            owner_mt_proof=mt_proof1
        )

        # 创建第二个相同的proof unit（内容相同）
        mt_proof2 = MerkleTreeProof()
        mt_proof2.mt_prf_list = [digest, "other_hash1"]

        multi_txns2 = MultiTransactions(sender=owner, multi_txns=[])
        multi_txns2.digest = digest

        proof_unit2 = ProofUnit(
            owner=owner,
            owner_multi_txns=multi_txns2,
            owner_mt_proof=mt_proof2
        )

        print(f"ProofUnit1 unit_id: {proof_unit1.unit_id}")
        print(f"ProofUnit2 unit_id: {proof_unit2.unit_id}")
        print(f"unit_id是否相同: {proof_unit1.unit_id == proof_unit2.unit_id}")

        # 添加value
        value_id = "0x1000"
        manager.add_value(value_id)

        # 添加第一个proof unit
        print("\n添加第一个proof unit...")
        result1 = manager.add_proof_unit_optimized(value_id, proof_unit1)
        print(f"添加结果: {result1}")

        # 添加第二个proof unit（应该被识别为重复）
        print("\n添加第二个proof unit（应该识别为重复）...")
        result2 = manager.add_proof_unit_optimized(value_id, proof_unit2)
        print(f"添加结果: {result2}")

        # 查看添加的proof units
        print("\n检查添加的proof units...")
        proof_units = manager.get_proof_units_for_value(value_id)
        print(f"Value {value_id} 的proof unit数量: {len(proof_units)}")

        for i, pu in enumerate(proof_units):
            print(f"  ProofUnit[{i+1}]: unit_id={pu.unit_id[:16]}..., digest={pu.owner_multi_txns.digest}, reference_count={pu.reference_count}")

        # 检查是否有重复
        unit_ids = [pu.unit_id for pu in proof_units]
        unique_unit_ids = set(unit_ids)
        print(f"\n是否有重复: {len(unit_ids) != len(unique_unit_ids)}")

        # 直接查询数据库验证
        print("\n直接查询数据库验证...")
        all_mappings = storage.get_all_proof_units_for_account(account_address)
        print(f"数据库中的总映射数: {len(all_mappings)}")

        for value_id, proof_unit in all_mappings:
            print(f"  Value: {value_id}, Unit: {proof_unit.unit_id[:16]}...")

        # 清理
        # AccountProofManager没有cleanup方法，不需要手动清理

        print("\n" + "=" * 60)
        print("修复验证完成！")
        if len(unit_ids) == len(unique_unit_ids):
            print("✅ 修复成功：没有重复的proof unit")
        else:
            print("❌ 仍有问题：存在重复的proof unit")
        print("=" * 60)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    test_fixed_duplicate_prevention()