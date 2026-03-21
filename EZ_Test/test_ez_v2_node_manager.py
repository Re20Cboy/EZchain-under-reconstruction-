import tempfile
import time
import unittest
import socket
from pathlib import Path
from unittest import mock

from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


class EZV2NodeManagerTest(unittest.TestCase):
    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_v2_localnet_lifecycle_cleans_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = NodeManager(
                data_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )

            started = manager.start(mode="v2-localnet", network_name="testnet")
            self.assertEqual(started["status"], "started")
            self.assertTrue(manager.v2_pid_file.exists())
            self.assertTrue(manager.v2_state_file.exists())

            status = manager.status()
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["mode"], "v2-localnet")
            self.assertEqual(status["mode_family"], "v2-localnet")
            self.assertEqual(status["roles"], ["account", "consensus"])

            stopped = manager.stop()
            self.assertEqual(stopped["status"], "stopped")
            self.assertEqual(stopped["mode"], "v2-localnet")
            self.assertEqual(stopped["mode_family"], "v2-localnet")
            self.assertEqual(stopped["roles"], ["account", "consensus"])

            time.sleep(0.1)
            self.assertEqual(manager.status()["status"], "stopped")
            self.assertFalse(manager.v2_pid_file.exists())
            self.assertFalse(manager.v2_state_file.exists())
            self.assertEqual(manager.stop()["status"], "not_running")

    def test_v2_backend_metadata_advances_with_shared_tx_engine(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = NodeManager(
                data_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            store = WalletStore(td)
            store.create_wallet(password="pw123", name="demo")
            engine = TxEngine(td, max_tx_amount=1000, protocol_version="v2")

            try:
                started = manager.start(mode="v2-localnet", network_name="testnet")
                self.assertIn(started["status"], {"started", "already_running"})

                faucet = engine.faucet(store, password="pw123", amount=200)
                self.assertEqual(faucet["chain_height"], 0)

                result = engine.send(
                    store,
                    password="pw123",
                    recipient="0xabc123",
                    amount=50,
                    client_tx_id="cid-node-metadata-1",
                )
                self.assertEqual(result.receipt_height, 1)

                metadata = engine.v2_client.backend_metadata()
                self.assertIsNotNone(metadata)
                assert metadata is not None
                self.assertEqual(metadata["height"], 1)
                self.assertEqual(metadata["chain_id"], 1)
                self.assertTrue(metadata["current_block_hash"])

                status = manager.status()
                self.assertEqual(status["status"], "running")
                self.assertEqual(status["backend"]["height"], 1)
            finally:
                manager.stop()

    def test_v2_tcp_consensus_lifecycle_exposes_reachable_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = NodeManager(
                data_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            try:
                port = self._reserve_port()
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            endpoint = f"127.0.0.1:{port}"

            try:
                started = manager.start(
                    mode="v2-tcp-consensus",
                    network_name="testnet-v2-tcp",
                    start_port=port,
                    bootstrap_nodes=[endpoint],
                )
            except RuntimeError as exc:
                if isinstance(exc.__cause__, PermissionError):
                    raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                raise
            self.assertEqual(started["status"], "started")
            self.assertEqual(started["mode"], "v2-tcp-consensus")
            self.assertEqual(started["mode_family"], "v2-consensus")
            self.assertEqual(started["roles"], ["consensus"])
            self.assertEqual(started["endpoint"], endpoint)
            self.assertTrue(manager.v2_pid_file.exists())
            self.assertTrue(manager.v2_state_file.exists())

            status = manager.status()
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["mode"], "v2-tcp-consensus")
            self.assertEqual(status["mode_family"], "v2-consensus")
            self.assertEqual(status["roles"], ["consensus"])
            self.assertEqual(status["endpoint"], endpoint)
            probe = manager.probe_bootstrap([endpoint])
            self.assertTrue(probe["all_reachable"])

            stopped = manager.stop()
            self.assertEqual(stopped["status"], "stopped")
            self.assertEqual(stopped["mode"], "v2-tcp-consensus")
            self.assertEqual(stopped["mode_family"], "v2-consensus")
            self.assertEqual(stopped["roles"], ["consensus"])

            time.sleep(0.1)
            self.assertEqual(manager.status()["status"], "stopped")
            self.assertFalse(manager.v2_pid_file.exists())
            self.assertFalse(manager.v2_state_file.exists())

    def test_v2_consensus_alias_maps_to_existing_tcp_consensus_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = NodeManager(
                data_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            try:
                port = self._reserve_port()
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            endpoint = f"127.0.0.1:{port}"

            try:
                started = manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=port,
                    bootstrap_nodes=[endpoint],
                )
            except RuntimeError as exc:
                if isinstance(exc.__cause__, PermissionError):
                    raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                raise
            self.assertEqual(started["mode"], "v2-tcp-consensus")
            self.assertEqual(started["mode_family"], "v2-consensus")
            self.assertEqual(started["roles"], ["consensus"])

            manager.stop()

    def test_v2_account_lifecycle_exposes_account_role_and_consensus_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as consensus_td, tempfile.TemporaryDirectory() as account_td:
            consensus_manager = NodeManager(
                data_dir=consensus_td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            account_manager = NodeManager(
                data_dir=account_td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            try:
                consensus_port = self._reserve_port()
                account_port = self._reserve_port()
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            consensus_endpoint = f"127.0.0.1:{consensus_port}"

            try:
                consensus_started = consensus_manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=consensus_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
                self.assertEqual(consensus_started["status"], "started")

                account_started = account_manager.start(
                    mode="v2-account",
                    network_name="testnet-v2-account",
                    start_port=account_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
            except RuntimeError as exc:
                if isinstance(exc.__cause__, PermissionError):
                    raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                raise
            try:
                self.assertEqual(account_started["status"], "started")
                self.assertEqual(account_started["mode"], "v2-account")
                self.assertEqual(account_started["mode_family"], "v2-account")
                self.assertEqual(account_started["roles"], ["account"])
                self.assertEqual(account_started["consensus_endpoint"], consensus_endpoint)
                self.assertIn("last_sync_ok", account_started)
                self.assertIn("last_sync_error", account_started)
                self.assertTrue(account_started["last_sync_ok"])
                self.assertEqual(account_started["last_sync_error"], "")
                first_address = str(account_started["address"])
                self.assertTrue(first_address.startswith("0x"))

                status = account_manager.status()
                self.assertEqual(status["status"], "running")
                self.assertEqual(status["mode"], "v2-account")
                self.assertEqual(status["roles"], ["account"])
                self.assertEqual(status["consensus_endpoint"], consensus_endpoint)
                self.assertEqual(str(status["address"]), first_address)
                self.assertIn("pending_bundle_count", status)
                self.assertIn("receipt_count", status)
                self.assertIn("pending_incoming_transfer_count", status)
                self.assertIn("fetched_block_count", status)
                self.assertIn("last_sync_at", status)
                self.assertIn("last_sync_started_at", status)
                self.assertIn("last_sync_duration_ms", status)
                self.assertIn("last_sync_ok", status)
                self.assertIn("last_sync_error", status)
                self.assertTrue(status["last_sync_ok"])
                self.assertEqual(status["last_sync_error"], "")
                probe = account_manager.probe_bootstrap([consensus_endpoint])
                self.assertTrue(probe["all_reachable"])

                account_manager.stop()
                restarted = account_manager.start(
                    mode="v2-account",
                    network_name="testnet-v2-account",
                    start_port=account_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
                self.assertEqual(str(restarted["address"]), first_address)
            finally:
                account_manager.stop()
                consensus_manager.stop()

    def test_v2_account_start_failure_surfaces_startup_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = NodeManager(
                data_dir=td,
                project_root=str(Path(__file__).resolve().parent.parent),
            )

            class _FakeProcess:
                def __init__(self, pid: int):
                    self.pid = pid

                def poll(self):
                    return 1

            def _fake_popen(*args, **kwargs):
                stderr_handle = kwargs.get("stderr")
                if stderr_handle is not None:
                    stderr_handle.write("traceback line 1\nreal account startup failure\n")
                    stderr_handle.flush()
                return _FakeProcess(43210)

            with mock.patch("EZ_App.node_manager.subprocess.Popen", side_effect=_fake_popen):
                with self.assertRaises(RuntimeError) as raised:
                    manager.start(
                        mode="v2-account",
                        network_name="testnet-v2-account",
                        start_port=19600,
                        bootstrap_nodes=["127.0.0.1:19500"],
                    )

            message = str(raised.exception)
            self.assertIn("v2_account_failed_to_start", message)
            self.assertIn("real account startup failure", message)
            log_path = Path(td) / "v2-account_startup.log"
            self.assertTrue(log_path.exists())
            self.assertIn("real account startup failure", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
