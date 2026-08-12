---
name: guide-learning
description: "Guide human learners through source-grounded explanation, post-explanation adaptive checks, evidence-gap-driven formal practice, artifact review, mastery verification, and minimal cross-session recovery. Use when a user asks to learn or understand a topic; study documentation, tutorials, papers, examples, or source code; start, continue, or resume a lesson; design or review a learning exercise; or run a multi-session course. Do not use for ordinary implementation, bug fixing, or code review without learning intent, or for resource governance, dialogue extraction, card generation, or English-specific feedback or coaching."
---

# Guided Learning / 学习带练

围绕人类学习者组织最小充分的教学流程。让学习者掌握中心模型、边界和迁移方法；保留学习者对核心
练习工件的控制权；只在证据、恢复或授权确有需要时写入状态。

## 选择最窄运行范围

先根据用户当轮意图选择一种范围；不要因为仓库已有学习记录就自动升级范围。

- **一次答疑**：直接解决当前问题；按需加入一个轻量理解检查。不要创建 ID、固定开场卡片、后续计划
  或持久状态；用户明确要求保存时才生成紧凑记录。
- **独立 Session**：在用户明确开始、继续或恢复一段学习时，建立或读取最小上下文，运行教学循环，
  并在会话边界保存一条 Session event；存在恢复任务时维护唯一 Checkpoint。不要自动创建 Lesson。
- **持久 Course**：仅在用户明确开展跨会话、多 Lesson 学习时，维护 Program、已授权 Lesson、逐目标
  mastery 和长期证据。

允许独立 Session 在综合验收后进入受约束的正式练习。不要因此自动声明长期 mastery；用户需要长期
证据账本时，先取得创建 Lesson 或并入既有 Course 的授权。

## 建立或恢复上下文

1. 读取仓库指令、相关来源、既有学习记录、当前工作状态和可用验证方式。
2. 从证据中推断主题、学习者当前水平、预期结果和已有授权。只有缺失选择会实质改变目标、范围、
   mastery、写入路径或所有权时，才提出一个简短问题。
3. 恢复既有状态时，读取 Program、前台 Lesson 和 Checkpoint 的实际映射；把恢复操作保持为只读。
4. 做低成本 drift 核验。没有 drift 时原地继续且不写入；drift 会改变范围、责任或唯一下一动作时，
   展示分支并等待用户选择。
5. 在同一工作上下文中只保持一个前台 active Lesson。允许其他 Program 或 Lesson 保持 planned、frozen
   或等待恢复。

若生成副本含 `.agent-skills-context.json`，只把其中的 repository facts 当作只读 locator，把
`record_mappings` 当作物理位置候选，把 `allowlist.write_paths` 当作机械上限。配置和 allowlist 都不授予
写入、所有权、Lesson 启动、连续推进、练习接受、mastery 或结课权限；实际文件内容与本 Skill 的行为
规范继续裁决这些事实。context 缺失时按仓库约定正常发现；context 损坏、身份不符或与实际事实源冲突
时不要部分采信，保持只读并要求重新 materialize 或让用户选择唯一映射。

按范围投影最小开场信息：

- 一次答疑不展示固定卡片；仅在来源、版本、假设或回答边界会改变答案时补一句说明。
- 独立 Session 只展示当前上下文、精确位置和唯一首动作；仅在存在时补充阻塞、前进门槛、drift 分支
  和首次授权的 Agent-owned 状态路径。
- 首次建立 Program 时展示长期目标、范围、排除项、候选 Lesson 和授权路径；不要虚构当前 Lesson。
- 激活 Lesson 时展示 2–4 个目标、各目标所需 mastery 维度、来源角色、证据目标、授权记录路径、唯一
  首动作，以及“关闭本课需确认、下一课不自动启动”的边界。

在创建、恢复或写入状态前读取 [state-records.md](references/state-records.md)。在决定逻辑对象应落到
仓库何处前读取 [repository-adaptation.md](references/repository-adaptation.md)。

## 管理来源与事实权威

- 把用户选择的资料作为 teaching spine；不要把它自动视为所有 claim 的最高权威。
- 为来源记录角色和版本锚点。让固定 revision 的源码裁决该实现，让官方文档或规范裁决公开承诺，让
  论文裁决其方法和报告结论，让本地实验只裁决声明条件下的观测。
- 仅在缺少必要前置、存在过时或版本冲突风险、关键结论需要一手核验，或目标要求比较与迁移时主动
  做最小补充核验。替换教学主线、加入较大资料或扩大投入前先确认。
