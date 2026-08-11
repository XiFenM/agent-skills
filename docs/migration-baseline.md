# Skill 迁移与升级基线

本文件保留 2026-08-10 第一阶段的迁移事实，并记录 2026-08-11 已获授权的中央学习核心升级结果。历史记录不表示对应 Skill 仍处于当时的生命周期状态；消费仓库迁移和远端操作不在中央实现授权内。

## 2026-08-10：第一阶段迁移事实

### 已纳入：自创 Skill

| Skill | 原仓库 | 中央路径 | 迁移状态 |
|---|---|---|---|
| `creator-workflow` | `daily-work` | `skills/creator-workflow` | 原样复制；后续改造成通用工作流 |
| `english-coach` | `PlanA` | `skills/english-coach` | 原样复制；保留消费仓库相对路径 |
| `memo-cards` | `PlanA` | `skills/memo-cards` | 原样复制；保留已知断链与消费仓库相对路径 |
| `resource-planning` | `PlanA` | `skills/resource-planning` | 原样复制；保留消费仓库相对路径 |
| `study-companion` | `PlanA` | `skills/study-companion` | 原样复制；保留消费仓库相对路径 |
| `study-log` | `PlanA` | `skills/study-log` | 原样复制；保留消费仓库相对路径及脚本的 CWD 默认行为 |
| `learn-by-practice` | `programming-lab` | `skills/learn-by-practice` | Skill 内 10 个文件原样复制；另迁入仓库外 exporter 测试并只调整导入位置 |

PlanA 的 `.claude/skills` 与 `.agents/skills` 原本是内容完全相同的双份副本，中央仓库只以 `.claude/skills` 为迁移来源，不保留重复副本。

逐项 SHA-256 复核确认上述自创 Skill 与来源文件一致；原仓库提交号当时保存在 `catalog.json` 的 `origin.commit`，并已在 2026-08-11 的 schema v2 升级中转入 `lineage[]`。`learn-by-practice` 额外迁入的 exporter 测试只为新目录调整导入位置，因此单独标记，不冒充原样文件。

### 已纳入：第三方官方来源

| 对外 Skill 名 | 官方仓库 | 仓库内选择路径 | 处理 |
|---|---|---|---|
| `playwright-cli` | `microsoft/playwright-cli` | `skills/playwright-cli` | 官方子模块直接引用 |
| `remotion-best-practices` | `remotion-dev/skills` | `skills/remotion-best-practices` | 官方子模块直接引用；唯一 Remotion 入口 |
| `zenmux-context` | `ZenMux/skills` | `skills/zenmux-context` | 官方子模块直接引用 |
| `zenmux-setup` | `ZenMux/skills` | `skills/zenmux-setup` | 官方子模块直接引用 |
| `zenmux-usage` | `ZenMux/skills` | `skills/zenmux-usage` | 官方子模块直接引用 |

Playwright 子模块当前对应官方 `@playwright/cli` 0.1.18，取代 `daily-work` 中由 0.1.17 生成的本地副本；这是采用最新官方规范源后的上游刷新，不是逐字复制。PlanA 的本地派生版同样不作为规范源保留。

Remotion 官方聚合目录包含旧独立能力，且其中 Markdown 文件链接已验证为自包含。因此以下旧入口不再登记：`mediabunny`、`remotion-captions`、`remotion-create`、`remotion-docs`、`remotion-interactivity`、`remotion-maps`、`remotion-markup`、`remotion-multimedia`、`remotion-render`、`remotion-saas`、`remotion-upgrade`。后续迁移 `daily-work` 调用时，旧名字统一路由至 `remotion-best-practices`。

ZenMux 官方仓库中当前还有其他 Skill，但它们不是三个主仓库已有能力，因此本轮不登记。

### 明确排除

- PlanA 的 PyTorch、SGLang、vLLM 源码子模块自带 Skill：不迁移、不登记、不保存清单。
- PlanA 的本地 `playwright-cli` 派生副本：由 Microsoft 官方仓库取代。
- `daily-work` 中 Remotion 与 ZenMux 的本地第三方副本：由官方子模块取代。
- `programming-lab` 的学习记录、Triton 领域资料、编辑器配置、仓库级 CI 与兼容软链接：不属于 Skill 本体。

## 2026-08-11：中央学习核心升级结果

- 中央 [`skills/`](../skills/) 现保留 8 个 first-party 目录。`guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning`、`creator-workflow` 为 active；`study-companion` 与 `learn-by-practice` 为 rollback-only，二者的 active 替代项均为 `guide-learning`。
- `guide-learning` 已吸收 `study-companion` 与 `learn-by-practice` 的主学习流程，采用精简入口与按需 references，并实现已确认的教学微循环、正式练习、评审、掌握验证和最小恢复模型。
- 学习对话发现、预览、边界选择、提取与 raw 存档已统一归属 `study-log`。统一入口为 `scripts/study_log.py`；项目根与 provider 数据在运行时发现和规范化，不再依赖中央源码位置示例或调用进程的旧 CWD 默认值。
- `learn-by-practice` 中重复的对话 exporter、相关 reference 与重复测试已经移除；固定学习档案初始化器及其测试仅作为 rollback-only 回滚源码继续保留。
- `catalog.json` 已升级至 schema v2，记录 first-party lineage、生命周期、替代项和 `primary-learning` 选择组。新配置不能选择 rollback-only 入口；一个配置跨 Codex 与 Claude 最多选择一个不同的主学习 Skill。
- 5 个 external Skill 仍由 3 个官方 Git 子模块固定，不复制第三方源码。
- C0–C3 只完成中央仓库实现与验证。2026-08-11 经用户另行授权完成 M0：公开远端 [`XiFenM/agent-skills`](https://github.com/XiFenM/agent-skills) 已配置并发布，`learning-core-pre-implementation` 固定实现前基线，`learning-core-v1` 固定通过验证的兼容版本。后续 M1–M5 尚未开始，仍需用户另行授权。

## 当前已知但暂不修复

1. `memo-cards/references/tech-qa-template.md` 使用 `../../../../英语/cards/_templates.md`；从当前中央源码位置解析为 `F:\Learning\英语\cards\_templates.md`，该文件不存在。它是否在发现副本中恢复取决于后续挂载深度，因此本轮只记录，不改链接。
2. 除已完成运行时路径适配的 `study-log` 外，来自 PlanA 的独立或回滚 Skill 仍广泛依赖消费仓库中的 `英语/`、`计划/`、`README.md`、`{module}/` 等相对路径；这些约定需要在 M4 按实际挂载深度修复。
3. `creator-workflow` 仍绑定当前创作目录约定；后续共同抽象为通用工作流。
4. `creator-workflow` 仍写有“`remotion-best-practices` 加窄域 Remotion Skill”的旧路由；去重后只有聚合入口，需在后续通用化时一起修正。

这些问题不阻塞当前学习核心；它们将在相应 Skill 的后续独立评审或消费仓库迁移中处理。
