# Registry and publishing

本文件拥有受管配置、registry、cursor、报告、预览、CAS 与恢复合同。

## 目录

1. 消费配置与受管上下文
2. 操作隔离
3. Registry、cursor 与 legacy
4. Prepare 与确认
5. Publish 与 recover
6. 路径和授权边界
7. 工具接口
8. Proposal 与 execution envelope

## 1. 消费配置与受管上下文

消费仓库使用：

- `.agent-skills.json` 选择 Skill/host 并引用配置；
- `.agent-skills-config/repository.json` 保存公共仓库事实索引；
- `.agent-skills-config/resource-planning.json` 保存本 Skill 的 source/query、module/adapter、overlay、storage 和偏好。

`repository.json` 使用 `agent-skills.repository/v1`；Skill 配置使用 `agent-skills.resource-planning/v1` 且 `skill` 必须为 `resource-planning`。未知字段、重复 ID、绝对/逃逸路径、任意 prompt、命令、selector、凭据、token 或 approval 均应拒绝。

结构化 `sources[]` 与 `queries[]` 是静态扫描定义的唯一机器事实源。动态 cursor、candidate、run、last seen 和裁决只在 registry。模块 portfolio 拥有稳定课程内容；README、订阅清单和报告只是人类投影，不能竞争机器事实源。

配置通过 `fact_refs` 引用 repository facts，不复制正文。Overlay 有 ID、fact 引用、scope、优先级与有效期，只影响相关性排序。Module 声明 portfolio、可选 progress projection 和中央白名单 adapter；配置不能注入解析代码。

中央脚本暴露纯函数：

```python
validate_materialized_context(repository_config, skill_config)
```

它只做 schema 和引用校验，返回 JSON 可序列化的 `context`、`tracked_files`、`tracked_collections`、`write_paths`；不读取文件、不调用 Git/网络。Materializer 负责验证 tracked regular file、collection、gitlink 和链接边界，把 collection 中实际 Git-tracked 的 regular members 展开进 wrapper 的 `tracked_files`，并生成 `.agent-skills-context.json`。运行时只读取这份明确成员白名单，不遍历 collection，也不自行调用 Git；同目录的未跟踪文件保持不可见。

共享 materializer 还拒绝 write path 与 consumer/repository/Skill config、显式 tracked fact file 或任何本次 materialized Skill 根目录相等或互为祖先。Collection 是否允许某 Skill 同时作为 inventory 与输出根，由该 Skill 自己声明；resource-planning 的 fact input/collection 与所有 registry、report、brief、journal、portfolio、progress 写面必须完全分离。

无有效 wrapper 时，退化为纯对话、零写入 research。

## 2. 操作隔离

- `research-brief`：只创建用户明确授权的独立 brief；不读写 registry 或历史报告，不进入候选池。它由 `prepare` 独立完成 context、依赖与 journal 前检，不以 registry 型 `verify` 为前置条件。
- `refresh`：创建一份不可变报告，并最后替换 registry；可写 resource/revision、claim/evidence、candidate 的 `draft/blocked/qualified` 事件、run、coverage 和成功 cursor；不得写 `approved/applied`。
- `review`：不修改报告。先写实际变化的 portfolio 与必要 progress projection，registry 最后。每门课程的写入必须与同一 `module_id + target_slot + action` 的 decision unit 精确绑定；apply/retire 各恰有一个 portfolio 目标，可选至多一个 progress 目标。Replace 的新旧两侧都必须位于同一 module/slot，旧侧还必须绑定到本次 replacement decision。Add/annotate/replace 新侧在同一受确认事务中记录 `approved -> applied`；registry-only defer/reject/supersede 写相应 outcome，且已 applied candidate 不得直接 supersede；retire 使旧侧进入 `stale`。

三种 operation 不得用同一 proposal 组合，也不得自动串联。

## 3. Registry、cursor 与 legacy

每个消费仓库只有一个 `agent-skills.resource-registry/v1` registry。它保存 resource/revision、claim/evidence、candidate/events/current projection、逐 scope cursor 和不可变 run 摘要。所有 current state 必须可由 event reducer 重建。

