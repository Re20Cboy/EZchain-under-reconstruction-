"""
VPB测试案例配置文件

基于VPB_test_demo.md的前8个案例实现的具体测试配置
提供完整的测试数据生成和验证接口
"""

import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Any
from unittest.mock import Mock

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_VPB.VPBVerify import (
    VPBVerify, VPBVerificationReport, MainChainInfo,
    VerificationResult
)
from EZ_Value.Value import Value
from EZ_Proof.Proofs import Proofs
from EZ_Proof.ProofUnit import ProofUnit
from EZ_BlockIndex.BlockIndexList import BlockIndexList
from EZ_CheckPoint.CheckPoint import CheckPoint
from EZ_Units.Bloom import BloomFilter


class VPBTestCaseGenerator:
    """VPB测试案例生成器"""

    def __init__(self):
        self.verifier = VPBVerify()

    def create_mock_value(self, begin_index: str, value_num: int) -> Value:
        """创建模拟Value对象"""
        return Value(begin_index, value_num)

    def create_mock_transaction(self, sender: str, receiver: str,
                              value_begin: str = "0x1000", value_num: int = 100,
                              is_target_value: bool = True) -> Mock:
        """创建模拟交易对象"""
        mock_tx = Mock()
        mock_tx.sender = sender
        mock_tx.payer = sender
        mock_tx.receiver = receiver
        mock_tx.payee = receiver

        if is_target_value:
            # 目标value的完整对象
            mock_target_value = self.create_mock_value(value_begin, value_num)
            mock_tx.input_values = [mock_target_value]
            mock_tx.output_values = [mock_target_value]
            mock_tx.spent_values = [mock_target_value]
            mock_tx.received_values = [mock_target_value]
        else:
            # 非目标value的其他交易
            other_value = self.create_mock_value("0x2000", 256)
            mock_tx.input_values = [other_value]
            mock_tx.output_values = [other_value]
            mock_tx.spent_values = [other_value]
            mock_tx.received_values = [other_value]

        return mock_tx

    def create_proof_unit(self, block_height: int, transactions: List[Mock]) -> Mock:
        """创建模拟ProofUnit"""
        proof_unit = Mock(spec=ProofUnit)
        proof_unit.block_height = block_height
        proof_unit.owner_multi_txns = Mock()
        proof_unit.owner_multi_txns.multi_txns = transactions
        proof_unit.verify_proof_unit = Mock(return_value=(True, ""))
        return proof_unit

    def create_bloom_filter_data(self, block_heights: List[int],
                                owner_data: Dict[int, str],
                                additional_transactions: Dict[int, List[str]]) -> Dict[int, BloomFilter]:
        """创建布隆过滤器数据"""
        bloom_filters = {}

        for height in block_heights:
            bloom_filter = BloomFilter(size=1024, hash_count=3)

            # 添加在该区块提交交易的sender地址
            if additional_transactions and height in additional_transactions:
                for sender_address in additional_transactions[height]:
                    bloom_filter.add(sender_address)

            bloom_filters[height] = bloom_filter

        return bloom_filters

    def create_main_chain_info(self, merkle_roots: Dict[int, str],
                             bloom_filters: Dict[int, Any],
                             current_height: int,
                             additional_transactions: Dict[int, List[str]] = None) -> MainChainInfo:
        """创建主链信息"""
        main_chain = MainChainInfo(
            merkle_roots=merkle_roots,
            bloom_filters=bloom_filters,
            current_block_height=current_height
        )

        # Mock get_owner_transaction_blocks方法
        def mock_get_owner_transaction_blocks(owner_address: str, start_height: int, end_height: int) -> List[int]:
            result = []
            if additional_transactions:
                for height in range(start_height, end_height + 1):
                    if height in additional_transactions and owner_address in additional_transactions[height]:
                        result.append(height)
            return result

        main_chain.get_owner_transaction_blocks = Mock(side_effect=mock_get_owner_transaction_blocks)
        return main_chain


