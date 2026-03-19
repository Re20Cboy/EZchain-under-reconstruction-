from __future__ import annotations

import argparse
import os
import signal
import tempfile
import time
from pathlib import Path

from EZ_V2.control import read_backend_metadata, write_state_file
from EZ_V2.localnet import V2ConsensusNode, V2LocalNetwork
from EZ_V2.values import ValueRange


def run_smoke(root_dir: str, chain_id: int) -> None:
    net = V2LocalNetwork(
        root_dir=root_dir,
        chain_id=chain_id,
        genesis_block_hash=b"\x11" * 32,
    )
    try:
        alice = net.add_account("alice")
        bob = net.add_account("bob")
        carol = net.add_account("carol")

        net.allocate_genesis_value("alice", ValueRange(0, 199))

        payment = alice.submit_payment(
            bob.address,
            amount=50,
            fee=1,
            tx_time=1,
        )
        produced = net.produce_block(timestamp=2)
        delivery = alice.deliver_outgoing_transfer(
            payment.target_tx,
            ValueRange(0, 49),
            recipient_addr=bob.address,
        )

        second_payment = bob.submit_payment(
            carol.address,
            amount=20,
            fee=1,
            tx_time=3,
        )
        produced2 = net.produce_block(timestamp=4)
        delivery2 = bob.deliver_outgoing_transfer(
            second_payment.target_tx,
            ValueRange(0, 19),
            recipient_addr=carol.address,
        )

        print("V2 localnet smoke scenario completed")
        print(f"root_dir={root_dir}")
        print(f"chain_id={chain_id}")
        print(f"height={net.consensus.chain.current_height}")
        print(f"alice_receipt_applied={produced.deliveries[alice.address].applied}")
        print(f"bob_receive_accepted={delivery.accepted}")
        print(f"bob_receipt_applied={produced2.deliveries[bob.address].applied}")
        print(f"carol_receive_accepted={delivery2.accepted}")
        print(f"alice_balance={alice.wallet.available_balance()}")
        print(f"bob_balance={bob.wallet.available_balance()}")
        print(f"carol_balance={carol.wallet.available_balance()}")
    finally:
        net.close()


def run_daemon(root_dir: str, chain_id: int, state_file: str, heartbeat_sec: float) -> None:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    consensus = V2ConsensusNode(store_path=str(root / "consensus.sqlite3"), chain_id=chain_id)
    consensus.close()

    running = True

    def _stop(_signum, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    started_at = int(time.time())
    while running:
        write_state_file(
            state_file,
            {
                "mode": "v2-localnet",
                "pid": os.getpid(),
                "root_dir": str(root),
                "started_at": started_at,
                "updated_at": int(time.time()),
                "backend": read_backend_metadata(str(root)),
            },
        )
        time.sleep(max(0.1, heartbeat_sec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal EZchain V2 localnet smoke scenario")
    parser.add_argument("--root-dir", default="", help="Directory for localnet sqlite files")
    parser.add_argument("--chain-id", type=int, default=701, help="Chain id for the V2 localnet")
    parser.add_argument("--daemon", action="store_true", help="Run as a long-lived localnet process")
    parser.add_argument("--state-file", default="", help="State file for daemon mode")
    parser.add_argument("--heartbeat-sec", type=float, default=0.5, help="Daemon heartbeat interval")
    args = parser.parse_args()

    if args.daemon:
        if not args.root_dir:
            raise ValueError("--root-dir is required in daemon mode")
        if not args.state_file:
            raise ValueError("--state-file is required in daemon mode")
        run_daemon(
            root_dir=args.root_dir,
            chain_id=args.chain_id,
            state_file=args.state_file,
            heartbeat_sec=args.heartbeat_sec,
        )
        return

    if args.root_dir:
        root_dir = args.root_dir
        Path(root_dir).mkdir(parents=True, exist_ok=True)
        run_smoke(root_dir=root_dir, chain_id=args.chain_id)
        return

    with tempfile.TemporaryDirectory(prefix="ez_v2_localnet_") as tmpdir:
        run_smoke(root_dir=tmpdir, chain_id=args.chain_id)


if __name__ == "__main__":
    main()
