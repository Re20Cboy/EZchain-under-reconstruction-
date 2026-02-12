from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from EZ_App.config import CONFIG_SCHEMA_VERSION, EZAppConfig, load_config


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
    lines = [
        "meta:",
        f"  config_version: {int(getattr(cfg, 'config_version', CONFIG_SCHEMA_VERSION))}",
        "",
        "network:",
        f'  name: "{cfg.network.name}"',
        f"  bootstrap_nodes: {json.dumps(cfg.network.bootstrap_nodes)}",
        f"  consensus_nodes: {int(cfg.network.consensus_nodes)}",
        f"  account_nodes: {int(cfg.network.account_nodes)}",
        f"  start_port: {int(cfg.network.start_port)}",
        "",
        "app:",
        f'  data_dir: "{cfg.app.data_dir}"',
        f'  log_dir: "{cfg.app.log_dir}"',
        f'  api_host: "{cfg.app.api_host}"',
        f"  api_port: {int(cfg.app.api_port)}",
        f'  api_token_file: "{cfg.app.api_token_file}"',
        "",
        "security:",
        f"  max_payload_bytes: {int(cfg.security.max_payload_bytes)}",
        f"  max_tx_amount: {int(cfg.security.max_tx_amount)}",
        f"  nonce_ttl_seconds: {int(cfg.security.nonce_ttl_seconds)}",
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
