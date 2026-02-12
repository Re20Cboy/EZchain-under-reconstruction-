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
    parser.add_argument("--with-stability", action="store_true")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
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
                "EZ_Test/test_ops_backup_restore.py",
                "EZ_Test/test_profile_config_script.py",
                "EZ_Test/test_stability_scripts.py",
                "EZ_Test/test_canary_scripts.py",
            ],
            cwd=root,
        )
        run([sys.executable, "scripts/security_gate.py"], cwd=root)
        if args.with_stability:
            stability_cmd = [
                sys.executable,
                "scripts/stability_gate.py",
                "--cycles",
                "30",
                "--interval",
                "1",
                "--restart-every",
                "10",
                "--max-failures",
                "0",
                "--max-failure-rate",
                "0.0",
            ]
            if args.allow_bind_restricted_skip:
                stability_cmd.append("--allow-bind-restricted-skip")
            run(stability_cmd, cwd=root)
    except RuntimeError as exc:
        print(f"[release-gate] FAILED: {exc}")
        return 1

    print("[release-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
