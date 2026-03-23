---
name: "ezchain-v2-debugger"
description: "Use for EZchain failure diagnosis: capture the exact failure, reproduce it narrowly, separate code bugs from config or state issues, and identify the true fault domain before editing."
---

# EZchain V2 Debugger

Use this skill when the main question is what is actually broken and where.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- a command, test, service, gate, or user path is failing
- the first job is to reproduce and narrow the fault domain
- stale state, config, or environment may be involved

## Do Not Use This When

- the bug location is already obvious and the task is just implementation
- the main question is architectural ownership
- the task is primarily about choosing verification scope after a change

## Core Rule

Find the smallest true fault domain before editing code.

## First Questions

- what exact command, test, or user path fails?
- is the active path using `protocol_version=v1` or `protocol_version=v2`?
- is the failure in CLI, service, runtime, config, script, test, or local state?
- is it reproducible?
- could stale local state explain it?

## Default Order

1. capture the failure exactly
2. reproduce it with the smallest useful command
3. inspect config and local state
4. read the owning code path
5. fix the narrowest real cause
6. rerun the smallest meaningful verification

## Common Starting Points

- CLI or wallet flow: `ezchain_cli.py`, `EZ_App/cli.py`, `EZ_App/runtime.py`
- service flow: `EZ_App/service.py`, `EZ_App/runtime.py`, `EZ_App/node_manager.py`
- V2 runtime: `EZ_V2/runtime_v2.py`, `EZ_V2/localnet.py`, nearby `EZ_V2/` modules
- gates or acceptance: `run_ez_v2_acceptance.py`, `scripts/app_gate.py`, `scripts/release_gate.py`

## State Check Reminder

Inspect the selected config, `.ezchain/`, `.ezchain_v2/`, `blockchain_data/`, and related wallet or log files before blaming code.
Do not mass-delete state unless you can explain why it matters.

## Output

Report:

1. smallest reproduction
2. real fault domain
3. fix or blocker
4. exact verification rerun
