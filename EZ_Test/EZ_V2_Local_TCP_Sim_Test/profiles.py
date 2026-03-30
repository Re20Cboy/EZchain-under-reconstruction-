from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledEvent:
    after_confirmed_tx: int
    action: str
    target_id: str = ""


@dataclass(frozen=True)
class LocalTCPSimProfile:
    name: str
    consensus_count: int
    account_count: int
    tx_count: int = 0
    genesis_amount: int = 0
    min_amount: int = 1
    max_amount: int = 1
    checkpoint_every: int = 0
    seed: int = 0
    network_timeout_sec: float = 10.0
    rounds: int = 0
    account_names: tuple[str, ...] = ()
    min_height_delta: int = 0
    max_txs_per_bundle: int = 1
    tx_shape_mode: str = "single_value_random"
    auto_run_window_sec: float = 0.0
    target_submissions_per_round: int = 1
    scheduled_events: tuple[ScheduledEvent, ...] = ()

    @property
    def total_supply(self) -> int:
        return int(self.account_count) * int(self.genesis_amount)


GATE_SMOKE_PROFILE = LocalTCPSimProfile(
    name="gate_smoke",
    consensus_count=4,
    account_count=8,
    tx_count=24,
    genesis_amount=1000,
    min_amount=5,
    max_amount=40,
    checkpoint_every=6,
    seed=20260329,
    network_timeout_sec=8.0,
    min_height_delta=6,
)

GATE_RECOVERY_PROFILE = LocalTCPSimProfile(
    name="gate_recovery",
    consensus_count=4,
    account_count=8,
    tx_count=12,
    genesis_amount=1000,
    min_amount=5,
    max_amount=30,
    checkpoint_every=4,
    seed=20260330,
    network_timeout_sec=8.0,
    min_height_delta=4,
)

HEAVY_MULTI_ROUND_PROFILE = LocalTCPSimProfile(
    name="heavy_multi_round",
    consensus_count=7,
    account_count=20,
    tx_count=200,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=25,
    seed=821,
    network_timeout_sec=10.0,
    min_height_delta=20,
    auto_run_window_sec=0.2,
    target_submissions_per_round=16,
)

HEAVY_FAILOVER_PROFILE = LocalTCPSimProfile(
    name="heavy_failover",
    consensus_count=7,
    account_count=20,
    tx_count=80,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=20,
    seed=915,
    network_timeout_sec=10.0,
    min_height_delta=15,
    auto_run_window_sec=0.2,
    target_submissions_per_round=12,
)

APP_USERFLOW_PROFILE = LocalTCPSimProfile(
    name="app_userflow",
    consensus_count=3,
    account_count=3,
    rounds=3,
    account_names=("alice", "bob", "carol"),
    network_timeout_sec=10.0,
)

XL_TOPOLOGY_PROFILE = LocalTCPSimProfile(
    name="xl_topology",
    consensus_count=9,
    account_count=30,
    tx_count=300,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=30,
    seed=20260331,
    network_timeout_sec=10.0,
    min_height_delta=25,
    max_txs_per_bundle=1,
    tx_shape_mode="single_value_random",
    auto_run_window_sec=0.25,
    target_submissions_per_round=24,
)

LONGRUN_SOAK_PROFILE = LocalTCPSimProfile(
    name="longrun_soak",
    consensus_count=7,
    account_count=20,
    tx_count=1000,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=40,
    seed=20260401,
    network_timeout_sec=10.0,
    min_height_delta=80,
    max_txs_per_bundle=1,
    tx_shape_mode="single_value_random",
    auto_run_window_sec=0.25,
    target_submissions_per_round=32,
    scheduled_events=(
        ScheduledEvent(after_confirmed_tx=180, action="restart_consensus", target_id="consensus-6"),
        ScheduledEvent(after_confirmed_tx=320, action="recover_all_accounts"),
        ScheduledEvent(after_confirmed_tx=520, action="restart_consensus", target_id="consensus-5"),
        ScheduledEvent(after_confirmed_tx=700, action="rotate_accounts_to_peer", target_id="consensus-4"),
        ScheduledEvent(after_confirmed_tx=760, action="recover_all_accounts"),
        ScheduledEvent(after_confirmed_tx=860, action="restart_consensus", target_id="consensus-4"),
    ),
)

MULTIVALUE_PROFILE = LocalTCPSimProfile(
    name="multi_value",
    consensus_count=5,
    account_count=10,
    tx_count=60,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=10,
    seed=20260402,
    network_timeout_sec=10.0,
    min_height_delta=20,
    max_txs_per_bundle=1,
    tx_shape_mode="multi_value_compose",
    auto_run_window_sec=0.15,
)

MULTI_TX_BUNDLE_PROFILE = LocalTCPSimProfile(
    name="multi_tx_bundle",
    consensus_count=5,
    account_count=10,
    tx_count=40,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=8,
    seed=20260403,
    network_timeout_sec=10.0,
    min_height_delta=15,
    max_txs_per_bundle=3,
    tx_shape_mode="multi_tx_bundle",
    auto_run_window_sec=0.15,
    target_submissions_per_round=6,
)

COMPLEX_RECOVERY_PROFILE = LocalTCPSimProfile(
    name="complex_recovery",
    consensus_count=7,
    account_count=12,
    tx_count=80,
    genesis_amount=1000,
    min_amount=5,
    max_amount=50,
    checkpoint_every=12,
    seed=20260404,
    network_timeout_sec=10.0,
    min_height_delta=30,
    max_txs_per_bundle=3,
    tx_shape_mode="mixed",
    auto_run_window_sec=0.15,
    target_submissions_per_round=6,
    scheduled_events=(
        ScheduledEvent(after_confirmed_tx=10, action="stop_consensus", target_id="consensus-6"),
        ScheduledEvent(after_confirmed_tx=10, action="rotate_accounts_to_peer", target_id="consensus-6"),
        ScheduledEvent(after_confirmed_tx=20, action="recover_all_accounts"),
        ScheduledEvent(after_confirmed_tx=35, action="restart_consensus", target_id="consensus-6"),
        ScheduledEvent(after_confirmed_tx=50, action="rotate_accounts_to_peer", target_id="consensus-6"),
        ScheduledEvent(after_confirmed_tx=60, action="recover_all_accounts"),
    ),
)
