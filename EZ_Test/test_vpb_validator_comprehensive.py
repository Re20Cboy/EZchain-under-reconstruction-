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
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from unittest.mock import Mock, MagicMock, patch

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_VPB_Validator.vpb_validator import VPBValidator
    from EZ_VPB_Validator.core.types import (
        VerificationResult, VerificationError, VPBVerificationReport,
        MainChainInfo, VPBSlice
    )
    from EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord
    from EZ_Value.Value import Value, ValueState
    from EZ_Proof.Proofs import Proofs
    from EZ_Proof.ProofUnit import ProofUnit
    from EZ_BlockIndex.BlockIndexList import BlockIndexList
    from EZ_Units.Bloom import BloomFilter
except ImportError as e:
    print(f"导入模块错误: {e}")
    print("请确保相关模块在正确的路径中")
    sys.exit(1)


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
    def create_block_index_list(indexes: List[int], owners: List[Tuple[int, str]]) -> BlockIndexList:
        """创建BlockIndexList对象"""
        return BlockIndexList(indexes, owners)

    @staticmethod
    def create_realistic_bloom_filters(block_heights: List[int],
                                     owner_data: Dict[int, str],
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

    def test_data(self):
        """设置案例1的测试数据"""
        # 目标value
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 创建有效的以太坊地址
        alice_addr = VPBTestDataGenerator.create_eth_address("alice")
        bob_addr = VPBTestDataGenerator.create_eth_address("bob")
        charlie_addr = VPBTestDataGenerator.create_eth_address("charlie")
        dave_addr = VPBTestDataGenerator.create_eth_address("dave")

        # TODO：block_index_list应包含全量编号[0,8,15,16,25,27,55,56,58]
        # 区块索引列表 - 只记录所有权变更的区块
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, alice_addr),    # 创世块：alice获得目标value
                (15, bob_addr),     # 区块15：bob从alice处接收目标value
                (27, charlie_addr), # 区块27：charlie从bob处接收目标value
                (56, dave_addr),    # 区块56：dave从charlie处接收目标value
                (58, bob_addr)      # 区块58：bob从dave处接收目标value
            ]
        )

        # 创建对应的proofs
        proofs = VPBTestDataGenerator.create_mock_proofs(5, target_value.begin_index)

        # 配置每个proof unit的交易数据
        self._setup_proof_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: alice_addr, 8: alice_addr, 15: bob_addr, 16: bob_addr, 25: bob_addr,
            27: charlie_addr, 55: charlie_addr, 56: dave_addr, 58: bob_addr
        }

        additional_transactions = {
            8: [alice_addr], 15: [alice_addr], 16: [bob_addr], 25: [bob_addr],
            27: [bob_addr], 55: [charlie_addr], 56: [charlie_addr], 58: [dave_addr]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], owner_data, additional_transactions
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

        # 配置每个proof unit
        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块没有交易
            [create_test_transaction(alice_addr, bob_addr, target_value)],  # 区块15
            [create_test_transaction(bob_addr, charlie_addr, target_value)],  # 区块27
            [create_test_transaction(charlie_addr, dave_addr, target_value)],  # 区块56
            [create_test_transaction(dave_addr, bob_addr, target_value)]  # 区块58
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case1_execution(self, test_data):
        """执行案例1测试"""
        # 创建带checkpoint的验证器
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建checkpoint：bob在区块27将value转移给charlie前的状态
                checkpoint.create_checkpoint(
                    test_data['target_value'],
                    test_data['account_address'],
                    test_data['expected_checkpoint_height']
                )

                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    test_data['proofs'],
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

                print(f"案例1验证成功:")
                print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
                print(f"  - 使用checkpoint: 区块{report.checkpoint_used.block_height}")
                print(f"  - 验证epoch: {report.verified_epochs}")

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

    def test_data(self):
        """设置案例2的测试数据"""
        # 目标value
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 区块索引列表
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value
                (58, "0xeve")      # 区块58：eve从dave处接收目标value（eve没有checkpoint）
            ]
        )

        # 创建对应的proofs
        proofs = VPBTestDataGenerator.create_mock_proofs(5, target_value.begin_index)

        # 配置交易数据（eve是新的验证者）
        self._setup_proof_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 58: "0xeve"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], owner_data, additional_transactions
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
            'account_address': "0xeve",  # eve从dave处接收value，没有checkpoint
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

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xeve", target_value)]
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
            test_data['proofs'],
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

    def test_data(self):
        """设置案例3的测试数据"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 正常的交易路径，但dave在区块57进行了双花
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value
                (58, "0xbob")      # 区块58：bob从dave处接收目标value
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)

        # 设置交易数据，包括双花
        self._setup_proof_transactions_with_double_spend(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xdave", 58: "0xbob"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"], 58: ["0xdave"]  # dave在区块57和58都有交易
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], owner_data, additional_transactions
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
            'account_address': "0xbob",
            'expected_checkpoint_height': 26,
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_proof_transactions_with_double_spend(self, proofs: Mock, target_value: Value):
        """设置包含双花的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xbob", target_value)]
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

        # 模拟双花检测：设置最后一个proof unit检测到双花
        # 这通过修改验证逻辑来模拟检测到区块57的双花交易
        proofs.proof_units[-1].verify_proof_unit = Mock(return_value=(
            False,
            "Double spend detected: value spent in block 57 to unknown party"
        ))

    def test_case3_execution(self, test_data):
        """执行案例3测试"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建checkpoint
                checkpoint.create_checkpoint(
                    test_data['target_value'],
                    "0xbob",
                    test_data['expected_checkpoint_height']
                )

                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    test_data['proofs'],
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

                print(f"案例3验证成功（检测到双花）:")
                print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
                print(f"  - 使用checkpoint: 区块{report.checkpoint_used.block_height if report.checkpoint_used else '无'}")
                print(f"  - 错误数量: {len(report.errors)}")
                for error in report.errors:
                    print(f"    - {error.error_type}: {error.error_message}")

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

    def test_data(self):
        """设置案例4的测试数据"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 正常的交易路径，但dave在区块57进行了双花，验证者frank没有checkpoint
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value
                (58, "0xfrank")    # 区块58：frank从dave处接收目标value（frank没有checkpoint）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)

        # 设置交易数据，包括双花
        self._setup_proof_transactions_with_double_spend(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xdave", 58: "0xfrank"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"], 58: ["0xdave"]  # dave在区块57和58都有交易
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], owner_data, additional_transactions
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
            'account_address': "0xfrank",  # frank从dave处接收value，没有checkpoint
            'expected_start_block': 0,  # 验证应该从创世块开始
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_proof_transactions_with_double_spend(self, proofs: Mock, target_value: Value):
        """设置包含双花的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xfrank", target_value)]
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

        # 模拟双花检测：设置最后一个proof unit检测到双花
        # 这通过修改验证逻辑来模拟检测到区块57的双花交易
        proofs.proof_units[-1].verify_proof_unit = Mock(return_value=(
            False,
            "Double spend detected: value spent in block 57 to unknown party"
        ))

    def test_case4_execution(self, test_data):
        """执行案例4测试"""
        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        # 执行验证
        report = validator.verify_vpb_pair(
            test_data['target_value'],
            test_data['proofs'],
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

    def test_data(self):
        """设置案例5的测试数据（组合交易）"""
        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)

        # 这是一个简化的组合交易案例，主要测试单个value的组合逻辑
        # 实际的组合交易需要更复杂的VPB结构
        target_value = target_value_1  # 主要测试目标value_1

        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value_1
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value_1
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value_1
                (58, "0xqian")     # 区块58：qian从dave处接收目标value_1+目标value_2（组合支付）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)
        self._setup_combined_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 58: "0xqian"
        }

        # qian在区块38从sun处接收value_2，所以有checkpoint
        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], owner_data, additional_transactions
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
            'account_address': "0xqian",  # qian有checkpoint（从value_2的历史）
            'expected_checkpoint_height': 37,  # qian在区块38获得value_2前的checkpoint
        }

    def _setup_combined_transactions(self, proofs: Mock, target_value: Value):
        """设置组合交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xqian", target_value)]  # 组合支付
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case5_execution(self, test_data):
        """执行案例5测试"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建checkpoint：qian在区块38前的状态
                checkpoint.create_checkpoint(
                    test_data['target_value'],
                    "0xqian",
                    test_data['expected_checkpoint_height']
                )

                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    test_data['proofs'],
                    test_data['block_index_list'],
                    test_data['main_chain_info'],
                    test_data['account_address']
                )

                # 验证结果
                assert report.result == VerificationResult.SUCCESS
                assert report.is_valid == True
                assert len(report.errors) == 0

                # 验证checkpoint被使用
                assert report.checkpoint_used is not None
                assert report.checkpoint_used.owner_address == "0xqian"

                print(f"案例5验证成功（组合交易）:")
                print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
                print(f"  - 使用checkpoint: 区块{report.checkpoint_used.block_height}")
                print(f"  - 验证epoch: {report.verified_epochs}")

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

    def test_data(self):
        """设置案例6的测试数据（组合交易，无checkpoint）"""
        # 创建两个目标value
        target_value_1 = VPBTestDataGenerator.create_value("0x1000", 100)
        target_value_2 = VPBTestDataGenerator.create_value("0x2000", 200)

        # 这是一个简化的组合交易案例，主要测试单个value的组合逻辑
        # 实际的组合交易需要更复杂的VPB结构
        target_value = target_value_1  # 主要测试目标value_1

        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value_1
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value_1
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value_1
                (58, "0xzero")     # 区块58：zero从dave处接收目标value_1+目标value_2（组合支付，zero没有checkpoint）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)
        self._setup_combined_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 58: "0xzero"
        }

        # zero是新的验证者，没有checkpoint
        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 58], owner_data, additional_transactions
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
            'account_address': "0xzero",  # zero从dave处接收value，没有checkpoint
            'expected_start_block': 0  # 验证应该从创世块开始
        }

    def _setup_combined_transactions(self, proofs: Mock, target_value: Value):
        """设置组合交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xzero", target_value)]  # 组合支付
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

    def test_case6_execution(self, test_data):
        """执行案例6测试"""
        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        # 执行验证
        report = validator.verify_vpb_pair(
            test_data['target_value'],
            test_data['proofs'],
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

        print(f"案例6验证成功（组合交易，无checkpoint）:")
        print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
        print(f"  - 使用checkpoint: 无")
        print(f"  - 验证epoch: {report.verified_epochs}")


class TestCase7_CombinedDoubleSpendWithCheckpoint:
    """案例7：组合双花交易，有checkpoint"""

    def test_data(self):
        """设置案例7的测试数据（组合双花交易，有checkpoint）"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 组合交易场景，包含双花行为，验证者有checkpoint
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value
                (58, "0xmallory")  # 区块58：mallory从dave处接收目标value（组合支付，但包含双花）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)

        # 设置交易数据，包括组合支付和双花
        self._setup_combined_double_spend_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xdave", 58: "0xmallory"
        }

        # mallory有checkpoint（从其他交易历史获得）
        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"], 58: ["0xdave"]  # dave在区块57和58都有交易，形成双花
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], owner_data, additional_transactions
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
            'account_address': "0xmallory",  # mallory有checkpoint
            'expected_checkpoint_height': 37,  # mallory在区块38前的checkpoint
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_combined_double_spend_transactions(self, proofs: Mock, target_value: Value):
        """设置包含组合支付和双花的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value, is_combined: bool = False):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            if is_combined:
                # 组合交易，有多个输入
                mock_tx.input_values = [value, Mock(spec=Value)]  # 添加第二个value
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xmallory", target_value, is_combined=True)]  # 组合支付但包含双花
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

        # 模拟双花检测：设置最后一个proof unit检测到双花
        # 在组合交易中检测到dave在区块57的双重支付
        proofs.proof_units[-1].verify_proof_unit = Mock(return_value=(
            False,
            "Double spend detected in combined transaction: input value spent in block 57 to unknown party"
        ))

    def test_case7_execution(self, test_data):
        """执行案例7测试"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建checkpoint：mallory在区块38前的状态
                checkpoint.create_checkpoint(
                    test_data['target_value'],
                    "0xmallory",
                    test_data['expected_checkpoint_height']
                )

                # 执行验证
                report = validator.verify_vpb_pair(
                    test_data['target_value'],
                    test_data['proofs'],
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

                # 验证使用了checkpoint
                assert report.checkpoint_used is not None
                assert report.checkpoint_used.owner_address == "0xmallory"

                print(f"案例7验证成功（检测到组合双花，有checkpoint）:")
                print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
                print(f"  - 使用checkpoint: 区块{report.checkpoint_used.block_height}")
                print(f"  - 错误数量: {len(report.errors)}")
                for error in report.errors:
                    print(f"    - {error.error_type}: {error.error_message}")

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

    def test_data(self):
        """设置案例8的测试数据（组合双花交易，无checkpoint）"""
        target_value = VPBTestDataGenerator.create_value("0x1000", 100)

        # 组合交易场景，包含双花行为，验证者没有checkpoint
        block_index_list = VPBTestDataGenerator.create_block_index_list(
            [0, 15, 27, 56, 58],
            [
                (0, "0xalice"),    # 创世块：alice获得目标value
                (15, "0xbob"),     # 区块15：bob从alice处接收目标value
                (27, "0xcharlie"), # 区块27：charlie从bob处接收目标value
                (56, "0xdave"),    # 区块56：dave从charlie处接收目标value
                (58, "0xtrudy")    # 区块58：trudy从dave处接收目标value（组合支付，但包含双花，trudy没有checkpoint）
            ]
        )

        proofs = VPBTestDataGenerator.create_mock_proofs(5)

        # 设置交易数据，包括组合支付和双花
        self._setup_combined_double_spend_transactions(proofs, target_value)

        # 创建主链信息
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xdave", 58: "0xtrudy"
        }

        # trudy是新的验证者，没有checkpoint
        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"], 58: ["0xdave"]  # dave在区块57和58都有交易，形成双花
        }

        bloom_filters = VPBTestDataGenerator.create_realistic_bloom_filters(
            [0, 8, 15, 16, 25, 27, 55, 56, 57, 58], owner_data, additional_transactions
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
            'account_address': "0xtrudy",  # trudy从dave处接收value，没有checkpoint
            'expected_start_block': 0,  # 验证应该从创世块开始
            'double_spend_block': 57  # dave在区块57进行双花
        }

    def _setup_combined_double_spend_transactions(self, proofs: Mock, target_value: Value):
        """设置包含组合支付和双花的交易数据"""
        def create_test_transaction(sender: str, receiver: str, value: Value, is_combined: bool = False):
            mock_tx = Mock()
            mock_tx.sender = sender
            mock_tx.receiver = receiver
            mock_tx.input_values = [value]
            if is_combined:
                # 组合交易，有多个输入
                mock_tx.input_values = [value, Mock(spec=Value)]  # 添加第二个value
            mock_tx.output_values = [value]
            return mock_tx

        block_heights = [0, 15, 27, 56, 58]
        transactions = [
            [],  # 创世块
            [create_test_transaction("0xalice", "0xbob", target_value)],
            [create_test_transaction("0xbob", "0xcharlie", target_value)],
            [create_test_transaction("0xcharlie", "0xdave", target_value)],
            [create_test_transaction("0xdave", "0xtrudy", target_value, is_combined=True)]  # 组合支付但包含双花
        ]

        for i, (height, txs) in enumerate(zip(block_heights, transactions)):
            proofs.proof_units[i].owner_multi_txns = Mock()
            proofs.proof_units[i].owner_multi_txns.sender = proofs.proof_units[i].owner
            proofs.proof_units[i].owner_multi_txns.multi_txns = txs
            proofs.proof_units[i].block_height = height
            proofs.proof_units[i].verify_proof_unit = Mock(return_value=(True, ""))

        # 模拟双花检测：设置最后一个proof unit检测到双花
        # 在组合交易中检测到dave在区块57的双重支付
        proofs.proof_units[-1].verify_proof_unit = Mock(return_value=(
            False,
            "Double spend detected in combined transaction: input value spent in block 57 to unknown party"
        ))

    def test_case8_execution(self, test_data):
        """执行案例8测试"""
        # 创建不带checkpoint的验证器
        validator = VPBValidator()

        # 执行验证
        report = validator.verify_vpb_pair(
            test_data['target_value'],
            test_data['proofs'],
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

        print(f"案例8验证成功（检测到组合双花，无checkpoint）:")
        print(f"  - 验证时间: {report.verification_time_ms:.2f}ms")
        print(f"  - 使用checkpoint: 无")
        print(f"  - 错误数量: {len(report.errors)}")
        for error in report.errors:
            print(f"    - {error.error_type}: {error.error_message}")


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
            empty_value, empty_proofs, empty_block_index, empty_main_chain, "0xtest"
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
            "not_a_value", invalid_proofs, invalid_block_index, invalid_main_chain, "0xtest"
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
                target_value, proofs, block_index_list, main_chain, "0xowner2"
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
                    target_value, proofs, block_index_list, main_chain, "0xowner2"
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

        # 执行一些验证
        target_value = Value("0x1000", 100)
        proofs = VPBTestDataGenerator.create_mock_proofs(3, target_value.begin_index)
        block_index_list = BlockIndexList([0, 15, 27], [(0, "0xalice"), (15, "0xbob")])
        main_chain = MainChainInfo({i: f"root{i}" for i in [0, 15, 27]}, {}, 27)

        for proof_unit in proofs.proof_units:
            proof_unit.verify_proof_unit = Mock(return_value=(True, ""))

        # 执行验证
        validator.verify_vpb_pair(target_value, proofs, block_index_list, main_chain, "0xbob")

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
                checkpoint.create_checkpoint(target_value, "0xowner2", 19)

                # 执行完整验证
                report = validator.verify_vpb_pair(
                    target_value, proofs, block_index_list, main_chain, "0xowner3"
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
    print("=" * 80)
    print("VPB Validator 全面测试套件")
    print("=" * 80)

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

    for case_name, test_case in test_cases:
        print(f"\n运行 {case_name}...")
        try:
            # 获取测试数据
            if hasattr(test_case, 'test_data'):
                test_data = test_case.test_data()
                if hasattr(test_case, 'test_case1_execution'):
                    test_case.test_case1_execution(test_data)
                elif hasattr(test_case, 'test_case2_execution'):
                    test_case.test_case2_execution(test_data)
                elif hasattr(test_case, 'test_case3_execution'):
                    test_case.test_case3_execution(test_data)
                elif hasattr(test_case, 'test_case4_execution'):
                    test_case.test_case4_execution(test_data)
                elif hasattr(test_case, 'test_case5_execution'):
                    test_case.test_case5_execution(test_data)
                elif hasattr(test_case, 'test_case6_execution'):
                    test_case.test_case6_execution(test_data)
                elif hasattr(test_case, 'test_case7_execution'):
                    test_case.test_case7_execution(test_data)
                elif hasattr(test_case, 'test_case8_execution'):
                    test_case.test_case8_execution(test_data)

            results.append((case_name, "PASS", None))
            print(f"[PASS] {case_name}")

        except Exception as e:
            results.append((case_name, "FAIL", str(e)))
            print(f"[FAIL] {case_name}: {e}")

    # 运行边缘案例测试
    print(f"\n运行边缘案例和压力测试...")
    edge_tests = TestEdgeCasesAndStress()
    edge_test_methods = [
        ("空VPB数据测试", edge_tests.test_empty_vpb_data),
        ("大规模验证测试", edge_tests.test_large_scale_verification),
        ("并发验证测试", edge_tests.test_concurrent_verification),
    ]

    for test_name, test_method in edge_test_methods:
        try:
            test_method()
            results.append((test_name, "PASS", None))
            print(f"[PASS] {test_name}")
        except Exception as e:
            results.append((test_name, "FAIL", str(e)))
            print(f"[FAIL] {test_name}: {e}")

    # 运行集成测试
    print(f"\n运行集成测试...")
    integration_tests = TestVPBValidatorIntegration()
    integration_test_methods = [
        ("验证统计测试", integration_tests.test_verification_statistics),
        ("完整验证流程测试", integration_tests.test_complete_verification_pipeline),
    ]

    for test_name, test_method in integration_test_methods:
        try:
            test_method()
            results.append((test_name, "PASS", None))
            print(f"[PASS] {test_name}")
        except Exception as e:
            results.append((test_name, "FAIL", str(e)))
            print(f"[FAIL] {test_name}: {e}")

    # 打印测试总结
    print("\n" + "=" * 80)
    print("测试结果总结")
    print("=" * 80)

    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")

    for case_name, status, error in results:
        status_symbol = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"{status_symbol} {case_name}")
        if error:
            print(f"  Error: {error}")

    print("-" * 80)
    print(f"总计: {len(results)} 个测试, 通过: {passed} 个, 失败: {failed} 个")
    print(f"成功率: {passed/len(results)*100:.1f}%")
    print("=" * 80)

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