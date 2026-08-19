# Practice, review, and mastery

在设计正式练习、创建验收工件、Review 学习者产物、提供 material assistance 或判断 mastery 时读取
本参考。不要把本参考用于关键节点中的轻量复述或普通一次答疑。

## Contents

1. [Enter practice only for an evidence gap](#enter-practice-only-for-an-evidence-gap)
2. [Present the six-block contract](#present-the-six-block-contract)
3. [Persist and revise the contract](#persist-and-revise-the-contract)
4. [Apply ownership and tests-first](#apply-ownership-and-tests-first)
5. [Provide help without silent takeover](#provide-help-without-silent-takeover)
6. [Review through stable findings](#review-through-stable-findings)
7. [Require minimum mastery evidence](#require-minimum-mastery-evidence)
8. [Project and close the gate](#project-and-close-the-gate)

## Enter practice only for an evidence gap

先完成关键节点微循环和跨节点综合验收。把现有 evidence 映射到每个目标的 required mastery 维度。

- 所有 required 维度已有最低充分证据时，跳过正式练习并进入 mastery gate。
- 缺少独立实践、变式或实证证据时，设计能补足这些缺口的最小练习。
- 不要为了课程形式安排 reproduction、boundary、transfer、evaluation 的完整阶梯；只选能区分理解与
  记忆的最低充分组合。
- 不要在练习中引入无关复杂度、新的心智模型或隐藏要求。若练习需要独立能力，提议拆分 Lesson。
- 对非代码主题，使用可观察工件，例如证明、推导、案例分析、设计、实验、批评或决策说明。

正式练习开始前停止继续教学，一次性展示完整契约并请求接受。用户接受前不要创建验收工件或改变
状态，既有只读调查除外。

## Present the six-block contract

按以下顺序向学习者展示：

1. **为什么做**：列出目标 ID、缺失的 mastery 维度和现有证据缺口。
2. **你交付什么**：说明任务和 learner-owned 核心产物。
3. **怎样算通过**：列出带 ID 的可观察 acceptance，以及对应测试、rubric、命令或其他 evidence
   method。披露全部 required 行为和边界，不必展开每个 fixture 的内部实现。
4. **文件边界**：分别列出“你写”“我维护”“我只读”“本次不动”。
5. **帮助如何影响证据**：允许自然语言求助；说明 material hint 或 Agent 接管只影响对应范围，之后用
   无提示同构新变式恢复独立证据。
6. **非目标与完成门槛**：把 optional 单列；说明 required acceptance 必须通过，映射到它们或 required
   mastery 的 blocking／major finding 必须关闭，并满足已声明的解释、变式或实证要求。

受管 context 若列出 `practice-contracts`、`practice-artifacts`、`practice-validation` 或
`practice-records`，这些只是候选位置和机械上限。它们不能预先指定 learner-owned／agent-owned，不能
替代本节的 actual path、受限 pattern、允许操作、revision、digest 与接受事件，也不能把 optional 变成
required。未在本次六块契约中逐项授权的路径保持只读或 excluded。

使用以下用户可见标签：

| 标签 | 默认含义 |
| --- | --- |
| 你写（learner-owned） | 学习者创建或修改；Agent 可读、运行和 Review，不得代改 |
| 我维护（agent-owned） | Agent 可在契约内创建、修复、运行和记录，不逐文件重复确认 |
| 我只读（read-only） | Agent 可检查，不创建或修改 |
| 本次不动（excluded） | 不属于本契约；纳入前须重新确认 |

不要让 optional 混入 required acceptance。不要用“之后再看”掩盖当前 gate，也不要把契约外工程润色
变成结课条件。

## Persist and revise the contract

使用以下逻辑 schema；适配到仓库既有格式，不要求固定 Markdown 模板：

```yaml
practice:
  id: <stable practice ID>
  revision: <monotonically increasing integer starting at 1>
  digest: <sha256:lowercase-hex>
  targets:
    - objective_id: <Lesson objective or independent Session target>
      missing_dimensions: [<conceptual | practical | empirical>]
      evidence_gap: <short observable gap>
  task: <one concise task statement>
  deliverables:
    - artifact: <relative path, restricted pattern, or logical artifact ID>
      outcome: <what the learner must produce>
  acceptance:
    - id: <stable acceptance ID>
      criterion: <observable required behavior or evidence>
      evidence_method: <test, rubric, command, comparison, explanation, or experiment>
  scope:
    learner_owned:
      - artifact: <relative path, restricted pattern, or logical artifact ID>
        operations: [<read | create | modify | run | record>]
    agent_owned:
      - artifact: <relative path, restricted pattern, or logical artifact ID>
        operations: [<read | create | modify | run | record>]
    read_only:
      - artifact: <relative path, restricted pattern, or logical artifact ID>
        operations: [read]
    excluded:
      - artifact: <relative path, restricted pattern, or logical artifact ID>
        operations: []
  optional:
    - id: <stable optional ID>
      criterion: <observable non-gating extension>
      evidence_method: <optional evidence method>
  acceptance_event:
    event_ref: <the event that records explicit acceptance>
    revision: <accepted revision>
    digest: <accepted digest>
```

让类别决定 owner；让 operations 只取 `read`、`create`、`modify`、`run`、`record` 中的最小集合。
使用相对路径、受限 pattern 或逻辑工件 ID，不使用宽泛目录作为隐式授权。

把所有 required 行为、代表边界、验证和完成条件合并进 `acceptance[]`，不要另建 must-satisfy、case
matrix、validation 和 completion-definition 四套重复字段。需要解释、独立变式或实证预测时，把它们
建成 observable acceptance。完成 gate 由全部 required acceptance、映射的 required blocking／major
finding 和既定 required mastery 维度唯一推导。

计算 digest 时仅包含规范化后的 `id`、`targets`、`task`、`deliverables`、`acceptance`、`scope` 和
`optional`：对 mapping 使用稳定 key 顺序，保留具有语义的数组顺序，统一换行并去除纯展示空白，然后
对 UTF-8 内容计算 SHA-256。不要把 `revision`、digest 自身或 acceptance event 纳入 digest。

让 revision 从 1 开始单调递增。目标、交付、required acceptance、scope、optional 或由其推导的 gate
发生语义变化时：

1. 更新规范化内容；
2. 递增 revision；
3. 重新计算 digest；
4. 展示变化并重新取得接受；
5. 绑定新的 revision 与 digest，不沿用旧 acceptance event。

纯排版变化不产生新 revision。发现原契约存在歧义时，把修订标为 contract clarification，不把旧歧义
归责为 learner finding；若澄清改变 gate，仍须重新接受。

## Apply ownership and tests-first

默认让学习者拥有核心工件，让 Agent 拥有例行验收基础设施并主动建立测试驱动循环。只有测试设计、
fixture 设计或验证工具本身是明确学习目标时，才把相应工件列为 learner-owned；不要把“学习者写测试”
当作代码练习的默认附加目标。

代码练习按以下顺序执行：

1. 接受行为、边界、交付和 scope 契约。
2. 在已授权的 Agent-owned 路径建立最小可读验收套件；测试公开行为、不变量、边界和必要错误行为，
   不编码或泄露内部解法。
3. 运行收集和适当验证。只有目标行为确实新增或待修、失败来自预期缺口，而且环境、fixture、harness
   和已有行为均正常时，才把失败称为 expected red。
4. 向学习者交付测试路径、精确运行方法和简短 case map；不要要求第二次契约确认。
5. 让学习者实现并从 red 推进到 green。若 required 行为缺覆盖或 Agent 测试错误，Agent 先在授权范围
   修复验收工件，再报告真实差距。

既有行为已经正确、无法产生有意义 expected red，或主题不适合可执行测试时，使用基线、rubric、对照、
证明检查或其他可观察 evidence，并明确 expected red 不适用。

对 measurement-only 或 benchmark 练习，默认按以下职责执行：

- 学习者在看到结果前给出有机制依据、可被结果推翻的预测，并在结果出现后解释证据支持、不支持什么；
- Agent 设计并维护实验方法与 harness，决定与 claim 相称的 warm-up、同步、重复次数、运行顺序、资源
  配置、工作量口径、控制变量、主要指标、结果 schema，以及支持／否定／证据不足的事前判据；
- Agent 在运行前用简短语言说明设置思路、必要性和预期投入，不要求学习者反向猜出方法参数；
- 方法保持最低充分。除非目标 claim 或预期噪声确实需要，不自动加入统计检验、置信区间、profiler、
  大规模 sweep 或固定性能阈值；
- 把功能正确性放在独立证据中，不断言某个配置必然最快，也不把预测与结果不一致视为实践失败；
- 只有实验设计、harness 实现、参数校验或统计推断本身是明确学习目标时，才在契约中把相应部分列为
  learner-owned 和 required。方法若扩大成本、依赖、硬件使用或目标范围，先修订契约并取得确认。

Agent-owned 测试、rubric、fixture 和记录不是学习者核心实现。新增这些工件不授权 Agent 修改
learner-owned 内容。

## Provide help without silent takeover

在学习者独立尝试期间先只报告契约、验证结果和证据差距。不要因一次失败、沉默或耗时较长自动提高
帮助程度。学习者自然表达卡住或主动求助后，先用一句最小诊断区分概念、执行、环境或精力问题，再按
最低必要程度提供支持：

- 重述不变量并帮助定位缺口；
- 指向相关概念、来源或边界；
- 给表面不同的较小类比，或缩成一个小门动作；
- 给伪代码、接口骨架或结构脚手架，同时保留要验收的核心选择；
- 仅在用户明确要求时完整示范或接管。

不要向用户暴露提示编号，也不要要求固定求助措辞。用户可以要求更强帮助，也可以随时恢复独立尝试。
聊天中展示答案不自动授权写入 learner-owned 文件。

按实际透露内容判断 material assistance。揭示关键分解、算法、核心公式、伪代码、具体修复或完整解法
会改变独立证据；重述契约、报告失败证据或修复 Agent 自身工件不会。

对每个受影响范围覆盖保存一次：

```yaml
material_assistance:
  - highest_disclosure: <实际透露到的最高实质程度，用自然语言描述>
    affected_scope: [<objective, acceptance, or artifact reference>]
    agent_wrote_learner_core: <true | false>
```

合并重叠范围并保留最高实质程度。不要保存层号、轮数、提示全文或逐轮时间线。只有 Agent 写入
learner-owned 核心工件时才把 `agent_wrote_learner_core` 设为 true；Agent 修自己的验收工件或记录不算。

撤销的只是受影响范围的独立实践 evidence。安排一个更小、表面不同但心智模型相同的新变式，在无
material assistance 下重新验证；把恢复 evidence 写入 mastery，不在 assistance 中重复。

## Review through stable findings

先检查接受的 contract revision 与 digest，再检查学习者产物和相称的仓库原生验证。按以下优先级
Review：

1. required acceptance 与概念一致性；
2. 边界、失败行为和证据可复现性；
3. clarity、maintainability 或 performance，但仅限它们已进入 required gate；
4. 契约外观察，明确保持 non-gating。

Review 的用户投影只包含：本轮结论与最小验证证据、新增或变化的 findings、最多三个 learner-owned
当前动作、Agent 自行处理的验收问题，以及契约外 observations。不要创建逐轮 Review 历史表。

每个 durable finding 只保存七类信息：

```yaml
finding:
  id: <stable finding ID>
  maps_to: [<objective and/or acceptance reference>]
  severity: <blocking | major | minor | suggestion>
  owner: <one current responsible party>
  status: <open | closed | deferred | dismissed>
  evidence:
    opened: <short expected-versus-observed proof and anchor>
    terminal: <verification evidence or defer/dismiss rationale; terminal states only>
  next_action: <one atomic action; open state only>
```

应用以下生命周期：

- 修改但尚未验证时保持 `open`；验证失败时更新 evidence 或 next action，不创建 `needs-more-work` 状态。
- 只有复验相关行为后才设为 `closed`，并保存最小 terminal evidence。
- `deferred` 或 `dismissed` 必须保存理由；进入终态后清空 next action。
- required blocking 或 major 若要 deferred，先让用户同意改变 gate 并修订契约。
- 由 `maps_to` 是否指向 required acceptance 或 required mastery 维度唯一推导 finding 是否 required。
- 契约外内容保持 observation；未经用户同意不得升级为 required finding。
- 同一根因只建一个 finding 并原地更新；不要保存按轮复制的表、完整日志或过程状态。

一轮可以登记并紧凑展示全部 findings，但只激活最多三个 learner-owned 当前动作。按 blocking、major
和依赖顺序选择；Checkpoint 只指向第一个可执行动作。Agent-owned 故障由 Agent 在授权内先处理，不
占学习者动作槽。minor 与 suggestion 默认不阻塞、不占槽。

所有 required blocking／major finding 关闭后停止正式 Review。不要因工程润色、optional extension
或新发现的契约外内容延长练习。

## Require minimum mastery evidence

在 Lesson 激活时对每个目标预先声明三个维度为 `required` 或 `not-required`。不要在结课时临时降低
标准，也不要在未授权时新增 required 维度。

使用以下默认选择作为起点，再按目标调整：

| Lesson 类型 | 概念 | 实践 | 实证 |
| --- | --- | --- | --- |
| 概念或源码理解 | required | 仅当目标包含独立设计、推导或操作时 required | 仅当目标主张真实运行、设备或版本行为时 required |
| 编码或实现 | required | required | 目标包含真实环境、设备或性能结论时 required |
| 实验或 benchmark | required | 仅当实验工件设计或实现属于目标时 required | required |

各维度的最低充分 evidence：

### Conceptual

- 学习者独立复述中心模型；
- 解释一个关键边界、反例或相似概念差异；
- 在未直接讲过的小型同构情境中完成条件变化、映射、诊断或迁移；
- 对版本敏感源码结论指出相应来源锚点。

### Practical

- 学习者拥有并完成契约内核心工件；
- Agent-owned 测试或 rubric 通过；
- required blocking／major finding 已关闭；
- 学习者解释一个重要验证用例；
- 完成同一心智模型下的无提示小型变式。

### Empirical

- 学习者在结果出现前给出并保存有机制依据的可证伪预测；
- Agent-owned 方法与 harness 明确环境、版本、输入、控制变量、测量边界和事前证据判据；
- Agent 选择的方法与结果能在声明条件下复现，并存在与目标相称的基线或受控比较；
- 学习者说明证据支持、不支持的结论和剩余不确定性；
- 性能实验另有独立正确性 evidence，且不会把同时变化的因素误作单一原因。

跨节点综合验收已经独立提供概念 evidence 时，直接复用。默认由 Agent 准备实验方法与 harness，学习者
负责预测、理解关键控制边界、按约定运行或观察运行，并解释结果；这可以满足 empirical，而 practical
为 `not-required`。只有实验设计或 harness 实现本身属于明确目标时才要求相应 learner-owned practical
evidence。不要保留 reflective 作为第四维度；高价值误解和修正属于过程记录，不能替代上述 evidence。

## Project and close the gate

在 Lesson mastery gate 向用户展示一行一个“目标 × required 维度”的矩阵：

| 目标 | 所需维度 | 最小 evidence 锚点 | 判断 |
| --- | --- | --- | --- |
| `<objective>` | `<conceptual, practical, or empirical>` | `<answer, artifact, check, variation, or experiment reference>` | `充分` 或 `不足` |

随后只列：

- required blocking／major 未关闭数及 ID；
- material assistance 影响范围是否已由新变式恢复；
- nonblocking minor、suggestion 和 optional 余项；
- 关闭或继续的建议。

对已授权 Lesson，等待用户确认后才一次写入 final mastery，并把当段唯一 Session event 标为 closure；
把 Checkpoint 移到 Lesson 边界，唯一下一动作写成等待下一 Lesson 授权。真正终结且无恢复任务时移除
Checkpoint，不伪造下一动作。不要自动启动下一 Lesson。

对独立 Session，只保存会话级 evidence、练习工件引用和带 `practice-closed` 标记的唯一 event；不要
写 final Lesson mastery。存在后续恢复任务时才保留或覆盖 Checkpoint，真正终结时移除。用户需要长期
mastery 时，先取得创建 Lesson 或并入 Course 的授权。
