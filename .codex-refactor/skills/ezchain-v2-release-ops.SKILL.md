---
name: "ezchain-v2-release-ops"
description: "Use for explicit EZchain release, RC, readiness, canary, trial, packaging, stability, or operational workflow tasks where script behavior, evidence, and docs must stay aligned."
---

# EZchain V2 Release Ops

Use this skill when the task touches release readiness or operational workflow.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- release, RC, readiness, canary, trial, packaging, or stability flow changed
- a release-facing gate or script failed
- the task needs evidence and docs to stay aligned with operational behavior

## Do Not Use This When

- the task is normal feature delivery
- the task is pure architecture planning, patch review, or design-conformance checking
- the task is a local bug that should be narrowed before any release workflow is involved

## Core Rule

Keep release-facing workflow runnable, explainable, and honest. Passing a script is not enough if surrounding docs or readiness claims are stale.

## Main Areas

- developer gates: `run_ezchain_tests.py`, `run_ez_v2_acceptance.py`, `scripts/app_gate.py`, `scripts/security_gate.py`
- release and RC: `scripts/release_gate.py`, `scripts/release_report.py`, `scripts/prepare_rc.py`, `scripts/rc_gate.py`, `scripts/release_candidate.py`
- stability and canary: `scripts/stability_gate.py`, `scripts/stability_smoke.py`, `scripts/metrics_probe.py`, `scripts/canary_monitor.py`, `scripts/canary_gate.py`
- trial flow: `scripts/init_external_trial.py`, `scripts/update_external_trial.py`, `scripts/external_trial_gate.py`, `scripts/testnet_profile_gate.py`
- packaging: `scripts/package_app.py`

## Working Rules

- debug the first failing wrapped command directly
- keep script behavior, docs, and readiness claims aligned
- be careful when changing defaults used by CI, RC, or release evidence
- keep default local path, default validation path, and default formal project path separate

## Output

Report:

1. which operational path changed
2. which scripts and docs changed with it
3. which command or gate verified it
4. what still remains unverified
