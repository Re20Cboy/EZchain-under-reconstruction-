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
from typing import Sequence


@dataclass(frozen=True)
class NodeSpec:
    name: str
    kind: str
    root_dir: str
    state_file: str
    stdout_log: str
    stderr_log: str
    command: tuple[str, ...]


def _consensus_spec(
    *,
    project_root: Path,
    root_dir: str,
    state_file: str,
    stdout_log: str,
    stderr_log: str,
    chain_id: int,
    node_id: str,
    endpoint: str,
    peers: tuple[str, ...],
    listen_host: str | None = None,
) -> NodeSpec:
    cmd = [
        sys.executable,
        str(project_root / "run_ez_v2_tcp_consensus.py"),
        "--root-dir",
        root_dir,
        "--state-file",
        state_file,
        "--chain-id",
        str(chain_id),
        "--node-id",
        node_id,
        "--endpoint",
        endpoint,
    ]
    if listen_host:
        cmd.extend(["--listen-host", listen_host])
    for peer in peers:
        cmd.extend(["--peer", peer])
    cmd.extend(["--consensus-mode", "mvp", "--auto-run-mvp-consensus"])
    return NodeSpec(
        name=node_id,
        kind="consensus",
        root_dir=root_dir,
        state_file=state_file,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=tuple(cmd),
    )


def _account_spec(
    *,
    project_root: Path,
    name: str,
    root_dir: str,
    state_file: str,
    stdout_log: str,
    stderr_log: str,
    chain_id: int,
    endpoint: str,
    consensus_endpoint: str,
    wallet_file: str,
    listen_host: str | None = None,
    reset_ephemeral_state: bool = True,
) -> NodeSpec:
    cmd = [
        sys.executable,
        str(project_root / "run_ez_v2_tcp_account.py"),
        "--root-dir",
        root_dir,
        "--state-file",
        state_file,
        "--chain-id",
        str(chain_id),
        "--endpoint",
        endpoint,
        "--consensus-endpoint",
        consensus_endpoint,
        "--wallet-file",
        wallet_file,
    ]
    if listen_host:
        cmd.extend(["--listen-host", listen_host])
    if reset_ephemeral_state:
        cmd.append("--reset-ephemeral-state")
    return NodeSpec(
        name=name,
        kind="account",
        root_dir=root_dir,
        state_file=state_file,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=tuple(cmd),
    )


def build_role_specs(
    *,
    role: str,
    project_root: Path,
    chain_id: int,
    mac_ip: str,
    ecs_ip: str,
    reset_account_ephemeral_state: bool,
) -> tuple[NodeSpec, ...]:
    peers = (
        f"consensus-0={mac_ip}:19500",
        f"consensus-1={mac_ip}:19501",
        f"consensus-2={ecs_ip}:19500",
        f"consensus-3={ecs_ip}:19501",
    )
    if role == "mac":
        return (
            _consensus_spec(
                project_root=project_root,
                root_dir=".ezchain-mac-c0",
                state_file=".ezchain-mac-c0/state.json",
                stdout_log=".ezchain-mac-c0/stdout.log",
                stderr_log=".ezchain-mac-c0/stderr.log",
                chain_id=chain_id,
                node_id="consensus-0",
                endpoint=f"{mac_ip}:19500",
                listen_host="0.0.0.0",
                peers=peers,
            ),
            _consensus_spec(
                project_root=project_root,
                root_dir=".ezchain-mac-c1",
                state_file=".ezchain-mac-c1/state.json",
                stdout_log=".ezchain-mac-c1/stdout.log",
                stderr_log=".ezchain-mac-c1/stderr.log",
                chain_id=chain_id,
                node_id="consensus-1",
                endpoint=f"{mac_ip}:19501",
                listen_host="0.0.0.0",
                peers=peers,
            ),
            _account_spec(
                project_root=project_root,
                name="mac-account",
                root_dir=".ezchain-mac-account-node",
                state_file=".ezchain-mac-account-node/state.json",
                stdout_log=".ezchain-mac-account-node/stdout.log",
                stderr_log=".ezchain-mac-account-node/stderr.log",
                chain_id=chain_id,
                endpoint=f"{mac_ip}:19600",
                listen_host="0.0.0.0",
                consensus_endpoint=f"{mac_ip}:19500",
                wallet_file=".ezchain-mac-account-store/wallet.json",
                reset_ephemeral_state=reset_account_ephemeral_state,
            ),
        )
    if role == "ecs":
        return (
            _consensus_spec(
                project_root=project_root,
                root_dir=".ezchain-ecs-c2",
                state_file=".ezchain-ecs-c2/state.json",
                stdout_log=".ezchain-ecs-c2/stdout.log",
                stderr_log=".ezchain-ecs-c2/stderr.log",
                chain_id=chain_id,
                node_id="consensus-2",
                endpoint=f"{ecs_ip}:19500",
                peers=peers,
            ),
            _consensus_spec(
                project_root=project_root,
                root_dir=".ezchain-ecs-c3",
                state_file=".ezchain-ecs-c3/state.json",
                stdout_log=".ezchain-ecs-c3/stdout.log",
                stderr_log=".ezchain-ecs-c3/stderr.log",
                chain_id=chain_id,
                node_id="consensus-3",
                endpoint=f"{ecs_ip}:19501",
                peers=peers,
            ),
            _account_spec(
                project_root=project_root,
                name="ecs-account",
                root_dir=".ezchain-ecs-account-node",
                state_file=".ezchain-ecs-account-node/state.json",
                stdout_log=".ezchain-ecs-account-node/stdout.log",
                stderr_log=".ezchain-ecs-account-node/stderr.log",
                chain_id=chain_id,
                endpoint=f"{ecs_ip}:19600",
                consensus_endpoint=f"{ecs_ip}:19500",
                wallet_file=".ezchain-ecs-account-store/wallet.json",
                reset_ephemeral_state=reset_account_ephemeral_state,
            ),
        )
    raise ValueError(f"unsupported_role:{role}")


