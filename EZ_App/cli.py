from __future__ import annotations

import argparse
import json
from pathlib import Path

from EZ_App.config import ensure_directories, load_api_token, load_config
from EZ_App.node_manager import NodeManager
from EZ_App.profiles import apply_network_profile, list_profiles
from EZ_App.runtime import TxEngine
from EZ_App.service import LocalService
from EZ_App.wallet_store import WalletStore


def _build_runtime(config_path: str):
    cfg = load_config(config_path)
    ensure_directories(cfg)
    wallet_store = WalletStore(cfg.app.data_dir)
    node_manager = NodeManager(data_dir=cfg.app.data_dir, project_root=str(Path(__file__).resolve().parent.parent))
    tx_engine = TxEngine(cfg.app.data_dir, max_tx_amount=cfg.security.max_tx_amount)
    return cfg, wallet_store, node_manager, tx_engine


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EZchain CLI")
    parser.add_argument("--config", default="ezchain.yaml")

    sub = parser.add_subparsers(dest="cmd", required=True)

    wallet = sub.add_parser("wallet")
    wallet_sub = wallet.add_subparsers(dest="wallet_cmd", required=True)

    w_create = wallet_sub.add_parser("create")
    w_create.add_argument("--name", default="default")
    w_create.add_argument("--password", required=True)

    w_import = wallet_sub.add_parser("import")
    w_import.add_argument("--name", default="default")
    w_import.add_argument("--password", required=True)
    w_import.add_argument("--mnemonic", required=True)

    wallet_sub.add_parser("show")
    w_balance = wallet_sub.add_parser("balance")
    w_balance.add_argument("--password", required=True)

    tx = sub.add_parser("tx")
    tx_sub = tx.add_subparsers(dest="tx_cmd", required=True)
    tx_send = tx_sub.add_parser("send")
    tx_send.add_argument("--recipient", required=True)
    tx_send.add_argument("--amount", type=int, required=True)
    tx_send.add_argument("--password", required=True)
    tx_send.add_argument("--client-tx-id", default=None)

    tx_faucet = tx_sub.add_parser("faucet")
    tx_faucet.add_argument("--amount", type=int, required=True)
    tx_faucet.add_argument("--password", required=True)

    node = sub.add_parser("node")
    node_sub = node.add_subparsers(dest="node_cmd", required=True)
    n_start = node_sub.add_parser("start")
    n_start.add_argument("--consensus", type=int, default=None)
    n_start.add_argument("--accounts", type=int, default=None)
    n_start.add_argument("--start-port", type=int, default=None)
    node_sub.add_parser("stop")
    node_sub.add_parser("status")

    network = sub.add_parser("network")
    network_sub = network.add_subparsers(dest="network_cmd", required=True)
    network_sub.add_parser("info")
    network_sub.add_parser("list-profiles")
    n_profile = network_sub.add_parser("set-profile")
    n_profile.add_argument("--name", required=True, choices=list_profiles())

    auth = sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("show-token")

    sub.add_parser("serve")

    args = parser.parse_args(argv)
    cfg, wallet_store, node_manager, tx_engine = _build_runtime(args.config)

    if args.cmd == "wallet":
        if args.wallet_cmd == "create":
            result = wallet_store.create_wallet(password=args.password, name=args.name)
            print(json.dumps({"address": result["address"], "mnemonic": result["mnemonic"]}, indent=2))
            return 0
        if args.wallet_cmd == "import":
            result = wallet_store.import_wallet(mnemonic=args.mnemonic, password=args.password, name=args.name)
            print(json.dumps({"address": result["address"]}, indent=2))
            return 0
        if args.wallet_cmd == "show":
            summary = wallet_store.summary()
            print(json.dumps(summary.__dict__, indent=2))
            return 0
        if args.wallet_cmd == "balance":
            data = tx_engine.balance(wallet_store, password=args.password)
            print(json.dumps(data, indent=2))
            return 0

    if args.cmd == "tx":
        if args.tx_cmd == "faucet":
            data = tx_engine.faucet(wallet_store, password=args.password, amount=args.amount)
            print(json.dumps(data, indent=2))
            return 0
        if args.tx_cmd == "send":
            result = tx_engine.send(
                wallet_store=wallet_store,
                password=args.password,
                recipient=args.recipient,
                amount=args.amount,
                client_tx_id=args.client_tx_id,
            )
            sender = wallet_store.summary().address
            item = {
                "tx_id": result.tx_hash,
                "submit_hash": result.submit_hash,
                "sender": sender,
                "recipient": result.recipient,
                "amount": result.amount,
                "status": result.status,
                "client_tx_id": result.client_tx_id,
            }
            wallet_store.append_history(item)
            print(json.dumps(item, indent=2))
            return 0

    if args.cmd == "node":
        if args.node_cmd == "start":
            consensus = args.consensus if args.consensus is not None else cfg.network.consensus_nodes
            accounts = args.accounts if args.accounts is not None else cfg.network.account_nodes
            start_port = args.start_port if args.start_port is not None else cfg.network.start_port
            print(json.dumps(node_manager.start(consensus=consensus, accounts=accounts, start_port=start_port), indent=2))
            return 0
        if args.node_cmd == "stop":
            print(json.dumps(node_manager.stop(), indent=2))
            return 0
        if args.node_cmd == "status":
            print(json.dumps(node_manager.status(), indent=2))
            return 0

    if args.cmd == "network" and args.network_cmd == "info":
        print(
            json.dumps(
                {
                    "network": cfg.network.name,
                    "bootstrap_nodes": cfg.network.bootstrap_nodes,
                    "consensus_nodes": cfg.network.consensus_nodes,
                    "account_nodes": cfg.network.account_nodes,
                    "start_port": cfg.network.start_port,
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "network" and args.network_cmd == "list-profiles":
        print(json.dumps({"profiles": list_profiles()}, indent=2))
        return 0

    if args.cmd == "network" and args.network_cmd == "set-profile":
        updated_cfg = apply_network_profile(config_path=args.config, profile_name=args.name)
        ensure_directories(updated_cfg)
        print(
            json.dumps(
                {
                    "status": "updated",
                    "profile": args.name,
                    "network": updated_cfg.network.name,
                    "bootstrap_nodes": updated_cfg.network.bootstrap_nodes,
                    "consensus_nodes": updated_cfg.network.consensus_nodes,
                    "account_nodes": updated_cfg.network.account_nodes,
                    "start_port": updated_cfg.network.start_port,
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "auth" and args.auth_cmd == "show-token":
        print(load_api_token(cfg))
        return 0

    if args.cmd == "serve":
        LocalService(
            host=cfg.app.api_host,
            port=cfg.app.api_port,
            wallet_store=wallet_store,
            node_manager=node_manager,
            tx_engine=tx_engine,
            api_token=load_api_token(cfg),
            max_payload_bytes=cfg.security.max_payload_bytes,
            nonce_ttl_seconds=cfg.security.nonce_ttl_seconds,
            log_dir=cfg.app.log_dir,
        ).run()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
