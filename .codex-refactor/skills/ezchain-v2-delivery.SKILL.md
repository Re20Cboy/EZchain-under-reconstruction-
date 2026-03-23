---
name: "ezchain-v2-delivery"
description: "Default EZchain-V2 implementation mode for making runtime, node, validator, transport, localnet, and acceptance paths more runnable and verifiable. Use for normal coding work, not for explicit review or spec-audit tasks."
---

# EZchain V2 Delivery

Use this skill when the task is mainly to implement, fix, or advance a real V2 path.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- fixing or implementing V2 behavior
- improving runtime, validator, localnet, node, transport, or acceptance paths
- tightening real executable behavior, not just wording
- the task should end with code changes or a concrete runnable improvement

## Do Not Use This When

- the main question is where ownership belongs across layers
- the main question is what is broken and where
- the main question is what tests to run
- the user explicitly asked for review, audit, spec alignment, or release-ops work

## Core Rule

Move the real V2 system forward. Prefer runnable improvement over commentary.

## Delivery Questions

Always ask:

- what executable V2 path gets better if I solve this?
- what is the smallest coherent change that improves that path?
- what is the narrowest verification that proves the improvement?
- did the changed path make any user or developer doc stale?

## Working Bias

- prefer real runtime progress over status wording
- prefer small code patches over broad cleanup
- prefer active V2 paths over legacy branches
- prefer matching tests over broad gates until risk requires widening

## Typical Areas

- `EZ_V2/` for protocol, runtime, validator, wallet, storage, localnet, and transport-facing internals
- `EZ_App/` for CLI, service, config, node lifecycle, and node-mode wiring
- `EZ_Test/` for coverage of changed behavior

## Output

Report:

1. which real V2 path improved
2. what changed
3. what verification proved it
4. what still remains rough, partial, or unverified
