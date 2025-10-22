from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof

class ProofUnit:  # value proof within a block
    def __init__(self, owner, owner_multi_txns: MultiTransactions, owner_mt_proof: MerkleTreeProof):
        self.owner = owner
        self.owner_multi_txns = owner_multi_txns  # 在此区块内的ownTxns
        self.owner_mt_proof = owner_mt_proof  # ownTxns对应的mTreeProof

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
            # 1. Verify that all transactions in owner_multi_txns have sender/payer equal to owner
            if self.owner_multi_txns.sender != self.owner:
                return False, f"MultiTransactions sender '{self.owner_multi_txns.sender}' does not match owner '{self.owner}'"

            # Additionally check individual transactions within the MultiTransactions
            for i, txn in enumerate(self.owner_multi_txns.multi_txns):
                if hasattr(txn, 'sender') and txn.sender != self.owner:
                    return False, f"Transaction {i} sender '{txn.sender}' does not match owner '{self.owner}'"
                if hasattr(txn, 'payer') and txn.payer != self.owner:
                    return False, f"Transaction {i} payer '{txn.payer}' does not match owner '{self.owner}'"

            # 2. Check if owner_mt_proof is correctly structured (basic validation)
            if not self.owner_mt_proof.mt_prf_list:
                return False, "Merkle proof list is empty"

            # 3. Check if the first element of owner_mt_proof matches the hash of owner_multi_txns
            if self.owner_multi_txns.digest is None:
                return False, "MultiTransactions digest is None"

            # The first element of mt_prf_list should be the hash of the MultiTransactions digest
            from EZ_Tool_Box.Hash import sha256_hash
            expected_leaf_hash = sha256_hash(self.owner_multi_txns.digest)
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
    