def _safe_read_state(state_path: Path) -> dict | None:
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_state(path: Path, *, timeout_sec: float = 5.0) -> dict:
    deadline = time.time() + timeout_sec
    last_payload: dict | None = None
    while time.time() < deadline:
        payload = _safe_read_state(path)
        if isinstance(payload, dict) and payload.get("pid"):
            return payload
        if isinstance(payload, dict):
            last_payload = payload
        time.sleep(0.1)
    raise RuntimeError(f"state_file_not_ready:{path}:{last_payload}")


def _start_spec(project_root: Path, spec: NodeSpec) -> dict:
    root_dir = project_root / spec.root_dir
    root_dir.mkdir(parents=True, exist_ok=True)
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
    state = _wait_for_state(project_root / spec.state_file)
    return {
        "name": spec.name,
        "kind": spec.kind,
        "status": "started",
        "pid": state.get("pid"),
        "state_file": spec.state_file,
    }


def _stop_spec(project_root: Path, spec: NodeSpec) -> dict:
    payload = _safe_read_state(project_root / spec.state_file)
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


def _status_spec(project_root: Path, spec: NodeSpec) -> dict:
    payload = _safe_read_state(project_root / spec.state_file)
    pid = int(payload.get("pid", 0)) if isinstance(payload, dict) and payload.get("pid") else 0
    running = bool(pid and _pid_running(pid))
    return {
        "name": spec.name,
        "kind": spec.kind,
        "running": running,
        "pid": pid or None,
        "state_file": spec.state_file,
        "endpoint": payload.get("endpoint") if isinstance(payload, dict) else None,
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control the EZchain multi-host V2 test cluster for the current Mac/ECS topology")
    parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--role", choices=("mac", "ecs"), required=True, help="Which machine role this invocation controls")
    parser.add_argument("--chain-id", type=int, default=821)
    parser.add_argument("--mac-ip", default="100.90.152.124")
    parser.add_argument("--ecs-ip", default="100.119.113.49")
    parser.add_argument(
        "--no-reset-account-ephemeral-state",
        action="store_true",
        help="Do not clear pending bundles and cached network state when starting account nodes",
    )
    args = parser.parse_args(argv)

    project_root = Path.cwd()
    specs = build_role_specs(
        role=args.role,
        project_root=project_root,
        chain_id=int(args.chain_id),
        mac_ip=str(args.mac_ip),
        ecs_ip=str(args.ecs_ip),
        reset_account_ephemeral_state=not bool(args.no_reset_account_ephemeral_state),
    )

    if args.action == "status":
        print(json.dumps({"role": args.role, "nodes": [_status_spec(project_root, spec) for spec in specs]}, indent=2))
        return 0

    if args.action == "stop":
        results = [_stop_spec(project_root, spec) for spec in reversed(specs)]
        print(json.dumps({"role": args.role, "action": "stop", "nodes": results}, indent=2))
        return 0

    if args.action == "restart":
        [_stop_spec(project_root, spec) for spec in reversed(specs)]
        time.sleep(0.5)
        results = [_start_spec(project_root, spec) for spec in specs]
        print(json.dumps({"role": args.role, "action": "restart", "nodes": results}, indent=2))
        return 0

    results = [_start_spec(project_root, spec) for spec in specs]
    print(json.dumps({"role": args.role, "action": "start", "nodes": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
