from __future__ import annotations

import argparse
import json
from pathlib import Path

from EZ_App.contact_card import build_contact_card, contact_entry_from_card, fetch_contact_card, load_contact_card
from EZ_App.config import ensure_directories, load_api_token, load_config, migrate_config_file
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
    tx_engine = TxEngine(
        cfg.app.data_dir,
        max_tx_amount=cfg.security.max_tx_amount,
        protocol_version=cfg.app.protocol_version,
    )
    return cfg, wallet_store, node_manager, tx_engine


def _has_non_loopback_bootstrap(cfg) -> bool:
    for endpoint in cfg.network.bootstrap_nodes or []:
        host = str(endpoint).split(":", 1)[0].strip().lower()
        if host not in {"127.0.0.1", "localhost"}:
            return True
    return False


def _network_mode(cfg) -> str:
    if _has_non_loopback_bootstrap(cfg):
        return "official-testnet"
    if str(cfg.app.protocol_version).lower() == "v2":
        return "v2-localnet"
    return "local"


def _mode_roles(mode: str) -> list[str]:
    return NodeManager._roles_for_mode(mode)


def _tx_path_info(cfg) -> dict[str, object]:
    protocol_version = str(cfg.app.protocol_version or "v1").lower()
    if protocol_version == "v2" and _has_non_loopback_bootstrap(cfg):
        return {
            "tx_path": "local_v2_runtime",
            "tx_path_ready": False,
            "tx_path_note": "Remote official-testnet still does not have the full tx path. Read-only queries work through the shared account wallet DB, and tx send needs either recipient_endpoint or a saved contact endpoint.",
        }
    if protocol_version == "v2":
        return {
            "tx_path": "local_v2_runtime",
            "tx_path_ready": True,
            "tx_path_note": "V2 tx commands run through the local runtime.",
        }
    return {
        "tx_path": "legacy_local_runtime",
        "tx_path_ready": True,
        "tx_path_note": "Tx commands run through the legacy local runtime.",
    }


def _tx_path_ready(cfg) -> bool:
    return bool(_tx_path_info(cfg).get("tx_path_ready", True))


def _print_tx_path_not_ready(cfg, *, action: str) -> int:
    info = _tx_path_info(cfg)
    print(
        json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "tx_path_not_ready",
                    "message": f"{action} is not available on this profile yet",
                },
                "network": cfg.network.name,
                "mode": _network_mode(cfg),
                "mode_family": NodeManager._mode_family(_network_mode(cfg)),
                **info,
            },
            indent=2,
        )
    )
    return 2


