#!/usr/bin/env python3
"""
分析AccountProofManager重复添加proof unit的问题
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof

def analyze_proof_unit_id_generation():
    """分析ProofUnit的ID生成机制"""

    print("=" * 60)
    print("ProofUnit ID生成机制分析")
    print("=" * 60)

    # 创建相同的proof unit数据
    owner = "alice"
    digest = "a1fdd1828b170f1a..."

    # 创建第一个proof unit
    mt_proof1 = MerkleTreeProof()
    mt_proof1.mt_prf_list = [digest, "other_hash1"]
    print(f"MerkleProof1.mt_prf_list = {mt_proof1.mt_prf_list}")

    # 创建MultiTransactions
    multi_txns1 = MultiTransactions(sender=owner, multi_txns=[])
    multi_txns1.digest = digest
    print(f"MultiTransactions1.digest = {multi_txns1.digest}")

    proof_unit1 = ProofUnit(
        owner=owner,
        owner_multi_txns=multi_txns1,
        owner_mt_proof=mt_proof1
    )

    # 创建第二个完全相同的proof unit
    mt_proof2 = MerkleTreeProof()
    mt_proof2.mt_prf_list = [digest, "other_hash1"]  # 完全相同的列表
    print(f"MerkleProof2.mt_prf_list = {mt_proof2.mt_prf_list}")

    multi_txns2 = MultiTransactions(sender=owner, multi_txns=[])
    multi_txns2.digest = digest  # 相同的digest
    print(f"MultiTransactions2.digest = {multi_txns2.digest}")

    proof_unit2 = ProofUnit(
        owner=owner,
        owner_multi_txns=multi_txns2,
        owner_mt_proof=mt_proof2
    )

    print("\n" + "-" * 40)
    print("比较结果:")
    print(f"ProofUnit1 unit_id: {proof_unit1.unit_id}")
    print(f"ProofUnit2 unit_id: {proof_unit2.unit_id}")
    print(f"unit_id是否相同: {proof_unit1.unit_id == proof_unit2.unit_id}")

    # 手动计算unit_id生成的内容
    print("\n" + "-" * 40)
    print("手动分析unit_id生成:")

    # _generate_unit_id方法的内容: f"{self.owner}_{self.owner_multi_txns.digest}_{hash(str(self.owner_mt_proof.mt_prf_list))}"
    content1 = f"{proof_unit1.owner}_{proof_unit1.owner_multi_txns.digest}_{hash(str(proof_unit1.owner_mt_proof.mt_prf_list))}"
    content2 = f"{proof_unit2.owner}_{proof_unit2.owner_multi_txns.digest}_{hash(str(proof_unit2.owner_mt_proof.mt_prf_list))}"

    print(f"Content1: {content1}")
    print(f"Content2: {content2}")
    print(f"Content是否相同: {content1 == content2}")

    print(f"\nhash(str(mt_proof1.mt_prf_list)) = {hash(str(mt_proof1.mt_prf_list))}")
    print(f"hash(str(mt_proof2.mt_prf_list)) = {hash(str(mt_proof2.mt_prf_list))}")

    # 问题分析
    print("\n" + "=" * 60)
    print("问题分析:")
    print("=" * 60)
    print("1. 如果两个ProofUnit的owner、digest和mt_prf_list完全相同")
    print("2. 那么它们的unit_id应该相同")
    print("3. 在add_proof_unit_optimized方法中，布隆过滤器应该能检测到重复")
    print("4. 但实际上数据库可能存储了多个相同的unit_id")
    print("\n可能的原因:")
    print("- get_all_proof_units_for_account返回了重复的记录")
    print("- 数据库中确实存在重复的value_id-unit_id映射")
    print("- add_value_proof_mapping使用了INSERT OR IGNORE，但可能sequence号不同导致重复插入")

if __name__ == "__main__":
    analyze_proof_unit_id_generation()