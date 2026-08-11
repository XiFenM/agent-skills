# Resource model

本文件只定义身份、关系、claim、候选事件和不变量。证据质量判断见 `evidence-and-ranking.md`；持久化与事务见 `registry-and-publishing.md`。

## 1. 两层身份

- `work_id` 标识稳定作品或项目线。由工具从精确原生身份规范化：DOI、去版本号 arXiv ID、GitHub `owner/repo`、受命名空间约束的 native ID，或规范 URL。
- `revision_key` 标识具体 revision，例如 tag、commit、arXiv `vN`、出版/接收状态。没有可证明 revision 时使用 `unspecified`，不要猜版本。
- 标题、镜像 URL、板块、报告期、宣传名称和别名不产生新身份。
- 精确原生 ID、规范 URL或已登记 alias 可以自动归并。仅标题或语义相似时，保留独立资源并标记 `possible_duplicate`。

论文、代码、博客等不同作品不因主题相同而合并。使用以下有方向关系连接：

- `version_of`
- `updates`
- `successor_to`
- `complements`
- `conflicts_with`
- `possible_duplicate`

`replace` 是经用户确认的 portfolio 动作，不是资源天然关系。

## 2. Resource 与 claim

一个 resource revision 至少包含：

- 精确 identity 输入以及工具生成的 `work_id`；
- `revision_key`、标题、canonical locator、aliases；
- 一个或多个 module mapping；
- 可选 relations；
- 影响推荐或晋级的 claim。

每个 claim 独立记录：文本、事实状态、有效范围和 evidence。事实状态只允许：

- `verified`
- `qualified`
- `unverified`
- `conflict`

Evidence 记录 locator、来源角色、核验时间、直接支持/反驳方向和可选的简短定位说明。硬件、版本、配置或适用人群等 scope 不可省略成笼统“有效”。
候选进入 `qualified` 时，它引用的每个关键 claim 都必须是 `verified | qualified`，并各自至少有一条非 discovery 的直接支持证据；整组关键 claim 还必须至少有一个规范性一手来源锚点。任一关键 claim 为 `unverified | conflict`、只有搜索线索，或核验时间晚于本次 `prepared_at` 时都不得靠其他 claim 补回。

同一作品的新 release、接收、获奖或状态变化属于 revision/status 增量，不伪装成新作品。一个 resource 可映射多个 module，但 registry 只保存一次。

## 3. Candidate 与 decision unit

Candidate 是一个原子 portfolio 决策单元，身份由 resource revision、module、动作和目标 slot 共同确定。一个资料若需要两个独立课程编辑动作，应建立两个 candidate/decision unit；不要用一条候选隐藏多个动作。

允许的 portfolio 动作为 `add | annotate | replace | retire`。Candidate 保存：

- `candidate_id` 与 `decision_unit_id`（均由工具生成）；
- resource revision、module、动作、目标 slot，以及该决策实际依赖的 key claim IDs；
- `review_after`、来源 run、需保留的学习状态字段；
- 按顺序追加的不可变 events；
- `current_state`，它必须等于 `reduce(events)`。

`ready` 仅由 `review_after <= now` 派生；`qualified-deferred` 仅是当轮展示标签，二者都不是持久状态。

## 4. 状态与事件

首个事件必须进入 `draft`。后续只允许：

```text
draft     -> blocked | qualified
qualified -> approved | blocked | deferred | rejected | superseded
blocked   -> draft | qualified | rejected | superseded
deferred  -> qualified | blocked | rejected | superseded
approved  -> applied
applied   -> stale | superseded
```

复核失败可以从 `qualified` 或 `deferred` 进入 `blocked`。`retire` 使旧的 `applied` 进入 `stale`；`replace` 使新侧 `qualified -> approved -> applied`，旧侧 `applied -> superseded`。

每个 event 包含严格递增 sequence、`from_state`、`to_state`、时间、run、operation 和理由。`approved` event 还绑定一次性的 `preview_digest`；它只可用于同一事务的完整回滚后重试或成功后的幂等检查。CAS 漂移、目标变化或新事务都使其失效。后续事务只为本次新增的 `approved` event 绑定新 digest；历史 approval 保留原 digest，不能被新预览改写，也不能反过来阻塞后续 refresh/review。

Registry 验证必须从头归约全部 events，并同时检查 sequence、`from_state` 和 `current_state`。不一致时所有入口停止；不得在 event 与投影间择一猜测。

## 5. Registry 不变量

- 每个 `work_id + revision_key` 唯一；aliases 不得跨作品冲突。
- `candidate_id`、`decision_unit_id` 和 `event_id` 全局唯一且可重算。
- Events 只追加，不改写历史；后续撤销使用新的补偿 decision。
- `approved != applied`。只有课程编辑集全部成功并通过后验验证，才可让新侧进入 `applied`。
- `refresh` 最终事件不得为 `approved` 或 `applied`。
- 报告不拥有 current state、cursor 或评审结果；不得从报告反推 registry。
- 排序和软数量目标不改变资格状态，也不能静默丢弃通过门槛的候选。
