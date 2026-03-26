from __future__ import annotations

import unittest

from EZ_V2.crypto import keccak256
from EZ_V2.smt import SparseMerkleTree, verify_proof


class EZV2SparseMerkleTreeTests(unittest.TestCase):
    def test_existing_and_missing_proofs_verify_against_root(self) -> None:
        tree = SparseMerkleTree(depth=8)
        key_a = b"\x10"
        key_b = b"\xf0"
        missing_key = b"\x33"
        value_a = keccak256(b"value-a")
        value_b = keccak256(b"value-b")

        tree.set(key_a, value_a)
        tree.set(key_b, value_b)
        root = tree.root()

        proof_a = tree.prove(key_a)
        self.assertTrue(proof_a.existence)
        self.assertTrue(verify_proof(root, key_a, value_a, proof_a, depth=8))
        self.assertFalse(verify_proof(root, key_a, keccak256(b"wrong"), proof_a, depth=8))

        missing_proof = tree.prove(missing_key)
        self.assertFalse(missing_proof.existence)
        self.assertTrue(verify_proof(root, missing_key, keccak256(b"ignored-for-missing"), missing_proof, depth=8))

    def test_tampered_proof_fails_verification(self) -> None:
        tree = SparseMerkleTree(depth=8)
        key = b"\xaa"
        value_hash = keccak256(b"original")
        tree.set(key, value_hash)

        proof = tree.prove(key)
        tampered_siblings = list(proof.siblings)
        tampered_siblings[0] = keccak256(b"tampered-sibling")

        self.assertFalse(
            verify_proof(
                tree.root(),
                key,
                value_hash,
                proof.__class__(siblings=tuple(tampered_siblings), existence=proof.existence),
                depth=8,
            )
        )

    def test_copy_is_independent_and_input_lengths_are_validated(self) -> None:
        tree = SparseMerkleTree(depth=8)
        key = b"\x01"
        tree.set(key, keccak256(b"seed"))

        cloned = tree.copy()
        cloned.set(b"\x02", keccak256(b"added-later"))

        self.assertIsNone(tree.get(b"\x02"))
        self.assertNotEqual(tree.root(), cloned.root())

        with self.assertRaisesRegex(ValueError, "key length does not match tree depth"):
            tree.set(b"\x00\x01", keccak256(b"bad-key"))
        with self.assertRaisesRegex(ValueError, "value_hash must be 32 bytes"):
            tree.set(b"\x03", b"short")
        with self.assertRaisesRegex(ValueError, "key length does not match tree depth"):
            tree.prove(b"\x00\x03")


if __name__ == "__main__":
    unittest.main()