def _remote_read_state(cfg, node_manager: NodeManager):
    if _network_mode(cfg) != "official-testnet" or str(cfg.app.protocol_version).lower() != "v2":
        return None
    state = node_manager.account_status(bootstrap_nodes=cfg.network.bootstrap_nodes)
    if not isinstance(state, dict):
        return None
    if state.get("status") != "running":
        return None
    if state.get("mode_family") != "v2-account":
        return None
    if not str(state.get("wallet_db_path", "")).strip():
        return None
    return state


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
    w_checkpoints = wallet_sub.add_parser("checkpoints")
    w_checkpoints.add_argument("--password", required=True)

    tx = sub.add_parser("tx")
    tx_sub = tx.add_subparsers(dest="tx_cmd", required=True)
    tx_send = tx_sub.add_parser("send")
    tx_send.add_argument("--recipient", required=True)
    tx_send.add_argument("--amount", type=int, required=True)
    tx_send.add_argument("--password", required=True)
    tx_send.add_argument("--client-tx-id", default=None)
    tx_send.add_argument("--recipient-endpoint", default=None)
    tx_pending = tx_sub.add_parser("pending")
    tx_pending.add_argument("--password", required=True)
    tx_receipts = tx_sub.add_parser("receipts")
    tx_receipts.add_argument("--password", required=True)
    tx_sub.add_parser("history")

    tx_faucet = tx_sub.add_parser("faucet")
    tx_faucet.add_argument("--amount", type=int, required=True)
    tx_faucet.add_argument("--password", required=True)

    node = sub.add_parser("node")
    node_sub = node.add_subparsers(dest="node_cmd", required=True)
    n_start = node_sub.add_parser("start")
    n_start.add_argument("--consensus", type=int, default=None)
    n_start.add_argument("--accounts", type=int, default=None)
    n_start.add_argument("--start-port", type=int, default=None)
    n_start.add_argument(
        "--mode",
        choices=["auto", "local", "v2-localnet", "v2-tcp-consensus", "v2-consensus", "v2-account", "official-testnet"],
        default="auto",
    )
    node_sub.add_parser("stop")
    node_sub.add_parser("status")
    node_sub.add_parser("account-status")

    network = sub.add_parser("network")
    network_sub = network.add_subparsers(dest="network_cmd", required=True)
    network_sub.add_parser("info")
    network_sub.add_parser("check")
    network_sub.add_parser("list-profiles")
    n_profile = network_sub.add_parser("set-profile")
    n_profile.add_argument("--name", required=True, choices=list_profiles())

    auth = sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("show-token")

    contacts = sub.add_parser("contacts")
    contacts_sub = contacts.add_subparsers(dest="contacts_cmd", required=True)
    contacts_set = contacts_sub.add_parser("set")
    contacts_set.add_argument("--address", required=True)
    contacts_set.add_argument("--endpoint", required=True)
    contacts_set.add_argument("--network", default=None)
    contacts_set.add_argument("--mode-family", default=None)
    contacts_set.add_argument("--consensus-endpoint", default=None)
    contacts_set.add_argument("--source", default="manual")
    contacts_sub.add_parser("list")
    contacts_show = contacts_sub.add_parser("show")
    contacts_show.add_argument("--address", required=True)
    contacts_remove = contacts_sub.add_parser("remove")
    contacts_remove.add_argument("--address", required=True)
    contacts_export = contacts_sub.add_parser("export-self")
    contacts_export.add_argument("--out", default=None)
    contacts_fetch = contacts_sub.add_parser("fetch-card")
    contacts_fetch.add_argument("--url", required=True)
    contacts_fetch.add_argument("--out", default=None)
    contacts_fetch.add_argument("--import-to-contacts", action="store_true")
    contacts_import = contacts_sub.add_parser("import-card")
    contacts_import.add_argument("--file", required=True)

    cfg_cmd = sub.add_parser("config")
    cfg_sub = cfg_cmd.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("migrate")

    sub.add_parser("serve")

    args = parser.parse_args(argv)
    cfg, wallet_store, node_manager, tx_engine = _build_runtime(args.config)

    if args.cmd == "wallet":
        if args.wallet_cmd == "create":
            result = wallet_store.create_wallet(password=args.password, name=args.name)
            summary = wallet_store.summary(protocol_version=cfg.app.protocol_version)
            print(json.dumps({"address": summary.address, "mnemonic": result["mnemonic"]}, indent=2))
            return 0
        if args.wallet_cmd == "import":
            result = wallet_store.import_wallet(mnemonic=args.mnemonic, password=args.password, name=args.name)
            summary = wallet_store.summary(protocol_version=cfg.app.protocol_version)
            print(json.dumps({"address": summary.address}, indent=2))
            return 0
        if args.wallet_cmd == "show":
            summary = wallet_store.summary(protocol_version=cfg.app.protocol_version)
            print(json.dumps(summary.__dict__, indent=2))
            return 0
        if args.wallet_cmd == "balance":
            if not _tx_path_ready(cfg):
                remote_state = _remote_read_state(cfg, node_manager)
                if remote_state is None:
                    return _print_tx_path_not_ready(cfg, action="wallet balance")
                data = tx_engine.remote_balance(wallet_store, password=args.password, state=remote_state)
                print(json.dumps(data, indent=2))
                return 0
            data = tx_engine.balance(wallet_store, password=args.password)
            print(json.dumps(data, indent=2))
            return 0
        if args.wallet_cmd == "checkpoints":
            if not _tx_path_ready(cfg):
                remote_state = _remote_read_state(cfg, node_manager)
                if remote_state is None:
                    return _print_tx_path_not_ready(cfg, action="wallet checkpoints")
                data = tx_engine.remote_checkpoints(wallet_store, password=args.password, state=remote_state)
                print(json.dumps(data, indent=2))
                return 0
            data = tx_engine.checkpoints(wallet_store, password=args.password)
            print(json.dumps(data, indent=2))
            return 0

    if args.cmd == "tx":
        if args.tx_cmd == "faucet":
            if not _tx_path_ready(cfg):
                return _print_tx_path_not_ready(cfg, action="tx faucet")
            data = tx_engine.faucet(wallet_store, password=args.password, amount=args.amount)
            print(json.dumps(data, indent=2))
            return 0
        if args.tx_cmd == "send":
            if not _tx_path_ready(cfg):
                remote_state = _remote_read_state(cfg, node_manager)
                recipient_endpoint = str(args.recipient_endpoint or "").strip()
                if not recipient_endpoint:
                    recipient_endpoint = str(wallet_store.get_contact_endpoint(args.recipient) or "").strip()
                if remote_state is None or not recipient_endpoint:
                    return _print_tx_path_not_ready(cfg, action="tx send")
                result = tx_engine.send(
                    wallet_store=wallet_store,
                    password=args.password,
                    recipient=args.recipient,
                    amount=args.amount,
                    client_tx_id=args.client_tx_id,
                    state=remote_state,
                    recipient_endpoint=recipient_endpoint,
                )
            else:
                result = tx_engine.send(
                    wallet_store=wallet_store,
                    password=args.password,
                    recipient=args.recipient,
                    amount=args.amount,
                    client_tx_id=args.client_tx_id,
                )
            sender = wallet_store.summary(protocol_version=cfg.app.protocol_version).address
            item = {
                "tx_id": result.tx_hash,
                "submit_hash": result.submit_hash,
                "sender": sender,
                "recipient": result.recipient,
                "amount": result.amount,
                "status": result.status,
                "client_tx_id": result.client_tx_id,
            }
            if result.receipt_height is not None:
                item["receipt_height"] = result.receipt_height
            if result.receipt_block_hash is not None:
                item["receipt_block_hash"] = result.receipt_block_hash
            wallet_store.append_history(item)
            print(json.dumps(item, indent=2))
            return 0
        if args.tx_cmd == "pending":
            if not _tx_path_ready(cfg):
                remote_state = _remote_read_state(cfg, node_manager)
                if remote_state is None:
                    return _print_tx_path_not_ready(cfg, action="tx pending")
                print(json.dumps(tx_engine.remote_pending(wallet_store, password=args.password, state=remote_state), indent=2))
                return 0
            print(json.dumps(tx_engine.pending(wallet_store, password=args.password), indent=2))
            return 0
        if args.tx_cmd == "receipts":
            if not _tx_path_ready(cfg):
                remote_state = _remote_read_state(cfg, node_manager)
                if remote_state is None:
                    return _print_tx_path_not_ready(cfg, action="tx receipts")
                print(json.dumps(tx_engine.remote_receipts(wallet_store, password=args.password, state=remote_state), indent=2))
                return 0
            print(json.dumps(tx_engine.receipts(wallet_store, password=args.password), indent=2))
            return 0
        if args.tx_cmd == "history":
            if not _tx_path_ready(cfg):
                return _print_tx_path_not_ready(cfg, action="tx history")
            print(json.dumps({"items": wallet_store.get_history()}, indent=2))
            return 0

    if args.cmd == "contacts":
        if args.contacts_cmd == "set":
            item = wallet_store.set_contact(
                address=args.address,
                endpoint=args.endpoint,
                network=args.network,
                mode_family=args.mode_family,
                consensus_endpoint=args.consensus_endpoint,
                source=args.source,
            )
            print(json.dumps(item, indent=2))
            return 0
        if args.contacts_cmd == "list":
            print(json.dumps({"items": wallet_store.list_contacts()}, indent=2))
            return 0
        if args.contacts_cmd == "show":
            item = wallet_store.get_contact(args.address)
            if item is None:
                print(json.dumps({"ok": False, "error": {"code": "contact_not_found", "message": "Contact not found"}}, indent=2))
                return 1
            print(json.dumps(item, indent=2))
            return 0
        if args.contacts_cmd == "remove":
            removed = wallet_store.remove_contact(args.address)
            print(json.dumps({"removed": removed, "address": args.address}, indent=2))
            return 0
        if args.contacts_cmd == "export-self":
            card = build_contact_card(
                node_manager.account_status(bootstrap_nodes=cfg.network.bootstrap_nodes),
                network_name=cfg.network.name,
            )
            if args.out:
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
                print(json.dumps({"written": True, "path": str(out_path), "card": card}, indent=2))
                return 0
            print(json.dumps(card, indent=2))
            return 0
        if args.contacts_cmd == "fetch-card":
            card = fetch_contact_card(args.url)
            result = {
                "fetched": True,
                "source_url": args.url,
                "card": card,
            }
            if args.out:
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
                result["written"] = True
                result["path"] = str(out_path)
            if args.import_to_contacts:
                entry = contact_entry_from_card(card, source="service_fetch", fetched_from=args.url)
                saved = wallet_store.set_contact(**entry)
                result["imported"] = True
                result["contact"] = saved
            print(json.dumps(result, indent=2))
            return 0
        if args.contacts_cmd == "import-card":
            card = load_contact_card(args.file)
            saved = wallet_store.set_contact(**contact_entry_from_card(card, source="contact_card_file"))
            print(json.dumps({"imported": True, "contact": saved, "card": card}, indent=2))
            return 0

    if args.cmd == "node":
        if args.node_cmd == "start":
            consensus = args.consensus if args.consensus is not None else cfg.network.consensus_nodes
            accounts = args.accounts if args.accounts is not None else cfg.network.account_nodes
            start_port = args.start_port if args.start_port is not None else cfg.network.start_port
            mode = _network_mode(cfg) if args.mode == "auto" else args.mode
            print(
                json.dumps(
                    node_manager.start(
                        consensus=consensus,
                        accounts=accounts,
                        start_port=start_port,
                        mode=mode,
                        bootstrap_nodes=cfg.network.bootstrap_nodes,
                        network_name=cfg.network.name,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.node_cmd == "stop":
            print(json.dumps(node_manager.stop(), indent=2))
            return 0
        if args.node_cmd == "status":
            print(json.dumps(node_manager.status(bootstrap_nodes=cfg.network.bootstrap_nodes), indent=2))
            return 0
        if args.node_cmd == "account-status":
            print(json.dumps(node_manager.account_status(bootstrap_nodes=cfg.network.bootstrap_nodes), indent=2))
            return 0

    if args.cmd == "network" and args.network_cmd == "info":
        mode = _network_mode(cfg)
        probe = node_manager.probe_bootstrap(cfg.network.bootstrap_nodes) if cfg.network.bootstrap_nodes else None
        print(
            json.dumps(
                {
                    "network": cfg.network.name,
                    "mode": mode,
                    "mode_family": NodeManager._mode_family(mode),
                    "roles": _mode_roles(mode),
                    "bootstrap_nodes": cfg.network.bootstrap_nodes,
                    "consensus_nodes": cfg.network.consensus_nodes,
                    "account_nodes": cfg.network.account_nodes,
                    "start_port": cfg.network.start_port,
                    "bootstrap_probe": probe,
                    **_tx_path_info(cfg),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "network" and args.network_cmd == "check":
        mode = _network_mode(cfg)
        probe = node_manager.probe_bootstrap(cfg.network.bootstrap_nodes) if cfg.network.bootstrap_nodes else {
            "total": 0,
            "reachable": 0,
            "unreachable": 0,
            "all_reachable": False,
            "any_reachable": False,
            "checked": [],
        }
        print(
            json.dumps(
                {
                    "network": cfg.network.name,
                    "mode": mode,
                    "mode_family": NodeManager._mode_family(mode),
                    "roles": _mode_roles(mode),
                    "bootstrap_probe": probe,
                    **_tx_path_info(cfg),
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
        mode = _network_mode(updated_cfg)
        print(
            json.dumps(
                {
                    "status": "updated",
                    "profile": args.name,
                    "network": updated_cfg.network.name,
                    "mode": mode,
                    "mode_family": NodeManager._mode_family(mode),
                    "roles": _mode_roles(mode),
                    "bootstrap_nodes": updated_cfg.network.bootstrap_nodes,
                    "consensus_nodes": updated_cfg.network.consensus_nodes,
                    "account_nodes": updated_cfg.network.account_nodes,
                    "start_port": updated_cfg.network.start_port,
                    **_tx_path_info(updated_cfg),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "auth" and args.auth_cmd == "show-token":
        print(load_api_token(cfg))
        return 0

    if args.cmd == "config" and args.config_cmd == "migrate":
        print(json.dumps(migrate_config_file(args.config), indent=2))
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
            network_info={
                "name": cfg.network.name,
                "mode": _network_mode(cfg),
                "mode_family": NodeManager._mode_family(_network_mode(cfg)),
                "roles": _mode_roles(_network_mode(cfg)),
                "bootstrap_nodes": cfg.network.bootstrap_nodes,
                "consensus_nodes": cfg.network.consensus_nodes,
                "account_nodes": cfg.network.account_nodes,
                "start_port": cfg.network.start_port,
                **_tx_path_info(cfg),
            },
        ).run()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
