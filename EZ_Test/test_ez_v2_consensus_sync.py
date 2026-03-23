from dataclasses import replace
import tempfile
import unittest

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.networking import MSG_BLOCK_ANNOUNCE, MSG_BLOCK_FETCH_REQ, MSG_BLOCK_FETCH_RESP, NetworkEnvelope, PeerInfo
from EZ_V2.values import ValueRange


class EZV2ConsensusSyncTest(unittest.TestCase):
    @staticmethod
    def _announce_block(network, sender_id: str, recipient_id: str, *, height: int, block_hash_hex: str):
        return network.send(
            NetworkEnvelope(
                msg_type=MSG_BLOCK_ANNOUNCE,
                sender_id=sender_id,
                recipient_id=recipient_id,
                payload={
                    "height": height,
                    "block_hash": block_hash_hex,
                },
            )
        )

    def test_static_consensus_rejects_announced_block_with_wrong_chain_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            source = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/source.sqlite3",
                network=network,
                chain_id=920,
                auto_announce_blocks=False,
            )
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=920,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=920,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=920,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                source.register_genesis_value(alice.address, minted)
                follower.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=301)
                valid_block = source.consensus.store.get_block_by_height(1)
                assert valid_block is not None
                bad_block = replace(valid_block, header=replace(valid_block.header, chain_id=921))

                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={
                                    "status": "ok",
                                    "block": bad_block,
                                    "height": bad_block.header.height,
                                    "block_hash_hex": bad_block.block_hash.hex(),
                                },
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                rejected = self._announce_block(
                    network,
                    "consensus-bad",
                    "consensus-1",
                    height=1,
                    block_hash_hex=bad_block.block_hash.hex(),
                )
                self.assertEqual(rejected["ok"], False)
                self.assertEqual(rejected["error"], "unexpected_chain_id")
                self.assertEqual(follower.consensus.chain.current_height, 0)

                synced = self._announce_block(
                    network,
                    "consensus-0",
                    "consensus-1",
                    height=1,
                    block_hash_hex=valid_block.block_hash.hex(),
                )
                self.assertEqual(synced["status"], "synced")
                self.assertEqual(synced["runtime_snapshot"].chain_height, 1)
                self.assertEqual(follower.consensus.chain.current_height, 1)
            finally:
                bob.close()
                alice.close()
                follower.close()
                source.close()

    def test_static_consensus_rejects_announced_block_with_bad_state_root_and_recovers_on_honest_announce(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            source = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/source.sqlite3",
                network=network,
                chain_id=922,
                auto_announce_blocks=False,
            )
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=922,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=922,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=922,
                network=network,
                consensus_peer_id="consensus-0",
            )
            try:
                minted = ValueRange(0, 199)
                source.register_genesis_value(alice.address, minted)
                follower.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)
                alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=302)
                valid_block = source.consensus.store.get_block_by_height(1)
                assert valid_block is not None
                bad_block = replace(valid_block, header=replace(valid_block.header, state_root=b"\xff" * 32))

                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={
                                    "status": "ok",
                                    "block": bad_block,
                                    "height": bad_block.header.height,
                                    "block_hash_hex": bad_block.block_hash.hex(),
                                },
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                rejected = self._announce_block(
                    network,
                    "consensus-bad",
                    "consensus-1",
                    height=1,
                    block_hash_hex=bad_block.block_hash.hex(),
                )
                self.assertEqual(rejected["ok"], False)
                self.assertEqual(rejected["error"], "state_root mismatch")
                self.assertEqual(follower.consensus.chain.current_height, 0)

                synced = self._announce_block(
                    network,
                    "consensus-0",
                    "consensus-1",
                    height=1,
                    block_hash_hex=valid_block.block_hash.hex(),
                )
                self.assertEqual(synced["status"], "synced")
                self.assertEqual(synced["runtime_snapshot"].chain_height, 1)
                self.assertEqual(follower.consensus.chain.current_height, 1)
            finally:
                bob.close()
                alice.close()
                follower.close()
                source.close()

    def test_static_consensus_rejects_fake_height_when_announcer_cannot_supply_missing_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            follower = V2ConsensusHost(
                node_id="consensus-1",
                endpoint="mem://consensus-1",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=923,
            )
            try:
                def _malicious_handler(envelope: NetworkEnvelope):
                    if envelope.msg_type == MSG_BLOCK_FETCH_REQ:
                        network.send(
                            NetworkEnvelope(
                                msg_type=MSG_BLOCK_FETCH_RESP,
                                sender_id="consensus-bad",
                                recipient_id=envelope.sender_id,
                                request_id=envelope.request_id,
                                payload={"status": "missing"},
                            )
                        )
                        return {"ok": True}
                    return {"ok": False, "error": f"unsupported_message:{envelope.msg_type}"}

                network.register(
                    PeerInfo(node_id="consensus-bad", role="consensus", endpoint="mem://consensus-bad"),
                    _malicious_handler,
                )

                result = self._announce_block(
                    network,
                    "consensus-bad",
                    "consensus-1",
                    height=3,
                    block_hash_hex="00" * 32,
                )
                self.assertEqual(result["ok"], False)
                self.assertEqual(result["error"], "missing_announced_block:1")
                self.assertEqual(follower.consensus.chain.current_height, 0)
            finally:
                follower.close()

    def test_static_network_bootstrap_fetches_missing_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            consensus = V2ConsensusHost(
                node_id="consensus-0",
                endpoint="mem://consensus-0",
                store_path=f"{td}/consensus.sqlite3",
                network=network,
                chain_id=906,
                auto_announce_blocks=False,
            )
            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=906,
                network=network,
                consensus_peer_id=consensus.peer.node_id,
            )
            follower = V2ConsensusHost(
                node_id="consensus-follower",
                endpoint="mem://consensus-follower",
                store_path=f"{td}/follower.sqlite3",
                network=network,
                chain_id=906,
                auto_announce_blocks=False,
            )
            try:
                minted = ValueRange(0, 299)
                consensus.register_genesis_value(alice.address, minted)
                follower.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                first = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=71)
                second = alice.submit_payment("bob", amount=25, tx_time=2, anti_spam_nonce=72)

                self.assertEqual(first.receipt_height, 1)
                self.assertEqual(second.receipt_height, 2)
                self.assertEqual(consensus.consensus.chain.current_height, 2)
                self.assertEqual(follower.consensus.chain.current_height, 0)

                synced = self._announce_block(
                    network,
                    consensus.peer.node_id,
                    follower.peer.node_id,
                    height=2,
                    block_hash_hex=consensus.consensus.chain.current_block_hash.hex(),
                )

                self.assertEqual(synced["status"], "synced")
                self.assertEqual(tuple(synced["applied_heights"]), (1, 2))
                self.assertEqual(synced["runtime_snapshot"].chain_height, 2)
                self.assertEqual(follower.consensus.chain.current_height, 2)
            finally:
                follower.close()
                bob.close()
                alice.close()
                consensus.close()
