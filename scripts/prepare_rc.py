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
        "- Confirm `consensus_tcp_evidence_status` and whether formal TCP consensus evidence was actually formed.\n"
        "- Check `consensus_tcp_step_notes` for per-step retry/skip details when TCP evidence is still missing.\n"
        "- If the current environment is bind-restricted, call that out explicitly instead of treating it as equivalent to passed TCP evidence.\n"
        "- Reference runbook: `doc/MVP_RUNBOOK.md`.\n"
    )


def _git_head(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True)
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    return "unknown"


def _path_for_manifest(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _sibling_markdown_path(path: Path) -> Path:
    return path.with_suffix(".md")


def _artifact_entry(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": _path_for_manifest(path, root),
        "exists": path.exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare RC release notes and manifest")
    parser.add_argument("--version", required=True, help="e.g. v0.1.0-rc1")
    parser.add_argument("--report-json", default="dist/release_report.json")
    parser.add_argument("--readiness-json", default="dist/v2_readiness.json")
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
    report_md_path = _sibling_markdown_path(report_path)

    readiness_path = root / args.readiness_json
    readiness = {}
    if readiness_path.exists():
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness_md_path = _sibling_markdown_path(readiness_path)

    git_head = str(report.get("git_head") or _git_head(root))
    if not notes_file.exists():
        notes_file.write_text(_default_notes(args.version, git_head), encoding="utf-8")

    manifest = {
        "version": args.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "release_notes": _path_for_manifest(notes_file, root),
        "release_report_json": _path_for_manifest(report_path, root) if report_path.exists() else "",
        "release_report_md": _path_for_manifest(report_md_path, root) if report_md_path.exists() else "",
        "release_report_status": report.get("overall_status", "missing"),
        "release_report_risks": report.get("risks", []),
        "v2_readiness_json": _path_for_manifest(readiness_path, root) if readiness_path.exists() else "",
        "v2_readiness_md": _path_for_manifest(readiness_md_path, root) if readiness_md_path.exists() else "",
        "v2_ready_for_default": readiness.get("ready_for_v2_default", False),
        "v2_readiness_blocking_items": readiness.get("blocking_items", []),
        "external_trial_status": report.get("summary", {}).get("external_trial_status", "missing"),
        "external_trial_gate_status": report.get("summary", {}).get("external_trial_gate_status", "missing"),
        "external_trial_remaining_steps": report.get("summary", {}).get("external_trial_remaining_steps", []),
        "external_trial_failed_steps": report.get("summary", {}).get("external_trial_failed_steps", []),
        "official_testnet_gate_status": report.get("summary", {}).get("official_testnet_gate_status", "missing"),
        "v2_adversarial_gate_status": report.get("summary", {}).get("v2_adversarial_gate_status", "missing"),
        "consensus_gate_status": report.get("summary", {}).get("consensus_gate_status", "missing"),
        "consensus_core_status": report.get("summary", {}).get("consensus_core_status", "missing"),
        "consensus_sync_status": report.get("summary", {}).get("consensus_sync_status", "missing"),
        "consensus_catchup_status": report.get("summary", {}).get("consensus_catchup_status", "missing"),
        "consensus_network_status": report.get("summary", {}).get("consensus_network_status", "missing"),
        "consensus_recovery_status": report.get("summary", {}).get("consensus_recovery_status", "missing"),
        "consensus_tcp_evidence_status": report.get("summary", {}).get("consensus_tcp_evidence_status", "missing"),
        "consensus_formal_tcp_evidence_ready": report.get("summary", {}).get(
            "consensus_formal_tcp_evidence_ready", False
        ),
        "consensus_tcp_step_notes": report.get("summary", {}).get("consensus_tcp_step_notes", []),
        "stability_gate_status": report.get("summary", {}).get("stability_gate_status", "missing"),
        "stability_failures": report.get("summary", {}).get("stability_failures", "missing"),
        "stability_failure_rate": report.get("summary", {}).get("stability_failure_rate", "missing"),
        "stability_restarts": report.get("summary", {}).get("stability_restarts", "missing"),
        "stability_burst_checks": report.get("summary", {}).get("stability_burst_checks", "missing"),
        "stability_blocking_reasons": report.get("summary", {}).get("stability_blocking_reasons", []),
        "v2_account_recovery_gate_status": report.get("summary", {}).get("v2_account_recovery_gate_status", "missing"),
        "v2_account_recovery_final_sync_health": report.get("summary", {}).get(
            "v2_account_recovery_final_sync_health", ""
        ),
        "v2_account_recovery_final_sync_health_reason": report.get("summary", {}).get(
            "v2_account_recovery_final_sync_health_reason", ""
        ),
        "v2_account_recovery_flaps_requested": report.get("summary", {}).get(
            "v2_account_recovery_flaps_requested", "missing"
        ),
        "v2_account_recovery_flaps_completed": report.get("summary", {}).get(
            "v2_account_recovery_flaps_completed", "missing"
        ),
        "v2_account_recovery_blocking_reasons": report.get("summary", {}).get(
            "v2_account_recovery_blocking_reasons", []
        ),
        "artifacts": {
            "release_notes": _artifact_entry(notes_file, root),
            "release_report_json": _artifact_entry(report_path, root),
            "release_report_md": _artifact_entry(report_md_path, root),
            "v2_readiness_json": _artifact_entry(readiness_path, root),
            "v2_readiness_md": _artifact_entry(readiness_md_path, root),
        },
    }

    manifest_out = root / args.manifest_out
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
