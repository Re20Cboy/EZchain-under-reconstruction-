#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from urllib.request import Request, urlopen


def fetch_json(url: str) -> dict:
    req = Request(url, method="GET")
    with urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch EZchain local service metrics")
    parser.add_argument("--url", default="http://127.0.0.1:8787/metrics")
    parser.add_argument("--min-success-rate", type=float, default=0.0)
    args = parser.parse_args()

    payload = fetch_json(args.url)
    if not payload.get("ok"):
        print("[metrics-probe] invalid response")
        return 1

    data = payload["data"]
    print(json.dumps(data, indent=2))

    success_rate = float(data.get("transactions", {}).get("success_rate", 0.0))
    if success_rate < args.min_success_rate:
        print(
            f"[metrics-probe] FAILED: success_rate={success_rate} < min={args.min_success_rate}",
            file=sys.stderr,
        )
        return 1

    print("[metrics-probe] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
