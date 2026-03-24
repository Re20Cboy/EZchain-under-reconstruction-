import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from EZ_V2.control import read_state_file
from run_ez_v2_tcp_consensus import _build_consensus_peers


class EZV2TCPConsensusDaemonScriptTest(unittest.TestCase):
    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_build_consensus_peers_requires_local_entry_when_cluster_is_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "local_node_missing_from_peer_specs"):
            _build_consensus_peers(
                node_id="consensus-1",
                endpoint="127.0.0.1:19501",
                peer_specs=(
                    "consensus-0=127.0.0.1:19500",
                    "consensus-2=127.0.0.1:19502",
                ),
            )

    def test_script_starts_with_explicit_mvp_cluster_metadata(self) -> None:
        try:
            port0 = self._reserve_port()
        except PermissionError as exc:
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
        port1 = self._reserve_port()
        port2 = self._reserve_port()

        project_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as td:
            root_dir = Path(td) / "runtime"
            state_file = Path(td) / "state.json"
            cmd = [
                sys.executable,
                str(project_root / "run_ez_v2_tcp_consensus.py"),
                "--root-dir",
                str(root_dir),
                "--state-file",
                str(state_file),
                "--chain-id",
                "821",
                "--node-id",
                "consensus-1",
                "--endpoint",
                f"127.0.0.1:{port1}",
                "--peer",
                f"consensus-0=127.0.0.1:{port0}",
                "--peer",
                f"consensus-1=127.0.0.1:{port1}",
                "--peer",
                f"consensus-2=127.0.0.1:{port2}",
                "--consensus-mode",
                "mvp",
                "--auto-run-mvp-consensus",
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 5.0
                state = None
                while time.time() < deadline:
                    state = read_state_file(str(state_file))
                    if state and int(state.get("pid", 0)) == proc.pid:
                        break
                    if proc.poll() is not None:
                        self.fail(f"consensus_daemon_exited_early:{proc.returncode}")
                    time.sleep(0.05)
                else:
                    self.fail("consensus_daemon_state_timeout")

                assert state is not None
                self.assertEqual(state["mode"], "v2-tcp-consensus")
                self.assertEqual(state["node_id"], "consensus-1")
                self.assertEqual(state["endpoint"], f"127.0.0.1:{port1}")
                self.assertEqual(state["listen_endpoint"], f"127.0.0.1:{port1}")
                self.assertEqual(state["consensus_mode"], "mvp")
                self.assertTrue(state["auto_run_mvp_consensus"])
                self.assertEqual(
                    state["peer_endpoints"],
                    {
                        "consensus-0": f"127.0.0.1:{port0}",
                        "consensus-1": f"127.0.0.1:{port1}",
                        "consensus-2": f"127.0.0.1:{port2}",
                    },
                )
                self.assertEqual(
                    state["consensus_validator_ids"],
                    ["consensus-0", "consensus-1", "consensus-2"],
                )
            finally:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5.0)

    def test_script_can_bind_on_override_host_while_advertising_tailnet_endpoint(self) -> None:
        try:
            port0 = self._reserve_port()
        except PermissionError as exc:
            raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
        port1 = self._reserve_port()
        port2 = self._reserve_port()

        project_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as td:
            root_dir = Path(td) / "runtime"
            state_file = Path(td) / "state.json"
            cmd = [
                sys.executable,
                str(project_root / "run_ez_v2_tcp_consensus.py"),
                "--root-dir",
                str(root_dir),
                "--state-file",
                str(state_file),
                "--chain-id",
                "821",
                "--node-id",
                "consensus-0",
                "--endpoint",
                f"100.90.152.124:{port0}",
                "--listen-host",
                "0.0.0.0",
                "--peer",
                f"consensus-0=100.90.152.124:{port0}",
                "--peer",
                f"consensus-1=100.101.104.77:{port1}",
                "--peer",
                f"consensus-2=100.119.113.49:{port2}",
                "--consensus-mode",
                "mvp",
                "--auto-run-mvp-consensus",
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 5.0
                state = None
                while time.time() < deadline:
                    state = read_state_file(str(state_file))
                    if state and int(state.get("pid", 0)) == proc.pid:
                        break
                    if proc.poll() is not None:
                        self.fail(f"consensus_daemon_exited_early:{proc.returncode}")
                    time.sleep(0.05)
                else:
                    self.fail("consensus_daemon_state_timeout")

                assert state is not None
                self.assertEqual(state["endpoint"], f"100.90.152.124:{port0}")
                self.assertEqual(state["listen_endpoint"], f"0.0.0.0:{port0}")
            finally:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5.0)
