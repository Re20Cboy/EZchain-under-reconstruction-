#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from EZ_App.config import load_config


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Create backup snapshot for EZchain app")
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--out-dir", default="backups")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = load_config(config_path)
    data_dir = Path(cfg.app.data_dir)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = f"-{args.label}" if args.label else ""
    backup_root = Path(args.out_dir) / f"snapshot-{stamp}{suffix}"
    backup_root.mkdir(parents=True, exist_ok=True)

    files = []
    if _copy_if_exists(config_path, backup_root / "ezchain.yaml"):
        files.append("ezchain.yaml")
    if _copy_if_exists(data_dir, backup_root / "data_dir"):
        files.append("data_dir")

    manifest = {
        "created_at": stamp,
        "config_path": str(config_path),
        "data_dir": str(data_dir),
        "files": files,
    }
    (backup_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "backup_dir": str(backup_root), "manifest": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
