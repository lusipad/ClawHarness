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
    "github_client",
    "harness_runtime",
    "local_client",
    "openclaw-plugin",
    "rocketchat_notifier",
    "run_store",
    "workflow_provider",
    "deploy/config",
    "deploy/docker",
    "deploy/windows",
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

Windows 推荐直接运行一键引导：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key>
```

如果你更希望按提示一步一步选择安装方式，也可以直接运行快速向导：

```powershell
./bootstrap.ps1 -Interactive
```

在交互式 PowerShell 里直接运行 `./bootstrap.ps1`，现在也会自动进入快速向导。
向导结束前会展示安装摘要，并在完成后自动执行一次安装检查。

如果你确实需要原生安装、更多目录选项或完整高级参数，再使用：

```powershell
./bootstrap.ps1 -Interactive -Advanced
```

如果你要显式选择安装路径：

```powershell
./bootstrap.ps1 -InstallMode docker -OpenAiApiKey <your-key>
./bootstrap.ps1 -InstallMode native-core -OpenAiApiKey <your-key>
./bootstrap.ps1 -InstallMode native-openclaw -OpenAiApiKey <your-key>
```

安装或配置完成后，可以运行：

```powershell
./check-install.ps1 -InstallMode docker
./check-install.ps1 -InstallMode native-core
./check-install.ps1 -InstallMode native-openclaw
```

如需顺手检查本机服务是否真的已经启动，可追加 `-CheckRuntime`。

如果本机还没装 Docker Desktop：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key> -InstallDocker
```

如需启用 OpenClaw Shell：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key> -Profile shell
```

如需启用 bot-view：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key> -Profile bot-view
```

如果你这次只想先准备 `.env`、数据目录和 token，不立即启动容器：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key> -SkipStart
```

如果你想顺手生成一个本地任务示例文件：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key> -CreateSampleTask
```

也可以继续使用手工方式：

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

## 离线部署

如果目标环境不能联网构建镜像：

1. 在有网机器导出镜像：

```sh
docker save -o clawharness-images.tar \\
  clawharness/openclaw-gateway:local \\
  clawharness/harness-bridge:local \\
  clawharness/openclaw-bot-view:local
```

2. 将本部署目录和 `clawharness-images.tar` 一起拷到目标机器。
3. 先导入镜像：

```powershell
./load-images.ps1
```

或：

```sh
./load-images.sh
```

4. 再离线启动：

```powershell
./up-offline.ps1
```

或：

```sh
./up-offline.sh
```

如果还要启用 OpenClaw Shell：

```powershell
./up-offline.ps1 -Shell
```

或：

```sh
./up-offline.sh --shell
```

如果还要启动 bot-view sidecar：

```powershell
./up-offline.ps1 -BotView
```

或：

```sh
./up-offline.sh --bot-view
```

## 说明

- 这个部署包已经包含构建镜像所需的最小源码子集，直接复制整个目录即可部署。
- `bootstrap.ps1` 会自动补 `.env`、准备数据目录、生成 token，并在需要时尝试拉起 Docker Desktop。
- `check-install.ps1` 会检查当前模式所需命令、关键配置、路径，以及可选的运行中 health endpoint。
- `bootstrap.ps1` 现在是统一安装入口，支持：
  - `InstallMode=docker`
  - `InstallMode=native-core`
  - `InstallMode=native-openclaw`
- `bootstrap.ps1` 默认会保留已有 `.env` 中未显式覆盖的值，避免重复执行时把现有 provider 或 token 配置清空。
- `bootstrap.ps1 -SkipStart` 只做安装准备，不要求当前 shell 能找到 `docker`。
- 默认启动路径是 core-only / local-first，只启动 `clawharness-bridge`。
- 如果需要 OpenClaw UI、chat 宿主或 bot-view，请额外启用 `shell` profile；启用 bot-view 时同时启用 `shell`。
- `openclaw-gateway` 容器只在启用 `shell` profile 时需要。
- 当前导出包默认仍是“单机单实例” Docker 栈；如果本机已经存在同名 `clawharness-bridge` / `openclaw-gateway` / `openclaw-bot-view` 容器，先停掉旧栈。
- `native-core` 不依赖 Docker，也不依赖 OpenClaw；但要求宿主机已有 `python`、`git`、`codex`。
- `native-openclaw` 不依赖 Docker，但要求宿主机已有 `python`、`git`、`codex`、`node`、`npm`、`openclaw`。
- `config.toml` 和 `auth.json` 会在容器启动时根据 `.env` 自动生成，不需要手工维护。
- 如果你要完全离线使用，请不要执行默认的 `up.ps1` / `up.sh`，因为这两个脚本会带 `--build`。
- 如使用 Codex 转发 endpoint，请填写：
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `CODEX_MODEL`
- 默认 provider profile 已经是 `local-task`，只需要填写：
  - `LOCAL_REPO_PATH`
  - `LOCAL_TASKS_PATH`
  - `LOCAL_REVIEW_PATH`
- 如果你要切到 Azure DevOps，请把 `.env` 里的 `HARNESS_PROVIDER_PROFILE` 改为 `azure-devops`，并填写：
  - `ADO_BASE_URL`
  - `ADO_PROJECT`
  - `ADO_PAT`
- 如果你要切到 GitHub，请把 `.env` 里的 `HARNESS_PROVIDER_PROFILE` 改为 `github`，并填写：
  - 填写 `GITHUB_TOKEN`
  - 如启用 GitHub webhook，再填写 `GITHUB_WEBHOOK_SECRET`
