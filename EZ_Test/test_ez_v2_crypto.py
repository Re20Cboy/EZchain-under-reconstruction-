from __future__ import annotations

import hashlib
import sys
import types

import pytest

from EZ_V2.crypto import keccak256


def test_keccak256_uses_hashlib_when_supported() -> None:
    payload = b"ezchain-v2-keccak"
    expected = hashlib.new("keccak-256", payload).digest()
    assert keccak256(payload) == expected


def test_keccak256_falls_back_to_pycryptodome_when_hashlib_keccak_is_missing(monkeypatch) -> None:
    real_hashlib_new = hashlib.new

    def _fake_hashlib_new(name: str, data: bytes = b"", **kwargs):
        if name == "keccak-256":
            raise ValueError("unsupported hash type keccak-256")
        return real_hashlib_new(name, data, **kwargs)

    class _FakeDigest:
        def __init__(self, *, digest_bits: int):
            assert digest_bits == 256
            self._data = b""

        def update(self, data: bytes) -> None:
            self._data += data

        def digest(self) -> bytes:
            return b"\xAB" * 32

    fake_keccak_module = types.SimpleNamespace(new=lambda *, digest_bits: _FakeDigest(digest_bits=digest_bits))
    fake_hash_module = types.SimpleNamespace(keccak=fake_keccak_module)
    fake_crypto_module = types.SimpleNamespace(Hash=fake_hash_module)

    monkeypatch.setattr(hashlib, "new", _fake_hashlib_new)
    monkeypatch.setitem(sys.modules, "Crypto", fake_crypto_module)
    monkeypatch.setitem(sys.modules, "Crypto.Hash", fake_hash_module)
    monkeypatch.setitem(sys.modules, "Crypto.Hash.keccak", fake_keccak_module)

    assert keccak256(b"fallback") == b"\xAB" * 32


def test_keccak256_raises_clear_error_when_no_backend_is_available(monkeypatch) -> None:
    real_hashlib_new = hashlib.new

    def _fake_hashlib_new(name: str, data: bytes = b"", **kwargs):
        if name == "keccak-256":
            raise ValueError("unsupported hash type keccak-256")
        return real_hashlib_new(name, data, **kwargs)

    monkeypatch.setattr(hashlib, "new", _fake_hashlib_new)
    monkeypatch.delitem(sys.modules, "Crypto", raising=False)
    monkeypatch.delitem(sys.modules, "Crypto.Hash", raising=False)
    monkeypatch.delitem(sys.modules, "Crypto.Hash.keccak", raising=False)

    real_import = __import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "Crypto.Hash" and "keccak" in fromlist:
            raise ModuleNotFoundError("No module named 'Crypto'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    with pytest.raises(RuntimeError, match="pycryptodome"):
        keccak256(b"no-backend")
