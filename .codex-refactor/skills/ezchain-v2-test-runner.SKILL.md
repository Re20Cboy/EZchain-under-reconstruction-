---
name: "ezchain-v2-test-runner"
description: "Use for choosing the smallest useful EZchain verification scope after code, config, script, acceptance, release, or doc changes. Escalate from focused tests to broader gates only when risk requires it."
---

# EZchain V2 Test Runner

Use this skill when the main job is to choose or justify the right verification scope.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- the main question is what to run after a change
- the task needs verification planning more than coding or debugging
- you need to justify why a focused test is enough or why a broader gate is required

## Do Not Use This When

- the main problem is locating a bug
- the right verification scope is already obvious
- the user explicitly asked for review or spec alignment instead

## Core Rule

Run the smallest meaningful verification first. Widen only when the changed path or residual risk really requires it.

## Verification Tiers

1. focused test file
2. grouped regression
3. acceptance path
4. app or security gate
5. release, adversarial, stability, or trial gate

## Quick Mapping

- protocol or core V2 logic: `EZ_Test/test_ez_v2_protocol.py`, then `python3 run_ezchain_tests.py --groups v2 --skip-slow` if needed
- wallet or storage: `EZ_Test/test_ez_v2_wallet_storage.py`, then nearby runtime or app tests if user flow changed
- runtime or localnet: `EZ_Test/test_ez_v2_runtime.py`, `EZ_Test/test_ez_v2_localnet.py`, then `python3 run_ez_v2_acceptance.py` if the user path changed
- CLI, service, or node manager: `EZ_Test/test_ez_v2_app_runtime.py`, `EZ_Test/test_ez_v2_node_manager.py`, then `python3 scripts/app_gate.py`
- release or ops scripts: changed script directly if possible, then `python3 scripts/release_gate.py --skip-slow`
- doc-only changes: usually no code tests, but verify changed commands when feasible

## Selection Rules

- prefer one file over one group when ownership is clear
- use acceptance when the user path changed
- use app or security gates when workflow or runtime wiring changed broadly
- use release, adversarial, stability, or trial gates only for higher-risk or release-facing work
- if a broad gate fails, reproduce the failing wrapped command directly

## Output

Report:

1. what changed
2. what you ran first
3. why that scope was enough or why it needed widening
4. what remains unverified
