from __future__ import annotations

import random
import socket
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.network_host import V2AccountHost, V2ConsensusHost
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import MSG_BUNDLE_SUBMIT, NetworkEnvelope, PeerInfo
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.types import OffChainTx
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.wallet import _partition_range

from .profiles import LocalTCPSimProfile, ScheduledEvent


def _reserve_port() -> int:
    last_exc: Exception | None = None
    for _ in range(20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return int(sock.getsockname()[1])
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.01)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("failed_to_reserve_port")


@dataclass
class ConsensusNodeRuntime:
    peer: PeerInfo
    store_path: Path
    network: TransportPeerNetwork | None = None
    host: V2ConsensusHost | None = None
    running: bool = False
    last_known_height: int = 0
    last_known_head_hash: str = ""


@dataclass
class AccountNodeRuntime:
    peer: PeerInfo
    wallet_db_path: Path
    state_path: Path
    private_key_pem: bytes
    public_key_pem: bytes
    address: str
    network: TransportPeerNetwork | None = None
    host: V2AccountHost | None = None
    running: bool = False
    send_count: int = 0
    receive_count: int = 0
    last_known_available_balance: int = 0
    last_known_total_balance: int = 0
    last_known_pending_bundle_count: int = 0
    last_known_receipt_count: int = 0
    last_known_checkpoint_count: int = 0
    last_known_consensus_peer_id: str = ""
    last_known_consensus_peer_ids: tuple[str, ...] = ()


@dataclass
class PendingBatchSubmission:
    sender_id: str
    txs: tuple[OffChainTx, ...]
    selected_primary: str
    expected_seq: int
    expected_receipt_count: int
    submit_hash_hex: str
    tx_hashes: tuple[str, ...]
    start_tx_index: int


