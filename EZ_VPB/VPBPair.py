import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Value import Value
from EZ_Proof import Proofs
from EZ_BlockIndex import BlockIndexList

class VPBpair:
    def __init__(self, value: Value, proofs: Proofs, block_index_lst: BlockIndexList):
        self.value = value
        self.proofs = proofs
        self.block_index_lst = block_index_lst

    def update_vpb(self, new_value=None, new_proofs=None, new_block_indices=None):
        """
        Update the VPB pair with new components.

        Args:
            new_value (Value, optional): New Value object to replace current value
            new_proofs (Proofs, optional): New Proofs object to replace current proofs
            new_block_indices (BlockIndexList or list, optional): New block indices to replace current list

        Returns:
            bool: True if update was successful, False otherwise

        Raises:
            ValueError: If invalid parameters are provided
        """
        try:
            # Update value if provided
            if new_value is not None:
                if not isinstance(new_value, Value):
                    raise ValueError("new_value must be a Value instance")
                self.value = new_value

            # Update proofs if provided
            if new_proofs is not None:
                if not isinstance(new_proofs, Proofs):
                    raise ValueError("new_proofs must be a Proofs instance")
                self.proofs = new_proofs

            # Update block index list if provided
            if new_block_indices is not None:
                if isinstance(new_block_indices, BlockIndexList):
                    self.block_index_lst = new_block_indices
                elif isinstance(new_block_indices, list):
                    self.block_index_lst = BlockIndexList(new_block_indices, owner=self.block_index_lst.owner)
                else:
                    raise ValueError("new_block_indices must be a BlockIndexList or list")

            return True

        except Exception as e:
            print(f"Error updating VPB: {str(e)}")
            return False

    def delete_vpb(self):
        """
        Delete/clean up the VPB pair by clearing all components.

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # Clear all components
            self.value = None
            self.proofs = None
            self.block_index_lst = None

            return True

        except Exception as e:
            print(f"Error deleting VPB: {str(e)}")
            return False

    def get_vpb_info(self):
        """
        Get information about the VPB pair.

        Returns:
            dict: Dictionary containing VPB information
        """
        if not self.is_valid_vpb():
            return {"status": "invalid", "components": {}}

        info = {
            "status": "valid",
            "components": {
                "value": {
                    "begin_index": self.value.begin_index,
                    "end_index": self.value.end_index,
                    "value_num": self.value.value_num,
                    "state": self.value.state.value
                },
                "proofs": {
                    "proof_count": len(self.proofs.proof_units) if self.proofs.proof_units else 0
                },
                "block_indices": {
                    "indices": self.block_index_lst.index_lst,
                    "owner": self.block_index_lst.owner
                }
            }
        }

        return info

