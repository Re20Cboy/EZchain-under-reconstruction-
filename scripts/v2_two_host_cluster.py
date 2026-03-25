#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore
from EZ_V2.crypto import address_from_public_key_pem, derive_secp256k1_keypair_from_mnemonic


@dataclass(frozen=True)
class NodeSpec:
    name: str
    kind: str
    root_dir: str
    state_file: str
    stdout_log: str
    stderr_log: str
    wallet_dir: str | None
    command: tuple[str, ...]


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _wait_for_state(path: Path, *, timeout_sec: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_payload: dict[str, Any] | None = None
    while time.time() < deadline:
        payload = _safe_read_json(path)
        if isinstance(payload, dict) and payload.get("pid"):
            return payload
        if isinstance(payload, dict):
            last_payload = payload
        time.sleep(0.1)
    raise RuntimeError(f"state_file_not_ready:{path}:{last_payload}")


def _mnemonic_for_account(cluster_name: str, node_id: str) -> str:
    return f"ezchain v2 two host cluster {cluster_name} {node_id}"


def _v2_address_for_mnemonic(mnemonic: str) -> str:
    _, public_key_pem = derive_secp256k1_keypair_from_mnemonic(mnemonic)
    return address_from_public_key_pem(public_key_pem)


def _build_topology(
    *,
    cluster_name: str,
    chain_id: int,
    mac_consensus_count: int,
    mac_account_count: int,
    ecs_consensus_count: int,
    ecs_account_count: int,
    mac_consensus_host: str,
    mac_account_host: str,
    ecs_consensus_host: str,
    ecs_account_host: str,
    genesis_amount: int,
    consensus_base_port: int,
    account_base_port: int,
) -> dict[str, Any]:
    if mac_consensus_count + ecs_consensus_count < 3:
        raise ValueError("total consensus nodes must be at least 3")
    if mac_account_count + ecs_account_count < 2:
        raise ValueError("total account nodes must be at least 2")

    consensus_nodes: list[dict[str, Any]] = []
    account_nodes: list[dict[str, Any]] = []

    consensus_index = 0
    mac_consensus_port = consensus_base_port
    ecs_consensus_port = consensus_base_port
    for _ in range(mac_consensus_count):
        node_id = f"consensus-{consensus_index}"
        consensus_nodes.append(
            {
                "node_id": node_id,
                "role": "mac",
                "endpoint": f"{mac_consensus_host}:{mac_consensus_port}",
                "listen_host": "0.0.0.0",
                "root_dir": f".ezchain-twohost/{node_id}",
                "state_file": f".ezchain-twohost/{node_id}/state.json",
                "stdout_log": f".ezchain-twohost/{node_id}/stdout.log",
                "stderr_log": f".ezchain-twohost/{node_id}/stderr.log",
            }
        )
        consensus_index += 1
        mac_consensus_port += 1
    for _ in range(ecs_consensus_count):
        node_id = f"consensus-{consensus_index}"
        consensus_nodes.append(
            {
                "node_id": node_id,
                "role": "ecs",
                "endpoint": f"{ecs_consensus_host}:{ecs_consensus_port}",
                "listen_host": "0.0.0.0",
                "root_dir": f".ezchain-twohost/{node_id}",
                "state_file": f".ezchain-twohost/{node_id}/state.json",
                "stdout_log": f".ezchain-twohost/{node_id}/stdout.log",
                "stderr_log": f".ezchain-twohost/{node_id}/stderr.log",
            }
        )
        consensus_index += 1
        ecs_consensus_port += 1

    account_index = 0
    mac_account_port = account_base_port
    ecs_account_port = account_base_port
    cursor = 0
    for role, count, host, start_port in (
        ("mac", mac_account_count, mac_account_host, mac_account_port),
        ("ecs", ecs_account_count, ecs_account_host, ecs_account_port),
    ):
        port = start_port
        role_consensus = [item for item in consensus_nodes if item["role"] == role]
        primary_consensus_id = (
            role_consensus[0]["node_id"] if role_consensus else consensus_nodes[0]["node_id"]
        )
        primary_consensus_endpoint = (
            role_consensus[0]["endpoint"] if role_consensus else consensus_nodes[0]["endpoint"]
        )
        for _ in range(count):
            node_id = f"account-{account_index:02d}"
            mnemonic = _mnemonic_for_account(cluster_name, node_id)
            address = _v2_address_for_mnemonic(mnemonic)
            begin = cursor
            end = cursor + genesis_amount - 1
            cursor = end + 1
            account_nodes.append(
                {
                    "node_id": node_id,
                    "role": role,
                    "endpoint": f"{host}:{port}",
                    "listen_host": "0.0.0.0",
                    "wallet_dir": f".ezchain-twohost/wallets/{node_id}",
                    "wallet_file": f".ezchain-twohost/wallets/{node_id}/wallet.json",
                    "root_dir": f".ezchain-twohost/{node_id}",
                    "state_file": f".ezchain-twohost/{node_id}/state.json",
                    "stdout_log": f".ezchain-twohost/{node_id}/stdout.log",
                    "stderr_log": f".ezchain-twohost/{node_id}/stderr.log",
                    "mnemonic": mnemonic,
                    "address": address,
                    "genesis_begin": begin,
                    "genesis_end": end,
                    "consensus_peer_id": primary_consensus_id,
                    "consensus_endpoint": primary_consensus_endpoint,
                }
            )
            account_index += 1
            port += 1

    genesis_allocations = [
        {
            "owner_addr": account["address"],
            "begin": account["genesis_begin"],
            "end": account["genesis_end"],
        }
        for account in account_nodes
    ]

    return {
        "cluster_name": cluster_name,
        "chain_id": chain_id,
        "roles": {
            "mac": {
                "consensus_host": mac_consensus_host,
                "account_host": mac_account_host,
            },
            "ecs": {
                "consensus_host": ecs_consensus_host,
                "account_host": ecs_account_host,
            },
        },
        "consensus_nodes": consensus_nodes,
        "account_nodes": account_nodes,
        "genesis_allocations": genesis_allocations,
    }


def _load_topology(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("topology_invalid")
    return payload


def _write_genesis_allocations(project_root: Path, topology: dict[str, Any]) -> str:
    target = project_root / ".ezchain-twohost" / "genesis_allocations.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"allocations": topology["genesis_allocations"]}, indent=2),
        encoding="utf-8",
    )
    return str(target.relative_to(project_root))


def _materialize_wallets(project_root: Path, topology: dict[str, Any], *, role: str, password: str) -> list[str]:
    created: list[str] = []
    for account in topology["account_nodes"]:
        if account["role"] != role:
            continue
        wallet_dir = project_root / account["wallet_dir"]
        store = WalletStore(str(wallet_dir))
        if store.exists():
            continue
        store.import_wallet(
            mnemonic=str(account["mnemonic"]),
            password=password,
            name=str(account["node_id"]),
        )
        created.append(str(account["node_id"]))
    return created


def _build_role_specs(
    *,
    project_root: Path,
    topology: dict[str, Any],
    role: str,
    network_timeout_sec: float,
    reset_account_ephemeral_state: bool,
    reset_account_derived_state: bool,
) -> tuple[NodeSpec, ...]:
    chain_id = int(topology["chain_id"])
    genesis_allocations_file = _write_genesis_allocations(project_root, topology)
    consensus_nodes = tuple(item for item in topology["consensus_nodes"] if item["role"] == role)
    account_nodes = tuple(item for item in topology["account_nodes"] if item["role"] == role)
    consensus_peers = tuple(
        f"{item['node_id']}={item['endpoint']}"
        for item in topology["consensus_nodes"]
    )
    validator_ids = tuple(str(item["node_id"]) for item in topology["consensus_nodes"])
    specs: list[NodeSpec] = []
    for item in consensus_nodes:
        cmd = [
            sys.executable,
            str(project_root / "run_ez_v2_tcp_consensus.py"),
            "--root-dir",
            str(item["root_dir"]),
            "--state-file",
            str(item["state_file"]),
            "--chain-id",
            str(chain_id),
            "--node-id",
            str(item["node_id"]),
            "--endpoint",
            str(item["endpoint"]),
            "--listen-host",
            str(item.get("listen_host", "0.0.0.0")),
            "--network-timeout-sec",
            str(network_timeout_sec),
            "--genesis-allocations-file",
            genesis_allocations_file,
        ]
        for peer in consensus_peers:
            cmd.extend(["--peer", peer])
        for validator_id in validator_ids:
            cmd.extend(["--validator-id", validator_id])
        cmd.extend(["--consensus-mode", "mvp", "--auto-run-mvp-consensus"])
        specs.append(
            NodeSpec(
                name=str(item["node_id"]),
                kind="consensus",
                root_dir=str(item["root_dir"]),
                state_file=str(item["state_file"]),
                stdout_log=str(item["stdout_log"]),
                stderr_log=str(item["stderr_log"]),
                wallet_dir=None,
                command=tuple(cmd),
            )
        )
    for item in account_nodes:
        cmd = [
            sys.executable,
            str(project_root / "run_ez_v2_tcp_account.py"),
            "--root-dir",
            str(item["root_dir"]),
            "--state-file",
            str(item["state_file"]),
            "--chain-id",
            str(chain_id),
            "--endpoint",
            str(item["endpoint"]),
            "--listen-host",
            str(item.get("listen_host", "0.0.0.0")),
            "--consensus-peer-id",
            str(item["consensus_peer_id"]),
            "--consensus-endpoint",
            str(item["consensus_endpoint"]),
            "--wallet-file",
            str(item["wallet_file"]),
            "--network-timeout-sec",
            str(network_timeout_sec),
        ]
        if reset_account_ephemeral_state:
            cmd.append("--reset-ephemeral-state")
        if reset_account_derived_state:
            cmd.append("--reset-derived-state")
        specs.append(
            NodeSpec(
                name=str(item["node_id"]),
                kind="account",
                root_dir=str(item["root_dir"]),
                state_file=str(item["state_file"]),
                stdout_log=str(item["stdout_log"]),
                stderr_log=str(item["stderr_log"]),
                wallet_dir=str(item["wallet_dir"]),
                command=tuple(cmd),
            )
        )
    return tuple(specs)


def _start_spec(project_root: Path, spec: NodeSpec) -> dict[str, Any]:
    root_dir = project_root / spec.root_dir
    root_dir.mkdir(parents=True, exist_ok=True)
    state_path = project_root / spec.state_file
    if state_path.exists():
        state_path.unlink()
    stdout_path = project_root / spec.stdout_log
    stderr_path = project_root / spec.stderr_log
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("a", encoding="utf-8") as stdout_handle, stderr_path.open("a", encoding="utf-8") as stderr_handle:
        subprocess.Popen(
            list(spec.command),
            cwd=str(project_root),
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
            text=True,
        )
    state = _wait_for_state(state_path)
    return {
        "name": spec.name,
        "kind": spec.kind,
        "status": "started",
        "pid": state.get("pid"),
        "state_file": spec.state_file,
    }


def _stop_spec(project_root: Path, spec: NodeSpec) -> dict[str, Any]:
    payload = _safe_read_json(project_root / spec.state_file)
    pid = int(payload.get("pid", 0)) if isinstance(payload, dict) and payload.get("pid") else 0
    if pid and _pid_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.time() + 5.0
        while time.time() < deadline and _pid_running(pid):
            time.sleep(0.1)
        if _pid_running(pid):
            os.kill(pid, signal.SIGKILL)
    return {
        "name": spec.name,
        "kind": spec.kind,
        "status": "stopped",
        "pid": pid or None,
        "state_file": spec.state_file,
    }


def _status_spec(project_root: Path, spec: NodeSpec) -> dict[str, Any]:
    payload = _safe_read_json(project_root / spec.state_file)
    pid = int(payload.get("pid", 0)) if isinstance(payload, dict) and payload.get("pid") else 0
    return {
        "name": spec.name,
        "kind": spec.kind,
        "running": bool(pid and _pid_running(pid)),
        "pid": pid or None,
        "state_file": spec.state_file,
        "endpoint": payload.get("endpoint") if isinstance(payload, dict) else None,
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
    }


def _run_tx_batch(
    *,
    project_root: Path,
    topology: dict[str, Any],
    role: str,
    password: str,
    tx_count: int,
    max_amount: int,
    seed: int,
) -> dict[str, Any]:
    rng = __import__("random").Random(seed)
    chain_id = int(topology["chain_id"])
    local_accounts = [item for item in topology["account_nodes"] if item["role"] == role]
    all_accounts = list(topology["account_nodes"])
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index in range(1, tx_count + 1):
        spendable: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for account in local_accounts:
            state_path = project_root / str(account["state_file"])
            state = _safe_read_json(state_path)
            if not state:
                continue
            wallet_dir = project_root / str(account["wallet_dir"])
            store = WalletStore(str(wallet_dir))
            engine = TxEngine(
                str(wallet_dir),
                max_tx_amount=100000000,
                protocol_version="v2",
                v2_chain_id=chain_id,
            )
            balance = engine.remote_balance(store, password=password, state=state)
            if int(balance.get("available_balance", 0)) > 0:
                spendable.append((account, balance))
        if not spendable:
            failures.append({"tx_index": index, "error": "no_local_spendable_account"})
            break
        sender, balance = rng.choice(spendable)
        recipients = [item for item in all_accounts if item["node_id"] != sender["node_id"]]
        recipient = rng.choice(recipients)
        wallet_dir = project_root / str(sender["wallet_dir"])
        state = _safe_read_json(project_root / str(sender["state_file"]))
        if not state:
            failures.append({"tx_index": index, "error": f"missing_state:{sender['node_id']}"})
            continue
        amount = rng.randint(1, min(max_amount, int(balance["available_balance"])))
        store = WalletStore(str(wallet_dir))
        engine = TxEngine(
            str(wallet_dir),
            max_tx_amount=100000000,
            protocol_version="v2",
            v2_chain_id=chain_id,
        )
        try:
            result = engine.remote_send(
                store,
                password=password,
                recipient=str(recipient["address"]),
                amount=amount,
                recipient_endpoint=str(recipient["endpoint"]),
                state=state,
                client_tx_id=f"{role}-batch-{seed}-{index}",
            )
            results.append(
                {
                    "tx_index": index,
                    "sender_node_id": sender["node_id"],
                    "recipient_node_id": recipient["node_id"],
                    "amount": amount,
                    "status": result.status,
                    "receipt_height": result.receipt_height,
                    "tx_hash": result.tx_hash,
                    "submit_hash": result.submit_hash,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "tx_index": index,
                    "sender_node_id": sender["node_id"],
                    "recipient_node_id": recipient["node_id"],
                    "amount": amount,
                    "error": str(exc),
                }
            )
    return {
        "role": role,
        "requested": tx_count,
        "submitted": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Configurable two-host EZchain V2 cluster controller for Mac + ECS")
    parser.add_argument(
        "action",
        choices=("init-topology", "start", "stop", "restart", "status", "tx-batch"),
    )
    parser.add_argument("--role", choices=("mac", "ecs"), help="Which machine role this invocation controls")
    parser.add_argument("--topology-file", default="configs/v2_two_host_topology.json")
    parser.add_argument("--cluster-name", default="two-host")
    parser.add_argument("--chain-id", type=int, default=821)
    parser.add_argument("--mac-consensus-count", type=int, default=2)
    parser.add_argument("--mac-account-count", type=int, default=1)
    parser.add_argument("--ecs-consensus-count", type=int, default=2)
    parser.add_argument("--ecs-account-count", type=int, default=1)
    parser.add_argument("--mac-consensus-host", default="100.90.152.124")
    parser.add_argument("--mac-account-host", default="100.90.152.124")
    parser.add_argument("--ecs-consensus-host", default="118.178.171.23")
    parser.add_argument("--ecs-account-host", default="118.178.171.23")
    parser.add_argument("--consensus-base-port", type=int, default=19500)
    parser.add_argument("--account-base-port", type=int, default=19600)
    parser.add_argument("--genesis-amount", type=int, default=500)
    parser.add_argument("--password", default="pw123")
    parser.add_argument("--network-timeout-sec", type=float, default=20.0)
    parser.add_argument("--tx-count", type=int, default=10)
    parser.add_argument("--max-amount", type=int, default=50)
    parser.add_argument("--seed", type=int, default=821)
    parser.add_argument("--no-reset-account-ephemeral-state", action="store_true")
    parser.add_argument("--no-reset-account-derived-state", action="store_true")
    args = parser.parse_args()

    project_root = Path.cwd()
    topology_path = project_root / str(args.topology_file)

    if args.action == "init-topology":
        topology = _build_topology(
            cluster_name=str(args.cluster_name),
            chain_id=int(args.chain_id),
            mac_consensus_count=int(args.mac_consensus_count),
            mac_account_count=int(args.mac_account_count),
            ecs_consensus_count=int(args.ecs_consensus_count),
            ecs_account_count=int(args.ecs_account_count),
            mac_consensus_host=str(args.mac_consensus_host),
            mac_account_host=str(args.mac_account_host),
            ecs_consensus_host=str(args.ecs_consensus_host),
            ecs_account_host=str(args.ecs_account_host),
            genesis_amount=int(args.genesis_amount),
            consensus_base_port=int(args.consensus_base_port),
            account_base_port=int(args.account_base_port),
        )
        topology_path.parent.mkdir(parents=True, exist_ok=True)
        topology_path.write_text(json.dumps(topology, indent=2), encoding="utf-8")
        print(json.dumps({"status": "written", "topology_file": str(topology_path), "topology": topology}, indent=2))
        return 0

    if not args.role:
        raise SystemExit("--role is required for this action")
    topology = _load_topology(topology_path)
    created_wallets = _materialize_wallets(
        project_root,
        topology,
        role=str(args.role),
        password=str(args.password),
    )

    specs = _build_role_specs(
        project_root=project_root,
        topology=topology,
        role=str(args.role),
        network_timeout_sec=float(args.network_timeout_sec),
        reset_account_ephemeral_state=not bool(args.no_reset_account_ephemeral_state),
        reset_account_derived_state=not bool(args.no_reset_account_derived_state),
    )

    if args.action == "status":
        print(
            json.dumps(
                {
                    "role": args.role,
                    "wallets_created_now": created_wallets,
                    "nodes": [_status_spec(project_root, spec) for spec in specs],
                },
                indent=2,
            )
        )
        return 0

    if args.action == "stop":
        results = [_stop_spec(project_root, spec) for spec in reversed(specs)]
        print(json.dumps({"role": args.role, "action": "stop", "nodes": results}, indent=2))
        return 0

    if args.action == "restart":
        [_stop_spec(project_root, spec) for spec in reversed(specs)]
        time.sleep(0.5)
        results = [_start_spec(project_root, spec) for spec in specs]
        print(
            json.dumps(
                {
                    "role": args.role,
                    "action": "restart",
                    "wallets_created_now": created_wallets,
                    "nodes": results,
                },
                indent=2,
            )
        )
        return 0

    if args.action == "start":
        results = [_start_spec(project_root, spec) for spec in specs]
        print(
            json.dumps(
                {
                    "role": args.role,
                    "action": "start",
                    "wallets_created_now": created_wallets,
                    "nodes": results,
                },
                indent=2,
            )
        )
        return 0

    batch = _run_tx_batch(
        project_root=project_root,
        topology=topology,
        role=str(args.role),
        password=str(args.password),
        tx_count=int(args.tx_count),
        max_amount=int(args.max_amount),
        seed=int(args.seed),
    )
    print(json.dumps(batch, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
