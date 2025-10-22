import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value import Value
from EZ_Proof import Proofs
from EZ_BlockIndex import BlockIndexList

class VPBpair:
    def __init__(self, value, proofs, block_index_lst):
        self.value = value
        self.proofs = proofs
        self.block_index_lst = block_index_lst

