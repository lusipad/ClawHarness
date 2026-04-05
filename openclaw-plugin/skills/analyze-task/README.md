# `analyze-task`

Status: draft contract

## Purpose

Analyze a normalized task and produce the planning artifact that the coding executor will consume.

## Inputs

- normalized task metadata
- full task body
- repository context

## Required Output

- structured execution plan
- impacted files or modules
- missing information list
- risk level

## Acceptance Notes

- The output must be deterministic enough for `implement-task` to consume.
- The output must be saved or attached so the run can resume after interruption.
