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
- `up.ps1` / `up.sh`
- `down.ps1` / `down.sh`
- `healthcheck.ps1` / `healthcheck.sh`
- `README.md`
- `src/`：构建镜像所需的最小源码子集

部署方只需要：

1. 复制整个导出目录
2. 将 `.env.example` 改成 `.env`
3. 填写 `.env`
4. 运行 `up.ps1` 或 `up.sh`

## 说明

- 导出包里的 `openclaw-gateway` 镜像默认会安装固定版本的官方 `@openai/codex` CLI。
- `config.toml` 和 `auth.json` 会在容器启动时根据 `.env` 自动生成，不建议部署方手工改这两个文件。
- 默认推荐只维护：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CODEX_MODEL`、`CODEX_REVIEW_MODEL`、`CODEX_REASONING_EFFORT`。
- 如果必须完全接管内部 Codex 配置，再使用 `CODEX_HOME_DIR` 这类高级覆盖方式。
- 如果后续要升级 Codex CLI 版本，优先改 `deploy/docker/openclaw-gateway.Dockerfile` 和 `deploy/docker/.env.example`，再重新导出部署包。
