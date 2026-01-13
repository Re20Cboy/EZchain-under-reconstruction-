#!/usr/bin/env python3
"""
One-click P2P network launcher for EZchain (TCP-based)

Configurable params:
- consensus node count
- account node count
- max neighbors
- host/port range

Boot sequence:
- Generate accounts (addresses + keys)
- Create genesis block and per-account VPB data
- Start consensus nodes (txpool+miner)
- Start account nodes
- Send GENESIS_VPB_INIT to each account via P2P
- Periodically instruct random accounts to create+submit transactions

Stop with Ctrl+C to terminate processes.
"""

import argparse
import asyncio
import multiprocessing as mp
import os
import random
import signal
import socket
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from EZ_Test.test_p2p_blockchain_integration_distributed import (
    _free_port,
    _account_generate_keypair,
    _create_eth_address,
    _block_to_payload,
    _send,
    account_node_main,
    consensus_node_main,
)

from EZ_Account.Account import Account
from EZ_Test.temp_data_manager import create_test_environment
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.router import Router


def main():
    ap = argparse.ArgumentParser(description="Run EZchain P2P network (demo)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--start-port", type=int, default=19500)
    ap.add_argument("--consensus", type=int, default=1)
    ap.add_argument("--accounts", type=int, default=4)
    ap.add_argument("--max-neighbors", type=int, default=16)
    ap.add_argument("--tx-burst", type=int, default=2, help="transactions per wave per selected sender")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between waves")
    ap.add_argument("--waves", type=int, default=0, help="number of waves to run (0 = infinite)")
    args = ap.parse_args()

    # Prepare temp dirs
    temp_mgr = create_test_environment("p2p_network_launcher", max_sessions=3)
    temp_mgr.cleanup_old_sessions()
    temp_mgr.create_session()
    session_dir = temp_mgr.get_current_session_dir() or "."
    chain_dir = temp_mgr.get_blockchain_data_dir() or "."
    acc_store_dir = temp_mgr.get_account_storage_dir() or "."

    # Build accounts
    accounts_meta: List[Dict[str, Any]] = []
    for i in range(args.accounts):
        priv, pub = _account_generate_keypair()
        name = f"acc{i}"
        addr = _create_eth_address(f"{name}_{i}")
        accounts_meta.append({
            "name": name,
            "address": addr,
            "priv": priv.decode("utf-8") if isinstance(priv, (bytes, bytearray)) else priv,
            "pub": pub.decode("utf-8") if isinstance(pub, (bytes, bytearray)) else pub,
        })

    # Create genesis and per-account VPB
    ghost_accounts = [Account(a["address"], a["priv"].encode("utf-8") if isinstance(a["priv"], str) else a["priv"], a["pub"].encode("utf-8") if isinstance(a["pub"], str) else a["pub"], name=a["name"], data_directory=acc_store_dir) for a in accounts_meta]
    genesis_block, unified_sti, unified_multi_txn, merkle_tree = create_genesis_block(ghost_accounts, custom_miner="ezchain_p2p_genesis_miner")
    per_account_vpbs: Dict[str, Dict[str, Any]] = {}
    for a in accounts_meta:
        values, proof_units, block_index = create_genesis_vpb_for_account(
            account_addr=a["address"],
            genesis_block=genesis_block,
            unified_submit_tx_info=unified_sti,
            unified_multi_txn=unified_multi_txn,
            merkle_tree=merkle_tree,
        )
        per_account_vpbs[a["address"]] = {
            "values": [v.to_dict() for v in values],
            "proof_units": [u.to_dict() for u in proof_units],
            "block_index": block_index.to_dict(),
        }

    # Start consensus nodes
    base_port = args.start_port
    cons_cfgs: List[Dict[str, Any]] = []
    cons_procs: List[mp.Process] = []
    for i in range(args.consensus):
        port = base_port + i
        cfg = {
            "host": args.host,
            "port": port,
            "peer_seeds": [],  # fill after launch
            "max_neighbors": args.max_neighbors,
            "data_directory": os.path.join(chain_dir, f"consensus_{i}"),
            "pool_db_path": os.path.join(session_dir, "pool_db", f"p2p_pool_{i}.db"),
            "miner_address": f"miner_{i}",
            "node_id": f"consensus_{i}",
        }
        # ensure directories exist
        os.makedirs(cfg["data_directory"], exist_ok=True)
        os.makedirs(os.path.dirname(cfg["pool_db_path"]), exist_ok=True)
        cons_cfgs.append(cfg)
    # seed each consensus with others
    all_cons_addrs = [f"{c['host']}:{c['port']}" for c in cons_cfgs]
    for c in cons_cfgs:
        c["peer_seeds"] = [a for a in all_cons_addrs if a != f"{c['host']}:{c['port']}"]
    for c in cons_cfgs:
        p = mp.Process(target=consensus_node_main, args=(c,), daemon=True)
        p.start()
        cons_procs.append(p)

    # Start accounts
    acc_cfgs: List[Dict[str, Any]] = []
    acc_procs: List[mp.Process] = []
    for i, meta in enumerate(accounts_meta):
        port = base_port + args.consensus + i
        cfg = {
            "host": args.host,
            "port": port,
            "peer_seeds": all_cons_addrs,
            "max_neighbors": args.max_neighbors,
            "address": meta["address"],
            "name": meta["name"],
            "priv": meta["priv"],
            "pub": meta["pub"],
            "data_directory": os.path.join(acc_store_dir, meta["address"]),
            "node_id": meta["address"],
        }
        acc_cfgs.append(cfg)
        # ensure directory exists
        os.makedirs(cfg["data_directory"], exist_ok=True)
        p = mp.Process(target=account_node_main, args=(cfg,), daemon=True)
        p.start()
        acc_procs.append(p)

    # Controller loop for genesis + tx waves
    async def controller():
        router = Router(P2PConfig(
            node_role="account",
            listen_host=args.host,
            listen_port=base_port + args.consensus + args.accounts + 1,
            transport="tcp",
            peer_seeds=all_cons_addrs + [f"{c['host']}:{c['port']}" for c in acc_cfgs],
            node_id="launcher_controller",
        ))
        await router.start()
        # Wait until account ports are listening
        async def _wait_addr(addr: str, timeout: float = 5.0) -> bool:
            host, port_s = addr.split(":")
            port = int(port_s)
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                try:
                    r, w = await asyncio.open_connection(host, port)
                    w.close()
                    try:
                        await w.wait_closed()
                    except Exception:
                        pass
                    return True
                except Exception:
                    await asyncio.sleep(0.1)
            return False
        await asyncio.gather(*[_wait_addr(f"{cfg['host']}:{cfg['port']}") for cfg in acc_cfgs])
        gpayload = _block_to_payload(genesis_block)
        # Genesis to all accounts
        for cfg in acc_cfgs:
            await _send(router, f"{cfg['host']}:{cfg['port']}", {"genesis_block": gpayload, **per_account_vpbs[cfg['address']]}, "GENESIS_VPB_INIT")
        await asyncio.sleep(0.8)

        async def waves():
            wave_no = 0
            while True:
                # pick 1-2 random senders per wave
                k = min(2, len(accounts_meta))
                for sender in random.sample(accounts_meta, k=k):
                    reqs = [{"recipient": r["address"], "amount": random.randint(1, 50), "reference": f"wave"}
                            for r in random.sample([x for x in accounts_meta if x["address"] != sender["address"]],
                                                   k=min(2, len(accounts_meta) - 1))]
                    target = next((f"{cfg['host']}:{cfg['port']}" for cfg in acc_cfgs if cfg["address"] == sender["address"]), None)
                    if target:
                        await _send(router, target, {"requests": reqs}, "CREATE_AND_SUBMIT")
                wave_no += 1
                # If a finite number of waves is requested, stop after reaching it
                if args.waves and wave_no >= args.waves:
                    # signal controller to stop
                    if not stop.done():
                        stop.set_result(True)
                    break
                await asyncio.sleep(args.interval)

        # run until SIGINT or waves limit
        stop = asyncio.Future()
        wave_task = asyncio.create_task(waves())
        def _sig():
            if not stop.done():
                stop.set_result(True)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _sig)
            except NotImplementedError:
                pass
        await stop
        # Gracefully cancel the wave task and suppress cancellation noise
        if not wave_task.done():
            wave_task.cancel()
        try:
            await wave_task
        except asyncio.CancelledError:
            pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(controller())
    finally:
        loop.stop()
        # terminate children
        for p in acc_procs:
            if p.is_alive():
                p.terminate()
        for p in cons_procs:
            if p.is_alive():
                p.terminate()


if __name__ == "__main__":
    # Show the private-key-in-memory warning only once per process
    import warnings
    warnings.filterwarnings(
        "once",
        message=r"^Private key is being loaded into memory\.",
        category=UserWarning,
    )
    main()
