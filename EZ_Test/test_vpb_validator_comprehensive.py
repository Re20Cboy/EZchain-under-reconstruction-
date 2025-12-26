#!/usr/bin/env python3
"""
VPB Validator 测试套件 - 基于VPB_test_demo.md案例的全面测试

该测试套件包含以下类型的测试案例：
1. 简单正常交易（有checkpoint）
2. 简单正常交易（无checkpoint）
3. 简单双花交易（有checkpoint）
4. 简单双花交易（无checkpoint）
5. 组合正常交易（有checkpoint）
6. 组合正常交易（无checkpoint）
7. 组合双花交易（有checkpoint）
8. 组合双花交易（无checkpoint）
9. 边缘案例和压力测试
"""

import pytest
import sys
import os
import tempfile
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from unittest.mock import Mock, MagicMock, patch

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 完全禁用所有日志输出
logging.disable(logging.CRITICAL)  # 禁用所有级别的日志

# 确保关键模块的日志被禁用
logging.getLogger('EZ_VPB_Validator').setLevel(logging.CRITICAL)
logging.getLogger('EZ_VPB_Validator.vpb_validator').setLevel(logging.CRITICAL)
logging.getLogger('EZ_VPB_Validator.steps').setLevel(logging.CRITICAL)
logging.getLogger('EZ_VPB_Validator.utils').setLevel(logging.CRITICAL)
logging.getLogger('EZ_VPB_Validator.core').setLevel(logging.CRITICAL)
logging.getLogger('EZ_CheckPoint').setLevel(logging.CRITICAL)
logging.getLogger('EZ_Proof').setLevel(logging.CRITICAL)
logging.getLogger('EZ_Value').setLevel(logging.CRITICAL)
logging.getLogger('EZ_BlockIndex').setLevel(logging.CRITICAL)
logging.getLogger('EZ_Units').setLevel(logging.CRITICAL)

# 禁用根logger的所有日志
root_logger = logging.getLogger()
root_logger.setLevel(logging.CRITICAL)

# 创建一个空的日志处理器来彻底禁用输出
class NullHandler(logging.Handler):
    def emit(self, record):
        pass  # 忽略所有日志记录

# 为所有logger添加空处理器
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
root_logger.addHandler(NullHandler())


class TestOutputManager:
    """测试输出管理器 - 提供简洁直观的测试结果展示"""

    @staticmethod
    def print_header(title: str, width: int = 80):
        """打印测试标题"""
        print("=" * width)
        print(f" {title} ".center(width, "="))
        print("=" * width)

    @staticmethod
    def print_case_header(case_name: str):
        """打印测试案例标题"""
        print(f"\n[测试] {case_name}")
        print("-" * 60)

    @staticmethod
    def print_success(message: str):
        """打印成功信息"""
        print(f"[PASS] {message}")

    @staticmethod
    def print_failure(message: str):
        """打印失败信息"""
        print(f"[FAIL] {message}")

    @staticmethod
    def print_info(message: str, indent: int = 2):
        """打印信息"""
        prefix = "  " * indent
        print(f"{prefix}- {message}")

    @staticmethod
    def print_error_details(errors: List, indent: int = 4):
        """打印错误详情"""
        prefix = "  " * indent
        if errors:
            for i, error in enumerate(errors, 1):
                print(f"{prefix}{i}. {error.error_type}: {error.error_message}")

    @staticmethod
    def print_verification_summary(report, case_name: str):
        """打印验证结果摘要"""
        print(f"\n【{case_name}验证结果】")
        print(f"  状态: {'通过' if report.is_valid else '失败'}")
        print(f"  耗时: {report.verification_time_ms:.2f}ms")
        print(f"  错误数: {len(report.errors)}")

        if report.checkpoint_used:
            print(f"  检查点: 区块{report.checkpoint_used.block_height}")
        else:
            print(f"  检查点: 未使用")

        if report.errors:
            print(f"  错误详情:")
            TestOutputManager.print_error_details(report.errors)

        if hasattr(report, 'verified_epochs') and report.verified_epochs:
            print(f"  验证区块: {len(report.verified_epochs)}个epoch")

    @staticmethod
    def print_progress_bar(current: int, total: int, width: int = 40):
        """打印进度条"""
        progress = current / total
        filled = int(width * progress)
        bar = "=" * filled + "-" * (width - filled)
        percent = progress * 100
        print(f"\r进度: [{bar}] {percent:.1f}% ({current}/{total})", end="", flush=True)

    @staticmethod
    def print_final_results(results: List[Tuple[str, bool]], total_time: float):
        """打印最终测试结果"""
        passed = sum(1 for _, success in results if success)
        failed = len(results) - passed
        success_rate = (passed / len(results)) * 100 if results else 0

        print("\n" + "=" * 80)
        print("【测试结果汇总】".center(80))
        print("=" * 80)

        # 结果统计
        print(f"总测试数: {len(results)}")
        print(f"通过数量: {passed}")
        print(f"失败数量: {failed}")
        print(f"成功率: {success_rate:.1f}%")
        print(f"总耗时: {total_time:.2f}秒")

        # 详细结果
        print("\n【详细结果】")
        for case_name, success in results:
            status = "通过" if success else "失败"
            print(f"  {status.ljust(4)} | {case_name}")

        print("=" * 80)

try:
    from EZ_VPB_Validator.vpb_validator import VPBValidator
    from EZ_VPB_Validator.core.types import (
        VerificationResult, VerificationError, VPBVerificationReport,
        MainChainInfo, VPBSlice
    )
    from EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord
    from EZ_VPB.values.Value import Value, ValueState
    from EZ_VPB.proofs.Proofs import Proofs
    from EZ_VPB.proofs.ProofUnit import ProofUnit
    from EZ_VPB.block_index.BlockIndexList import BlockIndexList
    from EZ_Units.Bloom import BloomFilter
except ImportError as e:
    print(f"导入模块错误: {e}")
    print("请确保相关模块在正确的路径中")
    sys.exit(1)


def convert_proofs_to_proof_units(proofs):
    """
    将Proofs对象转换为ProofUnit列表，以兼容新的VPBValidator接口

    Args:
        proofs: Proofs对象或ProofUnit列表

    Returns:
        List[ProofUnit]: ProofUnit列表
    """
    if hasattr(proofs, 'get_proof_units'):
        # 这是一个Proofs对象
        return proofs.get_proof_units()
    elif isinstance(proofs, list):
        # 这已经是一个ProofUnit列表
        return proofs
    else:
        # 其他情况，返回空列表
        return []


class VPBTestDataGenerator:
    """VPB测试数据生成器"""

    @staticmethod
    def create_value(begin_index: str, value_num: int) -> Value:
        """创建Value对象"""
        return Value(begin_index, value_num)

    @staticmethod
    def create_eth_address(name: str) -> str:
        """创建有效的以太坊地址格式"""
        # 使用名字的哈希值生成地址
        import hashlib
        hash_bytes = hashlib.sha256(name.encode()).digest()
        return f"0x{hash_bytes[:20].hex()}"

    @staticmethod
    def create_mock_proofs(count: int, value_id: str = "0x1000") -> Mock:
        """创建模拟的Proofs对象"""
        mock_proofs = Mock(spec=Proofs)
        # 创建可以迭代的proof_units
        mock_proofs.proof_units = [Mock(spec=ProofUnit) for _ in range(count)]
        mock_proofs.value_id = value_id  # 添加缺失的value_id属性

        # 添加get_proof_units方法使其可以被正确迭代
        def get_proof_units():
            return mock_proofs.proof_units
        mock_proofs.get_proof_units = get_proof_units

        # 使mock_proofs可迭代
        def __iter__(self):
            return iter(mock_proofs.proof_units)
        mock_proofs.__iter__ = __iter__

        # 为每个proof unit添加必要的属性
        for i, proof_unit in enumerate(mock_proofs.proof_units):
            # 生成有效的40字符十六进制地址
            address_suffix = format(i, '040x')  # 用0填充到40个字符
            proof_unit.owner = f"0x{address_suffix[-40:]}"  # 确保总长度42字符(0x + 40字符)
            proof_unit.unit_id = f"0x{'0'*63}{i:01x}"  # 64字符hex
            proof_unit.reference_count = 1
            proof_unit.owner_multi_txns = Mock()
            proof_unit.owner_multi_txns.sender = proof_unit.owner
            proof_unit.owner_multi_txns.digest = f"0x{'0'*63}{i:01x}"
            proof_unit.owner_multi_txns.multi_txns = []
            proof_unit.owner_mt_proof = Mock()
            proof_unit.owner_mt_proof.mt_prf_list = [f"0x{'0'*63}{j:01x}" for j in range(2)]
            proof_unit.block_height = i * 10
            proof_unit.verify_proof_unit = Mock(return_value=(True, ""))

        return mock_proofs

    @staticmethod
    def create_real_proofs(count: int, value_id: str = "0x1000") -> List[ProofUnit]:
        """创建真实的ProofUnit对象列表，完全避免使用Mock对象"""
        from EZ_Transaction.MultiTransactions import MultiTransactions
        from EZ_Transaction.SingleTransaction import Transaction
        from EZ_Units.MerkleProof import MerkleTreeProof
        from EZ_VPB.values.Value import Value

        proof_units = []

        for i in range(count):
            # 生成有效的以太坊地址
            address_suffix = format(i, '040x')
            owner = f"0x{address_suffix[-40:]}"  # 确保总长度42字符(0x + 40字符)

            # 创建完全真实的Transaction对象
            tx_value = Value(f"0x{i:04x}", 100)  # 真实的Value对象

            # 创建真实的Transaction（需要正确的参数）
            real_tx = Transaction(
                sender=owner,
                recipient="0x" + "0" * 40,  # 简化的接收者地址
                nonce=i,
                signature=b"test_signature",  # 简化的签名
                value=[tx_value],  # value应该是列表
                time=f"2024-01-01T00:00:{i:02d}"  # 简化的时间戳
            )

            # 创建真实的MultiTransactions，包含sender和multi_txns参数
            owner_multi_txns = MultiTransactions(sender=owner, multi_txns=[real_tx])

            # 创建简单的MerkleTreeProof
            owner_mt_proof = MerkleTreeProof([f"0x{'0'*63}{j:01x}" for j in range(2)])

            # 创建真实的ProofUnit
            unit_id = f"0x{'0'*63}{i:01x}"  # 64字符hex
            proof_unit = ProofUnit(
                owner=owner,
                owner_multi_txns=owner_multi_txns,
                owner_mt_proof=owner_mt_proof,
                unit_id=unit_id
            )

            proof_units.append(proof_unit)

        return proof_units

    @staticmethod
    def create_block_index_list(indexes: List[int], owners: List[Tuple[int, str]]) -> BlockIndexList:
        """创建BlockIndexList对象"""
        return BlockIndexList(indexes, owners)

    @staticmethod
    def create_realistic_bloom_filters(block_heights: List[int],
                                     additional_transactions: Dict[int, List[str]]) -> Dict[int, BloomFilter]:
        """创建真实的布隆过滤器模拟"""
        bloom_filters = {}

        for height in block_heights:
            bloom_filter = BloomFilter(size=1024, hash_count=3)

            # 添加在该区块提交交易的sender地址
            if height in additional_transactions:
                for sender_address in additional_transactions[height]:
                    bloom_filter.add(sender_address)

            bloom_filters[height] = bloom_filter

        return bloom_filters

    @staticmethod
    def create_main_chain_info(merkle_roots: Dict[int, str],
                             bloom_filters: Dict[int, Any],
                             current_block_height: int) -> MainChainInfo:
        """创建主链信息"""
        return MainChainInfo(
            merkle_roots=merkle_roots,
            bloom_filters=bloom_filters,
            current_block_height=current_block_height
        )


