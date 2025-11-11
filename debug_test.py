#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.getcwd())

from EZ_VPB.VPBVerify import VPBVerify
from EZ_Value.Value import Value
from EZ_BlockIndex.BlockIndexList import BlockIndexList
from unittest.mock import Mock

def main():
    print("Starting debug test...")

    # 创建测试数据
    vpb_verifier = VPBVerify()
    value = Value("0x1000", 100)

    # 创建mock proofs
    proofs = Mock()
    proofs.proof_units = []
    for i in range(4):
        proof_unit = Mock()
        proof_unit.verify_proof_unit.return_value = (True, "")
        proofs.proof_units.append(proof_unit)

    # 为每个proof unit添加正确的交易数据
    def create_mock_transaction(sender, receiver):
        """创建模拟交易对象"""
        mock_tx = Mock()
        mock_tx.sender = sender
        mock_tx.payer = sender  # 备用字段
        mock_tx.receiver = receiver
        mock_tx.payee = receiver  # 备用字段

        # 为交易添加必要的input_values、output_values和spent_values属性来模拟value交集
        if receiver == "0xalice":  # 创世交易给Alice
            mock_tx.input_values = [("0xGOD", "0x1000", 0, 100)]  # (sender, value_begin, start, end)
            mock_tx.output_values = [("0x1000", 0, 100)]  # (value_begin, start, end)
            mock_tx.spent_values = []  # 创世交易没有花费的value
        elif receiver == "0xbob":  # Alice转移给Bob
            mock_tx.input_values = [("0xalice", "0x1000", 0, 100)]
            mock_tx.output_values = [("0x1000", 0, 100)]
            mock_tx.spent_values = [("0xalice", "0x1000", 0, 100)]  # Alice花费了这个value
        elif receiver == "0xcharlie":  # Bob转移给Charlie
            mock_tx.input_values = [("0xbob", "0x1000", 0, 100)]
            mock_tx.output_values = [("0x1000", 0, 100)]
            mock_tx.spent_values = [("0xbob", "0x1000", 0, 100)]  # Bob花费了这个value
        elif receiver == "0xdave":  # Charlie转移给Dave
            mock_tx.input_values = [("0xcharlie", "0x1000", 0, 100)]
            mock_tx.output_values = [("0x1000", 0, 100)]
            mock_tx.spent_values = [("0xcharlie", "0x1000", 0, 100)]  # Charlie花费了这个value
        else:
            mock_tx.input_values = []
            mock_tx.output_values = []
            mock_tx.spent_values = []

        return mock_tx

    # 区块0: 创世块，从创世地址(0xGOD)派发value给Alice
    proofs.proof_units[0].block_height = 0
    proofs.proof_units[0].owner_multi_txns = Mock()
    proofs.proof_units[0].owner_multi_txns.multi_txns = [create_mock_transaction("0xGOD", "0xalice")]

    # 区块15: Alice -> Bob (Alice在区块15提交交易转移value)
    proofs.proof_units[1].block_height = 15
    proofs.proof_units[1].owner_multi_txns = Mock()
    proofs.proof_units[1].owner_multi_txns.multi_txns = [create_mock_transaction("0xalice", "0xbob")]

    # 区块27: Bob -> Charlie (Bob在区块27提交交易转移value)
    proofs.proof_units[2].block_height = 27
    proofs.proof_units[2].owner_multi_txns = Mock()
    proofs.proof_units[2].owner_multi_txns.multi_txns = [create_mock_transaction("0xbob", "0xcharlie")]

    # 区块56: Charlie -> Dave (Charlie在区块56提交交易转移value)
    proofs.proof_units[3].block_height = 56
    proofs.proof_units[3].owner_multi_txns = Mock()
    proofs.proof_units[3].owner_multi_txns.multi_txns = [create_mock_transaction("0xcharlie", "0xdave")]

    block_index_list = BlockIndexList(
        index_lst=[0, 15, 27, 56],
        owner=[(0, "0xalice"), (15, "0xbob"), (27, "0xcharlie"), (56, "0xdave")]
    )

    # 创建mock主链信息
    main_chain_info = Mock()
    main_chain_info.merkle_roots = {0: 'root0', 15: 'root15', 27: 'root27', 56: 'root56'}
    main_chain_info.bloom_filters = {}
    main_chain_info.current_block_height = 56

    print("Data created, starting slice generation...")

    try:
        # 第一步：尝试生成VPB切片
        vpb_slice, checkpoint_used = vpb_verifier._generate_vpb_slice(value, proofs, block_index_list, "0xeve")
        print("VPB slice generation successful")

        # 第二步：尝试基本数据结构验证
        basic_validation_result = vpb_verifier._validate_basic_data_structure(value, proofs, block_index_list)
        print(f"Basic validation result: {basic_validation_result}")

        # 第三步：尝试布隆过滤器验证
        print("Setting up main_chain_info mock...")
        additional_transactions = {
            0: ["0xGOD"],           # 创世地址在区块0派发value给alice
            15: ["0xalice"],        # alice在区块15提交交易，将value转移给bob
            27: ["0xbob"],          # bob在区块27提交交易，将value转移给charlie
            56: ["0xcharlie"]       # charlie在区块56提交交易，将value转移给dave
        }

        def mock_get_owner_transaction_blocks(owner_address, start_height, end_height):
            print(f"DEBUG: mock_get_owner_transaction_blocks called with owner={owner_address}, start={start_height}, end={end_height}")
            result = []
            for height in range(start_height, end_height + 1):
                if height in additional_transactions and owner_address in additional_transactions[height]:
                    result.append(height)
            print(f"DEBUG: returning blocks {result} for owner {owner_address}")
            return result

        main_chain_info.get_owner_transaction_blocks = Mock(side_effect=mock_get_owner_transaction_blocks)

        bloom_validation_result = vpb_verifier._verify_bloom_filter_consistency(vpb_slice, main_chain_info)
        print(f"Bloom filter validation result: {bloom_validation_result}")

        # 第四步：尝试proof unit验证
        print("Starting proof units verification...")
        epoch_verification_result = vpb_verifier._verify_proof_units_and_detect_double_spend(
            vpb_slice, main_chain_info
        )
        print(f"Epoch verification result: {epoch_verification_result}")

    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

        # 尝试识别哪个Mock对象导致问题
        print("\nDebugging mock objects...")
        for i, pu in enumerate(proofs.proof_units):
            print(f"Proof unit {i}: type={type(pu)}, block_height={getattr(pu, 'block_height', 'NOT_SET')}")
            if hasattr(pu, 'owner_multi_txns'):
                print(f"  owner_multi_txns: {type(pu.owner_multi_txns)}")
                if hasattr(pu.owner_multi_txns, 'multi_txns'):
                    print(f"  multi_txns: {type(pu.owner_multi_txns.multi_txns)}")
                    print(f"  multi_txns is iterable: {hasattr(pu.owner_multi_txns.multi_txns, '__iter__')}")

if __name__ == "__main__":
    main()