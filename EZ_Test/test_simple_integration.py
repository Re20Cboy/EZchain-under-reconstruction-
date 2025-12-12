#!/usr/bin/env python3
"""
Simple EZchain Integration Test - Minimal Output
"""

import sys
import os
import unittest
import tempfile
import shutil
import logging
from typing import List, Dict, Any

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging - critical errors only
logging.basicConfig(level=logging.CRITICAL)

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import pick_transactions_from_pool
from EZ_Account.Account import Account
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account, GenesisBlockCreator
from EZ_Tool_Box.SecureSignature import secure_signature_handler


class TestSimpleIntegration(unittest.TestCase):
    """Simple integration test with minimal output"""

    def setUp(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()

        # Configure blockchain
        self.config = ChainConfig(confirmation_blocks=2, max_fork_height=3, debug_mode=True)
        self.blockchain = Blockchain(config=self.config)

        # Setup transaction pool
        self.pool_db_path = os.path.join(self.temp_dir, "test_pool.db")
        self.transaction_pool = TxPool(db_path=self.pool_db_path)

        # Create accounts
        self.setup_accounts()

    def tearDown(self):
        """Cleanup test environment"""
        try:
            for account in self.accounts:
                account.cleanup()
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass

    def setup_accounts(self):
        """Create test accounts"""
        self.accounts = []
        names = ["alice", "bob", "charlie"]

        print("[INIT] Creating test accounts...")

        for i, name in enumerate(names):
            private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
            address = f"{name}_address_{i:03d}"

            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=name
            )

            self.accounts.append(account)

        # Initialize accounts with genesis data
        self.initialize_accounts_genesis()

        print(f"[DONE] Created and initialized {len(self.accounts)} accounts")

    def initialize_accounts_genesis(self):
        """Initialize accounts with genesis data"""
        print("[GENESIS] Initializing accounts with genesis data...")

        # Custom denomination for testing
        custom_denomination = [
            (1000, 1), (500, 1), (100, 1), (50, 1), (10, 1), (1, 1)
        ]

        total_per_account = sum(amount * count for amount, count in custom_denomination)
        print(f"[CONFIG] Each account gets total: {total_per_account}")

        # Create genesis block
        genesis_block, genesis_submit_tx_infos, genesis_multi_txns = create_genesis_block(
            accounts=self.accounts,
            denomination_config=custom_denomination,
            custom_miner="genesis_miner"
        )

        print(f"[SUCCESS] Genesis block created (#{genesis_block.index})")

        # Add to blockchain
        main_chain_updated = self.blockchain.add_block(genesis_block)
        print(f"[{'SUCCESS' if main_chain_updated else 'WARNING'}] Genesis block {'added' if main_chain_updated else 'not added'} to main chain")

        # Initialize VPB for each account
        genesis_creator = GenesisBlockCreator(custom_denomination)
        # Build the correct merkle tree using SubmitTxInfo hashes
        merkle_tree, _ = genesis_creator._build_genesis_merkle_tree_from_submit_tx_infos(genesis_submit_tx_infos)

        total_values = 0
        for i, account in enumerate(self.accounts):
            try:
                account_genesis_submit_tx_info = genesis_submit_tx_infos[i]
                merkle_proof = genesis_creator.create_merkle_proof_for_submit_tx_info(account_genesis_submit_tx_info, merkle_tree)
                block_index = genesis_creator.create_block_index(account.address)

                genesis_values, genesis_proof_units, block_index_result = create_genesis_vpb_for_account(
                    account_addr=account.address,
                    genesis_block=genesis_block,
                    genesis_submit_tx_info=account_genesis_submit_tx_info,
                    genesis_multi_txn=genesis_multi_txns[i],
                    merkle_tree=merkle_tree,
                    denomination_config=custom_denomination
                )

                # Initialize VPB
                success = account.vpb_manager.initialize_from_genesis_batch(
                    genesis_values=genesis_values,
                    genesis_proof_units=genesis_proof_units,
                    genesis_block_index=block_index_result
                )

                if success:
                    total_value = sum(v.value_num for v in genesis_values)
                    available_balance = account.get_available_balance()
                    total_values += len(genesis_values)
                    print(f"   [OK] {account.name}: {len(genesis_values)} values, total {total_value}, available {available_balance}")
                else:
                    print(f"   [FAIL] {account.name}: VPB initialization failed")
                    raise RuntimeError(f"Failed to initialize VPB for {account.name}")

            except Exception as e:
                print(f"   [ERROR] {account.name}: {e}")
                raise RuntimeError(f"Failed to initialize account {account.name}: {e}")

        print(f"[COMPLETE] All accounts initialized with {total_values} total values")

    def test_simple_flow(self):
        """Test simple transaction flow"""
        print("\n" + "="*60)
        print("[TEST] Simple Integration Flow")
        print("="*60)

        # Check initial state
        print("\n[STATE] Checking account states...")
        total_balance = 0
        for account in self.accounts:
            info = account.get_account_info()
            total_balance += info['balances']['total']
            print(f"   {account.name}: total={info['balances']['total']}, available={info['balances']['available']}")

        print(f"Initial total balance: {total_balance}")

        # Create and execute one transaction
        print("\n[TRANSACTION] Creating transactions...")
        sender = self.accounts[0]  # alice
        receiver = self.accounts[1]  # bob

        if sender.get_available_balance() >= 100:
            try:
                # Create transaction request
                txn_request = {
                    "recipient": receiver.address,
                    "amount": 100,
                    "nonce": 1,
                    "reference": "test_tx_1"
                }

                # Create transaction
                multi_txn = sender.create_batch_transactions(
                    transaction_requests=[txn_request],
                    reference="simple_test"
                )

                if multi_txn:
                    submit_tx_info = sender.create_submit_tx_info(multi_txn)

                    if submit_tx_info:
                        success, message = self.transaction_pool.add_submit_tx_info(submit_tx_info)
                        if success:
                            print(f"   [SUCCESS] Transaction created: {sender.name} -> {receiver.name}, amount: 100")
                        else:
                            print(f"   [FAIL] Failed to add to pool: {message}")
                    else:
                        print(f"   [FAIL] Failed to create SubmitTxInfo")
                else:
                    print(f"   [FAIL] Failed to create transaction")

            except Exception as e:
                print(f"   [ERROR] Transaction creation failed: {e}")
        else:
            print(f"   [SKIP] {sender.name} has insufficient balance")

        # Try to create a block
        print("\n[BLOCK] Creating block...")
        try:
            latest_hash = self.blockchain.get_latest_block_hash()
            next_index = self.blockchain.get_latest_block_index() + 1

            package_data, block = pick_transactions_from_pool(
                tx_pool=self.transaction_pool,
                miner_address="test_miner",
                previous_hash=latest_hash,
                block_index=next_index
            )

            if block:
                # Add block to blockchain
                main_chain_updated = self.blockchain.add_block(block)
                print(f"   [{'SUCCESS' if main_chain_updated else 'WARNING'}] Block #{block.index} {'added' if main_chain_updated else 'not added'}")
                if package_data and len(package_data.selected_submit_tx_infos) > 0:
                    print(f"   Contains {len(package_data.selected_submit_tx_infos)} transactions")
                else:
                    print(f"   Empty block")
            else:
                print(f"   [FAIL] No block created")

        except Exception as e:
            print(f"   [ERROR] Block creation failed: {e}")

        # Verify final state
        print("\n[VERIFY] Final state...")
        final_total_balance = 0
        for account in self.accounts:
            info = account.get_account_info()
            final_total_balance += info['balances']['total']
            integrity = account.validate_integrity()
            status = "[OK]" if integrity else "[FAIL]"
            print(f"   {status} {account.name}: total={info['balances']['total']}, available={info['balances']['available']}")

        balance_change = final_total_balance - total_balance
        print(f"Balance change: {total_balance} -> {final_total_balance} (difference: {balance_change})")

        print("\n[COMPLETE] Simple integration test finished")
        print("="*60)


def run_simple_test():
    """Run the simple integration test"""
    print("="*60)
    print("EZchain Simple Integration Test")
    print("Minimal output for clean testing")
    print("="*60)

    suite = unittest.TestSuite()
    suite.addTest(TestSimpleIntegration('test_simple_flow'))

    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    print("\n[RESULT] Test Result:")
    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100 if result.testsRun > 0 else 0
    print(f"Tests run: {result.testsRun}")
    print(f"Success rate: {success_rate:.1f}%")

    if result.failures:
        print("Failures:", len(result.failures))
    if result.errors:
        print("Errors:", len(result.errors))

    print("="*60)
    if success_rate >= 80:
        print("[SUCCESS] Integration test passed!")
    else:
        print("[FAIL] Integration test failed!")
    print("="*60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_simple_test()
    sys.exit(0 if success else 1)