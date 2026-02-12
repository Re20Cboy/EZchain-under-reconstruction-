from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

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


@dataclass
class DerivedKeypair:
    mnemonic: str
    private_key_pem: bytes
    public_key_pem: bytes
    address: str


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
    pub = serialization.load_pem_public_key(public_key_pem)
    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "0x" + hashlib.sha256(der).hexdigest()[:40]


def derive_keypair(mnemonic: str, passphrase: str = "") -> DerivedKeypair:
    seed = _seed_from_mnemonic(mnemonic, passphrase)
    secret_int = (int.from_bytes(seed, "big") % (SECP256R1_ORDER - 1)) + 1
    private_key = ec.derive_private_key(secret_int, ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return DerivedKeypair(
        mnemonic=mnemonic,
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        address=address_from_public_key(public_pem),
    )


def password_to_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def encrypt_text(plain_text: str, password: str, salt: Optional[bytes] = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    f = Fernet(password_to_fernet_key(password, salt))
    token = f.encrypt(plain_text.encode("utf-8"))
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token.decode("ascii"),
    }


def decrypt_text(ciphertext: str, password: str, salt_b64: str) -> str:
    salt = base64.b64decode(salt_b64.encode("ascii"))
    f = Fernet(password_to_fernet_key(password, salt))
    data = f.decrypt(ciphertext.encode("ascii"))
    return data.decode("utf-8")
