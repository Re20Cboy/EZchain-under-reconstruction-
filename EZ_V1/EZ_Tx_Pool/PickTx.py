"""
Transaction Picker Module
Extracts SubmitTxInfo from transaction pool and packages them into block data structures
Refactored to use SubmitTxInfo structure, leveraging its existing multi_transactions_hash field
According to Block.py design, blocks contain:
- m_tree_root: Merkle tree root composed of SubmitTxInfo's multi_transactions_hash
- bloom: Bloom filter with all SubmitTxInfo's submitter_address added
"""

import sys
import os
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Tx_Pool.TXPool import TxPool
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Main_Chain.Block import Block
from EZ_Units.MerkleTree import MerkleTree
from EZ_Units.MerkleProof import MerkleTreeProof


@dataclass
class PackagedBlockData:
    """Packaged block data structure, designed for Block.py"""
    selected_submit_tx_infos: List[SubmitTxInfo]  # Selected SubmitTxInfo list
    merkle_root: str  # Merkle root (composed of SubmitTxInfo's multi_transactions_hash)
    submitter_addresses: List[str]  # Submitter address list (for bloom filter)
    package_time: datetime.datetime  # Package time

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            'submit_tx_info_hashes': [tx_info.get_hash() for tx_info in self.selected_submit_tx_infos],
            'multi_transactions_hashes': [tx_info.multi_transactions_hash for tx_info in self.selected_submit_tx_infos],
            'merkle_root': self.merkle_root,
            'submitter_addresses': self.submitter_addresses,
            'package_time': self.package_time.isoformat()
        }


