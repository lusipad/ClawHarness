# `recover-ci-failure`

Status: draft contract

## Purpose

Interpret CI failure evidence and decide whether the run should patch and retry or escalate to a human.

## Inputs

- CI failure summary
- latest code state

## Required Output

- retry decision
- patch summary when recoverable
- escalation summary when not recoverable
