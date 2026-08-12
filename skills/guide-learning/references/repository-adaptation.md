# Repository adaptation

在发现消费仓库的记录约定、把 Program／Lesson／Session event／Checkpoint 映射到实际文件、选择授权
路径，或仓库没有学习结构而需要 schema-only fallback 时读取本参考。不要硬编码某个消费仓库的路径。

## Contents

1. [Inspect before mapping](#inspect-before-mapping)
2. [Use managed context as locators](#use-managed-context-as-locators)
3. [Discover facts in order](#discover-facts-in-order)
4. [Assign one role to each fact](#assign-one-role-to-each-fact)
5. [Choose and authorize paths](#choose-and-authorize-paths)
6. [Use schema-only fallback](#use-schema-only-fallback)
7. [Avoid duplicate facts](#avoid-duplicate-facts)
8. [Preserve legacy evidence](#preserve-legacy-evidence)

## Inspect before mapping

先读取仓库级指令、目录结构、已有学习或项目记录、当前状态和相关验证方式。检查是否存在未提交用户
工作；不要覆盖、移动或顺手整理无关内容。

优先回答：

- 哪个文件已经拥有长期目标和范围？
- 哪个位置已经拥有当前能力的设计、实验或证据？
- 哪个位置拥有实际进度或用户确认的时间？
- 是否已有唯一恢复游标？
- 哪些文件只是 dashboard、文章、日志、卡片或原始对话？
- 哪些路径允许 Agent 创建或维护？

从内容和仓库约定判断职责，不只根据文件名。一个物理文件可以承载多个逻辑对象，但要能用稳定锚点
区分；多个物理文件不得同时拥有同一活动事实。

## Use managed context as locators

生成副本可能带有 materializer 管理的 `.agent-skills-context.json`。仅在 wrapper 的 manager、Skill 身份和
context schema 完整匹配时使用它；不要自行修补或部分解释未知字段。

- `repository_fact_refs` 只定位只读的仓库指令、偏好、预算、资料、验证方式或历史 evidence。角色名称
  不会把资料自动提升为 teaching spine、claim authority 或 mastery evidence。
- `record_mappings` 只定位 Program、Lesson、Session event、Checkpoint 或练习工件的候选物理位置。
  文件内容仍是事实源；context 不保存其当前状态。
- `allowlist.write_paths` 是 materializer 核验过的机械上限，不是写入授权。仍须按本参考、
  `state-records.md` 和练习契约投影实际路径、职责与所有权。

先核对映射路径或 section 的实际内容是否承担声明角色。若映射与仓库指令、既有唯一 owner 或未提交用户
工作冲突，保持只读并让用户选择；不要按配置另建第二份记录。context 缺失时继续下面的正常发现顺序；
context 损坏或身份不符时停止使用其全部 locator，并要求重新 materialize。

## Discover facts in order

按以下顺序寻找映射：

1. 仓库指令中明确声明的状态、课程或记录事实源；
2. 已存在的 Program、Lesson、进度或 Checkpoint 结构；
3. 当前领域的设计包、实验包、研究记录或项目文档中可复用的逻辑章节；
4. 仓库已有的 notes、docs 或 learning 约定；
5. 用户明确指定的位置；
6. 完全没有约定时，由用户授权的 schema-only fallback。

找到合适位置后停止搜索。不要因为通用 schema 更整齐就创建第二套树。不要把 README、入口说明或
Agent 指令文件变成状态账本，除非仓库明确赋予它们该职责。

若同一候选位置承担多个能力，使用明确命名和稳定锚点分别承载多个 Lesson；不要机械复制整份文件。

## Assign one role to each fact

使用下表判断逻辑角色：

| 逻辑事实 | 合适的既有位置 | 不应承担该事实的位置 |
| --- | --- | --- |
| Program 目标、范围、候选 Lesson | 长期计划或课程控制面 | Lesson evidence、Session 日志、文章 |
| Lesson 目标、来源、阶段、契约、finding、mastery | 当前能力的设计／实验记录或轻量 Lesson 章节 | dashboard、原始对话、卡片 |
| Session event | 已有进度日志或 Lesson event 索引 | Checkpoint、完整教学文档 |
| Checkpoint 精确位置与唯一下一动作 | 唯一恢复文件或受控状态条目 | 历史日志、进度总表、Lesson 正文 |
| 全局预算 | 已有长期计划中的唯一预算事实源 | 适配说明、Checkpoint、Session event |
| 资料预计投入 | 稳定课程或资料治理文件 | 实际进度记录 |
| 用户确认的实际用时 | 原始进度事实源 | 派生 dashboard、Lesson evidence |
| 周期性汇总 | 派生 dashboard | 当前游标或原始 event 事实源 |
| 知识叙述 | 文章或权威知识产物 | Program、Checkpoint |
| 误解、纠错与关键转折 | 按需结构化过程记录 | mastery 结论的替代品 |
| 原始可见对话 | 经用户确认的原始归档 | 课程状态、正确结论 |

让 Program 只引用 Lesson，让 Lesson 只链接权威知识产物和大体量证据，让 Checkpoint 只链接最近有效
evidence。不要复制正文、命令输出或历史 Review。

## Choose and authorize paths

在首次创建 Program／Lesson 或任何 Agent-owned 状态文件前，向用户投影拟用路径及其逻辑职责。足够
具体的开始请求可以授权目标和范围，但不能自动授权未披露的路径。

受管 context 中已有 mapping 只省去路径猜测，不省去这里的授权。collection mapping 只表示一个狭窄
候选命名空间；正式练习仍须在六块契约中列出实际文件或受限 pattern，且不得覆盖未知成员。

选择路径时：

- 使用仓库相对路径；
- 限定到具体文件、稳定章节、受限 pattern 或逻辑工件 ID；
- 避免把宽泛目录当作所有权；
- 遵循仓库命名、语言和格式；
- 把记录、验收测试、rubric、fixture 和 Checkpoint 分别列入相应契约 scope；
- 不改变配置、CI、依赖或公共接口，除非用户另行授权。

把现有文件列为 learner-owned 或 read-only 时，不因 Agent 能读取就假设可修改。正式练习的 Agent-owned
路径在练习契约中单独授权，不在开课时预授权全部可能工件。

若路径存在歧义且选择会改变事实源或覆盖用户工作，停下来询问。不要通过创建“临时”第二事实源规避
选择。

## Use schema-only fallback

只有仓库完全没有可复用约定时才使用 fallback：

1. 依据当前运行范围选择必要逻辑对象；一次答疑仍默认零写。
2. 向用户提出一个最小、仓库风格一致的目标路径和职责。
3. 获得授权后，直接按 `state-records.md` 的逻辑字段写入；不要复制通用模板或创建固定档案树。
4. 独立 Session 优先只保存 event 和必要 Checkpoint；不要为形式完整创建 Program 或 Lesson。
5. 持久 Course 才创建 Program 和真实授权 Lesson；候选 Lesson 仍只是短描述。
6. 记录该路径为何成为唯一事实源，避免后续 Agent 再创建副本。

不要附带 README、archive index、固定 Lesson 模板、初始化脚本或示例占位文件。没有实际数据的条件片段
不写入。

## Avoid duplicate facts

对每类语义执行 single-writer 检查：

- **长期范围**：只在 Program 事实源修改；其他位置只引用。
- **Lesson evidence**：只在 Lesson ledger 修改；文章和过程日志只链接。
- **实际用时**：只在原始进度源修改；dashboard 由其派生。
- **当前游标**：只在 Checkpoint 修改；Session event 不保存精确位置。
- **finding**：只在稳定 finding 记录原地更新；Checkpoint 只列短 blocker 引用。
- **最终 mastery**：只在用户确认关闭后的 Lesson 写入；派生视图不得成为第二裁决者。

在写入前比较 semantic diff。若只是更新派生视图，先确认仓库已有周期性触点；不要随每次 Session 同步
所有汇总。派生视图过期不应反向覆盖原始事实。

文章、结构化过程记录、原始对话和卡片均按需生成。它们可以引用 Lesson 和 evidence，但不得保存当前
stage、唯一下一动作或独立 mastery 副本。

## Preserve legacy evidence

迁移旧记录时保留历史 evidence，不批量重写已完成 Lesson、旧 Skill 名称、旧路径、原始对话或已纳入
哈希的正文。把旧内容标为历史快照或 legacy evidence，并为新活动状态选择一个唯一事实源。

停止双写时按语义切换：

1. 识别旧文件间重复的当前位置、下一动作、Session 日志、时间或 mastery；
2. 选择一个活动 owner，并让其他位置停止更新；
3. 保留旧内容作为带日期历史，不让它继续裁决当前状态；
4. 在当前 Checkpoint 记录迁移后的同一语义位置和唯一下一动作；
5. 验证恢复无 drift 后再继续教学。

不要为了采用新 schema 等待整个 Course 完成；在真实暂停点做最小适配。不要在迁移过程中触碰无关用户
工作，也不要把适配说明变成另一套流程事实源。
