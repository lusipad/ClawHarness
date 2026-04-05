#!/usr/bin/env sh
set -eu

curl -fsS http://127.0.0.1:8080/healthz >/dev/null
curl -fsS http://127.0.0.1:8080/readyz >/dev/null
curl -fsS http://127.0.0.1:18789/healthz >/dev/null

echo "healthcheck_ok"
