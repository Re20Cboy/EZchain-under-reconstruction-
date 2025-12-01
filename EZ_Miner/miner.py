import sys
import os
import hashlib
import json
from typing import List, Optional, Dict, Any, Tuple

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Main_Chain.Block import Block
from EZ_Main_Chain.Blockchain import Blockchain
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof


class Miner:
    """
    EZChain Miner - 负责挖矿和VPB数据准备

    核心功能:
    - VPB数据提取和准备
    - 按地址分组VPB数据，支持分布式传输
    - 不直接操作Account对象，确保节点分离
    """

    def __init__(self, miner_id: str, blockchain: Optional[Blockchain] = None):
        self.miner_id = miner_id
        self.blockchain = blockchain
        self.is_mining = False
        self.mined_blocks_count = 0
        self.difficulty = 4
        self.max_nonce = 2**32

    def set_difficulty(self, difficulty: int):
        self.difficulty = max(1, difficulty)
        print(f"[{self.miner_id}] Mining difficulty set to {self.difficulty}")

    def set_blockchain(self, blockchain: Blockchain):
        self.blockchain = blockchain
        print(f"[{self.miner_id}] Blockchain reference updated")

    def extract_vpb_from_block(self, block: Block) -> Dict[str, Any]:
        """从区块中提取VPB数据"""
        vpb_data = {
            'values': [],
            'proof_units': [],
            'block_index': None,
            'merkle_tree': None,
            'multi_transactions': []
        }

        try:
            if hasattr(block, 'data') and block.data:
                for multi_txn in block.data:
                    if isinstance(multi_txn, MultiTransactions):
                        vpb_data['multi_transactions'].append(multi_txn)
                        if hasattr(multi_txn, 'multi_txns') and multi_txn.multi_txns:
                            for single_txn in multi_txn.multi_txns:
                                if hasattr(single_txn, 'value') and single_txn.value:
                                    vpb_data['values'].append(single_txn.value)

            vpb_data['block_index'] = BlockIndexList(
                index_lst=[block.index],
                owner=(block.index, self.miner_id)
            )

            if vpb_data['multi_transactions']:
                from EZ_GENESIS.genesis import GenesisBlockCreator
                creator = GenesisBlockCreator([])
                merkle_tree, _ = creator._build_genesis_merkle_tree(vpb_data['multi_transactions'])
                vpb_data['merkle_tree'] = merkle_tree

                for multi_txn in vpb_data['multi_transactions']:
                    merkle_proof = creator.create_merkle_proof(multi_txn, merkle_tree)
                    proof_unit = ProofUnit(
                        owner=self.miner_id,
                        owner_multi_txns=multi_txn,
                        owner_mt_proof=merkle_proof
                    )
                    vpb_data['proof_units'].append(proof_unit)

            print(f"[{self.miner_id}] Extracted VPB data from block #{block.index}: "
                  f"{len(vpb_data['values'])} values, {len(vpb_data['proof_units'])} proof units")

        except Exception as e:
            print(f"[{self.miner_id}] Error extracting VPB data from block #{block.index}: {e}")
            return {}

        return vpb_data

    def prepare_vpb_distribution_data(self, block: Block, recipient_addresses: List[str]) -> Dict[str, Any]:
        """准备VPB分发数据，按地址分组，供网络层传输使用"""
        print(f"[{self.miner_id}] Preparing VPB distribution data for block #{block.index} to {len(recipient_addresses)} addresses")

        try:
            vpb_data = self.extract_vpb_from_block(block)
            if not vpb_data or not vpb_data['values']:
                print(f"[{self.miner_id}] No VPB data found in block #{block.index}")
                return {'error': 'No VPB data found in block', 'block_index': block.index}

            distribution_data = self._group_vpb_by_addresses(vpb_data, recipient_addresses)
            accounts_with_values = len([addr for addr, data in distribution_data.items() if data['values']])
            total_values = sum(len(data['values']) for data in distribution_data.values())

            result = {
                'block_index': block.index,
                'distributions': distribution_data,
                'summary': {
                    'total_accounts': len(recipient_addresses),
                    'accounts_with_values': accounts_with_values,
                    'total_values': total_values,
                    'total_proof_units': len(vpb_data['proof_units'])
                }
            }

            print(f"[{self.miner_id}] VPB data prepared: {accounts_with_values}/{len(recipient_addresses)} accounts will receive {total_values} values")
            return result

        except Exception as e:
            print(f"[{self.miner_id}] Error preparing VPB distribution data for block #{block.index}: {e}")
            return {'error': str(e), 'block_index': block.index}

  
    def _group_vpb_by_addresses(self, vpb_data: Dict[str, Any], recipient_addresses: List[str]) -> Dict[str, Dict[str, Any]]:
        """按地址分组VPB数据"""
        address_data = {}
        for addr in recipient_addresses:
            address_data[addr] = {
                'values': [],
                'proof_units': [],
                'block_index': vpb_data['block_index'],
                'metadata': {
                    'total_value': 0,
                    'value_count': 0,
                    'proof_count': len(vpb_data['proof_units'])
                }
            }

        for multi_txn in vpb_data['multi_transactions']:
            if hasattr(multi_txn, 'multi_txns'):
                for single_txn in multi_txn.multi_txns:
                    recipient_addr = getattr(single_txn, 'recipient', None)
                    if recipient_addr in address_data and hasattr(single_txn, 'value') and single_txn.value:
                        address_data[recipient_addr]['values'].append(single_txn.value)
                        address_data[recipient_addr]['metadata']['total_value'] += single_txn.value.value_num
                        address_data[recipient_addr]['metadata']['value_count'] += 1

        for addr in address_data:
            if address_data[addr]['values']:
                address_data[addr]['proof_units'] = vpb_data['proof_units']

        return address_data

    
    