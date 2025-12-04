#!/usr/bin/env python3
"""
Final test suite for pick_transactions_from_pool_with_proofs function using EZChain's correct APIs.
Uses MerkleTreeProof.check_prf for actual Merkle proof verification.
"""

from __future__ import annotations

import sys
import os
import time
import tempfile
import datetime
import hashlib
import unittest
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    # These will be imported dynamically at runtime
    from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
    from EZ_Transaction.MultiTransactions import MultiTransactions
    from EZ_Transaction.SingleTransaction import Transaction

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


class TestPickTxProofsWithRealData(unittest.TestCase):
    """Test pick_transactions_from_pool_with_proofs using ONLY real EZChain modules and APIs."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files."""
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception:
                pass
        self.temp_files.clear()

    def create_temp_file(self, suffix: str = '.db') -> str:
        """Create a temporary file."""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file_path = tmp.name
        self.temp_files.append(file_path)
        return file_path

    def test_import_real_modules(self):
        """Test that we can import all required EZChain modules."""
        try:
            from EZ_Tx_Pool.TXPool import TxPool
            from EZ_Tx_Pool.PickTx import (
                TransactionPicker,
                PackagedBlockData,
                pick_transactions_from_pool_with_proofs
            )
            from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
            from EZ_Transaction.MultiTransactions import MultiTransactions
            from EZ_Transaction.SingleTransaction import Transaction
            from EZ_Main_Chain.Block import Block
            from EZ_VPB.values.Value import Value

            # Test basic Value creation
            test_value = Value("0x1", 10)
            self.assertIsInstance(test_value, Value)

            # Test secure signature
            from EZ_Tool_Box.SecureSignature import TransactionSigner
            signer = TransactionSigner()
            private_key, public_key = signer.generate_key_pair()
            self.assertIsInstance(private_key, bytes)
            self.assertIsInstance(public_key, bytes)

            return True

        except ImportError as e:
            self.fail(f"Cannot import required EZChain modules: {e}")

    def create_real_transaction(self, sender: str, recipient: str, amount: float, nonce: int = None) -> Transaction:
        """Create a real transaction using EZChain modules."""
        from EZ_VPB.values.Value import Value
        from EZ_Transaction.SingleTransaction import Transaction
        from EZ_Tool_Box.SecureSignature import TransactionSigner

        if nonce is None:
            nonce = int(time.time() * 1000000) % (2**32)

        value_num = max(1, int(amount))  # Ensure valueNum is at least 1
        value = Value("0x1", value_num)  # Provide beginIndex="0x1" and valid valueNum

        # Generate key pair and sign the transaction
        signer = TransactionSigner()
        private_key_pem, public_key_pem = signer.generate_key_pair()

        # Create message to sign
        message = f"{sender}{recipient}{amount}{nonce}".encode()
        message_hash = hashlib.sha256(message).digest()  # Get raw bytes for signing

        # Sign the message
        signature = signer.sign_transaction_data(message_hash, private_key_pem)

        return Transaction(
            sender=sender,
            recipient=recipient,
            nonce=nonce,
            signature=signature,
            value=[value],
            time=datetime.datetime.now().isoformat()
        )

    def create_real_multi_transactions(self, sender: str, recipients: List[str], amounts: List[float]) -> MultiTransactions:
        """Create real MultiTransactions using EZChain modules."""
        from EZ_Transaction.MultiTransactions import MultiTransactions

        single_txns = []
        for recipient, amount in zip(recipients, amounts):
            txn = self.create_real_transaction(sender, recipient, amount)
            single_txns.append(txn)

        multi_txn = MultiTransactions(sender=sender, multi_txns=single_txns)
        multi_txn.set_digest()
        return multi_txn

    def create_real_submit_tx_info(self, multi_txn: MultiTransactions) -> 'SubmitTxInfo':
        """Create real SubmitTxInfo using EZChain modules."""
        from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
        from EZ_Tool_Box.SecureSignature import TransactionSigner

        # Generate key pair for transaction validation
        signer = TransactionSigner()
        private_key_pem, public_key_pem = signer.generate_key_pair()

        # Add small delay to ensure unique timestamps for SubmitTxInfo
        time.sleep(0.05)  # 50ms delay to ensure different timestamps

        # Keys are used by SubmitTxInfo for transaction validation
        return SubmitTxInfo(multi_txn, private_key_pem, public_key_pem)

    def verify_merkle_proof_using_correct_api(self, multi_hash: str, merkle_proof: List, expected_root: str) -> bool:
        """Verify Merkle proof using EZChain's MerkleTreeProof.check_prf API."""
        from EZ_Units.MerkleProof import MerkleTreeProof

        try:
            # Use EZChain's built-in Merkle proof verification
            if isinstance(merkle_proof, (list, tuple)) and len(merkle_proof) > 0:
                # Create MerkleTreeProof instance
                merkle_tree_proof = MerkleTreeProof(mt_prf_list=list(merkle_proof))

                # Use existing check_prf method
                return merkle_tree_proof.check_prf(acc_txns_digest=multi_hash, true_root=expected_root)
            else:
                return False

        except Exception as e:
            self.fail(f"Error in Merkle proof verification: {e}")
            return False

    def test_single_transaction(self):
        """Test edge case: pool with exactly one transaction."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        # Create real transaction
        multi_txn = self.create_real_multi_transactions(
            sender="single_sender",
            recipients=["recipient1"],
            amounts=[10.5]
        )
        submit_tx_info = self.create_real_submit_tx_info(multi_txn)

        success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
        self.assertTrue(success, f"Failed to add real transaction: {message}")

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="single_tx_miner",
            previous_hash="0" * 64,
            block_index=2,
            max_submit_tx_infos=10,
            selection_strategy="fifo"
        )

        # Assertions for single transaction
        self.assertEqual(len(package_data.selected_submit_tx_infos), 1)
        self.assertEqual(len(proofs), 1)
        self.assertEqual(block_index, 2)

        # Verify sender_addrs structure
        self.assertIsInstance(sender_addrs, list)
        self.assertEqual(len(sender_addrs), 1)
        self.assertEqual(sender_addrs[0], multi_txn.sender)

        # Verify selected transaction is the one we added
        selected = package_data.selected_submit_tx_infos[0]
        self.assertEqual(selected.multi_transactions_hash, multi_txn.digest)
        self.assertEqual(selected.submitter_address, multi_txn.sender)

        # Verify Merkle proof using correct API
        multi_hash, merkle_proof = proofs[0]
        self.assertEqual(multi_hash, multi_txn.digest)
        self.assertIsNotNone(merkle_proof)

        # Use EZChain's MerkleTreeProof.check_prf method
        is_valid = self.verify_merkle_proof_using_correct_api(
            multi_hash, merkle_proof, package_data.merkle_root
        )
        self.assertTrue(is_valid, f"Merkle proof verification failed for single transaction!")

    def test_multi_transaction_verification(self):
        """Test edge case: verify output correctness of picked_txs_mt_proofs."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs
        from EZ_Units.MerkleTree import MerkleTree

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        # Add multiple different submitters with multi-transactions
        submitters = ["verify_sender_1", "verify_sender_2", "verify_sender_3"]
        multi_txns = []

        for i, sender in enumerate(submitters):
            multi_txn = self.create_real_multi_transactions(
                sender=sender,
                recipients=[f"verify_recipient_{i}_1", f"verify_recipient_{i}_2"],
                amounts=[float(i + 1) * 2.0, float(i + 1) * 1.0]
            )
            submit_tx_info = self.create_real_submit_tx_info(multi_txn)
            success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
            self.assertTrue(success, f"Failed to add verification transaction {i}: {message}")
            multi_txns.append(multi_txn)
            time.sleep(0.1)  # Ensure unique timestamps

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="verification_miner",
            previous_hash="0" * 64,
            block_index=99,  # Use high block index for verification
            max_submit_tx_infos=3,
            selection_strategy="fifo"
        )

        # Verify all three submitters were selected
        self.assertEqual(len(package_data.selected_submit_tx_infos), 3)
        self.assertEqual(len(proofs), 3)
        self.assertEqual(block_index, 99)

        # Verify sender_addrs structure
        self.assertIsInstance(sender_addrs, list)
        self.assertEqual(len(sender_addrs), 3)
        self.assertEqual(set(sender_addrs), set(submitters))

        # Verify output structure correctness
        self.assertIsInstance(package_data.selected_submit_tx_infos, list)
        self.assertIsInstance(proofs, list)
        self.assertIsInstance(block, object)
        self.assertIsInstance(block_index, int)

        # Verify each selected transaction matches what we submitted
        selected_hashes = {info.multi_transactions_hash for info in package_data.selected_submit_tx_infos}
        original_hashes = {multi_txn.digest for multi_txn in multi_txns}
        self.assertEqual(selected_hashes, original_hashes)

        # Verify submitter uniqueness and addresses
        selected_submitters = {info.submitter_address for info in package_data.selected_submit_tx_infos}
        self.assertEqual(len(selected_submitters), 3)
        self.assertEqual(selected_submitters, set(submitters))
        self.assertEqual(set(package_data.submitter_addresses), selected_submitters)  # Use set comparison for order-independent check

        # Verify Merkle root consistency
        self.assertNotEqual(package_data.merkle_root, "")
        self.assertEqual(len(package_data.merkle_root), 64)  # SHA256 hex length

        # Cross-verify Merkle root using independent MerkleTree
        leaf_hashes = [info.multi_transactions_hash for info in package_data.selected_submit_tx_infos]
        manual_merkle_tree = MerkleTree(leaf_hashes)
        expected_root = manual_merkle_tree.get_root_hash()
        self.assertEqual(package_data.merkle_root, expected_root)
        self.assertEqual(block.m_tree_root, expected_root)

        # Verify proof structure and root integrity using correct API
        for i, (multi_hash, merkle_proof) in enumerate(proofs):
            self.assertEqual(multi_hash, multi_txns[i].digest)
            self.assertIsNotNone(merkle_proof)

            # Use EZChain's MerkleTreeProof.check_prf method
            is_valid = self.verify_merkle_proof_using_correct_api(
                multi_hash, merkle_proof, package_data.merkle_root
            )
            self.assertTrue(is_valid, f"Merkle proof verification failed for transaction {i}!")

        # Verify block consistency
        self.assertEqual(block.index, 99)
        self.assertEqual(block.pre_hash, "0" * 64)  # Block uses pre_hash, not previous_hash
        self.assertEqual(block.m_tree_root, expected_root)

    def test_empty_pool(self):
        """Test edge case: completely empty transaction pool."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs
        from EZ_Main_Chain.Block import Block

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="test_miner_empty",
            previous_hash="0" * 64,
            block_index=1,
            max_submit_tx_infos=10,
            selection_strategy="fifo"
        )

        # Assertions for empty pool
        self.assertEqual(len(package_data.selected_submit_tx_infos), 0)
        self.assertEqual(package_data.merkle_root, "")
        self.assertEqual(len(package_data.submitter_addresses), 0)
        self.assertEqual(len(proofs), 0)
        self.assertEqual(block_index, 1)
        self.assertIsInstance(block, Block)
        self.assertEqual(block.index, 1)

        # Verify sender_addrs structure for empty pool
        self.assertIsInstance(sender_addrs, list)
        self.assertEqual(len(sender_addrs), 0)

    def test_sender_addrs_and_proofs_correspondence(self):
        """Test that sender_addrs corresponds one-to-one with picked_txs_mt_proofs."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        # Test with different numbers of transactions
        test_cases = [1, 3, 5, 7]

        for num_txs in test_cases:
            # Clear pool for each test case
            tx_pool.pool.clear()
            if hasattr(tx_pool, 'hash_index'):
                tx_pool.hash_index.clear()
            if hasattr(tx_pool, 'multi_tx_hash_index'):
                tx_pool.multi_tx_hash_index.clear()

            # Create transactions with unique senders
            senders = []
            multi_txns = []
            for i in range(num_txs):
                sender = f"correspondence_sender_{i}_{num_txs}"
                senders.append(sender)

                multi_txn = self.create_real_multi_transactions(
                    sender=sender,
                    recipients=[f"recipient_{i}_1", f"recipient_{i}_2"],
                    amounts=[float(i + 1) * 1.5, float(i + 1) * 2.0]
                )
                submit_tx_info = self.create_real_submit_tx_info(multi_txn)

                success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
                self.assertTrue(success, f"Failed to add transaction {i} for case {num_txs}: {message}")
                multi_txns.append(multi_txn)
                time.sleep(0.05)  # Ensure unique timestamps

            # Pick transactions with proofs
            package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
                tx_pool=tx_pool,
                miner_address=f"correspondence_miner_{num_txs}",
                previous_hash="0" * 64,
                block_index=100 + num_txs,
                max_submit_tx_infos=num_txs,
                selection_strategy="fifo"
            )

            # Verify one-to-one correspondence
            self.assertEqual(len(sender_addrs), len(proofs),
                           f"Case {num_txs}: sender_addrs count ({len(sender_addrs)}) != proofs count ({len(proofs)})")
            self.assertEqual(len(sender_addrs), len(package_data.selected_submit_tx_infos),
                           f"Case {num_txs}: sender_addrs count ({len(sender_addrs)}) != selected transactions count ({len(package_data.selected_submit_tx_infos)})")
            self.assertEqual(len(proofs), len(package_data.selected_submit_tx_infos),
                           f"Case {num_txs}: proofs count ({len(proofs)}) != selected transactions count ({len(package_data.selected_submit_tx_infos)})")

            # Verify each sender address corresponds to the correct transaction
            selected_senders_from_package = [tx_info.submitter_address for tx_info in package_data.selected_submit_tx_infos]
            self.assertEqual(set(sender_addrs), set(selected_senders_from_package),
                           f"Case {num_txs}: sender_addrs don't match selected transaction submitters")

            # Verify each proof corresponds to a selected transaction
            proof_hashes = [proof_hash for proof_hash, _ in proofs]
            selected_hashes = [tx_info.multi_transactions_hash for tx_info in package_data.selected_submit_tx_infos]
            self.assertEqual(set(proof_hashes), set(selected_hashes),
                           f"Case {num_txs}: proof hashes don't match selected transaction hashes")

            # Verify the order correspondence (should be the same order)
            for i, (sender_addr, (proof_hash, proof)) in enumerate(zip(sender_addrs, proofs)):
                # Find the corresponding selected transaction
                matching_tx_info = None
                for tx_info in package_data.selected_submit_tx_infos:
                    if tx_info.submitter_address == sender_addr and tx_info.multi_transactions_hash == proof_hash:
                        matching_tx_info = tx_info
                        break

                self.assertIsNotNone(matching_tx_info,
                                   f"Case {num_txs}, position {i}: No matching transaction found for sender {sender_addr} with hash {proof_hash}")

            # Additional verification: ensure no duplicates in sender_addrs
            self.assertEqual(len(sender_addrs), len(set(sender_addrs)),
                           f"Case {num_txs}: Duplicate sender addresses found")

    def test_sender_addrs_proofs_order_consistency(self):
        """Test that sender_addrs and picked_txs_mt_proofs maintain consistent ordering."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        # Create transactions with deterministic order
        ordered_senders = ["alpha_sender", "beta_sender", "gamma_sender", "delta_sender"]
        multi_txns = []

        for i, sender in enumerate(ordered_senders):
            multi_txn = self.create_real_multi_transactions(
                sender=sender,
                recipients=[f"recipient_{i}"],
                amounts=[float(i + 1) * 10.0]
            )
            submit_tx_info = self.create_real_submit_tx_info(multi_txn)
            success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
            self.assertTrue(success, f"Failed to add ordered transaction {i}: {message}")
            multi_txns.append(multi_txn)
            time.sleep(0.1)  # Ensure predictable ordering based on timestamps

        # Pick transactions multiple times to verify consistency
        for iteration in range(3):
            package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
                tx_pool=tx_pool,
                miner_address=f"order_miner_{iteration}",
                previous_hash="0" * 64,
                block_index=200 + iteration,
                max_submit_tx_infos=4,
                selection_strategy="fifo"
            )

            # Verify all counts match
            self.assertEqual(len(sender_addrs), len(proofs))
            self.assertEqual(len(sender_addrs), len(package_data.selected_submit_tx_infos))

            # Verify order consistency between sender_addrs and selected transactions
            expected_senders = [tx_info.submitter_address for tx_info in package_data.selected_submit_tx_infos]
            self.assertEqual(sender_addrs, expected_senders,
                           f"Iteration {iteration}: sender_addrs order doesn't match selected transactions order")

            # Verify order consistency between proofs and selected transactions
            expected_hashes = [tx_info.multi_transactions_hash for tx_info in package_data.selected_submit_tx_infos]
            actual_hashes = [proof_hash for proof_hash, _ in proofs]
            self.assertEqual(actual_hashes, expected_hashes,
                           f"Iteration {iteration}: proofs order doesn't match selected transactions order")

            # Verify one-to-one mapping with correct positions
            for i, (sender_addr, (proof_hash, proof)) in enumerate(zip(sender_addrs, proofs)):
                corresponding_tx_info = package_data.selected_submit_tx_infos[i]
                self.assertEqual(sender_addr, corresponding_tx_info.submitter_address,
                               f"Iteration {iteration}, position {i}: Sender address mismatch")
                self.assertEqual(proof_hash, corresponding_tx_info.multi_transactions_hash,
                               f"Iteration {iteration}, position {i}: Proof hash mismatch")

    def test_sender_addrs_proofs_edge_cases(self):
        """Test edge cases for sender_addrs and proofs correspondence."""
        from EZ_Tx_Pool.TXPool import TxPool
        from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs

        db_path = self.create_temp_file()
        tx_pool = TxPool(db_path=db_path)

        # Edge Case 1: Maximum allowed transactions
        tx_pool.pool.clear()
        max_txs = 10
        for i in range(max_txs):
            sender = f"edge_max_sender_{i}"
            multi_txn = self.create_real_multi_transactions(
                sender=sender,
                recipients=[f"edge_recipient_{i}"],
                amounts=[1.0]
            )
            submit_tx_info = self.create_real_submit_tx_info(multi_txn)
            success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
            self.assertTrue(success, f"Failed to add max edge transaction {i}: {message}")
            time.sleep(0.01)

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="edge_max_miner",
            previous_hash="0" * 64,
            block_index=300,
            max_submit_tx_infos=max_txs,
            selection_strategy="fifo"
        )

        self.assertEqual(len(sender_addrs), len(proofs))
        self.assertEqual(len(sender_addrs), max_txs)
        self.assertEqual(len(proofs), max_txs)

        # Edge Case 2: Transaction limit smaller than pool size
        # Re-populate pool for this test case
        for i in range(15):  # Create 15 transactions again
            sender = f"edge_limit_sender_{i}"
            multi_txn = self.create_real_multi_transactions(
                sender=sender,
                recipients=[f"edge_limit_recipient_{i}"],
                amounts=[float(i + 1)]
            )
            submit_tx_info = self.create_real_submit_tx_info(multi_txn)
            success, message = tx_pool.add_submit_tx_info(submit_tx_info, multi_txn)
            self.assertTrue(success, f"Failed to add limit edge transaction {i}: {message}")
            time.sleep(0.01)

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="edge_limit_miner",
            previous_hash="0" * 64,
            block_index=301,
            max_submit_tx_infos=5,  # Less than available transactions
            selection_strategy="fifo"
        )

        self.assertEqual(len(sender_addrs), len(proofs))
        self.assertEqual(len(sender_addrs), 5)
        self.assertEqual(len(proofs), 5)

        # Edge Case 3: Duplicate submitters (should be filtered to unique at TransactionPicker level)
        # Note: TxPool already enforces submitter uniqueness, so we test TransactionPicker filtering
        # by directly adding to pool to bypass TxPool's submitter_index check

        tx_pool.pool.clear()
        # Also clear the submitter index to allow testing duplicate scenarios
        if hasattr(tx_pool, 'submitter_index'):
            tx_pool.submitter_index.clear()

        duplicate_sender = "duplicate_test_sender"
        multi_txns = []

        for i in range(5):  # Create 5 transactions with same sender
            multi_txn = self.create_real_multi_transactions(
                sender=duplicate_sender,
                recipients=[f"dup_recipient_{i}"],
                amounts=[float(i + 1)]
            )
            submit_tx_info = self.create_real_submit_tx_info(multi_txn)

            # Directly add to pool to bypass TxPool's duplicate submitter validation
            # This tests the TransactionPicker level filtering
            tx_pool.pool.append(submit_tx_info)
            multi_txns.append(multi_txn)
            time.sleep(0.01)

        package_data, block, proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=tx_pool,
            miner_address="edge_duplicate_miner",
            previous_hash="0" * 64,
            block_index=302,
            max_submit_tx_infos=10,
            selection_strategy="fifo"
        )

        # Should only have one transaction due to TransactionPicker's submitter uniqueness filter
        self.assertEqual(len(sender_addrs), len(proofs))
        self.assertEqual(len(sender_addrs), 1)
        self.assertEqual(len(proofs), 1)
        self.assertEqual(sender_addrs[0], duplicate_sender)


def run_correct_api_tests():
    """Run all tests with correct EZChain MerkleTreeProof API."""
    print("=" * 80)
    print("Running CORRECT API Tests for pick_transactions_from_pool_with_proofs")
    print("=" * 80)
    print("Note: These tests REQUIRE all EZChain modules to be available")
    print("Using MerkleTreeProof.check_prf for actual Merkle proof verification")
    print("=" * 80)

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPickTxProofsWithRealData)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 80)
    print("CORRECT API Test Results Summary")
    print("=" * 80)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {result.wasSuccessful() * 100:.1f}%")

    if result.failures:
        print(f"\nFailures ({len(result.failures)}):")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.splitlines()[-1] if traceback else 'Unknown error'}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.splitlines()[-1] if traceback else 'Unknown error'}")

    print("=" * 80)
    print("CORRECT API TEST COMPLETE")

    if result.wasSuccessful():
        print("SUCCESS: All correct API tests passed!")
        print("The pick_transactions_from_pool_with_proofs function works correctly with real data.")
        print("Merkle proof verification uses EZChain's MerkleTreeProof.check_prf API.")
    else:
        print("FAILURE: Some correct API tests failed!")
        print("This indicates issues with EZChain module installation or configuration.")

    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    # First test module imports
    test_instance = TestPickTxProofsWithRealData()
    test_instance.test_import_real_modules()

    # Then run all tests
    success = run_correct_api_tests()
    sys.exit(0 if success else 1)
    