from __future__ import annotations

import sqlite3
import tempfile
import unittest

from EZ_V2.claim_set import claim_range_set_from_sidecar, claim_range_set_hash
from EZ_V2.chain import ChainStateV2, compute_bundle_hash, sign_bundle_envelope
from EZ_V2.consensus_store import ConsensusStateStore
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.localnet import V2ConsensusNode
from EZ_V2.network_host import V2AccountHost, open_static_network
from EZ_V2.networking import (
    DEFAULT_V2_FEATURES,
    PeerInfo,
    peer_supports,
    with_v2_features,
)
from EZ_V2.smt import build_multiproof, materialize_proof, verify_multiproof, verify_proof
from EZ_V2.storage import LocalWalletDB
from EZ_V2.types import BundleEnvelope, BundleSidecar, BundleSubmission, OffChainTx
from EZ_V2.values import ValueRange


def _make_sidecar(sender_addr: str) -> BundleSidecar:
    return BundleSidecar(
        sender_addr=sender_addr,
        tx_list=(
            OffChainTx(
                sender_addr=sender_addr,
                recipient_addr="bob",
                value_list=(ValueRange(0, 9), ValueRange(10, 19), ValueRange(25, 29)),
                tx_local_index=0,
                tx_time=1,
            ),
            OffChainTx(
                sender_addr=sender_addr,
                recipient_addr="carol",
                value_list=(ValueRange(30, 39),),
                tx_local_index=1,
                tx_time=2,
            ),
        ),
    )


