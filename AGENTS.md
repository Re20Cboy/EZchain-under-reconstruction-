# AGENTS.md

This file gives AI coding agents project-specific guidance for working in this repository.

## Mission

EZchain is a research-to-product blockchain codebase in transition from legacy V1 modules to the active V2 lane.

Default objective:

- Preserve the repository's transition direction
- Prefer practical, testable improvements over speculative rewrites
- Keep changes small, readable, and easy to verify

## Default Working Stance

- Treat `EZ_V2/`, `EZ_App/`, `configs/`, `scripts/`, `EZ_Test/`, and `doc/` as the active path
- Treat V1 modules as legacy/reference unless the task explicitly targets them
- Read existing docs and nearby code before editing
- Match the current code style instead of introducing a new architecture unnecessarily
- Avoid broad refactors unless they are required to unblock the requested task

## Communication Style

- When talking to the user, use simple, clear, and direct language
- Prefer plain, everyday wording over technical jargon, slang, or academic phrasing
- Explain ideas in a straightforward way so they are easy to understand quickly
- Only use specialized terms when they are truly necessary, and explain them briefly when used

## Priority Map

When multiple paths seem possible, prefer this order:

1. Fix or extend the V2 lane
2. Update docs and tests to match behavior
3. Touch legacy/V1 code only when necessary for compatibility, migration, or explicit user requests

## Repository Guidance

### Active implementation

- `EZ_V2/`: protocol core, runtime, validator, localnet
- `EZ_App/`: CLI, service API, runtime bridge, node lifecycle manager
- `configs/`: runnable config templates
- `scripts/`: gates, quickstarts, release and ops utilities
- `EZ_Test/`: integration, acceptance, and runtime coverage
- `doc/`: user, developer, release, and runbook documentation

### Legacy/reference implementation

- `EZ_VPB/`
- `EZ_VPB_Validator/`
- `EZ_Tx_Pool/`
- `EZ_Main_Chain/`
- `EZ_Account/`
- `EZ_Transaction/`

Do not migrate work back into V1 modules unless the task explicitly requires it.

## Change Rules

- Keep edits scoped to the user's request
- Do not silently rename major modules, move public entry points, or delete large sections of legacy code
- Preserve backward-compatible CLI behavior unless the task explicitly allows breaking changes
- Prefer incremental patches over "clean slate" rewrites
- If you must make a non-obvious tradeoff, explain it in the final handoff

## Testing Expectations

Choose the smallest meaningful verification that matches the change.

Common commands:

```bash
python3 run_ezchain_tests.py --list
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ez_v2_acceptance.py
python3 scripts/release_gate.py --skip-slow
```

Testing guidance:

- For targeted code changes, run the narrowest relevant test first
- For V2 runtime, CLI, service, or config changes, prefer V2-focused tests
- For release or operational script changes, run the closest matching script-level gate if feasible
- If a full test run is too expensive or blocked, say what was not run and why

## Documentation Expectations

Update documentation when behavior, commands, workflow, or repository guidance changes.

Likely docs to check:

- `README.md`
- `doc/README.md`
- `doc/DEV_TESTING.md`
- `doc/USER_QUICKSTART.md`
- `doc/RELEASE_CHECKLIST.md`
- `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

## Safety Rails

- Do not overwrite or revert user changes you did not create
- Check `git status` before risky edits when the workspace may be dirty
- Avoid destructive commands such as hard resets or mass deletions unless explicitly requested
- Be careful with generated state under `.ezchain/`, `.ezchain_v2/`, `blockchain_data/`, and local environment files

## Preferred Agent Workflow

1. Read the relevant README, docs, and nearby implementation
2. Confirm whether the task belongs to V2, docs, tests, scripts, or legacy compatibility
3. Make the smallest coherent change
4. Run focused verification
5. Summarize what changed, what was tested, and any remaining risk

## Good Defaults For This Repo

- Prefer V2 localnet and service workflows over older demonstrations
- Prefer explicit configs and documented commands
- Keep acceptance and release paths runnable
- Respect the repository's current transition plan instead of forcing an idealized redesign

## When Unsure

- Choose the path that strengthens V2 without destabilizing the repository
- Ask for clarification only when the choice could cause architectural churn or compatibility risk
