ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
ARG CODEX_CLI_VERSION=0.118.0
FROM ${OPENCLAW_IMAGE}

USER root

RUN npm install -g @openai/codex@${CODEX_CLI_VERSION}

COPY deploy/docker/openclaw-gateway.json.template /opt/clawharness/openclaw.json.template
COPY deploy/docker/render_openclaw_config.mjs /opt/clawharness/render_openclaw_config.mjs
COPY deploy/docker/render_codex_auth.mjs /opt/clawharness/render_codex_auth.mjs
COPY deploy/docker/render_codex_config.mjs /opt/clawharness/render_codex_config.mjs
COPY deploy/docker/openclaw-gateway-entrypoint.sh /opt/clawharness/openclaw-gateway-entrypoint.sh
COPY openclaw-plugin /opt/clawharness/plugins/clawharness

RUN cd /opt/clawharness/plugins/clawharness && npm install --omit=dev

ENTRYPOINT ["sh", "/opt/clawharness/openclaw-gateway-entrypoint.sh"]
CMD ["node", "openclaw.mjs", "gateway", "--allow-unconfigured"]
