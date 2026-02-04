#!/usr/bin/env python3
"""
One-click smoke test for EZchain P2P demo network.

This script launches `run_ez_p2p_network.py` with a finite number of waves
and exits non-zero if the run fails or times out.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EZchain P2P smoke test")
    parser.add_argument("--consensus", type=int, default=1)
    parser.add_argument("--accounts", type=int, default=4)
    parser.add_argument("--waves", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--tx-burst", type=int, default=2)
    parser.add_argument("--start-port", type=int, default=19600)
    parser.add_argument("--timeout", type=int, default=120, help="overall timeout in seconds")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    launcher = project_root / "run_ez_p2p_network.py"

    cmd = [
        sys.executable,
        str(launcher),
        "--consensus",
        str(args.consensus),
        "--accounts",
        str(args.accounts),
        "--waves",
        str(args.waves),
        "--interval",
        str(args.interval),
        "--tx-burst",
        str(args.tx_burst),
        "--start-port",
        str(args.start_port),
    ]

    print("== EZchain P2P smoke test ==")
    print("Command:", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project_root),
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: timeout after {args.timeout}s")
        return 1

    if completed.returncode != 0:
        print(f"FAIL: launcher exited with code {completed.returncode}")
        return completed.returncode

    print("PASS: P2P launcher completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
