# `openclaw-plugin/runtime`

Status: skeleton

Purpose:
- compose the runtime store, lock handling, dedupe, and audit helpers into the plugin layer

Planned subareas:
- db
- locks
- events
- audit

Implementation note:
- the executable bridge/runtime integration currently lives in the top-level Python package `harness_runtime/`
- this keeps the OpenClaw native plugin bundle lightweight while the webhook bridge owns ingress, persistence, and wake-up dispatch
