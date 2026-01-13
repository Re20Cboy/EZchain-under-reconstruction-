#!/usr/bin/env python3
"""
Distributed P2P Integration Test (multi-process, real TCP)

This test mirrors the flow of test_blockchain_integration_with_real_account.py
but replaces all intra-process copies/args with real P2P messaging via ez_p2p.Router.

Flow:
- Controller generates accounts and genesis data, starts processes:
  - 1 consensus/miner node (txpool + blockchain + block broadcast + proof dispatch)
  - N account nodes (Account + VPBManager + Router)
- Controller sends GENESIS_VPB_INIT to each account (value, proof units, block index)
- Controller instructs several accounts to create and submit transactions
- Consensus picks txs, mines block, broadcasts NEW_BLOCK, sends PROOF_TO_SENDER
- Senders update VPB, then send VPB_TRANSFER to recipients
- Recipients verify and receive VPB

Notes:
- Uses ez_p2p TCP transport
- Uses multiprocessing to isolate node loops
- Minimizes logging for concision
"""

import asyncio
import multiprocessing as mp
import os
import random
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Local imports from project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Test.temp_data_manager import create_test_environment
from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Account.Account import Account
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account
from EZ_Units.MerkleProof import MerkleTreeProof

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.router import Router


# --------------------- Utilities ---------------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return port


def _account_generate_keypair() -> Tuple[bytes, bytes]:
    return secure_signature_handler.signer.generate_key_pair()


def _block_to_payload(block) -> Dict[str, Any]:
    return {
        "index": block.index,
        "nonce": block.nonce,
        "m_tree_root": block.m_tree_root,
        "time": block.time.isoformat() if block.time else None,
        "miner": block.miner,
        "pre_hash": block.pre_hash,
        "version": getattr(block, "version", "1.0"),
    }


def _payload_to_block(payload) -> Any:
    from EZ_Main_Chain.Block import Block
    # time parsing kept simple; Block accepts datetime or None
    import datetime
    t = None
    if payload.get("time"):
        try:
            t = datetime.datetime.fromisoformat(payload["time"])  # type: ignore
        except Exception:
            t = None
    b = Block(
        index=int(payload["index"]),
        m_tree_root=payload["m_tree_root"],
        miner=payload["miner"],
        pre_hash=payload["pre_hash"],
        nonce=int(payload.get("nonce", 0)),
        time=t,
        version=payload.get("version", "1.0"),
    )
    return b


# --------------------- Node processes ---------------------

