# ClawHarness 插件化与单一 Skill 真源改造验收规范

日期：2026-04-09
状态：待执行
配套文档：
- `.omx/plans/prd-clawharness-plugin-architecture-2026-04-09.md`

## 验收目标

证明本轮改造完成后，系统能够：

1. 以单一 canonical source 管理所有 skill。
2. 让 OpenClaw 插件层只承担 shell / UI / capability 宿主职责。
3. 让 workflow 只引用 `skill_id` 和 `capability_id`。
4. 在保持现有闭环能力的同时完成架构收敛。
5. 以分步提交方式逐步迁移，不出现长时间半完成状态。

## 验收原则

- 每一步都必须可单独验证。
- 每一步都必须有明确的提交边界。
- 每一步完成后，主分支必须保持“可测试、可恢复、可继续”。
- 没有证据的“已经收敛”不算通过。

## 阶段门槛

### Gate-1：规划基线

必须通过：

- TS-01
- TS-02

### Gate-2：canonical skill source

必须通过：

- Gate-1 全部
- TS-03
- TS-04

### Gate-3：OpenClaw 投影

必须通过：

- Gate-2 全部
- TS-05
- TS-06

### Gate-4：capability plugin registry

必须通过：

- Gate-3 全部
- TS-07
- TS-08

### Gate-5：workflow 引用化与收口

必须通过：

- Gate-4 全部
- TS-09
- TS-10
- TS-11

## 测试项

### TS-01：计划文档完整性

给定：
- 新的 PRD 与测试规范文档

当：
- 审查计划内容

则：
- 能看到明确的阶段拆分
- 每一步都定义了目标、范围、闭环标准和提交边界
- 每一步都能独立完成而不依赖“最后一起收尾”

证据：
- `.omx/plans/prd-clawharness-plugin-architecture-2026-04-09.md`
- `.omx/plans/test-spec-clawharness-plugin-architecture-2026-04-09.md`

### TS-02：提交策略可执行

给定：
- 仓库可能存在无关脏改动

当：
- 审查提交策略

则：
- 计划明确要求 path-limited commit
- 不会把无关改动混入当前步骤提交

证据：
- 计划文档中的提交策略章节
- `git status --short` 审查记录

### TS-03：canonical skill source 可加载

给定：
- 新的 canonical skill source 目录

当：
- runtime 加载 skill registry

则：
- 能优先读取 canonical source
- 读取失败时有明确兼容策略
- 返回的 `skill_id`、`version`、`source` 信息完整

证据：
- `harness_runtime/skill_registry.py`
- 对应单元测试

### TS-04：旧路径兼容

给定：
- 仍保留旧的 `openclaw-plugin/skills/registry.json`

当：
- canonical source 未启用或缺失

则：
- runtime 仍可回退到旧路径
- 不破坏现有测试和离线链路

证据：
- 兼容逻辑测试
- 回退加载测试

### TS-05：OpenClaw skill 投影可生成

给定：
- canonical skill source 已存在

当：
- 运行 skill 投影脚本

则：
- 能生成 OpenClaw 所需的注册表与 skill 目录
- 生成结果不需要手工二次编辑

证据：
- 生成脚本
- 生成结果目录
- 一致性测试

### TS-06：投影结果与运行时一致

给定：
- 生成后的 OpenClaw skill 产物

当：
- runtime 与 OpenClaw 同时消费对应 skill 元数据

则：
- `skill_id`、版本、来源保持一致
- 不出现“双份真源”不一致问题

证据：
- 生成一致性测试
- registry 对照检查

### TS-07：capability plugin manifest 生效

给定：
- 新的 capability manifest schema 与 registry

当：
- 注册一个 provider 或 chat capability

则：
- 系统可以通过注册表发现并加载该能力
- 宿主核心代码不需要新增散落分支

证据：
- manifest schema
- registry 测试
- 至少一个 capability 接入样例

### TS-08：现有内建能力兼容

给定：
- Azure DevOps、GitHub、local-task、Rocket.Chat、bot-view 中至少一类能力

当：
- 接入新的 capability registry

则：
- 现有配置仍可工作
- 旧路径通过兼容适配层继续可用

证据：
- 适配层测试
- 集成测试

### TS-09：workflow 只引用 skill_id / capability_id

给定：
- 改造后的 workflow 定义

当：
- 审查 `task-run`、`pr-feedback`、`ci-recovery` workflow

则：
- workflow 不再承担 skill 正文真源角色
- 仅包含编排引用与阶段信息

证据：
- workflow 文件审查
- workflow 解析测试

### TS-10：现有主链路不回归

给定：
- 改造后的 skill / plugin / workflow 边界

当：
- 运行现有 Python 测试集

则：
- 既有任务主链路、PR feedback、CI recovery、chat 命令、bot-view、provider 测试继续通过

证据：
- `python -m unittest discover -s tests -v`

### TS-11：至少一条真实链路复验通过

给定：
- 改造后的运行时

当：
- 运行一次 `local-task` 离线闭环

则：
- 能完成 task -> workspace -> change -> review artifact 的闭环
- 证据能更新到新的记录文档中

证据：
- `python -m harness_runtime.main --provider-type local-task --task-id <sample>`
- 新的 evidence 文档或工件输出

## 验证命令基线

按步骤不同，最少执行以下命令集合：

### 文档与静态检查

```powershell
git diff -- .omx/plans
```

### Python 回归

```powershell
python -m unittest discover -s tests -v
```

### 语法编译

```powershell
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

### 离线闭环

```powershell
python -m harness_runtime.main --provider-type local-task --task-id <sample>
```

## 每步提交前检查单

- 该步骤的目标是否已完全达成
- 是否只改了该步骤需要的文件
- 是否存在半迁移状态
- 验证命令是否已执行并阅读结果
- 提交信息是否符合 Lore Commit Protocol

## 失败判定

出现以下任一情况，该步骤不得提交为完成：

- 仍需要依赖“下一步再修”才能跑通当前链路
- skill 真源仍然需要双向手工维护
- workflow 中仍保留第二份正文真源
- registry 改造导致旧链路失效且没有兼容层
- 测试失败但没有明确标注阻塞原因

## 最终通过判定

当且仅当以下条件同时满足时，本轮改造验收通过：

1. canonical skill source 已成为唯一手工维护入口。
2. OpenClaw skill 目录已成为投影产物或显式兼容层。
3. workflow 已只保留引用，不再承担正文真源。
4. capability 通过统一 manifest/registry 发现。
5. 现有闭环测试与至少一条真实离线链路复验通过。