class TestCase1_SimpleNormalWithCheckpoint:
    """案例1：简单正常交易，有checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例1的测试数据"""
        # 目标value
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")

        # 区块索引列表 - 包含全量编号[0,8,15,16,25,27,55,56,58]
        # 根据VPB_test_demo.md，block_index_list.index_lst应该包含所有相关区块，不仅仅是所有权变更的区块
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value
                (58, bob_addr)      # 区块58：bob从dave处接收目标value
            ]
        )

        # 创建对应的proofs - 需要9个proof units对应9个区块
        proofs = VPBTestDataGenerator.create_mock_proofs(9, target_value.begin_index)

        # 配置每个proof unit的交易数据
        self._setup_proof_transactions(proofs, target_value)

        # 创建主链信息
        additional_transactions = {
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr], 58: [dave_addr]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value': target_value,
            'proofs': proofs,
            'block_index_list': block_index_list,
            'main_chain_info': main_chain_info,
            'account_address': bob_addr,  # bob在区块58从dave处接收value
            'expected_checkpoint_height': 26,  # bob在区块27将value转移给charlie前的checkpoint
            'expected_start_block': 27  # 验证应该从区块27开始
        }

    def _setup_proof_transactions(self, proofs: Mock, target_value: Value):
        """设置proof unit的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            """创建测试交易"""
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # 创建地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")

        # 配置每个proof unit - 对应9个区块
        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [],  # 创世块没有交易
            [],  # 区块8：alice进行其他交易（非目标value）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value）
            [],  # 区块25：bob进行其他交易（非目标value）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, bob_addr, target_value)]  # 区块58：dave->bob
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case1_execution(self, test_data):
        """执行案例1测试"""
        TestOutputManager.print_case_header("案例1：简单正常交易（有checkpoint）")

        # 创建带checkpoint的验证器
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                TestOutputManager.print_info("创建checkpoint...")
                # 创建checkpoint：bob在区块27将value转移给charlie前的状态
                checkpoint.save_checkpoint(
                    test_data['target_value'],
                    test_data['account_address'],
                    test_data['expected_checkpoint_height']
                )

                TestOutputManager.print_info("执行VPB验证...")
                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    convert_proofs_to_proof_units(test_data['proofs']),
                    test_data['block_index_list'],
                    test_data['main_chain_info'],
                    test_data['account_address']
                )

                # 验证结果
                assert report.result == VerificationResult.SUCCESS
                assert report.is_valid == True
                assert len(report.errors) == 0

                # 验证checkpoint被正确使用
                assert report.checkpoint_used is not None
                assert report.checkpoint_used.block_height == test_data['expected_checkpoint_height']
                assert report.checkpoint_used.owner_address == test_data['account_address']

                # 验证验证时间
                assert report.verification_time_ms >= 0

                TestOutputManager.print_verification_summary(report, "简单正常交易+检查点")
                TestOutputManager.print_success("案例1验证通过")

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass


class TestCase2_SimpleNormalWithoutCheckpoint:
    """案例2：简单正常交易，无checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例2的测试数据"""
        # 目标value
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        eve_addr = VPBTestDataGenerator.create_eth_address("eve")

        # 区块索引列表 - 包含全量编号[0,8,15,16,25,27,55,56,58]
        # 根据VPB_test_demo.md，block_index_list.index_lst应该包含所有相关区块
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [ # owner list
                (0, alice_addr),    # 创世块：alice获得目标value
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value
                (58, eve_addr)      # 区块58：eve从dave处接收目标value（eve没有checkpoint）
            ]
        )

        # 创建对应的proofs - 需要9个proof units对应9个区块
        proofs = VPBTestDataGenerator.create_mock_proofs(9, target_value.begin_index)

        # 配置交易数据（eve是新的验证者）
        self._setup_proof_transactions(proofs, target_value)

        # 创建主链信息
        additional_transactions = {
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr], 58: [dave_addr]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value': target_value,
            'proofs': proofs,
            'block_index_list': block_index_list,
            'main_chain_info': main_chain_info,
            'account_address': eve_addr,  # eve从dave处接收value，没有checkpoint
            'expected_start_block': 0  # 验证应该从创世块开始
        }

    def _setup_proof_transactions(self, proofs: Mock, target_value: Value):
        """设置proof unit的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # 生成有效的以太坊地址（与test_data中的地址保持一致）
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        eve_addr = VPBTestDataGenerator.create_eth_address("eve")

        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice value派发
            [],  # 区块8：alice进行其他交易（非目标value）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value）
            [],  # 区块25：bob进行其他交易（非目标value）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, eve_addr, target_value)]  # 区块58：dave->eve
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case2_execution(self, test_data):
        """执行案例2测试"""
        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        # 执行验证
        report = validator.verify_vpb_pair(
            test_data['target_value'],
            convert_proofs_to_proof_units(test_data['proofs']),
            test_data['block_index_list'],
            test_data['main_chain_info'],
            test_data['account_address']
        )

        # 验证结果
        assert report.result == VerificationResult.SUCCESS
        assert report.is_valid == True
        assert len(report.errors) == 0

        # 验证没有使用checkpoint
        assert report.checkpoint_used is None

        # 验证验证时间
        assert report.verification_time_ms >= 0

        print(f"案例2验证成功:")
        print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
        print(f"  - 使用checkpoint: 无")
        print(f"  - 验证epoch: {report.verified_epochs}")


