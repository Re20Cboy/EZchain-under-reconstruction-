#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
from EZ_V2.networking import PeerInfo
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
    consensus_endpoint: str,
    wallet_file: str | None,
    wallet_db_path: str | None,
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
    wallet_db.parent.mkdir(parents=True, exist_ok=True)

    local_peer = PeerInfo(node_id=f"account-{address[-8:]}", role="account", endpoint=endpoint, metadata={"address": address})
    consensus_peer = PeerInfo(node_id="consensus-0", role="consensus", endpoint=consensus_endpoint)
    host, port = _parse_endpoint(endpoint)
    network = TransportPeerNetwork(
        TCPNetworkTransport(host, port),
        (consensus_peer,),
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
    parser.add_argument("--endpoint", default="127.0.0.1:19600", help="TCP listen endpoint for the account node")
    parser.add_argument("--consensus-endpoint", required=True, help="Remote consensus TCP endpoint")
    parser.add_argument("--wallet-file", default="", help="Optional wallet.json path to reuse as the account identity")
    parser.add_argument("--wallet-db-path", default="", help="Optional sqlite path to reuse as the account wallet database")
    args = parser.parse_args()

    run_daemon(
        root_dir=args.root_dir,
        chain_id=args.chain_id,
        state_file=args.state_file,
        heartbeat_sec=args.heartbeat_sec,
        endpoint=args.endpoint,
        consensus_endpoint=args.consensus_endpoint,
        wallet_file=str(args.wallet_file).strip() or None,
        wallet_db_path=str(args.wallet_db_path).strip() or None,
    )


if __name__ == "__main__":
    main()
