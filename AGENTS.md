# AGENTS.md

This file gives project-specific rules for AI coding agents working in this repository.

## Mission

Strengthen `EZchain-V2` as the default development and validation path without hiding that this repository is still in a transition stage.

Default goal:

- keep V2 moving forward
- avoid pushing new work back into V1
- prefer small, testable, explainable changes

## Order Of Truth

For architecture, protocol, migration, network, or status questions, use this order:

1. `EZchain-V2-design/` design documents
2. governance and readiness docs in `doc/`
3. current code

Read these first when the task touches design intent:

- `EZchain-V2-design/EZchain-V2-protocol-draft.md`
- `EZchain-V2-design/EZchain-V2-implementation-roadmap.md`
- `EZchain-V2-design/EZchain-V2-module-migration-checklist.md`
- `EZchain-V2-design/EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`
- `doc/V2_DEFAULT_READINESS.md`
- latest `doc/PROJECT_CHECKPOINT_*.md`

If code and design disagree, do not silently assume the code is the intended answer.
State clearly whether the code is:

- ahead of the older design text
- behind the design
- temporarily divergent because the repo is still in transition

## Hard Red Lines

- Do not add new V2 semantics to V1 modules.
- Do not make `EZ_V2` depend on V1 core protocol objects such as `VPBManager`, `VPBValidator`, `TXPool`, `SubmitTxInfo`, or `BlockIndexList`.
- Do not reintroduce Bloom-based validation into the V2 path.
- Do not add `ProofUnit`-style compatibility wrappers as if they were part of final V2 design.
- Do not use `pickle` in V2 protocol, network, or signing paths.
- Do not add V2 state fields into V1 core objects.
- Do not overstate project status. "default dev path", "default validation path", and "default formal project path" are not the same claim.

## Current Project Stance

- Active path: `EZ_V2/`, `EZ_App/`, `configs/`, `scripts/`, `EZ_Test/`, `doc/`
- V1 stays in the repo as frozen compatibility and reference material
- Default local path uses V2 config, V2 CLI/service flow, and `run_ez_v2_acceptance.py`
- Lightweight V2 node modes such as `v2-consensus` and `v2-account` exist, but do not treat that as proof that the full V2 network plan is complete
- This repository is still not a finished public-network V2 node stack

## Placement Rules

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

Put work in `scripts/` when it changes:

- release gates
- RC flow
- trial flow
- quickstart or ops tooling

Put work in `EZ_Test/` when it changes:

- expected behavior
- regression coverage
- acceptance coverage

Put work in `doc/` when it changes:

- user instructions
- developer workflow
- release or trial workflow
- structure or status claims

Touch V1 only for:

- explicit legacy tasks
- compatibility fixes
- clearly scoped migration seams

## Change Rules

- Keep edits scoped to the real task.
- Prefer incremental patches over broad rewrites.
- Do not rename major entry points or move top-level modules without a strong reason.
- Preserve CLI compatibility unless the task explicitly allows a breaking change.
- If a tradeoff is non-obvious, explain it clearly.

## Validation Rules

Start with the narrowest relevant test.

For cross-layer, user-facing, runtime, app, or script changes, the normal local baseline is:

```bash
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
python3 scripts/app_gate.py
python3 scripts/security_gate.py
```

Also use:

- `python3 run_ez_v2_acceptance.py` for user-path or acceptance-path changes
- `python3 scripts/release_gate.py --skip-slow` or a matching stronger gate for release and ops changes

If you do not run the full relevant scope, say exactly what was not run and why.

## Documentation Rules

When commands, behavior, workflow, structure, or status claims change, update the matching docs.

Check the nearest relevant files in:

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

Keep status language aligned with readiness and checkpoint docs.

## Skill Preference

If EZchain project skills are available, use the matching one:

- `$ezchain-v2-architect`
- `$ezchain-v2-debugger`
- `$ezchain-v2-test-runner`
- `$ezchain-v2-protocol-review`
- `$ezchain-v2-doc-sync`
- `$ezchain-v2-release-ops`
- `$ezchain-v2-spec-checker`

## Communication Style

- Use simple, direct, plain language.
- Avoid jargon unless it is necessary.
- If a project term is necessary, explain it briefly.
- Prefer short, concrete explanations over abstract wording.

## Default Workflow

1. identify the owning layer
2. identify the relevant design or governance rule
3. read the minimum nearby code and docs needed
4. make the smallest coherent change
5. run focused verification
6. report what changed, what was tested, and what risk remains
