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

    @staticmethod
    def _sanitize_mode_name(mode: str) -> str:
        return str(mode).replace("/", "_").replace(":", "_")

    def _startup_log_path(self, mode: str) -> Path:
        return self.data_dir / f"{self._sanitize_mode_name(mode)}_startup.log"

    def _prepare_startup_log(self, mode: str):
        path = self._startup_log_path(mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path, path.open("w", encoding="utf-8")

    def _read_startup_log_tail(self, mode: str, *, max_chars: int = 600) -> str:
        path = self._startup_log_path(mode)
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]

    def _raise_startup_failure(self, mode: str, code: str, *, stderr_handle=None) -> None:
        if stderr_handle is not None:
            try:
                stderr_handle.flush()
            except Exception:
                pass
            try:
                stderr_handle.close()
            except Exception:
                pass
        detail = self._read_startup_log_tail(mode)
        log_path = self._startup_log_path(mode)
        if detail:
            raise RuntimeError(f"{code}: {detail} (log: {log_path})")
        raise RuntimeError(f"{code} (log: {log_path})")

    @staticmethod
    def _is_v2_mode(mode: str) -> bool:
        return str(mode).startswith("v2-")

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        if str(mode) == "v2-consensus":
            return "v2-tcp-consensus"
        return str(mode)

    @classmethod
    def _mode_family(cls, mode: str) -> str:
        normalized = cls._normalize_mode(mode)
        if normalized == "v2-tcp-consensus":
            return "v2-consensus"
        return normalized

    @classmethod
    def _roles_for_mode(cls, mode: str) -> List[str]:
        normalized = cls._normalize_mode(mode)
        if normalized == "v2-localnet":
            return ["account", "consensus"]
        if normalized == "v2-tcp-consensus":
            return ["consensus"]
        if normalized == "v2-account":
            return ["account"]
        if normalized == "official-testnet":
            return ["account"]
        if normalized == "local":
            return ["account", "consensus"]
        return []

    @classmethod
    def _annotate_mode_payload(cls, payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
        annotated = dict(payload)
        annotated["mode"] = cls._normalize_mode(mode)
        annotated["mode_family"] = cls._mode_family(mode)
        annotated["roles"] = cls._roles_for_mode(mode)
        cls._annotate_account_sync_health(annotated)
        return annotated

    @staticmethod
    def _annotate_account_sync_health(payload: Dict[str, Any]) -> None:
        if payload.get("mode_family") != "v2-account":
            return
        if payload.get("status") != "running":
            return
        if "last_sync_ok" not in payload:
            return

        last_sync_ok = payload.get("last_sync_ok") is True
        last_sync_recovered = payload.get("last_sync_recovered") is True
        recovery_count = int(payload.get("recovery_count", 0) or 0)
        consecutive_failures = int(payload.get("consecutive_sync_failures", 0) or 0)

        if not last_sync_ok:
            payload["sync_health"] = "degraded"
            payload["sync_health_reason"] = "consensus_sync_failed"
        elif last_sync_recovered:
            payload["sync_health"] = "recovered"
            payload["sync_health_reason"] = "recovered_after_consensus_loss"
        elif recovery_count > 0 and consecutive_failures == 0:
            payload["sync_health"] = "healthy"
            payload["sync_health_reason"] = "stable_after_recovery"
        else:
            payload["sync_health"] = "healthy"
            payload["sync_health_reason"] = "steady"

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
        if self._is_v2_mode(mode):
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
        tracked = self._v2_process if self._is_v2_mode(mode) else self._local_process
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
        mode = self._normalize_mode(mode)
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
            return self._annotate_mode_payload(
                {
                    "status": "started_external",
                    "network": network_name,
                    "bootstrap_probe": probe,
                },
                mode,
            )

        if mode == "v2-localnet":
            existing_v2 = self._read_v2_pid()
            if existing_v2 and self._is_running(existing_v2):
                return self._annotate_mode_payload(
                    {
                        "status": "already_running",
                        "pid": str(existing_v2),
                        "network": network_name,
                        "backend": self._read_v2_backend_metadata(),
                    },
                    mode,
                )
            self._cleanup_v2_artifacts()
            _, stderr_handle = self._prepare_startup_log(mode)
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
                stderr=stderr_handle,
            )
            self._v2_process = proc
            self.v2_pid_file.write_text(str(proc.pid), encoding="utf-8")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                state = self._read_v2_state()
                if state is not None and state.get("pid") == proc.pid:
                    try:
                        stderr_handle.close()
                    except Exception:
                        pass
                    break
                if proc.poll() is not None:
                    self._clear_tracked_process(mode="v2-localnet", pid=proc.pid)
                    self._cleanup_v2_artifacts()
                    self._raise_startup_failure(mode, "v2_localnet_failed_to_start", stderr_handle=stderr_handle)
                time.sleep(0.05)
            else:
                try:
                    stderr_handle.close()
                except Exception:
                    pass
            return self._annotate_mode_payload(
                {
                    "status": "started",
                    "pid": str(proc.pid),
                    "network": network_name,
                    "backend_dir": str(self.data_dir / "v2_runtime"),
                    "backend": self._read_v2_backend_metadata(),
                },
                mode,
            )

        if mode == "v2-tcp-consensus":
            existing_v2 = self._read_v2_pid()
            if existing_v2 and self._is_running(existing_v2):
                state = self._read_v2_state() or {}
                return self._annotate_mode_payload(
                    {
                        "status": "already_running",
                        "pid": str(existing_v2),
                        "network": network_name,
                        "endpoint": state.get("endpoint", ""),
                        "backend": self._read_v2_backend_metadata(),
                    },
                    str(state.get("mode", mode)),
                )
            self._cleanup_v2_artifacts()
            endpoint = str((bootstrap_nodes or [f"127.0.0.1:{start_port}"])[0])
            _, stderr_handle = self._prepare_startup_log(mode)
            cmd = [
                sys.executable,
                str(self.project_root / "run_ez_v2_tcp_consensus.py"),
                "--root-dir",
                str(self.data_dir / "v2_runtime"),
                "--state-file",
                str(self.v2_state_file),
                "--chain-id",
                "1",
                "--endpoint",
                endpoint,
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.DEVNULL,
                stderr=stderr_handle,
            )
            self._v2_process = proc
            self.v2_pid_file.write_text(str(proc.pid), encoding="utf-8")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                state = self._read_v2_state()
                if state is not None and state.get("pid") == proc.pid:
                    try:
                        stderr_handle.close()
                    except Exception:
                        pass
                    break
                if proc.poll() is not None:
                    self._clear_tracked_process(mode="v2-tcp-consensus", pid=proc.pid)
                    self._cleanup_v2_artifacts()
                    self._raise_startup_failure(mode, "v2_tcp_consensus_failed_to_start", stderr_handle=stderr_handle)
                time.sleep(0.05)
            else:
                try:
                    stderr_handle.close()
                except Exception:
                    pass
            return self._annotate_mode_payload(
                {
                    "status": "started",
                    "pid": str(proc.pid),
                    "network": network_name,
                    "endpoint": endpoint,
                    "backend_dir": str(self.data_dir / "v2_runtime"),
                    "backend": self._read_v2_backend_metadata(),
                },
                mode,
            )

        if mode == "v2-account":
            existing_v2 = self._read_v2_pid()
            if existing_v2 and self._is_running(existing_v2):
                state = self._read_v2_state() or {}
                return self._annotate_mode_payload(
                    {
                        "status": "already_running",
                        "pid": str(existing_v2),
                        "network": network_name,
                        "endpoint": state.get("endpoint", ""),
                        "consensus_endpoint": state.get("consensus_endpoint", ""),
                        "address": state.get("address", ""),
                    },
                    str(state.get("mode", mode)),
                )
            if not bootstrap_nodes:
                raise ValueError("v2_account_requires_consensus_endpoint")
            self._cleanup_v2_artifacts()
            endpoint = f"127.0.0.1:{start_port}"
            consensus_endpoint = str(bootstrap_nodes[0])
            _, stderr_handle = self._prepare_startup_log(mode)
            cmd = [
                sys.executable,
                str(self.project_root / "run_ez_v2_tcp_account.py"),
                "--root-dir",
                str(self.data_dir / "v2_runtime"),
                "--state-file",
                str(self.v2_state_file),
                "--chain-id",
                "1",
                "--endpoint",
                endpoint,
                "--consensus-endpoint",
                consensus_endpoint,
                "--wallet-file",
                str(self.data_dir / "wallet.json"),
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.DEVNULL,
                stderr=stderr_handle,
            )
            self._v2_process = proc
            self.v2_pid_file.write_text(str(proc.pid), encoding="utf-8")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                state = self._read_v2_state()
                if state is not None and state.get("pid") == proc.pid:
                    try:
                        stderr_handle.close()
                    except Exception:
                        pass
                    break
                if proc.poll() is not None:
                    self._clear_tracked_process(mode="v2-account", pid=proc.pid)
                    self._cleanup_v2_artifacts()
                    self._raise_startup_failure(mode, "v2_account_failed_to_start", stderr_handle=stderr_handle)
                time.sleep(0.05)
            else:
                try:
                    stderr_handle.close()
                except Exception:
                    pass
            state = self._read_v2_state() or {}
            payload = {
                "status": "started",
                "pid": str(proc.pid),
                "network": network_name,
                "endpoint": endpoint,
                "consensus_endpoint": consensus_endpoint,
                "address": state.get("address", ""),
                "backend_dir": str(self.data_dir / "v2_runtime"),
            }
            if "identity_source" in state:
                payload["identity_source"] = state.get("identity_source")
            if "wallet_db_path" in state:
                payload["wallet_db_path"] = state.get("wallet_db_path")
            chain_cursor = state.get("chain_cursor")
            if chain_cursor is not None:
                payload["chain_cursor"] = chain_cursor
            for key in (
                "pending_bundle_count",
                "receipt_count",
                "pending_incoming_transfer_count",
                "fetched_block_count",
                "applied_receipts_last_sync",
                "last_sync_at",
                "last_sync_started_at",
                "last_sync_duration_ms",
                "last_sync_ok",
                "last_sync_error",
                "last_sync_recovered",
                "consecutive_sync_failures",
                "max_consecutive_sync_failures",
                "recovery_count",
                "last_successful_sync_at",
                "last_recovered_at",
            ):
                if key in state:
                    payload[key] = state.get(key)
            return self._annotate_mode_payload(payload, mode)

        existing = self._read_pid()
        if existing and self._is_running(existing):
            return self._annotate_mode_payload({"status": "already_running", "pid": str(existing)}, mode)

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
        return self._annotate_mode_payload({"status": "started", "pid": str(proc.pid)}, mode)

    def stop(self) -> Dict[str, Any]:
        v2_pid = self._read_v2_pid()
        if v2_pid is not None:
            state = self._read_v2_state() or {}
            mode = str(state.get("mode", "v2-localnet"))
            self._stop_pid(v2_pid, mode=mode)
            self._cleanup_v2_artifacts()
            return self._annotate_mode_payload({"status": "stopped", "pid": str(v2_pid)}, mode)

        external = self._read_external_state()
        if external:
            self.external_state_file.unlink(missing_ok=True)
            return self._annotate_mode_payload({"status": "stopped"}, str(external.get("mode", "external")))

        pid = self._read_pid()
        if not pid:
            return {"status": "not_running"}

        if not self._is_running(pid):
            self.pid_file.unlink(missing_ok=True)
            self._clear_tracked_process(mode="local", pid=pid)
            return {"status": "not_running"}

        self._stop_pid(pid, mode="local")
        self.pid_file.unlink(missing_ok=True)
        return self._annotate_mode_payload({"status": "stopped", "pid": str(pid)}, "local")

    def status(self, bootstrap_nodes: List[str] | None = None) -> Dict[str, Any]:
        v2_pid = self._read_v2_pid()
        if v2_pid is not None:
            state = self._read_v2_state() or {}
            mode = str(state.get("mode", "v2-localnet"))
            if not self._is_running(v2_pid):
                self._cleanup_v2_artifacts()
                return self._annotate_mode_payload({"status": "stopped"}, mode)
            payload = {
                "status": "running",
                "pid": str(v2_pid),
                "started_at": state.get("started_at", ""),
                "updated_at": state.get("updated_at", ""),
                "backend": self._read_v2_backend_metadata(),
            }
            endpoint = state.get("endpoint")
            if endpoint:
                payload["endpoint"] = endpoint
            consensus_endpoint = state.get("consensus_endpoint")
            if consensus_endpoint:
                payload["consensus_endpoint"] = consensus_endpoint
            address = state.get("address")
            if address:
                payload["address"] = address
            identity_source = state.get("identity_source")
            if identity_source:
                payload["identity_source"] = identity_source
            wallet_db_path = state.get("wallet_db_path")
            if wallet_db_path:
                payload["wallet_db_path"] = wallet_db_path
            chain_cursor = state.get("chain_cursor")
            if chain_cursor is not None:
                payload["chain_cursor"] = chain_cursor
            for key in (
                "pending_bundle_count",
                "receipt_count",
                "pending_incoming_transfer_count",
                "fetched_block_count",
                "applied_receipts_last_sync",
                "last_sync_at",
                "last_sync_started_at",
                "last_sync_duration_ms",
                "last_sync_ok",
                "last_sync_error",
                "last_sync_recovered",
                "consecutive_sync_failures",
                "max_consecutive_sync_failures",
                "recovery_count",
                "last_successful_sync_at",
                "last_recovered_at",
            ):
                if key in state:
                    payload[key] = state.get(key)
            return self._annotate_mode_payload(payload, mode)

        external = self._read_external_state()
        if external:
            nodes = bootstrap_nodes or external.get("bootstrap_nodes", [])
            probe = self.probe_bootstrap(nodes) if nodes else None
            return self._annotate_mode_payload(
                {
                    "status": "running",
                    "network": external.get("network", "testnet"),
                    "started_at": external.get("started_at", ""),
                    "bootstrap_probe": probe,
                },
                "official-testnet",
            )

        pid = self._read_pid()
        if not pid:
            return self._annotate_mode_payload({"status": "stopped"}, "local")
        running = self._is_running(pid)
        if not running:
            self._clear_tracked_process(mode="local", pid=pid)
        return self._annotate_mode_payload({"status": "running" if running else "stopped", "pid": str(pid)}, "local")

    def account_status(self, bootstrap_nodes: List[str] | None = None) -> Dict[str, Any]:
        current = self.status(bootstrap_nodes=bootstrap_nodes)
        if current.get("mode_family") == "v2-account" and current.get("status") == "running":
            return current
        if current.get("status") in {"stopped", "not_running"}:
            return self._annotate_mode_payload(
                {
                    "status": "not_running",
                    "reason": "v2_account_not_running",
                },
                "v2-account",
            )
        return self._annotate_mode_payload(
            {
                "status": "unavailable",
                "reason": "account_role_not_running_in_current_mode",
                "current_mode": current.get("mode", ""),
                "current_mode_family": current.get("mode_family", ""),
                "current_roles": current.get("roles", []),
            },
            "v2-account",
        )
