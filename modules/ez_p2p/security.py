from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key


SUPPORTED_ALGORITHM = "ecdsa-p256-sha256"


def _to_bytes(pem: str | bytes) -> bytes:
    if isinstance(pem, bytes):
        return pem
    return pem.encode("utf-8")


def canonical_envelope_payload(envelope: Dict[str, Any]) -> bytes:
    payload = {
        "version": envelope.get("version", ""),
        "network": envelope.get("network", ""),
        "type": envelope.get("type", ""),
        "msg_id": envelope.get("msg_id", ""),
        "timestamp": envelope.get("timestamp", 0),
        "sender_id": envelope.get("sender_id", ""),
        "payload": envelope.get("payload", {}),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def fingerprint_public_key(public_key_pem: str | bytes) -> str:
    pub = _to_bytes(public_key_pem)
    return hashlib.sha256(pub).hexdigest()


def derive_public_key_pem(private_key_pem: str | bytes) -> str:
    private_key = load_pem_private_key(_to_bytes(private_key_pem), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("identity_private_key_must_be_ec")
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_bytes.decode("utf-8")


def sign_envelope(envelope: Dict[str, Any], private_key_pem: str | bytes) -> str:
    private_key = load_pem_private_key(_to_bytes(private_key_pem), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("identity_private_key_must_be_ec")

    digest = hashlib.sha256(canonical_envelope_payload(envelope)).digest()
    signature = private_key.sign(digest, ec.ECDSA(hashes.SHA256()))
    return signature.hex()


def verify_envelope_signature(
    envelope: Dict[str, Any],
    signature_hex: str,
    public_key_pem: str | bytes,
) -> bool:
    try:
        public_key = load_pem_public_key(_to_bytes(public_key_pem))
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        digest = hashlib.sha256(canonical_envelope_payload(envelope)).digest()
        public_key.verify(bytes.fromhex(signature_hex), digest, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
