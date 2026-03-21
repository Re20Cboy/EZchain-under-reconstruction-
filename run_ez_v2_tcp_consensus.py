#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path

from EZ_V2.control import read_backend_metadata, write_state_file
from EZ_V2.network_host import V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    host, port_s = endpoint.rsplit(":", 1)
    return host.strip(), int(port_s)


def run_daemon(root_dir: str, chain_id: int, state_file: str, heartbeat_sec: float, endpoint: str) -> None:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    peer = PeerInfo(node_id="consensus-0", role="consensus", endpoint=endpoint)
    host, port = _parse_endpoint(endpoint)
    network = TransportPeerNetwork(
        TCPNetworkTransport(host, port),
        (peer,),
    )
    consensus = V2ConsensusHost(
        node_id=peer.node_id,
        endpoint=peer.endpoint,
        store_path=str(root / "consensus.sqlite3"),
        network=network,
        chain_id=chain_id,
    )

    running = True

    def _stop(_signum, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    network.start()
    started_at = int(time.time())
    try:
        while running:
            write_state_file(
                state_file,
                {
                    "mode": "v2-tcp-consensus",
                    "pid": os.getpid(),
                    "root_dir": str(root),
                    "endpoint": endpoint,
                    "started_at": started_at,
                    "updated_at": int(time.time()),
                    "backend": read_backend_metadata(str(root)),
                },
            )
            time.sleep(max(0.1, heartbeat_sec))
    finally:
        network.stop()
        consensus.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal EZchain V2 TCP consensus daemon")
    parser.add_argument("--root-dir", required=True, help="Directory for consensus sqlite files")
    parser.add_argument("--state-file", required=True, help="State file for daemon mode")
    parser.add_argument("--chain-id", type=int, default=1, help="Chain id for the V2 consensus daemon")
    parser.add_argument("--heartbeat-sec", type=float, default=0.5, help="Heartbeat interval")
    parser.add_argument("--endpoint", default="127.0.0.1:19500", help="TCP listen endpoint")
    args = parser.parse_args()

    run_daemon(
        root_dir=args.root_dir,
        chain_id=args.chain_id,
        state_file=args.state_file,
        heartbeat_sec=args.heartbeat_sec,
        endpoint=args.endpoint,
    )


if __name__ == "__main__":
    main()
