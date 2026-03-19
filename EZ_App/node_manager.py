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
        self.v2_pid_file = self.data_dir / "v2_localnet.pid"
        self.v2_state_file = self.data_dir / "v2_localnet_state.json"
        self._local_process: subprocess.Popen[str] | None = None
        self._v2_process: subprocess.Popen[str] | None = None
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
            waited_pid, _ = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                return False
        except (ChildProcessError, OSError):
            pass
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

    def _read_v2_pid(self) -> int | None:
        if not self.v2_pid_file.exists():
            return None
        try:
            return int(self.v2_pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _read_v2_state(self) -> Dict[str, Any] | None:
        try:
            from EZ_V2.control import read_state_file

            return read_state_file(str(self.v2_state_file))
        except Exception:
            return None

    def _cleanup_v2_artifacts(self) -> None:
        self.v2_pid_file.unlink(missing_ok=True)
        self.v2_state_file.unlink(missing_ok=True)

    def _read_v2_backend_metadata(self) -> Dict[str, Any] | None:
        try:
            from EZ_V2.control import read_backend_metadata

            return read_backend_metadata(str(self.data_dir / "v2_runtime"))
        except Exception:
            return None

    def _clear_tracked_process(self, *, mode: str, pid: int | None = None) -> None:
        if mode == "v2-localnet":
            if self._v2_process is not None and (pid is None or self._v2_process.pid == pid):
                self._v2_process = None
            return
        if self._local_process is not None and (pid is None or self._local_process.pid == pid):
            self._local_process = None

    def _stop_tracked_process(self, process: subprocess.Popen[str] | None, pid: int, *, mode: str) -> bool:
        if process is None or process.pid != pid:
            return False
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        self._clear_tracked_process(mode=mode, pid=pid)
        return True

    def _stop_pid(self, pid: int, *, mode: str) -> None:
        tracked = self._v2_process if mode == "v2-localnet" else self._local_process
        if self._stop_tracked_process(tracked, pid, mode=mode):
            return
        if not self._is_running(pid):
            self._clear_tracked_process(mode=mode, pid=pid)
            return
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if not self._is_running(pid):
                self._clear_tracked_process(mode=mode, pid=pid)
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            self._clear_tracked_process(mode=mode, pid=pid)
            return
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if not self._is_running(pid):
                break
            time.sleep(0.05)
        self._clear_tracked_process(mode=mode, pid=pid)

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

        if mode == "v2-localnet":
            existing_v2 = self._read_v2_pid()
            if existing_v2 and self._is_running(existing_v2):
                return {
                    "status": "already_running",
                    "pid": str(existing_v2),
                    "mode": "v2-localnet",
                    "network": network_name,
                    "backend": self._read_v2_backend_metadata(),
                }
            self._cleanup_v2_artifacts()
            cmd = [
                sys.executable,
                str(self.project_root / "run_ez_v2_localnet.py"),
                "--daemon",
                "--root-dir",
                str(self.data_dir / "v2_runtime"),
                "--state-file",
                str(self.v2_state_file),
                "--chain-id",
                "1",
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._v2_process = proc
            self.v2_pid_file.write_text(str(proc.pid), encoding="utf-8")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                state = self._read_v2_state()
                if state is not None and state.get("pid") == proc.pid:
                    break
                if proc.poll() is not None:
                    self._clear_tracked_process(mode="v2-localnet", pid=proc.pid)
                    self._cleanup_v2_artifacts()
                    raise RuntimeError("v2_localnet_failed_to_start")
                time.sleep(0.05)
            return {
                "status": "started",
                "pid": str(proc.pid),
                "mode": "v2-localnet",
                "network": network_name,
                "backend_dir": str(self.data_dir / "v2_runtime"),
                "backend": self._read_v2_backend_metadata(),
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
        self._local_process = proc
        self.pid_file.write_text(str(proc.pid), encoding="utf-8")
        return {"status": "started", "pid": str(proc.pid), "mode": "local"}

    def stop(self) -> Dict[str, Any]:
        v2_pid = self._read_v2_pid()
        if v2_pid is not None:
            mode = "v2-localnet"
            self._stop_pid(v2_pid, mode=mode)
            self._cleanup_v2_artifacts()
            return {"status": "stopped", "pid": str(v2_pid), "mode": mode}

        external = self._read_external_state()
        if external:
            self.external_state_file.unlink(missing_ok=True)
            return {"status": "stopped", "mode": external.get("mode", "external")}

        pid = self._read_pid()
        if not pid:
            return {"status": "not_running"}

        if not self._is_running(pid):
            self.pid_file.unlink(missing_ok=True)
            self._clear_tracked_process(mode="local", pid=pid)
            return {"status": "not_running"}

        self._stop_pid(pid, mode="local")
        self.pid_file.unlink(missing_ok=True)
        return {"status": "stopped", "pid": str(pid), "mode": "local"}

    def status(self, bootstrap_nodes: List[str] | None = None) -> Dict[str, Any]:
        v2_pid = self._read_v2_pid()
        if v2_pid is not None:
            if not self._is_running(v2_pid):
                self._cleanup_v2_artifacts()
                return {"status": "stopped", "mode": "v2-localnet"}
            state = self._read_v2_state() or {}
            return {
                "status": "running",
                "mode": "v2-localnet",
                "pid": str(v2_pid),
                "started_at": state.get("started_at", ""),
                "updated_at": state.get("updated_at", ""),
                "backend": self._read_v2_backend_metadata(),
            }

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
        running = self._is_running(pid)
        if not running:
            self._clear_tracked_process(mode="local", pid=pid)
        return {"status": "running" if running else "stopped", "pid": str(pid), "mode": "local"}