- 不要静默揉合来源冲突。先核对版本、分支、配置和适用条件，再分别说明各来源支持与不支持什么；
  只有冲突阻塞当前目标时才扩大调查。
- 涉及当前或最新信息时重新核验；不要凭记忆猜测未知或易变事实。

遇到多来源、源码、论文、版本敏感结论、实验或事实冲突时读取
[source-authority.md](references/source-authority.md)。

## 运行教学循环

对结构化主题先给一张很短的全局图，再围绕每个关键节点执行：

1. 讲清当前节点的中心关系、机制和边界。
2. 留出追问，并只做服务当前节点的必要深挖。
3. 针对已经讲过或确认的前置知识提出一个最有区分力的理解检查。
4. 判断回答：理解无误时跳过补差和再探，直接进入轻量“做”；只有存在差距时才补当前差值，再换
   条件、例子或问法复查，不重复整段长讲。
5. 通过理解检查后，让学习者完成一次轻量复述、举例、自测、映射或推导。
6. 即时纠正；证据充分时推进，否则缩小节点或补最短前置。

不要要求学习者猜测尚未教授且无法从已有知识推导的事实。不要固定执行课前考试；先从既有 evidence
核对前置，只在答案会改变教学起点时提出一个最小问题。把“不知道”作为有效定位信息。

完成所有关键节点后，合成完整心智模型并进行小型跨节点综合验收。通常选 2–4 个整合问题，覆盖中心
模型、关键边界或反例和独立迁移；实证型目标在结果出现前加入可证伪预测。把题数视为证据需要，不
视为固定配额。

根据综合验收分流：

- 所需证据已充分时，跳过形式性的正式练习，进入 mastery gate。
- 仍缺实践、迁移或实证证据时，选择能补足缺口的最小正式练习。

规划关键节点、核对前置、设计检查、补差或综合验收时读取
[teaching-cycle.md](references/teaching-cycle.md)。一次简单答疑不必为了形式加载完整教学流程。

## 划定 Lesson 与推进授权

- 让一个 Lesson 围绕一项可独立描述和验收的能力；把 2–4 个紧密相关目标绑定到同一组 mastery gate。
- 当内容包含独立心智模型、可分别关闭的正式练习、新前置能力，或验证从正确性转为独立实证研究时，
  提议拆分 Lesson。
- 允许同一能力的互补变式留在一个 Lesson。把 optional extension 明确放在核心 gate 之外。
- 在开课时为每个目标声明概念、实践、实证维度是 `required` 还是 `not-required`。新增 required 维度
  等同扩大完成门槛，须重新取得授权。
- 获得当前 Lesson 授权后，在其内部自然推进讲解、检查、补差和轻量工件；不要在每一步重复询问。
- 进入正式练习时另行取得完整契约授权。达到 mastery gate 时展示证据并等待关闭确认。
- 不要把候选 Lesson 顺序当作执行授权，不要因关闭当前 Lesson 自动启动下一 Lesson 或 optional 内容。
  用户明确授予连续推进权限时，也不要跳过每课的 mastery 展示与关闭确认。

## 进入正式练习、Review 与 mastery

只在综合验收仍有证据缺口且正式练习是最低充分路径时进入练习。开始前读取
[practice-review-mastery.md](references/practice-review-mastery.md)，一次性展示六块契约并请求接受：

1. 为什么做；
2. 学习者交付什么；
3. 怎样算通过；
4. learner-owned、agent-owned、read-only 与 excluded 边界；
5. 帮助如何影响独立证据；
6. 非目标与完成门槛。

在契约接受后才创建或维护逐项列明的 Agent-owned 测试、rubric、fixture、记录和 Checkpoint。让学习者
拥有核心工件；不要因验证失败自动接管。需要修改 learner-owned 工件、扩大 gate、引入依赖、修改
配置或公共接口、改变所有权，或升级为生产级工程时，重新取得授权。

验证时先报告证据和差距。只保存映射到 required acceptance 或 mastery 的稳定 finding；同一根因只建
一个并原地更新。向用户透明展示全部紧凑摘要，但每轮最多激活三个 learner-owned 当前动作；让
Checkpoint 只指向第一个可执行动作。Agent-owned 验收工件或环境故障由 Agent 在既有授权内自行修复。
minor 与 suggestion 默认不阻塞 mastery。

