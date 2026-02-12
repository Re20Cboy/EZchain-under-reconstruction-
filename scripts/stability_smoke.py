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
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--startup-wait", type=float, default=1.5)
    parser.add_argument("--restart-cooldown", type=float, default=1.2)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-bind-restricted-skip", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    serve_cmd = [sys.executable, "ezchain_cli.py", "--config", args.config, "serve"]

    def start_proc() -> subprocess.Popen:
        return subprocess.Popen(
            serve_cmd,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop_proc(p: subprocess.Popen) -> None:
        if p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()

    def read_err(p: subprocess.Popen) -> str:
        if p.stderr is None:
            return ""
        try:
            return p.stderr.read() or ""
        except Exception:
            return ""

    proc = start_proc()

    failures = 0
    restarts = 0
    started_at = time.time()
    try:
        time.sleep(max(0.1, args.startup_wait))
        if proc.poll() is not None:
            err = read_err(proc)
            bind_restricted = "PermissionError" in err and "Operation not permitted" in err
            summary = {
                "ok": bool(args.allow_bind_restricted_skip and bind_restricted),
                "skipped_bind_restricted": bool(args.allow_bind_restricted_skip and bind_restricted),
                "cycles": int(args.cycles),
                "failures": int(args.cycles),
                "failure_rate": 1.0,
                "max_failures": int(args.max_failures),
                "max_failure_rate": float(args.max_failure_rate),
                "restarts": 0,
                "duration_seconds": round(time.time() - started_at, 3),
            }
            if args.json_out:
                Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary, indent=2))
            if summary["ok"]:
                print("[stability-smoke] SKIPPED (bind restricted environment)")
                return 0
            print("[stability-smoke] FAILED to start local service")
            return 1

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
                restarts += 1
                time.sleep(max(0.1, args.restart_cooldown))

            time.sleep(args.interval)
    finally:
        stop_proc(proc)

    total = max(1, int(args.cycles))
    failure_rate = failures / total
    summary = {
        "ok": failures <= int(args.max_failures) and failure_rate <= float(args.max_failure_rate),
        "cycles": total,
        "failures": failures,
        "failure_rate": round(failure_rate, 6),
        "max_failures": int(args.max_failures),
        "max_failure_rate": float(args.max_failure_rate),
        "restarts": restarts,
        "duration_seconds": round(time.time() - started_at, 3),
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if not summary["ok"]:
        print(f"[stability-smoke] FAILED with {failures} failed checks ({failure_rate:.4f} rate)")
        return 1

    print("[stability-smoke] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