class VPBTestCases:
    """VPB测试案例实现"""

    def __init__(self):
        self.generator = VPBTestCaseGenerator()

    def case1_simple_normal_with_checkpoint(self) -> Dict[str, Any]:
        """
        案例1：简单正常交易，有checkpoint
        创世块：alice是目标value的首位所有者（从GOD处获得）
        区块8：alice进行其他交易（非目标value）
        区块15：bob从alice处接收目标value（alice->bob交易）
        区块16：bob进行其他交易（非目标value）
        区块25：bob进行其他交易（非目标value）
        区块27：charlie从bob处接收目标value（bob->charlie交易）
        区块55：charlie进行其他交易（非目标value）
        区块56：dave从charlie处接收目标value（charlie->dave交易）
        区块58：bob从dave处接收目标value（dave->bob交易）
        期望结果：dave->bob交易会触发bob的checkpoint(因为bob曾拥有过目标value)，从区块27开始验证。
        """
        target_value = self.generator.create_mock_value("0x1000", 100)

        # 创建BlockIndexList - 只记录所有权变更的区块
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice从GOD处获得value
                (15, "0xbob"),     # 区块15：bob从alice处获得value
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value
                (56, "0xdave"),    # 区块56：dave从charlie处获得value
                (58, "0xbob")      # 区块58：bob从dave处重新获得value
            ]
        )

        # 创建ProofUnits
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            # 区块0：创世块，alice从GOD处获得value（无转移交易）
            self.generator.create_proof_unit(0, []),
            # 区块15：alice->bob转移目标value
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            # 区块27：bob->charlie转移目标value
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            # 区块56：charlie->dave转移目标value
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 区块58：dave->bob转移目标value
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xbob", "0x1000", 100, True)
            ])
        ]

        # 创建主链信息
        merkle_roots = {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 58]}

        # 布隆过滤器数据
        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 58: "0xbob"
        }

        additional_transactions = {
            8: ["0xalice"],        # alice的其他交易
            15: ["0xalice"],       # alice->bob目标value转移
            16: ["0xbob"],         # bob的其他交易
            25: ["0xbob"],         # bob的其他交易
            27: ["0xbob"],         # bob->charlie目标value转移
            55: ["0xcharlie"],     # charlie的其他交易
            56: ["0xcharlie"],     # charlie->dave目标value转移
            58: ["0xdave"]         # dave->bob目标value转移
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        # 创建checkpoint（bob曾在区块27将value转移给charlie）
        # 简化处理，使用None来模拟checkpoint，避免数据库问题
        checkpoint = None

        return {
            "case_name": "案例1：简单正常交易，有checkpoint",
            "target_value": target_value,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xbob",
            "checkpoint": checkpoint,
            "expected_result": VerificationResult.SUCCESS,
            "expected_checkpoint_used": True,
            "expected_checkpoint_height": 26,
            "description": "验证dave->bob交易，应使用bob在区块26的checkpoint，从区块27开始验证"
        }

    def case2_simple_normal_without_checkpoint(self) -> Dict[str, Any]:
        """
        案例2：简单正常交易，无checkpoint
        类似案例1，但eve从未拥有过目标value，所以从头验证
        """
        target_value = self.generator.create_mock_value("0x1000", 100)

        # 创建BlockIndexList
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice从GOD处获得value
                (15, "0xbob"),     # 区块15：bob从alice处获得value
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value
                (56, "0xdave"),    # 区块56：dave从charlie处获得value
                (58, "0xeve")      # 区块58：eve从dave处获得value（新的所有者）
            ]
        )

        # 创建ProofUnits
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x1000", 100, True)
            ])
        ]

        # 创建主链信息
        merkle_roots = {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 58]}

        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 58: "0xeve"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        return {
            "case_name": "案例2：简单正常交易，无checkpoint",
            "target_value": target_value,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xeve",
            "checkpoint": None,
            "expected_result": VerificationResult.SUCCESS,
            "expected_checkpoint_used": False,
            "description": "eve从未拥有过目标value，应从头开始验证"
        }

    def case3_simple_double_spend_with_checkpoint(self) -> Dict[str, Any]:
        """
        案例3：简单双花交易，有checkpoint
        区块57：dave恶意将目标value转移给同伙x（双花）
        区块58：bob从dave处接收目标value（正常交易）
        期望：检测到dave在区块57的双花行为
        """
        target_value = self.generator.create_mock_value("0x1000", 100)

        # 创建BlockIndexList
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice从GOD处获得value
                (15, "0xbob"),     # 区块15：bob从alice处获得value
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value
                (56, "0xdave"),    # 区块56：dave从charlie处获得value
                (58, "0xbob")      # 区块58：bob从dave处重新获得value
            ]
        )

        # 🔥 修复：创建真实双花攻击场景的ProofUnits
        # dave隐藏区块57的恶意交易，只提供正常的proof units
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 🔥 关键：dave故意隐藏区块57的恶意交易，不提供区块57的proof！
            # 区块58：dave->bob正常交易（bob不知道value已被双花）
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xbob", "0x1000", 100, True)
            ])
            # 注意：故意缺少区块57的proof unit，模拟dave隐藏恶意双花交易
        ]

        # 创建主链信息（包含双花区块57）
        merkle_roots = {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 57, 58]}

        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xmalicious_x", 58: "0xbob"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"],  # dave在区块57恶意双花
            58: ["0xdave"]   # dave在区块58正常转移给bob
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        # 创建checkpoint（简化处理）
        checkpoint = None

        return {
            "case_name": "案例3：简单双花交易，有checkpoint",
            "target_value": target_value,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xbob",
            "checkpoint": checkpoint,
            "expected_result": VerificationResult.FAILURE,
            "expected_checkpoint_used": True,
            "expected_error_types": ["DOUBLE_SPEND_DETECTED", "INVALID_BLOCK_VALUE_INTERSECTION"],
            "description": "检测dave在区块57的恶意双花行为"
        }

    def case4_simple_double_spend_without_checkpoint(self) -> Dict[str, Any]:
        """
        案例4：简单双花交易，无checkpoint
        eve从未拥有过目标value，从头验证时发现双花
        """
        target_value = self.generator.create_mock_value("0x1000", 100)

        # 创建BlockIndexList
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice从GOD处获得value
                (15, "0xbob"),     # 区块15：bob从alice处获得value
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value
                (56, "0xdave"),    # 区块56：dave从charlie处获得value
                (58, "0xeve")      # 区块58：eve从dave处获得value
            ]
        )

        # 🔥 修复：创建真实双花攻击场景的ProofUnits
        # dave隐藏区块57的恶意交易，只提供正常的proof units
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 🔥 关键：dave故意隐藏区块57的恶意交易，不提供区块57的proof！
            # 区块58：dave->eve正常交易（eve不知道value已被双花）
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x1000", 100, True)
            ])
            # 注意：故意缺少区块57的proof unit，模拟dave隐藏恶意双花交易
        ]

        # 创建主链信息
        merkle_roots = {i: f"root{i}" for i in [0, 8, 15, 16, 25, 27, 55, 56, 57, 58]}

        owner_data = {
            0: "0xalice", 8: "0xalice", 15: "0xbob", 16: "0xbob", 25: "0xbob",
            27: "0xcharlie", 55: "0xcharlie", 56: "0xdave", 57: "0xmalicious_x", 58: "0xeve"
        }

        additional_transactions = {
            8: ["0xalice"], 15: ["0xalice"], 16: ["0xbob"], 25: ["0xbob"],
            27: ["0xbob"], 55: ["0xcharlie"], 56: ["0xcharlie"],
            57: ["0xdave"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        return {
            "case_name": "案例4：简单双花交易，无checkpoint",
            "target_value": target_value,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xeve",
            "checkpoint": None,
            "expected_result": VerificationResult.FAILURE,
            "expected_checkpoint_used": False,
            "expected_error_types": ["DOUBLE_SPEND_DETECTED", "INVALID_BLOCK_VALUE_INTERSECTION"],
            "description": "eve从头验证时发现dave在区块57的恶意双花行为"
        }

    def case5_combined_normal_with_checkpoint(self) -> Dict[str, Any]:
        """
        案例5：组合正常交易，有checkpoint
        目标value_1：alice->bob->charlie->dave
        目标value_2：zhao->qian->sun->dave
        区块58：dave->qian（组合支付value_1+value_2）
        qian曾拥有value_2，触发checkpoint从区块38开始验证value_2
        """
        # 创建两个目标value
        target_value_1 = self.generator.create_mock_value("0x1000", 100)  # alice line
        target_value_2 = self.generator.create_mock_value("0x2000", 200)  # zhao line

        # 创建BlockIndexList（为简化，只演示一个value的验证）
        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice获得value_1
                (15, "0xbob"),     # 区块15：bob从alice处获得value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value_1
                (56, "0xdave"),    # 区块56：dave从charlie处获得value_1
                (58, "0xqian")     # 区块58：qian从dave处获得value_1+value_2
            ]
        )

        # 创建ProofUnits
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 区块58：dave->qian组合支付（包含value_1和value_2）
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xqian", "0x1000", 100, True),
                self.generator.create_mock_transaction("0xdave", "0xqian", "0x2000", 200, True)
            ])
        ]

        # 创建主链信息
        merkle_roots = {i: f"root{i}" for i in [0, 3, 5, 8, 15, 17, 27, 38, 39, 56, 58]}

        owner_data = {
            0: "0xalice", 3: "0xzhao", 5: "0xqian", 8: "0xalice", 15: "0xbob",
            17: "0xqian", 27: "0xcharlie", 38: "0xsun", 39: "0xdave", 56: "0xdave", 58: "0xqian"
        }

        additional_transactions = {
            3: ["0xzhao"], 5: ["0xzhao"], 8: ["0xalice"], 15: ["0xalice"],
            17: ["0xqian"], 27: ["0xbob"], 38: ["0xqian"], 39: ["0xsun"],
            56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        # 创建checkpoint（简化处理）
        checkpoint = None

        return {
            "case_name": "案例5：组合正常交易，有checkpoint",
            "target_value": target_value_1,  # 主要验证value_1
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xqian",
            "checkpoint": checkpoint,
            "expected_result": VerificationResult.SUCCESS,
            "expected_checkpoint_used": True,
            "expected_checkpoint_height": 37,
            "description": "qian曾拥有value_2，触发checkpoint优化验证"
        }

    def case6_combined_normal_without_checkpoint(self) -> Dict[str, Any]:
        """
        案例6：组合正常交易，无checkpoint
        eve从未拥有过任何目标value，从头验证组合支付
        """
        target_value_1 = self.generator.create_mock_value("0x1000", 100)  # alice line
        target_value_2 = self.generator.create_mock_value("0x2000", 200)  # zhao line

        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice获得value_1
                (15, "0xbob"),     # 区块15：bob从alice处获得value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value_1
                (56, "0xdave"),    # 区块56：dave从charlie处获得value_1
                (58, "0xeve")      # 区块58：eve从dave处获得value_1+value_2
            ]
        )

        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 区块58：dave->eve组合支付
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x1000", 100, True),
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x2000", 200, True)
            ])
        ]

        merkle_roots = {i: f"root{i}" for i in [0, 3, 5, 8, 15, 17, 27, 38, 39, 56, 58]}

        owner_data = {
            0: "0xalice", 3: "0xzhao", 5: "0xqian", 8: "0xalice", 15: "0xbob",
            17: "0xqian", 27: "0xcharlie", 38: "0xsun", 39: "0xdave", 56: "0xdave", 58: "0xeve"
        }

        additional_transactions = {
            3: ["0xzhao"], 5: ["0xzhao"], 8: ["0xalice"], 15: ["0xalice"],
            17: ["0xqian"], 27: ["0xbob"], 38: ["0xqian"], 39: ["0xsun"],
            56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        return {
            "case_name": "案例6：组合正常交易，无checkpoint",
            "target_value": target_value_1,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xeve",
            "checkpoint": None,
            "expected_result": VerificationResult.SUCCESS,
            "expected_checkpoint_used": False,
            "description": "eve从未拥有过目标value，从头验证组合支付交易"
        }

    def case7_combined_double_spend_with_checkpoint(self) -> Dict[str, Any]:
        """
        案例7：组合双花交易，有checkpoint
        区块46：dave恶意将value_2转移给同伙x
        区块58：sun从dave处接收value_1+value_2
        sun曾拥有value_2，触发checkpoint发现双花
        """
        target_value_1 = self.generator.create_mock_value("0x1000", 100)  # alice line
        target_value_2 = self.generator.create_mock_value("0x2000", 200)  # zhao line

        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice获得value_1
                (15, "0xbob"),     # 区块15：bob从alice处获得value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value_1
                (56, "0xdave"),    # 区块56：dave从charlie处获得value_1
                (58, "0xsun")      # 区块58：sun从dave处获得value_1+value_2
            ]
        )

        # 🔥 修复：创建真实组合双花攻击场景的ProofUnits
        # dave隐藏区块46的恶意交易，只提供正常的proof units
        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 🔥 关键：dave故意隐藏区块46的恶意交易，不提供区块46的proof！
            # 区块58：dave->sun组合支付（sun不知道value_2已被双花）
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xsun", "0x1000", 100, True),
                self.generator.create_mock_transaction("0xdave", "0xsun", "0x2000", 200, True)
            ])
            # 注意：故意缺少区块46的proof unit，模拟dave隐藏恶意双花交易
        ]

        merkle_roots = {i: f"root{i}" for i in [0, 3, 5, 8, 15, 17, 27, 38, 39, 46, 56, 58]}

        owner_data = {
            0: "0xalice", 3: "0xzhao", 5: "0xqian", 8: "0xalice", 15: "0xbob",
            17: "0xqian", 27: "0xcharlie", 38: "0xsun", 39: "0xdave",
            46: "0xmalicious_x", 56: "0xdave", 58: "0xsun"
        }

        additional_transactions = {
            3: ["0xzhao"], 5: ["0xzhao"], 8: ["0xalice"], 15: ["0xalice"],
            17: ["0xqian"], 27: ["0xbob"], 38: ["0xqian"], 39: ["0xsun"],
            46: ["0xdave"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        # 创建checkpoint（简化处理）
        checkpoint = None

        return {
            "case_name": "案例7：组合双花交易，有checkpoint",
            "target_value": target_value_1,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xsun",
            "checkpoint": checkpoint,
            "expected_result": VerificationResult.FAILURE,
            "expected_checkpoint_used": True,
            "expected_error_types": ["DOUBLE_SPEND_DETECTED", "INVALID_BLOCK_VALUE_INTERSECTION"],
            "description": "sun使用checkpoint发现dave在区块46的恶意双花行为"
        }

    def case8_combined_double_spend_without_checkpoint(self) -> Dict[str, Any]:
        """
        案例8：组合双花交易，无checkpoint
        eve从未拥有过目标value，从头验证时发现双花
        """
        target_value_1 = self.generator.create_mock_value("0x1000", 100)  # alice line
        target_value_2 = self.generator.create_mock_value("0x2000", 200)  # zhao line

        block_index_list = BlockIndexList(
            index_lst=[0, 15, 27, 56, 58],
            owner=[
                (0, "0xalice"),    # 创世块：alice获得value_1
                (15, "0xbob"),     # 区块15：bob从alice处获得value_1
                (27, "0xcharlie"), # 区块27：charlie从bob处获得value_1
                (56, "0xdave"),    # 区块56：dave从charlie处获得value_1
                (58, "0xeve")      # 区块58：eve从dave处获得value_1+value_2
            ]
        )

        proofs = Mock(spec=Proofs)
        proofs.proof_units = [
            self.generator.create_proof_unit(0, []),
            self.generator.create_proof_unit(15, [
                self.generator.create_mock_transaction("0xalice", "0xbob", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(27, [
                self.generator.create_mock_transaction("0xbob", "0xcharlie", "0x1000", 100, True)
            ]),
            self.generator.create_proof_unit(56, [
                self.generator.create_mock_transaction("0xcharlie", "0xdave", "0x1000", 100, True)
            ]),
            # 🔥 关键：dave故意隐藏区块46的恶意交易，不提供区块46的proof！
            # 区块58：dave->eve组合支付（eve不知道value_2已被双花）
            self.generator.create_proof_unit(58, [
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x1000", 100, True),
                self.generator.create_mock_transaction("0xdave", "0xeve", "0x2000", 200, True)
            ])
            # 注意：故意缺少区块46的proof unit，模拟dave隐藏恶意双花交易
        ]

        merkle_roots = {i: f"root{i}" for i in [0, 3, 5, 8, 15, 17, 27, 38, 39, 46, 56, 58]}

        owner_data = {
            0: "0xalice", 3: "0xzhao", 5: "0xqian", 8: "0xalice", 15: "0xbob",
            17: "0xqian", 27: "0xcharlie", 38: "0xsun", 39: "0xdave",
            46: "0xmalicious_x", 56: "0xdave", 58: "0xeve"
        }

        additional_transactions = {
            3: ["0xzhao"], 5: ["0xzhao"], 8: ["0xalice"], 15: ["0xalice"],
            17: ["0xqian"], 27: ["0xbob"], 38: ["0xqian"], 39: ["0xsun"],
            46: ["0xdave"], 56: ["0xcharlie"], 58: ["0xdave"]
        }

        bloom_filters = self.generator.create_bloom_filter_data(
            list(merkle_roots.keys()), owner_data, additional_transactions
        )

        main_chain_info = self.generator.create_main_chain_info(
            merkle_roots, bloom_filters, 58, additional_transactions
        )

        return {
            "case_name": "案例8：组合双花交易，无checkpoint",
            "target_value": target_value_1,
            "proofs": proofs,
            "block_index_list": block_index_list,
            "main_chain_info": main_chain_info,
            "verifier_address": "0xeve",
            "checkpoint": None,
            "expected_result": VerificationResult.FAILURE,
            "expected_checkpoint_used": False,
            "expected_error_types": ["DOUBLE_SPEND_DETECTED", "INVALID_BLOCK_VALUE_INTERSECTION"],
            "description": "eve从头验证时发现dave在区块46的恶意双花行为"
        }

    def get_all_test_cases(self) -> List[Dict[str, Any]]:
        """获取所有测试案例"""
        return [
            self.case1_simple_normal_with_checkpoint(),
            self.case2_simple_normal_without_checkpoint(),
            self.case3_simple_double_spend_with_checkpoint(),
            self.case4_simple_double_spend_without_checkpoint(),
            self.case5_combined_normal_with_checkpoint(),
            self.case6_combined_normal_without_checkpoint(),
            self.case7_combined_double_spend_with_checkpoint(),
            self.case8_combined_double_spend_without_checkpoint()
        ]

    def get_test_case_by_number(self, case_number: int) -> Dict[str, Any]:
        """根据案例编号获取测试案例"""
        cases = {
            1: self.case1_simple_normal_with_checkpoint,
            2: self.case2_simple_normal_without_checkpoint,
            3: self.case3_simple_double_spend_with_checkpoint,
            4: self.case4_simple_double_spend_without_checkpoint,
            5: self.case5_combined_normal_with_checkpoint,
            6: self.case6_combined_normal_without_checkpoint,
            7: self.case7_combined_double_spend_with_checkpoint,
            8: self.case8_combined_double_spend_without_checkpoint
        }

        if case_number not in cases:
            raise ValueError(f"Invalid case number: {case_number}. Valid range: 1-8")

        return cases[case_number]()


class VPBTestCaseRunner:
    """VPB测试案例运行器"""

    def __init__(self):
        self.test_cases = VPBTestCases()
        self.verifier = VPBVerify()

    def run_case(self, case_number: int) -> Dict[str, Any]:
        """运行指定案例"""
        test_case = self.test_cases.get_test_case_by_number(case_number)

        # 创建验证器（如果需要checkpoint）
        if test_case["checkpoint"]:
            verifier = VPBVerify(checkpoint=test_case["checkpoint"])
        else:
            verifier = VPBVerify()

        # 执行验证
        report = verifier.verify_vpb_pair(
            test_case["target_value"],
            test_case["proofs"],
            test_case["block_index_list"],
            test_case["main_chain_info"],
            test_case["verifier_address"]
        )

        # 分析结果
        result_analysis = self._analyze_result(test_case, report)

        return {
            "case_number": case_number,
            "case_name": test_case["case_name"],
            "description": test_case["description"],
            "test_case_data": test_case,
            "verification_report": report,
            "result_analysis": result_analysis
        }

    def run_all_cases(self) -> List[Dict[str, Any]]:
        """运行所有案例"""
        results = []
        for i in range(1, 9):
            try:
                result = self.run_case(i)
                results.append(result)
            except Exception as e:
                results.append({
                    "case_number": i,
                    "error": str(e),
                    "traceback": str(e.__traceback__) if e.__traceback__ else None
                })
        return results

    def _analyze_result(self, test_case: Dict[str, Any], report: VPBVerificationReport) -> Dict[str, Any]:
        """分析验证结果"""
        analysis = {
            "success": report.result == test_case["expected_result"],
            "checkpoint_used_correctly": (
                (report.checkpoint_used is not None) == test_case["expected_checkpoint_used"]
            ),
            "verification_time_ms": report.verification_time_ms,
            "error_count": len(report.errors),
            "verified_epochs_count": len(report.verified_epochs),
            "details": []
        }

        # 检查checkpoint高度
        if report.checkpoint_used and test_case.get("expected_checkpoint_height"):
            analysis["checkpoint_height_correct"] = (
                report.checkpoint_used.block_height == test_case["expected_checkpoint_height"]
            )

        # 检查错误类型
        if test_case.get("expected_error_types") and report.errors:
            actual_error_types = [err.error_type for err in report.errors]
            analysis["error_types_match"] = any(
                expected_type in actual_error_types
                for expected_type in test_case["expected_error_types"]
            )

        # 添加详细信息
        analysis["details"].append(f"验证结果: {report.result.value}")
        analysis["details"].append(f"是否有效: {report.is_valid}")
        if report.checkpoint_used:
            analysis["details"].append(f"使用检查点: 区块{report.checkpoint_used.block_height}")
        else:
            analysis["details"].append("未使用检查点")

        if report.errors:
            analysis["details"].append(f"错误数量: {len(report.errors)}")
            for error in report.errors[:3]:  # 只显示前3个错误
                analysis["details"].append(f"  - {error.error_type}: {error.error_message}")

        return analysis


# 便捷接口函数
def run_vpb_test_case(case_number: int) -> Dict[str, Any]:
    """运行指定VPB测试案例的便捷函数"""
    runner = VPBTestCaseRunner()
    return runner.run_case(case_number)


def run_all_vpb_test_cases() -> List[Dict[str, Any]]:
    """运行所有VPB测试案例的便捷函数"""
    runner = VPBTestCaseRunner()
    return runner.run_all_cases()


def get_vpb_test_case_data(case_number: int) -> Dict[str, Any]:
    """获取指定VPB测试案例数据的便捷函数"""
    test_cases = VPBTestCases()
    return test_cases.get_test_case_by_number(case_number)


if __name__ == "__main__":
    # 示例用法
    print("VPB测试案例配置文件")
    print("=" * 50)

    # 运行案例1作为示例
    try:
        result = run_vpb_test_case(1)
        print(f"案例 {result['case_number']}: {result['case_name']}")
        print(f"描述: {result['description']}")
        print(f"分析结果: {'通过' if result['result_analysis']['success'] else '失败'}")
        print(f"验证时间: {result['result_analysis']['verification_time_ms']:.2f}ms")

        if result['verification_report'].errors:
            print("错误信息:")
            for error in result['verification_report'].errors:
                print(f"  - {error.error_type}: {error.error_message}")

    except Exception as e:
        print(f"运行案例1时出错: {e}")
        import traceback
        traceback.print_exc()