#!/usr/bin/env python3
import asyncio
import json
import os
import signal
from typing import Any, Dict

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import pick_transactions_from_pool_with_proofs
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.router import Router
from modules.ez_p2p.nodes.utils import block_to_payload, payload_to_block


async def consensus_node_async(cfg: Dict[str, Any], stop_evt: asyncio.Event):
    chain_cfg = ChainConfig(
        confirmation_blocks=cfg.get("confirmation_blocks", 2),
        max_fork_height=cfg.get("max_fork_height", 3),
        debug_mode=False,
        data_directory=cfg.get("data_directory", "blockchain_data/consensus"),
        auto_save=True,
    )
    blockchain = Blockchain(config=chain_cfg)
    txpool = TxPool(db_path=cfg.get("pool_db_path", os.path.join(cfg.get("data_directory", "."), "tx_pool.db")))
    submitter_endpoints: Dict[str, str] = {}
    address_book: Dict[str, str] = cfg.get("address_book", {}) or {}
    pending_blocks: Dict[int, Any] = {}

    # Optional local genesis bootstrap for distributed runs
    bundle_path = cfg.get("genesis_bundle_path")
    if bundle_path:
        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                bundle = json.load(f)
            genesis_payload = bundle.get("genesis_block")
            if genesis_payload:
                gblock = payload_to_block(genesis_payload)
                if blockchain.get_chain_length() == 0:
                    blockchain.add_block(gblock)
        except Exception:
            pass

    router = Router(P2PConfig(
        node_role="consensus",
        listen_host=cfg["host"],
        listen_port=cfg["port"],
        transport="tcp",
        peer_seeds=cfg.get("peer_seeds", []),
        network_id="devnet",
        protocol_version="0.1",
        max_neighbors=cfg.get("max_neighbors", 8),
        send_timeout_ms=cfg.get("send_timeout_ms", 3000),
        retry_count=cfg.get("retry_count", 2),
        retry_backoff_ms=cfg.get("retry_backoff_ms", 300),
        dedup_window_ms=cfg.get("dedup_window_ms", 5 * 60 * 1000),
        node_id=cfg.get("node_id", None),
    ))

    async def on_submit(msg, remote_addr, writer):
        payload = msg.get("payload", {})
        try:
            sti = SubmitTxInfo.from_dict(payload)
        except Exception:
            return
        account_endpoint = payload.get("account_endpoint")
        if isinstance(account_endpoint, str) and ":" in account_endpoint:
            submitter_endpoints[sti.submitter_address] = account_endpoint
        txpool.add_submit_tx_info(sti, multi_transactions=None)

    def _apply_pending_blocks():
        while True:
            expected = blockchain.get_latest_block_index() + 1
            block = pending_blocks.pop(expected, None)
            if block is None:
                break
            try:
                blockchain.add_block(block)
            except Exception:
                continue

    async def on_new_block(msg, remote_addr, writer):
        p = msg.get("payload", {})
        block = payload_to_block(p.get("block", {}))
        if not block:
            return
        expected_index = blockchain.get_latest_block_index() + 1
        if block.index > expected_index:
            pending_blocks[block.index] = block
            return
        try:
            blockchain.add_block(block)
            _apply_pending_blocks()
        except Exception:
            pending_blocks[block.index] = block

    router.register_handler("ACCTXN_SUBMIT", on_submit)
    router.register_handler("NEW_BLOCK", on_new_block)

    await router.start()

    async def miner_loop():
        miner_addr = cfg.get("miner_address", "miner_p2p")
        while not stop_evt.is_set():
            try:
                index = blockchain.get_chain_length()
                prev_hash = blockchain.main_chain[-1].get_hash() if blockchain.main_chain else "0"
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
                    blockchain.add_block(block)
                    await router.broadcastToConsensus({"block": block_to_payload(block)}, "NEW_BLOCK")
                    await router.broadcastToAccounts({"block": block_to_payload(block)}, "NEW_BLOCK")
                    await router.broadcastToConsensus({"block_index": block.index, "merkle_root": block.m_tree_root}, "BLOCK_COMMITTED")

                    for sti, (mt_hash, mt_proof), sender in zip(
                        package_data.selected_submit_tx_infos,
                        picked_txs_mt_proofs,
                        sender_addrs,
                    ):
                        sender_endpoint = submitter_endpoints.get(sender) or address_book.get(sender) or sender
                        if ":" not in str(sender_endpoint):
                            continue
                        await router.sendConsensusToAccount(
                            sender_endpoint,
                            {
                                "block_index": block.index,
                                "merkle_root": block.m_tree_root,
                                "multi_transactions_hash": mt_hash,
                                "mt_proof": mt_proof.to_dict() if hasattr(mt_proof, "to_dict") else {"mt_prf_list": getattr(mt_proof, "mt_prf_list", [])},
                            },
                            "PROOF_TO_SENDER",
                        )
            except Exception:
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.2)

    miner_task = asyncio.create_task(miner_loop())
    await stop_evt.wait()
    miner_task.cancel()
    try:
        await miner_task
    except asyncio.CancelledError:
        pass
    await router.stop()


def consensus_node_main(cfg: Dict[str, Any]):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
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
