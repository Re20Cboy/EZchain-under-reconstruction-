import tempfile
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
        engine = TxEngine(cfg.app.data_dir)

        faucet = engine.faucet(store, password="pw123", amount=500)
        assert faucet["available_balance"] >= 500

        result = engine.send(store, password="pw123", recipient="0xabc123", amount=100)
        assert result.status == "submitted"
        assert result.amount == 100
        assert result.tx_hash
        assert created["address"].startswith("0x")