Refresh run 内保留每个 source/query 的 `covered | no-hit | blocked | skipped`。只有完整成功的 `covered/no-hit` 更新 cursor；失败或跳过保持原 cursor。尚无 cursor 的每个新 scope 独立使用用户窗口，或配置明确给出的 bootstrap 天数；中央核心不暗设天数。用户窗口优先。

每次 refresh 的 coverage key 集合必须与本次配置中的全部 source/query 完全一致：未启用或未选择的 scope 也要显式写为 `skipped`，失败 scope 写为 `blocked` 且不得推进 cursor。候选中的每条 key claim 都必须有直接的、非 discovery 证据支持；属于规范性主张的 claim group 还必须具有规范 primary support，不能由一条强证据替其他 claim 兜底。

Legacy 报告保持原字节：不补 manifest、不追加状态、不自动转 backlog。首次接管只提取可证明身份、revision、来源和保守重复提示；更早覆盖标为未知。新 refresh 报告必须 create-only，且不得覆盖任何历史路径。

## 4. Prepare 与确认

Agent 先完成全部语义判断，再提交严格 proposal。`prepare` 在仓库内零写入地：

1. 校验受管 context、registry 和 reducer 投影；
2. 规范化精确 native identity，生成稳定 resource/candidate/event ID；
3. 应用合法事件与逐 scope cursor 规则；
4. 生成所有 after bytes，registry generation 和报告/run 引用；
5. 捕获 context、配置/adapter、事实依赖和目标 before 摘要；
6. 生成逐文件 unified diff、排序后的 decision units、`preview_digest` 和 `txn_id`。

两个中央 adapter 共用固定、不可执行的 slot 协议：`<!-- resource-slot:<target_slot>:start -->` 到对应 `end`。工具只允许改变被本次 decision 精确授权的 slot；slot 的集合、顺序、边界外字节和 `<!-- resource-state:{...} -->` 中受保护学习状态必须保持。Add 同样要求消费仓库预先提供空 slot；缺少标记、标记重复/嵌套或状态不能证明保持时只能 blocked/零写入，不能猜测插入位置。Problem adapter 复用同一 parser，且不允许 progress projection。

预览列出：每个 decision unit、目标文件/slot、`add | replace | annotate | retire`、计数/预算变化、需保留的学习状态以及完整 diff。所有 timestamp、actor、理由和 event 都必须在 prepare 输入中确定；publish 不得追加。

用户确认后创建 execution envelope，精确绑定 operation、txn、preview digest 与排序后的 decision units。它不是长期授权。任一依赖/目标漂移都要求重新 prepare 与确认。

## 5. Publish 与 recover

Publish 顺序固定：

- research-brief：brief；
- refresh：不可变报告，registry 最后；
- review：portfolio、必要 progress projection，registry 最后。

Publish 先重算计划完整性和全量 CAS，再在配置的 journal 路径以 exclusive create 建立事务。Journal 保存 plan、精确 before/after bytes、摘要、phase 和已完成替换集合。每个目标替换前再次做 CAS；写完全部目标后执行 schema、event reducer、报告不可变性和 adapter postcondition 检查。成功后删除 journal。

所有 registry 已登记的历史报告都属于 prepare 依赖和 CAS 面；prepare、publish 与 recover 的最终 postcondition 都必须证明报告字节未漂移。Registry 仍须最后写入，避免报告尚未落盘时提前公布 run。

新 publish 遇到 journal 必须停止。Recover 只允许：

- 全部目标为 after：重验 journal、after digest 和 postcondition，成功后完成收尾；
- 可证明的 before/after 混合：按替换逆序恢复全部 before；
- 任一目标为第三态或 journal 被篡改：停止并报告人工冲突。

后验失败时保留 journal 并尝试机械回滚。业务撤销使用新 decision，不修改历史 event。

## 6. 路径和授权边界

所有路径必须是仓库内安全相对路径。拒绝绝对路径、`..`、符号链接、junction/reparse point、特殊文件、穿越受管范围和未授权目标。事实输入/collection 的 tracked 与 gitlink 状态由 materializer 保证；运行时以 wrapper allowlist、路径检查和 CAS 为准。

