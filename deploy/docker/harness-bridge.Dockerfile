FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY ado_client /app/ado_client
COPY codex_acp_runner /app/codex_acp_runner
COPY harness_runtime /app/harness_runtime
COPY rocketchat_notifier /app/rocketchat_notifier
COPY run_store /app/run_store
COPY deploy/config /app/deploy/config

RUN python -m compileall /app

EXPOSE 8080

CMD ["python", "-m", "harness_runtime.main", "--bind", "0.0.0.0", "--port", "8080"]
