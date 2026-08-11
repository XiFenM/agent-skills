---
name: resource-planning
description: 研究、刷新与治理学习或工作资料组合，支持证据化专题研究、受管来源的增量刷新，以及经用户逐项确认的资源组合评审。Use when the user asks to research or compare resources, refresh configured sources or queries, review pending resource candidates, or safely add, annotate, replace, retire, defer, reject, or supersede items in a managed resource portfolio.
---

# Resource Planning

在开始时明确选择一种模式；不自动串联模式：

- `research`：围绕当前问题搜索、比较和推荐。默认只在对话中预览；只有用户当次明确要求保存，才准备独立 brief。保存的 brief 不进入 registry。
- `refresh`：扫描配置的 source/query 覆盖区间，登记资源、证据、候选、逐项 coverage/cursor，并创建不可变报告；绝不修改稳定资源组合。
- `review`：只评审已登记且适合评审的候选。允许重新打开已登记的一手来源做最小定向复核，但禁止广泛发现；意外发现的新资料只能留作后续 observation。

若模式不明确，先用一句话确认。日历提醒、报告命名、bootstrap 窗口和决策数量都属于消费配置，不作为中央前置条件。

## 按需读取

- 普通 `research`：读取 [evidence-and-ranking.md](references/evidence-and-ranking.md)。需要登记身份、版本或关系时，再读取 [resource-model.md](references/resource-model.md)。
- `refresh` 或 `review`：读取 [resource-model.md](references/resource-model.md)、[evidence-and-ranking.md](references/evidence-and-ranking.md) 和 [registry-and-publishing.md](references/registry-and-publishing.md)。
- 任何 registry、报告、brief、portfolio 或 progress 写入前：必须读取 [registry-and-publishing.md](references/registry-and-publishing.md)。

## 公共流程

1. 明确研究问题、范围、截止点和模式。只启用仍有效且适用于本次范围的 overlay，并在结果中列出它们。
2. 由 Agent 使用适合的搜索与阅读工具收集证据。不要把搜索摘要、排行榜、star 数或“官方”标签当作已核验结论。
3. 由 Agent 判断 claim、来源角色、身份关系、硬门槛、冲突、信息增量、持久性、成本与排序。不要让确定性脚本猜语义。
4. `refresh/review` 先运行 `verify`。独立 `research-brief` 不读取 registry，由 `prepare` 直接完成 context、依赖和 journal 前检。存在未完成 journal 时停止新操作，只能先 `recover`。
5. 将完成语义判断的 proposal 交给 `scripts/resource_planning.py prepare`。检查其 decision units、目标文件与 slot、动作、计数/预算变化、需保留状态、完整 diff、`preview_digest` 和 `txn_id`。
6. 在对话中展示完整预览。写入必须取得用户对本次精确预览的自然语言确认；`review` 必须逐项确认 decision units。
7. 仅为同一 `operation_kind + txn_id + preview_digest + decision units` 创建 execution envelope，再运行 `publish`。发现任何漂移时重新 prepare 和确认，不复用旧确认。
8. 发布后再次 `verify`。Git stage、commit、push，以及付费或私有网络访问均是独立授权，不属于本 Skill 的发布事务。

## 不可突破的边界

- 无有效受管上下文时，只进行用户主题驱动、纯对话、零写入的 `research`；不猜配置、路径、来源或期限。
- `research` 不自动入池；`refresh` 不产生 `approved`/`applied`；`review` 不自动启动学习，也不修改 Lesson、Checkpoint 或 mastery。
- 不自动合并仅标题或语义相似的资源；标为 `possible_duplicate` 并交给 Agent/用户判断。
- coverage 局部失败时明确报告 `blocked`，且不推进该 scope 的 cursor；不得宣称全局无更新。
- 每次 `refresh` 都逐项列出配置中的全部 source/query；未选或禁用项显式记为 `skipped`，不能靠省略隐藏失败。
- 历史报告不可回写。不要制造 Changelog、月评日志或通用进度投影；只写配置和精确预览声明的必要目标。
- 课程与进度 adapter 只允许修改 decision unit 所绑定的同 module、action 与 `target_slot`。消费文档必须预置中央固定的 `resource-slot` 标记；`add` 也不例外。缺少标记时只报告阻塞并保留零写预览，不猜插入位置。
- 不手写稳定 ID、状态投影、cursor merge、digest 或多文件事务；使用确定性工具。不要使用或发明 `--yes`、`--force`、跳过 CAS 等绕过方式。
- 恢复仅按 journal 中可证明的 before/after 状态机械完成或回滚。遇到第三态目标或 journal 篡改时停止并报告人工冲突。

## 与其他 Skill 的边界

本 Skill 只研究与治理资料组合。资料晋级不等于开始学习；需要教学时在发布完成后由用户另行调用 `guide-learning`。卡片生成、英语反馈和学习对话归档也不由本 Skill 自动触发。
