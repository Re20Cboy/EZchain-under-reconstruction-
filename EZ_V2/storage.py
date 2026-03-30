from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .claim_set import (
    claim_range_set_from_json_obj,
    claim_range_set_from_sidecar,
    claim_range_set_json_obj,
)
from .chain import compute_addr_key, compute_bundle_hash, confirmed_ref
from .serde import dumps_json, loads_json
from .smt import materialize_proof
from .types import (
    Checkpoint,
    ClaimRangeSet,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    HeaderLite,
    PendingBundleContext,
    PriorWitnessLink,
    Receipt,
    ReceiptProofBatch,
    ReceiptProofRef,
    WitnessV2,
)
from .values import LocalValueRecord


def _bundle_ref_key_from_fields(height: int, block_hash: bytes, bundle_hash: bytes, seq: int) -> str:
    return f"{height}:{block_hash.hex()}:{bundle_hash.hex()}:{seq}"


def _bundle_ref_key(bundle_ref) -> str:
    return _bundle_ref_key_from_fields(
        bundle_ref.height,
        bundle_ref.block_hash,
        bundle_ref.bundle_hash,
        bundle_ref.seq,
    )


def _compact_receipt_with_batch(
    receipt: Receipt,
    *,
    sender_addr: str,
    proof_batch: ReceiptProofBatch | None,
) -> Receipt:
    if receipt.account_state_proof is None or proof_batch is None:
        return receipt
    if proof_batch.state_root != receipt.header_lite.state_root:
        return receipt
    key = compute_addr_key(sender_addr)
    materialized = materialize_proof(proof_batch.multi_proof, key)
    if materialized != receipt.account_state_proof:
        return receipt
    return replace(
        receipt,
        account_state_proof=None,
        proof_batch_ref=ReceiptProofRef(batch_id=proof_batch.batch_id, key=key),
    )


def _materialize_receipt_with_lookup(
    receipt: Receipt,
    *,
    sender_addr: str,
    lookup_batch,
) -> Receipt:
    if receipt.account_state_proof is not None or receipt.proof_batch_ref is None:
        return receipt
    proof_batch = lookup_batch(receipt.proof_batch_ref.batch_id)
    if proof_batch is None:
        return receipt
    if proof_batch.state_root != receipt.header_lite.state_root:
        return receipt
    return replace(
        receipt,
        account_state_proof=materialize_proof(proof_batch.multi_proof, receipt.proof_batch_ref.key),
        proof_batch_ref=None,
    )


def _compact_unit_with_batch(unit: ConfirmedBundleUnit, proof_batch: ReceiptProofBatch | None) -> ConfirmedBundleUnit:
    return replace(
        unit,
        receipt=_compact_receipt_with_batch(
            unit.receipt,
            sender_addr=unit.bundle_sidecar.sender_addr,
            proof_batch=proof_batch,
        ),
    )


def _materialize_unit_with_lookup(unit: ConfirmedBundleUnit, lookup_batch) -> ConfirmedBundleUnit:
    return replace(
        unit,
        receipt=_materialize_receipt_with_lookup(
            unit.receipt,
            sender_addr=unit.bundle_sidecar.sender_addr,
            lookup_batch=lookup_batch,
        ),
    )


def _compact_witness_with_batch(witness: WitnessV2, lookup_batch) -> WitnessV2:
    compact_chain = tuple(
        _compact_unit_with_batch(
            unit,
            lookup_batch(f"{unit.receipt.header_lite.height}:{unit.receipt.header_lite.block_hash.hex()}"),
        )
        for unit in witness.confirmed_bundle_chain
    )
    anchor = witness.anchor
    if isinstance(anchor, PriorWitnessLink):
        anchor = replace(
            anchor,
            prior_witness=_compact_witness_with_batch(anchor.prior_witness, lookup_batch),
        )
    elif isinstance(anchor, (GenesisAnchor, CheckpointAnchor)):
        anchor = anchor
    return replace(witness, confirmed_bundle_chain=compact_chain, anchor=anchor)


