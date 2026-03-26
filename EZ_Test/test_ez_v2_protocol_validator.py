from __future__ import annotations

from dataclasses import replace
import unittest

from EZ_V2.chain import ChainStateV2, compute_bundle_hash, sign_bundle_envelope
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.types import (
    BundleEnvelope,
    BundleSidecar,
    BundleSubmission,
    ConfirmedBundleUnit,
    GenesisAnchor,
    OffChainTx,
    PriorWitnessLink,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.validator import V2TransferValidator, ValidationContext
from EZ_V2.values import ValueRange


class EZV2ProtocolValidatorTests(unittest.TestCase):
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

    def test_validator_rejects_tampered_state_proof(self) -> None:
        chain = ChainStateV2(chain_id=31)
        grace_priv, grace_pub = generate_secp256k1_keypair()
        alice_priv, alice_pub = generate_secp256k1_keypair()
        _, carol_pub = generate_secp256k1_keypair()
        grace_addr = address_from_public_key_pem(grace_pub)
        alice_addr = address_from_public_key_pem(alice_pub)
        carol_addr = address_from_public_key_pem(carol_pub)

        tx_g1 = OffChainTx(
            sender_addr=grace_addr,
            recipient_addr=alice_addr,
            value_list=(ValueRange(5000, 5049),),
            tx_local_index=0,
            tx_time=1,
        )
        sub_g1 = self._make_submission(grace_priv, grace_pub, 31, 1, 10, 1, 1, [tx_g1])
        chain.submit_bundle(sub_g1)
        _, receipts_g1 = chain.build_block(timestamp=1)
        unit_g1 = ConfirmedBundleUnit(receipt=receipts_g1[grace_addr], bundle_sidecar=sub_g1.sidecar)

        tx_a1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=carol_addr,
            value_list=(ValueRange(5000, 5049),),
            tx_local_index=0,
            tx_time=2,
        )
        sub_a1 = self._make_submission(alice_priv, alice_pub, 31, 1, 20, 1, 2, [tx_a1])
        chain.submit_bundle(sub_a1)
        _, receipts_a1 = chain.build_block(timestamp=2)
        unit_a1 = ConfirmedBundleUnit(receipt=receipts_a1[alice_addr], bundle_sidecar=sub_a1.sidecar)

        tampered_receipt = replace(
            unit_a1.receipt,
            account_state_proof=replace(
                unit_a1.receipt.account_state_proof,
                siblings=tuple(reversed(unit_a1.receipt.account_state_proof.siblings)),
            ),
        )
        tampered_unit = ConfirmedBundleUnit(receipt=tampered_receipt, bundle_sidecar=unit_a1.bundle_sidecar)
        package = TransferPackage(
            target_tx=tx_a1,
            target_value=ValueRange(5000, 5049),
            witness_v2=WitnessV2(
                value=ValueRange(5000, 5049),
                current_owner_addr=alice_addr,
                confirmed_bundle_chain=(tampered_unit,),
                anchor=PriorWitnessLink(
                    acquire_tx=tx_g1,
                    prior_witness=WitnessV2(
                        value=ValueRange(5000, 5049),
                        current_owner_addr=grace_addr,
                        confirmed_bundle_chain=(unit_g1,),
                        anchor=GenesisAnchor(
                            genesis_block_hash=b"\x55" * 32,
                            first_owner_addr=grace_addr,
                            value_begin=5000,
                            value_end=5099,
                        ),
                    ),
                ),
            ),
        )
        validator = V2TransferValidator(
            ValidationContext(genesis_allocations={grace_addr: (ValueRange(5000, 5099),)})
        )
        result = validator.validate_transfer_package(package, recipient_addr=carol_addr)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "account state proof does not verify")

    def test_validator_rejects_missing_prior_witness_chain(self) -> None:
        alice_priv, alice_pub = generate_secp256k1_keypair()
        alice_addr = address_from_public_key_pem(alice_pub)
        _, carol_pub = generate_secp256k1_keypair()
        carol_addr = address_from_public_key_pem(carol_pub)

        tx_a1 = OffChainTx(
            sender_addr=alice_addr,
            recipient_addr=carol_addr,
            value_list=(ValueRange(7000, 7049),),
            tx_local_index=0,
            tx_time=2,
        )
        package = TransferPackage(
            target_tx=tx_a1,
            target_value=ValueRange(7000, 7049),
            witness_v2=WitnessV2(
                value=ValueRange(7000, 7049),
                current_owner_addr=alice_addr,
                confirmed_bundle_chain=(),
                anchor=PriorWitnessLink(
                    acquire_tx=tx_a1,
                    prior_witness=WitnessV2(
                        value=ValueRange(7000, 7049),
                        current_owner_addr=alice_addr,
                        confirmed_bundle_chain=(),
                        anchor=GenesisAnchor(
                            genesis_block_hash=b"\x66" * 32,
                            first_owner_addr=alice_addr,
                            value_begin=7000,
                            value_end=7099,
                        ),
                    ),
                ),
            ),
        )
        validator = V2TransferValidator(
            ValidationContext(genesis_allocations={alice_addr: (ValueRange(7000, 7099),)})
        )
        result = validator.validate_transfer_package(package, recipient_addr=carol_addr)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "current sender witness segment cannot be empty")


if __name__ == "__main__":
    unittest.main()
