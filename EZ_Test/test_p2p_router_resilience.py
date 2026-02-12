import asyncio
import time

from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.peer_manager import PeerInfo
from modules.ez_p2p.router import Router


def test_seed_backoff_and_recovery_state_changes():
    router = Router(
        P2PConfig(
            node_role="account",
            peer_seeds=["127.0.0.1:19999"],
            seed_retry_base_sec=0.2,
            seed_retry_max_sec=1.0,
        )
    )

    calls = {"n": 0}

    async def fake_send_hello(seed: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("dial_failed")

    router._send_hello = fake_send_hello  # type: ignore[attr-defined]

    async def run_case():
        await router._attempt_seed_hello("127.0.0.1:19999", force=True)
        st = router._seed_state["127.0.0.1:19999"]
        assert st["failures"] == 1
        assert st["last_error"]

        # Force next attempt and simulate success.
        st["next_retry_monotonic"] = time.monotonic() - 1.0
        await router._attempt_seed_hello("127.0.0.1:19999", force=False)
        st2 = router._seed_state["127.0.0.1:19999"]
        assert st2["failures"] == 0
        assert st2["last_error"] == ""

    asyncio.run(run_case())


def test_router_degraded_status_without_peers():
    router = Router(
        P2PConfig(
            node_role="account",
            degraded_no_peer_sec=0.1,
        )
    )
    router._last_peer_seen_monotonic = time.monotonic() - 1.0
    status = router.get_health_status()
    assert status["degraded"] is True
    assert status["peer_count"] == 0


def test_router_not_degraded_with_active_peer():
    router = Router(
        P2PConfig(
            node_role="account",
            degraded_no_peer_sec=0.1,
        )
    )
    router.peer_manager.add_peer(
        PeerInfo(
            node_id="peer-a",
            role="consensus",
            network_id="devnet",
            latest_index=0,
            address="127.0.0.1:19001",
        )
    )
    router._last_peer_seen_monotonic = time.monotonic() - 1.0
    status = router.get_health_status()
    assert status["degraded"] is False
    assert status["peer_count"] == 1
