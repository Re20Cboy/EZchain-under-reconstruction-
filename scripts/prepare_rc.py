#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _default_notes(version: str, git_head: str) -> str:
    return (
        f"# EZchain Release {version}\n\n"
        f"- release_time_utc: {datetime.now(timezone.utc).isoformat()}\n"
        f"- git_head: {git_head}\n\n"
        "## Summary\n"
        "- Describe key changes in this RC.\n\n"
        "## Known Risks\n"
        "- List known issues and temporary mitigations.\n\n"
        "## Rollback Steps\n"
        "1. Stop local service and node processes.\n"
        "2. Restore previous release artifact.\n"
        "3. Restore backup snapshot via `python scripts/ops_restore.py --backup-dir <snapshot> --config ezchain.yaml --force`.\n"
        "4. Re-run health and one end-to-end send/receive check.\n\n"
        "## Validation Evidence\n"
        "- Attach `dist/release_report.json` and `dist/release_report.md`.\n"
        "- Reference runbook: `doc/MVP_RUNBOOK.md`.\n"
    )


def _git_head(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True)
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare RC release notes and manifest")
    parser.add_argument("--version", required=True, help="e.g. v0.1.0-rc1")
    parser.add_argument("--report-json", default="dist/release_report.json")
    parser.add_argument("--notes-dir", default="doc/releases")
    parser.add_argument("--manifest-out", default="dist/rc_manifest.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    notes_dir = root / args.notes_dir
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_file = notes_dir / f"{args.version}.md"

    report_path = root / args.report_json
    report = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    git_head = str(report.get("git_head") or _git_head(root))
    if not notes_file.exists():
        notes_file.write_text(_default_notes(args.version, git_head), encoding="utf-8")

    manifest = {
        "version": args.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "release_notes": str(notes_file.relative_to(root)),
        "release_report_json": str(report_path.relative_to(root)) if report_path.exists() else "",
        "release_report_status": report.get("overall_status", "missing"),
    }

    manifest_out = root / args.manifest_out
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
