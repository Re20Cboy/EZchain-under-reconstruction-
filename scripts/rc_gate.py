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
    manifest_arg = Path(args.manifest)
    manifest_path = manifest_arg if manifest_arg.is_absolute() else (root / manifest_arg)
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

    v2_readiness_json = str(manifest.get("v2_readiness_json", ""))
    if not v2_readiness_json:
        failures.append("v2_readiness_json missing from release manifest")

    external_trial_gate_status = str(manifest.get("external_trial_gate_status", "missing"))
    if external_trial_gate_status not in {"passed", "missing", "not_run"}:
        failures.append(
            f"external_trial_gate_status must be 'passed', 'missing', or 'not_run', got '{external_trial_gate_status}'"
        )
    if external_trial_gate_status in {"missing", "not_run"}:
        failures.append("external trial evidence missing from release manifest")

    official_testnet_gate_status = str(manifest.get("official_testnet_gate_status", "missing"))
    if official_testnet_gate_status not in {"passed", "missing", "not_run"}:
        failures.append(
            f"official_testnet_gate_status must be 'passed', 'missing', or 'not_run', got '{official_testnet_gate_status}'"
        )

    v2_adversarial_gate_status = str(manifest.get("v2_adversarial_gate_status", "missing"))
    if v2_adversarial_gate_status not in {"passed", "missing", "not_run"}:
        failures.append(
            f"v2_adversarial_gate_status must be 'passed', 'missing', or 'not_run', got '{v2_adversarial_gate_status}'"
        )

    v2_ready_for_default = bool(manifest.get("v2_ready_for_default", False))
    if not v2_ready_for_default:
        blocking = manifest.get("v2_readiness_blocking_items", [])
        if isinstance(blocking, list) and blocking:
            failures.append(f"v2 readiness not satisfied: {len(blocking)} blocking item(s)")
        else:
            failures.append("v2 readiness not satisfied")

    if failures:
        print("[rc-gate] FAILED")
        for item in failures:
            print(f" - {item}")
        return 1

    print("[rc-gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
