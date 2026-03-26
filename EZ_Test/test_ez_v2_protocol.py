from __future__ import annotations

import unittest

from EZ_V2.chain import (
    ChainStateV2,
    compute_bundle_hash,
    confirmed_ref,
    sign_bundle_envelope,
)
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.types import (
    BundleEnvelope,
    BundleSidecar,
    BundleSubmission,
    ConfirmedBundleUnit,
    OffChainTx,
)
from EZ_V2.values import ValueRange


class EZV2ProtocolTests(unittest.TestCase):
    def _make_submission(
        self,
        private_key_pem: bytes,
        public_key_pem: bytes,
        chain_id: int,
        seq: int,
        expiry_height: int,
        fee: int,
        nonce: int,
        txs,
    ) -> BundleSubmission:
        sender_addr = address_from_public_key_pem(public_key_pem)
        sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=tuple(txs))
        envelope = BundleEnvelope(
            version=2,
            chain_id=chain_id,
            seq=seq,
            expiry_height=expiry_height,
            fee=fee,
            anti_spam_nonce=nonce,
            bundle_hash=compute_bundle_hash(sidecar),
        )
        envelope = sign_bundle_envelope(envelope, private_key_pem)
        return BundleSubmission(envelope=envelope, sidecar=sidecar, sender_public_key_pem=public_key_pem)

    def test_block_build_apply_and_receipt_chain(self) -> None:
        chain_a = ChainStateV2(chain_id=9)
        chain_b = ChainStateV2(chain_id=9)
        alice_priv, alice_pub = generate_secp256k1_keypair()
        alice_addr = address_from_public_key_pem(alice_pub)
        bob_priv, bob_pub = generate_secp256k1_keypair()
        bob_addr = address_from_public_key_pem(bob_pub)

        tx1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(0, 99),),
            tx_local_index=0,
            tx_time=1,
        )
        sub1 = self._make_submission(alice_priv, alice_pub, 9, 1, 10, 1, 1, [tx1])
        chain_a.submit_bundle(sub1)
        block1, receipts1 = chain_a.build_block(timestamp=1)
        apply_receipts1 = chain_b.apply_block(block1)
        self.assertEqual(receipts1[alice_addr].seq, 1)
        self.assertEqual(apply_receipts1[alice_addr].seq, 1)
        self.assertIsNone(receipts1[alice_addr].prev_ref)

        tx2 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(100, 149),),
            tx_local_index=0,
            tx_time=2,
        )
        sub2 = self._make_submission(alice_priv, alice_pub, 9, 2, 20, 1, 2, [tx2])
        chain_a.submit_bundle(sub2)
        block2, receipts2 = chain_a.build_block(timestamp=2)
        chain_b.apply_block(block2)
        unit1 = ConfirmedBundleUnit(receipt=receipts1[alice_addr], bundle_sidecar=sub1.sidecar)
        self.assertEqual(receipts2[alice_addr].prev_ref, confirmed_ref(unit1))

    def test_apply_block_reconciles_follower_bundle_pool_using_finalized_diff_package(self) -> None:
        chain_a = ChainStateV2(chain_id=10)
        chain_b = ChainStateV2(chain_id=10)
        alice_priv, alice_pub = generate_secp256k1_keypair()
        alice_addr = address_from_public_key_pem(alice_pub)
        bob_priv, bob_pub = generate_secp256k1_keypair()
        bob_addr = address_from_public_key_pem(bob_pub)

        tx1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(0, 99),),
            tx_local_index=0,
            tx_time=1,
        )
        sub1 = self._make_submission(alice_priv, alice_pub, 10, 1, 10, 1, 1, [tx1])
        chain_a.submit_bundle(sub1)
        chain_b.submit_bundle(sub1)
        self.assertEqual(len(chain_b.bundle_pool.snapshot()), 1)

        block1, _ = chain_a.build_block(timestamp=1)
        chain_b.apply_block(block1)
        self.assertEqual(chain_b.bundle_pool.snapshot(), [])


if __name__ == "__main__":
    unittest.main()
