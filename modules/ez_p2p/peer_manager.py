from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class PeerInfo:
    node_id: str
    role: str  # consensus|account|pool_gateway
    network_id: str
    latest_index: int
    address: str  # host:port


class PeerManager:
    def __init__(self, max_neighbors: int = 8):
        self.max_neighbors = max_neighbors
        self._peers: Dict[str, PeerInfo] = {}

    def add_peer(self, peer: PeerInfo):
        if len(self._peers) >= self.max_neighbors:
            return False
        self._peers[peer.node_id] = peer
        return True

    def remove_peer(self, node_id: str):
        self._peers.pop(node_id, None)

    def list_peers(self) -> List[PeerInfo]:
        return list(self._peers.values())

    def select_by_role(self, role: str) -> List[PeerInfo]:
        return [p for p in self._peers.values() if p.role == role]

    def get(self, node_id: str) -> Optional[PeerInfo]:
        return self._peers.get(node_id)

