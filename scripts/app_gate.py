#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_GATE_TESTS = (
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
    "EZ_Test/test_external_trial_scripts.py",
    "EZ_Test/test_release_report_scripts.py",
)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "pytest", "-q", *APP_GATE_TESTS]
    print(f"[app-gate] RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(root))
    if proc.returncode != 0:
        print("[app-gate] FAILED")
        return proc.returncode
    print("[app-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
