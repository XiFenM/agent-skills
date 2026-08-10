# Skill 迁移基线（2026-08-10）

本文件只记录第一阶段的迁移事实和待讨论项，不构成质量评价，也不授权内容升级。

## 已纳入：自创 Skill

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

逐项 SHA-256 复核确认上述自创 Skill 与来源文件一致；原仓库提交号保存在 `catalog.json` 的 `origin.commit`。`learn-by-practice` 额外迁入的 exporter 测试只为新目录调整导入位置，因此单独标记，不冒充原样文件。

## 已纳入：第三方官方来源

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

## 明确排除

- PlanA 的 PyTorch、SGLang、vLLM 源码子模块自带 Skill：不迁移、不登记、不保存清单。
- PlanA 的本地 `playwright-cli` 派生副本：由 Microsoft 官方仓库取代。
- `daily-work` 中 Remotion 与 ZenMux 的本地第三方副本：由官方子模块取代。
- `programming-lab` 的学习记录、Triton 领域资料、编辑器配置、仓库级 CI 与兼容软链接：不属于 Skill 本体。

## 已知但暂不修复

1. `memo-cards/references/tech-qa-template.md` 使用 `../../../../英语/cards/_templates.md`；从当前中央源码位置解析为 `F:\Learning\英语\cards\_templates.md`，该文件不存在。它是否在发现副本中恢复取决于后续挂载深度，因此本轮只记录，不改链接。
2. PlanA 的五个 Skill 广泛依赖消费仓库中的 `英语/`、`计划/`、`README.md`、`{module}/` 等路径；这些约定只有在运行时工作目录为 PlanA 根目录时才成立。
3. `study-log` 仍包含 `.claude/skills/study-log` 与 `.agents/skills/study-log` 的旧位置示例；在中央源码位置并不成立，后续需结合最终发现视图一起修复。
4. `study-log` 的脚本默认以当前工作目录判断项目，在中央仓库单独执行会指向错误上下文。
5. 学习类 Skill 当前只标记为“职责边界待评审”。它们可能是协作管线，也可能存在重复；尚未作出合并结论。
6. `creator-workflow` 仍绑定当前创作目录约定；后续共同抽象为通用工作流。
7. `creator-workflow` 仍写有“`remotion-best-practices` 加窄域 Remotion Skill”的旧路由；去重后只有聚合入口，需在后续通用化时一起修正。

这些问题会进入质量评估与合并升级阶段；本轮不修改相关 Skill 内容。
