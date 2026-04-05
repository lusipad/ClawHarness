# `codex_acp_runner`

Status: skeleton

Purpose:
- execute coding work through OpenClaw ACP
- resume existing coding sessions for PR feedback and CI recovery
- return structured execution summaries to the plugin flows

Next implementation focus:
- define the ACP request and response wrapper
- map `run_id`, `session_id`, and `workspace_path`
- support run, resume, and cancel behavior
