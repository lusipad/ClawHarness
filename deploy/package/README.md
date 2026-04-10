# ClawHarness 部署包导出

这个目录不是第二套长期维护的部署源码，而是“导出独立部署包”的入口。

## 设计目标

- 对外只暴露稳定的 `.env` 接口
- 不要求部署方手工维护 `config.toml` / `auth.json`
- 不要求部署方在宿主机单独安装 Codex CLI
- 避免把 `deploy/docker`、`openclaw-plugin`、`harness_runtime` 这些目录再手工复制维护一份
- 默认只暴露少量稳定的 Codex 字段；高级用户再走覆盖模式

## 用法

在仓库根目录执行：

```sh
python deploy/package/export_deploy_bundle.py --output dist/clawharness-deploy
```

导出后，`dist/clawharness-deploy` 会包含：

- `compose.yml`
- `.env.example`
- `bootstrap.ps1`
- `check-install.ps1`
- `up.ps1` / `up.sh`
- `up-offline.ps1` / `up-offline.sh`
- `down.ps1` / `down.sh`
- `load-images.ps1` / `load-images.sh`
- `healthcheck.ps1` / `healthcheck.sh`
- `README.md`
- `src/`：构建镜像所需的最小源码子集

Windows 推荐最短路径：

1. 复制整个导出目录
2. 运行 `bootstrap.ps1 -OpenAiApiKey <your-key>`

如果你更希望像安装向导一样一步一步选择，也可以直接运行快速向导：

- `./bootstrap.ps1 -Interactive`

在交互式 PowerShell 里直接运行 `./bootstrap.ps1`，现在也会自动进入快速向导。
向导在执行前会展示一次安装摘要，完成后会自动跑一次安装检查。

如果你确实需要原生安装或完整高级参数，再使用：

- `./bootstrap.ps1 -Interactive -Advanced`

如果你想明确选择安装路径，可改成：

- `./bootstrap.ps1 -InstallMode docker -OpenAiApiKey <your-key>`
- `./bootstrap.ps1 -InstallMode native-core -OpenAiApiKey <your-key>`
- `./bootstrap.ps1 -InstallMode native-openclaw -OpenAiApiKey <your-key>`

安装或配置完成后，可运行：

- `./check-install.ps1 -InstallMode docker`
- `./check-install.ps1 -InstallMode native-core`
- `./check-install.ps1 -InstallMode native-openclaw`

如需顺手检查本机服务是否真的已经启动，可追加 `-CheckRuntime`。

如果本机还没装 Docker Desktop，可改成：

- `./bootstrap.ps1 -OpenAiApiKey <your-key> -InstallDocker`

如果你只想先准备 `.env`、数据目录和 token，不立刻启动容器，可改成：

- `./bootstrap.ps1 -OpenAiApiKey <your-key> -SkipStart`

如果你想顺手生成一个本地任务示例文件，可改成：

- `./bootstrap.ps1 -OpenAiApiKey <your-key> -CreateSampleTask`

如果需要 OpenClaw Shell：

- `./bootstrap.ps1 -OpenAiApiKey <your-key> -Profile shell`

如果需要 bot-view：

- `./bootstrap.ps1 -OpenAiApiKey <your-key> -Profile bot-view`

如果你要手工控制 `.env`，也可以继续使用：

1. 复制整个导出目录
2. 将 `.env.example` 改成 `.env`
3. 填写 `.env`
4. 运行 `up.ps1` 或 `up.sh`

如果目标环境不能联网构建镜像，则改用：

1. 在有网机器准备镜像归档：

```sh
docker save -o clawharness-images.tar \
  clawharness/openclaw-gateway:local \
  clawharness/harness-bridge:local \
  clawharness/openclaw-bot-view:local
```

2. 将部署目录与 `clawharness-images.tar` 一起复制到目标机器
3. 先运行 `load-images.ps1` / `load-images.sh`
4. 再运行 `up-offline.ps1` / `up-offline.sh`

如需启用 OpenClaw Shell，可改为：

- `./up-offline.ps1 -Shell`
- `./up-offline.sh --shell`

如需同时启动 bot-view sidecar，可改为：

- `./up-offline.ps1 -BotView`
- `./up-offline.sh --bot-view`