def _materialize_witness_with_lookup(witness: WitnessV2, lookup_batch) -> WitnessV2:
    materialized_chain = tuple(
        _materialize_unit_with_lookup(unit, lookup_batch)
        for unit in witness.confirmed_bundle_chain
    )
    anchor = witness.anchor
    if isinstance(anchor, PriorWitnessLink):
        anchor = replace(
            anchor,
            prior_witness=_materialize_witness_with_lookup(anchor.prior_witness, lookup_batch),
        )
    elif isinstance(anchor, (GenesisAnchor, CheckpointAnchor)):
        anchor = anchor
    return replace(witness, confirmed_bundle_chain=materialized_chain, anchor=anchor)


def _compact_record_with_batches(record: LocalValueRecord, lookup_batch) -> LocalValueRecord:
    return replace(record, witness_v2=_compact_witness_with_batch(record.witness_v2, lookup_batch))


def _materialize_record_with_batches(record: LocalValueRecord, lookup_batch) -> LocalValueRecord:
    return replace(record, witness_v2=_materialize_witness_with_lookup(record.witness_v2, lookup_batch))


class LocalWalletDB:
    def __init__(self, db_path: str):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._before_sidecar_refcount_recompute_hook = None
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS value_records (
                    owner_addr TEXT NOT NULL,
                    record_id TEXT PRIMARY KEY,
                    value_begin INTEGER NOT NULL,
                    value_end INTEGER NOT NULL,
                    local_status TEXT NOT NULL,
                    acquisition_height INTEGER NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_value_records_owner_status
                    ON value_records (owner_addr, local_status);

                CREATE TABLE IF NOT EXISTS bundle_sidecars (
                    bundle_hash BLOB PRIMARY KEY,
                    sidecar_json TEXT NOT NULL,
                    ref_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    sender_addr TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    bundle_ref_key TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (sender_addr, seq)
                );

                CREATE TABLE IF NOT EXISTS confirmed_units (
                    sender_addr TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    bundle_ref_key TEXT NOT NULL PRIMARY KEY,
                    bundle_hash BLOB NOT NULL,
                    unit_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_bundles (
                    sender_addr TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    bundle_hash BLOB NOT NULL UNIQUE,
                    context_json TEXT NOT NULL,
                    PRIMARY KEY (sender_addr, seq)
                );

                CREATE TABLE IF NOT EXISTS checkpoints_v2 (
                    owner_addr TEXT NOT NULL,
                    checkpoint_key TEXT PRIMARY KEY,
                    value_begin INTEGER NOT NULL,
                    value_end INTEGER NOT NULL,
                    checkpoint_height INTEGER NOT NULL,
                    checkpoint_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accepted_transfer_packages (
                    owner_addr TEXT NOT NULL,
                    package_hash BLOB NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    PRIMARY KEY (owner_addr, package_hash)
                );

                CREATE TABLE IF NOT EXISTS canonical_headers_v2 (
                    owner_addr TEXT NOT NULL,
                    height INTEGER NOT NULL,
                    block_hash BLOB NOT NULL,
                    state_root BLOB NOT NULL,
                    header_json TEXT NOT NULL,
                    PRIMARY KEY (owner_addr, height)
                );

                CREATE TABLE IF NOT EXISTS receipt_proof_batches (
                    batch_id TEXT PRIMARY KEY,
                    height INTEGER NOT NULL,
                    batch_json TEXT NOT NULL
                );
                """
            )
            self._ensure_column("bundle_sidecars", "claim_ranges_json", "TEXT")

    def _ensure_column(self, table: str, column: str, column_sql: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column not in existing:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_sql}")

    def replace_value_records(self, owner_addr: str, records: Iterable[LocalValueRecord]) -> None:
        records = list(records)
        with self._lock:
            with self._conn:
                self._replace_value_records_locked(owner_addr, records)

    def replace_value_records_and_recompute_sidecar_refs(self, owner_addr: str, records: Iterable[LocalValueRecord]) -> None:
        records = list(records)
        with self._lock:
            with self._conn:
                self._replace_value_records_locked(owner_addr, records)
                if callable(self._before_sidecar_refcount_recompute_hook):
                    self._before_sidecar_refcount_recompute_hook()
                self._recompute_sidecar_ref_counts_locked()

    def _replace_value_records_locked(self, owner_addr: str, records: list[LocalValueRecord]) -> None:
        self._conn.execute("DELETE FROM value_records WHERE owner_addr = ?", (owner_addr,))
        self._conn.executemany(
            """
            INSERT INTO value_records (
                owner_addr, record_id, value_begin, value_end,
                local_status, acquisition_height, record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    owner_addr,
                    record.record_id,
                    record.value.begin,
                    record.value.end,
                    record.local_status.value,
                    record.acquisition_height,
                    dumps_json(_compact_record_with_batches(record, self.get_receipt_proof_batch)),
                )
                for record in records
            ],
        )

    def list_value_records(self, owner_addr: str) -> list[LocalValueRecord]:
        rows = self._conn.execute(
            """
            SELECT record_json
            FROM value_records
            WHERE owner_addr = ?
            ORDER BY value_begin, value_end, record_id
            """,
            (owner_addr,),
        ).fetchall()
        return [
            _materialize_record_with_batches(loads_json(row["record_json"]), self.get_receipt_proof_batch)
            for row in rows
        ]

    def save_sidecar(self, sidecar) -> bytes:
        bundle_hash = compute_bundle_hash(sidecar)
        claim_ranges = claim_range_set_from_sidecar(sidecar)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO bundle_sidecars (bundle_hash, sidecar_json, claim_ranges_json, ref_count)
                VALUES (?, ?, ?, COALESCE((SELECT ref_count FROM bundle_sidecars WHERE bundle_hash = ?), 0))
                ON CONFLICT(bundle_hash) DO UPDATE SET
                    sidecar_json = excluded.sidecar_json,
                    claim_ranges_json = excluded.claim_ranges_json
                """,
                (
                    sqlite3.Binary(bundle_hash),
                    dumps_json(sidecar),
                    dumps_json(claim_range_set_json_obj(claim_ranges)),
                    sqlite3.Binary(bundle_hash),
                ),
            )
        return bundle_hash

    def get_sidecar(self, bundle_hash: bytes):
        row = self._conn.execute(
            "SELECT sidecar_json FROM bundle_sidecars WHERE bundle_hash = ?",
            (sqlite3.Binary(bundle_hash),),
        ).fetchone()
        return loads_json(row["sidecar_json"]) if row else None

    def list_sidecar_hashes(self) -> list[bytes]:
        rows = self._conn.execute("SELECT bundle_hash FROM bundle_sidecars ORDER BY bundle_hash").fetchall()
        return [bytes(row["bundle_hash"]) for row in rows]

    def get_sidecar_claim_ranges(self, bundle_hash: bytes) -> ClaimRangeSet | None:
        row = self._conn.execute(
            "SELECT claim_ranges_json FROM bundle_sidecars WHERE bundle_hash = ?",
            (sqlite3.Binary(bundle_hash),),
        ).fetchone()
        if row is None or row["claim_ranges_json"] is None:
            sidecar = self.get_sidecar(bundle_hash)
            if sidecar is None:
                return None
            claim_ranges = claim_range_set_from_sidecar(sidecar)
            self.save_sidecar(sidecar)
            return claim_ranges
        return claim_range_set_from_json_obj(loads_json(row["claim_ranges_json"]))

    def save_receipt(self, sender_addr: str, receipt: Receipt, bundle_hash: bytes) -> None:
        compact_receipt = _compact_receipt_with_batch(
            receipt,
            sender_addr=sender_addr,
            proof_batch=self.get_receipt_proof_batch(f"{receipt.header_lite.height}:{receipt.header_lite.block_hash.hex()}"),
        )
        bundle_ref_key = _bundle_ref_key_from_fields(
            compact_receipt.header_lite.height,
            compact_receipt.header_lite.block_hash,
            bundle_hash,
            compact_receipt.seq,
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO receipts (sender_addr, seq, bundle_ref_key, receipt_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sender_addr, seq) DO UPDATE SET
                    bundle_ref_key = excluded.bundle_ref_key,
                    receipt_json = excluded.receipt_json
                """,
                (sender_addr, compact_receipt.seq, bundle_ref_key, dumps_json(compact_receipt)),
            )

    def get_receipt(self, sender_addr: str, seq: int) -> Receipt | None:
        row = self._conn.execute(
            "SELECT receipt_json FROM receipts WHERE sender_addr = ? AND seq = ?",
            (sender_addr, seq),
        ).fetchone()
        if row is None:
            return None
        return _materialize_receipt_with_lookup(
            loads_json(row["receipt_json"]),
            sender_addr=sender_addr,
            lookup_batch=self.get_receipt_proof_batch,
        )

    def get_receipt_by_ref(self, bundle_ref) -> Receipt | None:
        row = self._conn.execute(
            "SELECT receipt_json FROM receipts WHERE bundle_ref_key = ?",
            (_bundle_ref_key(bundle_ref),),
        ).fetchone()
        if row is None:
            return None
        receipt = loads_json(row["receipt_json"])
        return _materialize_receipt_with_lookup(
            receipt,
            sender_addr=self._sender_addr_for_bundle_ref(bundle_ref),
            lookup_batch=self.get_receipt_proof_batch,
        )

    def list_receipts(self, sender_addr: str) -> list[Receipt]:
        rows = self._conn.execute(
            """
            SELECT receipt_json
            FROM receipts
            WHERE sender_addr = ?
            ORDER BY seq
            """,
            (sender_addr,),
        ).fetchall()
        return [
            _materialize_receipt_with_lookup(
                loads_json(row["receipt_json"]),
                sender_addr=sender_addr,
                lookup_batch=self.get_receipt_proof_batch,
            )
            for row in rows
        ]

    def save_confirmed_unit(self, unit: ConfirmedBundleUnit) -> None:
        bundle_ref = confirmed_ref(unit)
        compact_unit = _compact_unit_with_batch(
            unit,
            self.get_receipt_proof_batch(f"{bundle_ref.height}:{bundle_ref.block_hash.hex()}"),
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO confirmed_units (sender_addr, seq, bundle_ref_key, bundle_hash, unit_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bundle_ref_key) DO UPDATE SET
                    unit_json = excluded.unit_json,
                    bundle_hash = excluded.bundle_hash
                """,
                (
                    compact_unit.bundle_sidecar.sender_addr,
                    compact_unit.receipt.seq,
                    _bundle_ref_key(bundle_ref),
                    sqlite3.Binary(bundle_ref.bundle_hash),
                    dumps_json(compact_unit),
                ),
            )

    def get_confirmed_unit_by_ref(self, bundle_ref) -> ConfirmedBundleUnit | None:
        row = self._conn.execute(
            "SELECT unit_json FROM confirmed_units WHERE bundle_ref_key = ?",
            (_bundle_ref_key(bundle_ref),),
        ).fetchone()
        if row is None:
            return None
        return _materialize_unit_with_lookup(loads_json(row["unit_json"]), self.get_receipt_proof_batch)

    def get_confirmed_unit(self, sender_addr: str, seq: int) -> ConfirmedBundleUnit | None:
        row = self._conn.execute(
            """
            SELECT unit_json
            FROM confirmed_units
            WHERE sender_addr = ? AND seq = ?
            """,
            (sender_addr, seq),
        ).fetchone()
        if row is None:
            return None
        return _materialize_unit_with_lookup(loads_json(row["unit_json"]), self.get_receipt_proof_batch)

    def save_pending_bundle(self, context: PendingBundleContext) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO pending_bundles (sender_addr, seq, bundle_hash, context_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sender_addr, seq) DO UPDATE SET
                    bundle_hash = excluded.bundle_hash,
                    context_json = excluded.context_json
                """,
                (
                    context.sender_addr,
                    context.seq,
                    sqlite3.Binary(context.bundle_hash),
                    dumps_json(context),
                ),
            )

    def get_pending_bundle(self, sender_addr: str, seq: int) -> PendingBundleContext | None:
        row = self._conn.execute(
            "SELECT context_json FROM pending_bundles WHERE sender_addr = ? AND seq = ?",
            (sender_addr, seq),
        ).fetchone()
        return loads_json(row["context_json"]) if row else None

    def list_pending_bundles(self, sender_addr: str) -> list[PendingBundleContext]:
        rows = self._conn.execute(
            "SELECT context_json FROM pending_bundles WHERE sender_addr = ? ORDER BY seq",
            (sender_addr,),
        ).fetchall()
        return [loads_json(row["context_json"]) for row in rows]

    def next_sequence(self, sender_addr: str) -> int:
        row = self._conn.execute(
            """
            SELECT MAX(seq) AS max_seq
            FROM (
                SELECT seq FROM receipts WHERE sender_addr = ?
                UNION ALL
                SELECT seq FROM pending_bundles WHERE sender_addr = ?
            )
            """,
            (sender_addr, sender_addr),
        ).fetchone()
        max_seq = row["max_seq"] if row and row["max_seq"] is not None else 0
        return int(max_seq) + 1

    def has_accepted_transfer_package(self, owner_addr: str, package_hash: bytes) -> bool:
        row = self._conn.execute(
            """
            SELECT 1
            FROM accepted_transfer_packages
            WHERE owner_addr = ? AND package_hash = ?
            """,
            (owner_addr, sqlite3.Binary(package_hash)),
        ).fetchone()
        return row is not None

    def save_accepted_transfer_package(self, owner_addr: str, package_hash: bytes, accepted_at: int) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO accepted_transfer_packages (owner_addr, package_hash, accepted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner_addr, package_hash) DO NOTHING
                """,
                (owner_addr, sqlite3.Binary(package_hash), accepted_at),
            )

    def save_canonical_header(self, owner_addr: str, header: HeaderLite) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO canonical_headers_v2 (owner_addr, height, block_hash, state_root, header_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_addr, height) DO UPDATE SET
                    block_hash = excluded.block_hash,
                    state_root = excluded.state_root,
                    header_json = excluded.header_json
                """,
                (
                    owner_addr,
                    header.height,
                    sqlite3.Binary(header.block_hash),
                    sqlite3.Binary(header.state_root),
                    dumps_json(header),
                ),
            )

    def save_receipt_proof_batch(self, height: int, batch: ReceiptProofBatch) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO receipt_proof_batches (batch_id, height, batch_json)
                VALUES (?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    height = excluded.height,
                    batch_json = excluded.batch_json
                """,
                (batch.batch_id, int(height), dumps_json(batch)),
            )

    def get_receipt_proof_batch(self, batch_id: str) -> ReceiptProofBatch | None:
        row = self._conn.execute(
            "SELECT batch_json FROM receipt_proof_batches WHERE batch_id = ?",
            (str(batch_id),),
        ).fetchone()
        return loads_json(row["batch_json"]) if row else None

    def _sender_addr_for_bundle_ref(self, bundle_ref) -> str:
        row = self._conn.execute(
            "SELECT sender_addr FROM confirmed_units WHERE bundle_ref_key = ?",
            (_bundle_ref_key(bundle_ref),),
        ).fetchone()
        if row is not None:
            return str(row["sender_addr"])
        row = self._conn.execute(
            "SELECT sender_addr FROM receipts WHERE bundle_ref_key = ?",
            (_bundle_ref_key(bundle_ref),),
        ).fetchone()
        if row is not None:
            return str(row["sender_addr"])
        return ""

    def has_canonical_header(self, owner_addr: str, header: HeaderLite) -> bool:
        row = self._conn.execute(
            """
            SELECT 1
            FROM canonical_headers_v2
            WHERE owner_addr = ? AND height = ? AND block_hash = ? AND state_root = ?
            """,
            (
                owner_addr,
                header.height,
                sqlite3.Binary(header.block_hash),
                sqlite3.Binary(header.state_root),
            ),
        ).fetchone()
        return row is not None

    def delete_pending_bundle(self, sender_addr: str, seq: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM pending_bundles WHERE sender_addr = ? AND seq = ?",
                (sender_addr, seq),
            )

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        checkpoint_key = "|".join(
            [
                checkpoint.owner_addr,
                str(checkpoint.value_begin),
                str(checkpoint.value_end),
                checkpoint.checkpoint_block_hash.hex(),
                checkpoint.checkpoint_bundle_hash.hex(),
            ]
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO checkpoints_v2 (
                    owner_addr, checkpoint_key, value_begin, value_end,
                    checkpoint_height, checkpoint_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_key) DO UPDATE SET checkpoint_json = excluded.checkpoint_json
                """,
                (
                    checkpoint.owner_addr,
                    checkpoint_key,
                    checkpoint.value_begin,
                    checkpoint.value_end,
                    checkpoint.checkpoint_height,
                    dumps_json(checkpoint),
                ),
            )

    def list_checkpoints(self, owner_addr: str) -> list[Checkpoint]:
        rows = self._conn.execute(
            """
            SELECT checkpoint_json
            FROM checkpoints_v2
            WHERE owner_addr = ?
            ORDER BY value_begin, value_end, checkpoint_height
            """,
            (owner_addr,),
        ).fetchall()
        return [loads_json(row["checkpoint_json"]) for row in rows]

    def recompute_sidecar_ref_counts(self) -> None:
        with self._lock:
            with self._conn:
                self._recompute_sidecar_ref_counts_locked()

    def _recompute_sidecar_ref_counts_locked(self) -> None:
        counts: dict[bytes, int] = {}
        for row in self._conn.execute("SELECT record_json FROM value_records"):
            record = loads_json(row["record_json"])
            for bundle_hash in _collect_bundle_hashes_from_witness(record.witness_v2):
                counts[bundle_hash] = counts.get(bundle_hash, 0) + 1
        for row in self._conn.execute("SELECT context_json FROM pending_bundles"):
            context = loads_json(row["context_json"])
            counts[context.bundle_hash] = counts.get(context.bundle_hash, 0) + 1
        self._conn.execute("UPDATE bundle_sidecars SET ref_count = 0")
        for bundle_hash, ref_count in counts.items():
            sidecar = self.get_sidecar(bundle_hash)
            claim_ranges = None if sidecar is None else claim_range_set_from_sidecar(sidecar)
            self._conn.execute(
                """
                INSERT INTO bundle_sidecars (bundle_hash, sidecar_json, claim_ranges_json, ref_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bundle_hash) DO UPDATE SET
                    sidecar_json = excluded.sidecar_json,
                    claim_ranges_json = excluded.claim_ranges_json,
                    ref_count = excluded.ref_count
                """,
                (
                    sqlite3.Binary(bundle_hash),
                    dumps_json(sidecar),
                    None if claim_ranges is None else dumps_json(claim_range_set_json_obj(claim_ranges)),
                    ref_count,
                ),
            )

    def gc_unused_sidecars(self) -> int:
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM bundle_sidecars WHERE ref_count <= 0")
        return cursor.rowcount


def _collect_bundle_hashes_from_witness(witness) -> set[bytes]:
    hashes: set[bytes] = set()
    for unit in witness.confirmed_bundle_chain:
        hashes.add(compute_bundle_hash(unit.bundle_sidecar))
    anchor = witness.anchor
    if hasattr(anchor, "prior_witness"):
        hashes.update(_collect_bundle_hashes_from_witness(anchor.prior_witness))
    return hashes
