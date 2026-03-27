"""
Pacemaker adversarial tests — verify timeout backoff formula, round advancement,
and safety rules on PacemakerState.

Spec coverage:
  - consensus-mvp-spec §10.4  pacemaker testability requirements
  - consensus-mvp-spec §10.6  timeout exponential backoff
  - consensus-mvp-spec §10.7  higher QC/TC skip-round rule
  - consensus-mvp-spec §16.1  item 7 (timeout backoff correctness)
"""

import unittest

from EZ_V2.consensus.pacemaker import PacemakerState


class TestTimeoutBackoffDoublesEachRound(unittest.TestCase):
    """spec §10.6 — round_timeout_ms(h,r) = base * 2^min(r-1, cap)"""

    def test_backoff_sequence(self):
        pm = PacemakerState(base_timeout_ms=1000, max_timeout_ms=16000)
        self.assertEqual(pm.current_timeout_ms, 1000)

        pm = pm.note_local_timeout()  # r=1→2, consecutive=1
        self.assertEqual(pm.current_timeout_ms, 2000)

        pm = pm.note_local_timeout()  # r=2→3, consecutive=2
        self.assertEqual(pm.current_timeout_ms, 4000)

        pm = pm.note_local_timeout()  # r=3→4, consecutive=3
        self.assertEqual(pm.current_timeout_ms, 8000)

        pm = pm.note_local_timeout()  # r=4→5, consecutive=4
        self.assertEqual(pm.current_timeout_ms, 16000)

    def test_backoff_starts_at_base(self):
        pm = PacemakerState(base_timeout_ms=500, max_timeout_ms=32000)
        self.assertEqual(pm.current_timeout_ms, 500)


class TestTimeoutCapsAtMax(unittest.TestCase):
    """spec §10.6 — backoff must not exceed max_timeout_ms"""

    def test_caps_at_max(self):
        pm = PacemakerState(base_timeout_ms=1000, max_timeout_ms=8000)
        for _ in range(20):
            pm = pm.note_local_timeout()
        self.assertEqual(pm.current_timeout_ms, 8000)

    def test_custom_max_respected(self):
        pm = PacemakerState(base_timeout_ms=200, max_timeout_ms=1600)
        # 200, 400, 800, 1600, 1600, ...
        pm = pm.note_local_timeout()
        pm = pm.note_local_timeout()
        self.assertEqual(pm.current_timeout_ms, 800)
        pm = pm.note_local_timeout()
        self.assertEqual(pm.current_timeout_ms, 1600)
        pm = pm.note_local_timeout()
        self.assertEqual(pm.current_timeout_ms, 1600)  # capped


class TestQcResetsConsecutiveTimeouts(unittest.TestCase):
    """spec §10.6 — receiving a QC resets consecutive_local_timeouts to 0"""

    def test_qc_resets_backoff(self):
        pm = PacemakerState(base_timeout_ms=1000, max_timeout_ms=16000)
        pm = pm.note_local_timeout()  # consecutive=1
        pm = pm.note_local_timeout()  # consecutive=2
        self.assertEqual(pm.consecutive_local_timeouts, 2)
        self.assertEqual(pm.current_timeout_ms, 4000)

        pm = pm.note_qc(qc_round=3)
        self.assertEqual(pm.consecutive_local_timeouts, 0)
        self.assertEqual(pm.current_timeout_ms, 1000)  # back to base


class TestTcResetsConsecutiveTimeouts(unittest.TestCase):
    """spec §10.6 — receiving a TC also resets consecutive_local_timeouts"""

    def test_tc_resets_backoff(self):
        pm = PacemakerState(base_timeout_ms=1000)
        pm = pm.note_local_timeout()  # consecutive=1
        pm = pm.note_local_timeout()  # consecutive=2

        pm = pm.note_tc(tc_round=5)
        self.assertEqual(pm.consecutive_local_timeouts, 0)