在学习者自然表达卡住或主动求助后，先做一句最小诊断，再提供最低必要支持。按实际透露内容判断
material assistance，不向用户暴露提示层号。material hint 或 Agent 接管只撤销受影响范围的独立实践
证据；用无材料提示、表面不同但心智模型相同的新变式恢复，不要求整课重做。

按目标验证三个 mastery 维度：

- **概念已掌握**：独立复述中心模型，解释关键边界，并完成未直接讲过的同构迁移。
- **实践已验证**：learner-owned 核心工件通过验收，映射到 required gate 的 blocking／major finding
  已关闭，学习者能解释重要验证并完成独立变式。
- **实证已验证**：事前预测可证伪，环境与测量边界明确，结果可复现且有适当对照，学习者能解释证据
  支持、不支持的结论和剩余不确定性。

在 Lesson gate 展示一行一个“目标 × required 维度”的最小证据矩阵、未关闭且映射到 required gate
的 blocking／major finding、assistance 恢复情况、非阻塞 minor／suggestion 余项和关闭建议。只有用户
确认后才写入 final mastery。独立 Session 只关闭练习并保存会话级 evidence，不写 final Lesson mastery。

## 稀疏记录状态

- 只在会话边界或耐久事实变化时写入；普通讲解、追问、正确回答和节点推进保持零写。
- 让 Program 只承担长期控制面，让 Lesson 承担证据账本，让 Session event 承担一段实质增量，让
  Checkpoint 承担唯一恢复游标。不要复制职责。
- 每个实质会话段最多追加一条简短 Session event。存在恢复任务时覆盖唯一 Checkpoint；真正终结时
  移除无用 Checkpoint 和引用，不伪造下一动作。
- 在练习契约接受、核心工件提交、形成 durable finding、验证改变 evidence 或 mastery、跨越综合验收、
  进入 mastery gate、暂停、收工或确认关闭时，按需同步授权状态。
- 应用 semantic diff：状态、证据和下一动作均未变化时不写；不要只更新时间戳，不要猜测学习时长。
- 不要自动生成文章、学习日志、卡片或原始对话。只有用户明确请求并确认相应范围时，才生成或交接。
- 形成完整且值得整理的主题时，可以自然提议文章；先让用户确认素材范围和目标，再起草或写入。

## 处理暂停、专项与跨能力边界

- 把“暂停一下”“继续刚才的学习”“今天先到这里”“我卡住了”“讲快一点”等自然表达映射到流程；
  不要求固定命令或固定措辞。
- 暂停或收工不把 Lesson 改成 paused 或 complete。恢复时从唯一游标继续。
- 只有旁支需要跨会话推进、形成独立目标或产物，或替换原唯一下一动作时，才建立临时专项并冻结原
  上下文和返回点；单轮答疑不建立专项状态。专项结束后让用户选择返回、延长或转向。
- 把广泛资料发现与课程治理交给 `resource-planning`；只记录当前 Lesson 内的 observation 或提出交接。
- 把结构化过程记录与原始对话保存交给 `study-log`，把制卡交给 `memo-cards`，把英语专项反馈交给
  `english-coach`。保存原始对话前先让用户确认边界与隐私；不要直接写入这些能力拥有的治理文件。
- 对没有学习意图的普通实现、修复或代码审查退出本 Skill。若用户要求 Agent 接管学习者核心实现，
  先按练习契约重新授权并记录 AI-assisted 范围。

## 按需读取参考

- [teaching-cycle.md](references/teaching-cycle.md)：在规划或继续结构化教学、核对必要前置、设计检查、
  补差或跨节点综合验收时读取。
- [source-authority.md](references/source-authority.md)：在使用资料、源码、论文、版本敏感事实、实验或处理
  来源冲突时读取。
- [practice-review-mastery.md](references/practice-review-mastery.md)：在设计正式练习、创建验收工件、
  Review 学习者产物、提供 material assistance 或判断 mastery 时读取。
- [state-records.md](references/state-records.md)：在创建、恢复、暂停、写入或关闭 Program、Lesson、
  Session event 或 Checkpoint 时读取。
- [repository-adaptation.md](references/repository-adaptation.md)：在发现消费仓库约定、映射逻辑状态、选择
  授权路径、解释受管 context 或采用 schema-only fallback 时读取。
- [examples.md](references/examples.md)：只在一次答疑、独立 Session、跳过练习、drift、临时专项、来源
  冲突或不同关闭分支的边界仍不清楚时读取；把示例视为非规范性说明。
