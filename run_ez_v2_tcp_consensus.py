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


def _parse_peer_spec(spec: str) -> PeerInfo:
    node_id, endpoint = str(spec).split("=", 1)
    node_id = node_id.strip()
    endpoint = endpoint.strip()
    if not node_id:
        raise ValueError("peer_spec_missing_node_id")
    _parse_endpoint(endpoint)
    return PeerInfo(node_id=node_id, role="consensus", endpoint=endpoint)


def _build_consensus_peers(*, node_id: str, endpoint: str, peer_specs: tuple[str, ...]) -> tuple[PeerInfo, ...]:
    if not peer_specs:
        return (PeerInfo(node_id=node_id, role="consensus", endpoint=endpoint),)
    peers = tuple(_parse_peer_spec(spec) for spec in peer_specs)
    local_peer = next((peer for peer in peers if peer.node_id == node_id), None)
    if local_peer is None:
        raise ValueError("local_node_missing_from_peer_specs")
    if local_peer.endpoint != endpoint:
        raise ValueError("local_node_endpoint_mismatch")
    return peers


def run_daemon(
    *,
    root_dir: str,
    chain_id: int,
    state_file: str,
    heartbeat_sec: float,
    node_id: str,
    endpoint: str,
    listen_host: str | None,
    peer_specs: tuple[str, ...],
    consensus_mode: str,
    validator_ids: tuple[str, ...],
    auto_run_mvp_consensus: bool,
    network_timeout_sec: float,
) -> None:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    peers = _build_consensus_peers(node_id=node_id, endpoint=endpoint, peer_specs=peer_specs)
    peer_map = {peer.node_id: peer for peer in peers}
    peer = peer_map[node_id]
    endpoint_host, port = _parse_endpoint(endpoint)
    bind_host = str(listen_host).strip() if listen_host else endpoint_host
    network = TransportPeerNetwork(
        TCPNetworkTransport(bind_host, port),
        peers,
        timeout_sec=network_timeout_sec,
    )
    effective_validator_ids = tuple(validator_ids) or tuple(item.node_id for item in peers)
    consensus = V2ConsensusHost(
        node_id=peer.node_id,
        endpoint=peer.endpoint,
        store_path=str(root / "consensus.sqlite3"),
        network=network,
        chain_id=chain_id,
        consensus_mode=consensus_mode,
        consensus_validator_ids=effective_validator_ids,
        auto_run_mvp_consensus=auto_run_mvp_consensus,
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
                    "node_id": node_id,
                    "endpoint": endpoint,
                    "listen_endpoint": f"{bind_host}:{port}",
                    "peer_endpoints": {item.node_id: item.endpoint for item in peers},
                    "consensus_mode": consensus_mode,
                    "consensus_validator_ids": list(effective_validator_ids),
                    "auto_run_mvp_consensus": auto_run_mvp_consensus,
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
    parser.add_argument("--network-timeout-sec", type=float, default=5.0, help="Transport request timeout in seconds")
    parser.add_argument("--node-id", default="consensus-0", help="Consensus node id for this daemon")
    parser.add_argument("--endpoint", default="127.0.0.1:19500", help="TCP listen endpoint")
    parser.add_argument(
        "--listen-host",
        default="",
        help="Optional local bind host override; useful when the advertised endpoint differs from the local listen interface",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Repeatable consensus peer spec in the form node_id=host:port",
    )
    parser.add_argument(
        "--consensus-mode",
        choices=("legacy", "mvp"),
        default="legacy",
        help="Consensus host mode",
    )
    parser.add_argument(
        "--validator-id",
        action="append",
        default=[],
        help="Repeatable validator id list for mvp consensus; defaults to the configured peer ids",
    )
    parser.add_argument(
        "--auto-run-mvp-consensus",
        action="store_true",
        help="Automatically route and commit mvp consensus bundles through the selected proposer",
    )
    args = parser.parse_args()

    run_daemon(
        root_dir=args.root_dir,
        chain_id=args.chain_id,
        state_file=args.state_file,
        heartbeat_sec=args.heartbeat_sec,
        node_id=args.node_id,
        endpoint=args.endpoint,
        listen_host=str(args.listen_host).strip() or None,
        peer_specs=tuple(args.peer),
        consensus_mode=args.consensus_mode,
        validator_ids=tuple(args.validator_id),
        auto_run_mvp_consensus=bool(args.auto_run_mvp_consensus),
        network_timeout_sec=float(args.network_timeout_sec),
    )


if __name__ == "__main__":
    main()
