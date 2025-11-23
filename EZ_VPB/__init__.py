"""
EZ_VPB - EZChain Verifiable Proof Block Module

This module consolidates Value, Proof, and BlockIndex components
to provide unified VPB (Value-Proofs-BlockIndex) management functionality.
"""

from .values import Value, ValueState, AccountValueCollection, AccountPickValues
from .proofs import Proofs, ProofUnit, AccountProofManager
from .block_index import BlockIndexList
from .VPBPairs import VPBPair, VPBManager, VPBStorage

__all__ = [
    'Value', 'ValueState', 'AccountValueCollection', 'AccountPickValues',
    'Proofs', 'ProofUnit', 'AccountProofManager',
    'BlockIndexList',
    'VPBPair', 'VPBManager', 'VPBStorage'
]