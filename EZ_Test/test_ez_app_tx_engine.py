import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from EZ_App.config import ensure_directories, load_config
from EZ_App.runtime import TxEngine
from EZ_App.wallet_store import WalletStore


def test_tx_engine_faucet_and_send():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezchain"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\n"
                f"app:\n  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        cfg = load_config(cfg_path)
        ensure_directories(cfg)

        store = WalletStore(cfg.app.data_dir)
        created = store.create_wallet(password="pw123", name="demo")
        engine = TxEngine(cfg.app.data_dir, max_tx_amount=1000)

        faucet = engine.faucet(store, password="pw123", amount=500)
        assert faucet["available_balance"] >= 500

        result = engine.send(store, password="pw123", recipient="0xabc123", amount=100, client_tx_id="client-a")
        assert result.status == "submitted"
        assert result.amount == 100
        assert result.tx_hash
        assert created["address"].startswith("0x")

        try:
            engine.send(store, password="pw123", recipient="0xabc123", amount=100, client_tx_id="client-a")
            raise AssertionError("expected duplicate_transaction error")
        except ValueError as exc:
            assert str(exc) == "duplicate_transaction"

        try:
            engine.send(store, password="pw123", recipient="0xabc123", amount=2000, client_tx_id="client-b")
            raise AssertionError("expected amount_exceeds_limit error")
        except ValueError as exc:
            assert str(exc) == "amount_exceeds_limit"


def test_faucet_supports_exact_small_send_after_large_topup():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezchain"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\n"
                f"app:\n  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        cfg = load_config(cfg_path)
        ensure_directories(cfg)

        store = WalletStore(cfg.app.data_dir)
        store.create_wallet(password="pw123", name="demo")
        engine = TxEngine(cfg.app.data_dir, max_tx_amount=1000)

        faucet = engine.faucet(store, password="pw123", amount=300)
        assert faucet["available_balance"] >= 300

        result = engine.send(store, password="pw123", recipient="0xabc123", amount=50, client_tx_id="client-c")
        assert result.status == "submitted"
        assert result.amount == 50


def test_tx_engine_blocks_concurrent_duplicate_client_tx_id():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "ezchain.yaml"
        data_dir = Path(td) / ".ezchain"
        cfg_path.write_text(
            (
                "network:\n  name: testnet\n"
                f"app:\n  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
            ),
            encoding="utf-8",
        )

        cfg = load_config(cfg_path)
        ensure_directories(cfg)

        store = WalletStore(cfg.app.data_dir)
        store.create_wallet(password="pw123", name="demo")
        engine = TxEngine(cfg.app.data_dir, max_tx_amount=1000)
        engine.faucet(store, password="pw123", amount=500)

        def worker() -> str:
            try:
                result = engine.send(
                    store,
                    password="pw123",
                    recipient="0xabc123",
                    amount=10,
                    client_tx_id="client-concurrent-one",
                )
                return result.status
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=4) as ex:
            outcomes = list(ex.map(lambda _: worker(), range(4)))

        assert outcomes.count("submitted") == 1
        assert outcomes.count("duplicate_transaction") == 3