class TransactionPicker:
    """Transaction picker, designed for SubmitTxInfo-based transaction pool"""

    def __init__(self, max_submit_tx_infos_per_block: int = 100):
        """
        Initialize transaction picker

        Args:
            max_submit_tx_infos_per_block: Maximum number of SubmitTxInfo per block
        """
        self.max_submit_tx_infos_per_block = max_submit_tx_infos_per_block

    def pick_transactions(self, tx_pool: TxPool,
                         selection_strategy: str = "fifo") -> PackagedBlockData:
        """
        Select transactions from transaction pool to form block data

        Args:
            tx_pool: Transaction pool object
            selection_strategy: Transaction selection strategy ("fifo": first in first out, "fee": sort by fee)

        Returns:
            PackagedBlockData: Packaged block data
        """
        try:
            # Get all SubmitTxInfo to be selected from transaction pool
            all_submit_tx_infos = tx_pool.get_all_submit_tx_infos()

            if not all_submit_tx_infos:
                return PackagedBlockData(
                    selected_submit_tx_infos=[],
                    merkle_root="",
                    submitter_addresses=[],
                    package_time=datetime.datetime.now()
                )

            # Select transactions based on strategy
            selected_submit_tx_infos = self._select_transactions(all_submit_tx_infos, selection_strategy)

            # Limit number of transactions
            selected_submit_tx_infos = selected_submit_tx_infos[:self.max_submit_tx_infos_per_block]

            # Extract submitter addresses (for bloom filter)
            submitter_addresses = self._extract_submitter_addresses(selected_submit_tx_infos)

            # Build merkle tree (using SubmitTxInfo's multi_transactions_hash)
            merkle_root = self._build_merkle_tree_simple(selected_submit_tx_infos)

            return PackagedBlockData(
                selected_submit_tx_infos=selected_submit_tx_infos,
                merkle_root=merkle_root,
                submitter_addresses=submitter_addresses,
                package_time=datetime.datetime.now()
            )

        except Exception as e:
            raise Exception(f"Error picking transactions: {str(e)}")

    def pick_transactions_with_proofs(self, tx_pool: TxPool,
                                    selection_strategy: str = "fifo") -> Tuple[PackagedBlockData, List[Tuple[str, Any]]]:
        """
        Select transactions from transaction pool to form block data with Merkle proofs

        Args:
            tx_pool: Transaction pool object
            selection_strategy: Transaction selection strategy ("fifo": first in first out, "fee": sort by fee)

        Returns:
            Tuple of (PackagedBlockData, picked_txs_mt_proofs)
            picked_txs_mt_proofs: List of (multi_transactions_hash, MerkleTreeProof) tuples
        """
        try:
            # Get all SubmitTxInfo to be selected from transaction pool
            all_submit_tx_infos = tx_pool.get_all_submit_tx_infos()

            if not all_submit_tx_infos:
                return PackagedBlockData(
                    selected_submit_tx_infos=[],
                    merkle_root="",
                    submitter_addresses=[],
                    package_time=datetime.datetime.now()
                ), []

            # Select transactions based on strategy
            selected_submit_tx_infos = self._select_transactions(all_submit_tx_infos, selection_strategy)

            # Limit number of transactions
            selected_submit_tx_infos = selected_submit_tx_infos[:self.max_submit_tx_infos_per_block]

            # Extract submitter addresses (for bloom filter)
            submitter_addresses = self._extract_submitter_addresses(selected_submit_tx_infos)

            # Build merkle tree (using SubmitTxInfo's multi_transactions_hash) and get proofs
            merkle_root, merkle_tree, leaf_info_list = self._build_merkle_tree(selected_submit_tx_infos)

            # Generate MerkleTreeProof for each selected transaction
            picked_txs_mt_proofs = []
            if merkle_tree and merkle_tree.prf_list:
                for multi_transactions_hash, leaf_index in leaf_info_list:
                    if leaf_index < len(merkle_tree.prf_list):
                        proof_hashes = merkle_tree.prf_list[leaf_index]
                        # Wrap the hash list in a MerkleTreeProof object
                        merkle_tree_proof = MerkleTreeProof(mt_prf_list=proof_hashes)
                        picked_txs_mt_proofs.append((multi_transactions_hash, merkle_tree_proof))

            package_data = PackagedBlockData(
                selected_submit_tx_infos=selected_submit_tx_infos,
                merkle_root=merkle_root,
                submitter_addresses=submitter_addresses,
                package_time=datetime.datetime.now()
            )

            return package_data, picked_txs_mt_proofs

        except Exception as e:
            raise Exception(f"Error picking transactions: {str(e)}")

    def _select_transactions(self, submit_tx_infos: List[SubmitTxInfo], strategy: str) -> List[SubmitTxInfo]:
        """
        Select transactions based on strategy, ensuring each submitter has at most one SubmitTxInfo packaged

        Args:
            submit_tx_infos: SubmitTxInfo list
            strategy: Selection strategy

        Returns:
            Selected SubmitTxInfo list (each submitter has at most one)
        """
        if strategy == "fifo":
            # First in first out strategy
            filtered_tx_infos = self._filter_unique_submitters(submit_tx_infos)
            return filtered_tx_infos
        elif strategy == "fee":
            # Sort by fee (simplified: sort by timestamp, newer transactions have priority)
            sorted_tx_infos = sorted(submit_tx_infos, key=lambda x: x.submit_timestamp, reverse=True)
            filtered_tx_infos = self._filter_unique_submitters(sorted_tx_infos)
            return filtered_tx_infos
        else:
            # Default first in first out
            filtered_tx_infos = self._filter_unique_submitters(submit_tx_infos)
            return filtered_tx_infos

    def _filter_unique_submitters(self, submit_tx_infos: List[SubmitTxInfo]) -> List[SubmitTxInfo]:
        """
        Filter SubmitTxInfo list, ensuring each submitter has at most one SubmitTxInfo selected
        For submitters with multiple SubmitTxInfo, select the earliest submitted one

        Args:
            submit_tx_infos: SubmitTxInfo list

        Returns:
            Filtered SubmitTxInfo list (each submitter has at most one)
        """
        seen_submitters = set()
        filtered_tx_infos = []

        for submit_tx_info in submit_tx_infos:
            # Check for valid submitter address
            if not submit_tx_info.submitter_address:
                # If no submitter, keep this transaction
                filtered_tx_infos.append(submit_tx_info)
                continue

            # If this submitter hasn't been selected yet, keep this transaction
            if submit_tx_info.submitter_address not in seen_submitters:
                seen_submitters.add(submit_tx_info.submitter_address)
                filtered_tx_infos.append(submit_tx_info)
            # Otherwise skip this transaction (this submitter already has an earlier/better transaction selected)

        # Record filtered transactions (for debugging and logging)
        if len(submit_tx_infos) != len(filtered_tx_infos):
            filtered_count = len(submit_tx_infos) - len(filtered_tx_infos)
            print(f"Submitter uniqueness filter: removed {filtered_count} duplicate submitter transactions "
                  f"(kept {len(filtered_tx_infos)} unique submitter transactions)")

        return filtered_tx_infos

    def _extract_submitter_addresses(self, submit_tx_infos: List[SubmitTxInfo]) -> List[str]:
        """
        Extract submitter addresses (for bloom filter)

        Args:
            submit_tx_infos: SubmitTxInfo list

        Returns:
            Submitter address list
        """
        submitters = set()
        for submit_tx_info in submit_tx_infos:
            if submit_tx_info.submitter_address:
                submitters.add(submit_tx_info.submitter_address)
        return list(submitters)

    def _build_merkle_tree_simple(self, submit_tx_infos: List[SubmitTxInfo]) -> str:
        """
        Build merkle tree and return root hash (simplified version for backward compatibility)

        Args:
            submit_tx_infos: SubmitTxInfo list

        Returns:
            Merkle root hash
        """
        if not submit_tx_infos:
            return ""

        # Use SubmitTxInfo's multi_transactions_hash as merkle tree leaf nodes
        leaf_hashes = []
        for submit_tx_info in submit_tx_infos:
            leaf_hashes.append(submit_tx_info.multi_transactions_hash)

        # Build merkle tree
        merkle_tree = MerkleTree(leaf_hashes, values_are_hashed=True)
        return merkle_tree.get_root_hash()

    def _build_merkle_tree(self, submit_tx_infos: List[SubmitTxInfo]) -> Tuple[str, MerkleTree, List[Tuple[str, int]]]:
        """
        Build merkle tree and return root hash, tree object, and leaf info

        Args:
            submit_tx_infos: SubmitTxInfo list

        Returns:
            Tuple of (merkle_root_hash, merkle_tree_object, leaf_info_list)
            leaf_info_list: List of (multi_transactions_hash, leaf_index) tuples
        """
        if not submit_tx_infos:
            return "", None, []

        # Use SubmitTxInfo's multi_transactions_hash as merkle tree leaf nodes
        leaf_hashes = []
        leaf_info_list = []
        for i, submit_tx_info in enumerate(submit_tx_infos):
            leaf_hash = submit_tx_info.multi_transactions_hash
            leaf_hashes.append(leaf_hash)
            leaf_info_list.append((leaf_hash, i))

        # Build merkle tree
        merkle_tree = MerkleTree(leaf_hashes, values_are_hashed=True)
        return merkle_tree.get_root_hash(), merkle_tree, leaf_info_list

    def create_block_from_package(self, package_data: PackagedBlockData,
                                 miner_address: str,
                                 previous_hash: str,
                                 block_index: int) -> Block:
        """
        Create block from packaged data

        Args:
            package_data: Packaged block data
            miner_address: Miner address
            previous_hash: Previous block hash
            block_index: Block index

        Returns:
            Block: Created block object
        """
        # Create block
        block = Block(
            index=block_index,
            m_tree_root=package_data.merkle_root,
            miner=miner_address,
            pre_hash=previous_hash,
            time=package_data.package_time
        )

        # Add all SubmitTxInfo's submitter_address to bloom filter
        for submitter in package_data.submitter_addresses:
            block.add_item_to_bloom(submitter)

        return block

    def remove_picked_transactions(self, tx_pool: TxPool,
                                  picked_submit_tx_infos: List[SubmitTxInfo]) -> int:
        """
        Remove picked transactions from transaction pool

        Args:
            tx_pool: Transaction pool object
            picked_submit_tx_infos: Picked SubmitTxInfo list

        Returns:
            Number of successfully removed transactions
        """
        removed_count = 0

        for submit_tx_info in picked_submit_tx_infos:
            submit_hash = submit_tx_info.get_hash()
            success = tx_pool.remove_submit_tx_info(submit_hash)
            if success:
                removed_count += 1

        return removed_count

    def get_package_stats(self, package_data: PackagedBlockData) -> Dict[str, Any]:
        """
        Get packaging statistics

        Args:
            package_data: Packaged block data

        Returns:
            Statistics dictionary
        """
        return {
            'total_submit_tx_infos': len(package_data.selected_submit_tx_infos),
            'unique_submitters': len(package_data.submitter_addresses),
            'merkle_root': package_data.merkle_root,
            'package_time': package_data.package_time.isoformat(),
            'selected_submit_tx_info_hashes': [tx_info.get_hash() for tx_info in package_data.selected_submit_tx_infos],
            'multi_transactions_hashes': [tx_info.multi_transactions_hash for tx_info in package_data.selected_submit_tx_infos]
        }

    def get_multi_transactions_hashes(self, package_data: PackagedBlockData) -> List[str]:
        """
        Get all MultiTransactions hash list in packaged data
        This method can be used to retrieve specific MultiTransactions data from blockchain

        Args:
            package_data: Packaged block data

        Returns:
            MultiTransactions hash list
        """
        return [submit_tx_info.multi_transactions_hash for submit_tx_info in package_data.selected_submit_tx_infos]


