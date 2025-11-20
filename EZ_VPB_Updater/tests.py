"""
EZChain VPB Updater 简化测试

提供核心功能的基本测试验证。
"""

import unittest
import tempfile
import os
from datetime import datetime

# Mock组件（内联定义）
from enum import Enum
import hashlib
from dataclasses import dataclass

class ValueState(Enum):
    UNSPENT = "unspent"
    SELECTED = "selected"
    LOCAL_COMMITTED = "local_committed"
    CONFIRMED = "confirmed"

class Value:
    def __init__(self, begin_index: str, value_num: int):
        self.begin_index = begin_index
        self.value_num = value_num
        self.end_index = self.get_end_index(begin_index, value_num)

    @staticmethod
    def get_end_index(begin_index: str, value_num: int) -> str:
        begin_decimal = int(begin_index, 16)
        end_decimal = begin_decimal + value_num - 1
        return hex(end_decimal)

    def get_begin_index(self) -> str:
        return self.begin_index

class Transaction:
    def __init__(self, sender: str, recipient: str, value: int, fee: int, nonce: int):
        self.sender = sender
        self.recipient = recipient
        self.value = value
        self.fee = fee
        self.nonce = nonce
        self.digest = hashlib.sha256(f"{sender}{recipient}{value}{fee}{nonce}".encode()).hexdigest()

class MultiTransactions:
    def __init__(self, sender: str, multi_txns):
        self.sender = sender
        self.multi_txns = multi_txns
        self.digest = hashlib.sha256(f"{sender}{len(multi_txns)}".encode()).hexdigest()

class MerkleTreeProof:
    def __init__(self, merkle_root: str, proof_hash: str, index: int):
        self.merkle_root = merkle_root
        self.proof_hash = proof_hash
        self.index = index

class ProofUnit:
    def __init__(self, owner: str, owner_multi_txns: MultiTransactions, owner_mt_proof: MerkleTreeProof):
        self.owner = owner
        self.owner_multi_txns = owner_multi_txns
        self.owner_mt_proof = owner_mt_proof
        self.unit_id = hashlib.sha256(f"{owner}{owner_multi_txns.digest}".encode()).hexdigest()[:16]
        self.reference_count = 0

class Proofs:
    def __init__(self):
        self._proof_units = []

    def add_proof_unit(self, proof_unit: ProofUnit):
        self._proof_units.append(proof_unit)
        proof_unit.reference_count += 1

    def get_proof_units(self):
        return self._proof_units.copy()

class BlockIndexList:
    def __init__(self, owner: str):
        self.owner = owner
        self.index_lst = []
        self._owner_history = []

    def add_block_height(self, block_height: int):
        if block_height not in self.index_lst:
            self.index_lst.append(block_height)
            self.index_lst.sort()

    def add_ownership_change(self, block_index: int, new_owner: str):
        self._owner_history.append((block_index, new_owner))

    def get_current_owner(self) -> str:
        return self._owner_history[-1][1] if self._owner_history else self.owner

@dataclass
class VPBPair:
    value: Value
    proofs: Proofs
    block_index_lst: BlockIndexList
    vpb_id: str = ""

    def __post_init__(self):
        if not self.vpb_id:
            self.vpb_id = hashlib.sha256(f"{self.value.begin_index}{self.value.value_num}".encode()).hexdigest()[:16]

class VPBStorage:
    def __init__(self):
        self._vpbs = {}

    def store_vpb_triplet(self, vpb_pair: VPBPair):
        self._vpbs[vpb_pair.vpb_id] = vpb_pair

    def load_all_vpb_triplets(self):
        return list(self._vpbs.values())

class VPBManager:
    def __init__(self, storage: VPBStorage):
        self.storage = storage

    def update_vpb(self, vpb_pair: VPBPair):
        self.storage.store_vpb_triplet(vpb_pair)

# 导入VPB Updater
from vpb_updater import VPBUpdater, VPBUpdateRequest, VPBUpdaterFactory, create_vpb_update_request


class TestVPBUpdater(unittest.TestCase):
    """VPBUpdater核心功能测试"""

    def setUp(self):
        self.vpb_updater = VPBUpdaterFactory.create_test_vpb_updater()
        self.test_address = "0x1234567890abcdef"

        # 创建测试交易
        txn = Transaction(self.test_address, "0xbob", 100, 1, 1)
        self.test_transaction = MultiTransactions(self.test_address, [txn])
        self.test_merkle_proof = MerkleTreeProof("test_root", "test_proof", 0)

    def test_vpb_updater_initialization(self):
        """测试VPBUpdater初始化"""
        self.assertIsNotNone(self.vpb_updater.vpb_manager)
        self.assertIsNotNone(self.vpb_updater.vpb_storage)

    def test_vpb_update_request_creation(self):
        """测试VPBUpdateRequest创建"""
        request = VPBUpdateRequest(
            account_address=self.test_address,
            transaction=self.test_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        self.assertEqual(request.account_address, self.test_address)
        self.assertEqual(request.transaction, self.test_transaction)
        self.assertEqual(request.block_height, 100)

    def test_convenience_function(self):
        """测试便利函数"""
        request = create_vpb_update_request(
            account_address=self.test_address,
            transaction=self.test_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        self.assertIsInstance(request, VPBUpdateRequest)

    def test_vpb_update_with_no_vpbs(self):
        """测试无VPB时的更新"""
        request = VPBUpdateRequest(
            account_address=self.test_address,
            transaction=self.test_transaction,
            block_height=100,
            merkle_proof=self.test_merkle_proof
        )

        result = self.vpb_updater.update_vpb_for_transaction(request)

        self.assertTrue(result.success)
        self.assertEqual(len(result.updated_vpb_ids), 0)

    def test_vpb_status_query(self):
        """测试VPB状态查询"""
        status = self.vpb_updater.get_vpb_update_status(self.test_address)

        self.assertIsInstance(status, dict)
        self.assertEqual(status['account_address'], self.test_address)
        self.assertEqual(status['total_vpbs'], 0)


def run_basic_tests():
    """运行基本测试"""
    print("运行VPB Updater基本测试...")
    print("=" * 40)

    # 运行单元测试
    unittest.main(argv=[''], exit=False, verbosity=2)


if __name__ == '__main__':
    run_basic_tests()