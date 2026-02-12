#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="EZchain local stability smoke")
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--restart-every", type=int, default=0, help="Restart service every N cycles; 0 disables restart")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    serve_cmd = [sys.executable, "ezchain_cli.py", "--config", args.config, "serve"]

    def start_proc() -> subprocess.Popen:
        return subprocess.Popen(serve_cmd, cwd=str(root))

    def stop_proc(p: subprocess.Popen) -> None:
        p.terminate()
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()

    proc = start_proc()

    failures = 0
    try:
        time.sleep(1.5)
        for i in range(args.cycles):
            try:
                health = get_json("http://127.0.0.1:8787/health")
                if not health.get("ok"):
                    failures += 1
            except (URLError, TimeoutError, json.JSONDecodeError):
                failures += 1
            print(f"cycle={i + 1}/{args.cycles} failures={failures}")

            if args.restart_every > 0 and (i + 1) % args.restart_every == 0 and (i + 1) < args.cycles:
                stop_proc(proc)
                proc = start_proc()
                time.sleep(1.2)

            time.sleep(args.interval)
    finally:
        stop_proc(proc)

    if failures > 0:
        print(f"[stability-smoke] FAILED with {failures} failed checks")
        return 1

    print("[stability-smoke] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
