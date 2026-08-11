# Boundary examples

只在运行范围、练习分流、恢复、临时专项、来源冲突或关闭分支仍不清楚时读取本参考。以下案例是
非规范性说明；字段和 gate 仍以其他 references 为准。

## Contents

1. [One-off explanation](#one-off-explanation)
2. [Unknown knowledge](#unknown-knowledge)
3. [Independent Session without a Lesson](#independent-session-without-a-lesson)
4. [Program before Lesson authorization](#program-before-lesson-authorization)
5. [Skip formal practice](#skip-formal-practice)
6. [Revise a formal practice contract](#revise-a-formal-practice-contract)
7. [Material assistance and revalidation](#material-assistance-and-revalidation)
8. [Pause and resume without drift](#pause-and-resume-without-drift)
9. [Resume with drift](#resume-with-drift)
10. [Temporary program](#temporary-program)
11. [Source conflict](#source-conflict)
12. [Different closure branches](#different-closure-branches)

## One-off explanation

**Situation:** 用户问一个当前概念为什么成立，没有表达持续学习意图。

**Choose:** 一次答疑。

**Act:** 直接解释机制和边界；必要时用一个轻量条件变化检查理解。不要展示固定开场卡片，不创建
Program、Lesson、event 或 Checkpoint，也不安排下一主题。

**Write:** 默认零写。只有用户明确要求保存时，才生成紧凑记录。

## Unknown knowledge

**Situation:** 学习者尚未接触某机制，问题无法从已确认前置推导。

**Do not:** 在讲解前让学习者猜事实，或把猜错解释为能力不足。

**Act:** 先给一张短全局图并讲清第一个关键节点，再提出一个只依赖刚讲内容的检查。若事实本身未知或
版本敏感，先核验权威来源，并明确事实、观察、推断和待验证假设。

## Independent Session without a Lesson

**Situation:** 用户希望今天集中学习一个主题并可能明天继续，但没有建立长期 Course 的意图。

**Choose:** 独立 Session。

**Opening:** 只展示短主题、当前语义位置和唯一首动作。若首次需要持久恢复，先披露 event 与 Checkpoint
路径并取得授权。

**During:** 运行关键节点微循环和综合验收。若仍缺实践 evidence，可以接受一次正式练习契约并保存
练习工件；不要因此创建 Lesson。

**Write:** 会话边界最多一条 event；存在恢复任务时维护 Checkpoint。练习关闭时标记
`practice-closed`，不写 final Lesson mastery。

## Program before Lesson authorization

**Situation:** 用户希望规划一门跨会话课程，但尚未选择第一课。

**Choose:** 创建 Program，不创建 active Lesson。

**Opening:** 展示长期目标、范围、排除项、候选 Lesson 短描述和 Program 路径。若没有实际恢复任务，
不要创建 Checkpoint。

**State:** `candidate_lessons[]` 有内容，`authorized_lesson_refs[]` 可为空，`active_lesson_ref` 为空。

**Next:** 唯一授权动作是让用户选择或定义第一 Lesson，而不是自动开始候选列表第一项。

## Skip formal practice

**Situation:** 概念型 Lesson 完成关键节点后，学习者能独立复述中心模型、指出反例，并在陌生同构情境中
完成诊断；该 Lesson 的 practical 与 empirical 均预先声明为 `not-required`。

**Act:** 把综合验收直接记为 conceptual evidence，进入 mastery gate。不要安排形式性的代码或长作业。

**Close:** 展示目标 × conceptual evidence，等待用户确认。不要自动进入 optional extension 或下一课。

## Revise a formal practice contract

**Situation:** revision 1 的契约已经接受；Review 发现原 acceptance 中“输出保持一致”存在主语歧义。

**Act:** 把它标为 contract clarification，不建 learner finding。明确 observable criterion，递增为 revision
2，重新计算 digest，展示语义变化并取得新接受。

**Do not:** 让 revision 1 的 acceptance event继续授权 revision 2，也不要把旧歧义归责于学习者。

**If no gate change:** 纯排版或措辞等价变化保持原 revision；不要制造 digest churn。

## Material assistance and revalidation

**Situation:** 学习者主动请求更强帮助，Agent 给出核心分解与伪代码骨架，但未写 learner-owned 文件。

**Record:** 只保存最高实质帮助“核心分解与伪代码骨架”、受影响 objective／acceptance／artifact 范围，
以及 `agent_wrote_learner_core: false`。不要保存提示全文或轮数。

**Evidence effect:** 只撤销该范围的独立 practical evidence。让学习者在无材料提示下完成一个更小、表面
不同但心智模型相同的新变式；把成功 evidence 写回 mastery。

**If Agent writes core:** 先重新授权 learner-owned 修改，并把相应范围标为 AI-assisted；不要把该实现
直接当作学习者独立实践 evidence。

## Pause and resume without drift

**Pause:** 学习有实质进展，因此追加当段唯一 event，并把 Checkpoint 覆盖为精确位置、一个下一动作和
前进门槛。不要把 Lesson 改为 paused。

**Resume:** 读取实际 Program、Lesson 和 Checkpoint；来源、scope 和工件均未变化。

**Act:** 用一句话投影当前位置和唯一动作，直接继续。恢复操作保持只读，不更新时间戳或追加“已恢复”
event。

## Resume with drift

**Situation:** Checkpoint 指向的来源 revision 已改变，且差异可能推翻当前 explanation 或 acceptance。

**Act:** 做最小差异核验，展示三个以内清晰分支，例如继续旧锚点、迁移到新 revision、或冻结当前
Lesson 另开兼容性调查。让用户选择。

**Write:** 用户选择前不改目标、source anchor 或下一动作。选择后只更新受影响事实和 Checkpoint。

## Temporary program

**Situation:** 学习主线中出现一个需要两次会话完成的环境专项，它会替换原唯一下一动作并产生独立
产物。

**Act:** 冻结原 Program、Lesson 和 Checkpoint，保存 parent、return point 与最小 return capsule；建立
临时 Program。

**Close:** 展示专项结果与原返回点，让用户选择返回、延长或转向。不要自动跳回主线。

**Counterexample:** 单轮澄清一个旁支术语不会替换下一动作，因此保持一次答疑，不建立专项状态。

## Source conflict

**Situation:** 用户选定教程作为 teaching spine，但固定 revision 的源码与教程描述不同。

**Act:** 保留教程的教学顺序；分别说明教程的 explanatory role 和源码的 implementation authority，核对
版本、分支与配置。按用户目标 revision 选择本课采用的行为。

**If blocking:** 冲突阻塞目标时做最小一手核验；仍无法解决则标为待验证。

**If nonblocking:** 保存 observation 并返回 teaching spine。不要静默换教程，也不要扩成资料治理项目。

## Different closure branches

### Authorized Lesson

展示每项目标 × required mastery 维度的最小 evidence、required findings、assistance 恢复和 nonblocking
余项。用户确认后写 final mastery，把当段 event 标为 `closure`，并移动或移除 Checkpoint。不要自动
启动下一 Lesson。

### Independent Session practice

展示会话级 evidence 和练习 gate。关闭后保存工件引用，把当段 event 标为 `practice-closed`；不要写
Lesson mastery。没有后续恢复任务时移除 Checkpoint。

### Completed Lesson follow-up

一次补充答疑不改变 `complete`，默认零写。只有新 evidence 推翻原 mastery 或用户扩大目标时，才提议
重新授权并重开或另建 Lesson。