静态配置不授权联网、登录、付费、保存、覆盖、legacy 接管、晋级、发布、commit 或 push。工具不提供 `--yes`、`--force`、`--skip-cas` 或 `--accept-latest`。

## 7. 工具接口

脚本只使用 Python 标准库，不联网、不调用 subprocess/shell/Git：

```text
resource_planning.py verify  --repo ROOT --context WRAPPER --now ISO_TIME
resource_planning.py prepare --repo ROOT --context WRAPPER --proposal PROPOSAL [--plan-out OUTSIDE_REPO]
resource_planning.py publish --repo ROOT --context WRAPPER --plan PLAN --envelope ENVELOPE
resource_planning.py recover --repo ROOT --context WRAPPER
```

CLI 始终输出稳定 JSON。`prepare` 默认把完整 plan 输出到 stdout；若使用 `--plan-out`，目标必须在消费仓库外。调用方不要自行修改 prepare 产出的 plan。

## 8. Proposal 与 execution envelope

所有 proposal 使用：

```json
{
  "schema": "agent-skills.resource-proposal/v1",
  "operation_kind": "research-brief | refresh | review",
  "prepared_at": "带时区的 ISO-8601 时间",
  "dependencies": ["受管 tracked_files 中需要额外强调的相对路径"],
  "writes": [],
  "research|refresh|review": {}
}
```

只保留与 `operation_kind` 同名的 payload。`research` 为 `{brief_id, active_overlays}`，且 `writes` 恰有一个 `{path, role:"research-brief", after_text, decision_unit_ids:[]}`。

`refresh` 为：

```text
{run_id, active_overlays, coverage[], resources[], candidates[]}
coverage:  {scope_kind, scope_id, status, covered_from, covered_to, basis,
            cursor_after?, detail?}
resource:  {identity:{kind,value}, revision_key, title, canonical_locator,
            aliases[], modules[], relations[], claims[]}
relation:  {kind, target_identity:{kind,value}, target_revision_key?}
claim:     {text, status, scope, evidence[]}
evidence:  {locator, role, checked_at, direction, note?}
candidate: {identity, revision_key, module_id, action, target_slot, claim_refs[{text,scope}],
            preserve_learning_state[], review_after, state, reason}
```

Refresh 的 `writes` 恰有一个 report，字段为 `{path, role:"report", after_text, decision_unit_ids:[]}`；工具生成 decision IDs 与 snapshot header。`basis` 只允许 `user | cursor | bootstrap`。只有 `covered/no-hit` 提供 `cursor_after`，且必须等于 `covered_to`；`blocked/skipped` 禁止提供。Retire 不创建新的 refresh candidate，而是在 review 中作用于既有 `applied` mapping。

`coverage[]` 不得只列成功项：它必须逐一、且仅列出本次配置中的全部 source/query key；漏 source、漏 query、重复 key，或配置含 scope 时提交空 coverage，都应拒绝。

`review` 为 `{run_id, active_overlays, decisions[]}`。每条 decision 使用：

```text
{candidate_id, outcome, reason, count_change, budget_change,
 preserve_learning_state[], replaces_candidate_id?}
```

`outcome` 为 `apply | defer | reject | supersede | block | retire`；只有 replace 的 `apply` 提供 `replaces_candidate_id`。工具派生而非信任调用方提供的 `replaces_candidate_id`、`replaces_decision_unit_id` 与目标绑定。Portfolio/progress write 使用 `{path, role, after_text, module_id, action, decision_unit_ids[]}`，且 module、target slot、action 必须与 decision unit 精确一致。每个 `apply/retire` 恰好绑定一个 portfolio write，并可选至多一个合法 progress write；纯 registry 裁决必须零写入，不能伪造课程文件变化。

用户确认精确预览后，调用方创建而非长期保存以下 envelope：

```json
{
  "schema": "agent-skills.resource-execution/v1",
  "operation_kind": "与 plan 完全一致",
  "txn_id": "与 plan 完全一致",
  "preview_digest": "与 plan 完全一致",
  "decision_unit_ids": ["与 plan 排序后完全一致"],
  "authorized": true
}
```

它只表达 Agent 已在对话中取得的当次确认；工具不会把静态配置或旧 envelope 当作授权。
