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

    @staticmethod
    def _wait_for(predicate, timeout_sec: float = 6.0, interval_sec: float = 0.1):
        deadline = time.time() + timeout_sec
        last = None
        while time.time() < deadline:
            last = predicate()
            if last:
                return last
            time.sleep(interval_sec)
        return None

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

    def test_account_status_reports_unavailable_when_only_consensus_role_is_running(self) -> None:
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
                manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=port,
                    bootstrap_nodes=[endpoint],
                )
            except RuntimeError as exc:
                if isinstance(exc.__cause__, PermissionError):
                    raise unittest.SkipTest(f"bind_not_permitted:{exc.__cause__}") from exc
                raise
            try:
                account_status = manager.account_status()
                self.assertEqual(account_status["status"], "unavailable")
                self.assertEqual(account_status["reason"], "account_role_not_running_in_current_mode")
                self.assertEqual(account_status["current_mode_family"], "v2-consensus")
                self.assertEqual(account_status["current_roles"], ["consensus"])
            finally:
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
                self.assertEqual(account_started["identity_source"], "generated")
                first_address = str(account_started["address"])
                self.assertTrue(first_address.startswith("0x"))

                status = account_manager.status()
                self.assertEqual(status["status"], "running")
                self.assertEqual(status["mode"], "v2-account")
                self.assertEqual(status["roles"], ["account"])
                self.assertEqual(status["consensus_endpoint"], consensus_endpoint)
                self.assertEqual(str(status["address"]), first_address)
                self.assertEqual(status["identity_source"], "generated")
                self.assertIn("pending_bundle_count", status)
                self.assertIn("receipt_count", status)
                self.assertIn("pending_incoming_transfer_count", status)
                self.assertIn("fetched_block_count", status)
                self.assertIn("last_sync_at", status)
                self.assertIn("last_sync_started_at", status)
                self.assertIn("last_sync_duration_ms", status)
                self.assertIn("last_sync_ok", status)
                self.assertIn("last_sync_error", status)
                self.assertIn("last_sync_recovered", status)
                self.assertIn("consecutive_sync_failures", status)
                self.assertIn("max_consecutive_sync_failures", status)
                self.assertIn("recovery_count", status)
                self.assertIn("last_successful_sync_at", status)
                self.assertIn("last_recovered_at", status)
                self.assertEqual(status["sync_health"], "healthy")
                self.assertEqual(status["sync_health_reason"], "steady")
                self.assertTrue(status["last_sync_ok"])
                self.assertEqual(status["last_sync_error"], "")
                self.assertEqual(status["consecutive_sync_failures"], 0)
                account_status = account_manager.account_status()
                self.assertEqual(account_status["status"], "running")
                self.assertEqual(account_status["mode_family"], "v2-account")
                self.assertEqual(account_status["consensus_endpoint"], consensus_endpoint)
                self.assertEqual(str(account_status["address"]), first_address)
                self.assertEqual(account_status["identity_source"], "generated")
                self.assertEqual(account_status["sync_health"], "healthy")
                self.assertEqual(account_status["sync_health_reason"], "steady")
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

    def test_v2_account_reports_consensus_loss_then_recovers_after_repeated_consensus_restart(self) -> None:
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
                consensus_manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=consensus_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
                account_manager.start(
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
                initial_ok = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is True
                        else None
                    ),
                    timeout_sec=8.0,
                )
                self.assertIsNotNone(initial_ok)
                assert initial_ok is not None
                self.assertEqual(initial_ok["consecutive_sync_failures"], 0)

                consensus_manager.stop()

                failed_state = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is False
                        else None
                    ),
                    timeout_sec=8.0,
                )
                self.assertIsNotNone(failed_state)
                assert failed_state is not None
                self.assertGreaterEqual(int(failed_state["consecutive_sync_failures"]), 1)
                self.assertTrue(str(failed_state["last_sync_error"]))
                self.assertEqual(failed_state["sync_health"], "degraded")
                self.assertEqual(failed_state["sync_health_reason"], "consensus_sync_failed")

                consensus_manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=consensus_port,
                    bootstrap_nodes=[consensus_endpoint],
                )

                recovered_state = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is True
                        and int(state.get("recovery_count", 0)) >= 1
                        else None
                    ),
                    timeout_sec=10.0,
                )
                self.assertIsNotNone(recovered_state)
                assert recovered_state is not None
                self.assertTrue(recovered_state["last_sync_recovered"])
                self.assertEqual(recovered_state["consecutive_sync_failures"], 0)
                self.assertGreaterEqual(int(recovered_state["max_consecutive_sync_failures"]), 1)
                self.assertGreaterEqual(int(recovered_state["last_successful_sync_at"]), 1)
                self.assertGreaterEqual(int(recovered_state["last_recovered_at"]), 1)
                self.assertEqual(recovered_state["consensus_endpoint"], consensus_endpoint)
                self.assertEqual(recovered_state["sync_health"], "recovered")
                self.assertEqual(recovered_state["sync_health_reason"], "recovered_after_consensus_loss")

                stable_again = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is True
                        and state.get("last_sync_recovered") is False
                        and state.get("sync_health") == "healthy"
                        else None
                    ),
                    timeout_sec=8.0,
                )
                self.assertIsNotNone(stable_again)
                assert stable_again is not None
                self.assertEqual(stable_again["sync_health_reason"], "stable_after_recovery")

                consensus_manager.stop()

                second_failed_state = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is False
                        else None
                    ),
                    timeout_sec=8.0,
                )
                self.assertIsNotNone(second_failed_state)

                consensus_manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=consensus_port,
                    bootstrap_nodes=[consensus_endpoint],
                )

                second_recovered_state = self._wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is True
                        and int(state.get("recovery_count", 0)) >= 2
                        and state.get("last_sync_recovered") is True
                        else None
                    ),
                    timeout_sec=10.0,
                )
                self.assertIsNotNone(second_recovered_state)
                assert second_recovered_state is not None
                self.assertEqual(second_recovered_state["sync_health"], "recovered")
                self.assertEqual(second_recovered_state["sync_health_reason"], "recovered_after_consensus_loss")
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

    def test_v2_account_prefers_existing_wallet_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td_consensus:
            with tempfile.TemporaryDirectory() as td_account:
                consensus_manager = NodeManager(
                    data_dir=td_consensus,
                    project_root=str(Path(__file__).resolve().parent.parent),
                )
                account_manager = NodeManager(
                    data_dir=td_account,
                    project_root=str(Path(__file__).resolve().parent.parent),
                )
                wallet_store = WalletStore(td_account)
                wallet_store.create_wallet(password="pw123", name="demo")
                expected_address = wallet_store.summary(protocol_version="v2").address
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
                    self.assertEqual(account_started["identity_source"], "wallet_file")
                    self.assertEqual(str(account_started["address"]), expected_address)
                    self.assertTrue(str(account_started["wallet_db_path"]).endswith(f"wallet_state_v2/{expected_address}/wallet_v2.db"))

                    status = account_manager.account_status()
                    self.assertEqual(status["status"], "running")
                    self.assertEqual(status["identity_source"], "wallet_file")
                    self.assertEqual(str(status["address"]), expected_address)
                    self.assertTrue(str(status["wallet_db_path"]).endswith(f"wallet_state_v2/{expected_address}/wallet_v2.db"))
                finally:
                    account_manager.stop()
                    consensus_manager.stop()


if __name__ == "__main__":
    unittest.main()
