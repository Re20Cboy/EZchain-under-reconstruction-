"""
EZ_VPB Proofs Module

Proof management system for EZChain VPB system.
Provides unified Account-level proof management capabilities.

Key Components:
- ProofUnit: Individual proof unit containing transaction data and merkle proof
- AccountProofManager: Account-level unified management interface for Values and ProofUnits
- AccountProofStorage: Persistent storage for Account-level proof relationships

Migration Notes:
- The legacy Proofs class is deprecated but maintained for backward compatibility
- New implementations should use AccountProofManager for better architecture
"""

from .ProofUnit import ProofUnit
from .AccountProofManager import AccountProofManager, AccountProofStorage
from .Proofs import Proofs, LegacyProofsStorage

__all__ = [
    'ProofUnit',
    'AccountProofManager',
    'AccountProofStorage',
    'Proofs',
    'LegacyProofsStorage'
]
