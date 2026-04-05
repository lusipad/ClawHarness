---
name: fix-pr-feedback
description: Apply unresolved PR review feedback against the active run and produce a targeted patch plan.
---

# fix-pr-feedback

## Purpose

Process unresolved PR comments, patch the active branch, and prepare the run for a push and recheck cycle.

## Inputs

- current diff
- unresolved review comments
- failing checks if present

## Required Output

- patch summary
- addressed comment set
- unresolved blockers
