# AGENTS.md

Project rules for AI coding agents working in this repository.

## Mission

Build `EZchain-V2` into a real, runnable, verifiable blockchain system.

Default goal:

- move real V2 implementation forward
- strengthen runtime, validator, node, and transport behavior
- keep V1 frozen except for compatibility or migration seams

## Default Operating Bias

This repository is mainly an implementation project, not a report-writing project.

Default priority:

1. implementation and executable behavior
2. focused verification and gates
3. docs only when the changed code path made them wrong

Do not spend a turn polishing reports, checkpoints, or status wording unless:

- the user explicitly asked for that
- code or workflow changed and matching docs are now stale
- a release, trial, or readiness task explicitly requires that output

## Order Of Truth

For architecture, protocol, migration, network, or status questions, use this order:

1. `EZchain-V2-design/`
2. governance and readiness docs in `doc/`
3. current implementation

Read the minimum relevant design material first when intent matters:

- `EZchain-V2-design/EZchain-V2-protocol-draft.md`
- `EZchain-V2-design/EZchain-V2-consensus-mvp-spec.md`
- `EZchain-V2-design/EZchain-V2-implementation-roadmap.md`
- `EZchain-V2-design/EZchain-V2-module-migration-checklist.md`
- `EZchain-V2-design/EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-design/EZchain-V2-node-role-and-app-boundary.md`
- `EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`
- `doc/V2_DEFAULT_READINESS.md`
- latest `doc/PROJECT_CHECKPOINT_*.md` when status claims matter

If code and design disagree, say whether the code is:

- ahead of older design text
- behind the design
- temporarily divergent because the repo is still in transition

## Current Project Stance

- Active path: `EZ_V2/`, `EZ_App/`, `configs/`, `scripts/`, `EZ_Test/`, `doc/`
- Default local path uses V2 config, V2 CLI or service flow, and `run_ez_v2_acceptance.py`
- `v2-consensus`, `v2-account`, and official-testnet-oriented paths are real development targets
- V1 remains frozen compatibility and reference material
- This repository is still not a finished public-network V2 node stack

## Hard Red Lines

- Do not add new V2 semantics to V1 modules.
- Do not make `EZ_V2` depend on V1 core protocol objects such as `VPBManager`, `VPBValidator`, `TXPool`, `SubmitTxInfo`, or `BlockIndexList`.
- Do not reintroduce Bloom-based validation into the V2 path.
- Do not add `ProofUnit`-style compatibility wrappers as if they were part of final V2 design.
- Do not use `pickle` in V2 protocol, network, or signing paths.
- Do not add V2 state fields into V1 core objects.
- Do not overstate project status. "default dev path", "default validation path", and "default formal project path" are different claims.

## Ownership And Placement

Put work in `EZ_V2/` when it changes:

- protocol objects or semantics
- state transitions
- validator logic
- wallet or storage primitives
- runtime or localnet correctness
- transport-facing V2 internals

Put work in `EZ_App/` when it changes:

- CLI behavior
- service routes, auth, audit, metrics
- config parsing
- node lifecycle management
- user-facing runtime wiring
- node-mode entry and control flow

Put work in `scripts/` when it changes:

- gates
- release and readiness flow
- trial flow
- quickstart or ops tooling

Put work in `EZ_Test/` when it changes:

- expected behavior
- regression coverage
- acceptance coverage

Put work in `doc/` only when commands, behavior, workflow, structure, or status claims actually changed.

Touch V1 only for:

- explicit legacy tasks
- compatibility fixes
- clearly scoped migration seams

## Change Rules

- Keep edits scoped to the real task.
- Prefer incremental patches over broad rewrites.
- Do not rename major entry points or move top-level modules without a strong reason.
- Preserve CLI compatibility unless the task explicitly allows a breaking change.
- Say the tradeoff plainly when ownership or transition state is non-obvious.

## Validation Policy

Start with the smallest meaningful verification and widen only when the risk or changed path requires it.

Use this escalation order:

1. focused test file
2. grouped regression
3. acceptance path
4. app or security gate
5. release, adversarial, stability, or trial gate

Normal mapping:

- protocol or runtime logic: nearest `EZ_Test/test_ez_v2_*.py`
- cross-layer, user-facing, node, app, or script changes: use the nearest focused test first, then widen as needed
- acceptance-path or user-path changes: `python3 run_ez_v2_acceptance.py`
- app wiring or service flow: `python3 scripts/app_gate.py`
- security-sensitive or policy-sensitive workflow: `python3 scripts/security_gate.py`
- release, readiness, trial, packaging, or ops flow: `python3 scripts/release_gate.py --skip-slow` or a stronger matching gate

Common wider commands:

```bash
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
python3 scripts/app_gate.py
python3 scripts/security_gate.py
python3 run_ez_v2_acceptance.py
python3 scripts/release_gate.py --skip-slow
```

If you do not run the full relevant scope, say exactly what was not run and why.
If a broad gate fails, reproduce the first failing wrapped command directly before rerunning the whole gate.

## Documentation Sync

Docs are secondary to implementation.

Update matching docs only when:

- commands changed
- behavior changed
- workflow changed
- structure changed
- status or readiness claims changed

Check only the nearest relevant files, usually among:

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

Do not begin a coding task by polishing docs or reports.

## Skill Routing

Choose one primary skill by default. Combine skills only when the task truly mixes modes.

Primary default:

- `$ezchain-v2-delivery` for normal implementation work

Use these when the task is mainly about:

- `$ezchain-v2-architect`: layer ownership, module placement, refactor scope, cross-layer planning
- `$ezchain-v2-debugger`: failure diagnosis, reproduction, fault isolation
- `$ezchain-v2-test-runner`: picking the right verification scope
- `$ezchain-v2-protocol-review`: reviewing a patch for protocol, ownership, or regression risk
- `$ezchain-v2-spec-checker`: checking implementation or docs against the intended V2 design
- `$ezchain-v2-release-ops`: release, readiness, RC, canary, trial, or packaging flow

If unsure between implementation and review, default to delivery.
If unsure between review and design-conformance audit, use protocol review for a patch and spec checker for explicit design alignment work.

## Communication Style

- Use simple, direct, plain language.
- Avoid jargon unless it is necessary.
- If a project term is necessary, explain it briefly.
- Prefer short, concrete explanations over abstract wording.

## Default Workflow

1. identify the owning layer
2. identify the relevant design or governance rule
3. read the minimum nearby code and docs needed
4. choose one primary working mode or skill
5. implement or analyze the smallest coherent change
6. run focused verification and widen only when needed
7. update matching docs only if the changed path made them stale
8. report what changed, what was tested, what was not tested, and what risk remains
