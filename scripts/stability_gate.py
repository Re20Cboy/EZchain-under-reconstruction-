#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print(f"[stability-gate] RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="EZchain stability gate")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--restart-every", type=int, default=10)
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "stability.json"
        try:
            cmd = [
                sys.executable,
                "scripts/stability_smoke.py",
                "--config",
                args.config,
                "--cycles",
                str(args.cycles),
                "--interval",
                str(args.interval),
                "--restart-every",
                str(args.restart_every),
                "--max-failures",
                str(args.max_failures),
                "--max-failure-rate",
                str(args.max_failure_rate),
                "--json-out",
                str(out),
            ]
            if args.allow_bind_restricted_skip:
                cmd.append("--allow-bind-restricted-skip")
            run(cmd, cwd=root)
        except RuntimeError as exc:
            print(f"[stability-gate] FAILED: {exc}")
            return 1

        summary = json.loads(out.read_text(encoding="utf-8"))
        if args.restart_every > 0 and summary.get("restarts", 0) <= 0 and not summary.get("skipped_bind_restricted", False):
            print("[stability-gate] FAILED: restart path was not exercised")
            print(json.dumps(summary, indent=2))
            return 1

        print("[stability-gate] PASSED")
        print(json.dumps(summary, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
