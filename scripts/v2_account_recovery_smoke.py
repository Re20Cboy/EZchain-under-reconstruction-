#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.node_manager import NodeManager


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_bind_restricted_error(exc: BaseException) -> bool:
    text = str(exc)
    return "Operation not permitted" in text or "bind_not_permitted" in text


def _wait_for(predicate, timeout_sec: float, interval_sec: float = 0.1):
    deadline = time.time() + timeout_sec
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval_sec)
    return None


def build_summary(
    *,
    flaps_requested: int,
    rounds: list[dict[str, Any]],
    final_state: dict[str, Any],
    blocking_reasons: list[str],
    skipped_bind_restricted: bool = False,
) -> dict[str, Any]:
    return {
        "ok": not blocking_reasons,
        "skipped_bind_restricted": bool(skipped_bind_restricted),
        "flaps_requested": int(flaps_requested),
        "flaps_completed": sum(1 for item in rounds if item.get("recovered") is True),
        "degraded_rounds": [int(item["round"]) for item in rounds if item.get("degraded") is True],
        "recovered_rounds": [int(item["round"]) for item in rounds if item.get("recovered") is True],
        "steady_rounds": [int(item["round"]) for item in rounds if item.get("steady") is True],
        "final_sync_health": str(final_state.get("sync_health", "")),
        "final_sync_health_reason": str(final_state.get("sync_health_reason", "")),
        "final_recovery_count": int(final_state.get("recovery_count", 0) or 0),
        "final_max_consecutive_sync_failures": int(final_state.get("max_consecutive_sync_failures", 0) or 0),
        "rounds": rounds,
        "blocking_reasons": list(blocking_reasons),
    }