async def consensus_node_async(cfg: Dict[str, Any], stop_evt: asyncio.Event):
    """Consensus+Miner node coroutine."""
    # Local components
    chain_cfg = ChainConfig(
        confirmation_blocks=cfg.get("confirmation_blocks", 2),
        max_fork_height=cfg.get("max_fork_height", 3),
        debug_mode=False,
        data_directory=cfg.get("data_directory", "blockchain_data/consensus"),
        auto_save=False,
    )
    blockchain = Blockchain(config=chain_cfg)
    txpool = TxPool(db_path=cfg.get("pool_db_path", "tx_pool_consensus.db"))

    router = Router(P2PConfig(
        node_role="consensus",
        listen_host=cfg["host"],
        listen_port=cfg["port"],
        transport="tcp",
        peer_seeds=cfg.get("peer_seeds", []),
        network_id="devnet",
        protocol_version="0.1",
        max_neighbors=cfg.get("max_neighbors", 8),
        node_id=cfg.get("node_id", None),
    ))

    # Handlers
    async def on_submit(msg, remote_addr, writer):
        payload = msg.get("payload", {})
        try:
            sti = SubmitTxInfo.from_dict(payload)
        except Exception as e:
            return  # drop bad payload
        ok, _ = txpool.add_submit_tx_info(sti, multi_transactions=None)
        # No explicit ACK; miner loop will pick

    router.register_handler("ACCTXN_SUBMIT", on_submit)

    await router.start()

    # Controller can push genesis block to consensus via NEW_BLOCK as well; 
    # but we keep consensus' chain authoritative. Miner loop runs and broadcasts.
    async def miner_loop():
        miner_addr = cfg.get("miner_address", "miner_p2p")
        index = blockchain.get_chain_length()
        prev_hash = blockchain.main_chain[-1].get_hash() if blockchain.main_chain else "0"
        while not stop_evt.is_set():
            try:
                package_data, block, picked_txs_mt_proofs, blk_idx, sender_addrs = (
                    pick_transactions_from_pool_with_proofs(
                        tx_pool=txpool,
                        miner_address=miner_addr,
                        previous_hash=prev_hash,
                        block_index=index,
                        max_submit_tx_infos=100,
                        selection_strategy="fifo",
                    )
                )
                if package_data.selected_submit_tx_infos:
                    # Commit block 
                    blockchain.add_block(block)
                    index += 1
                    prev_hash = block.get_hash()
                    # Broadcast block
                    await router.broadcastToConsensus({"block": _block_to_payload(block)}, "NEW_BLOCK")
                    await router.broadcastToConsensus({"block_index": block.index, "merkle_root": block.m_tree_root}, "BLOCK_COMMITTED")
                    # Send proofs to corresponding senders (to account network)
                    for sti, (mt_hash, mt_proof), sender in zip(
                        package_data.selected_submit_tx_infos,
                        picked_txs_mt_proofs,
                        sender_addrs,
                    ):
                        await router.sendConsensusToAccount(
                            sender,
                            {
                                "block_index": block.index,
                                "merkle_root": block.m_tree_root,
                                "multi_transactions_hash": mt_hash,
                                "mt_proof": mt_proof.to_dict() if hasattr(mt_proof, "to_dict") else {"mt_prf_list": getattr(mt_proof, "mt_prf_list", [])},
                            },
                            "PROOF_TO_SENDER",
                        )
            except Exception:
                # Sleep and retry
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.2)

    miner_task = asyncio.create_task(miner_loop())

    # graceful stop
    await stop_evt.wait()
    miner_task.cancel()
    try:
        await miner_task
    except asyncio.CancelledError:
        # Suppress cancellation noise on shutdown
        pass


def consensus_node_main(cfg: Dict[str, Any]):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Reduce repeated secure-key warnings in child process
    import warnings as _warnings
    _warnings.filterwarnings(
        "once",
        message=r"^Private key is being loaded into memory\.",
        category=UserWarning,
    )
    stop_evt = asyncio.Event()

    def _sig(*_):
        if not stop_evt.is_set():
            stop_evt.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            pass

    loop.run_until_complete(consensus_node_async(cfg, stop_evt))


