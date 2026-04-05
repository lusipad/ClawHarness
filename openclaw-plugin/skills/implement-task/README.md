# `implement-task`

Status: draft contract

## Purpose

Turn the `analyze-task` output into a coding request for the ACP executor and collect the result.

## Inputs

- plan output from `analyze-task`
- workspace path
- repository policies

## Required Output

- code changes
- test or check summary
- commit summary

## Acceptance Notes

- The skill must preserve the no-direct-merge and protected-branch rules.
- The skill must provide enough output for the PR and resume flows to continue without re-analysis.
