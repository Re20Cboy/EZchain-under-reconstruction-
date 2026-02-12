from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class P2PConfig:
    node_role: str = "account"  # consensus|account|pool_gateway
    listen_host: str = "127.0.0.1"
    listen_port: int = 19001
    transport: str = "tcp"  # tcp|libp2p
    peer_seeds: List[str] = field(default_factory=list)  # ["host:port"]
    network_id: str = "devnet"
    protocol_version: str = "0.1"
    max_neighbors: int = 8
    dial_timeout_ms: int = 3000
    send_timeout_ms: int = 3000
    retry_count: int = 2
    retry_backoff_ms: int = 300
    msg_size_limit_bytes: int = 2 * 1024 * 1024
    dedup_window_ms: int = 5 * 60 * 1000
    node_id: Optional[str] = None  # can be public key fingerprint or uuid
    identity_private_key_pem: Optional[str] = None
    identity_public_key_pem: Optional[str] = None
    enforce_identity_verification: bool = False
    signed_message_types: List[str] = field(default_factory=list)
    maintenance_interval_sec: float = 5.0
    seed_retry_base_sec: float = 1.0
    seed_retry_max_sec: float = 30.0
    degraded_no_peer_sec: float = 20.0
    # libp2p specific
    libp2p_control_path: Optional[str] = None  # e.g., "/tmp/p2pd.sock" or ":/ip4/127.0.0.1/tcp/9999"
    libp2p_protocol: str = "/ez/1.0.0"
    libp2p_bootstrap: List[str] = field(default_factory=list)  # multiaddrs

    @staticmethod
    def from_dict(d: dict) -> "P2PConfig":
        return P2PConfig(**d)