## CI / 发布打包

如果你要给 GitHub Actions、手工交付或版本发布产出一组固定格式的安装包，可使用：

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --force
```

如果你已经在有网机器准备好了离线镜像归档，再追加：

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --image-archive clawharness-images.tar --force
```

这个命令会先导出独立部署包，再在 `dist/github-actions/artifacts/` 下生成：

- `clawharness-deploy-<label>.zip`
- `SHA256SUMS-<label>.txt`
- `artifact-manifest-<label>.json`
- `clawharness-images-<label>.tar`
  仅当传入 `--image-archive` 时生成

仓库里的 [`.github/workflows/package-installers.yml`](../../.github/workflows/package-installers.yml) 已经直接复用了这条打包逻辑：

- 推送到 `main` 或 `v*` tag 时，默认产出在线安装包
- 推送到 `v*` tag 时，还会自动构建离线镜像归档，并把这些文件发布到该 tag 对应的 GitHub Release
- 手工触发 `workflow_dispatch` 且 `include_offline_images=true` 时，额外附带离线镜像归档

## 说明

- 默认启动路径是 core-only / local-first；如需 OpenClaw UI、chat 宿主或 bot-view，再额外启用 `shell` profile。
- `bootstrap.ps1` 会自动创建 `.env`、准备数据目录、补随机 token，并在需要时尝试启动 Docker Desktop。
- `bootstrap.ps1` 的交互向导现在会先展示安装摘要，应用配置后自动执行一次安装检查。
- `check-install.ps1` 会检查当前模式所需命令、关键配置、路径，以及可选的运行中 health endpoint。
- `bootstrap.ps1` 现在是多合一入口：
  - `InstallMode=docker`：绿色优先，默认推荐
  - `InstallMode=native-core`：不依赖 Docker，也不依赖 OpenClaw
  - `InstallMode=native-openclaw`：不依赖 Docker，但会配置并启动本机 OpenClaw
- `bootstrap.ps1` 默认会保留已有 `.env` 中未显式覆盖的值，避免重复执行时把现有 provider 或 token 配置清空。
- `bootstrap.ps1 -SkipStart` 只做安装准备，不要求当前 shell 能找到 `docker`。
- 当前导出包默认仍是“单机单实例” Docker 栈；如果本机已经存在同名 `clawharness-bridge` / `openclaw-gateway` / `openclaw-bot-view` 容器，先停掉旧栈。
- `native-core` 需要宿主机已有 `python`、`git`、`codex`。
- `native-openclaw` 需要宿主机已有 `python`、`git`、`codex`、`node`、`npm`、`openclaw`。
- 导出包里的 `openclaw-gateway` 镜像只在启用 `shell` profile 时需要，并会安装固定版本的官方 `@openai/codex` CLI。
- `config.toml` 和 `auth.json` 会在容器启动时根据 `.env` 自动生成，不建议部署方手工改这两个文件。
- OpenClaw 侧的 `openclaw-plugin/skills/` 会在导出时从 `skills/core/` 自动投影，部署方不需要手工维护第二套 skill 真源。
- 默认的 `up.ps1` / `up.sh` 会带 `--build`；纯离线环境请改用 `up-offline.ps1` / `up-offline.sh`。
- 默认推荐只维护：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CODEX_MODEL`、`CODEX_REVIEW_MODEL`、`CODEX_REASONING_EFFORT`。
- 如果必须完全接管内部 Codex 配置，再使用 `CODEX_HOME_DIR` 这类高级覆盖方式。
- 如果后续要升级 Codex CLI 版本，优先改 `deploy/docker/openclaw-gateway.Dockerfile` 和 `deploy/docker/.env.example`，再重新导出部署包。
- 默认 provider profile 已经是 `local-task`，只需填写 `.env` 中的 `LOCAL_REPO_PATH`、`LOCAL_TASKS_PATH`、`LOCAL_REVIEW_PATH`。
- 如果要切到 Azure DevOps，把 `.env` 里的 `HARNESS_PROVIDER_PROFILE` 改为 `azure-devops`。
- 如果要切到 GitHub，把 `.env` 里的 `HARNESS_PROVIDER_PROFILE` 改为 `github`。
