#!/usr/bin/env sh
set -eu

OPENCLAW_HOME="${HOME:-/home/node}/.openclaw"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-${OPENCLAW_HOME}/openclaw.json}"
OPENCLAW_FORCE_RENDER_CONFIG="${OPENCLAW_FORCE_RENDER_CONFIG:-0}"
CODEX_HOME="${CODEX_HOME:-${HOME:-/home/node}/.codex}"
CODEX_AUTH_PATH="${CODEX_AUTH_PATH:-${CODEX_HOME}/auth.json}"
CODEX_CONFIG_PATH="${CODEX_CONFIG_PATH:-${CODEX_HOME}/config.toml}"
PLUGIN_SOURCE="/opt/clawharness/plugins/clawharness"
PLUGIN_TARGET="${OPENCLAW_HOME}/plugins/clawharness"

mkdir -p "${OPENCLAW_HOME}/plugins"
mkdir -p "$(dirname "${OPENCLAW_CONFIG_PATH}")"
mkdir -p "${CODEX_HOME}"

if [ -n "${OPENAI_API_KEY:-}" ]; then
  node /opt/clawharness/render_codex_auth.mjs "${CODEX_AUTH_PATH}"
  chmod 600 "${CODEX_AUTH_PATH}" 2>/dev/null || true
fi

if [ -n "${OPENAI_API_KEY:-}" ] || [ -n "${OPENAI_BASE_URL:-}" ] || [ -n "${CODEX_MODEL:-}" ]; then
  node /opt/clawharness/render_codex_config.mjs "${CODEX_CONFIG_PATH}"
  chmod 600 "${CODEX_CONFIG_PATH}" 2>/dev/null || true
fi

if [ ! -e "${PLUGIN_TARGET}" ] && [ ! -L "${PLUGIN_TARGET}" ]; then
  ln -s "${PLUGIN_SOURCE}" "${PLUGIN_TARGET}"
fi

if [ "${OPENCLAW_FORCE_RENDER_CONFIG}" = "1" ] || [ ! -f "${OPENCLAW_CONFIG_PATH}" ]; then
  node /opt/clawharness/render_openclaw_config.mjs
fi

exec docker-entrypoint.sh "$@"
