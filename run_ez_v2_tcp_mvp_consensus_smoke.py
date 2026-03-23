#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import tempfile
from pathlib import Path

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import ValueRange


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_smoke(root_dir: str, chain_id: int) -> dict[str, object]:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    alice_private, alice_public = generate_secp256k1_keypair()
    bob_private, bob_public = generate_secp256k1_keypair()
    alice_addr = address_from_public_key_pem(alice_public)
    bob_addr = address_from_public_key_pem(bob_public)

    peers = (
        PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="consensus-3", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": alice_addr}),
        PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": bob_addr}),
    )
    peer_map = {peer.node_id: peer for peer in peers}

    def _network_for(peer_id: str) -> TransportPeerNetwork:
        return TransportPeerNetwork(
            TCPNetworkTransport("127.0.0.1", int(peer_map[peer_id].endpoint.rsplit(":", 1)[1])),
            peers,
        )

    consensus0_network = _network_for("consensus-0")
    consensus1_network = _network_for("consensus-1")
    consensus2_network = _network_for("consensus-2")
    consensus3_network = _network_for("consensus-3")
    alice_network = _network_for("alice")
    bob_network = _network_for("bob")
    validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")

    consensus0 = V2ConsensusHost(
        node_id="consensus-0",
        endpoint=peer_map["consensus-0"].endpoint,
        store_path=str(root / "consensus0.sqlite3"),
        network=consensus0_network,
        chain_id=chain_id,
        consensus_mode="mvp",
        consensus_validator_ids=validator_ids,
    )
    consensus1 = V2ConsensusHost(
        node_id="consensus-1",
        endpoint=peer_map["consensus-1"].endpoint,
        store_path=str(root / "consensus1.sqlite3"),
        network=consensus1_network,
        chain_id=chain_id,
        consensus_mode="mvp",
        consensus_validator_ids=validator_ids,
    )
    consensus2 = V2ConsensusHost(
        node_id="consensus-2",
        endpoint=peer_map["consensus-2"].endpoint,
        store_path=str(root / "consensus2.sqlite3"),
        network=consensus2_network,
        chain_id=chain_id,
        consensus_mode="mvp",
        consensus_validator_ids=validator_ids,
    )
    consensus3 = V2ConsensusHost(
        node_id="consensus-3",
        endpoint=peer_map["consensus-3"].endpoint,
        store_path=str(root / "consensus3.sqlite3"),
        network=consensus3_network,
        chain_id=chain_id,
        consensus_mode="mvp",
        consensus_validator_ids=validator_ids,
    )
    alice = V2AccountHost(
        node_id="alice",
        endpoint=peer_map["alice"].endpoint,
        wallet_db_path=str(root / "alice.sqlite3"),
        chain_id=chain_id,
        network=alice_network,
        consensus_peer_id="consensus-0",
        address=alice_addr,
        private_key_pem=alice_private,
        public_key_pem=alice_public,
    )
    bob = V2AccountHost(
        node_id="bob",
        endpoint=peer_map["bob"].endpoint,
        wallet_db_path=str(root / "bob.sqlite3"),
        chain_id=chain_id,
        network=bob_network,
        consensus_peer_id="consensus-0",
        address=bob_addr,
        private_key_pem=bob_private,
        public_key_pem=bob_public,
    )
    consensus_hosts = {
        "consensus-0": consensus0,
        "consensus-1": consensus1,
        "consensus-2": consensus2,
        "consensus-3": consensus3,
    }

    try:
        consensus0_network.start()
        consensus1_network.start()
        consensus2_network.start()
        consensus3_network.start()
        alice_network.start()
        bob_network.start()

        allocation = ValueRange(0, 199)
        for consensus in (consensus0, consensus1, consensus2, consensus3):
            consensus.register_genesis_value(alice.address, allocation)
        alice.register_genesis_value(allocation)

        seed = keccak256(b"tcp-mvp-smoke-sortition")
        selection = consensus0.select_mvp_proposer(
            consensus_peer_ids=validator_ids,
            seed=seed,
        )
        winner_id = str(selection["selected_proposer_id"])
        ordered_peer_ids = tuple(selection["ordered_consensus_peer_ids"])
        alice.set_consensus_peer_id(winner_id)
        bob.set_consensus_peer_id(winner_id)

        payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=71)
        result = consensus_hosts[winner_id].run_mvp_consensus_round(consensus_peer_ids=ordered_peer_ids)

        return {
            "mode": "tcp-mvp-consensus",
            "chain_id": chain_id,
            "selected_proposer_id": winner_id,
            "selected_seed_hex": seed.hex(),
            "result": result,
            "heights": {
                "consensus_0": consensus0.consensus.chain.current_height,
                "consensus_1": consensus1.consensus.chain.current_height,
                "consensus_2": consensus2.consensus.chain.current_height,
                "consensus_3": consensus3.consensus.chain.current_height,
            },
            "balances": {
                "alice": alice.wallet.available_balance(),
                "bob": bob.wallet.available_balance(),
            },
            "payment": {
                "submit_hash": payment.submit_hash_hex,
                "receipt_height": payment.receipt_height,
            },
            "receipts": {
                "alice": len(alice.wallet.list_receipts()),
                "bob": len(bob.wallet.list_receipts()),
            },
        }
    finally:
        bob_network.stop()
        alice_network.stop()
        consensus3_network.stop()
        consensus2_network.stop()
        consensus1_network.stop()
        consensus0_network.stop()
        bob.close()
        alice.close()
        consensus3.close()
        consensus2.close()
        consensus1.close()
        consensus0.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an EZchain V2 TCP MVP consensus smoke scenario")
    parser.add_argument("--root-dir", default="", help="Directory for sqlite files")
    parser.add_argument("--chain-id", type=int, default=931)
    parser.add_argument(
        "--allow-bind-restricted-skip",
        action="store_true",
        help="Return a skipped status instead of failing when TCP bind is not permitted",
    )
    args = parser.parse_args()

    try:
        if args.root_dir:
            print(json.dumps(run_smoke(args.root_dir, args.chain_id), indent=2))
            return
        with tempfile.TemporaryDirectory(prefix="ez_v2_tcp_mvp_") as td:
            print(json.dumps(run_smoke(td, args.chain_id), indent=2))
    except PermissionError as exc:
        if not args.allow_bind_restricted_skip:
            raise
        print(json.dumps({"status": "skipped", "reason": f"bind_not_permitted:{exc}"}, indent=2))


if __name__ == "__main__":
    main()
