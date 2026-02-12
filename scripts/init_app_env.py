#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from EZ_App.config import ensure_directories, load_api_token, migrate_config_file
from EZ_App.profiles import apply_network_profile, list_profiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize EZchain app runtime environment")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--profile", default="local-dev", choices=list_profiles())
    parser.add_argument("--skip-migrate", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = apply_network_profile(cfg_path, args.profile)

    migration_result = {"status": "skipped"}
    if not args.skip_migrate:
        migration_result = migrate_config_file(cfg_path)
        cfg = apply_network_profile(cfg_path, args.profile)

    ensure_directories(cfg)
    token = load_api_token(cfg)

    print(
        json.dumps(
            {
                "status": "initialized",
                "config_path": str(cfg_path),
                "profile": args.profile,
                "network": cfg.network.name,
                "bootstrap_nodes": cfg.network.bootstrap_nodes,
                "data_dir": cfg.app.data_dir,
                "log_dir": cfg.app.log_dir,
                "api_host": cfg.app.api_host,
                "api_port": cfg.app.api_port,
                "api_token_preview": f"{token[:6]}..." if token else "",
                "migration": migration_result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
