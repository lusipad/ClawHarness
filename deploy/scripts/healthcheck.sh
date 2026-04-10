#!/usr/bin/env sh
set -eu

curl -fsS http://127.0.0.1:8080/healthz >/dev/null
curl -fsS http://127.0.0.1:8080/readyz >/dev/null

if docker inspect openclaw-gateway >/dev/null 2>&1; then
  if ! curl -fsS http://127.0.0.1:18789/healthz >/dev/null 2>&1; then
    gateway_health="$(docker inspect openclaw-gateway --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' 2>/dev/null || true)"
    if [ "$gateway_health" != "healthy" ]; then
      echo "gateway healthcheck failed" >&2
      exit 1
    fi
  fi
fi

echo "healthcheck_ok"
