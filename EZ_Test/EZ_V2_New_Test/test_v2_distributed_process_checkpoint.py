from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.networking import MSG_TRANSFER_PACKAGE_DELIVER, NetworkEnvelope
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.types import CheckpointAnchor, PriorWitnessLink, TransferPackage, WitnessV2
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class RecordingStaticPeerNetwork(StaticPeerNetwork):
    def __init__(self):
        super().__init__()
        self.sent_envelopes: list[NetworkEnvelope] = []

    def send(self, envelope: NetworkEnvelope) -> dict[str, object] | None:
        self.sent_envelopes.append(envelope)
        return super().send(envelope)


class EZV2DistributedProcessCheckpointTests(unittest.TestCase):
    @staticmethod
    def _witness_contains_checkpoint_anchor(witness: WitnessV2) -> bool:
        anchor = witness.anchor
        if isinstance(anchor, CheckpointAnchor):
            return True
        if isinstance(anchor, PriorWitnessLink):
            return EZV2DistributedProcessCheckpointTests._witness_contains_checkpoint_anchor(anchor.prior_witness)
        return False

    def _build_return_loop_with_checkpoint(self, td: str):
        network = StaticPeerNetwork()
        consensus = V2ConsensusHost(
            node_id="consensus-0",
            endpoint="mem://consensus-0",
            store_path=f"{td}/consensus.sqlite3",
            network=network,
            chain_id=5301,
        )
        alice = V2AccountHost(
            node_id="alice",
            endpoint="mem://alice",
            wallet_db_path=f"{td}/alice.sqlite3",
            chain_id=5301,
            network=network,
            consensus_peer_id="consensus-0",
        )
        bob = V2AccountHost(
            node_id="bob",
            endpoint="mem://bob",
            wallet_db_path=f"{td}/bob.sqlite3",
            chain_id=5301,
            network=network,
            consensus_peer_id="consensus-0",
        )
        carol = V2AccountHost(
            node_id="carol",
            endpoint="mem://carol",
            wallet_db_path=f"{td}/carol.sqlite3",
            chain_id=5301,
            network=network,
            consensus_peer_id="consensus-0",
        )
        dave = V2AccountHost(
            node_id="dave",
            endpoint="mem://dave",
            wallet_db_path=f"{td}/dave.sqlite3",
            chain_id=5301,
            network=network,
            consensus_peer_id="consensus-0",
            auto_accept_receipts=False,
        )

        exact_value = ValueRange(1500, 1599)
        consensus.register_genesis_value(alice.address, exact_value)
        alice.register_genesis_value(exact_value)

        first = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=901)
        second = bob.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=902)
        third = alice.submit_payment("carol", amount=100, tx_time=3, anti_spam_nonce=903)
        fourth = carol.submit_payment("dave", amount=100, tx_time=4, anti_spam_nonce=904)

        assert first.receipt_height == 1
        assert second.receipt_height == 2
        assert third.receipt_height == 3
        assert fourth.receipt_height == 4

        alice_archived = max(
            (
                record
                for record in alice.wallet.list_records()
                if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
            ),
            key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
        )
        checkpoint = alice.wallet.create_exact_checkpoint(alice_archived.record_id)
        checkpointed_alice_witness = WitnessV2(
            value=exact_value,
            current_owner_addr=alice.address,
            confirmed_bundle_chain=alice_archived.witness_v2.confirmed_bundle_chain,
            anchor=CheckpointAnchor(checkpoint=checkpoint),
        )

        carol_archived = next(
            record
            for record in carol.wallet.list_records()
            if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
        )
        downstream_tx = carol_archived.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
        downstream_package = carol.wallet.export_transfer_package(downstream_tx, exact_value)
        checkpointed_downstream_package = replace(
            downstream_package,
            witness_v2=replace(
                downstream_package.witness_v2,
                anchor=PriorWitnessLink(
                    acquire_tx=downstream_package.witness_v2.anchor.acquire_tx,
                    prior_witness=checkpointed_alice_witness,
                ),
            ),
        )
        return consensus, alice, bob, carol, dave, checkpoint, checkpointed_downstream_package, alice_archived

    def test_flow_checkpoint_exact_return_can_crop_history_for_downstream_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            consensus, alice, bob, carol, dave, checkpoint, package, _ = self._build_return_loop_with_checkpoint(td)
            try:
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                accepted = offline_dave.receive_transfer(
                    package,
                    validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint,)),
                )
                self.assertEqual(accepted.value, ValueRange(1500, 1599))
                self.assertEqual(accepted.witness_v2.current_owner_addr, dave.address)
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_split_value_falls_back_to_full_witness_when_exact_checkpoint_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5303,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
                auto_accept_receipts=False,
            )
            try:
                exact_value = ValueRange(1500, 1599)
                partial_value = ValueRange(1500, 1549)
                consensus.register_genesis_value(alice.address, exact_value)
                alice.register_genesis_value(exact_value)

                first = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=921)
                second = bob.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=922)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)

                archived_exact = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                checkpoint = alice.wallet.create_exact_checkpoint(archived_exact.record_id)
                self.assertEqual(alice.wallet.list_checkpoints(), [checkpoint])

                third = alice.submit_payment("carol", amount=50, tx_time=3, anti_spam_nonce=923)
                fourth = carol.submit_payment("dave", amount=50, tx_time=4, anti_spam_nonce=924)
                self.assertEqual(third.receipt_height, 3)
                self.assertEqual(fourth.receipt_height, 4)

                archived_partial = next(
                    record
                    for record in carol.wallet.list_records()
                    if record.local_status == LocalValueStatus.ARCHIVED and record.value == partial_value
                )
                target_tx = archived_partial.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                package = carol.wallet.export_transfer_package(target_tx, partial_value)
                self.assertFalse(self._witness_contains_checkpoint_anchor(package.witness_v2))

                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                accepted = offline_dave.receive_transfer(
                    package,
                    validator=dave._build_validator_for_package(package),
                )
                self.assertEqual(accepted.value, partial_value)
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_checkpoint_partial_overlap_cannot_reuse_exact_range_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            consensus, alice, bob, carol, dave, checkpoint, package, _ = self._build_return_loop_with_checkpoint(td)
            try:
                partial_package = replace(package, target_value=ValueRange(1500, 1549))
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                with self.assertRaisesRegex(ValueError, "checkpoint anchor is not trusted"):
                    offline_dave.receive_transfer(
                        partial_package,
                        validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint,)),
                    )
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_checkpoint_does_not_skip_post_checkpoint_sender_history_checks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            consensus, alice, bob, carol, dave, checkpoint, package, alice_archived = self._build_return_loop_with_checkpoint(td)
            try:
                forged_prior_witness = replace(
                    package.witness_v2.anchor.prior_witness,
                    confirmed_bundle_chain=(
                        alice_archived.witness_v2.confirmed_bundle_chain[0],
                        alice.wallet.db.get_confirmed_unit(alice.address, 1),
                    ),
                    anchor=CheckpointAnchor(checkpoint=checkpoint),
                )
                forged_package = replace(
                    package,
                    witness_v2=replace(
                        package.witness_v2,
                        anchor=PriorWitnessLink(
                            acquire_tx=package.witness_v2.anchor.acquire_tx,
                            prior_witness=forged_prior_witness,
                        ),
                    ),
                )
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                with self.assertRaisesRegex(ValueError, "value conflict detected inside current sender history"):
                    offline_dave.receive_transfer(
                        forged_package,
                        validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint,)),
                    )
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_delivery_to_old_owner_uses_local_checkpoint_trim_without_extra_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = RecordingStaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5302,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5302,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                exact_value = ValueRange(1500, 1599)
                consensus.register_genesis_value(alice.address, exact_value)
                alice.register_genesis_value(exact_value)

                first = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=911)
                second = bob.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=912)
                third = alice.submit_payment("carol", amount=100, tx_time=3, anti_spam_nonce=913)
                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(third.receipt_height, 3)

                archived_record = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                checkpoint = alice.wallet.create_exact_checkpoint(archived_record.record_id)
                network.sent_envelopes.clear()

                fourth = carol.submit_payment("alice", amount=100, tx_time=4, anti_spam_nonce=914)
                self.assertEqual(fourth.receipt_height, 4)
                self.assertEqual(alice.wallet.available_balance(), 100)

                delivered = [
                    envelope
                    for envelope in network.sent_envelopes
                    if envelope.msg_type == MSG_TRANSFER_PACKAGE_DELIVER
                    and envelope.sender_id == "carol"
                    and envelope.recipient_id == "alice"
                ]
                self.assertEqual(len(delivered), 1)
                delivered_package = delivered[0].payload["package"]
                self.assertIsInstance(delivered_package.witness_v2.anchor, PriorWitnessLink)
                prior_witness = delivered_package.witness_v2.anchor.prior_witness
                self.assertIsInstance(prior_witness.anchor, CheckpointAnchor)
                self.assertEqual(prior_witness.anchor.checkpoint, checkpoint)
            finally:
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_first_hop_delivery_keeps_full_anchor_when_recipient_never_owned_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = RecordingStaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5303,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5303,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                exact_value = ValueRange(1600, 1699)
                consensus.register_genesis_value(alice.address, exact_value)
                alice.register_genesis_value(exact_value)
                network.sent_envelopes.clear()

                payment = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=921)
                self.assertEqual(payment.receipt_height, 1)

                delivered = [
                    envelope
                    for envelope in network.sent_envelopes
                    if envelope.msg_type == MSG_TRANSFER_PACKAGE_DELIVER
                    and envelope.sender_id == "alice"
                    and envelope.recipient_id == "bob"
                ]
                self.assertEqual(len(delivered), 1)
                self.assertNotIsInstance(delivered[0].payload["package"].witness_v2.anchor, CheckpointAnchor)
            finally:
                bob.close()
                alice.close()
                consensus.close()


if __name__ == "__main__":
    unittest.main()
