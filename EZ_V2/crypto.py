from __future__ import annotations

import base64
import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple


SECP256K1_ORDER = int(
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141",
    16,
)
LOW_S_MAX = SECP256K1_ORDER // 2


def keccak256(data: bytes) -> bytes:
    return hashlib.new("keccak-256", data).digest()


def _run_openssl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["openssl", *args],
        check=True,
        capture_output=True,
        text=False,
    )


def generate_secp256k1_keypair() -> Tuple[bytes, bytes]:
    with tempfile.TemporaryDirectory() as tmpdir:
        priv_path = Path(tmpdir) / "key.pem"
        pub_path = Path(tmpdir) / "pub.pem"
        _run_openssl("ecparam", "-name", "secp256k1", "-genkey", "-noout", "-out", str(priv_path))
        _run_openssl("ec", "-in", str(priv_path), "-pubout", "-out", str(pub_path))
        return priv_path.read_bytes(), pub_path.read_bytes()


def _seed_from_mnemonic(mnemonic: str, passphrase: str = "") -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        mnemonic.encode("utf-8"),
        ("ezchain-v2-mnemonic-" + passphrase).encode("utf-8"),
        200_000,
        dklen=32,
    )


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


SECP256K1_OID_DER = b"\x06\x05\x2B\x81\x04\x00\x0A"


def _derive_secp256k1_private_key_pem_from_mnemonic(mnemonic: str, passphrase: str = "") -> bytes:
    seed = _seed_from_mnemonic(mnemonic, passphrase)
    secret_int = (int.from_bytes(seed, "big") % (SECP256K1_ORDER - 1)) + 1
    private_key_bytes = secret_int.to_bytes(32, byteorder="big", signed=False)
    der_bytes = _encode_sequence(
        _encode_der_integer(1),
        _encode_octet_string(private_key_bytes),
        _encode_explicit(0, SECP256K1_OID_DER),
    )
    return _pem_wrap("EC PRIVATE KEY", der_bytes)


def derive_secp256k1_keypair_from_mnemonic(mnemonic: str, passphrase: str = "") -> Tuple[bytes, bytes]:
    private_pem = _derive_secp256k1_private_key_pem_from_mnemonic(mnemonic, passphrase)
    with tempfile.TemporaryDirectory() as tmpdir:
        priv_path = Path(tmpdir) / "key.pem"
        pub_path = Path(tmpdir) / "pub.pem"
        priv_path.write_bytes(private_pem)
        _run_openssl("ec", "-in", str(priv_path), "-pubout", "-out", str(pub_path))
        public_pem = pub_path.read_bytes()
    return private_pem, public_pem


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


def address_from_public_key_pem(public_key_pem: bytes) -> str:
    der_bytes = _pem_to_der(public_key_pem)
    return "0x" + keccak256(der_bytes)[-20:].hex()


def _der_read_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("invalid DER length offset")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    octets = first & 0x7F
    if octets == 0 or offset + octets > len(data):
        raise ValueError("invalid DER length")
    length = int.from_bytes(data[offset:offset + octets], byteorder="big", signed=False)
    return length, offset + octets


def parse_ecdsa_der(signature: bytes) -> tuple[int, int]:
    if len(signature) < 8 or signature[0] != 0x30:
        raise ValueError("invalid DER sequence")
    seq_len, offset = _der_read_length(signature, 1)
    if offset + seq_len != len(signature):
        raise ValueError("invalid DER sequence length")
    if signature[offset] != 0x02:
        raise ValueError("invalid DER integer tag")
    r_len, offset = _der_read_length(signature, offset + 1)
    r = int.from_bytes(signature[offset:offset + r_len], byteorder="big", signed=False)
    offset += r_len
    if signature[offset] != 0x02:
        raise ValueError("invalid DER integer tag")
    s_len, offset = _der_read_length(signature, offset + 1)
    s = int.from_bytes(signature[offset:offset + s_len], byteorder="big", signed=False)
    offset += s_len
    if offset != len(signature):
        raise ValueError("unexpected trailing DER bytes")
    return r, s


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


def encode_ecdsa_der(r: int, s: int) -> bytes:
    body = _encode_der_integer(r) + _encode_der_integer(s)
    return b"\x30" + _der_encode_length(len(body)) + body


def normalize_low_s(signature: bytes) -> bytes:
    r, s = parse_ecdsa_der(signature)
    if s > LOW_S_MAX:
        s = SECP256K1_ORDER - s
    return encode_ecdsa_der(r, s)


def is_low_s_signature(signature: bytes) -> bool:
    _, s = parse_ecdsa_der(signature)
    return 0 < s <= LOW_S_MAX


def sign_digest_secp256k1(private_key_pem: bytes, digest: bytes) -> bytes:
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes")
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "key.pem"
        digest_path = Path(tmpdir) / "digest.bin"
        sig_path = Path(tmpdir) / "sig.der"
        key_path.write_bytes(private_key_pem)
        digest_path.write_bytes(digest)
        _run_openssl(
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(key_path),
            "-in",
            str(digest_path),
            "-out",
            str(sig_path),
        )
        return normalize_low_s(sig_path.read_bytes())


def sign_message_secp256k1(private_key_pem: bytes, message: bytes, *, domain: bytes = b"") -> bytes:
    digest = hashlib.sha256(domain + message).digest()
    return sign_digest_secp256k1(private_key_pem, digest)


def verify_digest_secp256k1(public_key_pem: bytes, digest: bytes, signature: bytes) -> bool:
    if len(digest) != 32:
        return False
    try:
        if not is_low_s_signature(signature):
            return False
    except ValueError:
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        pub_path = Path(tmpdir) / "pub.pem"
        digest_path = Path(tmpdir) / "digest.bin"
        sig_path = Path(tmpdir) / "sig.der"
        pub_path.write_bytes(public_key_pem)
        digest_path.write_bytes(digest)
        sig_path.write_bytes(signature)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-rawin",
                "-pubin",
                "-inkey",
                str(pub_path),
                "-in",
                str(digest_path),
                "-sigfile",
                str(sig_path),
            ],
            capture_output=True,
            text=False,
        )
        return result.returncode == 0


def verify_message_secp256k1(public_key_pem: bytes, message: bytes, signature: bytes, *, domain: bytes = b"") -> bool:
    digest = hashlib.sha256(domain + message).digest()
    return verify_digest_secp256k1(public_key_pem, digest, signature)
