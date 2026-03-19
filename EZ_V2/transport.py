from __future__ import annotations

import sqlite3
from pathlib import Path

from .crypto import keccak256
from .encoding import canonical_encode
from .serde import dumps_json, loads_json
from .types import TransferPackage


def transfer_package_hash(package: TransferPackage) -> bytes:
    return keccak256(b"EZCHAIN_TRANSFER_PACKAGE_V2" + canonical_encode(package))


class TransferMailboxStore:
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
                CREATE TABLE IF NOT EXISTS transfer_mailbox (
                    package_hash BLOB PRIMARY KEY,
                    sender_addr TEXT NOT NULL,
                    recipient_addr TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    claimed_at INTEGER,
                    package_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_transfer_mailbox_recipient
                    ON transfer_mailbox (recipient_addr, claimed_at, created_at);
                """
            )

    def enqueue_package(
        self,
        *,
        sender_addr: str,
        recipient_addr: str,
        package: TransferPackage,
        created_at: int,
    ) -> bytes:
        package_hash = transfer_package_hash(package)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO transfer_mailbox (
                    package_hash, sender_addr, recipient_addr, created_at, claimed_at, package_json
                ) VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(package_hash) DO UPDATE SET
                    sender_addr = excluded.sender_addr,
                    recipient_addr = excluded.recipient_addr,
                    package_json = excluded.package_json
                """,
                (
                    sqlite3.Binary(package_hash),
                    sender_addr,
                    recipient_addr,
                    created_at,
                    dumps_json(package),
                ),
            )
        return package_hash

    def list_pending_packages(self, recipient_addr: str) -> list[tuple[bytes, str, int, TransferPackage]]:
        rows = self._conn.execute(
            """
            SELECT package_hash, sender_addr, created_at, package_json
            FROM transfer_mailbox
            WHERE recipient_addr = ? AND claimed_at IS NULL
            ORDER BY created_at, package_hash
            """,
            (recipient_addr,),
        ).fetchall()
        return [
            (
                bytes(row["package_hash"]),
                str(row["sender_addr"]),
                int(row["created_at"]),
                loads_json(row["package_json"]),
            )
            for row in rows
        ]

    def mark_claimed(self, package_hash: bytes, *, claimed_at: int) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE transfer_mailbox
                SET claimed_at = ?
                WHERE package_hash = ?
                """,
                (claimed_at, sqlite3.Binary(package_hash)),
            )

    def pending_count(self, recipient_addr: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM transfer_mailbox
            WHERE recipient_addr = ? AND claimed_at IS NULL
            """,
            (recipient_addr,),
        ).fetchone()
        return int(row["count"]) if row is not None else 0
