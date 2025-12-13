import hashlib
import json
import sqlite3
import os
from typing import Optional, TYPE_CHECKING

import sys
sys.path.insert(0, os.path.dirname(__file__) + '/../..')

from EZ_Units.MerkleProof import MerkleTreeProof

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from EZ_Transaction.MultiTransactions import MultiTransactions

def _get_multi_transactions_class():
    """延迟导入MultiTransactions类以避免循环依赖"""
    from EZ_Transaction.MultiTransactions import MultiTransactions
    return MultiTransactions

class ProofUnit:  # value proof within a block
    def __init__(self, owner: str, owner_multi_txns: 'MultiTransactions', owner_mt_proof: MerkleTreeProof, unit_id: Optional[str] = None):
        self.owner = owner
        self.owner_multi_txns = owner_multi_txns  # 在此区块内的ownTxns
        self.owner_mt_proof = owner_mt_proof  # ownTxns对应的mTreeProof
        self.unit_id = unit_id or self._generate_unit_id()
        self.reference_count = 1  # Number of Values referencing this ProofUnit

    # check owner-multi txns-merkle tree proof, mutually matched?
    def verify_proof_unit(self, merkle_root: str = None) -> tuple[bool, str]:
        """
        Verify that the three elements of ProofUnit correspond to each other:
        1. Check if all transactions in owner_multi_txns have sender/payer equal to owner
        2. Check if owner_mt_proof is correctly structured and valid using MerkleTreeProof.check_prf
        3. Check if the first element of owner_mt_proof corresponds to owner_multi_txns

        Args:
            merkle_root: The Merkle root hash to verify against (required for deep proof validation)

        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        try:
            # 1. Verify that owner is involved in the transactions (as sender or recipient)
            owner_is_sender = (self.owner_multi_txns.sender == self.owner)
            owner_is_recipient = False
            owner_involved_count = 0

            for i, txn in enumerate(self.owner_multi_txns.multi_txns):
                # Check if owner is involved in this transaction (as sender, payer, or recipient)
                txn_sender_match = hasattr(txn, 'sender') and txn.sender == self.owner
                txn_payer_match = hasattr(txn, 'payer') and txn.payer == self.owner
                txn_recipient_match = hasattr(txn, 'recipient') and txn.recipient == self.owner

                if txn_sender_match or txn_payer_match or txn_recipient_match:
                    owner_involved_count += 1

                if txn_recipient_match:
                    owner_is_recipient = True

            # Owner must be either the overall sender or involved in at least one transaction
            if not owner_is_sender and not owner_is_recipient and owner_involved_count == 0:
                return False, f"Owner '{self.owner}' is not involved in any transactions (neither as sender nor recipient)"

            # 2. Check if owner_mt_proof is correctly structured (basic validation)
            if not self.owner_mt_proof.mt_prf_list:
                return False, "Merkle proof list is empty"

            # 3. Check if the first element of owner_mt_proof matches the hash of owner_multi_txns
            if self.owner_multi_txns.digest is None:
                return False, "MultiTransactions digest is None"

            # The first element of mt_prf_list should be the MultiTransactions digest
            expected_leaf_hash = self.owner_multi_txns.digest
            actual_leaf_hash = self.owner_mt_proof.mt_prf_list[0]

            if expected_leaf_hash != actual_leaf_hash:
                return False, f"Merkle proof leaf hash mismatch: expected '{expected_leaf_hash}', got '{actual_leaf_hash}'"

            # 4. Deep validation using MerkleTreeProof.check_prf function
            if merkle_root is not None:
                # Use the MerkleTreeProof's own validation function
                is_proof_valid = self.owner_mt_proof.check_prf(
                    acc_txns_digest=self.owner_multi_txns.digest,
                    true_root=merkle_root
                )

                if not is_proof_valid:
                    return False, f"Merkle proof validation failed for digest '{self.owner_multi_txns.digest}' against root '{merkle_root}'"
            else:
                return False, "Merkle root is required for deep proof validation"

            return True, "ProofUnit verification successful"

        except Exception as e:
            return False, f"Error during verification: {str(e)}"

    def _generate_unit_id(self) -> str:
        """Generate unique ID for this ProofUnit based on its content"""
        content_str = f"{self.owner}_{self.owner_multi_txns.digest}_{hash(str(self.owner_mt_proof.mt_prf_list))}"
        return hashlib.sha256(content_str.encode()).hexdigest()

    def to_dict(self) -> dict:
        """Convert ProofUnit to dictionary for storage"""
        return {
            'unit_id': self.unit_id,
            'owner': self.owner,
            'owner_multi_txns': self.owner_multi_txns.to_dict(),
            'owner_mt_proof': self.owner_mt_proof.to_dict(),
            'reference_count': self.reference_count
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ProofUnit':
        """Create ProofUnit from dictionary"""
        from EZ_Transaction.MultiTransactions import MultiTransactions
        from EZ_Units.MerkleProof import MerkleTreeProof

        unit = cls(
            owner=data['owner'],
            owner_multi_txns=MultiTransactions.from_dict(data['owner_multi_txns']),
            owner_mt_proof=MerkleTreeProof.from_dict(data['owner_mt_proof']),
            unit_id=data['unit_id']
        )
        unit.reference_count = data.get('reference_count', 1)
        return unit

    def increment_reference(self):
        """Increment reference count when this ProofUnit is referenced by another Value"""
        self.reference_count += 1

    def decrement_reference(self):
        """Decrement reference count when a Value no longer references this ProofUnit"""
        if self.reference_count > 0:
            self.reference_count -= 1
        return self.reference_count

    def can_be_deleted(self) -> bool:
        """Check if this ProofUnit can be safely deleted (no references)"""
        return self.reference_count <= 0
    