class EZV2P0ClaimSetTests(unittest.TestCase):
    def test_with_v2_features_preserves_metadata_and_enables_default_capabilities(self) -> None:
        peer = with_v2_features(
            PeerInfo(
                node_id="alice",
                role="account",
                endpoint="mem://alice",
                metadata={"address": "alice-addr"},
            )
        )

        self.assertEqual(peer.metadata["address"], "alice-addr")
        self.assertEqual(tuple(peer.metadata["v2_features"]), DEFAULT_V2_FEATURES)
        for feature in DEFAULT_V2_FEATURES:
            self.assertTrue(peer_supports(peer, feature))

    def test_claim_ranges_merge_adjacent_values_and_persist_with_sidecar(self) -> None:
        sender_addr = "alice"
        sidecar = _make_sidecar(sender_addr)
        claim_ranges = claim_range_set_from_sidecar(sidecar)

        self.assertEqual(claim_ranges.ranges, (ValueRange(0, 19), ValueRange(25, 39)))
        self.assertEqual(
            claim_range_set_hash(claim_ranges),
            claim_range_set_hash(claim_range_set_from_sidecar(sidecar)),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db = LocalWalletDB(f"{tmpdir}/wallet.sqlite3")
            try:
                bundle_hash = db.save_sidecar(sidecar)
                self.assertEqual(db.get_sidecar_claim_ranges(bundle_hash), claim_ranges)
            finally:
                db.close()

    def test_chain_binds_claim_set_hash_into_receipt_and_rejects_tampering(self) -> None:
        private_key_pem, public_key_pem = generate_secp256k1_keypair()
        sender_addr = address_from_public_key_pem(public_key_pem)
        sidecar = _make_sidecar(sender_addr)
        claim_set_hash = claim_range_set_hash(claim_range_set_from_sidecar(sidecar))
        chain = ChainStateV2(chain_id=771)

        envelope = BundleEnvelope(
            version=2,
            chain_id=771,
            seq=1,
            expiry_height=100,
            fee=0,
            anti_spam_nonce=7,
            bundle_hash=compute_bundle_hash(sidecar),
            claim_set_hash=claim_set_hash,
        )
        submission = BundleSubmission(
            envelope=sign_bundle_envelope(envelope, private_key_pem),
            sidecar=sidecar,
            sender_public_key_pem=public_key_pem,
        )

        chain.submit_bundle(submission)
        block, receipts = chain.build_block(timestamp=1)
        self.assertEqual(receipts[sender_addr].claim_set_hash, claim_set_hash)
        self.assertEqual(block.diff_package.diff_entries[0].new_leaf.claim_set_hash, claim_set_hash)

        bad_envelope = BundleEnvelope(
            version=2,
            chain_id=771,
            seq=1,
            expiry_height=100,
            fee=0,
            anti_spam_nonce=8,
            bundle_hash=compute_bundle_hash(sidecar),
            claim_set_hash=b"\x99" * 32,
        )
        bad_submission = BundleSubmission(
            envelope=sign_bundle_envelope(bad_envelope, private_key_pem),
            sidecar=sidecar,
            sender_public_key_pem=public_key_pem,
        )
        with self.assertRaisesRegex(ValueError, "claim_set_hash mismatch"):
            ChainStateV2(chain_id=771).submit_bundle(bad_submission)


class EZV2P0ReceiptBatchTests(unittest.TestCase):
    def test_multiproof_materializes_equivalent_single_proofs(self) -> None:
        from EZ_V2.smt import SparseMerkleTree

        tree = SparseMerkleTree(depth=8)
        key_a = b"\x01"
        key_b = b"\x09"
        value_a = b"\xaa" * 32
        value_b = b"\xbb" * 32
        tree.set(key_a, value_a)
        tree.set(key_b, value_b)

        multi_proof = build_multiproof(tree, [key_a, key_b])
        proof_a = materialize_proof(multi_proof, key_a)
        proof_b = materialize_proof(multi_proof, key_b)

        self.assertTrue(verify_proof(tree.root(), key_a, value_a, proof_a, depth=8))
        self.assertTrue(verify_proof(tree.root(), key_b, value_b, proof_b, depth=8))
        self.assertTrue(verify_multiproof(tree.root(), key_a, value_a, multi_proof))
        self.assertTrue(verify_multiproof(tree.root(), key_b, value_b, multi_proof))
        self.assertLess(len(multi_proof.nodes), len(proof_a.siblings) + len(proof_b.siblings))

    def test_block_announce_can_trigger_receipt_pull_with_proof_batch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=772)
            consensus.auto_dispatch_receipts = False
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=772,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=772,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                payment = alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=88)
                self.assertIsNone(payment.receipt_height)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)

                block = consensus.consensus.store.get_block_by_height(1)
                consensus._broadcast_block_announce(block)

                receipts = alice.wallet.list_receipts()
                self.assertEqual(len(receipts), 1)
                self.assertIsNotNone(receipts[0].account_state_proof)
                self.assertEqual(receipts[0].claim_set_hash, claim_range_set_hash(claim_range_set_from_sidecar(block.diff_package.sidecars[0])))
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertIsNotNone(
                    alice.wallet.db.get_receipt_proof_batch(f"1:{block.block_hash.hex()}")
                )
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_wallet_db_compacts_receipts_and_witnesses_to_batch_refs_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=773)
            consensus.auto_dispatch_receipts = False
            alice_db_path = f"{td}/alice.sqlite3"
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=alice_db_path,
                chain_id=773,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=773,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=89)
                block = consensus.consensus.store.get_block_by_height(1)
                consensus._broadcast_block_announce(block)

                conn = sqlite3.connect(alice_db_path)
                try:
                    receipt_json = conn.execute(
                        "SELECT receipt_json FROM receipts WHERE sender_addr = ? AND seq = 1",
                        (alice.address,),
                    ).fetchone()[0]
                    unit_json = conn.execute(
                        "SELECT unit_json FROM confirmed_units WHERE sender_addr = ? AND seq = 1",
                        (alice.address,),
                    ).fetchone()[0]
                    record_json = conn.execute(
                        "SELECT record_json FROM value_records WHERE owner_addr = ? ORDER BY record_id LIMIT 1",
                        (alice.address,),
                    ).fetchone()[0]
                finally:
                    conn.close()

                self.assertIn("proof_batch_ref", receipt_json)
                self.assertIn("\"account_state_proof\":null", receipt_json)
                self.assertIn("proof_batch_ref", unit_json)
                self.assertIn("proof_batch_ref", record_json)
                self.assertIsNotNone(alice.wallet.db.get_receipt(alice.address, 1).account_state_proof)
                self.assertIsNotNone(alice.wallet.db.get_confirmed_unit(alice.address, 1).receipt.account_state_proof)
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_receipt_request_falls_back_to_persisted_proof_batch_when_memory_cache_misses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network, consensus = open_static_network(td, chain_id=775)
            consensus.auto_dispatch_receipts = False
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=775,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=775,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                alice.submit_payment("bob", amount=40, tx_time=1, anti_spam_nonce=90)
                batch_id = f"1:{consensus.consensus.store.get_block_by_height(1).block_hash.hex()}"
                consensus.consensus.chain.receipt_cache._proof_batches.pop(batch_id, None)
                consensus.consensus.chain.receipt_cache._proof_batches_by_height.pop(1, None)

                self.assertEqual(alice.sync_pending_receipts(), 1)
                receipts = alice.wallet.list_receipts()
                self.assertEqual(len(receipts), 1)
                self.assertIsNotNone(receipts[0].account_state_proof)
                self.assertIsNotNone(alice.wallet.db.get_receipt_proof_batch(batch_id))
            finally:
                alice.close()
                bob.close()
                consensus.close()

    def test_consensus_store_persists_receipt_batch_refs_and_materializes_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            node = V2ConsensusNode(store_path=f"{td}/consensus.sqlite3", chain_id=774)
            try:
                private_key_pem, public_key_pem = generate_secp256k1_keypair()
                sender_addr = address_from_public_key_pem(public_key_pem)
                node.register_genesis_allocation(sender_addr, ValueRange(0, 99))

                sidecar = BundleSidecar(
                    sender_addr=sender_addr,
                    tx_list=(
                        OffChainTx(
                            sender_addr=sender_addr,
                            recipient_addr="bob",
                            value_list=(ValueRange(0, 49),),
                            tx_local_index=0,
                            tx_time=1,
                        ),
                    ),
                )
                envelope = sign_bundle_envelope(
                    BundleEnvelope(
                        version=2,
                        chain_id=774,
                        seq=1,
                        expiry_height=100,
                        fee=0,
                        anti_spam_nonce=9,
                        bundle_hash=compute_bundle_hash(sidecar),
                        claim_set_hash=claim_range_set_hash(claim_range_set_from_sidecar(sidecar)),
                    ),
                    private_key_pem,
                )
                node.submit_bundle(
                    BundleSubmission(
                        envelope=envelope,
                        sidecar=sidecar,
                        sender_public_key_pem=public_key_pem,
                    )
                )
                produced = node.produce_block(timestamp=1)
                receipt = produced.receipts[sender_addr]
                self.assertIsNotNone(receipt.account_state_proof)
            finally:
                node.close()

            raw_store = sqlite3.connect(f"{td}/consensus.sqlite3")
            try:
                stored_receipt_json = raw_store.execute(
                    "SELECT receipt_json FROM receipt_window_v2 WHERE sender_addr = ? AND seq = 1",
                    (sender_addr,),
                ).fetchone()[0]
                proof_batch_count = raw_store.execute(
                    "SELECT COUNT(*) FROM receipt_proof_batches_v2",
                ).fetchone()[0]
            finally:
                raw_store.close()

            self.assertIn("proof_batch_ref", stored_receipt_json)
            self.assertEqual(proof_batch_count, 1)

            store = ConsensusStateStore(f"{td}/consensus.sqlite3")
            try:
                recovered = store.get_receipt(sender_addr, 1).receipt
                self.assertIsNotNone(recovered)
                self.assertIsNotNone(recovered.account_state_proof)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
