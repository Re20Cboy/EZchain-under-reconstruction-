#!/usr/bin/env python3
import asyncio
import json
import os
import signal
from pathlib import Path

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.logger import setup_logger
from modules.ez_p2p.router import Router
from modules.ez_p2p.adapters.txpool_adapter import TxPoolAdapter


async def main():
    logger = setup_logger("gateway")
    # load config
    cfg_path = os.environ.get("EZ_P2P_CONFIG", str(Path(__file__).with_suffix("").parent / "config" / "gateway.json"))
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = P2PConfig.from_dict(json.load(f))

    router = Router(cfg)
    txpool = TxPoolAdapter(db_path="tx_pool_demo.db")

    # register a minimal ACCTXN_SUBMIT handler
    async def on_submit(msg, remote_addr, writer):
        payload = msg.get("payload", {})
        ok, result = txpool.add_submit_tx_info(payload)
        logger.info(
            "acctxn_submit_recv",
            extra={"extra": {"from": remote_addr, "ok": ok, "result": result, "submitter": payload.get("submitter_address")}},
        )

    router.register_handler("ACCTXN_SUBMIT", on_submit)

    await router.start()

    loop = asyncio.get_running_loop()
    stop = asyncio.Future()

    def _signal_handler():
        if not stop.done():
            stop.set_result(True)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    await stop


if __name__ == "__main__":
    asyncio.run(main())
