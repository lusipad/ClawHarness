---
name: recover-ci-failure
description: Triage failed CI runs and decide between patch-and-retry or escalation to a human.
---

# recover-ci-failure

## Purpose

Interpret CI failure evidence and route the run into recovery or escalation.

## Inputs

- CI failure summary
- latest code state

## Required Output

- retry decision
- patch summary when recoverable
- escalation summary when not recoverable
