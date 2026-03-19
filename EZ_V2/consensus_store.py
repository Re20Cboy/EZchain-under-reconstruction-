from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .chain import ZERO_HASH32, ChainStateV2
from .serde import dumps_json, loads_json
from .types import BlockV2, BundleRef, Receipt, ReceiptResponse
from .values import ValueRange


def _bundle_ref_key(bundle_ref: BundleRef) -> str:
    return f"{bundle_ref.height}:{bundle_ref.block_hash.hex()}:{bundle_ref.bundle_hash.hex()}:{bundle_ref.seq}"


@dataclass(frozen=True, slots=True)
class ConsensusStateMetadata:
    version: int
    chain_id: int
    receipt_cache_blocks: int
    genesis_block_hash: bytes
    current_height: int
    current_block_hash: bytes
    current_state_root: bytes


class ConsensusStateStore:
    def __init__(self, db_path: str):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS consensus_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    version INTEGER NOT NULL,
                    chain_id INTEGER NOT NULL,
                    receipt_cache_blocks INTEGER NOT NULL,
                    genesis_block_hash BLOB NOT NULL,
                    current_height INTEGER NOT NULL,
                    current_block_hash BLOB NOT NULL,
                    current_state_root BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS blocks_v2 (
                    height INTEGER PRIMARY KEY,
                    block_hash BLOB NOT NULL UNIQUE,
                    block_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS receipt_window_v2 (
                    sender_addr TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    bundle_ref_key TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (sender_addr, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_receipt_window_height
                    ON receipt_window_v2 (height);

                CREATE TABLE IF NOT EXISTS genesis_allocations_v2 (
                    owner_addr TEXT NOT NULL,
                    value_begin INTEGER NOT NULL,
                    value_end INTEGER NOT NULL,
                    PRIMARY KEY (owner_addr, value_begin, value_end)
                );
                """
            )

    def load_metadata(self) -> ConsensusStateMetadata | None:
        row = self._conn.execute(
            """
            SELECT version, chain_id, receipt_cache_blocks, genesis_block_hash,
                   current_height, current_block_hash, current_state_root
            FROM consensus_state
            WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            return None
        return ConsensusStateMetadata(
            version=int(row["version"]),
            chain_id=int(row["chain_id"]),
            receipt_cache_blocks=int(row["receipt_cache_blocks"]),
            genesis_block_hash=bytes(row["genesis_block_hash"]),
            current_height=int(row["current_height"]),
            current_block_hash=bytes(row["current_block_hash"]),
            current_state_root=bytes(row["current_state_root"]),
        )

    def list_blocks(self) -> list[BlockV2]:
        rows = self._conn.execute(
            "SELECT block_json FROM blocks_v2 ORDER BY height"
        ).fetchall()
        return [loads_json(row["block_json"]) for row in rows]

    def save_applied_block(
        self,
        block: BlockV2,
        receipts: Mapping[str, Receipt],
        *,
        version: int,
        chain_id: int,
        receipt_cache_blocks: int,
        genesis_block_hash: bytes = ZERO_HASH32,
    ) -> None:
        entry_refs = {
            entry.new_leaf.addr: entry.new_leaf.head_ref
            for entry in block.diff_package.diff_entries
        }
        missing_receipts = set(entry_refs) - set(receipts)
        if missing_receipts:
            raise ValueError("missing receipts for persisted block")
        min_height = max(1, block.header.height - receipt_cache_blocks + 1)
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO blocks_v2 (height, block_hash, block_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        block.header.height,
                        sqlite3.Binary(block.block_hash),
                        dumps_json(block),
                    ),
                )
                for sender_addr, receipt in receipts.items():
                    bundle_ref = entry_refs[sender_addr]
                    self._conn.execute(
                        """
                        INSERT INTO receipt_window_v2 (
                            sender_addr, seq, height, bundle_ref_key, receipt_json
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(sender_addr, seq) DO UPDATE SET
                            height = excluded.height,
                            bundle_ref_key = excluded.bundle_ref_key,
                            receipt_json = excluded.receipt_json
                        """,
                        (
                            sender_addr,
                            receipt.seq,
                            receipt.header_lite.height,
                            _bundle_ref_key(bundle_ref),
                            dumps_json(receipt),
                        ),
                    )
                self._conn.execute(
                    "DELETE FROM receipt_window_v2 WHERE height < ?",
                    (min_height,),
                )
                self._conn.execute(
                    """
                    INSERT INTO consensus_state (
                        singleton_id, version, chain_id, receipt_cache_blocks,
                        genesis_block_hash, current_height, current_block_hash, current_state_root
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        version = excluded.version,
                        chain_id = excluded.chain_id,
                        receipt_cache_blocks = excluded.receipt_cache_blocks,
                        genesis_block_hash = excluded.genesis_block_hash,
                        current_height = excluded.current_height,
                        current_block_hash = excluded.current_block_hash,
                        current_state_root = excluded.current_state_root
                    """,
                    (
                        version,
                        chain_id,
                        receipt_cache_blocks,
                        sqlite3.Binary(genesis_block_hash),
                        block.header.height,
                        sqlite3.Binary(block.block_hash),
                        sqlite3.Binary(block.header.state_root),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("block already persisted or conflicts with existing history") from exc

    def get_receipt(self, sender_addr: str, seq: int) -> ReceiptResponse:
        row = self._conn.execute(
            """
            SELECT receipt_json
            FROM receipt_window_v2
            WHERE sender_addr = ? AND seq = ?
            """,
            (sender_addr, seq),
        ).fetchone()
        receipt = loads_json(row["receipt_json"]) if row else None
        return ReceiptResponse(status="ok" if receipt else "missing", receipt=receipt)

    def get_receipt_by_ref(self, bundle_ref: BundleRef) -> ReceiptResponse:
        row = self._conn.execute(
            """
            SELECT receipt_json
            FROM receipt_window_v2
            WHERE bundle_ref_key = ?
            """,
            (_bundle_ref_key(bundle_ref),),
        ).fetchone()
        receipt = loads_json(row["receipt_json"]) if row else None
        return ReceiptResponse(status="ok" if receipt else "missing", receipt=receipt)

    def save_genesis_allocation(self, owner_addr: str, value: ValueRange) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO genesis_allocations_v2 (owner_addr, value_begin, value_end)
                VALUES (?, ?, ?)
                ON CONFLICT(owner_addr, value_begin, value_end) DO NOTHING
                """,
                (owner_addr, value.begin, value.end),
            )

    def list_genesis_allocations(self) -> dict[str, tuple[ValueRange, ...]]:
        rows = self._conn.execute(
            """
            SELECT owner_addr, value_begin, value_end
            FROM genesis_allocations_v2
            ORDER BY owner_addr, value_begin, value_end
            """
        ).fetchall()
        grouped: dict[str, list[ValueRange]] = {}
        for row in rows:
            grouped.setdefault(str(row["owner_addr"]), []).append(
                ValueRange(begin=int(row["value_begin"]), end=int(row["value_end"]))
            )
        return {
            owner_addr: tuple(values)
            for owner_addr, values in grouped.items()
        }

    def load_chain_state(
        self,
        *,
        version: int = 2,
        chain_id: int = 1,
        receipt_cache_blocks: int = 32,
        genesis_block_hash: bytes = ZERO_HASH32,
    ) -> ChainStateV2:
        metadata = self.load_metadata()
        if metadata is None:
            return ChainStateV2(
                version=version,
                chain_id=chain_id,
                receipt_cache_blocks=receipt_cache_blocks,
                genesis_block_hash=genesis_block_hash,
            )
        if metadata.version != version:
            raise ValueError("persisted chain version mismatch")
        if metadata.chain_id != chain_id:
            raise ValueError("persisted chain_id mismatch")
        chain = ChainStateV2(
            version=metadata.version,
            chain_id=metadata.chain_id,
            receipt_cache_blocks=metadata.receipt_cache_blocks,
            genesis_block_hash=metadata.genesis_block_hash,
        )
        for block in self.list_blocks():
            chain.apply_block(block)
        if chain.current_height != metadata.current_height:
            raise ValueError("persisted chain height mismatch")
        if chain.current_block_hash != metadata.current_block_hash:
            raise ValueError("persisted current block hash mismatch")
        if chain.tree.root() != metadata.current_state_root:
            raise ValueError("persisted state root mismatch")
        return chain


__all__ = [
    "ConsensusStateMetadata",
    "ConsensusStateStore",
]
