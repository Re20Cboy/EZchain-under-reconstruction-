#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
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


def _wait_for_consensus_height(consensus: V2ConsensusHost, expected_height: int, timeout_sec: float = 2.0) -> int:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if consensus.consensus.chain.current_height >= expected_height:
            return consensus.consensus.chain.current_height
        time.sleep(0.01)
    return consensus.consensus.chain.current_height


def _assign_cluster_order(
    accounts: tuple[V2AccountHost, ...],
    primary_peer_id: str,
    consensus_ids: tuple[str, ...],
) -> None:
    ordered = (primary_peer_id, *tuple(peer_id for peer_id in consensus_ids if peer_id != primary_peer_id))
    for account in accounts:
        account.set_consensus_peer_ids(ordered)


def run_smoke(root_dir: str, chain_id: int, seed: int, failover_round: int) -> dict[str, object]:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    alice_private, alice_public = generate_secp256k1_keypair()
    bob_private, bob_public = generate_secp256k1_keypair()
    carol_private, carol_public = generate_secp256k1_keypair()
    dave_private, dave_public = generate_secp256k1_keypair()
    alice_addr = address_from_public_key_pem(alice_public)
    bob_addr = address_from_public_key_pem(bob_public)
    carol_addr = address_from_public_key_pem(carol_public)
    dave_addr = address_from_public_key_pem(dave_public)

    peers = (
        PeerInfo(node_id="consensus-0", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="consensus-1", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="consensus-2", role="consensus", endpoint=f"127.0.0.1:{_reserve_port()}"),
        PeerInfo(node_id="alice", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": alice_addr}),
        PeerInfo(node_id="bob", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": bob_addr}),
        PeerInfo(node_id="carol", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": carol_addr}),
        PeerInfo(node_id="dave", role="account", endpoint=f"127.0.0.1:{_reserve_port()}", metadata={"address": dave_addr}),
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
    alice_network = _network_for("alice")
    bob_network = _network_for("bob")
    carol_network = _network_for("carol")
    dave_network = _network_for("dave")

    consensus0 = V2ConsensusHost(
        node_id="consensus-0",
        endpoint=peer_map["consensus-0"].endpoint,
        store_path=str(root / "consensus0.sqlite3"),
        network=consensus0_network,
        chain_id=chain_id,
    )
    consensus1 = V2ConsensusHost(
        node_id="consensus-1",
        endpoint=peer_map["consensus-1"].endpoint,
        store_path=str(root / "consensus1.sqlite3"),
        network=consensus1_network,
        chain_id=chain_id,
    )
    consensus2 = V2ConsensusHost(
        node_id="consensus-2",
        endpoint=peer_map["consensus-2"].endpoint,
        store_path=str(root / "consensus2.sqlite3"),
        network=consensus2_network,
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
    dave = V2AccountHost(
        node_id="dave",
        endpoint=peer_map["dave"].endpoint,
        wallet_db_path=str(root / "dave.sqlite3"),
        chain_id=chain_id,
        network=dave_network,
        consensus_peer_id="consensus-0",
        address=dave_addr,
        private_key_pem=dave_private,
        public_key_pem=dave_public,
    )

    try:
        consensus0_network.start()
        consensus1_network.start()
        consensus2_network.start()
        alice_network.start()
        bob_network.start()
        carol_network.start()
        dave_network.start()

        allocations = (
            (alice.address, ValueRange(0, 199)),
            (bob.address, ValueRange(200, 399)),
        )
        for consensus in (consensus0, consensus1, consensus2):
            for owner_addr, value in allocations:
                consensus.register_genesis_value(owner_addr, value)
        alice.register_genesis_value(allocations[0][1])
        bob.register_genesis_value(allocations[1][1])

        accounts = (alice, bob, carol, dave)
        rng = random.Random(seed)
        consensus_ids = ("consensus-0", "consensus-1", "consensus-2")
        rounds = (
            (alice, "carol", 50, 1, 201),
            (bob, "dave", 70, 2, 202),
            (carol, "alice", 20, 3, 203),
            (dave, "bob", 30, 4, 204),
        )
        winners: list[str] = []
        effective_winners: list[str] = []
        payments = []
        for sender, recipient_peer_id, amount, tx_time, nonce in rounds:
            winner = rng.choice(consensus_ids)
            winners.append(winner)
            if failover_round == tx_time:
                _assign_cluster_order(accounts, f"{winner}-offline", consensus_ids)
            else:
                _assign_cluster_order(accounts, winner, consensus_ids)
            payments.append(
                sender.submit_payment(
                    recipient_peer_id,
                    amount=amount,
                    tx_time=tx_time,
                    anti_spam_nonce=nonce,
                )
            )
            effective_winners.append(sender.consensus_peer_id)

        follower_1_height = _wait_for_consensus_height(consensus1, 4)
        follower_2_height = _wait_for_consensus_height(consensus2, 4)

        return {
            "mode": "three-consensus-four-account",
            "consensus_replication": "rotating-winner-with-replication-followers",
            "chain_id": chain_id,
            "winner_seed": seed,
            "failover_round": failover_round if failover_round > 0 else None,
            "round_winners": winners,
            "effective_round_winners": effective_winners,
            "heights": {
                "consensus_0": consensus0.consensus.chain.current_height,
                "follower_1": follower_1_height,
                "follower_2": follower_2_height,
            },
            "block_hashes": {
                "consensus_0": consensus0.consensus.chain.current_block_hash.hex(),
                "follower_1": consensus1.consensus.chain.current_block_hash.hex(),
                "follower_2": consensus2.consensus.chain.current_block_hash.hex(),
            },
            "balances": {
                "alice": alice.wallet.available_balance(),
                "bob": bob.wallet.available_balance(),
                "carol": carol.wallet.available_balance(),
                "dave": dave.wallet.available_balance(),
            },
            "receipts": {
                "alice": len(alice.wallet.list_receipts()),
                "bob": len(bob.wallet.list_receipts()),
                "carol": len(carol.wallet.list_receipts()),
                "dave": len(dave.wallet.list_receipts()),
            },
            "payments": [
                {
                    "winner": winners[index],
                    "effective_winner": effective_winners[index],
                    "sender_addr": payment.sender_addr,
                    "recipient_addr": payment.recipient_addr,
                    "amount": payment.amount,
                    "receipt_height": payment.receipt_height,
                    "receipt_block_hash": payment.receipt_block_hash_hex,
                }
                for index, payment in enumerate(payments)
            ],
        }
    finally:
        dave_network.stop()
        carol_network.stop()
        bob_network.stop()
        alice_network.stop()
        consensus2_network.stop()
        consensus1_network.stop()
        consensus0_network.stop()
        dave.close()
        carol.close()
        bob.close()
        alice.close()
        consensus2.close()
        consensus1.close()
        consensus0.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an EZchain V2 3-consensus 4-account TCP cluster smoke scenario")
    parser.add_argument("--root-dir", default="", help="Directory for sqlite files")
    parser.add_argument("--chain-id", type=int, default=821)
    parser.add_argument("--seed", type=int, default=821, help="Deterministic random seed for choosing the block winner each round")
    parser.add_argument(
        "--failover-round",
        type=int,
        default=0,
        help="If set to 1-4, treat the chosen winner in that round as unavailable and force automatic fallback",
    )
    parser.add_argument(
        "--allow-bind-restricted-skip",
        action="store_true",
        help="Return a skipped status instead of failing when TCP bind is not permitted",
    )
    args = parser.parse_args()

    try:
        if args.root_dir:
            print(json.dumps(run_smoke(args.root_dir, args.chain_id, args.seed, args.failover_round), indent=2))
            return

        with tempfile.TemporaryDirectory(prefix="ez_v2_tcp_cluster_") as td:
            print(json.dumps(run_smoke(td, args.chain_id, args.seed, args.failover_round), indent=2))
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
