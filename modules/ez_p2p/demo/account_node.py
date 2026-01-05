#!/usr/bin/env python3
import asyncio
import json
import os
import signal
import time
from pathlib import Path

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.logger import setup_logger
from modules.ez_p2p.router import Router


async def main():
    logger = setup_logger("account")
    cfg_path = os.environ.get("EZ_P2P_CONFIG", str(Path(__file__).with_suffix("").parent / "config" / "account.json"))
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = P2PConfig.from_dict(json.load(f))

    router = Router(cfg)
    await router.start()

    # send ping and a dummy ACCTXN_SUBMIT to first seed if any
    if cfg.peer_seeds:
        seed = cfg.peer_seeds[0]
        await asyncio.sleep(0.3)
        await router.ping(seed)
        await asyncio.sleep(0.2)
        # Dummy ACCTXN_SUBMIT payload aligned to SubmitTxInfo structure
        payload = {
            "multi_transactions_hash": "deadbeef" * 8,
            "submit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "version": "1.0.0",
            "submitter_address": cfg.node_id or "0xaccount",
            "signature": "00",
            "public_key": "00",
        }
        await router.sendAccountToConsensus(payload, "ACCTXN_SUBMIT")

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
