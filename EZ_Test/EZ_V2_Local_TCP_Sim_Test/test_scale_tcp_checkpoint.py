from __future__ import annotations

import tempfile
import unittest

from EZ_Test.EZ_V2_Local_TCP_Sim_Test.assertions import assert_cluster_converged
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.host_harness import build_host_cluster
from EZ_Test.EZ_V2_Local_TCP_Sim_Test.profiles import HEAVY_MULTI_ROUND_PROFILE
from EZ_V2.types import CheckpointAnchor, PriorWitnessLink, WitnessV2
from EZ_V2.values import LocalValueStatus


def _witness_contains_checkpoint_anchor(witness: WitnessV2) -> bool:
    anchor = witness.anchor
    if isinstance(anchor, CheckpointAnchor):
        return True
    if isinstance(anchor, PriorWitnessLink):
        return _witness_contains_checkpoint_anchor(anchor.prior_witness)
    return False


class LocalTCPScaleCheckpointTests(unittest.TestCase):
    def test_scale_tcp_checkpoint_exact_return_and_partial_overlap_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cluster = build_host_cluster(HEAVY_MULTI_ROUND_PROFILE, td)
            try:
                cluster.start()

                alice = cluster.account_nodes["account-00"].host
                bob = cluster.account_nodes["account-01"].host
                carol = cluster.account_nodes["account-02"].host
                sink_one = cluster.account_nodes["account-04"].host
                sink_two = cluster.account_nodes["account-05"].host
                assert alice is not None
                assert bob is not None
                assert carol is not None
                assert sink_one is not None
                assert sink_two is not None

                exact_value = cluster.allocations[alice.address]
                bob_genesis = cluster.allocations[bob.address]
                carol_genesis = cluster.allocations[carol.address]

                def _submit_and_confirm(node_id: str, host, recipient_peer_id: str, *, amount: int, tx_time: int, anti_spam_nonce: int, expected_height: int):
                    expected_seq = host.wallet.next_sequence()
                    expected_receipt_count = len(host.wallet.list_receipts()) + 1
                    payment = host.submit_payment(
                        recipient_peer_id,
                        amount=amount,
                        tx_time=tx_time,
                        anti_spam_nonce=anti_spam_nonce,
                    )
                    cluster.wait_for_cluster_height(expected_height)
                    cluster.wait_for_receipt_count(node_id, expected_receipt_count, timeout_sec=8.0)
                    receipt = next((item for item in host.wallet.list_receipts() if item.seq == expected_seq), None)
                    if receipt is None:
                        host.recover_network_state()
                        receipt = next((item for item in host.wallet.list_receipts() if item.seq == expected_seq), None)
                    self.assertIsNotNone(receipt)
                    self.assertEqual(receipt.header_lite.height, expected_height)
                    return payment

                _submit_and_confirm("account-01", bob, "account-04", amount=bob_genesis.size, tx_time=1, anti_spam_nonce=801, expected_height=1)
                _submit_and_confirm("account-02", carol, "account-05", amount=carol_genesis.size, tx_time=2, anti_spam_nonce=802, expected_height=2)
                _submit_and_confirm("account-00", alice, "account-01", amount=exact_value.size, tx_time=3, anti_spam_nonce=803, expected_height=3)
                _submit_and_confirm("account-01", bob, "account-02", amount=exact_value.size, tx_time=4, anti_spam_nonce=804, expected_height=4)

                bob_archived = max(
                    (
                        record
                        for record in bob.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED and record.value == exact_value
                    ),
                    key=lambda item: item.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                checkpoint = bob.wallet.create_exact_checkpoint(bob_archived.record_id)
                self.assertEqual(checkpoint.value_begin, exact_value.begin)

                second_return = _submit_and_confirm(
                    "account-02",
                    carol,
                    "account-01",
                    amount=exact_value.size,
                    tx_time=5,
                    anti_spam_nonce=805,
                    expected_height=5,
                )
                self.assertEqual(second_return.receipt_height or 5, 5)
                carol_return_archived = max(
                    (
                        record
                        for record in carol.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED
                        and record.value == exact_value
                    ),
                    key=lambda item: item.witness_v2.confirmed_bundle_chain[0].receipt.seq,
                )
                return_tx = carol_return_archived.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                return_package = carol.wallet.export_transfer_package(return_tx, exact_value)
                self.assertTrue(_witness_contains_checkpoint_anchor(return_package.witness_v2))
                self.assertEqual(bob.wallet.available_balance(), exact_value.size)

                partial_return = _submit_and_confirm(
                    "account-01",
                    bob,
                    "account-00",
                    amount=exact_value.size // 2,
                    tx_time=6,
                    anti_spam_nonce=806,
                    expected_height=6,
                )
                self.assertEqual(partial_return.receipt_height or 6, 6)
                bob_partial_archived = max(
                    (
                        record
                        for record in bob.wallet.list_records()
                        if record.local_status == LocalValueStatus.ARCHIVED
                        and record.value.size == exact_value.size // 2
                    ),
                    key=lambda item: (item.acquisition_height, item.value.begin, item.value.end),
                )
                partial_tx = bob_partial_archived.witness_v2.confirmed_bundle_chain[0].bundle_sidecar.tx_list[0]
                partial_package = bob.wallet.export_transfer_package(partial_tx, bob_partial_archived.value)
                self.assertFalse(_witness_contains_checkpoint_anchor(partial_package.witness_v2))

                spend_after_fallback = _submit_and_confirm(
                    "account-00",
                    alice,
                    "account-02",
                    amount=exact_value.size // 2,
                    tx_time=7,
                    anti_spam_nonce=807,
                    expected_height=7,
                )
                self.assertEqual(spend_after_fallback.receipt_height or 7, 7)
                self.assertGreater(carol.wallet.available_balance(), 0)
                assert_cluster_converged(cluster.snapshot())
            finally:
                cluster.stop()


if __name__ == "__main__":
    unittest.main()
