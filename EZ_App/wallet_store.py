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
