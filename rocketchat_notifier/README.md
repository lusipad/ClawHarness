# `rocketchat_notifier`

Status: skeleton

Purpose:
- send lifecycle notifications to Rocket.Chat through webhook delivery

MVP events:
- task started
- PR opened
- CI failed
- task blocked
- task completed

Next implementation focus:
- define webhook payload templates
- record delivery success and failure in the runtime audit trail

Current baseline:
- Python stdlib notifier implementation exists in `rocketchat_notifier/notifier.py`
- lifecycle payloads use the Rocket.Chat incoming webhook message structure
- delivery tests cover payload formatting and HTTP failure handling
