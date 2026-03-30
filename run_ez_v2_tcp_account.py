#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import time
from pathlib import Path

from EZ_V2.control import write_state_file
from EZ_V2.crypto import (
    address_from_public_key_pem,
    derive_secp256k1_keypair_from_mnemonic,
    generate_secp256k1_keypair,
)
from EZ_V2.network_host import V2AccountHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import PeerInfo, with_v2_features
from EZ_V2.transport_peer import TransportPeerNetwork


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    host, port_s = endpoint.rsplit(":", 1)
    return host.strip(), int(port_s)


def _load_identity_from_wallet_file(wallet_file: Path) -> tuple[bytes, bytes, str] | None:
    if not wallet_file.exists():
        return None
    payload = json.loads(wallet_file.read_text(encoding="utf-8"))
    mnemonic = str(payload.get("mnemonic", "")).strip()
    if not mnemonic:
        raise ValueError("wallet_file_missing_mnemonic")
    private_key_pem, public_key_pem = derive_secp256k1_keypair_from_mnemonic(mnemonic)
    address = address_from_public_key_pem(public_key_pem)
    return private_key_pem, public_key_pem, address


def _default_wallet_db_path_from_wallet_file(wallet_file: Path, address: str) -> Path:
    return wallet_file.parent / "wallet_state_v2" / address / "wallet_v2.db"


