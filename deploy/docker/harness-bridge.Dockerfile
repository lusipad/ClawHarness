FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG CODEX_CLI_VERSION=0.118.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git nodejs npm ca-certificates \
    && npm install -g @openai/codex@${CODEX_CLI_VERSION} \
    && rm -rf /var/lib/apt/lists/*

COPY ado_client /app/ado_client
COPY codex_acp_runner /app/codex_acp_runner
COPY deploy/docker /app/deploy/docker
COPY harness_runtime /app/harness_runtime
COPY rocketchat_notifier /app/rocketchat_notifier
COPY run_store /app/run_store
COPY deploy/config /app/deploy/config

RUN python -m compileall /app

EXPOSE 8080

CMD ["python", "-m", "harness_runtime.main", "--bind", "0.0.0.0", "--port", "8080"]
