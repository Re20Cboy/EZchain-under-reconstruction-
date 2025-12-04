import sys
import os
from typing import Optional

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Main_Chain.Blockchain import Blockchain


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

  
    
    