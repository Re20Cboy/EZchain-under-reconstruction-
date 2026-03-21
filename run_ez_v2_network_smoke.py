#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile

from EZ_V2.network_host import V2AccountHost, open_static_network
from EZ_V2.values import ValueRange


def run_smoke(root_dir: str, chain_id: int) -> dict[str, object]:
    network, consensus = open_static_network(root_dir, chain_id=chain_id)
    alice = V2AccountHost(
        node_id="alice",
        endpoint="mem://alice",
        wallet_db_path=f"{root_dir}/alice.sqlite3",
        chain_id=chain_id,
        network=network,
        consensus_peer_id=consensus.peer.node_id,
    )
    bob = V2AccountHost(
        node_id="bob",
        endpoint="mem://bob",
        wallet_db_path=f"{root_dir}/bob.sqlite3",
        chain_id=chain_id,
        network=network,
        consensus_peer_id=consensus.peer.node_id,
    )
    try:
        minted = ValueRange(0, 199)
        consensus.register_genesis_value(alice.address, minted)
        alice.register_genesis_value(minted)
        payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=7)
        bob.refresh_chain_state()
        return {
            "chain_id": chain_id,
            "height": consensus.consensus.chain.current_height,
            "alice_balance": alice.wallet.available_balance(),
            "bob_balance": bob.wallet.available_balance(),
            "alice_receipts": len(alice.wallet.list_receipts()),
            "bob_transfers": len(bob.received_transfers),
            "payment": {
                "tx_hash": payment.tx_hash_hex,
                "submit_hash": payment.submit_hash_hex,
                "receipt_height": payment.receipt_height,
                "receipt_block_hash": payment.receipt_block_hash_hex,
            },
        }
    finally:
        alice.close()
        bob.close()
        consensus.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal multi-node EZchain V2 network smoke scenario")
    parser.add_argument("--root-dir", default="", help="Directory for sqlite files")
    parser.add_argument("--chain-id", type=int, default=801)
    args = parser.parse_args()

    if args.root_dir:
        print(json.dumps(run_smoke(args.root_dir, args.chain_id), indent=2))
        return

    with tempfile.TemporaryDirectory(prefix="ez_v2_network_") as td:
        print(json.dumps(run_smoke(td, args.chain_id), indent=2))


if __name__ == "__main__":
    main()
