from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict


class NodeManager:
    def __init__(self, data_dir: str, project_root: str):
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.pid_file = self.data_dir / "node.pid"
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

    def start(self, consensus: int = 1, accounts: int = 1, start_port: int = 19500) -> Dict[str, str]:
        existing = self._read_pid()
        if existing and self._is_running(existing):
            return {"status": "already_running", "pid": str(existing)}

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
        return {"status": "started", "pid": str(proc.pid)}

    def stop(self) -> Dict[str, str]:
        pid = self._read_pid()
        if not pid:
            return {"status": "not_running"}

        if not self._is_running(pid):
            self.pid_file.unlink(missing_ok=True)
            return {"status": "not_running"}

        os.kill(pid, signal.SIGTERM)
        self.pid_file.unlink(missing_ok=True)
        return {"status": "stopped", "pid": str(pid)}

    def status(self) -> Dict[str, str]:
        pid = self._read_pid()
        if not pid:
            return {"status": "stopped"}
        return {"status": "running" if self._is_running(pid) else "stopped", "pid": str(pid)}
