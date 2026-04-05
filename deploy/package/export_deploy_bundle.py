from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "clawharness-deploy"
SOURCE_DIRS = [
    ".dockerignore",
    "ado_client",
    "codex_acp_runner",
    "harness_runtime",
    "openclaw-plugin",
    "rocketchat_notifier",
    "run_store",
    "deploy/config",
    "deploy/docker",
]
IGNORED_NAMES = {
    ".data",
    ".env",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
IGNORED_SUFFIXES = (".pyc", ".pyo")


BUNDLE_README = """# ClawHarness 独立部署包

## 快速开始

1. 将 `.env.example` 复制为 `.env`
2. 填写 `.env` 中的必要变量
3. Windows 运行：

```powershell
./up.ps1
```

4. Linux/macOS 运行：

```sh
chmod +x up.sh down.sh healthcheck.sh
./up.sh
```

5. 健康检查：

```sh
./healthcheck.sh
```

或：

```powershell
./healthcheck.ps1
```

## 说明

- 这个部署包已经包含构建镜像所需的最小源码子集，直接复制整个目录即可部署。
- `openclaw-gateway` 容器会默认安装固定版本的官方 `@openai/codex` CLI。
- `config.toml` 和 `auth.json` 会在容器启动时根据 `.env` 自动生成，不需要手工维护。
- 如使用 Codex 转发 endpoint，请填写：
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `CODEX_MODEL`
- 默认推荐只维护：
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `CODEX_MODEL`
  - `CODEX_REVIEW_MODEL`
  - `CODEX_REASONING_EFFORT`
- 如果必须完全接管内部 Codex 配置，再使用 `CODEX_HOME_DIR` 这类高级覆盖方式。
- 如不使用自定义入口，可将 `OPENAI_BASE_URL` 留空。
"""


UP_PS1 = r"""$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $scriptDir "compose.yml"
$envFile = Join-Path $scriptDir ".env"

if (-not (Test-Path $envFile)) {
  throw ".env not found. Copy .env.example to .env and fill the required values first."
}

docker compose --env-file $envFile -f $composeFile up --build -d
"""


DOWN_PS1 = r"""$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $scriptDir "compose.yml"
$envFile = Join-Path $scriptDir ".env"

if (-not (Test-Path $envFile)) {
  throw ".env not found."
}

docker compose --env-file $envFile -f $composeFile down
"""


HEALTHCHECK_PS1 = r"""$bridgeHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/healthz
$bridgeReady = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/readyz
$gatewayHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18789/healthz

if ($bridgeHealth.StatusCode -ne 200 -or $bridgeReady.StatusCode -ne 200 -or $gatewayHealth.StatusCode -ne 200) {
  throw "healthcheck failed"
}

Write-Host "healthcheck_ok"
"""


UP_SH = """#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"

if [ ! -f "$ENV_FILE" ]; then
  echo ".env not found. Copy .env.example to .env and fill the required values first." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up --build -d
"""


DOWN_SH = """#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"

if [ ! -f "$ENV_FILE" ]; then
  echo ".env not found." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
"""


HEALTHCHECK_SH = """#!/usr/bin/env sh
set -eu

curl -fsS http://127.0.0.1:8080/healthz >/dev/null
curl -fsS http://127.0.0.1:8080/readyz >/dev/null
curl -fsS http://127.0.0.1:18789/healthz >/dev/null

echo "healthcheck_ok"
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a standalone ClawHarness deployment bundle")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="target directory for the exported bundle")
    parser.add_argument("--force", action="store_true", help="overwrite the target directory if it already exists")
    return parser


def copy_path(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, ignore=_ignore_directory_entries)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _ignore_directory_entries(_: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in IGNORED_NAMES:
            ignored.add(name)
            continue
        if any(name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
            ignored.add(name)
    return ignored


def rewrite_compose_file(source_text: str) -> str:
    rewritten = source_text.replace("context: ../..", "context: ./src")
    rewritten = rewritten.replace("../config:/app/deploy/config:ro", "./src/deploy/config:/app/deploy/config:ro")
    return rewritten


def write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8", newline="\n")


def export_bundle(output_dir: Path, force: bool) -> None:
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)

    src_root = output_dir / "src"
    src_root.mkdir(parents=True, exist_ok=True)

    for relative in SOURCE_DIRS:
        source = REPO_ROOT / relative
        target = src_root / relative
        copy_path(source, target)

    compose_source = (REPO_ROOT / "deploy/docker/compose.yml").read_text(encoding="utf-8")
    write_text(output_dir / "compose.yml", rewrite_compose_file(compose_source))
    shutil.copy2(REPO_ROOT / "deploy/docker/.env.example", output_dir / ".env.example")
    write_text(output_dir / "README.md", BUNDLE_README)
    write_text(output_dir / "up.ps1", UP_PS1)
    write_text(output_dir / "down.ps1", DOWN_PS1)
    write_text(output_dir / "healthcheck.ps1", HEALTHCHECK_PS1)
    write_text(output_dir / "up.sh", UP_SH)
    write_text(output_dir / "down.sh", DOWN_SH)
    write_text(output_dir / "healthcheck.sh", HEALTHCHECK_SH)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    export_bundle(Path(args.output).resolve(), args.force)
    print(f"exported bundle to {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
