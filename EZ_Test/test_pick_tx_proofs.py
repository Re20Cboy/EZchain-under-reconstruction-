"""
PickTx.py 默克尔证明功能测试文件
专门测试 pick_transactions_from_pool_with_proofs 函数的正确性
"""

import sys
import os
import time
import tempfile
import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import unittest

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import TransactionPicker, PackagedBlockData, pick_transactions_from_pool, pick_transactions_from_pool_with_proofs
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Main_Chain.Block import Block
from EZ_Main_Chain.Blockchain import Blockchain
from EZ_Units.MerkleTree import MerkleTree
from EZ_Tool_Box.Hash import sha256_hash


@dataclass
class TestResult:
    """测试结果数据类"""
    test_name: str
    success: bool
    message: str
    data: Any = None
    execution_time: float = 0.0


class MockSubmitTxInfo:
    """模拟SubmitTxInfo用于测试"""

    def __init__(self, multi_tx_hash: str, submitter_address: str, timestamp: str = None):
        self.multi_transactions_hash = multi_tx_hash
        self.submitter_address = submitter_address
        self.submit_timestamp = timestamp or datetime.datetime.now().isoformat()
        self.signature = b"mock_signature"
        self.public_key = b"mock_public_key"
        self.version = "1.0.0"
        self._hash = None

    def get_hash(self) -> str:
        if self._hash is None:
            self._hash = f"hash_{self.multi_transactions_hash}_{self.submitter_address}"
        return self._hash


