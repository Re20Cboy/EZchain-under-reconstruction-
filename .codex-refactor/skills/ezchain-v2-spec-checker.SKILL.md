---
name: "ezchain-v2-spec-checker"
description: "Use for explicit EZchain design-conformance work: compare current code, tests, docs, or workflow against the intended V2 design and classify each checked point as aligned, temporary divergence, drift, or unclear."
---

# EZchain V2 Spec Checker

Use this skill when the main question is whether current repository reality still matches intended V2 design.

Read `AGENTS.md` first. Treat it as the source of repo-wide defaults.

## Use This When

- the user explicitly asks whether implementation matches design
- the task is to classify code or docs as aligned, temporary divergence, drift, or unclear
- you are checking a design statement, not merely reviewing a patch

## Do Not Use This When

- the task is ordinary implementation
- the task is patch review
- the task is mainly architecture placement or bug diagnosis

## Core Rule

Separate transition-state differences from real drift. Do not assume working code is automatically spec-compliant.

## Comparison Order

1. identify the exact design statement being checked
2. read the relevant design and governance docs
3. read the owning implementation files
4. compare tests and docs that describe the same path
5. classify the result plainly

## Main Questions

- what exact design statement am I checking?
- where is that statement implemented today?
- is the current state aligned, temporarily divergent, drifted, or unclear?
- if it differs, should code change, should docs change, or should design text change?

## Labels

- `aligned`
- `temporarily divergent but explained`
- `drifted and should be corrected`
- `unclear`

## Output

Report:

1. design statement checked
2. file, test, doc, or behavior compared
3. classification
4. reason
5. recommended follow-up
