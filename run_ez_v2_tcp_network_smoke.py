#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import tempfile
import time
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


def _wait_for_chain_height(account: V2AccountHost, expected_height: int, timeout_sec: float = 1.0) -> int | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if account.last_seen_chain is not None and account.last_seen_chain.height >= expected_height:
            return account.last_seen_chain.height
        time.sleep(0.01)
    if account.last_seen_chain is None:
        return None
    return account.last_seen_chain.height


def run_smoke(root_dir: str, chain_id: int) -> dict[str, object]:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    alice_private, alice_public = generate_secp256k1_keypair()
    bob_private, bob_public = generate_secp256k1_keypair()
    carol_private, carol_public = generate_secp256k1_keypair()
    alice_addr = address_from_public_key_pem(alice_public)
    bob_addr = address_from_public_key_pem(bob_public)
    carol_addr = address_from_public_key_pem(carol_public)

    peers = (
        PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": alice_addr}),
        PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": bob_addr}),
        PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": carol_addr}),
    )
    peer_map = {peer.node_id: peer for peer in peers}

    consensus_network = TransportPeerNetwork(
        TCPNetworkTransport("127.0.0.1", int(peer_map["consensus-0"].endpoint.rsplit(":", 1)[1])),
        peers,
    )
    alice_network = TransportPeerNetwork(
        TCPNetworkTransport("127.0.0.1", int(peer_map["alice"].endpoint.rsplit(":", 1)[1])),
        peers,
    )
    bob_network = TransportPeerNetwork(
        TCPNetworkTransport("127.0.0.1", int(peer_map["bob"].endpoint.rsplit(":", 1)[1])),
        peers,
    )
    carol_network = TransportPeerNetwork(
        TCPNetworkTransport("127.0.0.1", int(peer_map["carol"].endpoint.rsplit(":", 1)[1])),
        peers,
    )

    consensus = V2ConsensusHost(
        node_id="consensus-0",
        endpoint=peer_map["consensus-0"].endpoint,
        store_path=str(root / "consensus.sqlite3"),
        network=consensus_network,
        chain_id=chain_id,
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
    carol = V2AccountHost(
        node_id="carol",
        endpoint=peer_map["carol"].endpoint,
        wallet_db_path=str(root / "carol.sqlite3"),
        chain_id=chain_id,
        network=carol_network,
        consensus_peer_id="consensus-0",
        address=carol_addr,
        private_key_pem=carol_private,
        public_key_pem=carol_public,
    )

    try:
        consensus_network.start()
        alice_network.start()
        bob_network.start()
        carol_network.start()

        minted = ValueRange(0, 199)
        consensus.register_genesis_value(alice.address, minted)
        alice.register_genesis_value(minted)
        payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=7)
        chain_state = bob.refresh_chain_state()
        fetched = bob.sync_chain_blocks()
        carol_broadcast_height = _wait_for_chain_height(carol, 1)
        carol_chain_state = carol.refresh_chain_state()

        return {
            "chain_id": chain_id,
            "height": consensus.consensus.chain.current_height,
            "alice_balance": alice.wallet.available_balance(),
            "bob_balance": bob.wallet.available_balance(),
            "alice_receipts": len(alice.wallet.list_receipts()),
            "bob_transfers": len(bob.received_transfers),
            "bob_chain_height": None if chain_state is None else chain_state.height,
            "carol_broadcast_height": carol_broadcast_height,
            "carol_chain_height": None if carol_chain_state is None else carol_chain_state.height,
            "fetched_block_heights": [block.header.height for block in fetched],
            "payment": {
                "tx_hash": payment.tx_hash_hex,
                "submit_hash": payment.submit_hash_hex,
                "receipt_height": payment.receipt_height,
                "receipt_block_hash": payment.receipt_block_hash_hex,
            },
        }
    finally:
        carol_network.stop()
        bob_network.stop()
        alice_network.stop()
        consensus_network.stop()
        carol.close()
        bob.close()
        alice.close()
        consensus.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an EZchain V2 static TCP network smoke scenario")
    parser.add_argument("--root-dir", default="", help="Directory for sqlite files")
    parser.add_argument("--chain-id", type=int, default=811)
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

        with tempfile.TemporaryDirectory(prefix="ez_v2_tcp_network_") as td:
            print(json.dumps(run_smoke(td, args.chain_id), indent=2))
    except PermissionError as exc:
        if not args.allow_bind_restricted_skip:
            raise
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": f"bind_not_permitted:{exc}",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
