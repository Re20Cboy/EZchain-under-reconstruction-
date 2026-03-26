# AGENTS.md

Project rules for AI coding agents working in this repository.

## Mission

Land `EZchain-V2` as the real runnable and verifiable path.

Current phase:

- `EZchain-V2` is already the default development, validation, and RC path.
- Most work should tighten runtime behavior, tests, gates, and readiness evidence.
- V1 stays frozen except for compatibility or migration seams.
- Readiness still decides whether V2 counts as the default formal delivery path.

## Working Bias

Default priority:

1. keep active V2 paths runnable and honest
2. close verification gaps with the smallest useful test or gate
3. update docs only when behavior, commands, workflow, structure, or status claims changed

If the task is ambiguous, prefer hardening, debugging, or validation work over expanding scope.
Do not spend a turn polishing reports or status wording unless the task is explicitly about docs, release, readiness, or trial evidence.

## Distributed Reality

For transport, runtime, validator, wallet sync, storage, localnet, node-manager, acceptance, or multi-host work, think in distributed-system terms first.

- Assume single-node success is not enough evidence for a distributed path.
- Check restart, replay, duplicate delivery, out-of-order messages, partial write, stale or dirty local state, peer mismatch, timeout, reconnect, and concurrent startup risk.
- Distinguish code bugs from config mismatch, topology mismatch, port/path collision, stale disk state, and real network reachability problems.
- Prefer idempotent writes, deterministic serialization, explicit recovery behavior, and safe startup with existing on-disk data.
- If a path touches persistence or cross-node sync, ask what happens after restart, resync, and mixed old/new state.

## Order Of Truth

When intent matters, use:

1. the nearest relevant file in `EZchain-V2-design/`
2. `doc/V2_DEFAULT_READINESS.md` and the latest `doc/PROJECT_CHECKPOINT_*.md` when status claims matter
3. current implementation

Typical design reads are:

- `EZchain-V2-protocol-draft.md`
- `EZchain-V2-consensus-mvp-spec.md`
- `EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-node-role-and-app-boundary.md`
- `EZchain-V1-freeze-and-V2-default-transition.md`

Read only the minimum needed.
If code and design disagree, say whether code is ahead, behind, or temporarily divergent.

## Current Stance

- Active path: `EZ_V2/`, `EZ_App/`, `configs/`, `scripts/`, `EZ_Test/`, `doc/`
- Default local path: V2 config plus V2 CLI or service flow
- Default acceptance path: `python3 run_ez_v2_acceptance.py`
- Real targets include `v2-consensus`, `v2-account`, official-testnet flow, readiness evidence, and release evidence
- Do not describe the repo as a finished public-network V2 stack

## Hard Red Lines

- Do not add new V2 semantics to V1 modules.
- Do not make `EZ_V2` depend on V1 core protocol objects such as `VPBManager`, `VPBValidator`, `TXPool`, `SubmitTxInfo`, or `BlockIndexList`.
- Do not reintroduce Bloom-based validation into the V2 path.
- Do not add `ProofUnit`-style compatibility wrappers as if they were final V2 design.
- Do not use `pickle` in V2 protocol, network, or signing paths.
- Do not add V2 state fields into V1 core objects.
- Do not overstate project status. Keep default dev path, default validation path, and default formal delivery path separate.

## Ownership

Use the narrowest owning layer:

- `EZ_V2/`: protocol, state transition, validator, wallet, storage, runtime, localnet, transport-facing V2 internals
- `EZ_App/`: CLI, service, config, auth, metrics, node lifecycle, app-facing runtime wiring
- `scripts/`: gates, readiness, release, trial, packaging, and ops tooling
- `EZ_Test/`: focused regressions, acceptance coverage, readiness coverage
- `doc/`: only when commands, behavior, workflow, structure, or status claims changed

Touch V1 only for explicit legacy tasks, compatibility fixes, or clearly scoped migration seams.

## Change Rules

- Keep edits scoped to the real task.
- Prefer small coherent patches over broad rewrites.
- Preserve CLI and major entry-point compatibility unless the task explicitly allows a break.
- Prefer extending existing modules over adding new top-level structure.
- Say the tradeoff plainly when ownership or transition state is unclear.
- For V2 consensus and multi-node scripts, do not treat "one submit immediately triggers one round" as proof of mempool or batching correctness; verify snapshot-based multi-bundle behavior explicitly.

## Validation

Start with the smallest meaningful verification and widen only when change or risk requires it.

Escalation order:

1. focused test file
2. grouped regression
3. acceptance path
4. app or security gate
5. release, adversarial, stability, or trial gate

Normal mapping:

- protocol or runtime logic: nearest `EZ_Test/test_ez_v2_*.py`
- transport, storage, localnet, multi-node, or cross-node sync changes: nearest focused test, then add one restart, dirty-state, reconnect, or multi-node check when feasible
- CLI, service, node, config, or script changes: nearest focused test first, then widen
- acceptance or user-path changes: `python3 run_ez_v2_acceptance.py`
- app wiring or service flow: `python3 scripts/app_gate.py`
- security-sensitive workflow: `python3 scripts/security_gate.py`
- readiness, release, trial, packaging, or ops flow: `python3 scripts/release_gate.py --skip-slow` or the nearest stronger gate

Useful wider commands:

```bash
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
python3 scripts/app_gate.py
python3 scripts/security_gate.py
python3 run_ez_v2_acceptance.py
python3 scripts/release_gate.py --skip-slow
```

If you do not run the full relevant scope, say exactly what was not run and why.
If a broad gate fails, reproduce the first failing wrapped command directly before rerunning the gate.

## Context Budget

- Read one relevant design or governance file at a time unless a conflict requires more.
- Use one primary skill by default; do not stack skills just because several seem loosely related.
- Prefer short working summaries over re-reading and re-quoting long docs.
- Reuse already gathered context; do not reopen the same long files without a new reason.
- In reports, keep background brief and spend tokens on changed behavior, verification, and remaining risk.

## Documentation Sync

Docs are secondary to executable behavior.

Update only the nearest affected docs, usually among:

- `README.md`
- `README.zh-CN.md`
- `doc/README.md`
- `doc/USER_QUICKSTART.md`
- `doc/EZchain-V2-quickstart.md`
- `doc/DEV_TESTING.md`
- `doc/RELEASE_CHECKLIST.md`
- `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`
- `doc/PROJECT_STRUCTURE.md`
- `doc/V2_DEFAULT_READINESS.md`

Do not start a coding task with doc polishing.

## Skill Routing

Use one primary skill by default:

- `$ezchain-v2-delivery`: normal implementation, hardening, and bug-fix work
- `$ezchain-v2-architect`: ownership, placement, refactor scope, cross-layer planning
- `$ezchain-v2-debugger`: failure reproduction and fault isolation
- `$ezchain-v2-test-runner`: verification-scope selection
- `$ezchain-v2-protocol-review`: explicit patch review or audit
- `$ezchain-v2-spec-checker`: explicit design-conformance checking
- `$ezchain-v2-release-ops`: readiness, release, RC, canary, trial, or packaging work

If unsure, default to delivery.

## Communication Style

- Use simple, direct language.
- Prefer short, concrete explanations.
- Explain project terms briefly when they matter.

## Default Workflow

1. identify the owning layer
2. identify the relevant design or governance rule
3. read the minimum nearby code and docs needed
4. choose one primary skill or mode
5. make the smallest coherent change
6. run focused verification and widen only when needed
7. update matching docs only if the changed path made them stale
8. report what changed, what was tested, what was not tested, and what risk remains
