from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def _encode_length(length: int) -> bytes:
    if length < 0:
        raise ValueError("length must be non-negative")
    return length.to_bytes(4, byteorder="big", signed=False)


def _encode_int(value: int) -> bytes:
    sign = b"\x01" if value < 0 else b"\x00"
    magnitude = abs(value)
    if magnitude == 0:
        raw = b"\x00"
    else:
        raw = magnitude.to_bytes((magnitude.bit_length() + 7) // 8, byteorder="big", signed=False)
    return b"I" + sign + _encode_length(len(raw)) + raw


def canonicalize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (bool, int, str, bytes)):
        return obj
    if hasattr(obj, "to_canonical") and callable(obj.to_canonical):
        return canonicalize(obj.to_canonical())
    if is_dataclass(obj):
        return {
            field.name: canonicalize(getattr(obj, field.name))
            for field in fields(obj)
        }
    if isinstance(obj, (list, tuple)):
        return [canonicalize(item) for item in obj]
    if isinstance(obj, dict):
        normalized = {}
        for key in sorted(obj.keys(), key=lambda item: str(item)):
            normalized[str(key)] = canonicalize(obj[key])
        return normalized
    raise TypeError(f"Unsupported canonical object: {type(obj)!r}")


def canonical_encode(obj: Any) -> bytes:
    normalized = canonicalize(obj)
    return _encode_value(normalized)


def _encode_value(value: Any) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bool):
        return b"T" if value else b"F"
    if isinstance(value, int):
        return _encode_int(value)
    if isinstance(value, bytes):
        return b"Y" + _encode_length(len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"S" + _encode_length(len(raw)) + raw
    if isinstance(value, list):
        encoded_items = [_encode_value(item) for item in value]
        return b"L" + _encode_length(len(encoded_items)) + b"".join(encoded_items)
    if isinstance(value, dict):
        parts = []
        for key in sorted(value.keys()):
            parts.append(_encode_value(str(key)))
            parts.append(_encode_value(value[key]))
        return b"D" + _encode_length(len(value)) + b"".join(parts)
    raise TypeError(f"Unsupported encoded object: {type(value)!r}")
