---
name: analyze-task
description: Analyze a normalized Azure DevOps task and prepare a structured execution plan for the harness flow.
---

# analyze-task

## Purpose

Read the normalized task payload, identify impacted files or modules, surface missing information, and produce a plan that `implement-task` can execute.

## Inputs

- normalized task metadata
- full task body
- repository context

## Required Output

- structured execution plan
- impacted files or modules
- missing information list
- risk level

## Guardrails

- stay within the existing repository patterns
- do not skip missing-information reporting
- do not claim implementation is ready unless the plan is specific enough to execute
