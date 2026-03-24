import tempfile
import unittest

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.values import ValueRange


class EZV2GenesisBootstrapTest(unittest.TestCase):
    def test_account_recover_network_state_imports_remote_genesis_allocations_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=821,
            )
            private_key_pem, public_key_pem = generate_secp256k1_keypair()
            address = address_from_public_key_pem(public_key_pem)
            account = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=821,
                network=network,
                consensus_peer_id="consensus-0",
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
            )
            try:
                consensus.register_genesis_value(address, ValueRange(0, 499))

                first = account.recover_network_state()
                second = account.recover_network_state()

                self.assertEqual(first.applied_genesis_values, 1)
                self.assertEqual(second.applied_genesis_values, 0)
                self.assertEqual(account.wallet.available_balance(), 500)
                self.assertEqual(account.wallet.total_balance(), 500)
                self.assertEqual(len(account.wallet.list_records()), 1)
                self.assertIsNotNone(first.chain_cursor)
                assert first.chain_cursor is not None
                self.assertEqual(first.chain_cursor.height, 0)
            finally:
                account.close()
                consensus.close()
