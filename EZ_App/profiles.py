from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict

from EZ_App.config import EZAppConfig, load_config


NETWORK_PROFILES: Dict[str, Dict[str, object]] = {
    "local-dev": {
        "name": "testnet-local",
        "bootstrap_nodes": ["127.0.0.1:19500"],
        "consensus_nodes": 1,
        "account_nodes": 1,
        "start_port": 19500,
    },
    "official-testnet": {
        "name": "testnet",
        "bootstrap_nodes": ["bootstrap.ezchain.test:19500"],
        "consensus_nodes": 3,
        "account_nodes": 1,
        "start_port": 19500,
    },
}


def _to_yaml(cfg: EZAppConfig) -> str:
    network = asdict(cfg.network)
    app = asdict(cfg.app)
    security = asdict(cfg.security)
    lines = [
        "network:",
        f'  name: "{network["name"]}"',
        f'  bootstrap_nodes: {json.dumps(network["bootstrap_nodes"])}',
        f'  consensus_nodes: {network["consensus_nodes"]}',
        f'  account_nodes: {network["account_nodes"]}',
        f'  start_port: {network["start_port"]}',
        "",
        "app:",
        f'  data_dir: "{app["data_dir"]}"',
        f'  log_dir: "{app["log_dir"]}"',
        f'  api_host: "{app["api_host"]}"',
        f'  api_port: {app["api_port"]}',
        f'  api_token_file: "{app["api_token_file"]}"',
        "",
        "security:",
        f'  max_payload_bytes: {security["max_payload_bytes"]}',
        f'  max_tx_amount: {security["max_tx_amount"]}',
        f'  nonce_ttl_seconds: {security["nonce_ttl_seconds"]}',
    ]
    return "\n".join(lines) + "\n"


def list_profiles() -> list[str]:
    return sorted(NETWORK_PROFILES.keys())


def apply_network_profile(config_path: str | Path, profile_name: str) -> EZAppConfig:
    if profile_name not in NETWORK_PROFILES:
        raise ValueError(f"unknown_profile:{profile_name}")

    cfg = load_config(config_path)
    for key, value in NETWORK_PROFILES[profile_name].items():
        setattr(cfg.network, key, value)

    path = Path(config_path)
    path.write_text(_to_yaml(cfg), encoding="utf-8")
    return cfg
