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
from EZ_Account.Account import Account


class Miner:
    """
    A basic miner class for EZChain blockchain.
    This class provides fundamental mining functionality that can be extended.
    """

    def __init__(self, miner_id: str, blockchain: Optional[Blockchain] = None):
        """
        Initialize the miner with basic configuration.

        Args:
            miner_id (str): Unique identifier for this miner
            blockchain (Blockchain): Reference to the blockchain instance
        """
        self.miner_id = miner_id
        self.blockchain = blockchain
        self.is_mining = False
        self.mined_blocks_count = 0

        # Mining configuration
        self.difficulty = 4  # Number of leading zeros required for valid hash
        self.max_nonce = 2**32  # Maximum nonce value to try

    def set_difficulty(self, difficulty: int):
        """Set the mining difficulty (number of leading zeros)."""
        self.difficulty = max(1, difficulty)
        print(f"[{self.miner_id}] Mining difficulty set to {self.difficulty}")

    def set_blockchain(self, blockchain: Blockchain):
        """Set or update the blockchain reference."""
        self.blockchain = blockchain
        print(f"[{self.miner_id}] Blockchain reference updated")

    def extract_vpb_from_block(self, block: Block) -> Dict[str, Any]:
        """
        从区块中提取VPB相关数据

        Args:
            block: 要处理的区块

        Returns:
            Dict[str, Any]: 包含values、proof_units和block_index的字典
        """
        vpb_data = {
            'values': [],
            'proof_units': [],
            'block_index': None,
            'merkle_tree': None,
            'multi_transactions': []
        }

        try:
            # 1. 从区块中提取交易数据
            if hasattr(block, 'data') and block.data:
                for multi_txn in block.data:
                    if isinstance(multi_txn, MultiTransactions):
                        vpb_data['multi_transactions'].append(multi_txn)

                        # 从每个交易中提取Value对象
                        if hasattr(multi_txn, 'multi_txns') and multi_txn.multi_txns:
                            for single_txn in multi_txn.multi_txns:
                                if hasattr(single_txn, 'value') and single_txn.value:
                                    vpb_data['values'].append(single_txn.value)

            # 2. 创建区块索引
            vpb_data['block_index'] = BlockIndexList(
                index_lst=[block.index],
                owner=(block.index, self.miner_id)
            )

            # 3. 创建Merkle树和证明
            if vpb_data['multi_transactions']:
                from EZ_GENESIS.genesis import GenesisBlockCreator
                creator = GenesisBlockCreator([])  # 使用默认配置

                # 构建Merkle树
                merkle_tree, _ = creator._build_genesis_merkle_tree(vpb_data['multi_transactions'])
                vpb_data['merkle_tree'] = merkle_tree

                # 为每个交易创建Merkle证明和ProofUnit
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

    def distribute_vpb_to_accounts(self, block: Block, accounts: List[Account]) -> bool:
        """
        将区块中的values、proof_units以及block_index传输给指定的accounts
        让accounts可以将这些数据添加到各自的本地VPB管理器中

        这个方法借鉴了test_blockchain_integration_with_real_account.py中
        initialize_accounts_with_project_genesis的实现，但针对常规挖矿场景进行了优化

        Args:
            block: 包含VPB数据的区块
            accounts: 需要接收VPB数据的账户列表

        Returns:
            bool: 是否成功将VPB数据分发给所有账户
        """
        print(f"[{self.miner_id}] Starting VPB distribution for block #{block.index} to {len(accounts)} accounts")

        try:
            # 1. 从区块提取VPB数据
            vpb_data = self.extract_vpb_from_block(block)
            if not vpb_data or not vpb_data['values']:
                print(f"[{self.miner_id}] No VPB data found in block #{block.index}")
                return False

            # 2. 按账户分组VPB数据
            account_vpb_data = self._group_vpb_by_account(vpb_data, accounts)

            # 3. 将VPB数据分发给每个账户
            success_count = 0
            for account in accounts:
                account_addr = account.address

                if account_addr in account_vpb_data:
                    account_data = account_vpb_data[account_addr]

                    # 使用Account的VPBManager进行初始化
                    success = self._transfer_vpb_to_account(account, account_data)
                    if success:
                        success_count += 1
                        print(f"[{self.miner_id}] Successfully transferred VPB to account {account.name} ({account_addr})")
                    else:
                        print(f"[{self.miner_id}] Failed to transfer VPB to account {account.name} ({account_addr})")
                else:
                    print(f"[{self.miner_id}] No VPB data for account {account.name} ({account_addr})")

            # 4. 输出分发结果
            success_rate = (success_count / len(accounts)) * 100 if accounts else 0
            print(f"[{self.miner_id}] VPB distribution completed: {success_count}/{len(accounts)} accounts ({success_rate:.1f}%)")

            return success_count > 0

        except Exception as e:
            print(f"[{self.miner_id}] Error during VPB distribution for block #{block.index}: {e}")
            import traceback
            print(f"[{self.miner_id}] Detailed error: {traceback.format_exc()}")
            return False

    def _group_vpb_by_account(self, vpb_data: Dict[str, Any], accounts: List[Account]) -> Dict[str, Dict[str, Any]]:
        """
        按账户分组VPB数据

        Args:
            vpb_data: 从区块提取的VPB数据
            accounts: 账户列表

        Returns:
            Dict[str, Dict[str, Any]]: 按账户地址分组的VPB数据
        """
        account_data = {}

        # 初始化每个账户的数据结构
        for account in accounts:
            account_data[account.address] = {
                'values': [],
                'proof_units': [],
                'block_index': vpb_data['block_index']
            }

        # 按交易的接收地址分配VPB数据
        for multi_txn in vpb_data['multi_transactions']:
            if hasattr(multi_txn, 'multi_txns'):
                for single_txn in multi_txn.multi_txns:
                    recipient_addr = getattr(single_txn, 'recipient', None)

                    if recipient_addr in account_data:
                        # 添加Value到对应账户
                        if hasattr(single_txn, 'value') and single_txn.value:
                            account_data[recipient_addr]['values'].append(single_txn.value)

        # 分配ProofUnits（简化处理：每个账户都获得所有相关的证明）
        for account_addr in account_data:
            if account_data[account_addr]['values']:  # 只为有Value的账户分配ProofUnits
                account_data[account_addr]['proof_units'] = vpb_data['proof_units']

        return account_data

    def _transfer_vpb_to_account(self, account: Account, account_vpb_data: Dict[str, Any]) -> bool:
        """
        将VPB数据传输给单个账户的VPBManager

        这个方法实现了类似于测试代码中initialize_from_genesis_batch的功能，
        但适用于常规挖矿场景的VPB数据传输

        Args:
            account: 接收VPB数据的账户
            account_vpb_data: 该账户的VPB数据

        Returns:
            bool: 传输是否成功
        """
        try:
            values = account_vpb_data['values']
            proof_units = account_vpb_data['proof_units']
            block_index = account_vpb_data['block_index']

            if not values:
                print(f"[{self.miner_id}] No values to transfer to account {account.name}")
                return False

            # 使用账户的VPBManager进行批量初始化
            # 这里复用创世块初始化的逻辑，但适用于挖矿场景
            success = account.vpb_manager.initialize_from_genesis_batch(
                genesis_values=values,
                genesis_proof_units=proof_units,
                genesis_block_index=block_index
            )

            if success:
                total_value = sum(v.value_num for v in values)
                print(f"[{self.miner_id}] Transferred {len(values)} values (total: {total_value}) to account {account.name}")
            else:
                print(f"[{self.miner_id}] Failed to initialize VPB for account {account.name}")

            return success

        except Exception as e:
            print(f"[{self.miner_id}] Error transferring VPB to account {account.name}: {e}")
            return False