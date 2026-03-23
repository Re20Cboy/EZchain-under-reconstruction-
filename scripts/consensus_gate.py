#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


CONSENSUS_TESTS = (
    "EZ_Test/test_ez_v2_consensus_validator_set.py",
    "EZ_Test/test_ez_v2_consensus_sortition.py",
    "EZ_Test/test_ez_v2_consensus_pacemaker.py",
    "EZ_Test/test_ez_v2_consensus_core.py",
    "EZ_Test/test_ez_v2_consensus_runner.py",
    "EZ_Test/test_ez_v2_consensus_store.py",
)

SYNC_TEST_FILE = "EZ_Test/test_ez_v2_consensus_sync.py"
CATCHUP_TEST_FILE = "EZ_Test/test_ez_v2_consensus_catchup.py"

NETWORK_TEST_FILE = "EZ_Test/test_ez_v2_network.py"

NETWORK_K_PATTERNS = {
    "consensus_static_network_suite": (
        "mvp_consensus_round or "
        "mvp_auto_round or "
        "mvp_sortition_selects_consistent_proposer_and_commits or "
        "mvp_auto_round_forwards_bundle_to_selected_proposer_and_commits or "
        "mvp_timeout_round or "
        "mvp_timeout_allows_next_proposer_to_commit or "
        "rejects_proposal_with_block_hash_mismatch or "
        "rejects_locked_branch_conflict_over_network"
    ),
    "consensus_recovery_suite": (
        "proposer_restart_recovers_consensus_state or "
        "timeout_state_survives_restart_and_commits_next_round"
    ),
    "consensus_tcp_catchup_suite": (
        "tcp_mvp_timeout_then_restarted_next_proposer_still_commits or "
        "tcp_cluster_follower_misses_multiple_rounds_then_catches_up_after_restart"
    ),
    "consensus_tcp_network_suite": (
        "tcp_mvp_consensus_round_commits_block_across_four_consensus_hosts or "
        "tcp_mvp_sortition_selects_consistent_proposer_and_commits or "
        "tcp_mvp_timeout_allows_next_proposer_to_commit or "
        "tcp_mvp_rejects_proposal_with_block_hash_mismatch or "
        "tcp_mvp_rejects_locked_branch_conflict_over_network"
    ),
}

STEP_METADATA = {
    "consensus_core_suite": {"layer": "core", "transport": "none"},
    "consensus_sync_suite": {"layer": "sync", "transport": "static"},
    "consensus_catchup_suite": {"layer": "catchup", "transport": "static"},
    "consensus_tcp_catchup_suite": {"layer": "catchup", "transport": "tcp"},
    "consensus_static_network_suite": {"layer": "network", "transport": "static"},
    "consensus_recovery_suite": {"layer": "recovery", "transport": "static"},
    "consensus_tcp_network_suite": {"layer": "network", "transport": "tcp"},
}


def run_step(name: str, cmd: list[str], cwd: Path) -> dict[str, object]:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    stdout_tail = (proc.stdout or "")[-3000:]
    stderr_tail = (proc.stderr or "")[-3000:]
    combined_output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    skipped_bind_restricted = "bind_not_permitted:" in combined_output
    all_skipped = " skipped" in combined_output and " passed" not in combined_output and proc.returncode == 0
    metadata = STEP_METADATA.get(name, {})
    return {
        "name": name,
        "command": " ".join(cmd),
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "layer": metadata.get("layer", "unknown"),
        "transport": metadata.get("transport", "unknown"),
        "skipped_bind_restricted": skipped_bind_restricted,
        "all_skipped": all_skipped,
    }


def run_step_with_retry(name: str, cmd: list[str], cwd: Path) -> dict[str, object]:
    step = run_step(name, cmd, cwd)
    if step.get("transport") != "tcp" or not step.get("all_skipped", False):
        step["attempts"] = 1
        return step
    last = step
    for attempt, delay_sec in ((2, 1.0), (3, 2.0)):
        time.sleep(delay_sec)
        last = run_step(name, cmd, cwd)
        last["attempts"] = attempt
        last["retried_after_all_skipped"] = True
        if not last.get("all_skipped", False):
            return last
    return last