def run_smoke(
    *,
    project_root: Path,
    flaps: int,
    degraded_timeout_sec: float,
    recovered_timeout_sec: float,
    steady_timeout_sec: float,
    allow_bind_restricted_skip: bool,
) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []

    with tempfile.TemporaryDirectory(prefix="ez_v2_account_recovery_consensus_") as td_consensus:
        with tempfile.TemporaryDirectory(prefix="ez_v2_account_recovery_account_") as td_account:
            consensus_manager = NodeManager(data_dir=td_consensus, project_root=str(project_root))
            account_manager = NodeManager(data_dir=td_account, project_root=str(project_root))
            try:
                consensus_port = _reserve_port()
                account_port = _reserve_port()
            except PermissionError as exc:
                if allow_bind_restricted_skip:
                    return build_summary(
                        flaps_requested=flaps,
                        rounds=[],
                        final_state={},
                        blocking_reasons=[],
                        skipped_bind_restricted=True,
                    )
                raise

            consensus_endpoint = f"127.0.0.1:{consensus_port}"
            try:
                consensus_manager.start(
                    mode="v2-consensus",
                    network_name="testnet-v2-consensus",
                    start_port=consensus_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
                account_manager.start(
                    mode="v2-account",
                    network_name="testnet-v2-account",
                    start_port=account_port,
                    bootstrap_nodes=[consensus_endpoint],
                )
            except RuntimeError as exc:
                if allow_bind_restricted_skip and _is_bind_restricted_error(exc):
                    return build_summary(
                        flaps_requested=flaps,
                        rounds=[],
                        final_state={},
                        blocking_reasons=[],
                        skipped_bind_restricted=True,
                    )
                raise

            try:
                initial_ok = _wait_for(
                    lambda: (
                        state
                        if (state := account_manager.account_status()).get("status") == "running"
                        and state.get("last_sync_ok") is True
                        else None
                    ),
                    timeout_sec=max(2.0, recovered_timeout_sec),
                )
                if initial_ok is None:
                    blocking_reasons.append("initial_sync_never_became_healthy")
                    return build_summary(
                        flaps_requested=flaps,
                        rounds=rounds,
                        final_state=account_manager.account_status(),
                        blocking_reasons=blocking_reasons,
                    )

                for round_index in range(1, flaps + 1):
                    round_result: dict[str, Any] = {"round": round_index, "degraded": False, "recovered": False, "steady": False}
                    consensus_manager.stop()

                    degraded = _wait_for(
                        lambda: (
                            state
                            if (state := account_manager.account_status()).get("status") == "running"
                            and state.get("last_sync_ok") is False
                            else None
                        ),
                        timeout_sec=degraded_timeout_sec,
                    )
                    if degraded is None:
                        blocking_reasons.append(f"round_{round_index}_did_not_enter_degraded_state")
                    else:
                        round_result["degraded"] = True
                        round_result["degraded_sync_health"] = degraded.get("sync_health", "")
                        round_result["degraded_consecutive_failures"] = degraded.get("consecutive_sync_failures", 0)

                    try:
                        consensus_manager.start(
                            mode="v2-consensus",
                            network_name="testnet-v2-consensus",
                            start_port=consensus_port,
                            bootstrap_nodes=[consensus_endpoint],
                        )
                    except RuntimeError as exc:
                        if allow_bind_restricted_skip and _is_bind_restricted_error(exc):
                            return build_summary(
                                flaps_requested=flaps,
                                rounds=rounds,
                                final_state=account_manager.account_status(),
                                blocking_reasons=[],
                                skipped_bind_restricted=True,
                            )
                        raise

                    recovered = _wait_for(
                        lambda: (
                            state
                            if (state := account_manager.account_status()).get("status") == "running"
                            and state.get("last_sync_ok") is True
                            and int(state.get("recovery_count", 0) or 0) >= round_index
                            else None
                        ),
                        timeout_sec=recovered_timeout_sec,
                    )
                    if recovered is None:
                        blocking_reasons.append(f"round_{round_index}_did_not_recover")
                    else:
                        round_result["recovered"] = True
                        round_result["recovered_sync_health"] = recovered.get("sync_health", "")
                        round_result["recovery_count"] = recovered.get("recovery_count", 0)

                    steady = _wait_for(
                        lambda: (
                            state
                            if (state := account_manager.account_status()).get("status") == "running"
                            and state.get("last_sync_ok") is True
                            and state.get("sync_health") == "healthy"
                            and state.get("sync_health_reason") == "stable_after_recovery"
                            else None
                        ),
                        timeout_sec=steady_timeout_sec,
                    )
                    if steady is not None:
                        round_result["steady"] = True

                    rounds.append(round_result)
            finally:
                account_manager.stop()
                consensus_manager.stop()

            final_state = account_manager.account_status()
            return build_summary(
                flaps_requested=flaps,
                rounds=rounds,
                final_state=final_state,
                blocking_reasons=blocking_reasons,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeatedly flap a v2-consensus endpoint and verify v2-account recovers")
    parser.add_argument("--flaps", type=int, default=2)
    parser.add_argument("--degraded-timeout-sec", type=float, default=8.0)
    parser.add_argument("--recovered-timeout-sec", type=float, default=10.0)
    parser.add_argument("--steady-timeout-sec", type=float, default=8.0)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    summary = run_smoke(
        project_root=project_root,
        flaps=max(1, int(args.flaps)),
        degraded_timeout_sec=max(1.0, float(args.degraded_timeout_sec)),
        recovered_timeout_sec=max(1.0, float(args.recovered_timeout_sec)),
        steady_timeout_sec=max(1.0, float(args.steady_timeout_sec)),
        allow_bind_restricted_skip=bool(args.allow_bind_restricted_skip),
    )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if summary.get("skipped_bind_restricted"):
        print("[v2-account-recovery-smoke] SKIPPED (bind restricted environment)")
        return 0
    if summary.get("ok"):
        print("[v2-account-recovery-smoke] PASSED")
        return 0
    print("[v2-account-recovery-smoke] FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