class TestDecideResetsConsecutiveTimeouts(unittest.TestCase):
    """spec §10.6 — commit/decide resets consecutive_local_timeouts"""

    def test_decide_resets_backoff(self):
        pm = PacemakerState(base_timeout_ms=1000)
        pm = pm.note_local_timeout()  # consecutive=1

        pm = pm.note_decide(decided_round=3)
        self.assertEqual(pm.consecutive_local_timeouts, 0)
        self.assertEqual(pm.last_decided_round, 3)


class TestTcAdvancesRound(unittest.TestCase):
    """spec §10.7 — TC at round R advances to round R+1"""

    def test_tc_advances_to_tc_round_plus_one(self):
        pm = PacemakerState(current_round=1)
        pm = pm.note_tc(tc_round=5)
        self.assertEqual(pm.current_round, 6)  # max(1, 5+1)

    def test_tc_does_not_lower_round(self):
        pm = PacemakerState(current_round=10)
        pm = pm.note_tc(tc_round=3)
        self.assertEqual(pm.current_round, 10)  # max(10, 3+1)=10

    def test_tc_updates_highest_tc_round(self):
        pm = PacemakerState()
        pm = pm.note_tc(tc_round=7)
        self.assertEqual(pm.highest_tc_round, 7)
        pm = pm.note_tc(tc_round=3)  # lower TC
        self.assertEqual(pm.highest_tc_round, 7)  # unchanged


class TestQcAdvancesRound(unittest.TestCase):
    """spec §10.7 — QC at round R advances to round R+1"""

    def test_qc_advances_to_qc_round_plus_one(self):
        pm = PacemakerState(current_round=1)
        pm = pm.note_qc(qc_round=4)
        self.assertEqual(pm.current_round, 5)

    def test_qc_does_not_lower_round(self):
        pm = PacemakerState(current_round=8)
        pm = pm.note_qc(qc_round=2)
        self.assertEqual(pm.current_round, 8)  # max(8, 2+1)

    def test_qc_updates_highest_qc_round(self):
        pm = PacemakerState()
        pm = pm.note_qc(qc_round=6)
        self.assertEqual(pm.highest_qc_round, 6)
        pm = pm.note_qc(qc_round=3)
        self.assertEqual(pm.highest_qc_round, 6)


class TestLocalTimeoutIncreasesRound(unittest.TestCase):
    """spec §10 — note_local_timeout advances round by 1"""

    def test_timeout_increases_round(self):
        pm = PacemakerState(current_round=3)
        pm = pm.note_local_timeout()
        self.assertEqual(pm.current_round, 4)
        self.assertEqual(pm.consecutive_local_timeouts, 1)

    def test_multiple_timeouts_accumulate(self):
        pm = PacemakerState(current_round=1)
        for i in range(5):
            pm = pm.note_local_timeout()
        self.assertEqual(pm.current_round, 6)
        self.assertEqual(pm.consecutive_local_timeouts, 5)


class TestQcUpdatesLockedRound(unittest.TestCase):
    """spec §9 rule 3 — PreCommitQC advances locked_qc_round"""

    def test_lock_round_advances_on_precommit_qc(self):
        pm = PacemakerState()
        pm = pm.note_qc(qc_round=3, lock_round=3)
        self.assertEqual(pm.locked_qc_round, 3)

    def test_lock_round_takes_max(self):
        pm = PacemakerState(locked_qc_round=5)
        pm = pm.note_qc(qc_round=7, lock_round=7)
        self.assertEqual(pm.locked_qc_round, 7)
        # A lower lock round should NOT decrease
        pm = pm.note_qc(qc_round=9, lock_round=4)
        self.assertEqual(pm.locked_qc_round, 7)

    def test_prepare_qc_no_lock(self):
        """A PREPARE QC does NOT carry a lock_round."""
        pm = PacemakerState()
        pm = pm.note_qc(qc_round=3, lock_round=None)
        self.assertEqual(pm.locked_qc_round, 0)  # unchanged


if __name__ == "__main__":
    unittest.main()
