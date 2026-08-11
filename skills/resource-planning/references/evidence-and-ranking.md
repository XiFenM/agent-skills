# Evidence and ranking

本文件只指导 Agent 做证据与价值判断，不定义 registry schema 或发布机制。

## 1. 从问题与范围开始

先写清：用户要解决的问题、受众/水平、技术或时间范围、成本边界、现有 portfolio 以及本次生效的 overlay。Overlay 只调整相关性排序，不覆盖长期目标，也不扩大已配置 source/query 范围。

`research` 可以按用户问题广泛发现；`refresh` 只扫描选中的配置 scope；`review` 禁止广泛发现，只能为已登记候选做必要的最小定向复核。复核中意外发现的新资料仅记为后续 observation。

## 2. 区分来源角色

同一来源可以对不同 claim 承担不同角色；“官方”不是整篇通行证。

- **discovery/index**：搜索结果、榜单、聚合页、Trending、新闻或社交线索。只能帮助发现。
- **normative primary**：论文原文、标准、正式文档、release、项目原始记录。用来锚定身份、版本和规范性 claim。
- **first-party engineering observation**：作者或项目方的工程说明、benchmark、案例。保留其配置和利益关系范围。
- **independent validation**：独立复现、对比、勘误或外部采用证据。用于检验可迁移性与冲突。
- **teaching/review**：教程、课程、综述或解释材料。用于评估教学质量，不能替代其引用的一手事实。

记录事件/发布/状态变化时间、实际核验时间和 validity scope。易变的 API、支持状态、最新 benchmark 和作者归属在推荐或晋级时最小复核；固定版本的历史资料不因变旧自动失效。

## 3. 先过硬门槛

以下任一项无法满足时，不进入价值排序；标记 `blocked`、`unverified` 或延后：

1. 可证明的作品身份与 revision；
2. 至少一个与关键 claim 直接相关的一手锚点；
3. 对 refresh 而言，窗口内事件或明确的更新/后继关系；
4. 与配置 module、事实范围和允许动作匹配；
5. 有技术实质，而不只是宣传或热度；
6. 完成精确重复、revision、后继和可能重复判断；
7. 每个关键 claim 都是 `verified | qualified`，有逐项 scope 和至少一条非 discovery 的直接支持证据；整组还至少有一个规范性一手锚点，核验时间不晚于本次 prepare；
8. 未隐藏会改变结论的冲突。

不要用总分、yes 票数、star 数或来源名气补回未过硬门槛的候选。

## 4. 再做多维排序

对过门槛的候选分别说明，不合并成伪精确总分：

- **目标相关性**：对当前长期目标与有效 overlay 的直接贡献；
- **信息增量**：相对现有 portfolio 带来的新能力、修正、替代价值；
- **持久性**：概念/机制是否稳定，维护和过期风险如何；
- **学习与维护成本**：前置知识、篇幅、运行成本、更新负担和机会成本。

给出理由、主要不确定性和冲突。一个资料跨多个 module 仍保持同一 resource，只创建必要的独立 decision units。

## 5. 数量是注意力目标，不是质量阈值

消费配置可以给出 `decision_unit_soft_target`。它只控制本轮人类决策负担：

- 0 个合格项完全正常；
- 强替代、紧密成组或同分边界可以超过目标；
- 所有过门槛但未进入本轮的候选必须展示为 `qualified-deferred` 并说明原因；
- 不得以“Top N”为由静默丢弃强候选。

## 6. Coverage 表述

每个 source/query scope 独立记录：

- `covered`：完整执行且有可登记增量；
- `no-hit`：完整执行且明确无命中；
- `blocked`：因网络、登录、页面、权限或验证失败未完整覆盖；
- `skipped`：本轮明确未选择执行。

每次 refresh 必须逐项列出配置中的全部 source/query；禁用或本轮未选择的 scope 也显式记录 `skipped`，不能通过省略制造“已完成”印象。局部 `blocked` 不能表述为全局无更新。只有 `covered` 或 `no-hit` 可以建立/推进该 scope 的 cursor；其他 scope 的成功不替失败 scope 背书。
