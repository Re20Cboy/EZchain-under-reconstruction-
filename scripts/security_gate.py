#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.config import load_config


SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (RSA|EC|DSA) PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z\\-_]{35}"),
]


def run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def scan_for_secrets(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts or ".venv" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                findings.append(str(path))
                break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="EZchain security gate")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    root = ROOT
    cfg = load_config(root / args.config)

    failures: list[str] = []

    if cfg.app.api_host not in {"127.0.0.1", "localhost"}:
        failures.append("app.api_host must stay loopback for local-only MVP service")

    if cfg.security.max_payload_bytes > 1024 * 1024:
        failures.append("security.max_payload_bytes must be <= 1MB")

    if cfg.security.max_tx_amount <= 0:
        failures.append("security.max_tx_amount must be positive")

    secret_hits = scan_for_secrets(root)
    if secret_hits:
        failures.append(f"potential hardcoded secrets found in: {', '.join(secret_hits[:5])}")

    if not args.skip_tests:
        try:
            run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "EZ_Test/test_ez_app_service_api.py",
                    "EZ_Test/test_ez_app_tx_engine.py",
                ],
                cwd=root,
            )
        except RuntimeError as exc:
            failures.append(str(exc))

    if failures:
        print("[security-gate] FAILED")
        for item in failures:
            print(f" - {item}")
        return 1

    print("[security-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