# Convenience function (original interface for backward compatibility)
def pick_transactions_from_pool(tx_pool: TxPool,
                              miner_address: str,
                              previous_hash: str,
                              block_index: int,
                              max_submit_tx_infos: int = 100,
                              selection_strategy: str = "fifo") -> Tuple[PackagedBlockData, Block]:
    """
    Convenience function for picking transactions from pool (original interface)

    Args:
        tx_pool: Transaction pool object
        miner_address: Miner address
        previous_hash: Previous block hash
        block_index: Block index
        max_submit_tx_infos: Maximum number of SubmitTxInfo
        selection_strategy: Selection strategy

    Returns:
        (packaged_data, block) tuple
        packaged_data: PackagedBlockData object
        block: Block object
    """
    picker = TransactionPicker(max_submit_tx_infos_per_block=max_submit_tx_infos)

    # Select transactions (using original method for backward compatibility)
    package_data = picker.pick_transactions(
        tx_pool=tx_pool,
        selection_strategy=selection_strategy
    )

    # Create block
    block = picker.create_block_from_package(
        package_data=package_data,
        miner_address=miner_address,
        previous_hash=previous_hash,
        block_index=block_index
    )

    # Remove picked transactions from pool
    removed_count = picker.remove_picked_transactions(
        tx_pool=tx_pool,
        picked_submit_tx_infos=package_data.selected_submit_tx_infos
    )

    # Print statistics
    # 精简输出: print(f"Successfully picked {len(package_data.selected_submit_tx_infos)} SubmitTxInfos "
          # f"and removed {removed_count} transactions from pool")
    # 精简输出: print(f"Merkle root: {package_data.merkle_root}")
    # print(f"Submitters added to bloom filter: {package_data.submitter_addresses}")
    # print(f"MultiTransactions hashes: {picker.get_multi_transactions_hashes(package_data)}")

    return package_data, block

