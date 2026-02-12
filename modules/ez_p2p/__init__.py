"""EZchain minimal P2P module (MVP).

This package provides a minimal, standalone P2P implementation with:
- TCP transport (asyncio) with length-prefixed JSON framing
- Simple Router with handler registry
- PeerManager for connections and metadata
- Basic messages: HELLO/WELCOME, PING/PONG, ACCTXN_SUBMIT (stub)
- Optional identity envelope signing and verification

It is intentionally small and dependency-free to satisfy the
"最基础，最简单的实现" requirement.
"""

__all__ = [
    "config",
    "logger",
    "peer_manager",
    "router",
    "transport",
    "codec",
    "security",
]
