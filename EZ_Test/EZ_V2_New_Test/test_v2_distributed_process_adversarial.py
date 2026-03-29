from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.crypto import keccak256
from EZ_V2.encoding import canonical_encode
from EZ_V2.networking import (
    MSG_BLOCK_ANNOUNCE,
    MSG_BUNDLE_SUBMIT,
    MSG_CONSENSUS_BUNDLE_FORWARD,
    MSG_CONSENSUS_FINALIZE,
    MSG_RECEIPT_DELIVER,
    NetworkEnvelope,
)
from EZ_V2.types import ConfirmedBundleUnit, OffChainTx
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import WalletAccountV2


class EZV2DistributedProcessAdversarialTests(unittest.TestCase):
    def test_flow_mvp_timeout_advances_round_and_next_proposer_can_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=5201,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5201,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5201,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                timeout_result = consensus_hosts["consensus-0"].run_mvp_timeout_round(consensus_peer_ids=validator_ids)
                self.assertEqual(timeout_result["status"], "timed_out")
                self.assertEqual(timeout_result["next_round"], 2)
                for consensus in consensus_hosts.values():
                    snapshot = consensus.consensus_runtime_snapshot()
                    self.assertEqual(snapshot.current_round, 2)
                    self.assertEqual(snapshot.highest_tc_round, 1)

                alice.set_consensus_peer_ids(("consensus-1", "consensus-0", "consensus-2", "consensus-3"))
                bob.set_consensus_peer_ids(("consensus-1", "consensus-0", "consensus-2", "consensus-3"))
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=801)
                self.assertIsNone(payment.receipt_height)
                round_result = consensus_hosts["consensus-1"].run_mvp_consensus_round(
                    consensus_peer_ids=("consensus-1", "consensus-0", "consensus-2", "consensus-3")
                )
                self.assertEqual(round_result["status"], "committed")
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                for consensus in consensus_hosts.values():
                    self.assertEqual(consensus.consensus.chain.current_height, 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_flow_forward_bundle_rejects_invalid_ordered_consensus_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=5202,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5202,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5202,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                submission, context, _ = alice.wallet.build_payment_bundle(
                    recipient_addr=bob.address,
                    amount=50,
                    private_key_pem=alice.private_key_pem,
                    public_key_pem=alice.public_key_pem,
                    chain_id=5202,
                    expiry_height=100,
                    anti_spam_nonce=802,
                    tx_time=1,
                )
                response = network.send(
                    NetworkEnvelope(
                        msg_type=MSG_CONSENSUS_BUNDLE_FORWARD,
                        sender_id="consensus-0",
                        recipient_id="consensus-1",
                        payload={
                            "submission": submission,
                            "sender_peer_id": alice.peer.node_id,
                            "ordered_consensus_peer_ids": ("consensus-0", "consensus-1", "consensus-2", "consensus-3"),
                            "auto_commit": False,
                        },
                    )
                )
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "invalid_ordered_consensus_peer_ids")
                alice.wallet.rollback_pending_bundle(context.seq)
            finally:
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_flow_recipient_rejects_prev_ref_discontinuity_and_value_conflict_in_witness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5203,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5203,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5203,
                network=network,
                consensus_peer_id="consensus-0",
            )
            carol = V2AccountHost(
                node_id="carol",
                endpoint="mem://carol",
                wallet_db_path=f"{td}/carol.sqlite3",
                chain_id=5203,
                network=network,
                consensus_peer_id="consensus-0",
            )
            dave = V2AccountHost(
                node_id="dave",
                endpoint="mem://dave",
                wallet_db_path=f"{td}/dave.sqlite3",
                chain_id=5203,
                network=network,
                consensus_peer_id="consensus-0",
                auto_accept_receipts=False,
            )
            try:
                minted = ValueRange(0, 199)
                consensus.register_genesis_value(bob.address, minted)
                bob.register_genesis_value(minted)

                first = bob.submit_payment("carol", amount=20, tx_time=1, anti_spam_nonce=803)
                self.assertEqual(first.receipt_height, 1)
                second = carol.submit_payment("bob", amount=20, tx_time=2, anti_spam_nonce=804)
                self.assertEqual(second.receipt_height, 2)
                third = bob.submit_payment("dave", amount=20, tx_time=3, anti_spam_nonce=805)
                self.assertEqual(third.receipt_height, 3)

                archived_record = max(
                    (
                        record
                        for record in bob.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == ValueRange(0, 19)
                    ),
                    key=lambda record: record.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                unit = archived_record.witness_v2.confirmed_bundle_chain[0]
                target_tx = unit.bundle_sidecar.tx_list[0]
                package = bob.wallet.export_transfer_package(target_tx, archived_record.value)
                offline_dave = WalletAccountV2(
                    address=dave.address,
                    genesis_block_hash=b"\x00" * 32,
                    db_path=f"{td}/offline-dave.sqlite3",
                )

                discontinuous_package = replace(
                    package,
                    witness_v2=replace(
                        package.witness_v2,
                        confirmed_bundle_chain=(unit, unit),
                    ),
                )
                with self.assertRaisesRegex(ValueError, "prev_ref chain is discontinuous"):
                    offline_dave.receive_transfer(
                        discontinuous_package,
                        validator=dave._build_validator_for_package(discontinuous_package),
                    )

                previous_bob_unit = bob.wallet.db.get_confirmed_unit(bob.address, 1)
                assert previous_bob_unit is not None
                conflicting_package = replace(
                    package,
                    witness_v2=replace(
                        package.witness_v2,
                        confirmed_bundle_chain=(unit, previous_bob_unit),
                    ),
                )
                with self.assertRaisesRegex(ValueError, "value conflict detected inside current sender history"):
                    offline_dave.receive_transfer(
                        conflicting_package,
                        validator=dave._build_validator_for_package(conflicting_package),
                    )
                offline_dave.close()
            finally:
                dave.close()
                carol.close()
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_receipt_delivery_survives_missing_recipient_handler(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5204,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5204,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5204,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 99)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                missing_recipient = "0x" + "99" * 20
                submission, _ = alice.wallet.build_bundle(
                    tx_list=(
                        OffChainTx(
                            sender_addr=alice.address,
                            recipient_addr=missing_recipient,
                            value_list=(ValueRange(0, 49),),
                            tx_local_index=0,
                            tx_time=1,
                        ),
                        OffChainTx(
                            sender_addr=alice.address,
                            recipient_addr=bob.address,
                            value_list=(ValueRange(50, 99),),
                            tx_local_index=1,
                            tx_time=1,
                        ),
                    ),
                    private_key_pem=alice.private_key_pem,
                    public_key_pem=alice.public_key_pem,
                    chain_id=5204,
                    seq=1,
                    expiry_height=100,
                    fee=0,
                    anti_spam_nonce=806,
                    created_at=1,
                )

                response = network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-0",
                        payload={"submission": submission},
                    )
                )

                self.assertIsInstance(response, dict)
                assert isinstance(response, dict)
                self.assertTrue(response.get("ok", False))
                self.assertEqual(response.get("status"), "accepted")
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(bob.received_transfers), 1)
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_block_announce_rejects_same_height_conflicting_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=5205,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5205,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5205,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 99)
                consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=807)
                self.assertEqual(payment.receipt_height, 1)

                response = consensus.handle_envelope(
                    NetworkEnvelope(
                        msg_type=MSG_BLOCK_ANNOUNCE,
                        sender_id="consensus-1",
                        recipient_id="consensus-0",
                        payload={
                            "height": 1,
                            "block_hash": ("ab" * 32),
                        },
                    )
                )

                self.assertEqual(response["ok"], False)
                self.assertEqual(response["error"], "announced_block_hash_conflict")
            finally:
                bob.close()
                alice.close()
                consensus.close()

    def test_flow_mvp_commit_survives_partial_receipt_announce_and_finalize_failures(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2")
            consensus_hosts = {
                validator_id: V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=5206,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                )
                for validator_id in validator_ids
            }
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=5206,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=5206,
                network=network,
                consensus_peer_id="consensus-0",
            )
            original_send = network.send
            drops = {"announce": 0, "receipt": 0, "finalize": 0}

            def flaky_send(envelope: NetworkEnvelope):
                if (
                    envelope.msg_type == MSG_BLOCK_ANNOUNCE
                    and envelope.sender_id == "consensus-0"
                    and envelope.recipient_id == "consensus-1"
                    and drops["announce"] == 0
                ):
                    drops["announce"] += 1
                    raise ValueError("simulated_block_announce_drop")
                if (
                    envelope.msg_type == MSG_RECEIPT_DELIVER
                    and envelope.sender_id == "consensus-0"
                    and envelope.recipient_id == "alice"
                    and drops["receipt"] == 0
                ):
                    drops["receipt"] += 1
                    raise ValueError("simulated_receipt_drop")
                if (
                    envelope.msg_type == MSG_CONSENSUS_FINALIZE
                    and envelope.sender_id == "consensus-0"
                    and envelope.recipient_id == "consensus-1"
                    and drops["finalize"] == 0
                ):
                    drops["finalize"] += 1
                    raise ValueError("simulated_finalize_drop")
                return original_send(envelope)

            network.send = flaky_send
            try:
                minted = ValueRange(0, 99)
                for consensus in consensus_hosts.values():
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                missing_recipient = "0x" + "88" * 20
                submission, _ = alice.wallet.build_bundle(
                    tx_list=(
                        OffChainTx(
                            sender_addr=alice.address,
                            recipient_addr=missing_recipient,
                            value_list=(ValueRange(0, 49),),
                            tx_local_index=0,
                            tx_time=1,
                        ),
                        OffChainTx(
                            sender_addr=alice.address,
                            recipient_addr=bob.address,
                            value_list=(ValueRange(50, 99),),
                            tx_local_index=1,
                            tx_time=1,
                        ),
                    ),
                    private_key_pem=alice.private_key_pem,
                    public_key_pem=alice.public_key_pem,
                    chain_id=5206,
                    seq=1,
                    expiry_height=100,
                    fee=0,
                    anti_spam_nonce=808,
                    created_at=1,
                )

                response = network.send(
                    NetworkEnvelope(
                        msg_type=MSG_BUNDLE_SUBMIT,
                        sender_id="alice",
                        recipient_id="consensus-0",
                        payload={"submission": submission},
                    )
                )
                self.assertIsInstance(response, dict)
                assert isinstance(response, dict)
                self.assertTrue(response.get("ok", False))
                self.assertEqual(response.get("status"), "accepted_pending_consensus")

                round_result = consensus_hosts["consensus-0"].run_mvp_consensus_round(consensus_peer_ids=validator_ids)
                self.assertEqual(round_result["status"], "committed")
                self.assertEqual(consensus_hosts["consensus-0"].consensus.chain.current_height, 1)
                self.assertEqual(consensus_hosts["consensus-1"].consensus.chain.current_height, 0)
                self.assertEqual(consensus_hosts["consensus-2"].consensus.chain.current_height, 1)

                self.assertEqual(len(alice.wallet.list_pending_bundles()), 1)
                self.assertEqual(len(alice.wallet.list_receipts()), 0)
                self.assertEqual(bob.wallet.available_balance(), 0)
                self.assertEqual(len(bob.received_transfers), 0)

                applied_receipts = alice.sync_pending_receipts()
                self.assertEqual(applied_receipts, 1)
                self.assertEqual(len(alice.wallet.list_pending_bundles()), 0)
                self.assertEqual(len(alice.wallet.list_receipts()), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)
                self.assertEqual(len(bob.received_transfers), 1)

                recovered_heights = consensus_hosts["consensus-1"].recover_chain_from_consensus_peers()
                self.assertEqual(recovered_heights, (1,))
                self.assertEqual(consensus_hosts["consensus-1"].consensus.chain.current_height, 1)

                with self.assertRaisesRegex(ValueError, "bundle seq is not currently executable"):
                    network.send(
                        NetworkEnvelope(
                            msg_type=MSG_BUNDLE_SUBMIT,
                            sender_id="alice",
                            recipient_id="consensus-1",
                            payload={"submission": submission},
                        )
                    )
            finally:
                network.send = original_send
                bob.close()
                alice.close()
                for consensus in reversed(tuple(consensus_hosts.values())):
                    consensus.close()

    def test_tx_hash_uses_canonical_encoding(self) -> None:
        tx = OffChainTx(
            sender_addr="alice",
            recipient_addr="bob",
            value_list=(ValueRange(10, 19),),
            tx_local_index=3,
            tx_time=9,
        )

        self.assertEqual(
            V2AccountHost._tx_hash_hex(tx),
            keccak256(canonical_encode(tx)).hex(),
        )


if __name__ == "__main__":
    unittest.main()