def _load_or_create_identity(identity_path: Path, wallet_file: Path | None = None) -> tuple[bytes, bytes, str, str]:
    if wallet_file is not None:
        wallet_identity = _load_identity_from_wallet_file(wallet_file)
        if wallet_identity is not None:
            private_key_pem, public_key_pem, address = wallet_identity
            identity_path.parent.mkdir(parents=True, exist_ok=True)
            identity_path.write_text(
                json.dumps(
                    {
                        "private_key_pem": private_key_pem.decode("utf-8"),
                        "public_key_pem": public_key_pem.decode("utf-8"),
                        "address": address,
                        "source": "wallet_file",
                        "wallet_file": str(wallet_file),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return private_key_pem, public_key_pem, address, "wallet_file"
    if identity_path.exists():
        payload = json.loads(identity_path.read_text(encoding="utf-8"))
        private_key_pem = str(payload["private_key_pem"]).encode("utf-8")
        public_key_pem = str(payload["public_key_pem"]).encode("utf-8")
        address = str(payload["address"])
        return private_key_pem, public_key_pem, address, str(payload.get("source", "identity_file"))

    private_key_pem, public_key_pem = generate_secp256k1_keypair()
    address = address_from_public_key_pem(public_key_pem)
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(
        json.dumps(
            {
                "private_key_pem": private_key_pem.decode("utf-8"),
                "public_key_pem": public_key_pem.decode("utf-8"),
                "address": address,
                "source": "generated",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return private_key_pem, public_key_pem, address, "generated"


def run_daemon(
    *,
    root_dir: str,
    chain_id: int,
    state_file: str,
    heartbeat_sec: float,
    endpoint: str,
    listen_host: str | None,
    consensus_peer_id: str,
    consensus_endpoint: str,
    wallet_file: str | None,
    wallet_db_path: str | None,
    reset_ephemeral_state: bool,
    reset_derived_state: bool,
    network_timeout_sec: float,
) -> None:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    identity_path = root / "account_identity.json"
    network_state_path = root / "account_network_state.json"
    wallet_file_path = Path(wallet_file) if wallet_file else None
    private_key_pem, public_key_pem, address, identity_source = _load_or_create_identity(
        identity_path,
        wallet_file=wallet_file_path,
    )
    if wallet_db_path:
        wallet_db = Path(wallet_db_path)
    elif identity_source == "wallet_file" and wallet_file_path is not None:
        wallet_db = _default_wallet_db_path_from_wallet_file(wallet_file_path, address)
    else:
        wallet_db = root / "account_wallet.sqlite3"
    if reset_derived_state:
        if wallet_db.exists():
            wallet_db.unlink()
        if wallet_db.parent.exists() and wallet_db.parent != root:
            shutil.rmtree(wallet_db.parent, ignore_errors=True)
        if network_state_path.exists():
            network_state_path.unlink()
        state_path_obj = Path(state_file)
        if state_path_obj.exists():
            state_path_obj.unlink()
    wallet_db.parent.mkdir(parents=True, exist_ok=True)

    local_peer = with_v2_features(
        PeerInfo(node_id=f"account-{address[-8:]}", role="account", endpoint=endpoint, metadata={"address": address})
    )
    consensus_peer = with_v2_features(
        PeerInfo(node_id=str(consensus_peer_id), role="consensus", endpoint=consensus_endpoint)
    )
    endpoint_host, port = _parse_endpoint(endpoint)
    bind_host = str(listen_host).strip() if listen_host else endpoint_host
    network = TransportPeerNetwork(
        TCPNetworkTransport(bind_host, port),
        (consensus_peer,),
        timeout_sec=network_timeout_sec,
    )
    account = V2AccountHost(
        node_id=local_peer.node_id,
        endpoint=local_peer.endpoint,
        wallet_db_path=str(wallet_db),
        chain_id=chain_id,
        network=network,
        consensus_peer_id=consensus_peer.node_id,
        address=address,
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        state_path=str(network_state_path),
    )
    if reset_ephemeral_state:
        account.reset_ephemeral_state()

    running = True

    def _stop(_signum, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    network.start()
    started_at = int(time.time())
    consecutive_sync_failures = 0
    max_consecutive_sync_failures = 0
    recovery_count = 0
    last_successful_sync_at = 0
    last_recovered_at = 0
    try:
        while running:
            sync_started_at = int(time.time())
            sync_duration_ms = 0
            last_sync_ok = True
            last_sync_error = ""
            recovered_this_sync = False
            recovery = None
            try:
                sync_started_monotonic = time.monotonic()
                recovery = account.recover_network_state()
                sync_duration_ms = int((time.monotonic() - sync_started_monotonic) * 1000)
            except Exception as exc:
                sync_duration_ms = int((time.monotonic() - sync_started_monotonic) * 1000)
                last_sync_ok = False
                last_sync_error = str(exc)
                recovery = None
            if last_sync_ok:
                recovered_this_sync = consecutive_sync_failures > 0
                if recovered_this_sync:
                    recovery_count += 1
                    last_recovered_at = int(time.time())
                consecutive_sync_failures = 0
                last_successful_sync_at = int(time.time())
            else:
                consecutive_sync_failures += 1
                max_consecutive_sync_failures = max(max_consecutive_sync_failures, consecutive_sync_failures)
            chain_cursor = account.last_seen_chain if recovery is None else recovery.chain_cursor
            chain_cursor_payload = None
            if chain_cursor is not None:
                chain_cursor_payload = {
                    "height": chain_cursor.height,
                    "block_hash_hex": chain_cursor.block_hash_hex,
                }
            pending_bundle_count = len(account.wallet.list_pending_bundles())
            receipt_count = len(account.wallet.list_receipts())
            pending_incoming_transfer_count = len(account.received_transfers)
            fetched_block_count = len(account.fetched_blocks)
            applied_receipts = 0
            if recovery is not None:
                pending_bundle_count = recovery.pending_bundle_count
                receipt_count = recovery.receipt_count
                fetched_block_count = len(recovery.fetched_blocks)
                applied_receipts = recovery.applied_receipts
            write_state_file(
                state_file,
                {
                    "mode": "v2-account",
                    "pid": os.getpid(),
                    "root_dir": str(root),
                    "endpoint": endpoint,
                    "listen_endpoint": f"{bind_host}:{port}",
                    "consensus_peer_id": consensus_peer.node_id,
                    "consensus_endpoint": consensus_endpoint,
                    "address": address,
                    "identity_source": identity_source,
                    "started_at": started_at,
                    "updated_at": int(time.time()),
                    "wallet_db_path": str(wallet_db),
                    "chain_cursor": chain_cursor_payload,
                    "pending_bundle_count": pending_bundle_count,
                    "receipt_count": receipt_count,
                    "pending_incoming_transfer_count": pending_incoming_transfer_count,
                    "fetched_block_count": fetched_block_count,
                    "applied_receipts_last_sync": applied_receipts,
                    "last_sync_at": int(time.time()),
                    "last_sync_started_at": sync_started_at,
                    "last_sync_duration_ms": sync_duration_ms,
                    "last_sync_ok": last_sync_ok,
                    "last_sync_error": last_sync_error,
                    "last_sync_recovered": recovered_this_sync,
                    "consecutive_sync_failures": consecutive_sync_failures,
                    "max_consecutive_sync_failures": max_consecutive_sync_failures,
                    "recovery_count": recovery_count,
                    "last_successful_sync_at": last_successful_sync_at,
                    "last_recovered_at": last_recovered_at,
                },
            )
            time.sleep(max(0.1, heartbeat_sec))
    finally:
        network.stop()
        account.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal EZchain V2 TCP account daemon")
    parser.add_argument("--root-dir", required=True, help="Directory for account wallet and state files")
    parser.add_argument("--state-file", required=True, help="State file for daemon mode")
    parser.add_argument("--chain-id", type=int, default=1, help="Chain id for the V2 account daemon")
    parser.add_argument("--heartbeat-sec", type=float, default=0.5, help="Heartbeat interval")
    parser.add_argument("--network-timeout-sec", type=float, default=5.0, help="Transport request timeout in seconds")
    parser.add_argument("--endpoint", default="127.0.0.1:19600", help="TCP listen endpoint for the account node")
    parser.add_argument(
        "--listen-host",
        default="",
        help="Optional local bind host override; useful when the advertised endpoint differs from the local listen interface",
    )
    parser.add_argument("--consensus-peer-id", default="consensus-0", help="Consensus peer id for the remote consensus endpoint")
    parser.add_argument("--consensus-endpoint", required=True, help="Remote consensus TCP endpoint")
    parser.add_argument("--wallet-file", default="", help="Optional wallet.json path to reuse as the account identity")
    parser.add_argument("--wallet-db-path", default="", help="Optional sqlite path to reuse as the account wallet database")
    parser.add_argument(
        "--reset-ephemeral-state",
        action="store_true",
        help="Testing helper: clear pending bundles and cached network state before starting the account daemon",
    )
    parser.add_argument(
        "--reset-derived-state",
        action="store_true",
        help="Testing helper: rebuild the derived account wallet database and cached state while preserving wallet.json identity",
    )
    args = parser.parse_args()

    run_daemon(
        root_dir=args.root_dir,
        chain_id=args.chain_id,
        state_file=args.state_file,
        heartbeat_sec=args.heartbeat_sec,
        endpoint=args.endpoint,
        listen_host=str(args.listen_host).strip() or None,
        consensus_peer_id=str(args.consensus_peer_id).strip() or "consensus-0",
        consensus_endpoint=args.consensus_endpoint,
        wallet_file=str(args.wallet_file).strip() or None,
        wallet_db_path=str(args.wallet_db_path).strip() or None,
        reset_ephemeral_state=bool(args.reset_ephemeral_state),
        reset_derived_state=bool(args.reset_derived_state),
        network_timeout_sec=float(args.network_timeout_sec),
    )


if __name__ == "__main__":
    main()
