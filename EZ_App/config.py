from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_CONFIG = {
    "network": {
        "name": "testnet",
        "bootstrap_nodes": ["127.0.0.1:19500"],
        "consensus_nodes": 1,
        "account_nodes": 1,
        "start_port": 19500,
    },
    "app": {
        "data_dir": ".ezchain",
        "log_dir": ".ezchain/logs",
        "api_host": "127.0.0.1",
        "api_port": 8787,
        "api_token_file": ".ezchain/api.token",
    },
    "security": {
        "max_payload_bytes": 65536,
        "max_tx_amount": 100000000,
        "nonce_ttl_seconds": 600,
    },
}


@dataclass
class NetworkConfig:
    name: str = "testnet"
    bootstrap_nodes: List[str] = field(default_factory=lambda: ["127.0.0.1:19500"])
    consensus_nodes: int = 1
    account_nodes: int = 1
    start_port: int = 19500


@dataclass
class AppConfig:
    data_dir: str = ".ezchain"
    log_dir: str = ".ezchain/logs"
    api_host: str = "127.0.0.1"
    api_port: int = 8787
    api_token_file: str = ".ezchain/api.token"


@dataclass
class EZAppConfig:
    network: NetworkConfig = field(default_factory=NetworkConfig)
    app: AppConfig = field(default_factory=AppConfig)
    security: "SecurityConfig" = field(default_factory=lambda: SecurityConfig())


@dataclass
class SecurityConfig:
    max_payload_bytes: int = 65536
    max_tx_amount: int = 100000000
    nonce_ttl_seconds: int = 600


def _parse_min_yaml(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    current_section: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_section = line[:-1].strip()
            result[current_section] = {}
            continue
        if current_section and line.startswith("  ") and ":" in line:
            key, val = line.strip().split(":", 1)
            value = val.strip()
            if value.startswith("[") and value.endswith("]"):
                parsed = json.loads(value)
            elif value.lower() in {"true", "false"}:
                parsed = value.lower() == "true"
            else:
                try:
                    parsed = int(value)
                except ValueError:
                    parsed = value.strip('"')
            result[current_section][key] = parsed
    return result


def load_config(path: str | Path = "ezchain.yaml") -> EZAppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return EZAppConfig()

    text = config_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _parse_min_yaml(text)

    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for section in ("network", "app", "security"):
        if section in data and isinstance(data[section], dict):
            merged[section].update(data[section])

    return EZAppConfig(
        network=NetworkConfig(**merged["network"]),
        app=AppConfig(**merged["app"]),
        security=SecurityConfig(**merged["security"]),
    )


def ensure_directories(cfg: EZAppConfig) -> None:
    data_dir = Path(cfg.app.data_dir)
    log_dir = Path(cfg.app.log_dir)
    token_file = Path(cfg.app.api_token_file)

    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)

    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(24), encoding="utf-8")


def load_api_token(cfg: EZAppConfig) -> str:
    token_file = Path(cfg.app.api_token_file)
    if not token_file.exists():
        ensure_directories(cfg)
    return token_file.read_text(encoding="utf-8").strip()