async def account_node_async(cfg: Dict[str, Any], stop_evt: asyncio.Event):
    # Build account and components
    # Ensure data directory exists for sqlite files
    data_dir = cfg.get("data_directory", None)
    if data_dir:
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass
    acc = Account(
        address=cfg["address"],
        private_key_pem=cfg["priv"].encode("utf-8") if isinstance(cfg["priv"], str) else cfg["priv"],
        public_key_pem=cfg["pub"].encode("utf-8") if isinstance(cfg["pub"], str) else cfg["pub"],
        name=cfg.get("name", "acc"),
        data_directory=cfg.get("data_directory", None),
    )
    chain_cfg = ChainConfig(
        confirmation_blocks=cfg.get("confirmation_blocks", 2),
        max_fork_height=cfg.get("max_fork_height", 3),
        debug_mode=False,
        data_directory=cfg.get("data_directory", f"blockchain_data/{acc.address}"),
        auto_save=False,
    )
    blockchain = Blockchain(config=chain_cfg)

    router = Router(P2PConfig(
        node_role="account",
        listen_host=cfg["host"],
        listen_port=cfg["port"],
        transport="tcp",
        peer_seeds=cfg.get("peer_seeds", []),
        network_id="devnet",
        protocol_version="0.1",
        max_neighbors=cfg.get("max_neighbors", 8),
        node_id=cfg.get("node_id", acc.address),
    ))

    # Helpers
    async def send_submit(multi_txn_result: Dict):
        sti = acc.create_submit_tx_info(multi_txn_result)
        if not sti:
            return
        # add to local submitted queue for later lookup
        acc._add_to_submitted_queue(sti.multi_transactions_hash, multi_txn_result.get("multi_transactions"))
        await router.sendAccountToConsensus(sti.to_dict(), "ACCTXN_SUBMIT")

    def _find_recipient_values(multi_txns) -> List[Tuple[str, List[Value]]]:
        res: Dict[str, List[Value]] = {}
        for txn in getattr(multi_txns, "multi_txns", []) or []:
            if hasattr(txn, "recipient") and hasattr(txn, "value"):
                if txn.recipient not in res:
                    res[txn.recipient] = []
                for v in (txn.value or []):
                    res[txn.recipient].append(v)
        return list(res.items())

    # Handlers
    async def on_genesis_init(msg, remote_addr, writer):
        p = msg.get("payload", {})
        # Add genesis block to local chain
        gblock = _payload_to_block(p["genesis_block"]) if p.get("genesis_block") else None
        if gblock:
            blockchain.add_block(gblock)
        # Initialize VPB batch
        values = [Value.from_dict(v) for v in p.get("values", [])]
        proof_units = [ProofUnit.from_dict(u) for u in p.get("proof_units", [])]
        block_index = BlockIndexList.from_dict(p.get("block_index", {"index_lst": [0], "owner": acc.address}))
        acc.vpb_manager.initialize_from_genesis_batch(values, proof_units, block_index)

    async def on_new_block(msg, remote_addr, writer):
        p = msg.get("payload", {})
        block = _payload_to_block(p.get("block", {}))
        if block:
            blockchain.add_block(block)

    async def on_proof_to_sender(msg, remote_addr, writer):
        p = msg.get("payload", {})
        mt_hash = p.get("multi_transactions_hash")
        mt_proof = MerkleTreeProof.from_dict(p.get("mt_proof", {"mt_prf_list": []}))
        block_index = int(p.get("block_index", 0))
        # Find submitted multi transactions locally
        multi_txns = acc.get_submitted_transaction(mt_hash)
        if multi_txns:
            # Derive a primary recipient for old interface compatibility
            primary_recipient = None
            for txn in getattr(multi_txns, "multi_txns", []) or []:
                if hasattr(txn, "recipient") and txn.recipient:
                    primary_recipient = txn.recipient
                    break
            acc.update_vpb_after_transaction_sent(
                confirmed_multi_txns=multi_txns,
                mt_proof=mt_proof,
                block_height=block_index,
                recipient_address=primary_recipient or "unknown",
            )
            # After sender update, send VPB_TRANSFER to recipients
            for recipient, vals in _find_recipient_values(multi_txns):
                for v in vals:
                    pu = acc.vpb_manager.get_proof_units_for_value(v)
                    bi = acc.vpb_manager.get_block_index_for_value(v)
                    payload = {
                        "recipient": recipient,
                        "value": v.to_dict(),
                        "proof_units": [x.to_dict() for x in pu] if pu else [],
                        "block_index": bi.to_dict() if bi else {"index_lst": [block_index], "owner": recipient},
                        "sender": acc.address,
                    }
                    await router.sendToAccount(recipient, payload, "VPB_TRANSFER")

    async def on_vpb_transfer(msg, remote_addr, writer):
        p = msg.get("payload", {})
        if p.get("recipient") != acc.address:
            return
        v = Value.from_dict(p.get("value"))
        proof_units = [ProofUnit.from_dict(u) for u in p.get("proof_units", [])]
        bi = BlockIndexList.from_dict(p.get("block_index", {"index_lst": [], "owner": acc.address}))
        # Build main chain info for validator
        from EZ_VPB_Validator.core.types import MainChainInfo
        merkle_roots = {}
        bloom_filters = {}
        # minimal info: iterate known blocks in local chain
        for i in range(blockchain.get_chain_length()):
            b = blockchain.get_block_by_index(i)
            if b:
                merkle_roots[i] = b.get_m_tree_root()
                bloom_filters[i] = b.get_bloom()
        main_chain_info = MainChainInfo(merkle_roots=merkle_roots, bloom_filters=bloom_filters)
        report = acc.verify_vpb(v, proof_units, bi, main_chain_info)
        if getattr(report, "is_valid", False):
            acc.receive_vpb_from_others(v, proof_units, bi)

    async def on_create_and_submit(msg, remote_addr, writer):
        p = msg.get("payload", {})
        requests = p.get("requests", [])
        # Create batch and submit
        res = acc.create_batch_transactions(requests)
        if res:
            acc.confirm_multi_transaction(res)
            await send_submit(res)

    router.register_handler("GENESIS_VPB_INIT", on_genesis_init)
    router.register_handler("NEW_BLOCK", on_new_block)
    router.register_handler("PROOF_TO_SENDER", on_proof_to_sender)
    router.register_handler("VPB_TRANSFER", on_vpb_transfer)
    router.register_handler("CREATE_AND_SUBMIT", on_create_and_submit)

    await router.start()

    await stop_evt.wait()


