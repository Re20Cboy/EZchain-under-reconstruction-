from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from EZ_App.crypto import decrypt_text, derive_keypair, encrypt_text, generate_mnemonic


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
            "created_at": __import__("datetime").datetime.utcnow().isoformat(),
        }
        self.wallet_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding="utf-8")

        return payload

    def import_wallet(self, mnemonic: str, password: str, name: str = "default") -> Dict[str, Any]:
        return self.create_wallet(password=password, name=name, mnemonic=mnemonic)

    def load_wallet(self, password: str) -> Dict[str, Any]:
        if not self.wallet_file.exists():
            raise FileNotFoundError("wallet not found")

        payload = json.loads(self.wallet_file.read_text(encoding="utf-8"))
        enc = payload["encrypted_private_key"]
        private_key_pem = decrypt_text(
            ciphertext=enc["ciphertext"],
            password=password,
            salt_b64=enc["salt"],
        )

        result = dict(payload)
        result["private_key_pem"] = private_key_pem
        return result

    def summary(self) -> WalletSummary:
        if not self.wallet_file.exists():
            raise FileNotFoundError("wallet not found")
        payload = json.loads(self.wallet_file.read_text(encoding="utf-8"))
        return WalletSummary(
            address=payload["address"],
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
