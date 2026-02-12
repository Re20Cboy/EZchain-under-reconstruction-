from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple


class NodeManager:
    def __init__(self, data_dir: str, project_root: str):
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.pid_file = self.data_dir / "node.pid"
        self.external_state_file = self.data_dir / "external_node_state.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _read_pid(self) -> int | None:
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _parse_host_port(endpoint: str) -> Tuple[str, int]:
        host, port_s = endpoint.rsplit(":", 1)
        return host.strip(), int(port_s)

    def probe_bootstrap(self, bootstrap_nodes: List[str], timeout_sec: float = 1.5) -> Dict[str, Any]:
        checked = []
        reachable = 0

        for endpoint in bootstrap_nodes:
            item: Dict[str, Any] = {"endpoint": endpoint, "reachable": False}
            try:
                host, port = self._parse_host_port(endpoint)
                with socket.create_connection((host, port), timeout=timeout_sec):
                    pass
                item["reachable"] = True
                reachable += 1
            except Exception as exc:
                item["error"] = str(exc)
            checked.append(item)

        total = len(bootstrap_nodes)
        return {
            "total": total,
            "reachable": reachable,
            "unreachable": max(0, total - reachable),
            "all_reachable": (total > 0 and reachable == total),
            "any_reachable": reachable > 0,
            "checked": checked,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _write_external_state(self, payload: Dict[str, Any]) -> None:
        self.external_state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_external_state(self) -> Dict[str, Any] | None:
        if not self.external_state_file.exists():
            return None
        try:
            parsed = json.loads(self.external_state_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def start(
        self,
        consensus: int = 1,
        accounts: int = 1,
        start_port: int = 19500,
        mode: str = "local",
        bootstrap_nodes: List[str] | None = None,
        network_name: str = "testnet",
    ) -> Dict[str, Any]:
        bootstrap_nodes = bootstrap_nodes or []

        if mode == "official-testnet":
            probe = self.probe_bootstrap(bootstrap_nodes)
            payload = {
                "mode": "official-testnet",
                "network": network_name,
                "bootstrap_nodes": bootstrap_nodes,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._write_external_state(payload)
            return {
                "status": "started_external",
                "mode": "official-testnet",
                "network": network_name,
                "bootstrap_probe": probe,
            }

        existing = self._read_pid()
        if existing and self._is_running(existing):
            return {"status": "already_running", "pid": str(existing), "mode": "local"}

        cmd = [
            sys.executable,
            str(self.project_root / "run_ez_p2p_network.py"),
            "--consensus",
            str(consensus),
            "--accounts",
            str(accounts),
            "--waves",
            "0",
            "--start-port",
            str(start_port),
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=str(self.project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.pid_file.write_text(str(proc.pid), encoding="utf-8")
        return {"status": "started", "pid": str(proc.pid), "mode": "local"}

    def stop(self) -> Dict[str, Any]:
        external = self._read_external_state()
        if external:
            self.external_state_file.unlink(missing_ok=True)
            return {"status": "stopped", "mode": "official-testnet"}

        pid = self._read_pid()
        if not pid:
            return {"status": "not_running"}

        if not self._is_running(pid):
            self.pid_file.unlink(missing_ok=True)
            return {"status": "not_running"}

        os.kill(pid, signal.SIGTERM)
        self.pid_file.unlink(missing_ok=True)
        return {"status": "stopped", "pid": str(pid), "mode": "local"}

    def status(self, bootstrap_nodes: List[str] | None = None) -> Dict[str, Any]:
        external = self._read_external_state()
        if external:
            nodes = bootstrap_nodes or external.get("bootstrap_nodes", [])
            probe = self.probe_bootstrap(nodes) if nodes else None
            return {
                "status": "running",
                "mode": "official-testnet",
                "network": external.get("network", "testnet"),
                "started_at": external.get("started_at", ""),
                "bootstrap_probe": probe,
            }

        pid = self._read_pid()
        if not pid:
            return {"status": "stopped", "mode": "local"}
        return {"status": "running" if self._is_running(pid) else "stopped", "pid": str(pid), "mode": "local"}