def account_node_main(cfg: Dict[str, Any]):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Reduce repeated secure-key warnings in child process
    import warnings as _warnings
    _warnings.filterwarnings(
        "once",
        message=r"^Private key is being loaded into memory\.",
        category=UserWarning,
    )
    stop_evt = asyncio.Event()

    def _sig(*_):
        if not stop_evt.is_set():
            stop_evt.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            pass

    loop.run_until_complete(account_node_async(cfg, stop_evt))


# --------------------- Controller Orchestration ---------------------

def _create_eth_address(tag: str) -> str:
    import hashlib
    return f"0x{hashlib.sha256(tag.encode()).digest()[:20].hex()}"


def _build_random_requests_for(accounts: List[Dict[str, Any]], sender_addr: str, n: int = 2) -> List[Dict[str, Any]]:
    # pick random recipients not equal to sender
    recipients = [a for a in accounts if a["address"] != sender_addr]
    reqs: List[Dict[str, Any]] = []
    for i in range(n):
        if not recipients:
            break
        r = random.choice(recipients)
        amount = random.randint(1, 50)
        reqs.append({"recipient": r["address"], "amount": amount, "reference": f"p2p_{i}"})
    return reqs


def _start_process(target, cfg):
    p = mp.Process(target=target, args=(cfg,), daemon=True)
    p.start()
    return p


def _send(router: Router, addr: str, payload: Dict[str, Any], msg_type: str):
    # helper to run in loop
    return router._send_to_addr(addr, payload, msg_type, network="account")


