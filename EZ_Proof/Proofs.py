import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

class Proofs:
    def __init__(self, proof_units: list):
        self.proof_units = proof_units  # list of ProofUnit instances

    def verify_all_proof_units(self) -> list[tuple[bool, str]]:
        # Verify all ProofUnits in the collection, NOT FOR CKPOINTS!!!
        """
        Verify all ProofUnits in the collection.

        Returns:
            list[tuple[bool, str]]: A list of tuples containing the verification result
            and an error message (if any) for each ProofUnit.
        """
        results = []
        for pu in self.proof_units:
            is_valid, error_message = pu.verify_proof_unit()
            results.append((is_valid, error_message))
        return results
