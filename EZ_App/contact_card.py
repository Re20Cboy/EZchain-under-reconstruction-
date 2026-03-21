from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.request import urlopen
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def build_contact_card(state: Dict[str, Any], *, network_name: str) -> Dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("invalid_account_state")
    if state.get("status") != "running":
        raise ValueError("v2_account_not_running")
    if state.get("mode_family") != "v2-account":
        raise ValueError("account_role_not_running")
    address = str(state.get("address", "")).strip()
    endpoint = str(state.get("endpoint", "")).strip()
    if not address:
        raise ValueError("account_address_missing")
    if not endpoint:
        raise ValueError("account_endpoint_missing")
    card = {
        "kind": "ezchain-contact-card/v1",
        "address": address,
        "endpoint": endpoint,
        "network": str(network_name or "testnet"),
        "mode_family": "v2-account",
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    consensus_endpoint = str(state.get("consensus_endpoint", "")).strip()
    if consensus_endpoint:
        card["consensus_endpoint"] = consensus_endpoint
    return card


def normalize_contact_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("invalid_contact_card")
    address = str(payload.get("address", "")).strip()
    endpoint = str(payload.get("endpoint", "")).strip()
    if not address:
        raise ValueError("contact_card_address_missing")
    if not endpoint:
        raise ValueError("contact_card_endpoint_missing")
    card = {
        "kind": str(payload.get("kind", "ezchain-contact-card/v1")),
        "address": address,
        "endpoint": endpoint,
        "network": str(payload.get("network", "testnet")),
        "mode_family": str(payload.get("mode_family", "v2-account")),
        "exported_at": str(payload.get("exported_at", "")),
    }
    consensus_endpoint = str(payload.get("consensus_endpoint", "")).strip()
    if consensus_endpoint:
        card["consensus_endpoint"] = consensus_endpoint
    return card


def load_contact_card(path: str | Path) -> Dict[str, Any]:
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    return normalize_contact_card(parsed)


def contact_entry_from_card(card: Dict[str, Any], *, source: str, fetched_from: str | None = None) -> Dict[str, Any]:
    normalized = normalize_contact_card(card)
    entry = {
        "address": normalized["address"],
        "endpoint": normalized["endpoint"],
        "network": normalized.get("network", ""),
        "mode_family": normalized.get("mode_family", ""),
        "source": str(source).strip(),
    }
    consensus_endpoint = str(normalized.get("consensus_endpoint", "")).strip()
    if consensus_endpoint:
        entry["consensus_endpoint"] = consensus_endpoint
    if str(fetched_from or "").strip():
        entry["fetched_from"] = str(fetched_from).strip()
    return entry


def contact_card_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("contact_card_url_required")
    parsed = urlparse(raw)
    if not parsed.scheme:
        raw = f"http://{raw}"
        parsed = urlparse(raw)
    if not parsed.path or parsed.path == "/":
        return parsed._replace(path="/node/contact-card", query="", fragment="").geturl()
    return parsed.geturl()


def fetch_contact_card(url: str, timeout_sec: float = 5.0) -> Dict[str, Any]:
    target = contact_card_url(url)
    with urlopen(target, timeout=max(0.5, float(timeout_sec))) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("ok") is True and isinstance(payload.get("data"), dict):
        return normalize_contact_card(payload["data"])
    return normalize_contact_card(payload)
