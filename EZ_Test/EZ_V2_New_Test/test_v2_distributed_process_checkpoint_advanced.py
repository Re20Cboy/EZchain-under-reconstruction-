from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.runtime_v2 import V2Runtime
from EZ_V2.types import CheckpointAnchor, PriorWitnessLink, WitnessV2
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessCheckpointAdvancedTests(unittest.TestCase):
    def test_flow_multiple_exact_checkpoints_coexist_but_cannot_be_cross_applied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5401,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5401,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5401,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5401,
                network=network,
                consensus_peer_id="consensus-0",
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=5401,
                network=network,
                consensus_peer_id="consensus-0",
                auto_accept_receipts=False,
            )
            try:
                first_value = ValueRange(100, 149)
                second_value = ValueRange(150, 199)
                consensus.register_genesis_value(alice.address, first_value)
                consensus.register_genesis_value(alice.address, second_value)
                alice.register_genesis_value(first_value)
                alice.register_genesis_value(second_value)

                p1 = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=1001)
                p2 = bob.submit_payment("alice", amount=50, tx_time=2, anti_spam_nonce=1002)
                p3 = alice.submit_payment("dave", amount=50, tx_time=3, anti_spam_nonce=1003)
                q1 = alice.submit_payment("carol", amount=50, tx_time=4, anti_spam_nonce=1004)
                q2 = carol.submit_payment("alice", amount=50, tx_time=5, anti_spam_nonce=1005)
                q3 = alice.submit_payment("dave", amount=50, tx_time=6, anti_spam_nonce=1006)
                self.assertEqual([p1.receipt_height, p2.receipt_height, p3.receipt_height], [1, 2, 3])
                self.assertEqual([q1.receipt_height, q2.receipt_height, q3.receipt_height], [4, 5, 6])

                archived = [
                    record
                    for record in alice.wallet.list_records()
                    if record.local_status == LocalValueStatus.ARCHIVED
                ]
                cp_record_1 = next(record for record in archived if record.value == first_value)
                cp_record_2 = next(record for record in archived if record.value == second_value)
                checkpoint_1 = alice.wallet.create_exact_checkpoint(cp_record_1.record_id)
                checkpoint_2 = alice.wallet.create_exact_checkpoint(cp_record_2.record_id)
                self.assertEqual(
                    {(cp.value_begin, cp.value_end) for cp in alice.wallet.list_checkpoints()},
                    {(100, 149), (150, 199)},
                )

                target_record = max(
                    (
                        record
                        for record in archived
                        if record.value == first_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                target_tx = target_record.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                package = alice.wallet.export_transfer_package(target_tx, first_value)
                checkpointed_package = replace(
                    package,
                    witness_v2=replace(
                        package.witness_v2,
                        anchor=CheckpointAnchor(checkpoint=checkpoint_1),
                    ),
                )
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                with self.assertRaisesRegex(ValueError, "checkpoint anchor is not trusted"):
                    offline_dave.receive_transfer(
                        checkpointed_package,
                        validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint_2,)),
                    )
                accepted = offline_dave.receive_transfer(
                    checkpointed_package,
                    validator=trusted_runtime.build_validator(trusted_checkpoints=(checkpoint_1, checkpoint_2)),
                )
                self.assertEqual(accepted.value, first_value)
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_old_full_range_checkpoint_cannot_shortcut_later_subrange_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5402,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5402,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5402,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5402,
                network=network,
                consensus_peer_id="consensus-0",
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=5402,
                network=network,
                consensus_peer_id="consensus-0",
                auto_accept_receipts=False,
            )
            try:
                full_value = ValueRange(1000, 1099)
                sub_value = ValueRange(1000, 1049)
                consensus.register_genesis_value(alice.address, full_value)
                alice.register_genesis_value(full_value)

                a1 = alice.submit_payment("bob", amount=100, tx_time=1, anti_spam_nonce=1101)
                b1 = bob.submit_payment("alice", amount=100, tx_time=2, anti_spam_nonce=1102)
                a2 = alice.submit_payment("carol", amount=100, tx_time=3, anti_spam_nonce=1103)
                self.assertEqual([a1.receipt_height, b1.receipt_height, a2.receipt_height], [1, 2, 3])

                full_archived = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == full_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                full_checkpoint = alice.wallet.create_exact_checkpoint(full_archived.record_id)

                c1 = carol.submit_payment("alice", amount=50, tx_time=4, anti_spam_nonce=1104)
                self.assertEqual(c1.receipt_height, 4)
                a3 = alice.submit_payment("dave", amount=50, tx_time=5, anti_spam_nonce=1105)
                self.assertEqual(a3.receipt_height, 5)

                sub_archived = max(
                    (
                        record
                        for record in alice.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == sub_value
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                sub_tx = sub_archived.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                sub_package = alice.wallet.export_transfer_package(sub_tx, sub_value)
                forged_shortcut_package = replace(
                    sub_package,
                    witness_v2=replace(
                        sub_package.witness_v2,
                        anchor=PriorWitnessLink(
                            acquire_tx=sub_package.witness_v2.anchor.acquire_tx,
                            prior_witness=WitnessV2(
                                value=sub_value,
                                current_owner_addr=carol.address,
                                confirmed_bundle_chain=sub_archived.witness_v2.anchor.prior_witness.confirmed_bundle_chain,
                                anchor=CheckpointAnchor(checkpoint=full_checkpoint),
                            ),
                        ),
                    ),
                )
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )
                trusted_runtime = V2Runtime()
                with self.assertRaisesRegex(ValueError, "checkpoint anchor is not trusted"):
                    offline_dave.receive_transfer(
                        forged_shortcut_package,
                        validator=trusted_runtime.build_validator(trusted_checkpoints=(full_checkpoint,)),
                    )
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()


if __name__ == "__main__":
    unittest.main()
