---
name: implement-task
description: Turn an approved task plan into an ACP coding request and collect the execution result.
---

# implement-task

## Purpose

Use the `analyze-task` output, repository policies, and workspace path to drive Codex through ACP.

## Inputs

- plan output from `analyze-task`
- workspace path
- repository policies

## Required Output

- code changes
- test or check summary
- commit summary

## Guardrails

- no direct merge
- no protected-branch push
- checks must run before PR creation
