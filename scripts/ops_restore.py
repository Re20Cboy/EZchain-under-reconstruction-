#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from EZ_App.config import load_config


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore EZchain app from backup snapshot")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--config", default="ezchain.yaml")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    manifest_file = backup_dir / "manifest.json"
    if not manifest_file.exists():
        raise SystemExit("missing manifest.json in backup dir")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    config_path = Path(args.config)
    current_cfg = load_config(config_path)
    data_dir = Path(current_cfg.app.data_dir)

    if (config_path.exists() or data_dir.exists()) and not args.force:
        raise SystemExit("target exists; rerun with --force")

    backup_config = backup_dir / "ezchain.yaml"
    backup_data = backup_dir / "data_dir"

    if backup_config.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_config, config_path)

    restored_cfg = load_config(config_path)
    restored_data_dir = Path(restored_cfg.app.data_dir)
    if backup_data.exists():
        restored_data_dir.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(backup_data, restored_data_dir)

    print(
        json.dumps(
            {
                "status": "ok",
                "restored_from": str(backup_dir),
                "config_path": str(config_path),
                "data_dir": str(restored_data_dir),
                "source_manifest_files": manifest.get("files", []),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