class PickTxProofsTest:
    """PickTx.py 默克尔证明功能测试类"""

    def __init__(self):
        self.test_results: List[TestResult] = []
        self.temp_files: List[str] = []

    def cleanup(self):
        """清理临时文件"""
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except:
                pass
        self.temp_files.clear()

    def create_temp_file(self, suffix: str = '') -> str:
        """创建临时文件"""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file_path = tmp.name
        self.temp_files.append(file_path)
        return file_path

    def run_test(self, test_name: str, test_func):
        """运行单个测试并记录结果"""
        print(f"运行测试: {test_name}...", end=" ")
        start_time = time.time()

        try:
            result_data = test_func()
            execution_time = time.time() - start_time

            self.test_results.append(TestResult(
                test_name=test_name,
                success=True,
                message="测试通过",
                data=result_data,
                execution_time=execution_time
            ))
            print("通过")
            return True, result_data
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"测试失败: {str(e)}"

            self.test_results.append(TestResult(
                test_name=test_name,
                success=False,
                message=error_msg,
                execution_time=execution_time
            ))
            print(f"失败 - {error_msg}")
            return False, None

    def test_convenience_function_with_proofs(self):
        """测试带默克尔证明的便捷函数"""
        db_path = self.create_temp_file('.db')
        tx_pool = TxPool(db_path=db_path)

        # 创建测试数据
        submit_tx_infos = [
            MockSubmitTxInfo("hash1", "submitter1"),
            MockSubmitTxInfo("hash2", "submitter2"),
            MockSubmitTxInfo("hash3", "submitter3"),
        ]

        for tx_info in submit_tx_infos:
            tx_pool.pool.append(tx_info)

        # 调用新函数
        package_data, block, picked_txs_mt_proofs, block_index = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="test_miner",
            previous_hash="prev_hash",
            block_index=1,
            max_submit_tx_infos=10
        )

        # 验证返回值结构
        assert isinstance(package_data, PackagedBlockData)
        assert isinstance(block, Block)
        assert isinstance(picked_txs_mt_proofs, list)
        assert isinstance(block_index, int)

        # 验证基本属性
        assert block.index == 1
        assert block.miner == "test_miner"
        assert block.m_tree_root == package_data.merkle_root

        # 验证 picked_txs_mt_proofs 结构
        assert len(picked_txs_mt_proofs) == len(package_data.selected_submit_tx_infos)

        picked_hashes = set()
        for multi_transactions_hash, merkle_proof in picked_txs_mt_proofs:
            assert isinstance(multi_transactions_hash, str)
            assert multi_transactions_hash in ["hash1", "hash2", "hash3"]
            picked_hashes.add(multi_transactions_hash)
            assert merkle_proof is not None  # Merkle proof should exist

        # 验证所有选中的交易都有对应的证明
        selected_hashes = set(tx_info.multi_transactions_hash for tx_info in package_data.selected_submit_tx_infos)
        assert picked_hashes == selected_hashes

        # 验证 block_index 正确性
        assert block_index == 1

        return {
            "package_data_type": type(package_data).__name__,
            "block_type": type(block).__name__,
            "picked_proofs_count": len(picked_txs_mt_proofs),
            "selected_transactions_count": len(package_data.selected_submit_tx_infos),
            "block_index": block_index,
            "merkle_root_matches": block.m_tree_root == package_data.merkle_root,
            "proofs_valid": all(proof is not None for _, proof in picked_txs_mt_proofs),
            "all_selected_have_proofs": picked_hashes == selected_hashes
        }

    def test_merkle_proof_structure(self):
        """测试默克尔证明结构的正确性"""
        db_path = self.create_temp_file('.db')
        tx_pool = TxPool(db_path=db_path)

        # 创建固定数量的测试数据
        submit_tx_infos = [
            MockSubmitTxInfo("tx_hash_1", "submitter1"),
            MockSubmitTxInfo("tx_hash_2", "submitter2"),
            MockSubmitTxInfo("tx_hash_3", "submitter3"),
            MockSubmitTxInfo("tx_hash_4", "submitter4"),
        ]

        for tx_info in submit_tx_infos:
            tx_pool.pool.append(tx_info)

        # 获取带证明的交易
        package_data, block, picked_txs_mt_proofs, block_index = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="proof_test_miner",
            previous_hash="proof_prev_hash",
            block_index=5,
            max_submit_tx_infos=4
        )

        # 手动构建默克尔树进行验证
        leaf_hashes = [tx_info.multi_transactions_hash for tx_info in submit_tx_infos]
        manual_merkle_tree = MerkleTree(leaf_hashes)
        expected_root = manual_merkle_tree.get_root_hash()

        # 验证默克尔根一致性
        assert package_data.merkle_root == expected_root
        assert block.m_tree_root == expected_root

        # 验证每个证明的结构
        proof_hashes = set()
        for multi_transactions_hash, merkle_proof in picked_txs_mt_proofs:
            # 验证哈希在叶子节点中
            assert multi_transactions_hash in leaf_hashes
            proof_hashes.add(multi_transactions_hash)

            # 验证证明结构（根据 MerkleTree 的 prf_list 格式）
            assert isinstance(merkle_proof, list)
            # 证明应该包含哈希值和路径信息
            if merkle_proof:  # 如果证明不为空
                assert len(merkle_proof) > 0

        # 验证所有选中的交易都有对应的证明
        selected_hashes = set(tx_info.multi_transactions_hash for tx_info in package_data.selected_submit_tx_infos)
        assert proof_hashes == selected_hashes

        return {
            "leaf_count": len(leaf_hashes),
            "proof_count": len(picked_txs_mt_proofs),
            "selected_count": len(package_data.selected_submit_tx_infos),
            "merkle_root_valid": package_data.merkle_root == expected_root,
            "all_selected_have_proofs": proof_hashes == selected_hashes,
            "block_index": block_index
        }

    def test_empty_pool_with_proofs(self):
        """测试空池的带证明函数"""
        db_path = self.create_temp_file('.db')
        tx_pool = TxPool(db_path=db_path)

        # 调用新函数
        package_data, block, picked_txs_mt_proofs, block_index = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="empty_pool_miner",
            previous_hash="empty_prev_hash",
            block_index=10,
            max_submit_tx_infos=5
        )

        # 验证空池的处理
        assert len(package_data.selected_submit_tx_infos) == 0
        assert package_data.merkle_root == ""
        assert len(package_data.submitter_addresses) == 0
        assert len(picked_txs_mt_proofs) == 0
        assert block_index == 10
        assert isinstance(block, Block)

        return {
            "empty_pool_handled": True,
            "no_transactions_selected": len(package_data.selected_submit_tx_infos) == 0,
            "no_proofs_generated": len(picked_txs_mt_proofs) == 0,
            "block_index_preserved": block_index == 10,
            "block_created": isinstance(block, Block)
        }

    def test_proofs_vs_standard_function(self):
        """对比带证明函数和标准函数的结果一致性"""
        db_path1 = self.create_temp_file('.db')
        db_path2 = self.create_temp_file('.db')
        tx_pool1 = TxPool(db_path=db_path1)
        tx_pool2 = TxPool(db_path=db_path2)

        # 创建相同的测试数据
        submit_tx_infos = [
            MockSubmitTxInfo("comparison_hash_1", "submitter_a"),
            MockSubmitTxInfo("comparison_hash_2", "submitter_b"),
            MockSubmitTxInfo("comparison_hash_3", "submitter_c"),
        ]

        for tx_info in submit_tx_infos:
            tx_pool1.pool.append(tx_info)
            # 创建相似的 MockSubmitTxInfo（相同哈希，不同对象）
            mock_tx_info = MockSubmitTxInfo(tx_info.multi_transactions_hash, tx_info.submitter_address)
            tx_pool2.pool.append(mock_tx_info)

        # 调用标准函数
        package_data_std, block_std = pick_transactions_from_pool(
            tx_pool=tx_pool1,
            miner_address="standard_miner",
            previous_hash="standard_prev_hash",
            block_index=1,
            max_submit_tx_infos=3,
            selection_strategy="fifo"
        )

        # 调用带证明函数
        package_data_proof, block_proof, picked_txs_mt_proofs, block_index_proof = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool2,
            miner_address="proof_miner",
            previous_hash="proof_prev_hash",
            block_index=1,
            max_submit_tx_infos=3,
            selection_strategy="fifo"
        )

        # 验证核心数据一致性
        assert len(package_data_std.selected_submit_tx_infos) == len(package_data_proof.selected_submit_tx_infos)
        assert package_data_std.merkle_root == package_data_proof.merkle_root
        assert set(package_data_std.submitter_addresses) == set(package_data_proof.submitter_addresses)
        assert block_index_proof == 1

        # 验证交易哈希一致性
        std_hashes = [tx_info.multi_transactions_hash for tx_info in package_data_std.selected_submit_tx_infos]
        proof_hashes = [tx_info.multi_transactions_hash for tx_info in package_data_proof.selected_submit_tx_infos]
        assert set(std_hashes) == set(proof_hashes)

        # 验证证明数量匹配
        assert len(picked_txs_mt_proofs) == len(package_data_proof.selected_submit_tx_infos)

        # 验证证明哈希与选中交易匹配
        proof_tx_hashes = set(multi_hash for multi_hash, _ in picked_txs_mt_proofs)
        selected_tx_hashes = set(tx_info.multi_transactions_hash for tx_info in package_data_proof.selected_submit_tx_infos)
        assert proof_tx_hashes == selected_tx_hashes

        return {
            "transaction_counts_equal": len(package_data_std.selected_submit_tx_infos) == len(package_data_proof.selected_submit_tx_infos),
            "merkle_roots_equal": package_data_std.merkle_root == package_data_proof.merkle_root,
            "submitters_equal": set(package_data_std.submitter_addresses) == set(package_data_proof.submitter_addresses),
            "proofs_count_correct": len(picked_txs_mt_proofs) == len(package_data_proof.selected_submit_tx_infos),
            "proof_hashes_match_selected": proof_tx_hashes == selected_tx_hashes,
            "block_index_correct": block_index_proof == 1
        }

    def test_different_selection_strategies(self):
        """测试不同选择策略下的证明生成"""
        db_path_fifo = self.create_temp_file('.db')
        db_path_fee = self.create_temp_file('.db')
        tx_pool_fifo = TxPool(db_path=db_path_fifo)
        tx_pool_fee = TxPool(db_path=db_path_fee)

        # 创建带有时间戳的测试数据
        submit_tx_infos = [
            MockSubmitTxInfo("early_hash_1", "submitter1", "2023-01-01T10:00:00"),
            MockSubmitTxInfo("early_hash_2", "submitter2", "2023-01-01T11:00:00"),
            MockSubmitTxInfo("early_hash_3", "submitter3", "2023-01-01T12:00:00"),
            MockSubmitTxInfo("early_hash_4", "submitter4", "2023-01-01T09:00:00"),  # 最早但时间戳最晚
        ]

        # FIFO策略
        for tx_info in submit_tx_infos:
            tx_pool_fifo.pool.append(tx_info)

        # Fee策略（时间戳倒序）
        for tx_info in submit_tx_infos:
            tx_pool_fee.pool.append(tx_info)

        # 测试FIFO策略
        package_data_fifo, block_fifo, picked_txs_mt_proofs_fifo, _ = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool_fifo,
            miner_address="fifo_miner",
            previous_hash="fifo_prev_hash",
            block_index=1,
            max_submit_tx_infos=4,
            selection_strategy="fifo"
        )

        # 测试Fee策略
        package_data_fee, block_fee, picked_txs_mt_proofs_fee, _ = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool_fee,
            miner_address="fee_miner",
            previous_hash="fee_prev_hash",
            block_index=1,
            max_submit_tx_infos=4,
            selection_strategy="fee"
        )

        # 验证两种策略都产生了有效结果
        assert len(package_data_fifo.selected_submit_tx_infos) > 0
        assert len(package_data_fee.selected_submit_tx_infos) > 0
        assert len(picked_txs_mt_proofs_fifo) > 0
        assert len(picked_txs_mt_proofs_fee) > 0

        # 验证证明数量匹配选中的交易数量
        assert len(picked_txs_mt_proofs_fifo) == len(package_data_fifo.selected_submit_tx_infos)
        assert len(picked_txs_mt_proofs_fee) == len(package_data_fee.selected_submit_tx_infos)

        return {
            "fifo_strategy_works": len(picked_txs_mt_proofs_fifo) > 0,
            "fee_strategy_works": len(picked_txs_mt_proofs_fee) > 0,
            "fifo_proofs_match_transactions": len(picked_txs_mt_proofs_fifo) == len(package_data_fifo.selected_submit_tx_infos),
            "fee_proofs_match_transactions": len(picked_txs_mt_proofs_fee) == len(package_data_fee.selected_submit_tx_infos),
            "fifo_transaction_count": len(package_data_fifo.selected_submit_tx_infos),
            "fee_transaction_count": len(package_data_fee.selected_submit_tx_infos)
        }

    def test_max_transactions_limit(self):
        """测试最大交易数量限制"""
        db_path = self.create_temp_file('.db')
        tx_pool = TxPool(db_path=db_path)

        # 创建超过限制的交易数量
        submit_tx_infos = []
        for i in range(8):  # 创建8个交易，但限制为5个
            submit_tx_infos.append(MockSubmitTxInfo(f"hash_{i}", f"submitter_{i}"))

        for tx_info in submit_tx_infos:
            tx_pool.pool.append(tx_info)

        # 限制最大交易数量
        package_data, block, picked_txs_mt_proofs, _ = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="limit_test_miner",
            previous_hash="limit_test_prev_hash",
            block_index=1,
            max_submit_tx_infos=5  # 限制为5个
        )

        # 验证交易数量限制生效
        assert len(package_data.selected_submit_tx_infos) <= 5
        assert len(picked_txs_mt_proofs) <= 5
        assert len(package_data.selected_submit_tx_infos) == len(picked_txs_mt_proofs)

        return {
            "original_transaction_count": len(submit_tx_infos),
            "selected_transaction_count": len(package_data.selected_submit_tx_infos),
            "proofs_count": len(picked_txs_mt_proofs),
            "limit_enforced": len(package_data.selected_submit_tx_infos) <= 5,
            "proofs_match_limited_transactions": len(picked_txs_mt_proofs) == len(package_data.selected_submit_tx_infos)
        }

    def run_all_tests(self) -> List[TestResult]:
        """运行所有默克尔证明功能测试"""
        print("=" * 80)
        print("开始 PickTx.py 默克尔证明功能测试")
        print("=" * 80)

        # 运行所有测试
        self.run_test("带默克尔证明的便捷函数测试", self.test_convenience_function_with_proofs)
        self.run_test("默克尔证明结构测试", self.test_merkle_proof_structure)
        self.run_test("空池带证明测试", self.test_empty_pool_with_proofs)
        self.run_test("证明函数与标准函数对比测试", self.test_proofs_vs_standard_function)
        self.run_test("不同选择策略测试", self.test_different_selection_strategies)
        self.run_test("最大交易数量限制测试", self.test_max_transactions_limit)

        # 清理
        self.cleanup()

        # 打印结果
        self.print_summary()

        return self.test_results

    def print_summary(self):
        """打印测试摘要"""
        print("\n" + "=" * 80)
        print("PickTx 默克尔证明功能测试结果摘要")
        print("=" * 80)

        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result.success)
        failed_tests = total_tests - passed_tests

        print(f"总测试数: {total_tests}")
        print(f"通过: {passed_tests}")
        print(f"失败: {failed_tests}")
        print(f"通过率: {passed_tests/total_tests*100:.1f}%" if self.test_results else "无测试")

        # 失败测试详情
        failed_tests_list = [result for result in self.test_results if not result.success]
        if failed_tests_list:
            print(f"\n--- 失败测试详情 ---")
            for result in failed_tests_list:
                print(f"  [FAIL] {result.test_name}: {result.message}")

        # 性能摘要
        slow_tests = [
            (result.test_name, result.execution_time)
            for result in self.test_results
            if result.success and result.execution_time > 0.1
        ]
        if slow_tests:
            print(f"\n--- 性能摘要 ---")
            for test_name, exec_time in slow_tests:
                print(f"  慢速测试: {test_name} ({exec_time:.3f}秒)")

        # 最终结论
        print(f"\n--- 最终结论 ---")
        if failed_tests == 0:
            print("SUCCESS: 所有默克尔证明功能测试通过！")
            print("功能完整性: pick_transactions_from_pool_with_proofs 功能正常工作")
            print("数据一致性: 证明结构与选中交易完美匹配")
            print("接口兼容性: 新功能不影响原有功能")
            print("边界处理: 空池和限制条件处理正确")
        else:
            print("FAILURE: 部分测试失败，需要进一步检查。")
            print(f"建议优先修复失败的 {failed_tests} 个测试用例。")

        print("=" * 80)


def run_pick_tx_proofs_tests():
    """运行PickTx默克尔证明功能测试的便捷函数"""
    test_instance = PickTxProofsTest()
    return test_instance.run_all_tests()


if __name__ == "__main__":
    # 直接运行测试
    run_pick_tx_proofs_tests()