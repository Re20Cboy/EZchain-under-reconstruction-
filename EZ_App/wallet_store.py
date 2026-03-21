from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from EZ_App.crypto import decrypt_text, derive_keypair, encrypt_text, generate_mnemonic
from EZ_V2.crypto import address_from_public_key_pem, derive_secp256k1_keypair_from_mnemonic


@dataclass
class WalletSummary:
    address: str
    name: str
    created_at: str


class WalletStore:
    def __init__(self, data_dir: str):
        self.base_dir = Path(data_dir)
        self.wallet_file = self.base_dir / "wallet.json"
        self.history_file = self.base_dir / "tx_history.json"
        self.contacts_file = self.base_dir / "contacts.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        return self.wallet_file.exists()

    def _load_wallet_payload(self) -> Dict[str, Any]:
        if not self.wallet_file.exists():
            raise FileNotFoundError("wallet not found")
        return json.loads(self.wallet_file.read_text(encoding="utf-8"))

    def create_wallet(self, password: str, name: str = "default", mnemonic: Optional[str] = None) -> Dict[str, Any]:
        mnemonic = mnemonic or generate_mnemonic()
        derived = derive_keypair(mnemonic)

        enc_priv = encrypt_text(derived.private_key_pem.decode("utf-8"), password)
        payload = {
            "name": name,
            "address": derived.address,
            "public_key_pem": derived.public_key_pem.decode("utf-8"),
            "encrypted_private_key": enc_priv,
            "mnemonic": mnemonic,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.wallet_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding="utf-8")

        return payload

    def import_wallet(self, mnemonic: str, password: str, name: str = "default") -> Dict[str, Any]:
        return self.create_wallet(password=password, name=name, mnemonic=mnemonic)

    def load_wallet(self, password: str) -> Dict[str, Any]:
        payload = self._load_wallet_payload()
        enc = payload["encrypted_private_key"]
        private_key_pem = decrypt_text(
            ciphertext=enc["ciphertext"],
            password=password,
            salt_b64=enc["salt"],
        )

        result = dict(payload)
        result["private_key_pem"] = private_key_pem
        return result

    def load_v2_wallet(self, password: str) -> Dict[str, Any]:
        payload = self.load_wallet(password=password)
        private_key_pem, public_key_pem = derive_secp256k1_keypair_from_mnemonic(payload["mnemonic"])
        result = dict(payload)
        result["legacy_address"] = payload["address"]
        result["address"] = address_from_public_key_pem(public_key_pem)
        result["private_key_pem"] = private_key_pem.decode("utf-8")
        result["public_key_pem"] = public_key_pem.decode("utf-8")
        return result

    def load_protocol_wallet(self, password: str, protocol_version: str = "v1") -> Dict[str, Any]:
        version = str(protocol_version or "v1").lower()
        if version == "v2":
            return self.load_v2_wallet(password=password)
        if version != "v1":
            raise ValueError("unsupported protocol_version")
        return self.load_wallet(password=password)

    def summary(self, protocol_version: str = "v1") -> WalletSummary:
        payload = self._load_wallet_payload()
        version = str(protocol_version or "v1").lower()
        if version == "v2":
            _, public_key_pem = derive_secp256k1_keypair_from_mnemonic(payload["mnemonic"])
            address = address_from_public_key_pem(public_key_pem)
        elif version == "v1":
            address = payload["address"]
        else:
            raise ValueError("unsupported protocol_version")
        return WalletSummary(
            address=address,
            name=payload.get("name", "default"),
            created_at=payload.get("created_at", ""),
        )

    def append_history(self, record: Dict[str, Any]) -> None:
        history = self.get_history()
        history.append(record)
        self.history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def get_history(self) -> List[Dict[str, Any]]:
        if not self.history_file.exists():
            return []
        try:
            return json.loads(self.history_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _load_contacts(self) -> Dict[str, Dict[str, Any]]:
        if not self.contacts_file.exists():
            return {}
        try:
            parsed = json.loads(self.contacts_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for address, item in parsed.items():
            if not isinstance(item, dict):
                continue
            normalized_address = str(item.get("address", address)).strip()
            entry = {
                "address": normalized_address,
                "endpoint": str(item.get("endpoint", "")).strip(),
                "updated_at": str(item.get("updated_at", "")),
            }
            network = str(item.get("network", "")).strip()
            if network:
                entry["network"] = network
            mode_family = str(item.get("mode_family", "")).strip()
            if mode_family:
                entry["mode_family"] = mode_family
            consensus_endpoint = str(item.get("consensus_endpoint", "")).strip()
            if consensus_endpoint:
                entry["consensus_endpoint"] = consensus_endpoint
            source = str(item.get("source", "")).strip()
            if source:
                entry["source"] = source
            fetched_from = str(item.get("fetched_from", "")).strip()
            if fetched_from:
                entry["fetched_from"] = fetched_from
            normalized[normalized_address] = entry
        return normalized

    def _save_contacts(self, contacts: Dict[str, Dict[str, Any]]) -> None:
        self.contacts_file.write_text(json.dumps(contacts, indent=2), encoding="utf-8")

    def set_contact(
        self,
        *,
        address: str,
        endpoint: str,
        network: str | None = None,
        mode_family: str | None = None,
        consensus_endpoint: str | None = None,
        source: str | None = None,
        fetched_from: str | None = None,
    ) -> Dict[str, Any]:
        if not str(address).strip():
            raise ValueError("address_required")
        if not str(endpoint).strip():
            raise ValueError("endpoint_required")
        contacts = self._load_contacts()
        normalized_address = str(address).strip()
        entry = {
            "address": normalized_address,
            "endpoint": str(endpoint).strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if str(network or "").strip():
            entry["network"] = str(network).strip()
        if str(mode_family or "").strip():
            entry["mode_family"] = str(mode_family).strip()
        if str(consensus_endpoint or "").strip():
            entry["consensus_endpoint"] = str(consensus_endpoint).strip()
        if str(source or "").strip():
            entry["source"] = str(source).strip()
        if str(fetched_from or "").strip():
            entry["fetched_from"] = str(fetched_from).strip()
        contacts[normalized_address] = entry
        self._save_contacts(contacts)
        return dict(entry)

    def get_contact(self, address: str) -> Optional[Dict[str, Any]]:
        contacts = self._load_contacts()
        item = contacts.get(str(address).strip())
        if item is None:
            return None
        return dict(item)

    def get_contact_endpoint(self, address: str) -> Optional[str]:
        item = self.get_contact(address)
        if item is None:
            return None
        endpoint = str(item.get("endpoint", "")).strip()
        return endpoint or None

    def remove_contact(self, address: str) -> bool:
        contacts = self._load_contacts()
        normalized_address = str(address).strip()
        removed = contacts.pop(normalized_address, None)
        self._save_contacts(contacts)
        return removed is not None

    def list_contacts(self) -> List[Dict[str, Any]]:
        contacts = self._load_contacts()
        return [dict(contacts[address]) for address in sorted(contacts)]
