#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from EZ_App.config import load_config
from EZ_App.node_manager import NodeManager


def _endpoint_host(endpoint: str) -> str:
    return str(endpoint).split(":", 1)[0].strip().lower()


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost"}


def validate_official_profile(config_path: Path, check_connectivity: bool, allow_unreachable: bool) -> Dict[str, Any]:
    cfg = load_config(config_path)
    failures: List[str] = []

    if cfg.network.name != "testnet":
        failures.append("network.name must be 'testnet'")
    if int(cfg.network.consensus_nodes) != 3:
        failures.append("network.consensus_nodes must be 3")
    if int(cfg.network.account_nodes) != 1:
        failures.append("network.account_nodes must be 1")
    if not cfg.network.bootstrap_nodes:
        failures.append("network.bootstrap_nodes must not be empty")

    for endpoint in cfg.network.bootstrap_nodes:
        host = _endpoint_host(endpoint)
        if _is_loopback_host(host):
            failures.append(f"bootstrap node must be non-loopback for official profile: {endpoint}")

    probe = None
    if check_connectivity and cfg.network.bootstrap_nodes:
        manager = NodeManager(data_dir=cfg.app.data_dir, project_root=str(config_path.parent))
        probe = manager.probe_bootstrap(cfg.network.bootstrap_nodes, timeout_sec=1.5)
        if not probe.get("any_reachable", False) and not allow_unreachable:
            failures.append("no bootstrap nodes reachable")

    return {
        "ok": len(failures) == 0,
        "config": str(config_path),
        "network": cfg.network.name,
        "bootstrap_nodes": cfg.network.bootstrap_nodes,
        "consensus_nodes": int(cfg.network.consensus_nodes),
        "account_nodes": int(cfg.network.account_nodes),
        "check_connectivity": check_connectivity,
        "probe": probe,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate official testnet profile constraints")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--check-connectivity", action="store_true")
    parser.add_argument("--allow-unreachable", action="store_true")
    args = parser.parse_args()

    result = validate_official_profile(
        config_path=Path(args.config),
        check_connectivity=args.check_connectivity,
        allow_unreachable=args.allow_unreachable,
    )
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        print("[testnet-profile-gate] FAILED")
        return 1
    print("[testnet-profile-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
