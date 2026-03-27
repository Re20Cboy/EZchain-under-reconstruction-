from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .pacemaker import PacemakerState
from .types import Proposal, QC, TC, VotePhase


_PHASE_RANK = {
    VotePhase.PREPARE: 1,
    VotePhase.PRECOMMIT: 2,
    VotePhase.COMMIT: 3,
}


@dataclass(slots=True)
class InMemoryConsensusStore:
    proposals: dict[bytes, Proposal] = field(default_factory=dict)
    qcs: dict[bytes, QC] = field(default_factory=dict)
    tcs: dict[bytes, TC] = field(default_factory=dict)
    highest_qc: QC | None = None
    locked_qc: QC | None = None
    pacemaker_state: PacemakerState = field(default_factory=PacemakerState)
    _vote_log: dict[tuple[int, int, str, str], bytes] = field(default_factory=dict)
    _timeout_log: dict[tuple[int, int, str], tuple[int | None, bytes | None]] = field(default_factory=dict)

    def save_proposal(self, proposal_hash_value: bytes, proposal: Proposal) -> None:
        self.proposals[proposal_hash_value] = proposal

    def save_qc(self, qc_hash_value: bytes, qc: QC) -> None:
        self.qcs[qc_hash_value] = qc
        if self.highest_qc is None or _is_higher_qc(qc, self.highest_qc):
            self.highest_qc = qc

    def save_tc(self, tc_hash_value: bytes, tc: TC) -> None:
        self.tcs[tc_hash_value] = tc

    def update_locked_qc(self, qc: QC) -> None:
        if self.locked_qc is None or qc.round >= self.locked_qc.round:
            self.locked_qc = qc

    def save_pacemaker_state(self, pacemaker_state: PacemakerState) -> None:
        self.pacemaker_state = pacemaker_state

    def load_persisted_state(self) -> "PersistedConsensusState":
        return PersistedConsensusState(
            pacemaker_state=self.pacemaker_state,
            highest_qc=self.highest_qc,
            locked_qc=self.locked_qc,
        )

    def save_vote_record(self, height: int, round_: int, phase: str, voter_id: str, block_hash: bytes) -> None:
        self._vote_log[(height, round_, phase, voter_id)] = block_hash

    def load_vote_records(self) -> list[tuple[int, int, str, str, bytes]]:
        return [(h, r, p, v, b) for (h, r, p, v), b in self._vote_log.items()]

    def prune_vote_log(self, keep_round: int) -> None:
        keys_to_remove = [k for k in self._vote_log if k[1] < keep_round]
        for k in keys_to_remove:
            del self._vote_log[k]

    def save_timeout_record(
        self, height: int, round_: int, voter_id: str, high_qc_round: int | None, high_qc_hash: bytes | None,
    ) -> None:
        self._timeout_log[(height, round_, voter_id)] = (high_qc_round, high_qc_hash)

    def load_timeout_records(self) -> list[tuple[int, int, str, int | None, bytes | None]]:
        return [(h, r, v, qc_r, qc_h) for (h, r, v), (qc_r, qc_h) in self._timeout_log.items()]

    def prune_timeout_log(self, keep_round: int) -> None:
        keys_to_remove = [k for k in self._timeout_log if k[1] < keep_round]
        for k in keys_to_remove:
            del self._timeout_log[k]

    def close(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class PersistedConsensusState:
    pacemaker_state: PacemakerState
    highest_qc: QC | None
    locked_qc: QC | None


class SQLiteConsensusStore:
    def __init__(self, db_path: str):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self.proposals: dict[bytes, Proposal] = {}
        self.qcs: dict[bytes, QC] = {}
        self.tcs: dict[bytes, TC] = {}
        self.highest_qc: QC | None = None
        self.locked_qc: QC | None = None
        self.pacemaker_state = PacemakerState()
        self._load_into_memory()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS consensus_runtime_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    pacemaker_json TEXT NOT NULL,
                    highest_qc_hash BLOB NULL,
                    locked_qc_hash BLOB NULL
                );

                CREATE TABLE IF NOT EXISTS consensus_proposals (
                    proposal_hash BLOB PRIMARY KEY,
                    proposal_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS consensus_qcs (
                    qc_hash BLOB PRIMARY KEY,
                    qc_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS consensus_tcs (
                    tc_hash BLOB PRIMARY KEY,
                    tc_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS consensus_vote_log (
                    height INTEGER NOT NULL,
                    round INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    voter_id TEXT NOT NULL,
                    block_hash BLOB NOT NULL,
                    PRIMARY KEY (height, round, phase, voter_id)
                );

                CREATE TABLE IF NOT EXISTS consensus_timeout_log (
                    height INTEGER NOT NULL,
                    round INTEGER NOT NULL,
                    voter_id TEXT NOT NULL,
                    high_qc_round INTEGER,
                    high_qc_hash BLOB,
                    PRIMARY KEY (height, round, voter_id)
                );
                """
            )

    def _load_into_memory(self) -> None:
        proposal_rows = self._conn.execute(
            "SELECT proposal_hash, proposal_json FROM consensus_proposals"
        ).fetchall()
        self.proposals = {
            bytes(row["proposal_hash"]): _loads_json(row["proposal_json"])
            for row in proposal_rows
        }
        qc_rows = self._conn.execute(
            "SELECT qc_hash, qc_json FROM consensus_qcs"
        ).fetchall()
        self.qcs = {
            bytes(row["qc_hash"]): _loads_json(row["qc_json"])
            for row in qc_rows
        }
        tc_rows = self._conn.execute(
            "SELECT tc_hash, tc_json FROM consensus_tcs"
        ).fetchall()
        self.tcs = {
            bytes(row["tc_hash"]): _loads_json(row["tc_json"])
            for row in tc_rows
        }
        state_row = self._conn.execute(
            """
            SELECT pacemaker_json, highest_qc_hash, locked_qc_hash
            FROM consensus_runtime_state
            WHERE singleton_id = 1
            """
        ).fetchone()
        if state_row is None:
            return
        self.pacemaker_state = _loads_json(state_row["pacemaker_json"])
        highest_qc_hash = state_row["highest_qc_hash"]
        locked_qc_hash = state_row["locked_qc_hash"]
        self.highest_qc = None if highest_qc_hash is None else self.qcs.get(bytes(highest_qc_hash))
        self.locked_qc = None if locked_qc_hash is None else self.qcs.get(bytes(locked_qc_hash))

    def save_proposal(self, proposal_hash_value: bytes, proposal: Proposal) -> None:
        self.proposals[proposal_hash_value] = proposal
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_proposals (proposal_hash, proposal_json)
                VALUES (?, ?)
                ON CONFLICT(proposal_hash) DO UPDATE SET
                    proposal_json = excluded.proposal_json
                """,
                (sqlite3.Binary(proposal_hash_value), _dumps_json(proposal)),
            )

    def save_qc(self, qc_hash_value: bytes, qc: QC) -> None:
        self.qcs[qc_hash_value] = qc
        if self.highest_qc is None or _is_higher_qc(qc, self.highest_qc):
            self.highest_qc = qc
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_qcs (qc_hash, qc_json)
                VALUES (?, ?)
                ON CONFLICT(qc_hash) DO UPDATE SET
                    qc_json = excluded.qc_json
                """,
                (sqlite3.Binary(qc_hash_value), _dumps_json(qc)),
            )
        self._persist_runtime_state()

    def save_tc(self, tc_hash_value: bytes, tc: TC) -> None:
        self.tcs[tc_hash_value] = tc
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_tcs (tc_hash, tc_json)
                VALUES (?, ?)
                ON CONFLICT(tc_hash) DO UPDATE SET
                    tc_json = excluded.tc_json
                """,
                (sqlite3.Binary(tc_hash_value), _dumps_json(tc)),
            )
        self._persist_runtime_state()

    def save_vote_record(self, height: int, round_: int, phase: str, voter_id: str, block_hash: bytes) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_vote_log (height, round, phase, voter_id, block_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(height, round, phase, voter_id) DO UPDATE SET block_hash = excluded.block_hash
                """,
                (height, round_, phase, voter_id, sqlite3.Binary(block_hash)),
            )

    def load_vote_records(self) -> list[tuple[int, int, str, str, bytes]]:
        rows = self._conn.execute(
            "SELECT height, round, phase, voter_id, block_hash FROM consensus_vote_log"
        ).fetchall()
        return [(r[0], r[1], r[2], r[3], bytes(r[4])) for r in rows]

    def prune_vote_log(self, keep_round: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM consensus_vote_log WHERE round < ?", (keep_round,)
            )

    def save_timeout_record(
        self, height: int, round_: int, voter_id: str, high_qc_round: int | None, high_qc_hash: bytes | None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_timeout_log (height, round, voter_id, high_qc_round, high_qc_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(height, round, voter_id) DO UPDATE SET
                    high_qc_round = excluded.high_qc_round,
                    high_qc_hash = excluded.high_qc_hash
                """,
                (
                    height, round_, voter_id, high_qc_round,
                    None if high_qc_hash is None else sqlite3.Binary(high_qc_hash),
                ),
            )

    def load_timeout_records(self) -> list[tuple[int, int, str, int | None, bytes | None]]:
        rows = self._conn.execute(
            "SELECT height, round, voter_id, high_qc_round, high_qc_hash FROM consensus_timeout_log"
        ).fetchall()
        return [
            (r[0], r[1], r[2], r[3], None if r[4] is None else bytes(r[4]))
            for r in rows
        ]

    def prune_timeout_log(self, keep_round: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM consensus_timeout_log WHERE round < ?", (keep_round,)
            )

    def update_locked_qc(self, qc: QC) -> None:
        if self.locked_qc is None or qc.round >= self.locked_qc.round:
            self.locked_qc = qc
        self._persist_runtime_state()

    def save_pacemaker_state(self, pacemaker_state: PacemakerState) -> None:
        self.pacemaker_state = pacemaker_state
        self._persist_runtime_state()

    def load_persisted_state(self) -> "PersistedConsensusState":
        return PersistedConsensusState(
            pacemaker_state=self.pacemaker_state,
            highest_qc=self.highest_qc,
            locked_qc=self.locked_qc,
        )

    def _persist_runtime_state(self) -> None:
        highest_qc_hash = None if self.highest_qc is None else _find_hash_for_value(self.qcs, self.highest_qc)
        locked_qc_hash = None if self.locked_qc is None else _find_hash_for_value(self.qcs, self.locked_qc)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consensus_runtime_state (
                    singleton_id, pacemaker_json, highest_qc_hash, locked_qc_hash
                ) VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    pacemaker_json = excluded.pacemaker_json,
                    highest_qc_hash = excluded.highest_qc_hash,
                    locked_qc_hash = excluded.locked_qc_hash
                """,
                (
                    _dumps_json(self.pacemaker_state),
                    None if highest_qc_hash is None else sqlite3.Binary(highest_qc_hash),
                    None if locked_qc_hash is None else sqlite3.Binary(locked_qc_hash),
                ),
            )


def _is_higher_qc(candidate: QC, current: QC) -> bool:
    if candidate.round != current.round:
        return candidate.round > current.round
    return _PHASE_RANK[candidate.phase] > _PHASE_RANK[current.phase]


def _find_hash_for_value(items: dict[bytes, object], target: object) -> bytes | None:
    for item_hash, item in items.items():
        if item == target:
            return item_hash
    return None


def _dumps_json(value: object) -> str:
    from ..serde import dumps_json

    return dumps_json(value)


def _loads_json(raw: str) -> object:
    from ..serde import loads_json

    return loads_json(raw)