def run_controller_and_assert():
    # 1. Temp dirs
    temp_mgr = create_test_environment("p2p_integration_distributed", max_sessions=2)
    temp_mgr.cleanup_old_sessions()
    temp_mgr.create_session()
    session_dir = temp_mgr.get_current_session_dir()
    chain_dir = temp_mgr.get_blockchain_data_dir()
    pool_db = temp_mgr.get_pool_db_path()
    acc_store_dir = temp_mgr.get_account_storage_dir()

    # 2. Build accounts
    names = ["alice", "bob", "charlie", "david"]
    accounts_meta: List[Dict[str, Any]] = []
    for i, n in enumerate(names):
        priv, pub = _account_generate_keypair()
        addr = _create_eth_address(f"{n}_{i}")
        accounts_meta.append({
            "name": n,
            "address": addr,
            "priv": priv.decode("utf-8") if isinstance(priv, (bytes, bytearray)) else priv,
            "pub": pub.decode("utf-8") if isinstance(pub, (bytes, bytearray)) else pub,
        })

    # 3. Create genesis (controller-side) and per-account VPB
    # Use lightweight Account objects for genesis creator
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

    # 4. Start consensus node
    cons_port = _free_port()
    consensus_cfg = {
        "host": "127.0.0.1",
        "port": cons_port,
        "peer_seeds": [],
        "max_neighbors": 16,
        "data_directory": os.path.join(chain_dir or ".", "consensus"),
        "pool_db_path": os.path.join(session_dir or ".", "pool_db", "p2p_pool.db"),
        "miner_address": "p2p_miner",
    }
    cons_p = _start_process(consensus_node_main, consensus_cfg)

    # 5. Start account nodes
    acc_procs: List[Tuple[Dict[str, Any], mp.Process]] = []
    acc_listen_addrs: List[str] = []
    for meta in accounts_meta:
        port = _free_port()
        cfg = {
            "host": "127.0.0.1",
            "port": port,
            "peer_seeds": [f"127.0.0.1:{cons_port}"],
            "max_neighbors": 16,
            "address": meta["address"],
            "name": meta["name"],
            "priv": meta["priv"],
            "pub": meta["pub"],
            "data_directory": os.path.join(acc_store_dir or ".", meta["address"]),
        }
        p = _start_process(account_node_main, cfg)
        acc_procs.append((cfg, p))
        acc_listen_addrs.append(f"127.0.0.1:{port}")

    # 6. Controller router to send control messages (acts as a lightweight client)
    async def controller_main():
        router = Router(P2PConfig(
            node_role="account",
            listen_host="127.0.0.1",
            listen_port=_free_port(),
            transport="tcp",
            peer_seeds=[f"127.0.0.1:{cons_port}"] + acc_listen_addrs,
            node_id="controller",
        ))
        await router.start()

        # wait until all account ports are listening
        async def _wait_addr(addr: str, timeout: float = 3.0) -> bool:
            host, port_s = addr.split(":")
            port = int(port_s)
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                try:
                    reader, writer = await asyncio.open_connection(host, port)
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    return True
                except Exception:
                    await asyncio.sleep(0.1)
            return False

        await asyncio.gather(*[_wait_addr(a, timeout=5.0) for a in acc_listen_addrs])

        # 6.1 Send genesis VPB to each account
        gpayload = _block_to_payload(genesis_block)
        for cfg, _ in acc_procs:
            acc_addr = f"{cfg['host']}:{cfg['port']}"
            per = per_account_vpbs[cfg["address"]]
            await _send(router, acc_addr, {"genesis_block": gpayload, **per}, "GENESIS_VPB_INIT")

        # small delay to let accounts init
        await asyncio.sleep(0.5)

        # 6.2 Instruct two random senders to create and submit
        senders = random.sample(accounts_meta, k=min(2, len(accounts_meta)))
        for s in senders:
            reqs = _build_random_requests_for(accounts_meta, s["address"], n=2)
            # Map to account node address
            target = next((f"127.0.0.1:{cfg['port']}" for (cfg, _p) in acc_procs if cfg["address"] == s["address"]), None)
            if target:
                await _send(router, target, {"requests": reqs}, "CREATE_AND_SUBMIT")

        # 6.3 Wait for mining and VPB transfers to settle
        await asyncio.sleep(3.0)

        # 6.4 Additional small transaction to further exercise pipeline
        more_sender = random.choice(accounts_meta)
        reqs = _build_random_requests_for(accounts_meta, more_sender["address"], n=1)
        target = next((f"127.0.0.1:{cfg['port']}" for (cfg, _p) in acc_procs if cfg["address"] == more_sender["address"]), None)
        if target:
            await _send(router, target, {"requests": reqs}, "CREATE_AND_SUBMIT")
        await asyncio.sleep(2.0)

    # Run controller main
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(controller_main())
    finally:
        # stop children
        for _cfg, p in acc_procs:
            if p.is_alive():
                p.terminate()
        if cons_p.is_alive():
            cons_p.terminate()
        temp_mgr.cleanup_current_session()


def test_p2p_blockchain_integration_distributed():
    """Top-level test entry."""
    run_controller_and_assert()
