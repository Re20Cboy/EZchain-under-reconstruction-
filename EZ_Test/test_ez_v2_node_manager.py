import tempfile
import time
import unittest
from pathlib import Path

from EZ_App.node_manager import NodeManager
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


class EZV2NodeManagerTest(unittest.TestCase):
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

            stopped = manager.stop()
            self.assertEqual(stopped["status"], "stopped")
            self.assertEqual(stopped["mode"], "v2-localnet")

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


if __name__ == "__main__":
    unittest.main()