def build_summary(steps: list[dict[str, object]]) -> dict[str, object]:
    static_steps = [step for step in steps if step.get("transport") == "static"]
    tcp_steps = [step for step in steps if step.get("transport") == "tcp"]
    tcp_steps_executed = [step for step in tcp_steps if not step.get("all_skipped", False)]
    tcp_steps_bind_skipped = [
        step for step in tcp_steps if step.get("skipped_bind_restricted", False) or step.get("all_skipped", False)
    ]
    return {
        "layers": {
            "core": next((step.get("status") for step in steps if step["name"] == "consensus_core_suite"), "missing"),
            "sync": next((step.get("status") for step in steps if step["name"] == "consensus_sync_suite"), "missing"),
            "catchup": "passed" if all(step.get("status") == "passed" for step in steps if step.get("layer") == "catchup") else "failed",
            "network": "passed" if all(step.get("status") == "passed" for step in steps if step.get("layer") == "network") else "failed",
            "recovery": next((step.get("status") for step in steps if step["name"] == "consensus_recovery_suite"), "missing"),
        },
        "static_steps_total": len(static_steps),
        "static_steps_passed": sum(1 for step in static_steps if step.get("status") == "passed"),
        "tcp_steps_total": len(tcp_steps),
        "tcp_steps_passed": sum(1 for step in tcp_steps if step.get("status") == "passed"),
        "tcp_steps_executed": len(tcp_steps_executed),
        "tcp_steps_all_skipped": sum(1 for step in tcp_steps if step.get("all_skipped", False)),
        "tcp_bind_restricted_skips": sum(1 for step in tcp_steps_bind_skipped),
        "tcp_evidence_status": (
            "passed"
            if tcp_steps and tcp_steps_executed and all(step.get("status") == "passed" for step in tcp_steps_executed)
            else ("not_executed_bind_restricted" if tcp_steps and not tcp_steps_executed else "failed")
        ),
        "formal_tcp_evidence_ready": bool(
            tcp_steps
            and tcp_steps_executed
            and all(step.get("status") == "passed" for step in tcp_steps_executed)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EZchain V2 consensus gate")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    steps: list[dict[str, object]] = []

    core_cmd = [sys.executable, "-m", "pytest", "-q", *CONSENSUS_TESTS]
    print(f"[consensus-gate] RUN {' '.join(core_cmd)}")
    steps.append(run_step_with_retry("consensus_core_suite", core_cmd, cwd=root))

    sync_cmd = [sys.executable, "-m", "pytest", "-q", SYNC_TEST_FILE]
    print(f"[consensus-gate] RUN {' '.join(sync_cmd)}")
    steps.append(run_step_with_retry("consensus_sync_suite", sync_cmd, cwd=root))

    catchup_cmd = [sys.executable, "-m", "pytest", "-q", CATCHUP_TEST_FILE]
    print(f"[consensus-gate] RUN {' '.join(catchup_cmd)}")
    steps.append(run_step_with_retry("consensus_catchup_suite", catchup_cmd, cwd=root))

    for step_name, pattern in NETWORK_K_PATTERNS.items():
        network_cmd = [
            sys.executable,
            "-m",
            "pytest",
            NETWORK_TEST_FILE,
            "-q",
        ]
        if STEP_METADATA.get(step_name, {}).get("transport") == "tcp":
            network_cmd.append("-rs")
        network_cmd.extend(["-k", pattern])
        print(f"[consensus-gate] RUN {' '.join(network_cmd)}")
        steps.append(run_step_with_retry(step_name, network_cmd, cwd=root))

    overall_status = "passed" if all(step["status"] == "passed" for step in steps) else "failed"
    payload = {
        "overall_status": overall_status,
        "steps_total": len(steps),
        "steps_passed": sum(1 for step in steps if step["status"] == "passed"),
        "steps_failed": sum(1 for step in steps if step["status"] != "passed"),
        "summary": build_summary(steps),
        "steps": steps,
    }

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[consensus-gate] wrote {out_path}")

    print(json.dumps(payload, indent=2))
    if overall_status != "passed":
        print("[consensus-gate] FAILED")
        return 1
    print("[consensus-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
