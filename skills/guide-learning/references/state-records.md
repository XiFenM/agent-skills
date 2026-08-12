# State records

在创建、恢复、暂停、写入或关闭 Program、Lesson、Session event 或 Checkpoint 时读取本参考。把这里的
对象视为逻辑职责，不要求固定目录或 Markdown 模板；先用 `repository-adaptation.md` 映射到仓库既有
事实源。

## Contents

1. [Keep state logical and singular](#keep-state-logical-and-singular)
2. [Project the minimum opening](#project-the-minimum-opening)
3. [Use the Program schema](#use-the-program-schema)
4. [Use the Lesson schema](#use-the-lesson-schema)
5. [Use the Session event schema](#use-the-session-event-schema)
6. [Use the Checkpoint schema](#use-the-checkpoint-schema)
7. [Enforce relations and invariants](#enforce-relations-and-invariants)
8. [Write only semantic transitions](#write-only-semantic-transitions)
9. [Pause, resume, and close](#pause-resume-and-close)
10. [Handle temporary programs](#handle-temporary-programs)

## Keep state logical and singular

分开四种职责，即使它们物理上共用一个文件：

- **Program control plane**：保存长期范围、候选 Lesson、已授权 Lesson 和条件性的前台指针。
- **Lesson evidence ledger**：保存目标、来源、阶段、练习契约、finding、evidence 和 final mastery。
- **Session event**：保存一次具有实质增量的会话片段。
- **Checkpoint**：保存唯一、可覆盖的精确恢复游标。

不要让 Program 复制 Lesson evidence，不要让 Lesson 复制教学正文或会话游标，不要让 event 复制 Lesson
状态，不要让 Checkpoint 累积历史。派生 dashboard、文章、学习日志、卡片和原始对话不是状态事实源。

允许一个物理文件承载多个逻辑对象，也允许分文件保存；同一语义只能有一个活动事实源。不要为通用
schema 强制创建档案树。

受管 context 的 `record_mappings` 只提供这些逻辑对象的候选物理 locator。它不提供对象内容，也不改变
本参考的字段、关系或写入事务。映射到同一文件时使用各自稳定 section；映射与实际职责不符时以仓库
指令和实际记录为准并先消除歧义。`allowlist.write_paths` 不构成创建、修改或关闭授权。

确实需要独立 Lesson 文件时，把约 50–80 行作为非约束性精简目标；只在练习、实验、Review 或 mastery
实际发生时增加条件片段，不为凑齐模板预建空章节。

## Project the minimum opening

开场投影只呈现既有逻辑状态，不生成第二份“开课契约”。

### 一次答疑

直接回答。不要展示固定卡片、创建 ID、读取无关长期状态或写入文件。只有来源、版本、假设或回答边界
会改变答案时，才用一句话说明。

### 独立 Session

开始或恢复时只展示：

- 当前上下文或短主题；
- 精确语义位置；
- 恰好一个首动作。

仅在存在时展示阻塞、前进门槛、drift 分支，以及首次建立的 Agent-owned 状态或基础记录路径。不要因为
跨会话恢复就自动创建 Lesson。

### 只创建 Program

首次只授权 Program 时展示：

- 长期目标和范围；
- 明确排除项；
- 候选 Lesson 的有序短描述；
- Agent-owned Program 路径；
- 实际需要恢复任务时的 Checkpoint 路径；
- 下一项授权动作。

不要虚构 active Lesson。候选 Lesson 不是已授权 Lesson，也不构成执行许可。

### 激活 Lesson

展示：

- 能力标题和 2–4 个目标；
- 每个目标的 required mastery 维度；
- teaching spine、事实权威和版本范围；
- 本课专属 evidence 目标；
- Agent-owned Lesson、event 和必要 Checkpoint 路径；
- 恰好一个首动作；
- 关闭本课需要确认，下一 Lesson 不自动启动。

用户一次请求同时明确授权 Program 与 Lesson 时可以合并投影。目标、范围、mastery、required gate、
路径或所有权存在重大歧义时先确认；否则足够具体的自然语言请求可以直接构成授权。

正式练习的测试、rubric、fixture 和完整 ownership scope 不在开课时预加载。只有综合验收确认需要练习
时，才按 `practice-review-mastery.md` 展示并接受练习契约。

## Use the Program schema

使用以下最小逻辑形状：

```yaml
program:
  id: <stable Program ID>
  title: <human-readable title>
  state: <planned | active | frozen | closed>
  objective_scope:
    objective: <long-term outcome>
    included: [<short scope item>]
    excluded: [<short non-goal>]
  candidate_lessons:
    - id: <candidate ID>
      title: <short capability title>
      order: <integer>
  authorized_lesson_refs: [<zero or more real Lesson references>]
  active_lesson_ref: <conditional>
  suspended_lesson_ref: <conditional>
  checkpoint_ref: <conditional>
  budget_ref: <conditional unique external source>
  continuous_progression: <conditional authorization boundary>
  parent_program_ref: <temporary Program only>
  return_ref: <temporary Program only>
```

必填：ID、标题、状态、目标范围、`candidate_lessons[]` 的有序短描述，以及可为空的
`authorized_lesson_refs[]`。

条件字段：

- 有前台 Lesson 时使用 `active_lesson_ref`。
- 冻结原 Lesson 时使用 `suspended_lesson_ref`，不要同时把它当作 active。
- 存在恢复任务时使用 `checkpoint_ref`。
- 已有预算时只保存 `budget_ref`；不要复制金额或时长。
- 用户明确授予按既定顺序连续推进时保存 `continuous_progression` 的适用范围；它不包含 optional、范围
  扩张、新依赖、新写入权限或跳过每课关闭确认。
- 临时 Program 才使用 parent 和 return 引用。

明确禁止：Lesson evidence、finding、精确游标、Session 历史、实际工时明细，以及把 candidate 写成
已授权 Lesson。

## Use the Lesson schema

使用以下最小逻辑形状：

```yaml
lesson:
  id: <stable Lesson ID>
  title: <one independently assessable capability>
  program_ref: <owning Program>
  sources:
    - locator: <source reference>
      role: <source role>
      version_anchor: <commit, tag, version, or date>
      scope: <used portion>
  objectives:
    - id: <objective ID>
      statement: <observable target>
      mastery:
        conceptual: <required | not-required>
        practical: <required | not-required>
        empirical: <required | not-required>
  stage: <teaching | synthesis | practice | review | mastery-gate | complete>
  evidence_targets: [<lesson-specific evidence goal>]
  prerequisite_gaps: <conditional>
  core_artifacts: <conditional>
  accepted_practice: <conditional revision and digest reference>
  findings: <conditional stable finding records or references>
  material_assistance: <conditional affected-scope records>
  event_refs: <conditional index>
  final_mastery: <conditional after confirmed closure>
  fallback_mental_model: <conditional 3–6 lines>
```

必填：ID、能力标题、Program 引用、带角色和版本范围的来源、2–4 个目标及其 required mastery 维度、
当前 stage 和本课专属 evidence 目标。

仅在实际发生时添加条件片段。只有没有文章或其他权威知识产物可以链接时，才保存 3–6 行、明确标为
fallback 的简短心智模型。

明确禁止：完整教学正文、逐题问答、完整命令输出、原始对话、暂停快照、逐轮 Review、重复 checklist、
changelog 和 `paused` 状态。

## Use the Session event schema

每个具有实质增量的会话或暂停段最多追加一条 event：

```yaml
session_event:
  id: <stable event ID>
  date: <absolute date>
  context:
    lesson_ref: <when a Lesson exists>
    topic: <short independent Session label when no Lesson exists>
  covered_scope: <short source or capability span>
  completed_actions: [<substantive action>]
  evidence_refs: <conditional>
  open_issues: <conditional>
  confirmed_duration: <conditional, only user-provided or confirmed>
  marker: <conditional closure | practice-closed>
```

`lesson_ref` 与独立 `topic` 选择一个。`marker` 只在同一 event 完成相应关闭事务时出现；不要为 closure
额外再建一条 event。

明确禁止：精确游标、完整会话摘要、逐轮问答、全部产物清单和 Lesson 状态副本。

## Use the Checkpoint schema

只在存在恢复任务时保存：

```yaml
checkpoint:
  foreground_context: <Program, Lesson, temporary Program, or independent topic reference>
  semantic_position: <exact source node, learning phase, or review location>
  next_action: <exactly one executable action>
  forward_gate: <what must be true before advancing>
  blockers: <conditional short references>
  latest_evidence_ref: <conditional, at most one latest useful anchor>
  return_point: <temporary Program only>
  as_of: <conditional, update only with semantic change>
```

覆盖更新 Checkpoint，不追加历史快照。`next_action` 恰好一个；即使 Review 向用户展示最多三个当前
动作，Checkpoint 也只指向第一个可执行动作。

明确禁止：完成内容长叙述、Session 历史、预算、cadence、隐私政策、finding 明细、多个下一动作和纯
时间戳更新。

## Enforce relations and invariants

### Program and Lesson pointers

- `candidate_lessons[]` 只保存候选 ID、标题和顺序；不创建 Lesson。
- `authorized_lesson_refs[]` 只指向真实、已授权 Lesson。
- 开放 Program 的 candidate 或 authorized 集合至少一个非空。
- `active` Program 有前台 Lesson 时设置 `active_lesson_ref`；等待下一 Lesson 授权时可以为空。
- `frozen` Program 将原引用放入 `suspended_lesson_ref` 并保留 Checkpoint 或 return capsule。
- `planned` 与 `closed` Program 的 active 和 suspended 指针均为空。
- 同一工作上下文只允许一个前台 active Lesson。

### Checkpoint presence

- 已有可恢复上下文时 `checkpoint_ref` 必填。
- `planned` 且尚未开始，或 `closed` 且没有返回任务时，可以没有 Checkpoint。
- Lesson 边界等待用户决定时，把唯一下一动作写为等待下一 Lesson 授权。
- 真正终态不伪造下一动作；移除 Checkpoint 和引用。

### Session and Lesson state

- 暂停或结束 Session 不改变 Lesson 为 paused 或 complete。
- 读完来源、完成文章或生成学习日志不构成 Lesson complete。
- 独立 Session 可以保存 topic、event 和 Checkpoint，不自动升级为 Lesson。
- 独立 Session 的练习契约、测试或 rubric 可以作为工件保存并由 Checkpoint 引用；它们不是新的状态层。

## Write only semantic transitions

默认保持只读。普通讲解、追问、理解检查、正确回答、关键节点推进和无 drift 恢复均不写入。

只在以下耐久事实变化时按需同步授权状态：

- 正式练习契约被接受；
- 学习者提交核心工件；
- material assistance 改变独立 evidence 的有效范围；
- 正式 Review 形成新的 durable finding；
- 验证改变 finding、evidence 或 mastery 判断；
- 跨过综合验收或进入 mastery gate；
- 为跨会话恢复而改变唯一下一动作；
- Session 暂停、计划内收工，或用户确认关闭 Lesson／Program。

应用 semantic diff：状态、证据和下一动作均未改变时不写；不要只更新时间戳。`as_of` 只随它所描述
语义变化。学习时长只记录用户明确提供或确认的值；缺少时长不阻塞 event 或 Checkpoint。

新增路径、扩大目标、范围、required mastery 或 gate、改变所有权、启动未授权 Lesson、重开 complete
Lesson、关闭 Lesson 或 Program，都先取得相应授权。已授权范围内的 Review、验证、event 和 Checkpoint
更新可以自动执行，不逐次展示 diff。

## Pause, resume, and close

### Pause or planned stop

把暂停与计划内收工视为一个最小事务：

1. 有实质进展时追加当段唯一 Session event。
2. 仍有恢复任务时覆盖 Checkpoint；真正终态时移除它。
3. 没有进展、evidence 或游标变化时零写。

不要自动生成文章、结构化学习日志、原始对话或卡片。不要把 Lesson 改为 paused 或 complete。

### Resume

读取 Program、Lesson 和 Checkpoint 的实际映射，执行低成本 drift 核验。没有 drift 时直接执行唯一下一
动作且零写。drift 会改变范围、责任、来源版本或下一动作时，向用户展示最小分支并等待选择。

### Close a Lesson

先展示每项目标、required 维度、最小 evidence、required finding 和 nonblocking 余项。用户确认后：

1. 一次写入 `final_mastery` 与 `stage: complete`；
2. 把当段唯一 Session event 标为 `closure`；
3. 把 Checkpoint 移到 Lesson 边界，等待下一 Lesson 授权；
4. 没有后续恢复任务时移除 Checkpoint。

不要自动启动下一 Lesson。complete Lesson 的一次补充答疑默认零写；只有当轮本就是独立 Session 时才
追加补充 event。只有新 evidence 推翻 mastery 或目标扩大时，才提议重开或另建 Lesson。

### Close independent practice

保存会话级 evidence、练习工件引用，并把当段唯一 event 标为 `practice-closed`。不要写 final Lesson
mastery。需要长期 mastery 时先授权创建或并入 Lesson。

## Handle temporary programs

只有旁支满足至少一个条件时才建立临时 Program：

- 需要跨会话推进；
- 形成独立目标或产物；
- 会替换原唯一下一动作。

启动时冻结原 Program、Lesson 和 Checkpoint，保存 parent、return point 和最小 return capsule。单轮旁支
答疑不创建临时状态。

临时 Program 结束时展示专项结果和原返回点，让用户选择返回、延长或转向。不要自动跳回或启动新的
Lesson。返回时恢复原唯一下一动作，并对期间 drift 做最小核验。
