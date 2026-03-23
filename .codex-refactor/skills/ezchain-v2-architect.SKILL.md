---
name: "ezchain-v2-architect"
description: "Use for EZchain-V2 layer ownership, module placement, refactor scope, cross-layer planning, and V1 vs V2 boundary decisions. Use when the main risk is architectural drift, not when the task is ordinary coding or debugging."
---

# EZchain V2 Architect

Use this skill when the task needs architecture judgment before or alongside code changes.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- deciding whether logic belongs in `EZ_V2/`, `EZ_App/`, `scripts/`, `EZ_Test/`, or `doc/`
- planning a refactor that crosses module or layer boundaries
- judging whether a V1/V2 seam is acceptable or drifting into the wrong architecture
- deciding whether a proposed status claim is too strong for current repo reality

## Do Not Use This When

- the task is straightforward implementation in an already obvious owning layer
- the main question is reproducing a failure
- the user wants a patch review or a design-conformance audit

## Core Rule

Choose the narrowest correct owning layer and strengthen V2 without pretending transition seams are already finished.

## Decision Questions

Always ask:

- what layer truly owns this behavior?
- is this protocol semantics, app wiring, workflow tooling, test coverage, or documentation?
- does the change reduce or increase V1 dependence in active V2 paths?
- is a small placement fix enough, or is a broader refactor truly necessary?

## Architecture Checks

- do not hide protocol logic in CLI or service glue
- do not turn temporary compatibility seams into permanent architecture silently
- prefer extending an existing module over creating a new top-level area
- keep transition-state caveats explicit when they matter

## Output

Report:

1. chosen ownership
2. why it is the least risky placement
3. what neighboring code, tests, or docs should move with it
4. any transition-state caveat that still remains