# New convenience function with Merkle proofs
def pick_transactions_from_pool_with_proofs(tx_pool: TxPool,
                                          miner_address: str,
                                          previous_hash: str,
                                          block_index: int,
                                          max_submit_tx_infos: int = 100,
                                          selection_strategy: str = "fifo") -> Tuple[PackagedBlockData, Block, List[Tuple[str, Any]], int, List[str]]:
    """
    Convenience function for picking transactions from pool with Merkle proofs

    Args:
        tx_pool: Transaction pool object
        miner_address: Miner address
        previous_hash: Previous block hash
        block_index: Block index
        max_submit_tx_infos: Maximum number of SubmitTxInfo
        selection_strategy: Selection strategy

    Returns:
        (packaged_data, block, picked_txs_mt_proofs, block_index, sender_addrs) tuple
        packaged_data: PackagedBlockData object
        block: Block object
        picked_txs_mt_proofs: List of (multi_transactions_hash, MerkleTreeProof) tuples
        block_index: Block index number
        sender_addrs: List of sender addresses corresponding one-to-one with picked_txs_mt_proofs
    """
    picker = TransactionPicker(max_submit_tx_infos_per_block=max_submit_tx_infos)

    # Select transactions and get Merkle proofs
    package_data, picked_txs_mt_proofs = picker.pick_transactions_with_proofs(
        tx_pool=tx_pool,
        selection_strategy=selection_strategy
    )

    # Extract sender addresses corresponding to picked_txs_mt_proofs
    sender_addrs = []
    for submit_tx_info in package_data.selected_submit_tx_infos:
        # Get the sender address from each SubmitTxInfo
        # This corresponds to the submitter_address in the transaction data
        sender_addrs.append(submit_tx_info.submitter_address)

    # Create block
    block = picker.create_block_from_package(
        package_data=package_data,
        miner_address=miner_address,
        previous_hash=previous_hash,
        block_index=block_index
    )

    # Remove picked transactions from pool
    removed_count = picker.remove_picked_transactions(
        tx_pool=tx_pool,
        picked_submit_tx_infos=package_data.selected_submit_tx_infos
    )

    # Print statistics
    # 精简输出: print(f"Successfully picked {len(package_data.selected_submit_tx_infos)} SubmitTxInfos "
          # f"and removed {removed_count} transactions from pool")
    # 精简输出: print(f"Merkle root: {package_data.merkle_root}")
    # print(f"Submitters added to bloom filter: {package_data.submitter_addresses}")
    # print(f"MultiTransactions hashes: {picker.get_multi_transactions_hashes(package_data)}")
    # 精简输出: print(f"Generated {len(picked_txs_mt_proofs)} Merkle proofs for transactions")
    # print(f"Sender addresses for VPB distribution: {sender_addrs}")

    return package_data, block, picked_txs_mt_proofs, block_index, sender_addrs
