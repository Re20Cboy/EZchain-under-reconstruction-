# AGENTS.md

Repository rules for AI coding agents in this project.

## Mission

Ship `EZchain-V2` as the real runnable and verifiable path.

- `EZchain-V2` is the default development, validation, and RC path.
- V1 is frozen except for explicit compatibility or migration seams.
- Most work should strengthen runtime behavior, tests, gates, and readiness evidence.

## Default Priorities

1. keep active V2 paths runnable and honest
2. close the smallest real verification gap
3. update docs only when behavior, workflow, commands, or status claims changed

If the task is ambiguous, prefer debugging, hardening, and validation over expanding scope.

## Scope

Use the narrowest owning layer:

- `EZ_V2/`: protocol, chain state, validator, wallet, storage, runtime, localnet, transport-facing internals
- `EZ_App/`: CLI, service, config, auth, metrics, lifecycle, app wiring
- `scripts/`: gates, readiness, release, packaging, trial, ops
- `EZ_Test/`: regressions, acceptance, readiness evidence
- `doc/`: only when nearby docs became stale

Do not add new V2 semantics to V1 code.

## Design Truth

When intent matters, prefer:

1. the nearest relevant file in `EZchain-V2-design/`
2. `doc/V2_DEFAULT_READINESS.md` and latest `doc/PROJECT_CHECKPOINT_*.md` when status claims matter
3. current implementation

Read only what is needed. If code and design disagree, say whether code is ahead, behind, or temporarily divergent.

## Hard Rules

- Do not make `EZ_V2` depend on V1 core protocol objects.
- Do not reintroduce Bloom-based validation into the V2 path.
- Do not use `pickle` in V2 protocol, network, or signing paths.
- Do not add extra sender/recipient/network/storage/compute cost just to simplify implementation or testing.
- Do not overstate project status. Default dev path, default validation path, and formal delivery path are not the same thing.

## Distributed Defaults

For transport, runtime, validator, wallet sync, storage, localnet, acceptance, or multi-host work:

- assume single-node success is weak evidence
- check restart, replay, duplicate delivery, out-of-order messages, stale local state, reconnect, timeout, and mixed old/new state
- prefer idempotent writes, deterministic serialization, and explicit recovery behavior
- separate real code bugs from stale state, topology mismatch, port collisions, and reachability issues

For throughput or scale testing:

- prefer realistic local workload shapes
- let the mempool accumulate and pack as many pending bundles into a block as current safety rules allow
- treat `one tx -> one block` as an anti-pattern unless the test is explicitly about single-submit sequencing

## Change Rules

- Keep changes scoped and coherent.
- Prefer small patches over broad rewrites.
- Preserve major CLI and entry-point compatibility unless the task explicitly allows a break.
- Be explicit when ownership or transition-state tradeoffs are unclear.
- Before adding any new message, persistence field, or background sync, prove the extra cost is required by the design rather than a local shortcut.

## Validation

Start small and widen only when risk requires it.

Escalation order:

1. focused test file
2. grouped regression
3. acceptance path
4. app or security gate
5. release, adversarial, stability, or trial gate

Common commands:

```bash
python3 run_ez_v2_acceptance.py
python3 scripts/app_gate.py
python3 scripts/security_gate.py
python3 scripts/release_gate.py --skip-slow
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
```

If you do not run the full relevant scope, say exactly what was not run and why.

## Communication

- Use plain, direct language.
- Avoid unexplained internal jargon.
- When explaining EZchain-V2 concepts, prefer the wording style used in `EZchain-V2-design/EZchain-V2 desgin-human-write.md`.
- If a technical term is necessary, explain it briefly in everyday language.

## Default Workflow

1. identify the owning layer
2. identify the relevant design or governance rule
3. read the minimum nearby code and docs needed
4. choose one primary skill or mode
5. make the smallest coherent change
6. run focused verification and widen only when needed
7. update the nearest stale docs if needed
8. report what changed, what was tested, what was not tested, and what risk remains
