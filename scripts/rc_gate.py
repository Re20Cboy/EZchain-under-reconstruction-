#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_NOTE_MARKERS = [
    "## Summary",
    "## Known Risks",
    "## Rollback Steps",
    "doc/MVP_RUNBOOK.md",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RC release notes and manifest")
    parser.add_argument("--manifest", default="dist/rc_manifest.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    if not manifest_path.exists():
        print("[rc-gate] FAILED: missing manifest")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    notes_rel = manifest.get("release_notes", "")
    notes_path = root / notes_rel if notes_rel else None
    if not notes_path or not notes_path.exists():
        failures.append("release notes file missing")
    else:
        notes = notes_path.read_text(encoding="utf-8")
        for marker in REQUIRED_NOTE_MARKERS:
            if marker not in notes:
                failures.append(f"release notes missing marker: {marker}")

    report_status = str(manifest.get("release_report_status", "missing"))
    if report_status != "passed":
        failures.append(f"release_report_status must be 'passed', got '{report_status}'")

    if failures:
        print("[rc-gate] FAILED")
        for item in failures:
            print(f" - {item}")
        return 1

    print("[rc-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
