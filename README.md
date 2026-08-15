# Agent Skills

这是三个学习／工作主仓库的 Skill 规范源。中央仓库已经完成五个学习核心及 `creator-workflow` 的评审、通用化升级与校验，并发布既有学习批次到公开远端 [`XiFenM/agent-skills`](https://github.com/XiFenM/agent-skills)。六个 first-party Skill 均采用中央通用核心、严格消费配置和受管上下文；`daily-work` 的 version 2 消费适配、旧副本退役与历史保护验证也已完成候选，等待独立提交与发布。

## 当前范围

- [`skills/`](skills/) 中保留 6 个 active first-party Skill：`guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning`、`creator-workflow`。
- `study-companion` 与 `learn-by-practice` 已从中央源码树删除并登记为 retired name，统一替代项为 `guide-learning`；兼容源码仍可从 `learning-core-v1` 标签恢复，但不再提供可发现入口。
- 5 个 external Skill 从 3 个官方 Git 子模块读取；不在本仓库复制第三方源码。
- PlanA 的 PyTorch、SGLang、vLLM 源码子模块自带 Skill 不迁移、不登记。
- Remotion 只暴露官方聚合入口 `remotion-best-practices`，不再保留功能重复的独立入口。

完整来源、分类、生命周期和消费仓库记录在 [`catalog.json`](catalog.json)。schema v2 还记录替代关系与选择组：materializer 会拒绝 rollback-only 或已退役名称，并提示最终 active 替代项；`primary-learning` 规定一个消费配置跨所有 host 最多选择一个不同的主学习 Skill，同一个 `guide-learning` 同时分发给 Codex 与 Claude 仍然合法。

## 学习类 Skill 用户说明

面向学习者的整体分工和组合流程见[学习类 Skill 组合使用指南](docs/learning-skills-user-guide.md)。也可以直接阅读各 Skill 的独立说明：

- [`guide-learning`](docs/user-guides/guide-learning.md)
- [`english-coach`](docs/user-guides/english-coach.md)
- [`study-log`](docs/user-guides/study-log.md)
- [`memo-cards`](docs/user-guides/memo-cards.md)
- [`resource-planning`](docs/user-guides/resource-planning.md)

迁移历史、中央升级结果及当前遗留问题记录在 [`docs/migration-baseline.md`](docs/migration-baseline.md)。学习类 Skill 的 D1–D42 与创作工作流的 D43–D44 决策、实现设计和迁移边界记录在 [`docs/learning-skills-review.md`](docs/learning-skills-review.md)。D41 及后续精确文章交接修复已发布；PlanA 的 version 2 配置、历史产物适配与资源 bootstrap 也已发布。

## 目录

```text
agent-skills/
├── skills/                    # active first-party Skill 的规范源码
├── vendor/                    # 第三方官方仓库（Git submodule）
├── tools/                     # 清单校验与消费仓库同步工具
├── tests/                     # 仓库级测试
├── catalog.json               # 机器可读的分类与来源清单
└── .agent-skills.example.json # 消费仓库声明示例
```

## 消费方式

消费仓库从公开中央远端把本仓库加入为 `.agent-skills` 子模块，并提交自己的 `.agent-skills.json`。M0–M5 已全部完成：`learning-core-v1` 对应的 `b2afd92854d57a375fdf990028c31561118cf8ec` 继续固定兼容版本。programming-lab 向 Codex 分发 `guide-learning`、`study-log`、`english-coach` 与 `memo-cards`；PlanA 则向 Codex 与 Claude 分发 `guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning` 与 `playwright-cli`。

2026-08-12 的工作批次先分别形成 PlanA `1a2a162` 与 programming-lab `d4ddc14`，完成 version 2 基础消费配置；随后中央 `c3ae66a` 加入文章能力，PlanA 继续完成历史状态、日志、卡片与资源治理接管，programming-lab 则在保持 legacy 冻结的前提下增加英语反馈与受管制卡入口。消费配置只提供 locator 和机械边界，不授予读取 raw、写入、发布、提交或推送。

不需要消费环境配置的仓库可以继续使用 version 1。需要为自创 Skill 提供仓库事实、素材 collection、输出目标或 adapter 时，使用 version 2，并让索引只引用严格 JSON 配置：

```json
{
  "version": 2,
  "source": ".agent-skills",
  "skills": {
    "creator-workflow": ["codex"],
    "english-coach": ["codex", "claude"],
    "guide-learning": ["codex", "claude"],
    "memo-cards": ["codex", "claude"],
    "resource-planning": ["codex", "claude"],
    "study-log": ["codex", "claude"]
  },
  "config": {
    "repository": ".agent-skills-config/repository.json",
    "skills": {
      "creator-workflow": ".agent-skills-config/creator-workflow.json",
      "english-coach": ".agent-skills-config/english-coach.json",
      "guide-learning": ".agent-skills-config/guide-learning.json",
      "memo-cards": ".agent-skills-config/memo-cards.json",
      "resource-planning": ".agent-skills-config/resource-planning.json",
      "study-log": ".agent-skills-config/study-log.json"
    }
  }
}
```

公共仓库配置使用 `agent-skills.repository/v1`，只声明 `repository_id`、可选语言／时区和带稳定 ID 的仓库事实；各 Skill 配置使用 `agent-skills.<skill>/v1`。这里的 version 2 指消费索引及其受管配置能力，不会改写既有学习记录、CLI envelope、原始对话存档或创作项目业务 manifest 的格式版本。配置只能声明环境事实、能力路由和合法候选位置，不能预授权保存、覆盖、制卡、付费、发布、提交或推送。`creator-workflow` 只允许严格的 profile、package-script／selected-Skill 路由、受管根和保护根；密钥、远端任务、当前状态、任意命令与授权文本不得进入公共配置。`guide-learning` 的映射不保存 Program、Lesson、Checkpoint 或 mastery 状态值；D41 的可选 `article_profile` 也只约束语言、语气、章节、领域视角与候选目标，不能代替起草范围确认或精确写入授权，文章也不拥有学习状态和日志。`study-log` 的公共配置只列结构化记录目标，原始对话的私有 archive root、会话来源和边界永不进入公共配置或受管上下文。version 2 配置及其引用必须是 Git 已跟踪的 UTF-8 普通文件；collection 只展开 Git 已跟踪的 UTF-8 成员，未跟踪文件不会进入运行时白名单。完整索引形状见 [`.agent-skills.example.json`](.agent-skills.example.json)，各 Skill 的字段由其登记的严格 validator 校验。

### 新 clone：恢复消费仓库固定的版本

新 clone 或换一台机器后，先恢复消费仓库已经记录的中央版本，再生成宿主实际会发现的目录：

```powershell
git submodule sync --recursive -- .agent-skills
git submodule update --init --recursive -- .agent-skills
python .agent-skills/tools/materialize_skills.py --repo .
```

这里的路径限制很重要：命令只初始化 `.agent-skills` 及其内部依赖，不会连带初始化消费仓库中的其他大型子模块。这组命令只恢复父仓库固定的版本，不会主动升级到中央仓库的最新提交。

### 中央发布后：一键升级消费仓库

中央 Skill 发布新版本后，在消费仓库根目录先预览，再执行升级：

```powershell
python .agent-skills/tools/update_consumer.py --dry-run
python .agent-skills/tools/update_consumer.py
```

`--dry-run` 只获取远端元数据并显示当前与目标提交，不检出或生成文件。正式执行时，脚本会获取默认远端的 `main`、以 detached HEAD 精确检出目标提交、只递归更新 `.agent-skills` 内部的第三方子模块，并依次预览、生成和检查本地 Skill。若检出后的步骤失败，它会尝试恢复原提交及原生成结果。它允许消费仓库保留其他未提交修改，但要求 `.agent-skills` 自身干净。

需要指定已发布的分支、标签或完整提交 ID 时使用 `--ref`；降级或切换到非快进历史还必须明确允许：

```powershell
python .agent-skills/tools/update_consumer.py --ref release-v2
python .agent-skills/tools/update_consumer.py --ref <full-commit-id>
python .agent-skills/tools/update_consumer.py --ref <older-ref> --allow-non-fast-forward
```

脚本不会执行 `git add`、commit 或 push。成功后检查差异，并只提交新的子模块指针：

```powershell
git diff --submodule=short -- .agent-skills
git add -- .agent-skills
git commit --only -m "chore: update agent skills" -- .agent-skills
git push
```

如果消费仓库当前固定的旧版本还没有这个脚本，而本工作区有并列的中央仓库 clone，可以先从中央 clone 运行一次：

```powershell
python ../agent-skills/tools/update_consumer.py
```

脚本只依赖 Python 标准库；没有全局 Python 时，可让 uv 提供 Python：

```powershell
uv run --no-project python .agent-skills/tools/update_consumer.py
```

映射固定为：

- `codex` → `.agents/skills/<name>`
- `claude` → `.claude/skills/<name>`

消费仓库应忽略生成物：

```gitignore
/.agents/skills/
/.claude/skills/
/.agent-skills.state.json
/.agent-skills.lock
```

中央子模块必须处于已有提交且工作树干净的状态；materialize 工具同时记录中央提交、每个 Skill 的源码摘要、消费配置摘要和生成上下文摘要。version 2 会在每个已配置的生成副本中写入逐字节确定的 `.agent-skills-context.json`；配置变化后必须重新 materialize。底层 materialize 工具本身不会拉取远端、更新子模块、提交、跟随链接，或覆盖未经 state 与目录 marker 共同证明属于它的同名目录；上述更新脚本负责在其外层完成受限的 Git 更新。

底层 materialize 工具的常用操作：

- `--dry-run`：显示会复制/清理的受管目录，不留下持久文件。
- `--check`：只检查提交版本、内容漂移、孤儿目录和 state；一致时退出码为 0，漂移为 1，配置或安全错误为 2。
- `--config <path>`：指定相对于 `--repo` 的消费声明。
- 把 `skills` 设为 `{}`：安全卸载 state 中最后一批受管 Skill。

生成目录内的手工修改会在下一次同步时被覆盖，不能作为工作副本。若 state 丢失而仍存在带 marker 的生成目录，工具会拒绝猜测所有权；应先恢复 `.agent-skills.state.json`，或人工确认后移除对应生成目录。崩溃遗留 `.agent-skills.lock` 时，也应先确认没有同步进程再删除锁。

生成副本不会自动随 clone 或云端会话出现；每次新 clone、中央子模块更新后都必须执行 materialize。云环境若不能在 Skill 扫描前运行该步骤，需要后续另行选择提交生成副本、setup hook 或插件方案。

## 本仓库校验

```powershell
uv run --cache-dir .uv-cache --no-project python tools/validate_catalog.py
uv run --cache-dir .uv-cache --no-project --with pytest python -m pytest tests skills -v
```

第二条命令同时覆盖仓库级测试以及全部 first-party Skill 的单元与安全测试。

第三方版本由 `.gitmodules` 与 Git submodule 指针共同固定。更新第三方来源时，应先审阅上游变更，再更新对应指针和运行校验。
