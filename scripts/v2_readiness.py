#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid JSON object: {path}")
    return payload


def _evaluate(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    risks = report.get("risks", [])
    checks = [
        {
            "name": "release_report_passed",
            "required": True,
            "status": "passed" if report.get("overall_status") == "passed" else "failed",
            "detail": f"overall_status={report.get('overall_status', 'missing')}",
        },
        {
            "name": "v2_default_gate",
            "required": True,
            "status": "passed" if summary.get("v2_gate_status") == "passed" else "failed",
            "detail": f"v2_gate_status={summary.get('v2_gate_status', 'missing')}",
        },
        {
            "name": "v2_adversarial_gate",
            "required": True,
            "status": "passed" if summary.get("v2_adversarial_gate_status") == "passed" else "failed",
            "detail": f"v2_adversarial_gate_status={summary.get('v2_adversarial_gate_status', 'missing')}",
        },
        {
            "name": "consensus_gate",
            "required": True,
            "status": "passed" if summary.get("consensus_gate_status") == "passed" else "failed",
            "detail": f"consensus_gate_status={summary.get('consensus_gate_status', 'missing')}",
        },
        {
            "name": "consensus_tcp_evidence",
            "required": False,
            "status": "passed" if summary.get("consensus_formal_tcp_evidence_ready") is True else "failed",
            "detail": (
                "consensus_tcp_evidence_status="
                f"{summary.get('consensus_tcp_evidence_status', 'missing')}"
            ),
        },
        {
            "name": "v2_account_recovery_gate",
            "required": True,
            "status": "passed" if summary.get("v2_account_recovery_gate_status") == "passed" else "failed",
            "detail": f"v2_account_recovery_gate_status={summary.get('v2_account_recovery_gate_status', 'missing')}",
        },
        {
            "name": "stability_gate",
            "required": True,
            "status": "passed" if summary.get("stability_gate_status") == "passed" else "failed",
            "detail": f"stability_gate_status={summary.get('stability_gate_status', 'missing')}",
        },
        {
            "name": "official_testnet_gate",
            "required": True,
            "status": "passed" if summary.get("official_testnet_gate_status") == "passed" else "failed",
            "detail": f"official_testnet_gate_status={summary.get('official_testnet_gate_status', 'missing')}",
        },
        {
            "name": "external_trial_gate",
            "required": True,
            "status": "passed" if summary.get("external_trial_gate_status") == "passed" else "failed",
            "detail": f"external_trial_gate_status={summary.get('external_trial_gate_status', 'missing')}",
        },
        {
            "name": "unresolved_release_risks",
            "required": True,
            "status": "passed" if not risks else "failed",
            "detail": "no open risks" if not risks else f"{len(risks)} open risk(s)",
        },
    ]
    blocking = [check for check in checks if check["required"] and check["status"] != "passed"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_for_v2_default": not blocking,
        "checks": checks,
        "blocking_items": [
            {
                "name": item["name"],
                "detail": item["detail"],
            }
            for item in blocking
        ],
    }


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# V2 Default Readiness",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- ready_for_v2_default: {payload['ready_for_v2_default']}",
    ]
    source_report_json = str(payload.get("source_report_json", "") or "").strip()
    if source_report_json:
        lines.append(f"- source_report_json: {source_report_json}")
    source_report_git_head = str(payload.get("source_report_git_head", "") or "").strip()
    if source_report_git_head:
        lines.append(f"- source_report_git_head: {source_report_git_head}")
    source_report_generated_at = str(payload.get("source_report_generated_at", "") or "").strip()
    if source_report_generated_at:
        lines.append(f"- source_report_generated_at: {source_report_generated_at}")
    lines.extend(
        [
            "",
            "## Checks",
        ]
    )
    for item in payload["checks"]:
        marker = "PASS" if item["status"] == "passed" else "FAIL"
        lines.append(f"- [{marker}] {item['name']}: {item['detail']}")
    lines.extend(["", "## Blocking Items"])
    if payload["blocking_items"]:
        for item in payload["blocking_items"]:
            lines.append(f"- {item['name']}: {item['detail']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate whether V2 is ready to become the default project path")
    parser.add_argument("--report-json", default="dist/release_report.json")
    parser.add_argument("--out-json", default="dist/v2_readiness.json")
    parser.add_argument("--out-md", default="dist/v2_readiness.md")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    report_path = (root / args.report_json) if not Path(args.report_json).is_absolute() else Path(args.report_json)
    report = _load_json(report_path)
    payload = _evaluate(report)
    payload["source_report_json"] = str(report_path)
    payload["source_report_generated_at"] = report.get("generated_at", "")
    payload["source_report_git_head"] = report.get("git_head", "")
    payload["source_report_overall_status"] = report.get("overall_status", "")

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    if not out_json.is_absolute():
        out_json = root / out_json
    if not out_md.is_absolute():
        out_md = root / out_md
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_md.write_text(_to_markdown(payload), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    print(f"[v2-readiness] wrote {out_json}")
    print(f"[v2-readiness] wrote {out_md}")
    return 0 if payload["ready_for_v2_default"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
