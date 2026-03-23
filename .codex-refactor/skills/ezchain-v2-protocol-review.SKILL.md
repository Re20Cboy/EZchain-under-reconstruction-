---
name: "ezchain-v2-protocol-review"
description: "Use for explicit EZchain review of a patch or proposed change when you need to look for protocol correctness risk, wrong layer ownership, migration seam abuse, missing tests, or stale docs."
---

# EZchain V2 Protocol Review

Use this skill when the user wants a review, audit, or risk check on a concrete change.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- reviewing a patch, diff, or proposed change
- checking for protocol correctness, ownership drift, or regression risk
- deciding whether tests and docs are strong enough for a specific change

## Do Not Use This When

- the main task is to implement a feature
- the main question is whether the whole current implementation matches design docs
- the main question is just which layer should own a new change

## Core Rule

Review the change against design intent and system coherence, not just whether the code looks locally reasonable.

## Review Questions

- did protocol semantics change, or only app behavior?
- is the logic in the correct layer?
- does the change create state, replay, validation, or consistency risk?
- does it increase V1 coupling or make a temporary seam more permanent?
- are focused tests and matching docs strong enough for this exact change?

## What To Flag

- protocol logic hidden in CLI or service glue
- silent architecture drift
- semantic changes without focused tests
- runtime changes without acceptance consideration
- public workflow changes without matching doc updates

## Priority Order

1. correctness or data-integrity risk
2. wrong ownership or architecture drift
3. missing regression coverage
4. stale docs or misleading status claims

## Output

Report:

1. main risk
2. why it matters
3. where ownership looks wrong, if applicable
4. what tests or docs are missing
5. residual risk if no major bug is found
