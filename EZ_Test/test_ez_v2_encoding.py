from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import unittest

from EZ_V2.encoding import canonical_encode, canonicalize
from EZ_V2.values import ValueRange


class SampleMode(Enum):
    FAST = "fast"


@dataclass(frozen=True)
class SamplePayload:
    amount: int
    window: ValueRange
    enabled: bool
    raw: bytes
    mode: SampleMode


class EZV2EncodingTests(unittest.TestCase):
    def test_canonicalize_normalizes_dataclasses_dict_order_and_enums(self) -> None:
        payload = {
            "zeta": 3,
            "alpha": SamplePayload(
                amount=7,
                window=ValueRange(10, 19),
                enabled=True,
                raw=b"\x00\x01",
                mode=SampleMode.FAST,
            ),
        }

        normalized = canonicalize(payload)

        self.assertEqual(
            normalized,
            {
                "alpha": {
                    "amount": 7,
                    "window": {"begin": 10, "end": 19},
                    "enabled": True,
                    "raw": b"\x00\x01",
                    "mode": "fast",
                },
                "zeta": 3,
            },
        )

    def test_canonical_encode_is_deterministic_for_equivalent_objects(self) -> None:
        left = {"b": [2, 1], "a": {"y": "two", "x": 1}}
        right = {"a": {"x": 1, "y": "two"}, "b": [2, 1]}

        self.assertEqual(canonical_encode(left), canonical_encode(right))
        self.assertNotEqual(canonical_encode(1), canonical_encode(-1))
        self.assertNotEqual(canonical_encode(False), canonical_encode(0))

    def test_canonicalize_rejects_unsupported_objects(self) -> None:
        with self.assertRaisesRegex(TypeError, "Unsupported canonical object"):
            canonicalize({1, 2, 3})


if __name__ == "__main__":
    unittest.main()
