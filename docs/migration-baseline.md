# Skill 迁移与升级基线

本文件保留 2026-08-10 第一阶段的迁移事实，并记录 2026-08-11 已获授权的中央学习核心及后续三项学习辅助 Skill 升级结果。历史记录不表示对应 Skill 仍处于当时的生命周期状态；每一轮消费适配、提交和远端操作仍按各自授权边界执行。

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

- 中央 [`skills/`](../skills/) 现保留 6 个 active first-party 目录：`guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning`、`creator-workflow`。`study-companion` 与 `learn-by-practice` 已从源码树删除并进入 `retired_names`，二者的 active 替代项均为 `guide-learning`。
- `guide-learning` 已吸收 `study-companion` 与 `learn-by-practice` 的主学习流程，采用精简入口与按需 references，并实现已确认的教学微循环、正式练习、评审、掌握验证和最小恢复模型。
- 学习对话发现、预览、边界选择、提取与 raw 存档已统一归属 `study-log`。统一入口为 `scripts/study_log.py`；项目根与 provider 数据在运行时发现和规范化，不再依赖中央源码位置示例或调用进程的旧 CWD 默认值。
- `learn-by-practice` 中重复的对话 exporter、相关 reference 与重复测试已在 C2 移除；M5 又删除其固定学习档案初始化器及其余 rollback-only 源码。兼容版本继续由 `learning-core-v1` 标签固定。
- `catalog.json` 使用 schema v2 记录 first-party lineage、生命周期、退役名称和 `primary-learning` 选择组。旧名称会得到 `guide-learning` 替代提示而不是 unknown；一个配置跨 Codex 与 Claude 最多选择一个不同的主学习 Skill。
- 5 个 external Skill 仍由 3 个官方 Git 子模块固定，不复制第三方源码。
- C0–C3 只完成中央仓库实现与验证。2026-08-11 经用户另行授权完成 M0：公开远端 [`XiFenM/agent-skills`](https://github.com/XiFenM/agent-skills) 已配置并发布，`learning-core-pre-implementation` 固定实现前基线，`learning-core-v1` 固定通过验证的兼容版本。
- 2026-08-11 完成 M1 迁移输入冻结：从公开远端全新递归克隆 `learning-core-v1`，确认三个官方子模块均位于登记 gitlink，中央验证保持 `82 passed, 2 skipped, 40 subtests passed`，三个相关 Skill 与 catalog 校验通过；独立合成消费仓库中的四个发现副本可 materialize 并通过 `--check`，rollback-only 名称会拒绝并提示 `guide-learning`。M2–M4 唯一输入固定为 `b2afd92854d57a375fdf990028c31561118cf8ec`；验证未读取或修改真实消费仓库。
- 2026-08-11 完成 M2 空管线接入并发布：programming-lab `fec3e862dd41de3c1ec95d6d12fe5770581f6e1c` 与 PlanA `1245d0856bb480e929f00561c18a1c7c2cac2633` 均以 `.agent-skills` gitlink 固定 M1 输入，`.gitmodules` 使用 `../agent-skills.git`，`.agent-skills.json` 保持 `"skills": {}`，并忽略生成发现目录、state 临时文件和 lock。两仓库 dry-run 无复制／删除计划，实际空同步的 `managed` 为零且 `--check` 通过；原 Skill 源码、发现入口、测试与上游源码子模块均未改变。
- 2026-08-11 完成 M3 programming-lab 金丝雀切换并发布：原子提交 `979b777a55579dcbb7771c474d2cce776796c781` 保持 `.agent-skills` 固定在 `b2afd92854d57a375fdf990028c31561118cf8ec`，只向 Codex 启用 `guide-learning` 与 `study-log`；删除本地 `learn-by-practice` 源码、旧发现／exporter 链接及重复 exporter 测试，并更新活跃配置与 Triton 学习文档。提交后 materialize 仅生成两个受管 Codex 入口且 `--check` 通过；默认 CPU 测试、中央 `study-log` 脚本测试、两个生成 Skill 结构校验、Ruff、BasedPyright 及全新会话前向测试通过。已完成 Lesson 01／02 与 legacy dialogues 未改写。
- 2026-08-11 完成 M4 PlanA 切换并发布：原子提交 `f7e267d22cc626e4c79aeeac918ebb217d34be8e` 继续把 `.agent-skills` 固定在 `b2afd92854d57a375fdf990028c31561118cf8ec`，移除两棵受 Git 跟踪的旧发现副本，并把 `guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning` 与 `playwright-cli` 同时分发给 Codex 和 Claude。PlanA 的流程、唯一稀疏 Checkpoint、学习偏好及入口文档已改为中央行为规范的仓库适配；提交后 materialize 生成 12 个带 marker 的受管入口且 `--check` 通过，12 个生成 Skill 的结构校验及 `study-log` 的 `41 passed, 1 skipped` 通过（跳过项是 Windows 无目录符号链接权限的环境用例）。全新会话从 Pass C-1 唯一下一动作零写恢复且无 drift；Program、Lesson、证据、进度文件及无关未跟踪用户工作均未触碰。
- 2026-08-11 完成 M5 并发布：中央提交 `4ce419ced337b15937af03a93f26468c0ea2ddeb` 删除两个 rollback-only 旧目录，把 `learn-by-practice` 与 `study-companion` 移入 `retired_names` 并继续指向 `guide-learning`，同时只把 `english-coach` 中唯一的旧入口名称机械替换为 `guide-learning`；catalog 校验为 11 Skills（6 first-party、5 external），完整测试为 `78 passed, 2 skipped, 34 subtests passed`，6 个 active first-party Skill 结构校验通过。programming-lab 提交 `a9dac09c744d94f11d20f8a6ee85404899a14099` 与 PlanA 提交 `272e68cfc82cd91b26af12e46bb87609ea7bfb92` 均把 `.agent-skills` 固定到该中央提交并重新 materialize：前者保持 2 个 Codex 入口，后者保持 12 个双 host 入口，state、marker 与 `--check` 全部一致。两仓库的 `study-log` 均为 `41 passed, 1 skipped`，programming-lab 默认 CPU 测试为 `10 passed`；全新只读恢复分别停在 Lesson 03 授权边界和 Pass C-1 唯一下一动作，均零写且不依赖旧入口。三个仓库均已推送并与远端 `main` 同步；历史学习证据、PlanA 无关未跟踪用户工作和 `learning-core-v1` 标签未改变。

## 2026-08-11：三项学习辅助 Skill 中央升级

- `english-coach` 已落实 D24–D27：只在用户实际使用英语或明确要求时激活，采用低打扰随行反馈、支架优先回顾、混合纠错、技术语义分流与默认零写入；中央入口不再包含 PlanA 路径或旧 prompt 分支。
- `memo-cards` 已落实 D28–D34：中央核心只服务受管 Markji 3.8+ 暂存产物，采用稳定逻辑身份、严格素材门槛、单一模板 registry、派生 inventory、风险分级确认、预览 digest、来源／目标 CAS 与原子发布；原 PlanA 相对链接模板已退出中央源码。
- `resource-planning` 已落实 D35–D39：`research-brief`、`refresh`、`review` 三模式隔离，资源身份／claim 证据／coverage cursor／候选事件归入单一 registry，并由 `verify`、`prepare`、`publish`、`recover` 管理可恢复的多文件事务。
- 三项 Skill 均登记严格的 `validate_materialized_context`。materializer 继续兼容 version 1，并新增 version 2 配置索引、公共 repository facts、逐 Skill 配置、Git-tracked UTF-8 collection 展开和逐副本 `.agent-skills-context.json`；中央源码、消费配置和生成上下文均进入摘要与漂移检查。
- 最终中央验证为 `197 passed, 4 skipped, 46 subtests passed`，catalog 与三项 Skill 结构校验通过；隔离的英语制卡、技术依赖卡、无配置 research 和受管 refresh／review 前向场景均通过。跳过项只涉及当前 Windows 环境缺少链接／junction 权限的防护用例。
- `creator-workflow` 的通用化质量评审、升级方案和 `daily-work` 适配迁移已明确延期，不与本轮学习类实施混合。
- 本节只记录中央实现边界。PlanA 的 version 2 配置、旧英语 prompt／旧资源 SOP 退役、历史卡片渐进接管、资源 registry bootstrap 及首次真实 refresh／review 均属于后续消费适配；本轮不批量改写历史学习产物或用户未跟踪工作。

## 2026-08-12：五个学习类 Skill 统一 version 2 配置层

- `guide-learning` 与 `study-log` 已加入和另外三项学习类 Skill 相同的 version 2 受管配置管线；version 1
  消费者以及 version 2 中“已选择但未配置”的 Skill 继续保持无 context 的兼容行为。
- 这里的 version 2 只指消费索引 `.agent-skills.json`。公共仓库配置和各 Skill 配置仍分别使用严格的
  `agent-skills.repository/v1` 与 `agent-skills.<skill>/v1`；materialized wrapper、`study-log` CLI envelope
  和 raw archive 的既有 schema version 均未被改写。
- `guide-learning` 的配置只包含只读 `repository_fact_refs` 与候选 `record_mappings`。配置不保存 Program、
  Lesson、Session event、Checkpoint、练习契约或 mastery 的当前值；`write_paths` 只是机械上限，不能代替
  状态路径投影、六块练习契约、用户授权或结课确认。
- `study-log` 的公共配置只声明结构化记录 target roots，并产生 write-only allowlist；materializer 不扫描
  这些目录。会话 source、边界、临时提取位置、raw archive root、隐私决定和 exact target 仍只属于当次
  请求与用户级私有配置，不进入公共仓库配置、受管 context 或 state。
- materializer 现验证跨 Skill 写入边界：不同 Skill 的 write roots 不得重叠；一方写入、另一方读取同一
  collection 只有在双方配置都精确声明该交接时才合法，writer 不能扩大到 reader collection 的父目录。
  消费索引、repository config 与各 Skill config 的原始字节及 Git-tracked 合同还会在首次安装前及
  state 提交前再次复核；在复核点发现的竞态变化会停止并回滚。
- 中央完整验证为 `252 passed, 4 skipped, 54 subtests passed`；catalog 保持 11 Skills（6 first-party、
  5 official external），两个新增 validator、五 Skill 双 host 真实 materialization、配置隔离、raw 私有边界、
  兼容降级与结构校验均通过。跳过项仍只涉及当前 Windows 环境缺少链接／junction 权限的防护用例。
- 本节只涉及中央实现，不修改 PlanA、programming-lab 或 `daily-work`，也不读取或接管消费仓库中的
  未跟踪用户文件。消费仓库配置、子模块升级和重新 materialize 仍须单独实施与授权。

## 2026-08-12：D41 学习文章产物与历史产物适配批次

- 用户已确认把按需学习文章归入 `guide-learning`：中央核心提供通用文章骨架，消费仓库只通过受限的
  `article_profile` 声明语言、语气、章节、领域视角和候选目标。文章起草范围与精确落盘分别确认；静态
  配置不预授权写入、覆盖、发布、提交或推送。文章只综合已确认的学习内容和证据，不拥有或替代 Program、
  Lesson、Session event、Checkpoint、mastery，也不复制 `study-log` 的结构化记录或 raw archive 职责。
- PlanA 的历史适配边界已经确认：重复的 AI 陪学记忆、陪学流程和文章模板在中央能力及消费配置承接后
  退役；活动学习状态按稀疏 Program → Lesson → Checkpoint 事实链规范化，仪表盘只作派生视图，不反向
  发明缺失的授权、时间、练习证据或 mastery。仓库特有偏好和文章环境事实进入配置层，而不是复制中央
  行为规范。
- programming-lab 的既有 Lesson 01／02、历史对话、实验及其他 legacy 学习产物继续冻结，不进行回填、
  改写或追溯结构化。PlanA 的历史日志、英语卡片与资源规划 registry／slot／SOP 接管属于后续独立阶段，
  不与本轮状态和文章适配混写。
- 两个消费者的 version 2 基础迁移先形成 PlanA `1a2a162` 与 programming-lab `d4ddc14`。中央文章扩展
  随后在 `c3ae66a` 完成，并通过 `274 passed, 4 skipped, 54 subtests passed`、Skill 结构校验与独立
  边界审查。PlanA `b490b30` 又完成重复记忆／陪学流程／文章模板退役与状态稀疏规范化；programming-lab
  `60d5bc2` 只更新中央指针并继续冻结 legacy。两仓均重新 materialize、检查 current 并通过独立终审。
  中央与 PlanA 的后续日志、卡片、资源治理提交已经按依赖顺序发布；programming-lab 的 version 2 基线
  将与 D42 新增的英语反馈和制卡入口一并发布。

## 当前后续事项

1. PlanA 与 programming-lab 的 version 2 配置和历史产物边界均已完成；旧周报、旧 Lesson 与 raw 对话
   仍按各自合同冻结，不属于迁移欠账。
2. PlanA 的首次真实资源 refresh／review，以及两个仓库后续 Lesson、日志、卡片与 raw 产物，继续按
   当轮目标和授权运行；静态配置不预授权这些操作。
3. `creator-workflow` 仍绑定当前创作目录约定；其通用化评审、旧 Remotion 路由修正和 `daily-work` 适配
   已经登记为延期事项。

这些后续事项不阻塞当前中央学习核心。
