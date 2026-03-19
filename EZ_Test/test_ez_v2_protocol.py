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
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    OffChainTx,
    PriorWitnessLink,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.validator import V2TransferValidator, ValidationContext
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


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

    def test_recursive_witness_validation_and_checkpoint_anchor(self) -> None:
        chain = ChainStateV2(chain_id=11)
        grace_priv, grace_pub = generate_secp256k1_keypair()
        alice_priv, alice_pub = generate_secp256k1_keypair()
        carol_priv, carol_pub = generate_secp256k1_keypair()
        grace_addr = address_from_public_key_pem(grace_pub)
        alice_addr = address_from_public_key_pem(alice_pub)
        carol_addr = address_from_public_key_pem(carol_pub)

        tx_g1 = OffChainTx(
            sender_addr=grace_addr,
            recipient_addr=alice_addr,
            value_list=(ValueRange(2700, 2749),),
            tx_local_index=0,
            tx_time=1,
        )
        sub_g1 = self._make_submission(grace_priv, grace_pub, 11, 1, 10, 1, 1, [tx_g1])
        chain.submit_bundle(sub_g1)
        _, receipts_g1 = chain.build_block(timestamp=1)
        unit_g1 = ConfirmedBundleUnit(receipt=receipts_g1[grace_addr], bundle_sidecar=sub_g1.sidecar)

        witness_g_to_a = WitnessV2(
            value=ValueRange(2700, 2749),
            current_owner_addr=grace_addr,
            confirmed_bundle_chain=(unit_g1,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x11" * 32,
                first_owner_addr=grace_addr,
                value_begin=2700,
                value_end=2999,
            ),
        )

        tx_a1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=carol_addr,
            value_list=(ValueRange(2700, 2749),),
            tx_local_index=0,
            tx_time=2,
        )
        sub_a1 = self._make_submission(alice_priv, alice_pub, 11, 1, 20, 1, 2, [tx_a1])
        chain.submit_bundle(sub_a1)
        _, receipts_a1 = chain.build_block(timestamp=2)
        unit_a1 = ConfirmedBundleUnit(receipt=receipts_a1[alice_addr], bundle_sidecar=sub_a1.sidecar)

        witness_a_to_c = WitnessV2(
            value=ValueRange(2700, 2749),
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(unit_a1,),
            anchor=PriorWitnessLink(acquire_tx=tx_g1, prior_witness=witness_g_to_a),
        )
        package = TransferPackage(target_tx=tx_a1, target_value=ValueRange(2700, 2749), witness_v2=witness_a_to_c)
        validator = V2TransferValidator(
            ValidationContext(
                genesis_allocations={grace_addr: (ValueRange(2700, 2999),)},
            )
        )
        result = validator.validate_transfer_package(package, recipient_addr=carol_addr)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.accepted_witness.current_owner_addr, carol_addr)

        checkpoint = Checkpoint(
            value_begin=1500,
            value_end=1599,
            owner_addr=alice_addr,
            checkpoint_height=2,
            checkpoint_block_hash=b"\x22" * 32,
            checkpoint_bundle_hash=b"\x33" * 32,
        )
        witness_with_checkpoint = WitnessV2(
            value=ValueRange(1500, 1599),
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(unit_a1,),
            anchor=CheckpointAnchor(checkpoint=checkpoint),
        )
        checkpoint_validator = V2TransferValidator(
            ValidationContext(
                trusted_checkpoints=(checkpoint,),
                genesis_allocations={grace_addr: (ValueRange(2700, 2999),)},
            )
        )
        checkpoint_package = TransferPackage(
            target_tx=tx_a1,
            target_value=ValueRange(2700, 2749),
            witness_v2=witness_a_to_c,
        )
        self.assertTrue(checkpoint_validator.validate_transfer_package(checkpoint_package, recipient_addr=carol_addr).ok)
        self.assertIsInstance(witness_with_checkpoint.anchor, CheckpointAnchor)

    def test_wallet_acquisition_boundary_updates(self) -> None:
        alice_priv, alice_pub = generate_secp256k1_keypair()
        alice_addr = address_from_public_key_pem(alice_pub)
        bob_priv, bob_pub = generate_secp256k1_keypair()
        bob_addr = address_from_public_key_pem(bob_pub)

        chain = ChainStateV2(chain_id=21)
        wallet = WalletAccountV2(address=alice_addr, genesis_block_hash=b"\x44" * 32)
        genesis_record = wallet.add_genesis_value(ValueRange(300, 599))

        tx_a1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(0, 99),),
            tx_local_index=0,
            tx_time=1,
        )
        sub_a1 = self._make_submission(alice_priv, alice_pub, 21, 1, 10, 1, 1, [tx_a1])
        chain.submit_bundle(sub_a1)
        _, receipts_a1 = chain.build_block(timestamp=1)
        unit_a1 = ConfirmedBundleUnit(receipt=receipts_a1[alice_addr], bundle_sidecar=sub_a1.sidecar)
        wallet.apply_sender_confirmed_unit(unit_a1)

        tx_b1 = OffChainTx(
            sender_addr=bob_addr,
            recipient_addr=alice_addr,
            value_list=(ValueRange(2700, 2749),),
            tx_local_index=0,
            tx_time=1,
        )
        sub_b1 = self._make_submission(bob_priv, bob_pub, 21, 1, 10, 1, 7, [tx_b1])
        chain.submit_bundle(sub_b1)
        _, receipts_b1 = chain.build_block(timestamp=1_1)
        unit_b1 = ConfirmedBundleUnit(receipt=receipts_b1[bob_addr], bundle_sidecar=sub_b1.sidecar)
        prior_witness = WitnessV2(
            value=ValueRange(2700, 2749),
            current_owner_addr=bob_addr,
            confirmed_bundle_chain=(unit_b1,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x44" * 32,
                first_owner_addr=bob_addr,
                value_begin=2700,
                value_end=2999,
            ),
        )
        incoming_record = wallet.receive_transfer(
            TransferPackage(
                target_tx=tx_b1,
                target_value=ValueRange(2700, 2749),
                witness_v2=prior_witness,
            ),
            validator=V2TransferValidator(
                ValidationContext(
                    genesis_allocations={
                        bob_addr: (ValueRange(2700, 2999),),
                    }
                )
            ),
        )

        tx_a2_0 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(2700, 2749),),
            tx_local_index=0,
            tx_time=2,
        )
        tx_a2_1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=bob_addr,
            value_list=(ValueRange(300, 349),),
            tx_local_index=1,
            tx_time=2,
        )
        sub_a2 = self._make_submission(alice_priv, alice_pub, 21, 2, 20, 1, 2, [tx_a2_0, tx_a2_1])
        chain.submit_bundle(sub_a2)
        _, receipts_a2 = chain.build_block(timestamp=2)
        unit_a2 = ConfirmedBundleUnit(receipt=receipts_a2[alice_addr], bundle_sidecar=sub_a2.sidecar)
        updated = wallet.apply_sender_confirmed_unit(
            unit_a2,
            outgoing_values=(ValueRange(2700, 2749), ValueRange(300, 349)),
        )

        retained = next(item for item in updated if item.value == ValueRange(350, 599))
        archived_received = next(item for item in updated if item.value == ValueRange(2700, 2749))
        self.assertEqual(retained.local_status, LocalValueStatus.VERIFIED_SPENDABLE)
        self.assertEqual(archived_received.local_status, LocalValueStatus.ARCHIVED)
        retained_hashes = [unit.receipt.seq for unit in retained.witness_v2.confirmed_bundle_chain]
        archived_hashes = [unit.receipt.seq for unit in archived_received.witness_v2.confirmed_bundle_chain]
        self.assertEqual(retained_hashes, [2, 1])
        self.assertEqual(archived_hashes, [2])
        self.assertEqual(genesis_record.acquisition_height, 0)
        self.assertEqual(incoming_record.acquisition_height, 2)


if __name__ == "__main__":
    unittest.main()
