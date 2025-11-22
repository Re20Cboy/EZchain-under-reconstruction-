"""
EZ_Proof Module

Proof management system for EZChain blockchain.
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

__version__ = "2.0.0"
__author__ = "EZChain Team"

__all__ = [
    # Core components
    'ProofUnit',

    # New architecture (recommended)
    'AccountProofManager',
    'AccountProofStorage',

    # Legacy components (deprecated)
    'Proofs',
    'LegacyProofsStorage'
]

# Recommended usage patterns
def create_account_proof_manager(account_address: str, db_path: str = None) -> AccountProofManager:
    """
    Create a new AccountProofManager instance with optional custom storage

    Args:
        account_address: The account address to manage proofs for
        db_path: Optional custom database path

    Returns:
        AccountProofManager: New manager instance
    """
    storage = AccountProofStorage(db_path) if db_path else None
    return AccountProofManager(account_address, storage)

def migrate_legacy_proofs(legacy_proofs: 'Proofs', account_address: str) -> AccountProofManager:
    """
    Migrate data from legacy Proofs to new AccountProofManager

    Args:
        legacy_proofs: Existing Proofs instance to migrate from
        account_address: Target account address for the new manager

    Returns:
        AccountProofManager: New manager with migrated data
    """
    return legacy_proofs.migrate_to_account_proof_manager(account_address)