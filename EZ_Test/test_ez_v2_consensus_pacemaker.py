from __future__ import annotations

import unittest

from EZ_V2.consensus import PacemakerState


class EZV2ConsensusPacemakerTests(unittest.TestCase):
    def test_local_timeout_advances_round_and_backs_off_timeout(self) -> None:
        state = PacemakerState(base_timeout_ms=500, max_timeout_ms=4000)
        state = state.note_local_timeout()
        self.assertEqual(state.current_round, 2)
        self.assertEqual(state.current_timeout_ms, 1000)
        state = state.note_local_timeout()
        self.assertEqual(state.current_round, 3)
        self.assertEqual(state.current_timeout_ms, 2000)

    def test_qc_jumps_round_and_clears_timeout_streak(self) -> None:
        state = PacemakerState().note_local_timeout().note_local_timeout()
        self.assertEqual(state.consecutive_local_timeouts, 2)
        state = state.note_qc(5, lock_round=4)
        self.assertEqual(state.current_round, 6)
        self.assertEqual(state.highest_qc_round, 5)
        self.assertEqual(state.locked_qc_round, 4)
        self.assertEqual(state.consecutive_local_timeouts, 0)

    def test_tc_jump_and_decide_keep_round_history_consistent(self) -> None:
        state = PacemakerState(current_round=3)
        state = state.note_tc(6)
        self.assertEqual(state.current_round, 7)
        self.assertEqual(state.highest_tc_round, 6)
        state = state.note_decide(6)
        self.assertEqual(state.last_decided_round, 6)