class LocalTCPHostCluster:
    def __init__(self, *, profile: LocalTCPSimProfile, root_dir: str):
        self.profile = profile
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.chain_id = 20000 + (int(profile.seed) % 10000)
        self.random = random.Random(profile.seed)
        self._forced_proposer_id: str | None = None
        self._genesis_seeded = False
        self._initial_cluster_height = 0
        self._next_tx_index = 1
        self._confirmed_tx_count = 0
        self._failed_tx_count = 0
        self._confirmed_bundle_count = 0
        self._multi_value_tx_count = 0
        self._multi_tx_bundle_count = 0
        self._created_checkpoint_count = 0
        self._created_checkpoint_record_ids: set[tuple[str, str]] = set()
        self._accounts_touched: set[str] = set()
        self._scheduled_event_index = 0
        self._multi_value_seeded_composers: set[str] = set()
        self._multi_value_cycle_index = 0
        self._multi_tx_bundle_toggle = 0
        self._split_loop_completed = False
        self.transactions: list[dict[str, Any]] = []

        consensus_peers = tuple(
            PeerInfo(
                node_id=f"consensus-{index}",
                role="consensus",
                endpoint=f"127.0.0.1:{_reserve_port()}",
            )
            for index in range(profile.consensus_count)
        )
        account_identities: list[tuple[bytes, bytes, str]] = []
        for _ in range(profile.account_count):
            private_key_pem, public_key_pem = generate_secp256k1_keypair()
            account_identities.append(
                (
                    private_key_pem,
                    public_key_pem,
                    address_from_public_key_pem(public_key_pem),
                )
            )
        account_peers = tuple(
            PeerInfo(
                node_id=f"account-{index:02d}",
                role="account",
                endpoint=f"127.0.0.1:{_reserve_port()}",
                metadata={"address": identity[2]},
            )
            for index, identity in enumerate(account_identities)
        )
        self.all_peers = (*consensus_peers, *account_peers)
        self.peer_map = {peer.node_id: peer for peer in self.all_peers}
        self.consensus_ids = tuple(peer.node_id for peer in consensus_peers)
        self.account_ids = tuple(peer.node_id for peer in account_peers)

        self.consensus_nodes: dict[str, ConsensusNodeRuntime] = {}
        for peer in consensus_peers:
            self.consensus_nodes[peer.node_id] = ConsensusNodeRuntime(
                peer=peer,
                store_path=self.root_dir / f"{peer.node_id}.sqlite3",
            )

        self.account_nodes: dict[str, AccountNodeRuntime] = {}
        for index, peer in enumerate(account_peers):
            private_key_pem, public_key_pem, address = account_identities[index]
            self.account_nodes[peer.node_id] = AccountNodeRuntime(
                peer=peer,
                wallet_db_path=self.root_dir / f"{peer.node_id}.sqlite3",
                state_path=self.root_dir / f"{peer.node_id}-network-state.json",
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                address=address,
                last_known_consensus_peer_id=self.consensus_ids[0],
                last_known_consensus_peer_ids=self.consensus_ids,
            )

        cursor = 0
        self.allocations: dict[str, ValueRange] = {}
        for account_id in self.account_ids:
            runtime = self.account_nodes[account_id]
            value = ValueRange(cursor, cursor + int(profile.genesis_amount) - 1)
            self.allocations[runtime.address] = value
            cursor += int(profile.genesis_amount)

    @property
    def active_consensus_ids(self) -> tuple[str, ...]:
        return tuple(node_id for node_id, runtime in self.consensus_nodes.items() if runtime.running and runtime.host is not None)

    @property
    def active_account_ids(self) -> tuple[str, ...]:
        return tuple(node_id for node_id, runtime in self.account_nodes.items() if runtime.running and runtime.host is not None)

    @property
    def confirmed_tx_count(self) -> int:
        return self._confirmed_tx_count

    @property
    def failed_tx_count(self) -> int:
        return self._failed_tx_count

    def _network_for(self, peer_id: str) -> TransportPeerNetwork:
        endpoint = self.peer_map[peer_id].endpoint
        _, port_s = endpoint.rsplit(":", 1)
        return TransportPeerNetwork(
            TCPNetworkTransport("127.0.0.1", int(port_s)),
            self.all_peers,
            timeout_sec=self.profile.network_timeout_sec,
        )

    def _install_deterministic_proposer(self, host: V2ConsensusHost) -> None:
        def _select_mvp_proposer(**kwargs) -> dict[str, Any]:
            active_ids = self.active_consensus_ids
            if not active_ids:
                raise ValueError("no_running_consensus_nodes")
            winner_id = self._forced_proposer_id if self._forced_proposer_id in active_ids else active_ids[0]
            ordered_ids = (winner_id, *tuple(peer_id for peer_id in active_ids if peer_id != winner_id))
            seed = kwargs.get("seed", b"")
            seed_hex = seed.hex() if isinstance(seed, (bytes, bytearray)) else str(seed)
            return {
                "selected_proposer_id": winner_id,
                "ordered_consensus_peer_ids": ordered_ids,
                "height": int(kwargs.get("height", host.consensus.chain.current_height + 1)),
                "round": int(kwargs.get("round", 1)),
                "seed_hex": seed_hex,
                "claims_total": len(ordered_ids),
            }

        host.select_mvp_proposer = _select_mvp_proposer  # type: ignore[assignment]

    def _build_consensus_runtime(self, node_id: str) -> ConsensusNodeRuntime:
        runtime = self.consensus_nodes[node_id]
        network = self._network_for(node_id)
        host = V2ConsensusHost(
            node_id=node_id,
            endpoint=runtime.peer.endpoint,
            store_path=str(runtime.store_path),
            network=network,
            chain_id=self.chain_id,
            consensus_mode="mvp",
            consensus_validator_ids=self.consensus_ids,
            auto_run_mvp_consensus=True,
            auto_run_mvp_consensus_window_sec=self.profile.auto_run_window_sec,
        )
        self._install_deterministic_proposer(host)
        runtime.network = network
        runtime.host = host
        runtime.running = True
        return runtime

    def _build_account_runtime(self, node_id: str) -> AccountNodeRuntime:
        runtime = self.account_nodes[node_id]
        network = self._network_for(node_id)
        host = V2AccountHost(
            node_id=node_id,
            endpoint=runtime.peer.endpoint,
            wallet_db_path=str(runtime.wallet_db_path),
            chain_id=self.chain_id,
            network=network,
            consensus_peer_id=runtime.last_known_consensus_peer_id or self.consensus_ids[0],
            consensus_peer_ids=runtime.last_known_consensus_peer_ids or self.consensus_ids,
            address=runtime.address,
            private_key_pem=runtime.private_key_pem,
            public_key_pem=runtime.public_key_pem,
            state_path=str(runtime.state_path),
        )
        runtime.network = network
        runtime.host = host
        runtime.running = True
        return runtime

    def _snapshot_consensus_runtime(self, runtime: ConsensusNodeRuntime) -> None:
        if runtime.host is None:
            return
        runtime.last_known_height = int(runtime.host.consensus.chain.current_height)
        runtime.last_known_head_hash = runtime.host.consensus.chain.current_block_hash.hex()

    def _snapshot_account_runtime(self, runtime: AccountNodeRuntime) -> None:
        if runtime.host is None:
            return
        wallet = runtime.host.wallet
        runtime.last_known_available_balance = wallet.available_balance()
        runtime.last_known_total_balance = wallet.total_balance()
        runtime.last_known_pending_bundle_count = len(wallet.list_pending_bundles())
        runtime.last_known_receipt_count = len(wallet.list_receipts())
        runtime.last_known_checkpoint_count = len(wallet.list_checkpoints())
        runtime.last_known_consensus_peer_id = runtime.host.consensus_peer_id
        runtime.last_known_consensus_peer_ids = runtime.host.consensus_peer_ids

    def _current_cluster_height(self) -> int:
        heights = [
            runtime.host.consensus.chain.current_height
            for runtime in self.consensus_nodes.values()
            if runtime.running and runtime.host is not None
        ]
        return max(heights, default=0)

    def start(self) -> None:
        if self.active_consensus_ids or self.active_account_ids:
            return
        try:
            for node_id in self.consensus_ids:
                self._build_consensus_runtime(node_id)
            for node_id in self.account_ids:
                self._build_account_runtime(node_id)
            for node_id in self.consensus_ids:
                assert self.consensus_nodes[node_id].network is not None
                self.consensus_nodes[node_id].network.start()
            for node_id in self.account_ids:
                assert self.account_nodes[node_id].network is not None
                self.account_nodes[node_id].network.start()
        except PermissionError as exc:
            self.stop()
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
        except RuntimeError as exc:
            self.stop()
            if isinstance(exc.__cause__, PermissionError):
                raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
            raise
        if not self._genesis_seeded:
            for consensus_id in self.consensus_ids:
                host = self.consensus_nodes[consensus_id].host
                assert host is not None
                for owner_addr, value in self.allocations.items():
                    host.register_genesis_value(owner_addr, value)
            for account_id in self.account_ids:
                host = self.account_nodes[account_id].host
                assert host is not None
                host.register_genesis_value(self.allocations[host.address])
            self._genesis_seeded = True
        self._initial_cluster_height = self._current_cluster_height()
        for runtime in self.account_nodes.values():
            self._snapshot_account_runtime(runtime)
        for runtime in self.consensus_nodes.values():
            self._snapshot_consensus_runtime(runtime)

    def stop(self) -> None:
        for runtime in reversed(tuple(self.account_nodes.values())):
            if runtime.host is not None:
                self._snapshot_account_runtime(runtime)
                try:
                    runtime.host.close()
                finally:
                    runtime.host = None
            if runtime.network is not None:
                try:
                    runtime.network.stop()
                finally:
                    runtime.network = None
            runtime.running = False
        for runtime in reversed(tuple(self.consensus_nodes.values())):
            if runtime.host is not None:
                self._snapshot_consensus_runtime(runtime)
                try:
                    runtime.host.close()
                finally:
                    runtime.host = None
            if runtime.network is not None:
                try:
                    runtime.network.stop()
                finally:
                    runtime.network = None
            runtime.running = False

    def set_selected_proposer(self, consensus_id: str | None) -> None:
        self._forced_proposer_id = str(consensus_id) if consensus_id else None

    def wait_for_cluster_height(self, expected_height: int, *, timeout_sec: float | None = None) -> int:
        running = [
            runtime.host
            for runtime in self.consensus_nodes.values()
            if runtime.running and runtime.host is not None
        ]
        deadline = time.time() + float(timeout_sec or max(3.0, self.profile.network_timeout_sec))
        while time.time() < deadline:
            heights = [host.consensus.chain.current_height for host in running]
            if heights and min(heights) >= expected_height:
                return min(heights)
            time.sleep(0.02)
        heights = [host.consensus.chain.current_height for host in running]
        return min(heights) if heights else 0

    def wait_for_receipt_count(self, account_id: str, expected_count: int, *, timeout_sec: float = 5.0) -> int:
        runtime = self.account_nodes[account_id]
        assert runtime.host is not None
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            count = len(runtime.host.wallet.list_receipts())
            if count >= expected_count:
                return count
            time.sleep(0.02)
        return len(runtime.host.wallet.list_receipts())

    def recover_all_accounts(self) -> dict[str, Any]:
        recovered: dict[str, Any] = {}
        for node_id in self.active_account_ids:
            runtime = self.account_nodes[node_id]
            assert runtime.host is not None
            recovery = runtime.host.recover_network_state()
            self._snapshot_account_runtime(runtime)
            recovered[node_id] = {
                "chain_height": None if recovery.chain_cursor is None else recovery.chain_cursor.height,
                "applied_receipts": recovery.applied_receipts,
                "pending_bundle_count": recovery.pending_bundle_count,
                "receipt_count": recovery.receipt_count,
                "fetched_blocks": len(recovery.fetched_blocks),
            }
        return recovered

    def stop_consensus(self, node_id: str) -> None:
        runtime = self.consensus_nodes[node_id]
        if runtime.host is not None:
            self._snapshot_consensus_runtime(runtime)
            runtime.host.close()
            runtime.host = None
        if runtime.network is not None:
            runtime.network.stop()
            runtime.network = None
        runtime.running = False
        if self._forced_proposer_id == node_id:
            self._forced_proposer_id = None

    def restart_consensus(self, node_id: str) -> tuple[int, ...]:
        if self.consensus_nodes[node_id].running:
            self.stop_consensus(node_id)
        runtime = self._build_consensus_runtime(node_id)
        assert runtime.network is not None
        try:
            runtime.network.start()
        except PermissionError as exc:
            self.stop_consensus(node_id)
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
        except RuntimeError as exc:
            self.stop_consensus(node_id)
            if isinstance(exc.__cause__, PermissionError):
                raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
            raise
        assert runtime.host is not None
        applied = runtime.host.recover_chain_from_consensus_peers()
        self._snapshot_consensus_runtime(runtime)
        return applied

    def restart_account(self, node_id: str) -> dict[str, Any]:
        runtime = self.account_nodes[node_id]
        if runtime.host is not None:
            self._snapshot_account_runtime(runtime)
            runtime.host.close()
            runtime.host = None
        if runtime.network is not None:
            runtime.network.stop()
            runtime.network = None
        runtime.running = False
        runtime = self._build_account_runtime(node_id)
        assert runtime.network is not None
        try:
            runtime.network.start()
        except PermissionError as exc:
            runtime.running = False
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
        except RuntimeError as exc:
            runtime.running = False
            if isinstance(exc.__cause__, PermissionError):
                raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
            raise
        assert runtime.host is not None
        recovery = runtime.host.recover_network_state()
        self._snapshot_account_runtime(runtime)
        return {
            "chain_height": None if recovery.chain_cursor is None else recovery.chain_cursor.height,
            "applied_receipts": recovery.applied_receipts,
            "pending_bundle_count": recovery.pending_bundle_count,
            "receipt_count": recovery.receipt_count,
        }

    def _plan_pairs(self, requested: int) -> list[tuple[str, str] | None]:
        account_ids = list(self.account_ids)
        if requested <= 0:
            return []
        planned: list[tuple[str, str] | None] = []
        if requested >= len(account_ids):
            for index, sender_id in enumerate(account_ids):
                planned.append((sender_id, account_ids[(index + 1) % len(account_ids)]))
        while len(planned) < requested:
            planned.append(None)
        return planned[:requested]

    def _pick_random_pair(self, *, excluded_senders: set[str] | None = None) -> tuple[str, str]:
        excluded = excluded_senders or set()
        spendable = [
            node_id
            for node_id in self.active_account_ids
            if self.account_nodes[node_id].host is not None
            and self.account_nodes[node_id].host.wallet.available_balance() >= int(self.profile.min_amount)
            and node_id not in excluded
        ]
        if not spendable:
            raise RuntimeError("no_spendable_sender_remaining")
        sender_id = self.random.choice(spendable)
        recipient_candidates = [node_id for node_id in self.active_account_ids if node_id != sender_id]
        recipient_id = self.random.choice(recipient_candidates)
        return sender_id, recipient_id

    def _maybe_create_checkpoints(self) -> int:
        created = 0
        for node_id in self.active_account_ids:
            runtime = self.account_nodes[node_id]
            assert runtime.host is not None
            for record in runtime.host.wallet.list_records(LocalValueStatus.VERIFIED_SPENDABLE):
                if not record.witness_v2.confirmed_bundle_chain:
                    continue
                key = (runtime.host.address, record.record_id)
                if key in self._created_checkpoint_record_ids:
                    continue
                runtime.host.wallet.create_exact_checkpoint(record.record_id)
                self._created_checkpoint_record_ids.add(key)
                created += 1
        self._created_checkpoint_count += created
        return created

    def _mark_accounts_touched(self, *node_ids: str) -> None:
        for node_id in node_ids:
            if node_id in self.account_nodes:
                self._accounts_touched.add(node_id)

    def _rotate_sender_primary(self, runtime: AccountNodeRuntime, selected_primary: str, *, rotate_sender_primary: bool) -> None:
        assert runtime.host is not None
        if not rotate_sender_primary:
            return
        ordered = (
            selected_primary,
            *tuple(peer_id for peer_id in runtime.host.consensus_peer_ids if peer_id != selected_primary),
            *tuple(peer_id for peer_id in self.active_consensus_ids if peer_id != selected_primary and peer_id not in runtime.host.consensus_peer_ids),
        )
        runtime.host.set_consensus_peer_ids(tuple(dict.fromkeys(ordered)))

    def _select_primary_for_sender(self, runtime: AccountNodeRuntime, *, rotate_sender_primary: bool) -> str:
        active_consensus_ids = self.active_consensus_ids
        if not active_consensus_ids:
            raise RuntimeError("no_running_consensus_nodes")
        selected_primary = self.random.choice(active_consensus_ids)
        self.set_selected_proposer(selected_primary)
        self._rotate_sender_primary(runtime, selected_primary, rotate_sender_primary=rotate_sender_primary)
        return selected_primary

    def _bind_sender_to_primary(
        self,
        runtime: AccountNodeRuntime,
        *,
        selected_primary: str,
        rotate_sender_primary: bool,
    ) -> str:
        self.set_selected_proposer(selected_primary)
        self._rotate_sender_primary(runtime, selected_primary, rotate_sender_primary=rotate_sender_primary)
        return selected_primary

    def _force_commit_selected_primary(self, selected_primary: str) -> None:
        runtime = self.consensus_nodes[selected_primary]
        assert runtime.host is not None
        deadline = time.time() + max(4.0, self.profile.network_timeout_sec)
        while time.time() < deadline:
            result = runtime.host.drive_auto_mvp_consensus_tick(force=True)
            status = None if not isinstance(result, dict) else str(result.get("status", ""))
            if result is None or status in {"waiting_for_remote_proposer", "accepted_pending_consensus"}:
                time.sleep(0.02)
                continue
            return
        runtime.host.drive_auto_mvp_consensus_tick(force=True)

    def _wait_for_sender_receipt(self, sender_runtime: AccountNodeRuntime, *, expected_seq: int, expected_receipt_count: int):
        assert sender_runtime.host is not None
        self.wait_for_receipt_count(
            sender_runtime.peer.node_id,
            expected_receipt_count,
            timeout_sec=max(6.0, self.profile.network_timeout_sec * 2.0),
        )
        receipt = next(
            (item for item in sender_runtime.host.wallet.list_receipts() if item.seq == expected_seq),
            None,
        )
        if receipt is None:
            sender_runtime.host.recover_network_state()
            self._snapshot_account_runtime(sender_runtime)
            receipt = next(
                (item for item in sender_runtime.host.wallet.list_receipts() if item.seq == expected_seq),
                None,
            )
        return receipt

    def _record_failed(self, payload: dict[str, Any]) -> int:
        self._failed_tx_count += 1
        payload.setdefault("status", "failed")
        payload.setdefault("tx_index", self._next_tx_index)
        self.transactions.append(payload)
        self._next_tx_index += 1
        return 0

    def _record_confirmed_bundle(
        self,
        *,
        sender_id: str,
        txs: tuple[OffChainTx, ...],
        selected_primary: str,
        receipt_height: int | None,
        submit_hash_hex: str,
        tx_hashes: tuple[str, ...],
        created_checkpoints: int,
        start_tx_index: int,
    ) -> int:
        recipient_ids = tuple(self._find_account_id_by_address(tx.recipient_addr) for tx in txs)
        self._confirmed_bundle_count += 1
        if len(txs) > 1:
            self._multi_tx_bundle_count += 1
        for tx, recipient_id in zip(txs, recipient_ids):
            self._confirmed_tx_count += 1
            if len(tx.value_list) > 1:
                self._multi_value_tx_count += 1
            self.account_nodes[sender_id].send_count += 1
            self.account_nodes[recipient_id].receive_count += 1
            self._mark_accounts_touched(sender_id, recipient_id)
        self.transactions.append(
            {
                "tx_index": start_tx_index,
                "status": "confirmed",
                "sender_node_id": sender_id,
                "recipient_node_ids": list(recipient_ids),
                "sender_addr": self.account_nodes[sender_id].address,
                "recipient_addrs": [tx.recipient_addr for tx in txs],
                "selected_primary": selected_primary,
                "bundle_tx_count": len(txs),
                "bundle_amount": sum(sum(value.size for value in tx.value_list) for tx in txs),
                "tx_hashes": list(tx_hashes),
                "submit_hash": submit_hash_hex,
                "receipt_height": receipt_height,
                "created_checkpoints": created_checkpoints,
                "multi_value_tx_count_in_bundle": sum(1 for tx in txs if len(tx.value_list) > 1),
            }
        )
        self._next_tx_index += len(txs)
        return len(txs)

    def _would_cross_checkpoint_boundary(self, previous_confirmed: int, added_count: int) -> bool:
        if self.profile.checkpoint_every <= 0:
            return False
        next_confirmed = previous_confirmed + int(added_count)
        checkpoint_every = int(self.profile.checkpoint_every)
        return (previous_confirmed // checkpoint_every) < (next_confirmed // checkpoint_every)

    def _run_pending_scheduled_events(self) -> None:
        while self._scheduled_event_index < len(self.profile.scheduled_events):
            event = self.profile.scheduled_events[self._scheduled_event_index]
            if self._confirmed_tx_count < int(event.after_confirmed_tx):
                break
            self._execute_scheduled_event(event)
            self._scheduled_event_index += 1

    def _execute_scheduled_event(self, event: ScheduledEvent) -> None:
        if event.action == "restart_consensus":
            if event.target_id:
                self.restart_consensus(event.target_id)
            return
        if event.action == "stop_consensus":
            if event.target_id:
                self.stop_consensus(event.target_id)
            return
        if event.action == "recover_all_accounts":
            self.recover_all_accounts()
            return
        if event.action == "rotate_accounts_to_peer":
            preferred = event.target_id or (self.active_consensus_ids[-1] if self.active_consensus_ids else "")
            if preferred:
                self._set_all_accounts_preferred_peer(preferred)
            return
        raise ValueError(f"unsupported_scheduled_event:{event.action}")

    def _set_all_accounts_preferred_peer(self, preferred_peer_id: str) -> None:
        ordered = (preferred_peer_id, *tuple(peer_id for peer_id in self.consensus_ids if peer_id != preferred_peer_id))
        for node_id in self.active_account_ids:
            runtime = self.account_nodes[node_id]
            assert runtime.host is not None
            runtime.host.set_consensus_peer_ids(ordered)
            self._snapshot_account_runtime(runtime)

    def _submit_single_payment(
        self,
        sender_id: str,
        recipient_id: str,
        *,
        amount: int,
        rotate_sender_primary: bool = True,
        selected_primary: str | None = None,
        allow_retry: bool = True,
    ) -> int:
        sender_runtime = self.account_nodes[sender_id]
        recipient_runtime = self.account_nodes[recipient_id]
        assert sender_runtime.host is not None
        assert recipient_runtime.host is not None

        selected_primary = (
            self._bind_sender_to_primary(
                sender_runtime,
                selected_primary=selected_primary,
                rotate_sender_primary=rotate_sender_primary,
            )
            if selected_primary is not None
            else self._select_primary_for_sender(sender_runtime, rotate_sender_primary=rotate_sender_primary)
        )
        expected_height = self._current_cluster_height() + 1
        expected_seq = sender_runtime.host.wallet.next_sequence()
        expected_receipt_count = len(sender_runtime.host.wallet.list_receipts()) + 1
        start_tx_index = self._next_tx_index
        try:
            payment = sender_runtime.host.submit_payment(
                recipient_id,
                amount=amount,
                tx_time=start_tx_index,
                anti_spam_nonce=self.random.randrange(1, 1 << 31),
            )
        except Exception as exc:
            if allow_retry and "consensus_phase_failed:" in str(exc):
                time.sleep(0.2)
                try:
                    sender_runtime.host.recover_network_state()
                except Exception:
                    pass
                return self._submit_single_payment(
                    sender_id,
                    recipient_id,
                    amount=amount,
                    rotate_sender_primary=rotate_sender_primary,
                    selected_primary=selected_primary,
                    allow_retry=False,
                )
            return self._record_failed(
                {
                    "status": "failed_submit",
                    "error": str(exc),
                    "sender_node_id": sender_id,
                    "recipient_node_id": recipient_id,
                    "selected_primary": selected_primary,
                    "amount": amount,
                }
            )

        self.wait_for_cluster_height(expected_height)
        receipt = self._wait_for_sender_receipt(
            sender_runtime,
            expected_seq=expected_seq,
            expected_receipt_count=expected_receipt_count,
        )
        if receipt is None and payment.receipt_height is None:
            return self._record_failed(
                {
                    "status": "missing_receipt",
                    "sender_node_id": sender_id,
                    "recipient_node_id": recipient_id,
                    "selected_primary": selected_primary,
                    "amount": amount,
                    "tx_hash": payment.tx_hash_hex,
                    "submit_hash": payment.submit_hash_hex,
                }
            )

        previous_confirmed = self._confirmed_tx_count
        created_checkpoints = self._maybe_create_checkpoints() if self._would_cross_checkpoint_boundary(previous_confirmed, 1) else 0
        return self._record_confirmed_bundle(
            sender_id=sender_id,
            txs=(
                OffChainTx(
                    sender_addr=sender_runtime.address,
                    recipient_addr=recipient_runtime.address,
                    value_list=(
                        ValueRange(0, amount - 1),
                    ),
                    tx_local_index=0,
                    tx_time=start_tx_index,
                ),
            ),
            selected_primary=selected_primary,
            receipt_height=payment.receipt_height or (None if receipt is None else receipt.header_lite.height),
            submit_hash_hex=payment.submit_hash_hex,
            tx_hashes=(payment.tx_hash_hex,),
            created_checkpoints=created_checkpoints,
            start_tx_index=start_tx_index,
        )

    def _free_segments(self, source: ValueRange, used: tuple[ValueRange, ...]) -> tuple[ValueRange, ...]:
        overlaps = tuple(
            sorted(
                (item for item in used if source.intersects(item)),
                key=lambda item: (item.begin, item.end),
            )
        )
        if not overlaps:
            return (source,)
        return tuple(segment for segment, is_used in _partition_range(source, overlaps) if not is_used)

    def _allocate_bundle_value_groups(self, sender_id: str, amounts: tuple[int, ...]) -> tuple[tuple[ValueRange, ...], ...]:
        sender_runtime = self.account_nodes[sender_id]
        assert sender_runtime.host is not None
        sender_runtime.host.wallet.reload_state()
        records = sender_runtime.host.wallet.list_records(LocalValueStatus.VERIFIED_SPENDABLE)
        used: list[ValueRange] = []
        groups: list[tuple[ValueRange, ...]] = []
        for amount in amounts:
            remaining = int(amount)
            current: list[ValueRange] = []
            for record in records:
                for segment in self._free_segments(record.value, tuple(used)):
                    if remaining <= 0:
                        break
                    take = min(segment.size, remaining)
                    if take <= 0:
                        continue
                    chosen = ValueRange(segment.begin, segment.begin + take - 1)
                    current.append(chosen)
                    used.append(chosen)
                    remaining -= take
                if remaining <= 0:
                    break
            if remaining > 0:
                raise ValueError("insufficient_balance_for_bundle")
            groups.append(tuple(sorted(current, key=lambda item: (item.begin, item.end))))
        return tuple(groups)

    def _submit_custom_bundle(
        self,
        sender_id: str,
        *,
        tx_groups: tuple[tuple[str, tuple[ValueRange, ...]], ...],
        rotate_sender_primary: bool = True,
        selected_primary: str | None = None,
        allow_retry: bool = True,
    ) -> int:
        sender_runtime = self.account_nodes[sender_id]
        assert sender_runtime.host is not None
        sender_runtime.host.wallet.reload_state()
        selected_primary = (
            self._bind_sender_to_primary(
                sender_runtime,
                selected_primary=selected_primary,
                rotate_sender_primary=rotate_sender_primary,
            )
            if selected_primary is not None
            else self._select_primary_for_sender(sender_runtime, rotate_sender_primary=rotate_sender_primary)
        )
        expected_height = self._current_cluster_height() + 1
        expected_seq = sender_runtime.host.wallet.next_sequence()
        expected_receipt_count = len(sender_runtime.host.wallet.list_receipts()) + 1
        start_tx_index = self._next_tx_index
        tx_list = tuple(
            OffChainTx(
                sender_addr=sender_runtime.address,
                recipient_addr=self.account_nodes[recipient_id].address,
                value_list=value_list,
                tx_local_index=index,
                tx_time=start_tx_index,
            )
            for index, (recipient_id, value_list) in enumerate(tx_groups)
        )
        try:
            submission, context = sender_runtime.host.wallet.build_bundle(
                tx_list=tx_list,
                private_key_pem=sender_runtime.private_key_pem,
                public_key_pem=sender_runtime.public_key_pem,
                chain_id=self.chain_id,
                seq=expected_seq,
                expiry_height=1_000_000,
                fee=0,
                anti_spam_nonce=self.random.randrange(1, 1 << 31),
                created_at=start_tx_index,
            )
            sender_runtime.host._refresh_best_peer_if_preferred_stale()
            response = sender_runtime.host._send_to_consensus(MSG_BUNDLE_SUBMIT, {"submission": submission})
            if isinstance(response, dict) and response.get("ok") is False:
                error = str(response.get("error", "bundle_submit_failed"))
                if error == "bundle seq is not currently executable":
                    retried = sender_runtime.host._retry_on_missing_after_refresh(
                        MSG_BUNDLE_SUBMIT,
                        {"submission": submission},
                    )
                    if not isinstance(retried, dict) or retried.get("ok") is False:
                        raise ValueError(error)
                else:
                    raise ValueError(error)
        except Exception as exc:
            try:
                sender_runtime.host.wallet.rollback_pending_bundle(expected_seq)
            except Exception:
                pass
            if allow_retry and "consensus_phase_failed:" in str(exc):
                time.sleep(0.2)
                try:
                    sender_runtime.host.recover_network_state()
                except Exception:
                    pass
                return self._submit_custom_bundle(
                    sender_id,
                    tx_groups=tx_groups,
                    rotate_sender_primary=rotate_sender_primary,
                    selected_primary=selected_primary,
                    allow_retry=False,
                )
            return self._record_failed(
                {
                    "status": "failed_submit",
                    "error": str(exc),
                    "sender_node_id": sender_id,
                    "recipient_node_ids": [recipient_id for recipient_id, _ in tx_groups],
                    "selected_primary": selected_primary,
                    "bundle_tx_count": len(tx_groups),
                }
            )

        self.wait_for_cluster_height(expected_height)
        receipt = self._wait_for_sender_receipt(
            sender_runtime,
            expected_seq=expected_seq,
            expected_receipt_count=expected_receipt_count,
        )
        if receipt is None:
            return self._record_failed(
                {
                    "status": "missing_receipt",
                    "sender_node_id": sender_id,
                    "recipient_node_ids": [recipient_id for recipient_id, _ in tx_groups],
                    "selected_primary": selected_primary,
                    "bundle_tx_count": len(tx_groups),
                    "submit_hash": submission.envelope.bundle_hash.hex(),
                }
            )

        previous_confirmed = self._confirmed_tx_count
        created_checkpoints = self._maybe_create_checkpoints() if self._would_cross_checkpoint_boundary(previous_confirmed, len(tx_list)) else 0
        return self._record_confirmed_bundle(
            sender_id=sender_id,
            txs=tx_list,
            selected_primary=selected_primary,
            receipt_height=receipt.header_lite.height,
            submit_hash_hex=submission.envelope.bundle_hash.hex(),
            tx_hashes=tuple(sender_runtime.host._tx_hash_hex(tx) for tx in tx_list),
            created_checkpoints=created_checkpoints,
            start_tx_index=start_tx_index,
        )

    def _submit_single_payment_nowait(
        self,
        sender_id: str,
        recipient_id: str,
        *,
        amount: int,
        selected_primary: str,
        rotate_sender_primary: bool = True,
    ) -> PendingBatchSubmission | None:
        sender_runtime = self.account_nodes[sender_id]
        recipient_runtime = self.account_nodes[recipient_id]
        assert sender_runtime.host is not None
        assert recipient_runtime.host is not None
        self._bind_sender_to_primary(
            sender_runtime,
            selected_primary=selected_primary,
            rotate_sender_primary=rotate_sender_primary,
        )
        expected_seq = sender_runtime.host.wallet.next_sequence()
        expected_receipt_count = len(sender_runtime.host.wallet.list_receipts()) + 1
        start_tx_index = self._next_tx_index
        try:
            payment = sender_runtime.host.submit_payment(
                recipient_id,
                amount=amount,
                tx_time=start_tx_index,
                anti_spam_nonce=self.random.randrange(1, 1 << 31),
            )
        except Exception as exc:
            self._record_failed(
                {
                    "status": "failed_submit",
                    "error": str(exc),
                    "sender_node_id": sender_id,
                    "recipient_node_id": recipient_id,
                    "selected_primary": selected_primary,
                    "amount": amount,
                }
            )
            return None
        return PendingBatchSubmission(
            sender_id=sender_id,
            txs=(
                OffChainTx(
                    sender_addr=sender_runtime.address,
                    recipient_addr=recipient_runtime.address,
                    value_list=(ValueRange(0, amount - 1),),
                    tx_local_index=0,
                    tx_time=start_tx_index,
                ),
            ),
            selected_primary=selected_primary,
            expected_seq=expected_seq,
            expected_receipt_count=expected_receipt_count,
            submit_hash_hex=payment.submit_hash_hex,
            tx_hashes=(payment.tx_hash_hex,),
            start_tx_index=start_tx_index,
        )

    def _flush_pending_batch(
        self,
        pending: list[PendingBatchSubmission],
        *,
        expected_height: int,
        selected_primary: str,
    ) -> int:
        if not pending:
            return 0
        self._force_commit_selected_primary(selected_primary)
        self.wait_for_cluster_height(expected_height)
        self.recover_all_accounts()
        progressed = 0
        for item in pending:
            sender_runtime = self.account_nodes[item.sender_id]
            receipt = self._wait_for_sender_receipt(
                sender_runtime,
                expected_seq=item.expected_seq,
                expected_receipt_count=item.expected_receipt_count,
            )
            if receipt is None:
                progressed += self._record_failed(
                    {
                        "status": "missing_receipt",
                        "sender_node_id": item.sender_id,
                        "recipient_node_ids": [self._find_account_id_by_address(tx.recipient_addr) for tx in item.txs],
                        "selected_primary": item.selected_primary,
                        "bundle_tx_count": len(item.txs),
                        "submit_hash": item.submit_hash_hex,
                    }
                )
                continue
            previous_confirmed = self._confirmed_tx_count
            created_checkpoints = (
                self._maybe_create_checkpoints()
                if self._would_cross_checkpoint_boundary(previous_confirmed, len(item.txs))
                else 0
            )
            progressed += self._record_confirmed_bundle(
                sender_id=item.sender_id,
                txs=item.txs,
                selected_primary=item.selected_primary,
                receipt_height=receipt.header_lite.height,
                submit_hash_hex=item.submit_hash_hex,
                tx_hashes=item.tx_hashes,
                created_checkpoints=created_checkpoints,
                start_tx_index=item.start_tx_index,
            )
        return progressed

    def _submit_multi_tx_bundle(self, *, remaining_txs: int, rotate_sender_primary: bool = True) -> int:
        preferred_size = 2 if self._multi_tx_bundle_toggle % 2 == 0 else min(3, int(self.profile.max_txs_per_bundle))
        bundle_size = min(preferred_size, int(self.profile.max_txs_per_bundle), remaining_txs)
        if bundle_size == 3 and remaining_txs == 4:
            bundle_size = 2
        if bundle_size <= 1:
            sender_id, recipient_id = self._pick_random_pair()
            sender_runtime = self.account_nodes[sender_id]
            assert sender_runtime.host is not None
            available = sender_runtime.host.wallet.available_balance()
            amount = self.random.randint(int(self.profile.min_amount), min(int(self.profile.max_amount), available))
            return self._submit_single_payment(
                sender_id,
                recipient_id,
                amount=amount,
                rotate_sender_primary=rotate_sender_primary,
            )

        fixed_amounts = (20, 30, 40)[:bundle_size]
        required_total = sum(fixed_amounts)
        spendable_senders = [
            node_id
            for node_id in self.active_account_ids
            if self.account_nodes[node_id].host is not None
            and self.account_nodes[node_id].host.wallet.available_balance() >= required_total
        ]
        if not spendable_senders:
            return 0
        sender_id = self.random.choice(spendable_senders)
        recipient_ids = list(self.active_account_ids)
        recipient_ids.remove(sender_id)
        self.random.shuffle(recipient_ids)
        recipient_ids = recipient_ids[:bundle_size]
        groups = self._allocate_bundle_value_groups(sender_id, fixed_amounts)
        tx_groups = tuple((recipient_id, groups[index]) for index, recipient_id in enumerate(recipient_ids))
        self._multi_tx_bundle_toggle += 1
        return self._submit_custom_bundle(
            sender_id,
            tx_groups=tx_groups,
            rotate_sender_primary=rotate_sender_primary,
        )

    def _run_multi_value_cycle(self, *, rotate_sender_primary: bool = True) -> int:
        if len(self.account_ids) < 10:
            return 0
        composers = self.account_ids[:5]
        support = self.account_ids[5:10]
        cycle = self._multi_value_cycle_index
        composer_id = composers[cycle % len(composers)]
        sink_id = support[cycle % len(support)]
        recipient_id = support[(cycle + 1) % len(support)]
        donor_ids = (
            support[(cycle + 2) % len(support)],
            support[(cycle + 3) % len(support)],
            support[(cycle + 4) % len(support)],
        )
        progressed = 0
        composer_runtime = self.account_nodes[composer_id]
        assert composer_runtime.host is not None
        composer_runtime.host.wallet.reload_state()
        available = composer_runtime.host.wallet.available_balance()
        if composer_id not in self._multi_value_seeded_composers and available > 0:
            progressed += self._submit_single_payment(
                composer_id,
                sink_id,
                amount=available,
                rotate_sender_primary=rotate_sender_primary,
            )
            self._multi_value_seeded_composers.add(composer_id)
        fragment_amounts = (30, 40, 50)
        for donor_id, amount in zip(donor_ids, fragment_amounts):
            progressed += self._submit_single_payment(
                donor_id,
                composer_id,
                amount=amount,
                rotate_sender_primary=rotate_sender_primary,
            )
        composer_runtime.host.wallet.reload_state()
        selected = composer_runtime.host.wallet.select_payment_ranges(sum(fragment_amounts))
        tx_groups = ((recipient_id, selected),)
        progressed += self._submit_custom_bundle(
            composer_id,
            tx_groups=tx_groups,
            rotate_sender_primary=rotate_sender_primary,
        )
        self._multi_value_cycle_index += 1
        return progressed

    def _next_multi_value_cycle_cost(self) -> int:
        if len(self.account_ids) < 10:
            return 1
        composers = self.account_ids[:5]
        composer_id = composers[self._multi_value_cycle_index % len(composers)]
        return 4 if composer_id in self._multi_value_seeded_composers else 5

    def _run_split_recombine_loop(self, *, rotate_sender_primary: bool = True) -> int:
        if self._split_loop_completed or len(self.account_ids) < 6:
            sender_id, recipient_id = self._pick_random_pair()
            sender_runtime = self.account_nodes[sender_id]
            assert sender_runtime.host is not None
            amount = min(int(self.profile.max_amount), sender_runtime.host.wallet.available_balance())
            amount = max(amount, int(self.profile.min_amount))
            return self._submit_single_payment(
                sender_id,
                recipient_id,
                amount=amount,
                rotate_sender_primary=rotate_sender_primary,
            )
        alice_id = self.account_ids[0]
        bob_id = self.account_ids[1]
        carol_id = self.account_ids[2]
        sink_one_id = self.account_ids[4]
        sink_two_id = self.account_ids[5]
        alice_value = self.allocations[self.account_nodes[alice_id].address]
        bob_value = self.allocations[self.account_nodes[bob_id].address]
        carol_value = self.allocations[self.account_nodes[carol_id].address]
        progressed = 0
        progressed += self._submit_single_payment(bob_id, sink_one_id, amount=bob_value.size, rotate_sender_primary=rotate_sender_primary)
        progressed += self._submit_single_payment(carol_id, sink_two_id, amount=carol_value.size, rotate_sender_primary=rotate_sender_primary)
        progressed += self._submit_single_payment(alice_id, bob_id, amount=alice_value.size, rotate_sender_primary=rotate_sender_primary)
        progressed += self._submit_single_payment(bob_id, carol_id, amount=alice_value.size, rotate_sender_primary=rotate_sender_primary)
        bob_host = self.account_nodes[bob_id].host
        assert bob_host is not None
        archived = [
            record
            for record in bob_host.wallet.list_records()
            if record.local_status == LocalValueStatus.ARCHIVED and record.value == alice_value
        ]
        if archived:
            target = max(archived, key=lambda item: item.witness_v2.confirmed_bundle_chain[0].receipt.seq)
            bob_host.wallet.create_exact_checkpoint(target.record_id)
        progressed += self._submit_single_payment(carol_id, bob_id, amount=alice_value.size, rotate_sender_primary=rotate_sender_primary)
        progressed += self._submit_single_payment(bob_id, alice_id, amount=alice_value.size // 2, rotate_sender_primary=rotate_sender_primary)
        self._split_loop_completed = True
        return progressed

    def _run_single_value_random_step(self, *, planned_pair: tuple[str, str] | None = None, rotate_sender_primary: bool = True) -> int:
        if planned_pair is None:
            try:
                sender_id, recipient_id = self._pick_random_pair()
            except RuntimeError:
                return 0
        else:
            sender_id, recipient_id = planned_pair
        sender_runtime = self.account_nodes[sender_id]
        assert sender_runtime.host is not None
        available = sender_runtime.host.wallet.available_balance()
        if available < int(self.profile.min_amount):
            sender_id, recipient_id = self._pick_random_pair()
            sender_runtime = self.account_nodes[sender_id]
            assert sender_runtime.host is not None
            available = sender_runtime.host.wallet.available_balance()
        amount = self.random.randint(int(self.profile.min_amount), min(int(self.profile.max_amount), available))
        return self._submit_single_payment(
            sender_id,
            recipient_id,
            amount=amount,
            rotate_sender_primary=rotate_sender_primary,
        )

    def _run_single_value_random_batch(
        self,
        *,
        remaining_txs: int,
        planned_pairs: list[tuple[str, str] | None],
        rotate_sender_primary: bool,
    ) -> int:
        active_consensus_ids = self.active_consensus_ids
        if not active_consensus_ids:
            return 0
        batch_size = max(1, min(int(self.profile.target_submissions_per_round), remaining_txs))
        selected_primary = self.random.choice(active_consensus_ids)
        expected_height = self._current_cluster_height() + 1
        pending: list[PendingBatchSubmission] = []
        used_senders: set[str] = set()
        for planned_pair in planned_pairs[:batch_size]:
            try:
                if planned_pair is None:
                    sender_id, recipient_id = self._pick_random_pair(excluded_senders=used_senders)
                else:
                    sender_id, recipient_id = planned_pair
                    if sender_id in used_senders:
                        sender_id, recipient_id = self._pick_random_pair(excluded_senders=used_senders)
                sender_runtime = self.account_nodes[sender_id]
                assert sender_runtime.host is not None
                available = sender_runtime.host.wallet.available_balance()
                if available < int(self.profile.min_amount):
                    sender_id, recipient_id = self._pick_random_pair(excluded_senders=used_senders)
                    sender_runtime = self.account_nodes[sender_id]
                    assert sender_runtime.host is not None
                    available = sender_runtime.host.wallet.available_balance()
                amount = self.random.randint(int(self.profile.min_amount), min(int(self.profile.max_amount), available))
                item = self._submit_single_payment_nowait(
                    sender_id,
                    recipient_id,
                    amount=amount,
                    selected_primary=selected_primary,
                    rotate_sender_primary=rotate_sender_primary,
                )
                if item is not None:
                    pending.append(item)
                    used_senders.add(sender_id)
            except RuntimeError:
                break
        return self._flush_pending_batch(
            pending,
            expected_height=expected_height,
            selected_primary=selected_primary,
        )

    def _run_shape_step(
        self,
        *,
        remaining_txs: int,
        requested_txs: int,
        planned_pair: tuple[str, str] | None,
        rotate_sender_primary: bool,
        confirmed_before: int,
    ) -> int:
        mode = self.profile.tx_shape_mode
        if mode == "single_value_random":
            return self._run_single_value_random_step(
                planned_pair=planned_pair,
                rotate_sender_primary=rotate_sender_primary,
            )
        if mode == "multi_value_compose":
            if self._multi_value_cycle_index < 10 and remaining_txs >= self._next_multi_value_cycle_cost():
                return self._run_multi_value_cycle(rotate_sender_primary=rotate_sender_primary)
            return self._run_single_value_random_step(
                planned_pair=planned_pair,
                rotate_sender_primary=rotate_sender_primary,
            )
        if mode == "multi_tx_bundle":
            return self._submit_multi_tx_bundle(
                remaining_txs=remaining_txs,
                rotate_sender_primary=rotate_sender_primary,
            )
        if mode == "split_recombine_loop":
            return self._run_split_recombine_loop(rotate_sender_primary=rotate_sender_primary)
        if mode == "mixed":
            local_confirmed = self._confirmed_tx_count - confirmed_before
            if local_confirmed < max(12, requested_txs // 3) and remaining_txs >= self._next_multi_value_cycle_cost():
                return self._run_multi_value_cycle(rotate_sender_primary=rotate_sender_primary)
            if local_confirmed < max(24, (requested_txs * 2) // 3):
                return self._submit_multi_tx_bundle(
                    remaining_txs=remaining_txs,
                    rotate_sender_primary=rotate_sender_primary,
                )
            return self._run_single_value_random_step(
                planned_pair=planned_pair,
                rotate_sender_primary=rotate_sender_primary,
            )
        raise ValueError(f"unsupported_tx_shape_mode:{mode}")

    def _find_account_id_by_address(self, address: str) -> str:
        for node_id, runtime in self.account_nodes.items():
            if runtime.address == address:
                return node_id
        raise ValueError(f"unknown_account_address:{address}")

    def run_random_rounds(self, tx_count: int | None = None, *, rotate_sender_primary: bool = True) -> dict[str, Any]:
        requested = int(self.profile.tx_count if tx_count is None else tx_count)
        confirmed_before = self._confirmed_tx_count
        failed_before = self._failed_tx_count
        planned = self._plan_pairs(min(requested, len(self.account_ids)))
        planned_index = 0
        no_progress_rounds = 0
        while self._confirmed_tx_count - confirmed_before < requested:
            remaining = requested - (self._confirmed_tx_count - confirmed_before)
            if self.profile.tx_shape_mode == "single_value_random" and int(self.profile.target_submissions_per_round) > 1:
                batch_size = min(int(self.profile.target_submissions_per_round), remaining)
                planned_pairs = [
                    planned[index] if index < len(planned) else None
                    for index in range(planned_index, planned_index + batch_size)
                ]
                progressed = self._run_single_value_random_batch(
                    remaining_txs=remaining,
                    planned_pairs=planned_pairs,
                    rotate_sender_primary=rotate_sender_primary,
                )
                planned_index += batch_size
            else:
                planned_pair = planned[planned_index] if planned_index < len(planned) else None
                progressed = self._run_shape_step(
                    remaining_txs=remaining,
                    requested_txs=requested,
                    planned_pair=planned_pair,
                    rotate_sender_primary=rotate_sender_primary,
                    confirmed_before=confirmed_before,
                )
                planned_index += 1
            if progressed <= 0:
                no_progress_rounds += 1
                if no_progress_rounds >= 3:
                    break
            else:
                no_progress_rounds = 0
            self._run_pending_scheduled_events()
        self.recover_all_accounts()
        for runtime in self.account_nodes.values():
            if runtime.running:
                self._snapshot_account_runtime(runtime)
        for runtime in self.consensus_nodes.values():
            if runtime.running:
                self._snapshot_consensus_runtime(runtime)
        return {
            "tx_requested": requested,
            "tx_confirmed": self._confirmed_tx_count - confirmed_before,
            "tx_failed": self._failed_tx_count - failed_before,
            "final_height": max(
                (item["height"] for item in self.snapshot()["consensus"].values() if item.get("running", True)),
                default=0,
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        consensus_payload: dict[str, Any] = {}
        for node_id, runtime in self.consensus_nodes.items():
            if runtime.running and runtime.host is not None:
                self._snapshot_consensus_runtime(runtime)
            consensus_payload[node_id] = {
                "height": runtime.last_known_height,
                "head_hash": runtime.last_known_head_hash,
                "running": runtime.running,
            }

        accounts_payload: dict[str, Any] = {}
        total_supply = 0
        for node_id, runtime in self.account_nodes.items():
            if runtime.running and runtime.host is not None:
                self._snapshot_account_runtime(runtime)
            total_supply += runtime.last_known_total_balance
            accounts_payload[node_id] = {
                "address": runtime.address,
                "available_balance": runtime.last_known_available_balance,
                "total_balance": runtime.last_known_total_balance,
                "pending_bundle_count": runtime.last_known_pending_bundle_count,
                "receipt_count": runtime.last_known_receipt_count,
                "checkpoint_count": runtime.last_known_checkpoint_count,
                "consensus_peer_id": runtime.last_known_consensus_peer_id,
                "consensus_peer_ids": list(runtime.last_known_consensus_peer_ids),
                "send_count": runtime.send_count,
                "receive_count": runtime.receive_count,
                "running": runtime.running,
            }

        max_height = max((item["height"] for item in consensus_payload.values() if item.get("running", True)), default=0)
        return {
            "profile": self.profile.name,
            "chain_id": self.chain_id,
            "consensus": consensus_payload,
            "accounts": accounts_payload,
            "confirmed_tx_count": self._confirmed_tx_count,
            "failed_tx_count": self._failed_tx_count,
            "bundle_count": self._confirmed_bundle_count,
            "multi_value_tx_count": self._multi_value_tx_count,
            "multi_tx_bundle_count": self._multi_tx_bundle_count,
            "created_checkpoint_count": self._created_checkpoint_count,
            "height_delta": max(0, max_height - self._initial_cluster_height),
            "total_supply": total_supply,
            "accounts_touched": sorted(self._accounts_touched),
            "transactions": list(self.transactions),
            "running_consensus_ids": list(self.active_consensus_ids),
            "running_account_ids": list(self.active_account_ids),
        }


def build_host_cluster(profile: LocalTCPSimProfile, root_dir: str) -> LocalTCPHostCluster:
    try:
        return LocalTCPHostCluster(profile=profile, root_dir=root_dir)
    except PermissionError as exc:
        raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
