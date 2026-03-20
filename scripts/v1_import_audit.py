#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


V1_ROOTS = [
    "EZ_Account",
    "EZ_CheckPoint",
    "EZ_GENESIS",
    "EZ_Main_Chain",
    "EZ_Miner",
    "EZ_Msg",
    "EZ_Transaction",
    "EZ_Tx_Pool",
    "EZ_Units",
    "EZ_VPB",
    "EZ_VPB_Validator",
]


def audit_imports(root: Path) -> dict:
    py_files = sorted(root.rglob("*.py"))
    summary: dict[str, dict] = {}
    for package in V1_ROOTS:
        matches: list[str] = []
        needle_from = f"from {package}"
        needle_import = f"import {package}"
        for path in py_files:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if needle_from in text or needle_import in text:
                matches.append(str(path.relative_to(root)))
        summary[package] = {
            "direct_import_count": len(matches),
            "sample_files": matches[:12],
        }
    return summary


def classify_risk(import_count: int) -> str:
    if import_count >= 40:
        return "high"
    if import_count >= 10:
        return "medium"
    if import_count > 0:
        return "low"
    return "clear"


def build_report(summary: dict[str, dict]) -> dict:
    ranked = []
    for package, data in summary.items():
        count = int(data["direct_import_count"])
        ranked.append(
            {
                "package": package,
                "direct_import_count": count,
                "risk": classify_risk(count),
                "sample_files": data["sample_files"],
            }
        )
    ranked.sort(key=lambda item: (-item["direct_import_count"], item["package"]))
    return {
        "packages": ranked,
        "migration_candidates": {
            "phase_1_low_risk": [item["package"] for item in ranked if item["risk"] in {"clear", "low"}],
            "phase_2_medium_risk": [item["package"] for item in ranked if item["risk"] == "medium"],
            "phase_3_high_risk": [item["package"] for item in ranked if item["risk"] == "high"],
        },
    }


def write_markdown(path: Path, report: dict) -> None:
    lines = [
        "# V1 Import Audit",
        "",
        "This report shows how many direct top-level imports still reference each V1 package.",
        "",
        "## Packages",
        "",
        "| Package | Direct imports | Risk |",
        "| --- | ---: | --- |",
    ]
    for item in report["packages"]:
        lines.append(f"| `{item['package']}` | {item['direct_import_count']} | {item['risk']} |")

    lines.extend(
        [
            "",
            "## Suggested Move Order",
            "",
            f"- Phase 1 low risk: {', '.join(report['migration_candidates']['phase_1_low_risk']) or 'none'}",
            f"- Phase 2 medium risk: {', '.join(report['migration_candidates']['phase_2_medium_risk']) or 'none'}",
            f"- Phase 3 high risk: {', '.join(report['migration_candidates']['phase_3_high_risk']) or 'none'}",
            "",
        ]
    )

    for item in report["packages"]:
        if not item["sample_files"]:
            continue
        lines.append(f"### {item['package']}")
        lines.append("")
        for sample in item["sample_files"]:
            lines.append(f"- `{sample}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit direct V1 package imports before any EZ_V1 move")
    parser.add_argument("--out-json", help="Optional JSON output path")
    parser.add_argument("--out-md", help="Optional Markdown output path")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    report = build_report(audit_imports(repo_root))

    print("[v1-import-audit] direct import counts")
    for item in report["packages"]:
        print(f"- {item['package']}: {item['direct_import_count']} ({item['risk']})")

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.out_md:
        write_markdown(Path(args.out_md), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
