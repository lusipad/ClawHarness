from __future__ import annotations

from codex_acp_runner import CodexAcpRunner, CodexCliRunner
from rocketchat_notifier import RocketChatNotifier

from .capability_registry import RuntimeCapabilityContext


def create_codex_cli_executor(context: RuntimeCapabilityContext) -> CodexCliRunner | None:
    del context
    return CodexCliRunner()


def create_codex_acp_executor(context: RuntimeCapabilityContext) -> CodexAcpRunner | None:
    if context.gateway_tool_client is None:
        return None
    return CodexAcpRunner(
        lambda payload: context.gateway_tool_client.invoke_tool(
            tool="sessions_spawn",
            action="session_spawn",
            args=payload,
        )
    )


def create_rocketchat_notifier(context: RuntimeCapabilityContext) -> RocketChatNotifier | None:
    config = context.config
    if not config.rocketchat.webhook_url:
        return None
    return RocketChatNotifier(
        webhook_url=config.rocketchat.webhook_url,
        default_channel=config.rocketchat.channel,
    )