- 默认推荐只维护：
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `CODEX_MODEL`
  - `CODEX_REVIEW_MODEL`
  - `CODEX_REASONING_EFFORT`
- 如果必须完全接管内部 Codex 配置，再使用 `CODEX_HOME_DIR` 这类高级覆盖方式。
- 如不使用自定义入口，可将 `OPENAI_BASE_URL` 留空。
"""


UP_PS1 = r"""param(
  [switch]$Shell,
  [switch]$BotView
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $scriptDir "compose.yml"
$envFile = Join-Path $scriptDir ".env"

if (-not (Test-Path $envFile)) {
  throw ".env not found. Copy .env.example to .env and fill the required values first."
}

$args = @("--env-file", $envFile, "-f", $composeFile)
if ($Shell -or $BotView) {
  $args += @("--profile", "shell")
}
if ($BotView) {
  $args += @("--profile", "bot-view")
}
$args += @("up", "--build", "-d")
docker compose @args
"""


UP_OFFLINE_PS1 = r"""param(
  [switch]$Shell,
  [switch]$BotView
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $scriptDir "compose.yml"
$envFile = Join-Path $scriptDir ".env"

if (-not (Test-Path $envFile)) {
  throw ".env not found. Copy .env.example to .env and fill the required values first."
}

$args = @("--env-file", $envFile, "-f", $composeFile)
if ($Shell -or $BotView) {
  $args += @("--profile", "shell")
}
if ($BotView) {
  $args += @("--profile", "bot-view")
}
$args += @("up", "-d")
docker compose @args
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


LOAD_IMAGES_PS1 = r"""param(
  [string]$Archive = "clawharness-images.tar"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$archivePath = Join-Path $scriptDir $Archive

if (-not (Test-Path $archivePath)) {
  throw "Image archive not found: $archivePath"
}

docker load -i $archivePath
"""


HEALTHCHECK_PS1 = r"""$bridgeHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/healthz
$bridgeReady = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/readyz
$gatewayHealthy = $true

if (Get-Command docker -ErrorAction SilentlyContinue) {
  & docker inspect openclaw-gateway *> $null
  if ($LASTEXITCODE -eq 0) {
    $gatewayHealthy = $false
    try {
      $gatewayHealth = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18789/healthz
      $gatewayHealthy = ($gatewayHealth.StatusCode -eq 200)
    } catch {
      $gatewayHealthStatus = & docker inspect openclaw-gateway --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' 2>$null
      if ($LASTEXITCODE -eq 0 -and $gatewayHealthStatus.Trim() -eq 'healthy') {
        $gatewayHealthy = $true
      }
    }
  }
}

if ($bridgeHealth.StatusCode -ne 200 -or $bridgeReady.StatusCode -ne 200 -or -not $gatewayHealthy) {
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

shell_profile=""
bot_view_profile=""
for arg in "$@"; do
  case "$arg" in
    --shell)
      shell_profile="--profile shell"
      ;;
    --bot-view)
      shell_profile="--profile shell"
      bot_view_profile="--profile bot-view"
      ;;
  esac
done

docker compose $shell_profile $bot_view_profile --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up --build -d
"""


UP_OFFLINE_SH = """#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"

if [ ! -f "$ENV_FILE" ]; then
  echo ".env not found. Copy .env.example to .env and fill the required values first." >&2
  exit 1
fi

shell_profile=""
bot_view_profile=""
for arg in "$@"; do
  case "$arg" in
    --shell)
      shell_profile="--profile shell"
      ;;
    --bot-view)
      shell_profile="--profile shell"
      bot_view_profile="--profile bot-view"
      ;;
  esac
done

docker compose $shell_profile $bot_view_profile --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
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


LOAD_IMAGES_SH = """#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ARCHIVE="${1:-clawharness-images.tar}"
ARCHIVE_PATH="$SCRIPT_DIR/$ARCHIVE"

if [ ! -f "$ARCHIVE_PATH" ]; then
  echo "Image archive not found: $ARCHIVE_PATH" >&2
  exit 1
fi

docker load -i "$ARCHIVE_PATH"
"""


HEALTHCHECK_SH = """#!/usr/bin/env sh
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
    shutil.copy2(REPO_ROOT / "deploy/windows/bootstrap.ps1", output_dir / "bootstrap.ps1")
    shutil.copy2(REPO_ROOT / "deploy/windows/check-install.ps1", output_dir / "check-install.ps1")
    write_text(output_dir / "README.md", BUNDLE_README)
    write_text(output_dir / "up.ps1", UP_PS1)
    write_text(output_dir / "up-offline.ps1", UP_OFFLINE_PS1)
    write_text(output_dir / "down.ps1", DOWN_PS1)
    write_text(output_dir / "load-images.ps1", LOAD_IMAGES_PS1)
    write_text(output_dir / "healthcheck.ps1", HEALTHCHECK_PS1)
    write_text(output_dir / "up.sh", UP_SH)
    write_text(output_dir / "up-offline.sh", UP_OFFLINE_SH)
    write_text(output_dir / "down.sh", DOWN_SH)
    write_text(output_dir / "load-images.sh", LOAD_IMAGES_SH)
    write_text(output_dir / "healthcheck.sh", HEALTHCHECK_SH)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    export_bundle(Path(args.output).resolve(), args.force)
    print(f"exported bundle to {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
