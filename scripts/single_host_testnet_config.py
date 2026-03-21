#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.config import _to_yaml, load_config
from EZ_App.profiles import get_profile_template_path


def _detect_non_loopback_ip() -> str:
    for target in ("192.0.2.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            ip = str(sock.getsockname()[0]).strip()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            sock.close()

    hostname = socket.gethostname()
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None, socket.AF_INET):
            if family != socket.AF_INET:
                continue
            ip = str(sockaddr[0]).strip()
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    raise SystemExit("unable to detect a non-loopback local IP; rerun with --host-ip")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a single-host pseudo-remote V2 testnet config from the official-testnet template"
    )
    parser.add_argument("--out", default="ezchain.yaml")
    parser.add_argument("--host-ip", default="")
    parser.add_argument("--port", type=int, default=19500)
    parser.add_argument("--data-dir", default=".ezchain_single_host_testnet")
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    host_ip = str(args.host_ip).strip() or _detect_non_loopback_ip()
    if host_ip.startswith("127."):
        raise SystemExit("--host-ip must be a non-loopback address")

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        raise SystemExit(f"target_exists:{out_path}")

    cfg = load_config(get_profile_template_path("official-testnet"))
    cfg.network.bootstrap_nodes = [f"{host_ip}:{int(args.port)}"]
    cfg.app.protocol_version = "v2"
    cfg.app.data_dir = str(args.data_dir)
    cfg.app.log_dir = f"{args.data_dir}/logs"
    cfg.app.api_token_file = f"{args.data_dir}/api.token"
    cfg.app.api_port = int(args.api_port)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_to_yaml(cfg), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "mode": "single-host-pseudo-remote",
                "template": str(get_profile_template_path("official-testnet")),
                "output": str(out_path),
                "host_ip": host_ip,
                "bootstrap_endpoint": cfg.network.bootstrap_nodes[0],
                "protocol_version": cfg.app.protocol_version,
                "data_dir": cfg.app.data_dir,
                "api_port": cfg.app.api_port,
                "overwritten": bool(args.force),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