class TestCase3_SimpleDoubleSpendWithCheckpoint:
    """案例3：简单双花交易，有checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例3的测试数据"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 正常的交易路径，但dave在区块57进行了双花（恶意节点会隐藏区块57）
        # 注意：block_index_list不包含区块57，因为dave恶意隐藏了双花区块
        # 同时，proofs也不包含区块57对应的proof unit
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],  # 缺少区块57，只有8个区块
            [
                (0, "0x1234567890abcdef1234567890abcdef12345678"),    # 创世块：alice获得目标value
                (8, "0x1234567890abcdef1234567890abcdef12345678"),    # 区块8：alice进行其他交易（非目标value）
                (15, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块15：bob从alice处接收目标value
                (16, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块16：bob进行其他交易（非目标value）
                (25, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块25：bob进行其他交易（非目标value）
                (27, "0x567890abcdef1234567890abcdef1234567890ab"), # 区块27：charlie从bob处接收目标value
                (55, "0x567890abcdef1234567890abcdef1234567890ab"), # 区块55：charlie进行其他交易（非目标value）
                (56, "0x7890abcdef1234567890abcdef1234567890abcd"),    # 区块56：dave从charlie处接收目标value
                # 这里故意跳过区块57，因为被恶意节点隐藏
                (58, "0xabcdef1234567890abcdef1234567890abcdef12")      # 区块58：bob从dave处接收目标value（注意：这是非法的，因为dave在隐藏的区块57已经双花）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(9)  # 9个proof units对应9个区块（区块57被隐藏）

        # 设置交易数据，包括双花（恶意节点隐藏区块57）
        self._setup_proof_transactions_with_double_spend_case3(proofs, target_value)

        # 创建主链信息 - 包含区块57（用于检测双花）
        additional_transactions = {
            8: ["0x1234567890abcdef1234567890abcdef12345678"], 15: ["0x1234567890abcdef1234567890abcdef12345678"], 16: ["0xabcdef1234567890abcdef1234567890abcdef12"], 25: ["0xabcdef1234567890abcdef1234567890abcdef12"],
            27: ["0xabcdef1234567890abcdef1234567890abcdef12"], 55: ["0x567890abcdef1234567890abcdef1234567890ab"], 56: ["0x567890abcdef1234567890abcdef1234567890ab"],
            57: ["0x7890abcdef1234567890abcdef1234567890abcd"], 58: ["0x7890abcdef1234567890abcdef1234567890abcd"]  # dave在区块57和58都有交易
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 57, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value': target_value,
            'proofs': proofs,
            'block_index_list': block_index_list,
            'main_chain_info': main_chain_info,
            'account_address': "0xabcdef1234567890abcdef1234567890abcdef12",
            'expected_checkpoint_height': 26,
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_proof_transactions_with_double_spend_case3(self, proofs: Mock, target_value: Value):
        """设置案例3包含双花的交易数据（恶意节点隐藏区块57）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # 案例3：恶意节点dave隐藏了区块57的双花交易，所以有9个proof units对应9个区块
        # 完整路径应该是[0, 8, 15, 16, 25, 27, 55, 56, 57, 58]，但区块57被隐藏
        actual_block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]  # 实际包含在VPB中的区块（跳过57）
        transactions = [
            [],  # 创世块
            [],  # 区块8：alice进行其他交易（非目标value）
            [create_test_transaction("0x1234567890abcdef1234567890abcdef12345678", "0xabcdef1234567890abcdef1234567890abcdef12", target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value）
            [],  # 区块25：bob进行其他交易（非目标value）
            [create_test_transaction("0xabcdef1234567890abcdef1234567890abcdef12", "0x567890abcdef1234567890abcdef1234567890ab", target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value）
            [create_test_transaction("0x567890abcdef1234567890abcdef1234567890ab", "0x7890abcdef1234567890abcdef1234567890abcd", target_value)],  # 区块56：charlie->dave
            [create_test_transaction("0x7890abcdef1234567890abcdef1234567890abcd", "0xabcdef1234567890abcdef1234567890abcdef12", target_value)]  # 区块58：dave->bob（注意：这是非法的，因为dave在区块57已经双花）
        ]

        # 设置9个proof units对应9个区块
        for i, (height, txs) in enumerate(zip(actual_block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height

            # 设置验证结果：最后一个proof unit（区块58）应该验证失败，因为dave在区块57已经双花了
            if height == 58:  # 区块58的交易是非法的，因为dave在区块57已经双花
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(
                    False,
                    "Double spend detected: value already spent in block 57 by dave"
                ))
            else:
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case3_execution(self, test_data):
        """执行案例3测试"""
        TestOutputManager.print_case_header("案例3：简单双花交易（有checkpoint）")

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                TestOutputManager.print_info("创建checkpoint...")
                # 创建checkpoint
                checkpoint.save_checkpoint(
                    test_data['target_value'],
                    "0xabcdef1234567890abcdef1234567890abcdef12",
                    test_data['expected_checkpoint_height']
                )

                TestOutputManager.print_info("执行VPB验证（预期检测到双花）...")
                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    convert_proofs_to_proof_units(test_data['proofs']),
                    test_data['block_index_list'],
                    test_data['main_chain_info'],
                    test_data['account_address']
                )

                # 验证结果：应该检测到双花
                assert report.result == VerificationResult.FAILURE
                assert report.is_valid == False
                assert len(report.errors) > 0

                # 验证包含双花错误
                double_spend_errors = [err for err in report.errors
                                     if "double spend" in err.error_message.lower()]
                assert len(double_spend_errors) > 0

                TestOutputManager.print_verification_summary(report, "双花攻击检测")

                # 特殊显示双花检测结果
                print(f"\n【安全检测结果】")
                if double_spend_errors:
                    TestOutputManager.print_success(f"检测到 {len(double_spend_errors)} 个双花攻击")
                    TestOutputManager.print_info(f"攻击类型：恶意节点在隐藏区块57进行双花", indent=3)
                else:
                    TestOutputManager.print_failure("未能检测到双花攻击")

                # 显示其他安全威胁
                other_errors = [err for err in report.errors if "double spend" not in err.error_message.lower()]
                if other_errors:
                    TestOutputManager.print_info(f"同时检测到 {len(other_errors)} 个其他安全威胁:", indent=3)
                    for i, error in enumerate(other_errors, 1):
                        TestOutputManager.print_info(f"{i}. {error.error_type}", indent=4)

                TestOutputManager.print_success("案例3验证通过 - 双花攻击检测成功")

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass


class TestCase4_SimpleDoubleSpendWithoutCheckpoint:
    """案例4：简单双花交易，无checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例4的测试数据"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 正常的交易路径，但dave在区块57进行了双花（恶意节点会隐藏区块57）
        # 验证者frank没有checkpoint
        # 注意：block_index_list不包含区块57，因为dave恶意隐藏了双花区块
        # 同时，proofs也不包含区块57对应的proof unit
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],  # 缺少区块57，只有8个区块
            [
                (0, "0x1234567890abcdef1234567890abcdef12345678"),    # 创世块：alice获得目标value
                (8, "0x1234567890abcdef1234567890abcdef12345678"),    # 区块8：alice进行其他交易（非目标value）
                (15, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块15：bob从alice处接收目标value
                (16, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块16：bob进行其他交易（非目标value）
                (25, "0xabcdef1234567890abcdef1234567890abcdef12"),     # 区块25：bob进行其他交易（非目标value）
                (27, "0x567890abcdef1234567890abcdef1234567890ab"), # 区块27：charlie从bob处接收目标value
                (55, "0x567890abcdef1234567890abcdef1234567890ab"), # 区块55：charlie进行其他交易（非目标value）
                (56, "0x7890abcdef1234567890abcdef1234567890abcd"),    # 区块56：dave从charlie处接收目标value
                # 区块57被恶意节点隐藏
                (58, "0xdef0123456789abcdef1234567890abcdef12345")    # 区块58：frank从dave处接收目标value（frank没有checkpoint）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(9)  # 9个proof units对应9个区块（区块57被隐藏）

        # 设置交易数据，包括双花（验证者是frank）
        self._setup_proof_transactions_with_double_spend(proofs, target_value)

        # 创建主链信息
        additional_transactions = {
            8: ["0x1234567890abcdef1234567890abcdef12345678"], 15: ["0x1234567890abcdef1234567890abcdef12345678"], 16: ["0xabcdef1234567890abcdef1234567890abcdef12"], 25: ["0xabcdef1234567890abcdef1234567890abcdef12"],
            27: ["0xabcdef1234567890abcdef1234567890abcdef12"], 55: ["0x567890abcdef1234567890abcdef1234567890ab"], 56: ["0x567890abcdef1234567890abcdef1234567890ab"],
            57: ["0x7890abcdef1234567890abcdef1234567890abcd"], 58: ["0x7890abcdef1234567890abcdef1234567890abcd"]  # dave在区块57和58都有交易
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 57, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value': target_value,
            'proofs': proofs,
            'block_index_list': block_index_list,
            'main_chain_info': main_chain_info,
            'account_address': "0xdef0123456789abcdef1234567890abcdef12345",  # frank从dave处接收value，没有checkpoint
            'expected_start_block': 0,  # 验证应该从创世块开始
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_proof_transactions_with_double_spend(self, proofs: Mock, target_value: Value):
        """设置案例4包含双花的交易数据（恶意节点隐藏区块57，验证者是frank）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # 案例4：恶意节点dave隐藏了区块57的双花交易，所以只有8个proof units对应8个区块
        # 完整路径应该是[0, 8, 15, 16, 25, 27, 55, 56, 57, 58]，但区块57被隐藏
        actual_block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]  # 实际包含在VPB中的区块
        transactions = [
            [],  # 创世块
            [],  # 区块8：alice进行其他交易（非目标value）
            [create_test_transaction("0x1234567890abcdef1234567890abcdef12345678", "0xabcdef1234567890abcdef1234567890abcdef12", target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value）
            [],  # 区块25：bob进行其他交易（非目标value）
            [create_test_transaction("0xabcdef1234567890abcdef1234567890abcdef12", "0x567890abcdef1234567890abcdef1234567890ab", target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value）
            [create_test_transaction("0x567890abcdef1234567890abcdef1234567890ab", "0x7890abcdef1234567890abcdef1234567890abcd", target_value)],  # 区块56：charlie->dave
            [create_test_transaction("0x7890abcdef1234567890abcdef1234567890abcd", "0xdef0123456789abcdef1234567890abcdef12345", target_value)]  # 区块58：dave->frank（注意：这是非法的，因为dave在区块57已经双花）
        ]

        # 设置9个proof units对应9个区块
        for i, (height, txs) in enumerate(zip(actual_block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height

            # 设置验证结果：最后一个proof unit（区块58）应该验证失败，因为dave在区块57已经双花了
            if height == 58:  # 区块58的交易是非法的，因为dave在区块57已经双花
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(
                    False,
                    "Double spend detected: value already spent in block 57 by dave"
                ))
            else:
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case4_execution(self, test_data):
        """执行案例4测试"""
        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        # 执行验证
        report = validator.verify_vpb_pair(
            test_data['target_value'],
            convert_proofs_to_proof_units(test_data['proofs']),
            test_data['block_index_list'],
            test_data['main_chain_info'],
            test_data['account_address']
        )

        # 验证结果：应该检测到双花
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) > 0

        # 验证包含双花错误
        double_spend_errors = [err for err in report.errors
                             if "double spend" in err.error_message.lower()]
        assert len(double_spend_errors) > 0

        # 验证没有使用checkpoint
        assert report.checkpoint_used is None

        print(f"案例4验证成功（检测到双花，无checkpoint）:")
        print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
        print(f"  - 使用checkpoint: 无")
        print(f"  - 错误数量: {len(report.errors)}")
        for error in report.errors:
            print(f"    - {error.error_type}: {error.error_message}")


class TestCase5_CombinedNormalWithCheckpoint:
    """案例5：组合正常交易，有checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例5的测试数据（真正的组合交易）"""
        # 根据VPB_test_demo.md案例5，这是dave->qian的组合交易，包含两个value

        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)  # value_1: alice->bob->charlie->dave->qian
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)  # value_2: zhao->qian->sun->dave->qian

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        zhao_addr = VPBTestDataGenerator.create_eth_address("zhao")
        qian_addr = VPBTestDataGenerator.create_eth_address("qian")
        sun_addr = VPBTestDataGenerator.create_eth_address("sun")

        # 根据VPB_test_demo.md，value_1的完整路径包含全量编号[0,8,15,16,25,27,55,56,58]
        # 这是目标value_1的block_index_list
        block_index_list_1 = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value_1
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value_1）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value_1
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value_1）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value_1）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value_1
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value_1）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value_1
                (58, qian_addr)     # 区块58：qian从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 根据VPB_test_demo.md，value_2的完整路径包含全量编号[0,3,5,17,38,39,58]
        # 这是目标value_2的block_index_list
        block_index_list_2 = VPBTestDataGenerator.create_block_index_list(
            [0, 3, 5, 17, 38, 39, 58],
            [
                (0, zhao_addr),     # 创世块：zhao获得目标value_2
                (3, zhao_addr),     # 区块3：zhao进行其他交易（非目标value_2）
                (5, qian_addr),     # 区块5：qian从zhao处接收目标value_2
                (17, qian_addr),    # 区块17：qian进行其他交易（非目标value_2）
                (38, sun_addr),     # 区块38：sun从qian处接收目标value_2
                (39, dave_addr),    # 区块39：dave从sun处接收目标value_2
                (58, qian_addr)     # 区块58：qian从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 创建对应的proofs
        proofs_1 = VPBTestDataGenerator.create_mock_proofs(9, target_value_1.begin_index)  # value_1需要9个proof units
        proofs_2 = VPBTestDataGenerator.create_mock_proofs(7, target_value_2.begin_index)  # value_2需要7个proof units

        # 配置每个proof unit的交易数据
        self._setup_value1_transactions(proofs_1, target_value_1, alice_addr, bob_addr, charlie_addr, dave_addr, qian_addr)
        self._setup_value2_transactions(proofs_2, target_value_2, zhao_addr, qian_addr, sun_addr, dave_addr, qian_addr)

        # 创建主链信息 - 包含所有区块
        additional_transactions = {
            # value_1相关的交易
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr],
            # value_2相关的交易
            3: [zhao_addr], 5: [zhao_addr], 17: [qian_addr], 38: [qian_addr], 39: [sun_addr],
            # 组合交易
            58: [dave_addr]  # dave向qian进行组合支付
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value_1': target_value_1,
            'target_value_2': target_value_2,
            'proofs_1': proofs_1,
            'proofs_2': proofs_2,
            'block_index_list_1': block_index_list_1,
            'block_index_list_2': block_index_list_2,
            'main_chain_info': main_chain_info,
            'account_address': qian_addr,  # qian在区块58从dave处接收组合支付
            'expected_checkpoint_height': 37,  # qian的checkpoint：区块38前（qian曾拥有过value_2）
            'expected_start_block_value1': 0,  # value_1从头开始验证
            'expected_start_block_value2': 38  # value_2从区块38开始验证（使用checkpoint）
        }

    def _setup_value1_transactions(self, proofs: Mock, target_value: Value, alice_addr: str,
                                  bob_addr: str, charlie_addr: str, dave_addr: str, qian_addr: str):
        """设置value_1的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_1的完整路径：[0,8,15,16,25,27,55,56,58]
        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice value_1分配
            [],  # 区块8：alice进行其他交易（非目标value_1）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value_1）
            [],  # 区块25：bob进行其他交易（非目标value_1）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value_1）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, qian_addr, target_value)]  # 区块58：dave->qian（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def _setup_value2_transactions(self, proofs: Mock, target_value: Value, zhao_addr: str,
                                  qian_addr: str, sun_addr: str, dave_addr: str, qian_addr_final: str):
        """设置value_2的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_2的完整路径：[0,3,5,17,38,39,58]
        block_heights = [0, 3, 5, 17, 38, 39, 58]
        transactions = [
            [create_test_transaction("GOD", zhao_addr, target_value)],  # 创世块：GOD->zhao value_2分配
            [],  # 区块3：zhao进行其他交易（非目标value_2）
            [create_test_transaction(zhao_addr, qian_addr, target_value)],  # 区块5：zhao->qian
            [],  # 区块17：qian进行其他交易（非目标value_2）
            [create_test_transaction(qian_addr, sun_addr, target_value)],  # 区块38：qian->sun
            [create_test_transaction(sun_addr, dave_addr, target_value)],  # 区块39：sun->dave
            [create_test_transaction(dave_addr, qian_addr_final, target_value)]  # 区块58：dave->qian（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case5_execution(self, test_data):
        """执行案例5测试（真正的组合交易验证）"""
        TestOutputManager.print_case_header("案例5：组合正常交易（有checkpoint）")

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                TestOutputManager.print_info("创建qian的checkpoint...")
                # 创建checkpoint：qian在区块38前的状态（针对value_2）
                # qian在区块38将value_2转移给sun，所以在区块37有checkpoint
                checkpoint.save_checkpoint(
                    test_data['target_value_2'],  # 为value_2创建checkpoint
                    test_data['account_address'],  # qian的地址
                    test_data['expected_checkpoint_height']  # 区块37
                )

                TestOutputManager.print_info("验证组合交易中的value_1（从头开始验证）...")
                # 验证value_1：qian没有value_1的历史，所以从头开始验证
                report_1 = validator.verify_vpb_pair(
                    test_data['target_value_1'],
                    convert_proofs_to_proof_units(test_data['proofs_1']),
                    test_data['block_index_list_1'],
                    test_data['main_chain_info'],
                    test_data['account_address']  # qian验证value_1
                )

                TestOutputManager.print_info("验证组合交易中的value_2（使用checkpoint）...")
                # 验证value_2：qian有checkpoint，所以从区块38开始验证
                report_2 = validator.verify_vpb_pair(
                    test_data['target_value_2'],
                    convert_proofs_to_proof_units(test_data['proofs_2']),
                    test_data['block_index_list_2'],
                    test_data['main_chain_info'],
                    test_data['account_address']  # qian验证value_2
                )

                # 验证结果：两个value都应该验证成功
                assert report_1.result == VerificationResult.SUCCESS
                assert report_1.is_valid == True
                assert len(report_1.errors) == 0
                # value_1不应该使用checkpoint（qian没有value_1的历史）
                assert report_1.checkpoint_used is None

                assert report_2.result == VerificationResult.SUCCESS
                assert report_2.is_valid == True
                assert len(report_2.errors) == 0
                # value_2应该使用checkpoint（qian有value_2的历史）
                assert report_2.checkpoint_used is not None
                assert report_2.checkpoint_used.block_height == test_data['expected_checkpoint_height']
                assert report_2.checkpoint_used.owner_address == test_data['account_address']

                # 验证验证时间
                assert report_1.verification_time_ms >= 0
                assert report_2.verification_time_ms >= 0

                # 打印详细的验证结果
                TestOutputManager.print_verification_summary(report_1, "value_1验证")
                TestOutputManager.print_verification_summary(report_2, "value_2验证")

                TestOutputManager.print_success("案例5验证通过 - 组合交易验证成功")
                TestOutputManager.print_info(f"dave->qian组合交易验证完成", indent=2)
                TestOutputManager.print_info(f"value_1 (alice->bob->charlie->dave->qian): 从头验证", indent=3)
                TestOutputManager.print_info(f"value_2 (zhao->qian->sun->dave->qian): 从区块38开始验证", indent=3)

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass


class TestCase6_CombinedNormalWithoutCheckpoint:
    """案例6：组合正常交易，无checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例6的测试数据（组合交易，无checkpoint）"""
        # 根据VPB_test_demo.md案例6，这是dave->eve的组合交易，包含两个value
        # 目标value_1：alice->bob->charlie->dave->eve
        # 目标value_2：zhao->qian->sun->dave->eve

        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)  # value_1: alice->bob->charlie->dave->eve
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)  # value_2: zhao->qian->sun->dave->eve

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        zhao_addr = VPBTestDataGenerator.create_eth_address("zhao")
        qian_addr = VPBTestDataGenerator.create_eth_address("qian")
        sun_addr = VPBTestDataGenerator.create_eth_address("sun")
        eve_addr = VPBTestDataGenerator.create_eth_address("eve")

        # 根据VPB_test_demo.md，value_1的完整路径包含全量编号[0,8,15,16,25,27,55,56,58]
        # 这是目标value_1的block_index_list
        block_index_list_1 = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value_1
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value_1）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value_1
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value_1）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value_1）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value_1
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value_1）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value_1
                (58, eve_addr)      # 区块58：eve从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 根据VPB_test_demo.md，value_2的完整路径包含全量编号[0,3,5,17,38,39,58]
        # 这是目标value_2的block_index_list
        block_index_list_2 = VPBTestDataGenerator.create_block_index_list(
            [0, 3, 5, 17, 38, 39, 58],
            [
                (0, zhao_addr),     # 创世块：zhao获得目标value_2
                (3, zhao_addr),     # 区块3：zhao进行其他交易（非目标value_2）
                (5, qian_addr),     # 区块5：qian从zhao处接收目标value_2
                (17, qian_addr),    # 区块17：qian进行其他交易（非目标value_2）
                (38, sun_addr),     # 区块38：sun从qian处接收目标value_2
                (39, dave_addr),    # 区块39：dave从sun处接收目标value_2
                (58, eve_addr)      # 区块58：eve从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 创建对应的proofs
        proofs_1 = VPBTestDataGenerator.create_mock_proofs(9, target_value_1.begin_index)  # value_1需要9个proof units
        proofs_2 = VPBTestDataGenerator.create_mock_proofs(7, target_value_2.begin_index)  # value_2需要7个proof units

        # 配置每个proof unit的交易数据
        self._setup_value1_transactions_case6(proofs_1, target_value_1, alice_addr, bob_addr, charlie_addr, dave_addr, eve_addr)
        self._setup_value2_transactions_case6(proofs_2, target_value_2, zhao_addr, qian_addr, sun_addr, dave_addr, eve_addr)

        # 创建主链信息 - 包含所有区块
        additional_transactions = {
            # value_1相关的交易
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr],
            # value_2相关的交易
            3: [zhao_addr], 5: [zhao_addr], 17: [qian_addr], 38: [qian_addr], 39: [sun_addr],
            # 组合交易
            58: [dave_addr]  # dave向eve进行组合支付
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value_1': target_value_1,
            'target_value_2': target_value_2,
            'proofs_1': proofs_1,
            'proofs_2': proofs_2,
            'block_index_list_1': block_index_list_1,
            'block_index_list_2': block_index_list_2,
            'main_chain_info': main_chain_info,
            'account_address': eve_addr,  # eve在区块58从dave处接收组合支付，没有checkpoint
            'expected_start_block_value1': 0,  # value_1从头开始验证
            'expected_start_block_value2': 0   # value_2从头开始验证（eve没有checkpoint）
        }

    def _setup_value1_transactions_case6(self, proofs: Mock, target_value: Value, alice_addr: str,
                                         bob_addr: str, charlie_addr: str, dave_addr: str, eve_addr: str):
        """设置案例6中value_1的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_1的完整路径：[0,8,15,16,25,27,55,56,58]
        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice value_1分配
            [],  # 区块8：alice进行其他交易（非目标value_1）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value_1）
            [],  # 区块25：bob进行其他交易（非目标value_1）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value_1）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, eve_addr, target_value)]  # 区块58：dave->eve（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def _setup_value2_transactions_case6(self, proofs: Mock, target_value: Value, zhao_addr: str,
                                         qian_addr: str, sun_addr: str, dave_addr: str, eve_addr: str):
        """设置案例6中value_2的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_2的完整路径：[0,3,5,17,38,39,58]
        block_heights = [0, 3, 5, 17, 38, 39, 58]
        transactions = [
            [create_test_transaction("GOD", zhao_addr, target_value)],  # 创世块：GOD->zhao value_2分配
            [],  # 区块3：zhao进行其他交易（非目标value_2）
            [create_test_transaction(zhao_addr, qian_addr, target_value)],  # 区块5：zhao->qian
            [],  # 区块17：qian进行其他交易（非目标value_2）
            [create_test_transaction(qian_addr, sun_addr, target_value)],  # 区块38：qian->sun
            [create_test_transaction(sun_addr, dave_addr, target_value)],  # 区块39：sun->dave
            [create_test_transaction(dave_addr, eve_addr, target_value)]  # 区块58：dave->eve（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case6_execution(self, test_data):
        """执行案例6测试（组合交易，无checkpoint）"""
        TestOutputManager.print_case_header("案例6：组合正常交易（无checkpoint）")

        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        TestOutputManager.print_info("验证组合交易中的value_1（从头开始验证）...")
        # 验证value_1：eve没有value_1的历史，所以从头开始验证
        report_1 = validator.verify_vpb_pair(
            test_data['target_value_1'],
            convert_proofs_to_proof_units(test_data['proofs_1']),
            test_data['block_index_list_1'],
            test_data['main_chain_info'],
            test_data['account_address']  # eve验证value_1
        )

        TestOutputManager.print_info("验证组合交易中的value_2（从头开始验证）...")
        # 验证value_2：eve没有value_2的历史，所以从头开始验证
        report_2 = validator.verify_vpb_pair(
            test_data['target_value_2'],
            convert_proofs_to_proof_units(test_data['proofs_2']),
            test_data['block_index_list_2'],
            test_data['main_chain_info'],
            test_data['account_address']  # eve验证value_2
        )

        # 验证结果：两个value都应该验证成功
        assert report_1.result == VerificationResult.SUCCESS
        assert report_1.is_valid == True
        assert len(report_1.errors) == 0
        # value_1不应该使用checkpoint（eve没有value_1的历史）
        assert report_1.checkpoint_used is None

        assert report_2.result == VerificationResult.SUCCESS
        assert report_2.is_valid == True
        assert len(report_2.errors) == 0
        # value_2不应该使用checkpoint（eve没有value_2的历史）
        assert report_2.checkpoint_used is None

        # 验证验证时间
        assert report_1.verification_time_ms >= 0
        assert report_2.verification_time_ms >= 0

        # 打印详细的验证结果
        TestOutputManager.print_verification_summary(report_1, "value_1验证")
        TestOutputManager.print_verification_summary(report_2, "value_2验证")

        TestOutputManager.print_success("案例6验证通过 - 组合交易验证成功")
        TestOutputManager.print_info(f"dave->eve组合交易验证完成", indent=2)
        TestOutputManager.print_info(f"value_1 (alice->bob->charlie->dave->eve): 从头验证", indent=3)
        TestOutputManager.print_info(f"value_2 (zhao->qian->sun->dave->eve): 从头验证", indent=3)


class TestCase7_CombinedDoubleSpendWithCheckpoint:
    """案例7：组合双花交易，有checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例7的测试数据（组合双花交易，有checkpoint）"""
        # 根据VPB_test_demo.md案例7，这是dave->sun的组合交易，dave在区块46对value_2进行了双花
        # 目标value_1：alice->bob->charlie->dave->sun（正常路径）
        # 目标value_2：zhao->qian->sun->dave->(双花给x)->dave->sun（双花路径）

        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)  # value_1: alice->bob->charlie->dave->sun
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)  # value_2: zhao->qian->sun->dave->x（双花）->sun

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        zhao_addr = VPBTestDataGenerator.create_eth_address("zhao")
        qian_addr = VPBTestDataGenerator.create_eth_address("qian")
        sun_addr = VPBTestDataGenerator.create_eth_address("sun")
        x_addr = VPBTestDataGenerator.create_eth_address("x")  # dave的同伙

        # 根据VPB_test_demo.md，value_1的完整路径包含全量编号[0,8,15,16,25,27,55,56,58]
        # 这是目标value_1的block_index_list（正常路径，无双花）
        block_index_list_1 = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value_1
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value_1）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value_1
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value_1）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value_1）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value_1
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value_1）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value_1
                (58, sun_addr)      # 区块58：sun从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 根据VPB_test_demo.md，value_2的完整路径包含全量编号[0,3,5,17,38,39,58]
        # 注意：区块46被恶意节点隐藏，因为dave在那里进行了双花
        block_index_list_2 = VPBTestDataGenerator.create_block_index_list(
            [0, 3, 5, 17, 38, 39, 58],  # 故意跳过区块46（双花被隐藏）
            [
                (0, zhao_addr),     # 创世块：zhao获得目标value_2
                (3, zhao_addr),     # 区块3：zhao进行其他交易（非目标value_2）
                (5, qian_addr),     # 区块5：qian从zhao处接收目标value_2
                (17, qian_addr),    # 区块17：qian进行其他交易（非目标value_2）
                (38, sun_addr),     # 区块38：sun从qian处接收目标value_2
                (39, dave_addr),    # 区块39：dave从sun处接收目标value_2
                (58, sun_addr)      # 区块58：sun从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 创建对应的proofs
        proofs_1 = VPBTestDataGenerator.create_mock_proofs(9, target_value_1.begin_index)  # value_1需要9个proof units
        proofs_2 = VPBTestDataGenerator.create_mock_proofs(7, target_value_2.begin_index)  # value_2需要7个proof units（跳过区块46）

        # 配置每个proof unit的交易数据
        self._setup_value1_transactions_case7(proofs_1, target_value_1, alice_addr, bob_addr, charlie_addr, dave_addr, sun_addr)
        self._setup_value2_transactions_case7(proofs_2, target_value_2, zhao_addr, qian_addr, sun_addr, dave_addr, sun_addr, x_addr)

        # 创建主链信息 - 包含所有区块，包括隐藏的双花区块46
        additional_transactions = {
            # value_1相关的交易
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr],
            # value_2相关的交易
            3: [zhao_addr], 5: [zhao_addr], 17: [qian_addr], 38: [qian_addr], 39: [sun_addr],
            # 双花交易（被恶意节点隐藏，但在主链信息中存在）
            46: [dave_addr],  # dave在区块46向同伙x进行双花交易
            # 组合交易
            58: [dave_addr]  # dave向sun进行组合支付
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 46, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 46, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value_1': target_value_1,
            'target_value_2': target_value_2,
            'proofs_1': proofs_1,
            'proofs_2': proofs_2,
            'block_index_list_1': block_index_list_1,
            'block_index_list_2': block_index_list_2,
            'main_chain_info': main_chain_info,
            'account_address': sun_addr,  # sun在区块58从dave处接收组合支付，有checkpoint
            'expected_checkpoint_height': 37,  # sun的checkpoint：区块38前（sun曾拥有过value_2）
            'expected_start_block_value1': 0,  # value_1从头开始验证
            'expected_start_block_value2': 38, # value_2从区块38开始验证（使用checkpoint）
            'double_spend_block': 46  # dave在区块46进行双花
        }

    def _setup_value1_transactions_case7(self, proofs: Mock, target_value: Value, alice_addr: str,
                                         bob_addr: str, charlie_addr: str, dave_addr: str, sun_addr: str):
        """设置案例7中value_1的交易数据（正常路径，无双花）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_1的完整路径：[0,8,15,16,25,27,55,56,58]
        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice value_1分配
            [],  # 区块8：alice进行其他交易（非目标value_1）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value_1）
            [],  # 区块25：bob进行其他交易（非目标value_1）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value_1）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, sun_addr, target_value)]  # 区块58：dave->sun（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def _setup_value2_transactions_case7(self, proofs: Mock, target_value: Value, zhao_addr: str,
                                         qian_addr: str, sun_addr: str, dave_addr: str, sun_addr_final: str, x_addr: str):
        """设置案例7中value_2的交易数据（包含双花攻击）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_2的路径：[0,3,5,17,38,39,58]，但dave在区块46进行了双花（被隐藏）
        block_heights = [0, 3, 5, 17, 38, 39, 58]  # 跳过双花区块46
        transactions = [
            [create_test_transaction("GOD", zhao_addr, target_value)],  # 创世块：GOD->zhao value_2分配
            [],  # 区块3：zhao进行其他交易（非目标value_2）
            [create_test_transaction(zhao_addr, qian_addr, target_value)],  # 区块5：zhao->qian
            [],  # 区块17：qian进行其他交易（非目标value_2）
            [create_test_transaction(qian_addr, sun_addr, target_value)],  # 区块38：qian->sun
            [create_test_transaction(sun_addr, dave_addr, target_value)],  # 区块39：sun->dave
            [create_test_transaction(dave_addr, sun_addr_final, target_value)]  # 区块58：dave->sun（组合支付的一部分，但这是非法的，因为dave在区块46已经双花了）
        ]

        # 双花区块信息（dave在区块46将value转移给同伙x）
        double_spend_block = 46

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height

            # 设置验证结果：最后一个proof unit（区块58）应该验证失败，因为dave在区块46已经双花了
            if height == 58:  # 区块58的交易是非法的，因为dave在区块46已经双花
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(
                    False,
                    f"Double spend detected: value already spent in block {double_spend_block} by dave to {x_addr}"
                ))
            else:
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case7_execution(self, test_data):
        """执行案例7测试（组合双花交易，有checkpoint）"""
        TestOutputManager.print_case_header("案例7：组合双花交易（有checkpoint）")

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                TestOutputManager.print_info("创建sun的checkpoint...")
                # 创建checkpoint：sun在区块38前的状态（针对value_2）
                # sun在区块38将value_2转移给dave，所以在区块37有checkpoint
                checkpoint.save_checkpoint(
                    test_data['target_value_2'],  # 为value_2创建checkpoint
                    test_data['account_address'],  # sun的地址
                    test_data['expected_checkpoint_height']  # 区块37
                )

                TestOutputManager.print_info("验证组合交易中的value_1（从头开始验证）...")
                # 验证value_1：sun没有value_1的历史，所以从头开始验证
                report_1 = validator.verify_vpb_pair(
                    test_data['target_value_1'],
                    convert_proofs_to_proof_units(test_data['proofs_1']),
                    test_data['block_index_list_1'],
                    test_data['main_chain_info'],
                    test_data['account_address']  # sun验证value_1
                )

                TestOutputManager.print_info("验证组合交易中的value_2（使用checkpoint）...")
                # 验证value_2：sun有checkpoint，所以从区块38开始验证，应该检测到双花
                report_2 = validator.verify_vpb_pair(
                    test_data['target_value_2'],
                    convert_proofs_to_proof_units(test_data['proofs_2']),
                    test_data['block_index_list_2'],
                    test_data['main_chain_info'],
                    test_data['account_address']  # sun验证value_2
                )

                # 验证value_1结果：应该成功（无双花）
                assert report_1.result == VerificationResult.SUCCESS
                assert report_1.is_valid == True
                assert len(report_1.errors) == 0
                # value_1不应该使用checkpoint（sun没有value_1的历史）
                assert report_1.checkpoint_used is None

                # 验证value_2结果：应该失败（检测到双花）
                assert report_2.result == VerificationResult.FAILURE
                assert report_2.is_valid == False
                assert len(report_2.errors) > 0
                # value_2应该使用checkpoint（sun有value_2的历史）
                assert report_2.checkpoint_used is not None
                assert report_2.checkpoint_used.block_height == test_data['expected_checkpoint_height']
                assert report_2.checkpoint_used.owner_address == test_data['account_address']

                # 验证包含双花错误
                double_spend_errors = [err for err in report_2.errors
                                     if "double spend" in err.error_message.lower()]
                assert len(double_spend_errors) > 0

                # 打印详细的验证结果
                TestOutputManager.print_verification_summary(report_1, "value_1验证")
                TestOutputManager.print_verification_summary(report_2, "value_2验证")

                TestOutputManager.print_success("案例7验证通过 - 组合双花攻击检测成功")
                TestOutputManager.print_info(f"dave->sun组合交易双花检测完成", indent=2)
                TestOutputManager.print_info(f"value_1 (alice->bob->charlie->dave->sun): 验证成功", indent=3)
                TestOutputManager.print_info(f"value_2 (zhao->qian->sun->dave->sun): 检测到双花攻击", indent=3)

                # 特殊显示双花检测结果
                print(f"\n【安全检测结果】")
                if double_spend_errors:
                    TestOutputManager.print_success(f"检测到 {len(double_spend_errors)} 个双花攻击")
                    TestOutputManager.print_info(f"攻击类型：dave在区块46对value_2进行双花", indent=3)
                else:
                    TestOutputManager.print_failure("未能检测到双花攻击")

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass


class TestCase8_CombinedDoubleSpendWithoutCheckpoint:
    """案例8：组合双花交易，无checkpoint"""

    @pytest.fixture
    def test_data(self):
        """设置案例8的测试数据（组合双花交易，无checkpoint）"""
        # 根据VPB_test_demo.md案例8，这是dave->eve的组合交易，dave在区块46对value_2进行了双花
        # 目标value_1：alice->bob->charlie->dave->eve（正常路径）
        # 目标value_2：zhao->qian->sun->dave->(双花给x)->dave->eve（双花路径）

        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)  # value_1: alice->bob->charlie->dave->eve
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)  # value_2: zhao->qian->sun->dave->x（双花）->eve

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")
        zhao_addr = VPBTestDataGenerator.create_eth_address("zhao")
        qian_addr = VPBTestDataGenerator.create_eth_address("qian")
        sun_addr = VPBTestDataGenerator.create_eth_address("sun")
        eve_addr = VPBTestDataGenerator.create_eth_address("eve")
        x_addr = VPBTestDataGenerator.create_eth_address("x")  # dave的同伙

        # 根据VPB_test_demo.md，value_1的完整路径包含全量编号[0,8,15,16,25,27,55,56,58]
        # 这是目标value_1的block_index_list（正常路径，无双花）
        block_index_list_1 = VPBTestDataGenerator.create_block_index_list(
            [0, 8, 15, 16, 25, 27, 55, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value_1
                (8, alice_addr),    # 区块8：alice进行其他交易（非目标value_1）
                (15, bob_addr),     # 区块15：bob从alice处接收目标value_1
                (16, bob_addr),     # 区块16：bob进行其他交易（非目标value_1）
                (25, bob_addr),     # 区块25：bob进行其他交易（非目标value_1）
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value_1
                (55, charlie_addr), # 区块55：charlie进行其他交易（非目标value_1）
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value_1
                (58, eve_addr)      # 区块58：eve从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 根据VPB_test_demo.md，value_2的完整路径包含全量编号[0,3,5,17,38,39,58]
        # 注意：区块46被恶意节点隐藏，因为dave在那里进行了双花
        block_index_list_2 = VPBTestDataGenerator.create_block_index_list(
            [0, 3, 5, 17, 38, 39, 58],  # 故意跳过区块46（双花被隐藏）
            [
                (0, zhao_addr),     # 创世块：zhao获得目标value_2
                (3, zhao_addr),     # 区块3：zhao进行其他交易（非目标value_2）
                (5, qian_addr),     # 区块5：qian从zhao处接收目标value_2
                (17, qian_addr),    # 区块17：qian进行其他交易（非目标value_2）
                (38, sun_addr),     # 区块38：sun从qian处接收目标value_2
                (39, dave_addr),    # 区块39：dave从sun处接收目标value_2
                (58, eve_addr)      # 区块58：eve从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        # 创建对应的proofs
        proofs_1 = VPBTestDataGenerator.create_mock_proofs(9, target_value_1.begin_index)  # value_1需要9个proof units
        proofs_2 = VPBTestDataGenerator.create_mock_proofs(7, target_value_2.begin_index)  # value_2需要7个proof units（跳过区块46）

        # 配置每个proof unit的交易数据
        self._setup_value1_transactions_case8(proofs_1, target_value_1, alice_addr, bob_addr, charlie_addr, dave_addr, eve_addr)
        self._setup_value2_transactions_case8(proofs_2, target_value_2, zhao_addr, qian_addr, sun_addr, dave_addr, eve_addr, x_addr)

        # 创建主链信息 - 包含所有区块，包括隐藏的双花区块46
        additional_transactions = {
            # value_1相关的交易
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr],
            # value_2相关的交易
            3: [zhao_addr], 5: [zhao_addr], 17: [qian_addr], 38: [qian_addr], 39: [sun_addr],
            # 双花交易（被恶意节点隐藏，但在主链信息中存在）
            46: [dave_addr],  # dave在区块46向同伙x进行双花交易
            # 组合交易
            58: [dave_addr]  # dave向eve进行组合支付
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 46, 55, 56, 58], additional_transactions
        )

        main_chain_info = VPBTestDataGenerator.create_main_chain_info(
            {i: f"root{i}" for i in [0, 3, 5, 8, 15, 16, 17, 25, 27, 38, 39, 46, 55, 56, 58]},
            bloom_filters,
            58
        )

        return {
            'target_value_1': target_value_1,
            'target_value_2': target_value_2,
            'proofs_1': proofs_1,
            'proofs_2': proofs_2,
            'block_index_list_1': block_index_list_1,
            'block_index_list_2': block_index_list_2,
            'main_chain_info': main_chain_info,
            'account_address': eve_addr,  # eve在区块58从dave处接收组合支付，没有checkpoint
            'expected_start_block_value1': 0,  # value_1从头开始验证
            'expected_start_block_value2': 0,  # value_2从头开始验证（eve没有checkpoint）
            'double_spend_block': 46  # dave在区块46进行双花
        }

    def _setup_value1_transactions_case8(self, proofs: Mock, target_value: Value, alice_addr: str,
                                         bob_addr: str, charlie_addr: str, dave_addr: str, eve_addr: str):
        """设置案例8中value_1的交易数据（正常路径，无双花）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_1的完整路径：[0,8,15,16,25,27,55,56,58]
        block_heights = [0, 8, 15, 16, 25, 27, 55, 56, 58]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice value_1分配
            [],  # 区块8：alice进行其他交易（非目标value_1）
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
            [],  # 区块16：bob进行其他交易（非目标value_1）
            [],  # 区块25：bob进行其他交易（非目标value_1）
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27：bob->charlie
            [],  # 区块55：charlie进行其他交易（非目标value_1）
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56：charlie->dave
            [create_test_transaction(dave_addr, eve_addr, target_value)]  # 区块58：dave->eve（组合支付的一部分）
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def _setup_value2_transactions_case8(self, proofs: Mock, target_value: Value, zhao_addr: str,
                                         qian_addr: str, sun_addr: str, dave_addr: str, eve_addr: str, x_addr: str):
        """设置案例8中value_2的交易数据（包含双花攻击）"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        # value_2的路径：[0,3,5,17,38,39,58]，但dave在区块46进行了双花（被隐藏）
        block_heights = [0, 3, 5, 17, 38, 39, 58]  # 跳过双花区块46
        transactions = [
            [create_test_transaction("GOD", zhao_addr, target_value)],  # 创世块：GOD->zhao value_2分配
            [],  # 区块3：zhao进行其他交易（非目标value_2）
            [create_test_transaction(zhao_addr, qian_addr, target_value)],  # 区块5：zhao->qian
            [],  # 区块17：qian进行其他交易（非目标value_2）
            [create_test_transaction(qian_addr, sun_addr, target_value)],  # 区块38：qian->sun
            [create_test_transaction(sun_addr, dave_addr, target_value)],  # 区块39：sun->dave
            [create_test_transaction(dave_addr, eve_addr, target_value)]  # 区块58：dave->eve（组合支付的一部分，但这是非法的，因为dave在区块46已经双花了）
        ]

        # 双花区块信息（dave在区块46将value转移给同伙x）
        double_spend_block = 46

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height

            # 设置验证结果：最后一个proof unit（区块58）应该验证失败，因为dave在区块46已经双花了
            if height == 58:  # 区块58的交易是非法的，因为dave在区块46已经双花
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(
                    False,
                    f"Double spend detected: value already spent in block {double_spend_block} by dave to {x_addr}"
                ))
            else:
                proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case8_execution(self, test_data):
        """执行案例8测试（组合双花交易，无checkpoint）"""
        TestOutputManager.print_case_header("案例8：组合双花交易（无checkpoint）")

        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        TestOutputManager.print_info("验证组合交易中的value_1（从头开始验证）...")
        # 验证value_1：eve没有value_1的历史，所以从头开始验证
        report_1 = validator.verify_vpb_pair(
            test_data['target_value_1'],
            convert_proofs_to_proof_units(test_data['proofs_1']),
            test_data['block_index_list_1'],
            test_data['main_chain_info'],
            test_data['account_address']  # eve验证value_1
        )

        TestOutputManager.print_info("验证组合交易中的value_2（从头开始验证）...")
        # 验证value_2：eve没有value_2的历史，所以从头开始验证，应该检测到双花
        report_2 = validator.verify_vpb_pair(
            test_data['target_value_2'],
            convert_proofs_to_proof_units(test_data['proofs_2']),
            test_data['block_index_list_2'],
            test_data['main_chain_info'],
            test_data['account_address']  # eve验证value_2
        )

        # 验证value_1结果：应该成功（无双花）
        assert report_1.result == VerificationResult.SUCCESS
        assert report_1.is_valid == True
        assert len(report_1.errors) == 0
        # value_1不应该使用checkpoint（eve没有value_1的历史）
        assert report_1.checkpoint_used is None

        # 验证value_2结果：应该失败（检测到双花）
        assert report_2.result == VerificationResult.FAILURE
        assert report_2.is_valid == False
        assert len(report_2.errors) > 0
        # value_2不应该使用checkpoint（eve没有value_2的历史）
        assert report_2.checkpoint_used is None

        # 验证包含双花错误
        double_spend_errors = [err for err in report_2.errors
                             if "double spend" in err.error_message.lower()]
        assert len(double_spend_errors) > 0

        # 打印详细的验证结果
        TestOutputManager.print_verification_summary(report_1, "value_1验证")
        TestOutputManager.print_verification_summary(report_2, "value_2验证")

        TestOutputManager.print_success("案例8验证通过 - 组合双花攻击检测成功")
        TestOutputManager.print_info(f"dave->eve组合交易双花检测完成", indent=2)
        TestOutputManager.print_info(f"value_1 (alice->bob->charlie->dave->eve): 验证成功", indent=3)
        TestOutputManager.print_info(f"value_2 (zhao->qian->sun->dave->eve): 检测到双花攻击", indent=3)

        # 特殊显示双花检测结果
        print(f"\n【安全检测结果】")
        if double_spend_errors:
            TestOutputManager.print_success(f"检测到 {len(double_spend_errors)} 个双花攻击")
            TestOutputManager.print_info(f"攻击类型：dave在区块46对value_2进行双花", indent=3)
        else:
            TestOutputManager.print_failure("未能检测到双花攻击")


class TestEdgeCasesAndStress:
    """边缘案例和压力测试"""

    def test_empty_vpb_data(self):
        """测试空VPB数据"""
        validator = VPBValidator()

        # 创建空的VPB数据（Value不能有0个valueNum，所以使用最小值1）
        empty_value = Value("0x1000", 1)  # 最小value
        empty_proofs = Mock(spec=Proofs)
        empty_proofs.proof_units = []
        empty_proofs.value_id = "0x1000"
        empty_block_index = BlockIndexList([], [])
        empty_main_chain = MainChainInfo({}, {}, 0)

        report = validator.verify_vpb_pair(
            empty_value, convert_proofs_to_proof_units(empty_proofs), empty_block_index, empty_main_chain, "0xtest"
        )

        # 应该返回失败
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) > 0

    def test_invalid_data_types(self):
        """测试无效数据类型"""
        validator = VPBValidator()

        # 测试非Value对象 - 这会通过数据结构验证并返回失败报告
        invalid_proofs = Mock(spec=Proofs)
        invalid_proofs.proof_units = []
        invalid_proofs.value_id = "test"
        invalid_block_index = Mock(spec=BlockIndexList)
        invalid_block_index.index_lst = []
        invalid_block_index.owner = []
        invalid_main_chain = Mock(spec=MainChainInfo)
        invalid_main_chain.merkle_roots = {}
        invalid_main_chain.bloom_filters = {}
        invalid_main_chain.current_block_height = 0

        report = validator.verify_vpb_pair(
            "not_a_value", convert_proofs_to_proof_units(invalid_proofs), invalid_block_index, invalid_main_chain, "0xtest"
        )

        # 应该返回失败而不是抛出异常
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) > 0

    def test_large_scale_verification(self):
        """测试大规模验证的性能"""
        validator = VPBValidator()

        # 创建大量VPB数据进行性能测试
        start_time = time.time()

        for i in range(100):  # 100个VPB验证
            target_value = Value(f"0x{i:04x}", 100)
            proofs = VPBTestDataGenerator.create_mock_proofs(3, target_value.begin_index)
            block_index_list = BlockIndexList([0, i, i+10], [(0, "0xowner1"), (i, "0xowner2")])
            main_chain = MainChainInfo({j: f"root{j}" for j in range(i+11)}, {}, i+10)

            # 简化的proof设置
            for proof_unit in proofs.proof_units:
                proof_unit.verify_proof_unit = Mock(return_value=(True, ""))

            report = validator.verify_vpb_pair(
                target_value, convert_proofs_to_proof_units(proofs), block_index_list, main_chain, "0xowner2"
            )

            # 大多数应该成功（简化测试）
            assert report.verification_time_ms >= 0

        elapsed_time = time.time() - start_time
        print(f"大规模验证测试完成: {elapsed_time:.2f}秒, 平均每个: {elapsed_time/100*1000:.2f}ms")

    def test_concurrent_verification(self):
        """测试并发验证"""
        import threading

        validator = VPBValidator()
        results = []
        errors = []

        def verify_vpb(worker_id):
            try:
                target_value = Value(f"0x{worker_id:04x}", 100)
                proofs = VPBTestDataGenerator.create_mock_proofs(3, target_value.begin_index)
                block_index_list = BlockIndexList([0, worker_id], [(0, "0xowner1"), (worker_id, "0xowner2")])
                main_chain = MainChainInfo({j: f"root{j}" for j in range(worker_id+1)}, {}, worker_id)

                for proof_unit in proofs.proof_units:
                    proof_unit.verify_proof_unit = Mock(return_value=(True, ""))

                report = validator.verify_vpb_pair(
                    target_value, convert_proofs_to_proof_units(proofs), block_index_list, main_chain, "0xowner2"
                )

                results.append((worker_id, report.result, report.verification_time_ms))

            except Exception as e:
                errors.append((worker_id, str(e)))

        # 创建多个线程
        threads = []
        for worker_id in range(10):
            thread = threading.Thread(target=verify_vpb, args=(worker_id,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 验证结果
        assert len(errors) == 0, f"并发测试出现错误: {errors}"
        assert len(results) == 10, "并发测试结果数量不正确"

        print(f"并发验证测试完成: {len(results)}个验证成功")


class TestVPBValidatorIntegration:
    """VPB验证器集成测试"""

    def test_verification_statistics(self):
        """测试验证统计功能"""
        validator = VPBValidator()

        # 初始统计
        stats = validator.get_verification_stats()
        assert stats['total'] == 0
        assert stats['successful'] == 0
        assert stats['failed'] == 0

        # 创建一个完整的交易路径测试数据 - 参考通过案例的模式
        target_value = Value("0x1000", 100)

        # 创建测试地址
        alice_addr = "0x1234567890abcdef1234567890abcdef12345678"
        bob_addr = "0xabcdef1234567890abcdef1234567890abcdef12"

        # 创建完整的proof_units - 包含创世块和交易路径
        proof_units = VPBTestDataGenerator.create_real_proofs(2, target_value.begin_index)  # 简化为2个proof units

        # 设置完整的交易路径
        def create_test_transaction(sender: str, receiver: str, value: Value):
            from EZ_Transaction.SingleTransaction import Transaction

            # 创建真实的Transaction对象
            real_tx = Transaction(
                sender=sender,
                recipient=receiver,
                nonce=0,  # 使用固定的nonce
                signature=b"test_signature",  # 简化的签名
                value=[value],  # value应该是列表
                time="2024-01-01T00:00:00"  # 简化的时间戳
            )
            return real_tx

        # 交易路径：创世块(GOD->alice) -> 转账(alice->bob)
        block_heights = [0, 15]
        transactions = [
            [create_test_transaction("GOD", alice_addr, target_value)],  # 创世块：GOD->alice
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15：alice->bob
        ]

        # 设置proof units
        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proof_units[i].owner_multi_txns.multi_txns = txs

        # 创建对应的BlockIndexList
        block_index_list = BlockIndexList(
            [0, 15],
            [(0, alice_addr), (15, bob_addr)]
        )

        # 创建主链信息
        additional_transactions = {
            0: [alice_addr],  # 创世块包含alice地址
            15: [bob_addr]    # 区块15包含bob地址
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 15], additional_transactions
        )

        main_chain = MainChainInfo(
            {i: f"root{i}" for i in [0, 15]},
            bloom_filters,
            15
        )

        # 执行验证
        report = validator.verify_vpb_pair(
            target_value, proof_units, block_index_list, main_chain, bob_addr
        )

        # 检查验证是否成功
        assert report.is_valid == True, f"验证应该成功，但失败了: {report.errors}"

        # 检查统计更新
        stats = validator.get_verification_stats()
        assert stats['total'] == 1
        assert stats['successful'] == 1
        assert stats['success_rate'] == 1.0

        # 重置统计
        validator.reset_stats()
        stats = validator.get_verification_stats()
        assert stats['total'] == 0

    def test_complete_verification_pipeline(self):
        """测试完整的验证流程"""
        # 创建完整的测试环境
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建测试数据
                target_value = Value("0x5000", 500)
                proofs = VPBTestDataGenerator.create_mock_proofs(4, target_value.begin_index)
                block_index_list = BlockIndexList(
                    [0, 10, 20, 30],
                    [(0, "0xcreator"), (10, "0xowner1"), (20, "0xowner2"), (30, "0xowner3")]
                )

                # 设置proof验证
                for proof_unit in proofs.proof_units:
                    proof_unit.verify_proof_unit = Mock(return_value=(True, ""))
                    proof_unit.owner_multi_txns = Mock()
                    proof_unit.owner_multi_txns.multi_txns = []

                # 创建主链信息
                main_chain = MainChainInfo(
                    {i: f"merkle_root_{i}" for i in [0, 10, 20, 30]},
                    {},
                    30
                )

                # 创建checkpoint
                checkpoint.save_checkpoint(target_value, "0xowner2", 19)

                # 执行完整验证
                report = validator.verify_vpb_pair(
                    target_value, convert_proofs_to_proof_units(proofs), block_index_list, main_chain, "0xowner3"
                )

                # 验证完整流程
                assert report is not None
                assert isinstance(report, VPBVerificationReport)
                assert report.verification_time_ms >= 0

                print(f"完整验证流程测试成功:")
                print(f"  - 验证结果: {report.result.value}")
                print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
                print(f"  - 错误数量: {len(report.errors)}")
                print(f"  - 验证epoch: {len(report.verified_epochs)}")

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass


def run_all_test_cases():
    """运行所有测试案例"""
    start_time = time.time()
    TestOutputManager.print_header("VPB Validator 全面测试套件")

    test_cases = [
        ("案例1：简单正常交易（有checkpoint）", TestCase1_SimpleNormalWithCheckpoint()),
        ("案例2：简单正常交易（无checkpoint）", TestCase2_SimpleNormalWithoutCheckpoint()),
        ("案例3：简单双花交易（有checkpoint）", TestCase3_SimpleDoubleSpendWithCheckpoint()),
        ("案例4：简单双花交易（无checkpoint）", TestCase4_SimpleDoubleSpendWithoutCheckpoint()),
        ("案例5：组合正常交易（有checkpoint）", TestCase5_CombinedNormalWithCheckpoint()),
        ("案例6：组合正常交易（无checkpoint）", TestCase6_CombinedNormalWithoutCheckpoint()),
        ("案例7：组合双花交易（有checkpoint）", TestCase7_CombinedDoubleSpendWithCheckpoint()),
        ("案例8：组合双花交易（无checkpoint）", TestCase8_CombinedDoubleSpendWithoutCheckpoint()),
    ]

    results = []
    total_tests = len(test_cases)

    for i, (case_name, test_case) in enumerate(test_cases, 1):
        TestOutputManager.print_progress_bar(i-1, total_tests)

        try:
            # 获取测试数据并执行测试
            if hasattr(test_case, 'test_data'):
                test_data = test_case.test_data()

                # 动态调用对应的执行方法
                for case_num in range(1, 9):
                    method_name = f"test_case{case_num}_execution"
                    if hasattr(test_case, method_name):
                        getattr(test_case, method_name)(test_data)
                        break

            results.append((case_name, True))
            TestOutputManager.print_progress_bar(i, total_tests)

        except Exception as e:
            results.append((case_name, False))
            print(f"\n")  # 换行以避免进度条覆盖
            TestOutputManager.print_failure(f"{case_name}: {str(e)}")

    # 完成进度条
    TestOutputManager.print_progress_bar(total_tests, total_tests)
    print()  # 换行

    # 运行边缘案例和压力测试
    TestOutputManager.print_case_header("边缘案例和压力测试")

    # 运行边缘案例测试
    edge_tests = TestEdgeCasesAndStress()
    edge_test_methods = [
        ("空VPB数据测试", edge_tests.test_empty_vpb_data),
        ("大规模验证测试", edge_tests.test_large_scale_verification),
        ("并发验证测试", edge_tests.test_concurrent_verification),
    ]

    for test_name, test_method in edge_test_methods:
        try:
            TestOutputManager.print_info(f"运行 {test_name}...")
            test_method()
            results.append((test_name, True))
            TestOutputManager.print_success(f"{test_name} 通过")
        except Exception as e:
            results.append((test_name, False))
            TestOutputManager.print_failure(f"{test_name} 失败: {str(e)}")

    # 运行集成测试
    TestOutputManager.print_case_header("集成测试")
    integration_tests = TestVPBValidatorIntegration()
    integration_test_methods = [
        ("验证统计测试", integration_tests.test_verification_statistics),
        ("完整验证流程测试", integration_tests.test_complete_verification_pipeline),
    ]

    for test_name, test_method in integration_test_methods:
        try:
            TestOutputManager.print_info(f"运行 {test_name}...")
            test_method()
            results.append((test_name, True))
            TestOutputManager.print_success(f"{test_name} 通过")
        except Exception as e:
            results.append((test_name, False))
            TestOutputManager.print_failure(f"{test_name} 失败: {str(e)}")

    # 打印最终测试结果
    total_time = time.time() - start_time
    TestOutputManager.print_final_results(results, total_time)

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "pytest":
            # 运行pytest测试
            pytest.main([__file__, "-v", "--tb=short"])
        elif command == "all":
            # 运行所有测试案例
            run_all_test_cases()
        elif command == "edge":
            # 只运行边缘案例测试
            edge_tests = TestEdgeCasesAndStress()
            test_methods = [
                ("空VPB数据测试", edge_tests.test_empty_vpb_data),
                ("无效数据类型测试", edge_tests.test_invalid_data_types),
                ("大规模验证测试", edge_tests.test_large_scale_verification),
                ("并发验证测试", edge_tests.test_concurrent_verification),
            ]
            for name, method in test_methods:
                print(f"Running {name}...")
                try:
                    method()
                    print(f"[PASS] {name}")
                except Exception as e:
                    print(f"[FAIL] {name}: {e}")
        elif command == "integration":
            # 只运行集成测试
            integration_tests = TestVPBValidatorIntegration()
            test_methods = [
                ("验证统计测试", integration_tests.test_verification_statistics),
                ("完整验证流程测试", integration_tests.test_complete_verification_pipeline),
            ]
            for name, method in test_methods:
                print(f"Running {name}...")
                try:
                    method()
                    print(f"[PASS] {name}")
                except Exception as e:
                    print(f"[FAIL] {name}: {e}")
        else:
            print("未知命令。可用命令:")
            print("  pytest       - 运行pytest单元测试")
            print("  all          - 运行所有测试案例")
            print("  edge         - 运行边缘案例测试")
            print("  integration  - 运行集成测试")
    else:
        # 默认运行pytest
        print("运行VPB Validator pytest测试...")
        pytest.main([__file__, "-v"])

        print(f"\n要运行完整测试套件，请使用:")
        print(f"  python {__file__} all")
        print("=" * 80)