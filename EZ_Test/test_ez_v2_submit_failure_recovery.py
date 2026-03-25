from __future__ import annotations

import tempfile
import unittest

from EZ_V2.crypto import generate_secp256k1_keypair, address_from_public_key_pem
from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost
from EZ_V2.networking import NetworkEnvelope, PeerInfo
from EZ_V2.values import ValueRange


class V2SubmitFailureRecoveryTests(unittest.TestCase):
    def test_submit_payment_rolls_back_pending_bundle_when_consensus_send_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            private_key_pem, public_key_pem = generate_secp256k1_keypair()
            address = address_from_public_key_pem(public_key_pem)
            network = StaticPeerNetwork()

            def _consensus_fail(_envelope: NetworkEnvelope):
                raise TimeoutError("simulated_timeout")

            network.register(
                PeerInfo(node_id="consensus-0", role="consensus", endpoint="127.0.0.1:19500"),
                _consensus_fail,
            )
            network.register(
                PeerInfo(
                    node_id="bob",
                    role="account",
                    endpoint="127.0.0.1:19600",
                    metadata={"address": "0x" + "12" * 20},
                ),
                lambda _envelope: {"ok": True},
            )

            account = V2AccountHost(
                node_id="alice",
                endpoint="127.0.0.1:19599",
                wallet_db_path=f"{td}/wallet.sqlite3",
                chain_id=821,
                network=network,
                consensus_peer_id="consensus-0",
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
            )
            try:
                account.register_genesis_value(ValueRange(0, 99))
                with self.assertRaises(TimeoutError):
                    account.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=1)
                self.assertEqual(account.wallet.available_balance(), 100)
                self.assertEqual(len(account.wallet.list_pending_bundles()), 0)
            finally:
                account.close()


if __name__ == "__main__":
    unittest.main()
