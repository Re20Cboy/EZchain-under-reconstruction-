#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print(f"[release-gate] RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="EZchain release gate")
    parser.add_argument("--skip-slow", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "run_ezchain_tests.py", "--groups", "core", "transactions"]
    if args.skip_slow:
        cmd.append("--skip-slow")

    try:
        run(cmd, cwd=root)
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "EZ_Test/test_ez_app_crypto_wallet.py",
                "EZ_Test/test_ez_app_config_cli.py",
                "EZ_Test/test_ez_app_profiles.py",
                "EZ_Test/test_ez_app_network_connectivity.py",
                "EZ_Test/test_ez_app_tx_engine.py",
                "EZ_Test/test_ez_app_service_api.py",
            ],
            cwd=root,
        )
        run([sys.executable, "scripts/security_gate.py"], cwd=root)
    except RuntimeError as exc:
        print(f"[release-gate] FAILED: {exc}")
        return 1

    print("[release-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
