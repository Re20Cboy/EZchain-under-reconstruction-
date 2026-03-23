from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class PacemakerState:
    current_round: int = 1
    highest_qc_round: int = 0
    locked_qc_round: int = 0
    highest_tc_round: int = 0
    last_decided_round: int = 0
    consecutive_local_timeouts: int = 0
    base_timeout_ms: int = 1000
    max_timeout_ms: int = 16000

    def __post_init__(self) -> None:
        if self.current_round <= 0:
            raise ValueError("current_round must be positive")
        if self.highest_qc_round < 0 or self.locked_qc_round < 0 or self.highest_tc_round < 0:
            raise ValueError("round fields must be non-negative")
        if self.last_decided_round < 0 or self.consecutive_local_timeouts < 0:
            raise ValueError("state counters must be non-negative")
        if self.base_timeout_ms <= 0 or self.max_timeout_ms < self.base_timeout_ms:
            raise ValueError("timeout bounds must be valid")

    @property
    def current_timeout_ms(self) -> int:
        timeout = self.base_timeout_ms * (2 ** self.consecutive_local_timeouts)
        return min(timeout, self.max_timeout_ms)

    def note_qc(self, qc_round: int, *, lock_round: int | None = None) -> "PacemakerState":
        if qc_round < 0:
            raise ValueError("qc_round must be non-negative")
        next_round = max(self.current_round, qc_round + 1)
        next_lock_round = self.locked_qc_round if lock_round is None else max(self.locked_qc_round, lock_round)
        return replace(
            self,
            current_round=next_round,
            highest_qc_round=max(self.highest_qc_round, qc_round),
            locked_qc_round=next_lock_round,
            consecutive_local_timeouts=0,
        )

    def note_tc(self, tc_round: int) -> "PacemakerState":
        if tc_round < 0:
            raise ValueError("tc_round must be non-negative")
        return replace(
            self,
            current_round=max(self.current_round, tc_round + 1),
            highest_tc_round=max(self.highest_tc_round, tc_round),
            consecutive_local_timeouts=0,
        )

    def note_decide(self, decided_round: int) -> "PacemakerState":
        if decided_round < 0:
            raise ValueError("decided_round must be non-negative")
        return replace(
            self,
            last_decided_round=max(self.last_decided_round, decided_round),
            consecutive_local_timeouts=0,
        )

    def note_local_timeout(self) -> "PacemakerState":
        return replace(
            self,
            current_round=self.current_round + 1,
            consecutive_local_timeouts=self.consecutive_local_timeouts + 1,
        )
