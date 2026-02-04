#!/usr/bin/env python3
import asyncio
import json
import os
import signal
from typing import Any, Dict, List, Tuple

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Account.Account import Account
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account  # noqa: F401 (imported for external use if needed)
from EZ_VPB.values.Value import Value
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Units.MerkleProof import MerkleTreeProof

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.router import Router
from modules.ez_p2p.nodes.utils import payload_to_block


async def account_node_async(cfg: Dict[str, Any], stop_evt: asyncio.Event):
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
        auto_save=True,
    )
    blockchain = Blockchain(config=chain_cfg)
    pending_blocks: Dict[int, Any] = {}
    address_book: Dict[str, str] = cfg.get("address_book", {}) or {}
    advertise_host = cfg.get("advertise_host", cfg.get("host"))
    advertise_port = cfg.get("advertise_port", cfg.get("port"))
    self_endpoint = f"{advertise_host}:{advertise_port}"

    # Optional local genesis bootstrap for distributed runs
    bundle_path = cfg.get("genesis_bundle_path")
    if bundle_path:
        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                bundle = json.load(f)
            genesis_payload = bundle.get("genesis_block")
            account_data = (bundle.get("accounts") or {}).get(acc.address)
            if genesis_payload and account_data:
                gblock = payload_to_block(genesis_payload)
                if blockchain.get_chain_length() == 0:
                    blockchain.add_block(gblock)
                    values = [Value.from_dict(v) for v in account_data.get("values", [])]
                    proof_units = [ProofUnit.from_dict(u) for u in account_data.get("proof_units", [])]
                    block_index = BlockIndexList.from_dict(
                        account_data.get("block_index", {"index_lst": [0], "owner": acc.address})
                    )
                    acc.vpb_manager.initialize_from_genesis_batch(values, proof_units, block_index)
        except Exception:
            pass

    router = Router(P2PConfig(
        node_role="account",
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
        node_id=cfg.get("node_id", acc.address),
    ))

    async def send_submit(multi_txn_result: Dict):
        sti = acc.create_submit_tx_info(multi_txn_result)
        if not sti:
            return
        acc._add_to_submitted_queue(sti.multi_transactions_hash, multi_txn_result.get("multi_transactions"))
        payload = sti.to_dict()
        payload["account_endpoint"] = self_endpoint
        await router.sendAccountToConsensus(payload, "ACCTXN_SUBMIT")

    def _resolve_account_endpoint(account_addr: str) -> str:
        return address_book.get(account_addr, account_addr)

    def _apply_pending_blocks():
        while True:
            expected = blockchain.get_latest_block_index() + 1
            block = pending_blocks.pop(expected, None)
            if block is None:
                break
            try:
                blockchain.add_block(block)
            except Exception:
                # Keep going; malformed fork blocks are safely ignored for this node.
                continue

    def _find_recipient_values(multi_txns) -> List[Tuple[str, List[Value]]]:
        res: Dict[str, List[Value]] = {}
        for txn in getattr(multi_txns, "multi_txns", []) or []:
            if hasattr(txn, "recipient") and hasattr(txn, "value"):
                if txn.recipient not in res:
                    res[txn.recipient] = []
                for v in (txn.value or []):
                    res[txn.recipient].append(v)
        return list(res.items())

    async def on_genesis_init(msg, remote_addr, writer):
        p = msg.get("payload", {})
        gblock = payload_to_block(p["genesis_block"]) if p.get("genesis_block") else None
        if gblock and blockchain.get_chain_length() == 0:
            blockchain.add_block(gblock)
            values = [Value.from_dict(v) for v in p.get("values", [])]
            proof_units = [ProofUnit.from_dict(u) for u in p.get("proof_units", [])]
            block_index = BlockIndexList.from_dict(p.get("block_index", {"index_lst": [0], "owner": acc.address}))
            acc.vpb_manager.initialize_from_genesis_batch(values, proof_units, block_index)

    async def on_new_block(msg, remote_addr, writer):
        p = msg.get("payload", {})
        block = payload_to_block(p.get("block", {}))
        if block:
            expected_index = blockchain.get_latest_block_index() + 1
            if block.index > expected_index:
                pending_blocks[block.index] = block
                return
            try:
                blockchain.add_block(block)
                _apply_pending_blocks()
            except Exception:
                pending_blocks[block.index] = block

    async def on_proof_to_sender(msg, remote_addr, writer):
        p = msg.get("payload", {})
        mt_hash = p.get("multi_transactions_hash")
        mt_proof = MerkleTreeProof.from_dict(p.get("mt_proof", {"mt_prf_list": []}))
        block_index = int(p.get("block_index", 0))
        multi_txns = acc.get_submitted_transaction(mt_hash)
        if multi_txns:
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
            for recipient, vals in _find_recipient_values(multi_txns):
                target = _resolve_account_endpoint(recipient)
                if ":" not in str(target):
                    continue
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
                    await router.sendToAccount(target, payload, "VPB_TRANSFER")

    async def on_vpb_transfer(msg, remote_addr, writer):
        p = msg.get("payload", {})
        if p.get("recipient") != acc.address:
            return
        v = Value.from_dict(p.get("value"))
        proof_units = [ProofUnit.from_dict(u) for u in p.get("proof_units", [])]
        bi = BlockIndexList.from_dict(p.get("block_index", {"index_lst": [], "owner": acc.address}))
        from EZ_VPB_Validator.core.types import MainChainInfo
        merkle_roots = {}
        bloom_filters = {}
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
    auto_cfg = cfg.get("auto_submit", {}) or {}

    async def auto_submit_loop():
        await asyncio.sleep(float(auto_cfg.get("initial_delay_sec", 2.0)))
        while not stop_evt.is_set():
            recipient_candidates = auto_cfg.get("recipients")
            if not recipient_candidates:
                recipient_candidates = [a for a in address_book.keys() if a != acc.address]
            if recipient_candidates:
                burst = int(auto_cfg.get("burst", 1))
                min_amount = int(auto_cfg.get("min_amount", 1))
                max_amount = int(auto_cfg.get("max_amount", 50))
                reqs = []
                for i in range(max(1, burst)):
                    r = recipient_candidates[i % len(recipient_candidates)]
                    reqs.append({"recipient": r, "amount": min_amount if min_amount == max_amount else min_amount + (i % (max_amount - min_amount + 1))})
                res = acc.create_batch_transactions(reqs)
                if res:
                    acc.confirm_multi_transaction(res)
                    await send_submit(res)
            await asyncio.sleep(float(auto_cfg.get("interval_sec", 5.0)))

    auto_task = None
    if auto_cfg.get("enabled"):
        auto_task = asyncio.create_task(auto_submit_loop())
    await stop_evt.wait()
    if auto_task:
        auto_task.cancel()
        try:
            await auto_task
        except asyncio.CancelledError:
            pass
    await router.stop()


def account_node_main(cfg: Dict[str, Any]):
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

    loop.run_until_complete(account_node_async(cfg, stop_evt))
