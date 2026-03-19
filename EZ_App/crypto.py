from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Lightweight embedded word list for mnemonic generation.
WORDLIST: List[str] = [
    "able", "about", "absorb", "access", "account", "acid", "across", "action", "adapt", "adult",
    "agent", "ahead", "aim", "air", "album", "alert", "alpha", "amazing", "anchor", "angle",
    "animal", "answer", "apple", "april", "archive", "arena", "argue", "arise", "arrow", "artist",
    "asset", "atom", "august", "author", "auto", "awake", "badge", "balance", "banana", "banner",
    "base", "basic", "beach", "beauty", "become", "before", "begin", "behind", "belief", "below",
    "benefit", "best", "beyond", "bicycle", "bird", "black", "blend", "bless", "blue", "board",
    "bonus", "border", "borrow", "boss", "bottom", "brain", "brand", "brave", "bread", "breeze",
    "brief", "bright", "bring", "broad", "brother", "budget", "build", "burst", "business", "button",
    "cable", "camera", "camp", "canal", "candy", "capital", "carbon", "care", "cargo", "carpet",
    "carry", "castle", "casual", "cause", "center", "chain", "chair", "change", "charge", "chase",
    "check", "chief", "choice", "city", "civil", "claim", "class", "clean", "clear", "client",
    "clock", "close", "cloud", "coach", "coast", "coffee", "coin", "collect", "color", "column",
    "combine", "comfort", "common", "company", "concert", "confirm", "connect", "control", "cook", "copy",
    "corner", "cost", "cotton", "course", "cover", "craft", "crash", "create", "credit", "crew",
    "cross", "crystal", "culture", "custom", "cycle", "daily", "damage", "danger", "data", "day",
    "debate", "decide", "deep", "defend", "degree", "deliver", "demand", "design", "detail", "device",
    "dialog", "digital", "dinner", "direct", "discover", "display", "distance", "doctor", "domain", "double",
    "draft", "dragon", "dream", "drift", "drill", "driver", "drop", "duty", "eager", "early",
    "earth", "easily", "echo", "economy", "edge", "edit", "educate", "effect", "effort", "eight",
    "either", "electric", "element", "elite", "else", "embark", "emerge", "emotion", "employ", "enable",
    "energy", "engine", "enhance", "enjoy", "enough", "enter", "entire", "entry", "equal", "error",
    "escape", "essay", "estate", "ethics", "event", "every", "evidence", "exact", "example", "exchange",
    "excite", "execute", "exist", "expand", "expect", "expert", "explain", "explore", "export", "extend",
]

SECP256R1_ORDER = int(
    "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16
)
PRIME256V1_OID_DER = b"\x06\x08\x2A\x86\x48\xCE\x3D\x03\x01\x07"


@dataclass
class DerivedKeypair:
    mnemonic: str
    private_key_pem: bytes
    public_key_pem: bytes
    address: str


def _run_openssl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["openssl", *args],
        check=True,
        capture_output=True,
        text=False,
    )


def _der_encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, byteorder="big", signed=False)
    return bytes([0x80 | len(raw)]) + raw


def _encode_der_integer(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), byteorder="big", signed=False)
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + _der_encode_length(len(raw)) + raw


def _encode_octet_string(data: bytes) -> bytes:
    return b"\x04" + _der_encode_length(len(data)) + data


def _encode_sequence(*parts: bytes) -> bytes:
    body = b"".join(parts)
    return b"\x30" + _der_encode_length(len(body)) + body


def _encode_explicit(tag_number: int, payload: bytes) -> bytes:
    return bytes([0xA0 + tag_number]) + _der_encode_length(len(payload)) + payload


def _pem_wrap(label: str, der_bytes: bytes) -> bytes:
    encoded = base64.encodebytes(der_bytes).replace(b"\n", b"")
    lines = [encoded[index:index + 64] for index in range(0, len(encoded), 64)]
    body = b"\n".join(lines)
    return (
        f"-----BEGIN {label}-----\n".encode("ascii")
        + body
        + f"\n-----END {label}-----\n".encode("ascii")
    )


def _pem_to_der(pem_bytes: bytes) -> bytes:
    lines = []
    for raw_line in pem_bytes.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith(b"-----"):
            continue
        lines.append(line)
    if not lines:
        raise ValueError("invalid PEM bytes")
    return base64.b64decode(b"".join(lines))


def generate_mnemonic(words: int = 12) -> str:
    if words < 12:
        raise ValueError("mnemonic words must be >= 12")
    return " ".join(secrets.choice(WORDLIST) for _ in range(words))


def _seed_from_mnemonic(mnemonic: str, passphrase: str = "") -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        mnemonic.encode("utf-8"),
        ("ezchain-mnemonic-" + passphrase).encode("utf-8"),
        200_000,
        dklen=32,
    )


def address_from_public_key(public_key_pem: bytes) -> str:
    der = _pem_to_der(public_key_pem)
    return "0x" + hashlib.sha256(der).hexdigest()[:40]


def derive_keypair(mnemonic: str, passphrase: str = "") -> DerivedKeypair:
    seed = _seed_from_mnemonic(mnemonic, passphrase)
    secret_int = (int.from_bytes(seed, "big") % (SECP256R1_ORDER - 1)) + 1
    private_key_bytes = secret_int.to_bytes(32, byteorder="big", signed=False)
    private_der = _encode_sequence(
        _encode_der_integer(1),
        _encode_octet_string(private_key_bytes),
        _encode_explicit(0, PRIME256V1_OID_DER),
    )
    private_pem = _pem_wrap("EC PRIVATE KEY", private_der)

    with tempfile.TemporaryDirectory() as tmpdir:
        priv_path = Path(tmpdir) / "key.pem"
        pub_path = Path(tmpdir) / "pub.pem"
        priv_path.write_bytes(private_pem)
        _run_openssl("ec", "-in", str(priv_path), "-pubout", "-out", str(pub_path))
        public_pem = pub_path.read_bytes()

    return DerivedKeypair(
        mnemonic=mnemonic,
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        address=address_from_public_key(public_pem),
    )


def _password_key_material(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000,
        dklen=32,
    )


def password_to_fernet_key(password: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(_password_key_material(password, salt))


def _stream_xor(key: bytes, nonce: bytes, data: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hmac.new(
            key,
            nonce + counter.to_bytes(4, byteorder="big", signed=False),
            hashlib.sha256,
        ).digest()
        output.extend(block)
        counter += 1
    return bytes(left ^ right for left, right in zip(data, output[:len(data)]))


def encrypt_text(plain_text: str, password: str, salt: Optional[bytes] = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _password_key_material(password, salt)
    ciphertext = _stream_xor(key, nonce, plain_text.encode("utf-8"))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    payload = nonce + tag + ciphertext
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": base64.b64encode(payload).decode("ascii"),
    }


def decrypt_text(ciphertext: str, password: str, salt_b64: str) -> str:
    salt = base64.b64decode(salt_b64.encode("ascii"))
    payload = base64.b64decode(ciphertext.encode("ascii"))
    if len(payload) < 48:
        raise ValueError("invalid ciphertext")
    nonce = payload[:16]
    tag = payload[16:48]
    body = payload[48:]
    key = _password_key_material(password, salt)
    expected_tag = hmac.new(key, nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("invalid password or ciphertext")
    return _stream_xor(key, nonce, body).decode("utf-8")
