from __future__ import annotations

from dataclasses import dataclass

from .crypto import keccak256
from .types import SparseMerkleMultiProof, SparseMerkleMultiProofNode, SparseMerkleProof


EMPTY_LEAF_HASH = keccak256(b"EZCHAIN_SMT_EMPTY_LEAF_V2")


def _node_hash(left: bytes, right: bytes) -> bytes:
    return keccak256(b"EZCHAIN_SMT_NODE_V2" + left + right)


def _leaf_node_hash(key: bytes, value_hash: bytes) -> bytes:
    return keccak256(b"EZCHAIN_SMT_LEAF_V2" + key + value_hash)


class SparseMerkleTree:
    def __init__(self, depth: int = 256):
        if depth <= 0:
            raise ValueError("depth must be positive")
        self.depth = depth
        self._values: dict[int, bytes] = {}
        self._default_hashes = [EMPTY_LEAF_HASH]
        for _ in range(depth):
            previous = self._default_hashes[-1]
            self._default_hashes.append(_node_hash(previous, previous))

    def copy(self) -> "SparseMerkleTree":
        cloned = SparseMerkleTree(depth=self.depth)
        cloned._values = dict(self._values)
        return cloned

    def get(self, key: bytes) -> bytes | None:
        return self._values.get(int.from_bytes(key, byteorder="big", signed=False))

    def set(self, key: bytes, value_hash: bytes) -> None:
        if len(key) * 8 != self.depth:
            raise ValueError("key length does not match tree depth")
        if len(value_hash) != 32:
            raise ValueError("value_hash must be 32 bytes")
        self._values[int.from_bytes(key, byteorder="big", signed=False)] = value_hash

    def root(self) -> bytes:
        return self._subtree_hash(0, self._values)

    def prove(self, key: bytes) -> SparseMerkleProof:
        if len(key) * 8 != self.depth:
            raise ValueError("key length does not match tree depth")
        key_int = int.from_bytes(key, byteorder="big", signed=False)
        siblings = tuple(self._prove_recursive(0, key_int, self._values))
        return SparseMerkleProof(siblings=siblings, existence=key_int in self._values)

    def _split_items(self, node_depth: int, items: dict[int, bytes]) -> tuple[dict[int, bytes], dict[int, bytes]]:
        left: dict[int, bytes] = {}
        right: dict[int, bytes] = {}
        bit_index = self.depth - 1 - node_depth
        for key_int, value_hash in items.items():
            if ((key_int >> bit_index) & 1) == 0:
                left[key_int] = value_hash
            else:
                right[key_int] = value_hash
        return left, right

    def _subtree_hash(self, node_depth: int, items: dict[int, bytes]) -> bytes:
        remaining_depth = self.depth - node_depth
        if not items:
            return self._default_hashes[remaining_depth]
        if node_depth == self.depth:
            if len(items) != 1:
                raise ValueError("leaf depth subtree must contain exactly one item")
            key_int, value_hash = next(iter(items.items()))
            key_bytes = key_int.to_bytes(self.depth // 8, byteorder="big", signed=False)
            return _leaf_node_hash(key_bytes, value_hash)
        left_items, right_items = self._split_items(node_depth, items)
        left_hash = self._subtree_hash(node_depth + 1, left_items)
        right_hash = self._subtree_hash(node_depth + 1, right_items)
        return _node_hash(left_hash, right_hash)

    def _prove_recursive(self, node_depth: int, key_int: int, items: dict[int, bytes]) -> list[bytes]:
        if node_depth == self.depth:
            return []
        left_items, right_items = self._split_items(node_depth, items)
        bit_index = self.depth - 1 - node_depth
        target_bit = (key_int >> bit_index) & 1
        if target_bit == 0:
            path_items = left_items
            sibling_hash = self._subtree_hash(node_depth + 1, right_items)
        else:
            path_items = right_items
            sibling_hash = self._subtree_hash(node_depth + 1, left_items)
        proof = self._prove_recursive(node_depth + 1, key_int, path_items)
        proof.append(sibling_hash)
        return proof


def verify_proof(root: bytes, key: bytes, value_hash: bytes, proof: SparseMerkleProof, depth: int = 256) -> bool:
    if len(root) != 32 or len(key) * 8 != depth or len(value_hash) != 32:
        return False
    if len(proof.siblings) != depth:
        return False
    current = _leaf_node_hash(key, value_hash) if proof.existence else EMPTY_LEAF_HASH
    key_int = int.from_bytes(key, byteorder="big", signed=False)
    for level, sibling in enumerate(proof.siblings):
        bit = (key_int >> level) & 1
        if bit == 0:
            current = _node_hash(current, sibling)
        else:
            current = _node_hash(sibling, current)
    return current == root


def _default_hashes(depth: int) -> list[bytes]:
    defaults = [EMPTY_LEAF_HASH]
    for _ in range(depth):
        previous = defaults[-1]
        defaults.append(_node_hash(previous, previous))
    return defaults


def _key_bits(key: bytes, depth: int) -> str:
    return "".join("1" if (key[index // 8] >> (7 - (index % 8))) & 1 else "0" for index in range(depth))


def _sibling_prefix_for_level(key_bits: str, level: int) -> str:
    split_index = len(key_bits) - level - 1
    target_bit = key_bits[split_index]
    sibling_bit = "1" if target_bit == "0" else "0"
    return key_bits[:split_index] + sibling_bit


def build_multiproof(tree: SparseMerkleTree, keys: list[bytes] | tuple[bytes, ...]) -> SparseMerkleMultiProof:
    ordered_keys = tuple(keys)
    nodes: dict[str, bytes] = {}
    for key in ordered_keys:
        proof = tree.prove(key)
        key_bits = _key_bits(key, tree.depth)
        for level, sibling in enumerate(proof.siblings):
            nodes.setdefault(_sibling_prefix_for_level(key_bits, level), sibling)
    ordered_nodes = tuple(
        SparseMerkleMultiProofNode(prefix_bits=prefix_bits, node_hash=node_hash)
        for prefix_bits, node_hash in sorted(nodes.items(), key=lambda item: (len(item[0]), item[0]))
    )
    return SparseMerkleMultiProof(depth=tree.depth, keys=ordered_keys, nodes=ordered_nodes)


def materialize_proof(multi_proof: SparseMerkleMultiProof, key: bytes) -> SparseMerkleProof:
    if len(key) * 8 != multi_proof.depth:
        raise ValueError("key length does not match multiproof depth")
    node_map = {node.prefix_bits: node.node_hash for node in multi_proof.nodes}
    defaults = _default_hashes(multi_proof.depth)
    key_bits = _key_bits(key, multi_proof.depth)
    siblings = []
    for level in range(multi_proof.depth):
        prefix_bits = _sibling_prefix_for_level(key_bits, level)
        siblings.append(node_map.get(prefix_bits, defaults[level]))
    return SparseMerkleProof(siblings=tuple(siblings), existence=key in multi_proof.keys)


def verify_multiproof(root: bytes, key: bytes, value_hash: bytes, multi_proof: SparseMerkleMultiProof) -> bool:
    return verify_proof(
        root,
        key,
        value_hash,
        materialize_proof(multi_proof, key),
        depth=multi_proof.depth,
    )
