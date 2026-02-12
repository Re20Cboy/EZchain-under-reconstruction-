from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from EZ_App.config import CONFIG_SCHEMA_VERSION, EZAppConfig, load_config


PROFILE_TEMPLATES: Dict[str, str] = {
    "local-dev": "ezchain.local-dev.yaml",
    "official-testnet": "ezchain.official-testnet.yaml",
}

DEFAULT_NETWORK_SETTINGS: Dict[str, Dict[str, object]] = {
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
    return sorted(PROFILE_TEMPLATES.keys())


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_profile_template_path(profile_name: str) -> Path:
    filename = PROFILE_TEMPLATES.get(profile_name)
    if not filename:
        raise ValueError(f"unknown_profile:{profile_name}")
    path = _project_root() / "configs" / filename
    if not path.exists():
        raise FileNotFoundError(f"profile_template_missing:{path}")
    return path


def _profile_network_settings(profile_name: str) -> Dict[str, object]:
    if profile_name not in DEFAULT_NETWORK_SETTINGS:
        raise ValueError(f"unknown_profile:{profile_name}")

    try:
        cfg = load_config(get_profile_template_path(profile_name))
        return {
            "name": cfg.network.name,
            "bootstrap_nodes": list(cfg.network.bootstrap_nodes),
            "consensus_nodes": int(cfg.network.consensus_nodes),
            "account_nodes": int(cfg.network.account_nodes),
            "start_port": int(cfg.network.start_port),
        }
    except FileNotFoundError:
        fallback = DEFAULT_NETWORK_SETTINGS[profile_name]
        return {
            "name": str(fallback["name"]),
            "bootstrap_nodes": list(fallback["bootstrap_nodes"]),
            "consensus_nodes": int(fallback["consensus_nodes"]),
            "account_nodes": int(fallback["account_nodes"]),
            "start_port": int(fallback["start_port"]),
        }


def write_profile_template(config_path: str | Path, profile_name: str, force: bool = False) -> Path:
    template_path = get_profile_template_path(profile_name)
    output_path = Path(config_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"target_exists:{output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    return output_path


def apply_network_profile(config_path: str | Path, profile_name: str) -> EZAppConfig:
    cfg = load_config(config_path)
    for key, value in _profile_network_settings(profile_name).items():
        setattr(cfg.network, key, value)

    path = Path(config_path)
    path.write_text(_to_yaml(cfg), encoding="utf-8")
    return cfg
