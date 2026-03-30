from __future__ import annotations

import json
import secrets
import signal
import socket
import subprocess
import sys
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from EZ_V2.control import read_state_file
from EZ_V2.network_transport import TCPNetworkTransport
from EZ_V2.networking import MSG_TRANSFER_PACKAGE_DELIVER, NetworkEnvelope, PeerInfo, with_v2_features
from EZ_V2.transport_peer import TransportPeerNetwork
from EZ_V2.values import LocalValueStatus
from EZ_V2.wallet import WalletAccountV2

from .profiles import APP_USERFLOW_PROFILE, LocalTCPSimProfile


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


@dataclass(frozen=True)
class ConsensusDaemonSpec:
    node_id: str
    endpoint: str
    root_dir: Path
    state_file: Path
    stdout_log: Path
    stderr_log: Path


@dataclass(frozen=True)
class AccountDaemonSpec:
    name: str
    endpoint: str
    root_dir: Path
    state_file: Path
    stdout_log: Path
    stderr_log: Path
    wallet_dir: Path
    wallet_file: Path
    address: str


class LocalTCPDaemonCluster:
    def __init__(self, *, root_dir: str, profile: LocalTCPSimProfile = APP_USERFLOW_PROFILE):
        try:
            self.profile = profile
            self.root_dir = Path(root_dir)
            self.root_dir.mkdir(parents=True, exist_ok=True)
            self.project_root = Path(__file__).resolve().parents[2]
            self.chain_id = 30000 + len(profile.account_names)
            self.password = "pw123"
            self._shared_mvp_cluster_secret_hex = secrets.token_hex(32)
            self.consensus_processes: dict[str, subprocess.Popen[str]] = {}
            self.account_processes: dict[str, subprocess.Popen[str]] = {}

            if not profile.account_names:
                raise ValueError("app_userflow_profile_requires_account_names")

            self.consensus_specs: dict[str, ConsensusDaemonSpec] = {}
            for index in range(profile.consensus_count):
                node_id = f"consensus-{index}"
                self.consensus_specs[node_id] = ConsensusDaemonSpec(
                    node_id=node_id,
                    endpoint=f"127.0.0.1:{_reserve_port()}",
                    root_dir=self.root_dir / node_id,
                    state_file=self.root_dir / node_id / "state.json",
                    stdout_log=self.root_dir / node_id / "stdout.log",
                    stderr_log=self.root_dir / node_id / "stderr.log",
                )

            self.wallet_stores: dict[str, WalletStore] = {}
            self.engines: dict[str, TxEngine] = {}
            self.account_specs: dict[str, AccountDaemonSpec] = {}
            for name in profile.account_names:
                wallet_dir = self.root_dir / "wallets" / name
                wallet_dir.mkdir(parents=True, exist_ok=True)
                store = WalletStore(str(wallet_dir))
                if not (wallet_dir / "wallet.json").exists():
                    store.create_wallet(password=self.password, name=name)
                address = store.summary(protocol_version="v2").address
                self.wallet_stores[name] = store
                self.engines[name] = TxEngine(
                    str(wallet_dir),
                    max_tx_amount=10_000,
                    protocol_version="v2",
                    v2_chain_id=self.chain_id,
                    v2_network_timeout_sec=profile.network_timeout_sec,
                )
                self.account_specs[name] = AccountDaemonSpec(
                    name=name,
                    endpoint=f"127.0.0.1:{_reserve_port()}",
                    root_dir=self.root_dir / name,
                    state_file=self.root_dir / name / "state.json",
                    stdout_log=self.root_dir / name / "stdout.log",
                    stderr_log=self.root_dir / name / "stderr.log",
                    wallet_dir=wallet_dir,
                    wallet_file=wallet_dir / "wallet.json",
                    address=address,
                )

            self.genesis_allocations_file = self.root_dir / "genesis_allocations.json"
            alice_name = profile.account_names[0]
            self.genesis_allocations_file.write_text(
                json.dumps(
                    [
                        {
                            "owner_addr": self.account_specs[alice_name].address,
                            "begin": 0,
                            "end": 999,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            for spec in self.consensus_specs.values():
                spec.root_dir.mkdir(parents=True, exist_ok=True)
                (
                    spec.root_dir / f".ezchain_v2_mvp_cluster_secret.chain{int(self.chain_id)}.hex"
                ).write_text(self._shared_mvp_cluster_secret_hex, encoding="utf-8")
        except PermissionError as exc:
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc

    def _open_logs(self, stdout_log: Path, stderr_log: Path) -> tuple[Any, Any]:
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        return (
            stdout_log.open("w", encoding="utf-8"),
            stderr_log.open("w", encoding="utf-8"),
        )

    @staticmethod
    def _peer_id_for_address(address: str) -> str:
        return f"account-{str(address)[-8:]}"

    def _is_bind_not_permitted(self, stderr_log: Path) -> bool:
        if not stderr_log.exists():
            return False
        try:
            payload = stderr_log.read_text(encoding="utf-8")
        except Exception:
            return False
        return "Operation not permitted" in payload or "PermissionError" in payload

    def _build_consensus_cmd(self, spec: ConsensusDaemonSpec) -> list[str]:
        cmd = [
            sys.executable,
            str(self.project_root / "run_ez_v2_tcp_consensus.py"),
            "--root-dir",
            str(spec.root_dir),
            "--state-file",
            str(spec.state_file),
            "--chain-id",
            str(self.chain_id),
            "--node-id",
            spec.node_id,
            "--endpoint",
            spec.endpoint,
            "--consensus-mode",
            "mvp",
            "--auto-run-mvp-consensus",
            "--auto-run-mvp-consensus-window-sec",
            "0.2",
            "--network-timeout-sec",
            str(self.profile.network_timeout_sec),
            "--genesis-allocations-file",
            str(self.genesis_allocations_file),
        ]
        for peer_spec in self.consensus_specs.values():
            cmd.extend(["--peer", f"{peer_spec.node_id}={peer_spec.endpoint}"])
        for validator_id in self.consensus_specs:
            cmd.extend(["--validator-id", validator_id])
        return cmd

    def _build_account_cmd(self, spec: AccountDaemonSpec) -> list[str]:
        primary_consensus = next(iter(self.consensus_specs.values()))
        return [
            sys.executable,
            str(self.project_root / "run_ez_v2_tcp_account.py"),
            "--root-dir",
            str(spec.root_dir),
            "--state-file",
            str(spec.state_file),
            "--chain-id",
            str(self.chain_id),
            "--endpoint",
            spec.endpoint,
            "--consensus-peer-id",
            primary_consensus.node_id,
            "--consensus-endpoint",
            primary_consensus.endpoint,
            "--wallet-file",
            str(spec.wallet_file),
            "--network-timeout-sec",
            str(self.profile.network_timeout_sec),
        ]

    def _start_process(self, cmd: list[str], *, stdout_log: Path, stderr_log: Path) -> subprocess.Popen[str]:
        stdout_handle, stderr_handle = self._open_logs(stdout_log, stderr_log)
        try:
            return subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
        finally:
            stdout_handle.close()
            stderr_handle.close()

    def _wait_for_state(self, state_file: Path, *, proc: subprocess.Popen[str], stderr_log: Path) -> dict[str, Any]:
        deadline = time.time() + max(8.0, self.profile.network_timeout_sec)
        while time.time() < deadline:
            state = read_state_file(str(state_file))
            if isinstance(state, dict) and int(state.get("pid", 0)) == int(proc.pid):
                return state
            if proc.poll() is not None:
                if self._is_bind_not_permitted(stderr_log):
                    raise unittest.SkipTest("bind_not_permitted:Operation not permitted")
                raise RuntimeError(f"daemon_exited_early:{proc.returncode}:{stderr_log}")
            time.sleep(0.05)
        raise RuntimeError(f"daemon_state_timeout:{state_file}")

    def _wait_for_account_balance(self, name: str, expected_balance: int, *, timeout_sec: float = 10.0) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            state = self.read_account_state(name)
            balance = self.engines[name].remote_balance(
                self.wallet_stores[name],
                password=self.password,
                state=state,
            )
            if int(balance["available_balance"]) == expected_balance:
                return balance
            time.sleep(0.1)
        state = self.read_account_state(name)
        return self.engines[name].remote_balance(
            self.wallet_stores[name],
            password=self.password,
            state=state,
        )

    def _wait_for_account_balance_at_least(self, name: str, minimum_balance: int, *, timeout_sec: float = 10.0) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            state = self.read_account_state(name)
            balance = self.engines[name].remote_balance(
                self.wallet_stores[name],
                password=self.password,
                state=state,
            )
            if int(balance["available_balance"]) >= minimum_balance:
                return balance
            time.sleep(0.1)
        state = self.read_account_state(name)
        return self.engines[name].remote_balance(
            self.wallet_stores[name],
            password=self.password,
            state=state,
        )

    def _wait_for_sender_receipt(self, name: str, *, minimum_count: int, timeout_sec: float = 12.0) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        last_view: dict[str, Any] | None = None
        while time.time() < deadline:
            last_view = self.receipts(name)
            if len(last_view.get("items", ())) >= minimum_count:
                return last_view
            time.sleep(0.1)
        if last_view is None:
            last_view = self.receipts(name)
        return last_view

    def _deliver_confirmed_packages(self, name: str, *, seq: int) -> dict[str, int]:
        state = self.read_account_state(name)
        sender_address = self.account_specs[name].address
        sender_peer = with_v2_features(
            PeerInfo(
                node_id=self._peer_id_for_address(sender_address),
                role="account",
                endpoint="127.0.0.1:0",
                metadata={"address": sender_address},
            )
        )
        account_peers = tuple(
            with_v2_features(
                PeerInfo(
                    node_id=self._peer_id_for_address(spec.address),
                    role="account",
                    endpoint=spec.endpoint,
                    metadata={"address": spec.address},
                )
            )
            for peer_name, spec in self.account_specs.items()
            if peer_name != name
        )
        network = TransportPeerNetwork(
            TCPNetworkTransport("127.0.0.1", 0),
            peers=(sender_peer, *account_peers),
            timeout_sec=self.profile.network_timeout_sec,
        )
        wallet = WalletAccountV2(
            address=sender_address,
            genesis_block_hash=b"\x00" * 32,
            db_path=str(state["wallet_db_path"]),
        )
        try:
            confirmed_unit = wallet.db.get_confirmed_unit(sender_address, int(seq))
            if confirmed_unit is None:
                raise ValueError(f"confirmed_unit_missing:{name}:{seq}")
            delivered = 0
            network.start()
            for tx in confirmed_unit.bundle_sidecar.tx_list:
                for value in tx.value_list:
                    package = wallet.export_transfer_package(tx, value)
                    recipient_peer_id = self._peer_id_for_address(tx.recipient_addr)
                    response = network.send(
                        NetworkEnvelope(
                            msg_type=MSG_TRANSFER_PACKAGE_DELIVER,
                            sender_id=sender_peer.node_id,
                            recipient_id=recipient_peer_id,
                            payload={"package": package},
                        )
                    )
                    if isinstance(response, dict) and response.get("ok") is False:
                        error = str(response.get("error", "transfer_package_deliver_failed"))
                        if error != "transfer package already accepted":
                            raise ValueError(error)
                    delivered += 1
            return {"delivered_packages": delivered}
        finally:
            try:
                wallet.close()
            finally:
                network.stop()

    def _wait_for_account_height(self, name: str, expected_height: int, *, timeout_sec: float = 10.0) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            state = self.read_account_state(name)
            cursor = state.get("chain_cursor") or {}
            try:
                height = int(cursor.get("height", 0))
            except Exception:
                height = 0
            if height >= expected_height:
                return state
            time.sleep(0.1)
        return self.read_account_state(name)

    def start(self) -> None:
        for spec in self.consensus_specs.values():
            proc = self._start_process(
                self._build_consensus_cmd(spec),
                stdout_log=spec.stdout_log,
                stderr_log=spec.stderr_log,
            )
            self.consensus_processes[spec.node_id] = proc
        for spec in self.consensus_specs.values():
            self._wait_for_state(spec.state_file, proc=self.consensus_processes[spec.node_id], stderr_log=spec.stderr_log)

        for spec in self.account_specs.values():
            proc = self._start_process(
                self._build_account_cmd(spec),
                stdout_log=spec.stdout_log,
                stderr_log=spec.stderr_log,
            )
            self.account_processes[spec.name] = proc
        for spec in self.account_specs.values():
            self._wait_for_state(spec.state_file, proc=self.account_processes[spec.name], stderr_log=spec.stderr_log)

        alice_name = self.profile.account_names[0]
        self._wait_for_account_balance(alice_name, 1000)
        for name in self.profile.account_names[1:]:
            self._wait_for_account_balance(name, 0)

    def _stop_process(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)

    def stop(self) -> None:
        for name, proc in reversed(tuple(self.account_processes.items())):
            self._stop_process(proc)
            self.account_processes.pop(name, None)
        for node_id, proc in reversed(tuple(self.consensus_processes.items())):
            self._stop_process(proc)
            self.consensus_processes.pop(node_id, None)

    def read_account_state(self, name: str) -> dict[str, Any]:
        state = read_state_file(str(self.account_specs[name].state_file))
        if not isinstance(state, dict):
            raise RuntimeError(f"account_state_missing:{name}")
        return state

    def read_consensus_state(self, node_id: str) -> dict[str, Any]:
        state = read_state_file(str(self.consensus_specs[node_id].state_file))
        if not isinstance(state, dict):
            raise RuntimeError(f"consensus_state_missing:{node_id}")
        return state

    def restart_consensus(self, node_id: str) -> None:
        proc = self.consensus_processes.get(node_id)
        self._stop_process(proc)
        self.consensus_processes.pop(node_id, None)
        spec = self.consensus_specs[node_id]
        proc = self._start_process(
            self._build_consensus_cmd(spec),
            stdout_log=spec.stdout_log,
            stderr_log=spec.stderr_log,
        )
        self.consensus_processes[node_id] = proc
        self._wait_for_state(spec.state_file, proc=proc, stderr_log=spec.stderr_log)

    def send(self, sender: str, recipient: str, *, amount: int, client_tx_id: str):
        sender_receipts_before = len(self.receipts(sender)["items"])
        recipient_before = self.balance(recipient)["available_balance"]
        sender_state = self.read_account_state(sender)
        recipient_state = self.read_account_state(recipient)
        result = self.engines[sender].send(
            self.wallet_stores[sender],
            password=self.password,
            recipient=self.account_specs[recipient].address,
            amount=amount,
            client_tx_id=client_tx_id,
            state=sender_state,
            recipient_endpoint=str(recipient_state["endpoint"]),
        )
        receipt_view = self._wait_for_sender_receipt(
            sender,
            minimum_count=sender_receipts_before + 1,
            timeout_sec=max(12.0, self.profile.network_timeout_sec * 2.0),
        )
        latest_receipt = None
        if receipt_view.get("items"):
            latest_receipt = max(receipt_view["items"], key=lambda item: int(item.get("seq", 0)))
            result.receipt_height = int(latest_receipt["height"])
            result.receipt_block_hash = str(latest_receipt["block_hash"])
            result.status = "confirmed"
        expected_height = int(result.receipt_height or 0)
        if expected_height <= 0:
            raise AssertionError(f"sender_receipt_not_confirmed:{sender}:{client_tx_id}")
        for name in self.profile.account_names:
            self._wait_for_account_height(name, expected_height)
        self._deliver_confirmed_packages(sender, seq=int(latest_receipt["seq"]))
        recipient_balance = self._wait_for_account_balance_at_least(
            recipient,
            int(recipient_before) + int(amount),
            timeout_sec=max(12.0, self.profile.network_timeout_sec * 2.0),
        )
        if int(recipient_balance["available_balance"]) < int(recipient_before) + int(amount):
            raise AssertionError(f"recipient_balance_not_available:{recipient}:{client_tx_id}")
        return result

    def balance(self, name: str) -> dict[str, Any]:
        return self.engines[name].remote_balance(
            self.wallet_stores[name],
            password=self.password,
            state=self.read_account_state(name),
        )

    def receipts(self, name: str) -> dict[str, Any]:
        return self.engines[name].remote_receipts(
            self.wallet_stores[name],
            password=self.password,
            state=self.read_account_state(name),
        )

    def history(self, name: str) -> dict[str, Any]:
        return self.engines[name].remote_history(
            self.wallet_stores[name],
            state=self.read_account_state(name),
        )

    def checkpoints(self, name: str) -> dict[str, Any]:
        return self.engines[name].remote_checkpoints(
            self.wallet_stores[name],
            password=self.password,
            state=self.read_account_state(name),
        )

    def create_checkpoint_from_latest_archived(self, name: str) -> dict[str, Any]:
        state = self.read_account_state(name)
        wallet = WalletAccountV2(
            address=self.account_specs[name].address,
            genesis_block_hash=b"\x00" * 32,
            db_path=str(state["wallet_db_path"]),
        )
        try:
            records = [
                record
                for record in wallet.list_records()
                if record.local_status == LocalValueStatus.ARCHIVED
                and record.witness_v2.confirmed_bundle_chain
            ]
            if not records:
                raise ValueError(f"checkpoint_source_missing:{name}")
            target = max(
                records,
                key=lambda item: item.witness_v2.confirmed_bundle_chain[0].receipt.seq,
            )
            checkpoint = wallet.create_exact_checkpoint(target.record_id)
            return {
                "record_id": target.record_id,
                "value_begin": checkpoint.value_begin,
                "value_end": checkpoint.value_end,
                "checkpoint_height": checkpoint.checkpoint_height,
            }
        finally:
            wallet.close()

    def restart_account(self, name: str) -> None:
        proc = self.account_processes.get(name)
        self._stop_process(proc)
        self.account_processes.pop(name, None)
        spec = self.account_specs[name]
        proc = self._start_process(
            self._build_account_cmd(spec),
            stdout_log=spec.stdout_log,
            stderr_log=spec.stderr_log,
        )
        self.account_processes[name] = proc
        self._wait_for_state(spec.state_file, proc=proc, stderr_log=spec.stderr_log)
