#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print(f"[package] RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EZchain desktop MVP artifact")
    parser.add_argument("--target", choices=["macos", "windows"], required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    dist_dir = root / "dist"

    if args.clean:
        shutil.rmtree(root / "build", ignore_errors=True)
        shutil.rmtree(dist_dir, ignore_errors=True)

    pyinstaller = shutil.which("pyinstaller")
    if pyinstaller:
        add_data_sep = ";" if args.target == "windows" else ":"
        cmd = [
            pyinstaller,
            "--name",
            "ezchain-cli",
            "--onefile",
            "--add-data",
            f"configs{add_data_sep}configs",
            "ezchain_cli.py",
        ]
        if args.target == "windows":
            cmd.append("--console")
        run(cmd, cwd=root)
    else:
        # Fallback: zip source-based runnable package for manual python execution.
        fallback = dist_dir / f"ezchain-{args.target}-python-runner"
        fallback.mkdir(parents=True, exist_ok=True)
        files = [
            "ezchain_cli.py",
            "ezchain.yaml",
            "requirements.txt",
            "README.md",
        ]
        for rel in files:
            shutil.copy2(root / rel, fallback / rel)
        shutil.copytree(root / "configs", fallback / "configs", dirs_exist_ok=True)
        shutil.copy2(root / "scripts" / "profile_config.py", fallback / "profile_config.py")
        shutil.copytree(root / "EZ_App", fallback / "EZ_App", dirs_exist_ok=True)
        print("[package] pyinstaller not found, generated python-runner package")

    print("[package] DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
