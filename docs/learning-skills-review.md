# 学习类 Skill 合并升级决策与评审记录

本文记录学习类 Skill 在质量评估与合并升级阶段的已确认决策、中央实现和后续迁移边界。
用户已授权并完成 D23 定义的中央 C0–C3；因此本文所述 `guide-learning`、`study-log`、catalog 和中央验证状态已经落地。远端发布、消费仓库修改和 M0–M5 仍只是已确认设计，尚未获迁移授权或执行。

## 当前范围

本轮评审涵盖以下 6 个自创 Skill：

- `english-coach`
- `learn-by-practice`
- `memo-cards`
- `resource-planning`
- `study-companion`
- `study-log`

## 已确认决策（2026-08-10）

### D1：三个下游或上游能力继续保持独立

以下 Skill 不并入主学习流程：

- `english-coach`：继续负责技术学习中的英语反馈，以及学习后的英语专项复盘。
- `memo-cards`：继续负责把成熟的英语或技术学习素材转换为墨墨记忆卡导入数据。
- `resource-planning`：继续负责学习资料周更、候选治理和经用户确认后的课程晋级。

后续仍可分别提高它们的通用性、触发精度和质量，但不改变其独立 Skill 的定位。

### D2：学习对话提取能力统一归 `study-log`

`study-log` 现有的对话提取能力，需要与 `learn-by-practice` 中的学习记录／对话提取能力合并统一。
完成升级后：

- `study-log` 是学习对话发现、选择、清洗、边界截取和提取能力的唯一归属；
- 合并时保留两边已有的有效能力，包括多客户端发现、日期或语义边界选择、可见对话清洗、来源信息、完整性校验和现有测试覆盖；
- `learn-by-practice` 不再自行保存对话提取脚本或对话提取流程；
- `learn-by-practice` 如需学习记录或对话材料，应调用 `study-log` 或消费其产物，而不是维护第二套实现。

两种输出模式的触发、默认路径、覆盖、Git 与保留政策在 D16 确定；自然语言路由、共享内核、仓库外
私有根配置、安全写入和脚本／测试迁移边界在 D22 确定，并已在 C1–C2 实现和验证。

### D3：`study-companion` 与 `learn-by-practice` 合并升级

`study-companion` 与 `learn-by-practice` 不再以两套互相竞争的主学习流程长期并存。
目标是吸收双方有效能力，形成职责统一、状态一致、可支持不同学习场景的新学习流程。

流程差异、目标行为和实现设计已经由 D4–D23 逐项研究并经用户确认：

- 合并后的唯一主 Skill 已在 D17 定名为 `guide-learning`，显示名为 “Guided Learning / 学习带练”；
- 精简主入口与按需 references 的目标目录已经在 D18 确定；最小状态、练习、finding 与 mastery schema
  已在 D20–D21 确定，并已落实到 `guide-learning` 的主入口与一级 references；
- 教学微循环已在 D4 确定，检查题设计与纠错规则已在 D12 确定；关键节点场景已纳入 D23 的中央验证；
- 微动作、综合验收与正式练习的衔接已在 D5 确定，提示梯度与 mastery 证据已在 D12–D13 确定；
  最小练习契约、finding 和结课证据投影已在 D21 确定；
- PlanA 的事实源角色和“不创建第二套通用档案树”已在 D6 确定；现有文件的一义映射与分阶段精简迁移
  已在 D15、D19–D20 确定；
- Session、Lesson、Program、mastery 和文章状态的分离已在 D6 确定，稀疏写入时机和所有权已在 D14
  确定；具体逻辑 schema 已在 D20 确定；
- PlanA 事实源映射与消费仓库适配职责已在 D15 确定；旧文件的分阶段迁移、兼容窗口和退役顺序已在
  D19 确定。中央兼容状态已完成；PlanA 的具体变更仍须等待 M4 的独立迁移授权。

### D4：教学微循环采用“先讲关键节点，再检查理解”

合并后的学习流程不再把“先问后讲”作为默认顺序。对于学习者尚未接触、无法从已有知识推导的
知识性问题，讲解前提问容易退化为猜测；猜对或猜错都不能稳定证明理解，还会增加不必要的挫败感。

在陪学 Session 或持久 Course 中，每个结构化学习主题先给一张很短的全局图，再对其中每个关键节点
执行以下微循环：

```text
讲：详细讲解当前关键节点
  ↓
挖：留出追问与必要扩展
  ↓
探：针对刚讲过的内容提出理解检查问题
  ↓
答：学习者作答，暴露当前理解
  ↓
讲：只补充当前理解与目标之间的差值
  ↓
判断：理解有误或不完整时，回到“探”继续深究；理解无误时进入“做”
  ↓
做：完成一次轻量的复述、举例、自测或推导工件
  ↓
验：即时纠正并判断是否推进到下一个关键节点
```

这里的“探”是**讲解后的理解诊断**，不是要求学习者猜测尚未教授的事实。检查问题应能依据刚完成的
讲解或已经确认的前置知识作答。这里的“做”是比后续正式练习更轻量的学习工件，用于巩固当前节点，
不替代 D5、D7、D21 定义的正式练习契约、作品评审和 mastery gate。

一次答疑只选用解决当前问题所需的讲解、追问或轻量检查，不强制生成全局图，也不强制跑完整微循环。

循环覆盖所有关键节点后，再合成完整心智模型并进入综合验收；是否继续进入正式练习，按 D5 的证据
缺口判断。完整案例的要求作为整节课的累计覆盖门槛，不要求在一次长篇讲解中完成。

### D5：综合验收后按证据缺口进入正式练习

“轻量工件 → 正式练习 → mastery”不是每节课都必须完整执行的直线。所有结构化 lesson 都应在关键
节点微循环结束后完成一次跨节点综合验收，但只有学习目标仍缺少实践、迁移或实证证据时，才进入正式
练习：

```text
完成所有关键节点微循环
  ↓
合成完整心智模型
  ↓
完成一次跨节点综合验收
  ↓
判断本课目标所需证据是否充分
  ├─ 充分：进入 mastery gate
  └─ 不充分：最小正式练习 → review → 修订 → 验证 → mastery gate
```

正式练习开始前，Agent 先一次性展示完整的最小契约，让学习者独立完成。只有学习者明确表达卡住、
希望降低难度或主动求助时，才重新进入微动作和渐进提示；验证发现问题时先报告证据和差距，不自动
接管学习过程。
综合验收题型、提示梯度和 mastery 证据已在 D12–D13 确定；最小契约字段、finding 生命周期和结课证据
投影已在 D21 确定。测试与作品的默认所有权、契约授权和 Review 停止范围已在 D7 确定。

Mastery 分三个可独立记录的维度，并由 lesson 目标预先声明需要哪些维度：

- **概念已掌握**：能用自己的话讲清中心模型和关键边界，并预测关键条件变化；
- **实践已验证**：核心工件通过验收，能解释为何成立，并完成一个不靠照抄的变式；
- **实证已验证**：真实运行或实验可以复现，并能说明证据支持与不能支持的结论。

理解源码架构不自动声称运行能力；实现类目标需要概念和实践证据；性能、设备行为等经验性结论需要
实证证据。文章、课程档案和过程记录的职责已在 D7 确定；各 mastery 维度的最低证据和适用范围已在
D13 确定。

### D6：采用三种运行范围、三层状态和自然语言控制

合并后的通用学习 Skill 按用户当轮意图选择最窄的运行范围：

- **一次答疑**：使用教学式解释和必要的轻量理解检查，但不建立持久档案、不锁定学习会话、不修改
  学习状态，也不自动安排后续课程；
- **陪学 Session**：用户明确表达开始或继续一段学习时，执行快速恢复、D4 微循环、自然语言暂停与
  收尾，并保存最小恢复信息；
- **持久 Course**：用户明确开展跨会话、多 Lesson 学习时，才启用 Program／Lesson 长期状态、逐目标
  mastery 和长期进度记录。正式练习不专属于 Course；独立 Session 若在综合验收后仍有证据缺口，也可
  按 D5、D7 进入一次受约束的练习，但不会因此自动创建持久 Lesson 或声明长期 mastery。

状态按三个层级组织：

```text
Program：长期目标、范围、候选 Lesson 顺序和前台指针；已有预算时只引用其唯一来源
  └─ Lesson：已授权学习单元、来源、目标、教学阶段和三维 mastery
Session event：一次有实质增量的会话片段；可引用 Lesson，也可只引用独立主题
Checkpoint：唯一可覆盖的精确恢复游标
```

会话是否正在进行、Lesson 教学阶段、资料内部或阶段边界、三维 mastery，以及文章素材或草稿状态是
彼此独立的状态。暂停或结束一次会话不等于 Lesson 完成；读完资料不等于通过 mastery；整理文章也不
改变 Lesson 的完成状态。

每种语义只保留一个事实源，并优先适配消费仓库已经存在的约定，不为 PlanA 再创建一套
`docs/learning` 档案树。PlanA 中：

- 现有文件的唯一职责和适配边界按 D15 执行；
- Lesson 优先复用已有领域产物中的逻辑章节，只有没有适合的既有位置时才创建轻量记录；
- `学习断点.md`、模块 `进度.md` 和 `进度总表.md` 分别承担恢复游标、原始进度事实和派生视图；
- 文章、`study-log`、卡片和原始对话属于学习产物或过程记录，不决定当前学习状态。

最终 Skill **不提供任何斜杠快捷命令**，也不在 frontmatter、正文、界面提示或参考资料中要求用户记忆
固定命令。用户只需自然表达“先暂停一下”“继续刚才的学习”“今天先到这里”“我卡住了”“讲快一点”
“帮我整理成文章”等意图；Agent 识别意图并执行相应状态转换。自然语言表达不要求固定措辞。

### D7：采用最小记录、按需产物和契约范围授权

记录规模按 D6 的三种运行范围递增：

- **一次答疑**默认零仓库写入；只有用户明确要求保存时，才生成紧凑记录；
- **陪学 Session**结束时只追加一条简短 Session 事件；仍有恢复任务时更新唯一 Checkpoint，真正终态
  则删除 Checkpoint 引用和无用游标。Session 事件保存日期、上下文（已有 Lesson 时为 Lesson 引用，
  否则为短主题标签）、覆盖范围、完成动作、证据或产物链接和未关闭问题；保留的 Checkpoint 只保存
  精确恢复位置、唯一下一动作、当前阻塞项、最近有效证据和前进门槛；
- **持久 Course**使用轻量 Lesson 逻辑记录；需要独立文件时，以约 50–80 行作为非约束性精简目标，
  保存身份与来源范围、2–4 条目标、状态、核心产物、完成门槛、未关闭阻塞项、Session 事件索引和关闭
  时的三维 mastery 结果；练习契约、实验、Review 和 mastery 细节只在实际发生时增加条件片段。

Program 保存课程目标与范围、候选 Lesson 短描述和已授权 Lesson 引用；当前活动 Lesson 指针与唯一
Checkpoint 引用按 D20 的状态条件出现。它不得复制 Lesson 的详细结论、证据和开放问题。

基础 Lesson 记录不再复制完整教学正文、逐题问答、完整测试输出、暂停快照、原始对话元数据、重复
checklist 或 changelog。Program、Lesson 和 Session 可以是逻辑层级，不要求每层都新建独立文件；
最终文件位置必须适配消费仓库现有约定。

各类产物采用以下职责分工：

- **Lesson record**：保存本课目标、来源范围、状态、完成门槛、证据链接、正式 Review 和三维 mastery；
  有文章或其他权威知识产物时只链接，不重复正确结论；没有独立知识产物时，才保留 3–6 行、明确标为
  fallback 的简短心智模型；
- **`study-log` 结构化过程模式**：保存学习者原始回答、误解、纠错、高价值问题和关键转折，不重复完整
  教学正文；没有持久 Lesson 时才可承担简短独立要点摘要；
- **`study-log` 原始对话模式**：保存经过规则化提取的可见消息、来源、边界、哈希和清洗参数，不负责
  最终正确结论或课程状态；
- **文章**：保存面向读者的体系化叙述，不负责当前状态、下一动作或 mastery；
- **Cards**：从稳定结论或独特纠错生成的可再生复习视图，不成为新的知识事实源。

文章、结构化 `study-log`、原始对话和 Cards 均按需生成，不在每次 Session 结束时成套执行。原始对话
默认不提交仓库，只在用户明确提出保存原始／逐轮可见文本，或提出审计、研究、复盘需求，并确认边界
与隐私后保存。PlanA 不再把每次学习结束自动生成文章草稿作为固定 Stage；在形成完整且值得整理的
主题时，以自然语言提议，用户确认素材范围和目标后再起草与写入。

正式练习开始前，契约必须声明文件所有权和范围：学习者核心工件、Agent 验收工件、Agent 记录工件、
只读来源和明确排除项。用户接受契约后，即授权 Agent 仅在逐项列明的 Agent-owned 测试、rubric、
fixture、记录和唯一 Checkpoint 路径内创建和维护内容、修复自身工件、为契约内已有行为补最小回归
覆盖、运行验证，并更新 evidence 与 finding，不必逐文件重复确认。

以下情况仍必须重新取得用户授权：修改学习者核心工件或学习者自有测试；扩大契约或新增完成门槛；
把 optional 改为 required；引入依赖；修改配置、CI 或公共接口；从教学级练习升级为生产级工程；对
任何非 Agent-owned 文件执行新增、修改、移动或覆盖。用户明确要求 Agent 接管核心实现时，须记录
AI-assisted 范围；该部分不能直接作为学习者独立完成的实践证据，需要通过新的独立变式重新验证。

Durable Review 只保存映射到既定契约或 mastery 的 finding：ID、对应目标、严重度、最小证据、责任人、
下一动作和状态。一个根因只保留一个 finding；同一轮最多给学习者三个当前动作；minor 和 suggestion
默认不阻塞 mastery；所有 required blocking/major finding 关闭后停止正式 Review，不因工程润色扩张
练习。契约外发现先作为 observation 或待澄清项，未经用户同意不得升级为新的 required gate。

### D8：Lesson 按可独立验收的能力划分

Lesson 不与文件、资料、Session、日期或文章机械对应。一个 Lesson 应围绕一项能够独立描述的目标能力，
其 2–4 条目标必须紧密相关，并能由同一组 mastery gate 共同验收。读完资料、结束 Session 或完成文章
均不构成 Lesson complete。

- 一份较大的资料可以拆成多个 Lesson；多份资料也可以共同支撑一个 Lesson；
- 一个 Lesson 可以跨多个 Session；一次 Session 是否结束不改变 Lesson 边界；
- 文章与 Lesson 允许多对多：一个 Lesson 不必产出文章，一篇文章也可以综合多个 Lesson；
- 若内容包含两个独立心智模型、两个可分别关闭的正式练习或 mastery gate、新的前置知识，或者验证方式
  从功能正确性转为独立的性能实验与证据解释，通常应拆分；
- 若多个练习只是同一能力的互补变式，并共享同一心智模型和 gate，可以保留在同一 Lesson；
- optional extension 不阻挡核心 Lesson 完成；已完成 Lesson 后的小型补充不改变 Lesson 状态：一次
  答疑仍保持零持久写入，只有当轮本就属于陪学 Session 时才按 D6–D7 记录补充 Session。只有新证据
  推翻原 mastery，或用户扩大原目标时，才提议重新授权并重开。

按此规则复核现有案例：Triton Lesson 02 应将普通行级 Softmax 正确性与 Persistent 调度和性能测量拆为
两个 Lesson；Triton Lesson 01 的 block-size benchmark 应与向量加法核心能力分开；PlanA 的 vLLM
Pass A 与 Pass B 可以共同组成“仓库与进程架构”Lesson，而 Pass C 的请求生命周期属于下一 Lesson。

### D9：分开教学主线与事实权威

用户选择的资料优先作为本课的 **teaching spine**，决定教学沿哪条路径推进，但不自动成为所有结论的
最高权威。每份来源必须声明它在当前 Lesson 中承担的角色；不同 claim 按其性质选择证据：

- 固定 revision 的源码裁决该版本的具体实现与控制流；
- 官方文档或规范裁决公开接口和承诺语义；
- 论文裁决论文所定义的方法、假设和报告结论；
- 本地运行或实验只证明明确环境、配置与输入下的观测；
- 官方教程、示例及第三方解释负责教学脚手架，不能覆盖相应的一手事实来源。

Agent 不因发现另一份看似更好的资料而静默替换用户选择的教学主线。Agent 主动补充资料的默认条件是：
缺少必要前置、存在过时或版本冲突风险、关键结论需要一手核验，或当前目标明确要求比较与迁移；用户
主动指定的补充资料则按其指令纳入，并补记来源角色与范围。不会改变目标、范围和学习投入的最小事实
核验可以直接进行，但须标明来源角色；替换教学主线、加入较大资料、扩大范围或明显增加投入时，必须
先取得用户确认。开课时应记录相关 commit、tag、文档版本或日期；涉及“当前”或“最新”的结论时
重新核验。

多来源冲突不得静默揉成单一答案。应先核对版本、分支、配置和适用条件，再分别记录各来源能够支持
与不能支持的结论；按用户目标版本选择本课采用的行为，无法解决的内容标为待验证。只有冲突阻塞当前
Lesson 时才扩大调查，否则登记后返回教学主线。

`resource-planning` 继续负责跨模块的广泛资料发现、去重、候选排序和稳定课程晋级；主学习 Skill 只为
当前 Lesson 做最小补充核验。当前学习中发现的长期资料只能在当前 Lesson 权限范围内记录为 observation，
或向用户提出交接建议；主学习 Skill 不直接写入 `resource-planning` 的候选池、周报或稳定规划文件。
只有用户触发 `resource-planning` 后，候选才进入其治理流程；候选不自动修改学习指引、不自动晋级，也不
因计划列出下一资料就启动下一 Lesson。

### D10：Lesson 内自然推进，Lesson 间等待授权

Program 中列出的 Lesson 顺序只是候选计划，不等于执行授权。用户明确选择当前 Lesson 后，Agent 可以
在该 Lesson 内连续完成讲解、理解检查、补差、轻量工件与关键节点推进，不在每个内部步骤重复询问；
进入正式练习时仍须遵循 D7 的完整契约和文件权限边界。

当当前 Lesson 达到既定 mastery gate 时，Agent 先展示各目标和所需 mastery 维度的证据，由用户确认是否
关闭。关闭当前 Lesson 不自动授权或启动下一 Lesson，也不自动进入 optional extension。用户可以为某个
Program 明确授予按已确认顺序连续推进的权限，但该权限仍不包含 optional 或 conditional 内容、课程
范围扩张、新依赖、新写入权限、跳过前置条件或启动新的 Program。连续推进只免去当前 Lesson 关闭后
对下一 Lesson 的第二次启动确认，不免除 mastery 证据展示和用户关闭确认。

系统可以保留多个暂停或待恢复的 Program，但同一工作上下文只有一个前台 active Lesson。启动临时专项
前先冻结原 Program、Lesson、恢复位置和唯一下一动作；专项结束后展示专项结果和原返回点，由用户选择
返回、延长或转向，不自动跳转。已完成 Lesson 的补充答疑遵循 D6–D8：默认不改变 Lesson 状态和原
契约，是否记录补充 Session 由当轮运行范围和 D7 的记录规则决定。

### D11：只核对必要前置，预测改为条件触发

D11 不新增固定的课前考试。一次答疑不做正式学前诊断；结构化 Lesson 开始时，Agent 先从既有课程
记录、产物和已验证 mastery 中核对前置条件。已有证据充分时直接开始教学；只有某项关键前置不明确且
答案会实质改变教学起点时，才提出一个能够依据学习者已有知识回答的最小问题。学习者回答“不知道”
是有效信息，不视为失败或能力缺陷。

尚未教授的新知识不要求学习者预先猜测。小型前置缺口可以在进入本课前做最短补充；若缺口本身构成
一项需要独立验收的能力，则提议拆为前置 Lesson，由用户决定是否调整当前范围。最短补充不自动新增
Lesson 目标或 mastery gate。普通正确回答不需要持久化，只记录会改变 Lesson 范围、教学路径或恢复
动作的前置缺口与决定。

旧模板中泛化的 pre-lesson prediction 不再作为默认字段或固定仪式。预测仅在以下情况下使用：

- 相关机制已经讲解后，用条件变化或陌生同构情境检查迁移；
- 真实运行或实验结果出现前，保存之后能够被验证或推翻的假设。

实验前预测至少说明预期方向、依据、不确定性和可推翻条件；不得在看到结果后补写成事前预测。前一种
迁移预测属于 D12 的理解或综合检查，后一种实验预测可以成为 D13 的实证证据。

### D12：采用自适应检查题和自然语言提示梯度

D4 微循环中的“探”就是讲解与必要深挖后的关键节点理解检查。每个节点只选择一个当前最有区分力的
检查，不堆叠同义问题；根据目标从以下形式中自适应选择：

- 复述关键关系或不变量；
- 追踪数据、控制、状态或论证流程；
- 比较相近概念，识别边界、反例或失败条件；
- 改变一个已讲条件并预测结果；
- 把新案例映射到刚学模型，或根据现象诊断失效节点；
- 完成最小推导，或给出一个例子作为回答。

检查必须能根据刚完成的讲解和已经确认的前置知识作答，不能夹带隐藏事实。选择题、术语回忆或照着
刚给出的标准答案复述可以辅助定位，但不能单独证明理解。回答存在差距时只补差值，并更换条件、例子
或问法复查；持续困难时缩小关键节点或补前置，不重复整段长讲。

所有关键节点完成后、正式练习之前，执行一次小型自适应跨节点综合验收，通常使用 2–4 个整合问题，
覆盖完整心智模型、关键边界或反例和独立迁移；实证型目标再加入实验预测。题数不是固定配额，应以
得到最低充分证据为止。综合验收已经充分覆盖目标时，按 D5 跳过不必要的正式练习。

正式练习中的帮助采用内部渐进层级，但不向用户暴露编号，也不要求固定命令或措辞：

0. 只报告契约、验证结果和证据差距；
1. 重述不变量并帮助诊断缺口；
2. 指向相关概念、来源或需要重查的边界；
3. 给表面不同的较小类比，或把任务缩成一个小门动作；
4. 给伪代码、接口骨架或结构脚手架，但保留本课要验证的核心选择；
5. 仅在用户明确要求时完整示范或接管；聊天中展示答案不自动授权修改文件，写入仍遵循 D7。

单次答错、测试失败、沉默或耗时较长都不会自动提升帮助。学习者自然表达卡住或主动求助后，通过一句
最小诊断与学习者共同判断是概念、执行、环境还是精力问题，再提供最低必要支持；默认一次只提升一层，
用户可以明确要求更强帮助，也可以随时要求恢复独立尝试。Agent-owned 测试、fixture 或环境故障由
Agent 在既有授权内修复，不算学习者求助，也不产生 learner finding。

material hint 由实际透露的内容而非层级编号机械决定：揭示关键分解、算法、核心公式、伪代码、具体
修复或完整解法，会改变独立证据；仅重述契约、报告失败证据或修复 Agent 自身工件不会。持久 Course
只保存最高实质帮助程度、受影响目标或工件范围以及是否存在 Agent 写入，不保存逐轮提示全文。接受
material hint 或 AI-assisted 实现后，只撤销受影响范围的独立实践证据；用一个更小、表面不同但心智
模型相同的新变式，在无材料提示下重新验证，不要求整课重做。

### D13：三维 mastery 采用按目标声明的最低充分证据

每个结构化 Lesson 在开课契约中预先声明需要哪些 mastery 维度。`not-required` 表示该维度不属于本课
目标，不能因为后续没有完成而临时降级；新增维度等同于扩大完成门槛，须按 D7 重新取得授权。

| Lesson 类型 | 概念已掌握 | 实践已验证 | 实证已验证 |
| --- | --- | --- | --- |
| 概念或源码理解 | required | 通常 `not-required`；目标包含独立设计、推导或操作时 required | 通常 `not-required`；目标包含真实运行时、设备或版本行为主张时 required |
| 编码或实现 | required | required | 目标包含真实环境、设备或性能结论时 required，否则 `not-required` |
| 实验或 benchmark | required | 仅在目标包含测量工具或实验工件实现时 required | required |

各维度的最低充分证据如下：

- **概念已掌握**：学习者独立复述中心模型，解释一个关键边界、反例或相似概念差异，并在未直接讲过
  的小型同构情境中完成条件变化、映射、诊断或迁移；版本敏感的源码结论还应能指出相应来源锚点。
- **实践已验证**：学习者拥有并完成契约内核心工件；Agent-owned 测试或 rubric 通过；required 的
  blocking/major finding 已关闭；学习者能解释一个重要验证用例，并完成同一模型下的小型变式。
- **实证已验证**：结果出现前保存可证伪预测；环境、版本、输入、控制变量与测量边界明确；命令和结果
  能在声明条件下复现；存在与目标相称的基线和/或受控比较；学习者能说明证据支持、不能支持的结论与
  剩余不确定性。性能 benchmark 还须具备独立正确性证据和至少一个受控比较，避免比较错误实现或把
  同时变化的多个因素误作单一原因。

跨节点综合验收若已独立提供上述概念证据，可以直接满足概念维度，不为形式完整再安排正式练习。
Agent 已准备 benchmark harness，而学习者只负责预测、运行和解释时，计入实证能力，实践维度为
`not-required`；只有实验工件的设计或实现本身属于目标时，才要求实践维度。测试绿灯属于实践验证，
不会仅因发生了真实运行就自动成为实证 mastery。

旧 `learn-by-practice` 的 reflective mastery 不保留为第四个维度。高价值误解、失败尝试、取舍和修正
继续按 D7 作为过程记录保存，但不能替代概念、实践或实证证据。

### D14：采用稀疏、语义化的状态写入

状态分为四种职责，不因物理上共用一个文件而混淆：

- **Program 控制面**：只保存长期范围、候选 Lesson 短描述、已授权 Lesson 引用，以及条件性的当前活动
  或已冻结 Lesson 和 Checkpoint 引用，不复制 Lesson 的状态与证据；
- **Lesson 证据账本**：保存来源、2–4 个目标、预先声明的 mastery 维度、当前教学阶段、正式练习契约、
  核心产物、required findings 和最终 mastery，不保存逐轮问答或精确会话游标；
- **Session event**：每个具有实质增量的会话或暂停段最多追加一条简短历史摘要；
- **Checkpoint 唯一游标**：只保存最新精确位置、唯一下一动作、阻塞项、最近有效证据和前进门槛，
  覆盖更新，不追加历史快照。

状态只在会话边界或耐久事实发生变化时写入。一次答疑始终默认零写；打开或恢复已有 Lesson 只读，
不因查看状态更新时间戳。普通讲解、追问、理解检查、正确回答和关键节点推进不逐步写文件。以下事件
可以在已授权路径内同步所属状态：

- 正式练习契约获接受；
- 学习者提交核心工件；
- 正式 Review 形成新的 durable finding；
- 验证改变 finding、证据或 mastery 判断；
- 跨过综合验收或进入 mastery gate；
- 在会话边界或上述耐久 gate 上，为跨会话恢复而改变唯一下一动作；
- Session 暂停、计划内收工或用户确认关闭 Lesson／Program。

暂停与收工使用同一种最小事务：有实际进展时追加一条 Session event；仍有恢复任务时覆盖 Checkpoint，
真正终态则删除 Checkpoint 引用和无用游标；没有进展、证据和游标均未变化时零写。暂停或结束 Session
不把 Lesson 改成 `paused` 或 `complete`，也不自动成文、制卡、生成结构化 `study-log` 或导出原始对话。
恢复时读取 Program、Lesson 和 Checkpoint 并做低成本 drift 核验；没有 drift 时零写，drift 会改变范围、
责任或下一动作时先让用户选择分支。

新 Program／Lesson 及其 Agent-owned 状态／基础记录文件路径须先获得授权；用户自然语言中足够具体的
开始请求可以直接构成授权，
不再额外要求固定仪式。开课时只声明 Agent-owned 的状态与基础记录路径；若 D5 判断需要正式练习，
再由 D7 的完整练习契约声明测试、rubric、fixture 和其他验收工件。已经授权的范围内，暂停、收工、
Review、验证和 Checkpoint 更新可以自动执行，不逐次展示 diff。新增路径，扩大目标、范围、mastery
维度或 required gate，改变所有权，启动未授权的下一 Lesson，重开已完成 Lesson，以及关闭 Lesson／
Program，仍须按 D7、D10 取得相应确认。

Lesson 达到 gate 后，Agent 先展示每项目标、所需维度、证据和非阻塞余项；用户确认后才一次写入最终
状态与 mastery，并把当段唯一 Session event 标记为 closure，再将 Checkpoint 移到 Lesson 边界。不得
自动启动下一 Lesson。已完成
Lesson 的一次补充答疑保持零写和 `complete`；当轮明确属于陪学 Session 时才追加补充事件。只有新证据
推翻 mastery 或目标扩大时，才提议重开或另建 Lesson。

临时专项只有在需要跨会话推进、形成独立目标或产物，或者会替换原唯一下一动作时，才冻结原 Program、
Lesson、Checkpoint 和返回点；单轮旁支答疑不建立专项状态。专项结束后由用户选择返回、延长或转向。

所有状态写入遵循 semantic diff：没有状态、证据或下一动作变化就不写，禁止纯时间戳 churn。学习时长
只记录用户明确提供或确认的值，不依据对话跨度猜测；缺少时长不得阻塞 Session event 或 Checkpoint。
Program 不抄 Lesson，Lesson 不抄教学正文、完整命令输出或原始对话，Checkpoint 不抄历史，派生总表
不成为第二事实源。

### D15：PlanA 采用现有文件的一义事实源映射

通用学习 Skill 不为 PlanA 创建第二套 `docs/learning` 或固定的 `lessons/` 档案树。PlanA 的事实按下表
映射到现有文件；Program、Lesson 和 Session 是逻辑层级，不要求分别占用独立文件：

| PlanA 位置 | 唯一职责 |
| --- | --- |
| `计划/主计划.md` | 长期 Program 的目标、全局范围、总预算和候选大阶段；不保存当前 Lesson 细节 |
| 专项冲刺计划 | 对应临时 Program 的专项范围、候选 Lesson 顺序、专项预算与授权规则；计划存在不等于 Lesson 已激活 |
| 各模块 `学习指引.md` | 稳定课程、候选资料、优先级和排除项，由 `resource-planning` 治理；不保存当前学习状态 |
| 开课时明确指定的领域设计包或实验包中的 Lesson 专属章节 | Lesson 的目标、来源、阶段、契约、证据、findings 和 mastery；能够复用逻辑章节时不新建档案；文章、`log/`、Cards 和原始对话不得承担此职责 |
| 各模块 `进度.md` | 用户确认的实际用时、资料或任务状态，以及一行式 Session 历史；不保存精确恢复游标或完整证据 |
| `计划/学习断点.md` | 前台 Program／Lesson 指针、精确位置、唯一下一动作、阻塞或前进门槛，以及临时专项返回引用 |
| `计划/进度总表.md` | 从主计划与模块进度形成的周期性 dashboard；不作为每日事件、Lesson 证据或当前游标的事实源 |
| 文章、`log/`、`cards/` 和原始对话 | 知识产物、过程记录或再生复习视图；不决定 Program、Lesson 或 Session 状态 |

一个已明确承担 Lesson 记录职责的领域设计包或实验包覆盖多个能力时，可以用明确命名并记录精确锚点的
章节分别承担多个 Lesson 的逻辑记录；例如 PlanA 当前设计包可以让架构 Lesson 与请求生命周期 Lesson
使用不同章节，而不是复制成另一棵课程档案。若确实没有合适的既有记录，才在模块既有组织方式中建立
D7 所述的轻量 Lesson 记录。

预算与用时也遵循一义来源：`主计划.md` 拥有全局预算，专项计划只能声明其在全局预算中的分配关系并
链接父级，不得静默创建另一只可重复累计的时钟；模块 `学习指引.md` 拥有资料级预计用时，模块
`进度.md` 只保存用户确认后的实际用时。`陪学流程.md` 等适配或入口文档只能引用这些数值，不能重新
声明一份可独立修改的预算。

`学习断点.md` 必须从现有的大段完成叙述中精简出来。它不得重复设计包中的已完成事实、详细产物、
cadence、隐私说明、教学正文或历史 Review，只能链接最近证据。临时专项的返回信息也只保存足以恢复的
小型引用或 capsule，不复制原 Lesson 内容。模块 `进度.md` 是时间与任务状态的原始事实；`进度总表.md`
只在既有周期性汇总触点更新，不随每个 Session 制造第二份日志。

实施迁移时，专项计划或设计包中与 `学习断点.md` 重复的精确当前位置和下一动作停止并行更新；设计包中
与模块 `进度.md` 重复的 Session 日志停止双写；模块进度中的资料标题、预计用时和总表中的当前位置只
作为来源文件的派生视图。旧内容可以保留为带日期的历史快照，但不再充当活动事实源。

`计划/陪学流程.md` 后续改造为 PlanA 消费仓库的适配说明，不再与通用 Skill 竞争流程事实源。它只保留
PlanA 特有的路径映射、时间粒度、状态图标、预算规则、文章模板衔接和稳定层保护。旧文档中的“先问
后讲”、斜杠命令、收工自动成文和逐步写入规则须在实施阶段按 D4、D6–D7、D14 修订。

`计划/记忆/peixue-learning-style.md` 继续作为个人学习偏好，`计划/记忆/MEMORY.md` 只作为记忆导航；
二者都不作为教学状态或通用流程事实源。后续保留
“接本职、沿原理推导、使用具体数字或例子、明确纠错”等稳定偏好，但把已被 D4 否定的“先问后讲”
更新为讲解后检查。周报和资源变更记录只属于 `resource-planning` 的治理历史，`计划/文章模版.md` 只是
可选知识产物模板。README、CLAUDE、AGENTS 等入口文档只是导航与路由视图，实施完成后随事实源同步，
不独立声明另一套流程。

### D16：`study-log` 统一提取内核并提供两个按需模式

学习对话能力统一归 `study-log`。它应把现有两套实现合成一个共享的“发现会话 → 预览 → 选择边界 →
清洗与规范化 → 完整性校验 → 原子输出”内核：

- 保留现有 `study-log` 的 Claude Code／Codex 自动发现、项目与根会话过滤、日期切片和临时工具摘要；
- 吸收 `learn-by-practice` 的语义与时间边界、可见消息规范化、去重、phase、消息数、来源与对话哈希、
  清洗参数、默认拒绝覆盖和测试覆盖；
- 扩展严格 raw 导出到 Claude Code，并修复 Windows 项目路径映射；
- 主学习 Skill 只传递 mode、source、boundary 和 target 并消费产物，不再解析 JSONL 或维护 exporter；
- `english-coach` 需要的 scratch dump 只作为仓库外临时传输，不形成第三种持久模式。

两个持久模式的职责如下：

| 政策 | 结构化过程记录 | 可追溯可见文本对话 |
| --- | --- | --- |
| 触发 | 用户明确要求整理学习记录、纠错、高价值问答或制卡素材；主学习 Skill 只能提议，用户同意后调用 | 仅在用户明确提出原始对话、逐轮可见文本、审计或研究复盘时调用；“存档对话”含糊时先确认模式 |
| 内容 | 学习者原始回答、误解、纠错、高价值问题和关键转折；不复制完整教学、状态或 mastery | 规则化的用户可见文本序列，以及来源、边界、消息数、哈希和清洗参数 |
| PlanA 位置 | `{module}/log/YYYY-MM-DD-topic.md`，继续供 `memo-cards` 与 `english-coach` 消费 | 默认写入 PlanA Git 工作树外的统一私有目录，不得混入 `{module}/log/` |
| Git | 可跟随消费仓库现有惯例；Skill 不负责 commit | 默认不提交；要求放入仓库时须确认隐私、目标路径与 Git 忽略状态，不得静默修改 `.gitignore` |
| 覆盖 | 已有同一逻辑记录时先展示 diff 并明确确认，不再按同日同主题静默整份覆盖 | finalized archive 默认不可变；至多保留一个 partial，只有最终关闭时经 diff 和显式 overwrite 替换 |
| 保留 | 作为长期过程记录，跟随消费仓库生命周期 | 每个边界保留最终档和至多一个可替换 partial；不保存每次刷新快照，也不自动删除用户明确保存的最终档 |

结构化记录应从仓库外临时提取结果蒸馏，完成后清理 scratch。无论是否已有文章或 Lesson，它都保留本
模式专属的原始回答、误解、纠错、高价值问题和关键转折，但不重复其中已经稳定化的正确结论；`[要点]`
或知识摘要只补文章未收录的内容并链接权威产物。没有持久 Lesson 时才允许 3–6 行 fallback 要点。它
不是知识权威或课程状态。首次生成已由用户请求授权；更新现有文件仍按上表先看 diff，防止覆盖人工编辑。

raw 模式必须在输出前确认 source、起止边界、隐私和目标位置。它应准确称为“可追溯可见文本对话”，
不能声称是完整客户端 Session 或匿名化数据。默认排除 system／developer、reasoning、工具事件和客户端
注入，附件与图片不嵌入。发现凭据、个人信息、公司代码、内部 API 或未公开硬件／性能数据时，优先
缩小边界或改用结构化模式；确需脱敏时采用可复现规则并记录 redaction 元数据，不手工润色正文。
结构化临时提取可以在明确告警后容忍尾部残缺记录，raw 导出必须严格失败并保留原目标不变。

### D17：合并后的唯一主 Skill 命名为 `guide-learning`

合并后的目录名和 frontmatter `name` 统一使用 `guide-learning`，人类可见名称使用
“Guided Learning / 学习带练”。该名称以动词开头，并能覆盖一次答疑、陪学 Session 和持久 Course，
不再像 `learn-by-practice` 一样暗示正式实践每次必经，也不继承 `study-companion` 的 PlanA 日常仪式和
固定命令语义。

frontmatter `description` 必须在紧凑的一段中完成触发路由：

- 明确服务对象是人类学习者，能力包括来源驱动讲解、讲后自适应检查、按证据缺口触发的正式练习、
  学习工件 Review、mastery 验证和最小恢复状态；
- 覆盖“教我／解释这个主题”“带我读文档、教程、论文、示例或源码”“开始、继续或恢复 Lesson”
  “设计或评审学习练习”“开展跨会话 Course”等自然语言意图，不要求固定措辞；
- 排除没有学习意图的普通实现、修复或代码审查，以及 `resource-planning` 的资料治理、`study-log` 的
  对话提取、`memo-cards` 的制卡和 `english-coach` 的英语专项反馈；
- 不写入 PlanA 路径、斜杠命令、固定开始语，也不承诺每轮练习、写日志、生成文章或建立档案。

旧入口按三个明确时点退出：C2 将 `study-companion` 与 `learn-by-practice` 从活动 catalog 状态切为
rollback-only；M3／M4 分别把它们移出 programming-lab／PlanA 的消费配置与发现目录；M5 才删除中央
目录和 catalog 条目并登记 `retired_names`。任何阶段都不得保留带 frontmatter 的 alias／redirect 包装，
因为三个相近入口会产生重复触发和长期漂移。新 catalog 条目须保存两者的来源仓库、路径和固定提交作为
lineage。旧名称在原始对话、已完成 Lesson、历史决策和 Git 历史中保持原样，不做全局替换。

### D18：`guide-learning` 采用精简入口与按需 references

目标目录固定为：

```text
skills/guide-learning/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    ├── teaching-cycle.md
    ├── source-authority.md
    ├── practice-review-mastery.md
    ├── state-records.md
    ├── repository-adaptation.md
    └── examples.md
```

主 `SKILL.md` 以约 180–230 行作为非约束性精简目标，并始终保持在 500 行以内。它只保留每次触发都
需要的内容：三种最窄运行范围、上下文建立与恢复、来源角色摘要、D4 微循环、D5 综合验收分流、
Lesson 内外授权、正式练习所有权入口、三维 mastery 名称及按目标预先声明 `required`／`not-required`
的规则、D14 稀疏写入摘要、自然语言控制、跨 Skill 边界，以及每个 reference 的明确读取条件。详细
schema、场景与变体不在主入口重复。

各 reference 只承担一类按需知识：

| 文件 | 唯一职责 |
| --- | --- |
| `teaching-cycle.md` | 关键节点划分、必要前置核对、检查题选择、补差与换题、跨节点综合验收 |
| `source-authority.md` | teaching spine、claim authority、版本锚点、来源冲突、最小补充核验和实证边界 |
| `practice-review-mastery.md` | 正式练习契约、所有权、tests-first、提示梯度、finding 生命周期和 D13 最低证据 |
| `state-records.md` | 开课契约及 Program、Lesson、Session event、Checkpoint 的逻辑 schema 与 D14 写入事务 |
| `repository-adaptation.md` | 逻辑角色映射到消费仓库现有文件的发现顺序和 fallback 原则，不硬编码 PlanA 路径 |
| `examples.md` | 少量非规范性边界案例，用于展示一次答疑、跳过正式练习、恢复 drift、临时专项等选择 |

`guide-learning` 首版不设置 `scripts/`、`assets/` 或 Skill 内 `tests/`。教学、诊断、适配和状态判断属于
高自由度推理，不用脚本固化；完全没有学习记录约定的仓库采用 schema-only fallback，由 Agent 依据
`state-records.md` 在用户授权目标路径后生成最小记录，不附带可复制的通用 Lesson 模板。后续只有前向
测试证明 schema 不足时，才重新评估是否增加小型 asset。

旧资源按以下边界处理：

- 两个旧 `SKILL.md` 合并重写；只吸收通用的带练、恢复、练习、Review、mastery 和协作边界；
- 旧 `agents/openai.yaml` 丢弃，最终根据新 `SKILL.md` 重新生成；
- `learning-archive.md` 拆入 `state-records.md`、`repository-adaptation.md` 和 `source-authority.md`；
- `practice-review-mastery.md` 保留文件名但按 D5、D7、D12、D13 大幅重写；
- `dialogue-archive.md`、`export_codex_dialogue.py` 及其有效测试迁入唯一所有者 `study-log`；
- 316 行 Lesson 模板、固定 archive index 和 `init_learning_archive.py` 在 M5 随旧目录退出，不提供替代的固定档案树；
- 初始化器测试在 M5 随已退出脚本删除；exporter 测试迁往 `study-log`，不得在两个 Skill 中保留副本。

静态结构检查和教学行为前向测试属于中央仓库级验证面，不进入运行时 Skill 目录。至少验证 frontmatter
与 `agents/openai.yaml` 一致、所有一级 reference 可达、主入口无 PlanA 路径／斜杠命令／JSONL 解析，
并覆盖三种运行范围、未知知识不猜测、正式练习授权、material hint、暂停恢复、Lesson 关闭、临时专项
和来源冲突。

### D19：采用公开中央远端和分阶段、单入口迁移

正式中央远端确定为公开的 `XiFenM/agent-skills`。消费仓库的 `.gitmodules` 使用相对 URL
`../agent-skills.git`，使其随父仓库继承 SSH 或 HTTPS 协议，并允许公开消费仓库匿名递归克隆。当前
中央仓库尚未配置远端；由用户在分阶段迁移开始前创建公开仓库。C0–C3 没有创建远端、发布或加入
本地路径 submodule，也没有因该前置条件暂停中央实现。

中央实现已按 D23 的 C0–C3 在本地完成并验证；它不属于 M0–M5，也不要求远端提前存在。远端就绪后，
迁移按以下阶段执行：

1. **M0，发布中央来源**：远端就绪后推送已经通过 C0–C3 验证的完整历史，并分别为中央实现前基线和
   合并兼容版本保留 tag／固定提交作为回滚锚点。
2. **M1，冻结迁移输入**：从远端全新克隆并复验兼容提交，确认 `guide-learning`、升级后的
   `study-log`、两个 rollback-only 旧源码、catalog lineage／retired 提示和 materializer 行为与本地验证
   一致；记录唯一中央提交供 M2–M4 固定引用，不在本阶段重新实现 Skill。
3. **M2，消费仓库空管线**：PlanA 与 programming-lab 先分别提交 `.agent-skills` submodule、
   `.agent-skills.json`、生成目录／state／lock 忽略规则和安装校验说明；配置暂设 `"skills": {}`，不改变
   当时的 Skill 发现状态。
4. **M3，programming-lab canary**：一个原子切换提交将 `guide-learning` 与 `study-log` 配置给 Codex，
   删除本地 `learn-by-practice` 源码、Windows 上退化为文本的发现／exporter 链接和重复 exporter 测试，
   清理 pytest、VS Code、CI 与活跃文档引用，再由 materializer 生成并 `--check`。
5. **M4，PlanA 切换**：在切换当时的真实语义暂停点冻结活动 Checkpoint，保持唯一下一动作和返回点
   不变；本次设计基线是 Pass C-1，若迁移时仍未变化则直接沿用。随后移除两棵受 Git 跟踪的 Skill
   副本，配置 `guide-learning`、`study-log`、`english-coach`、`memo-cards`、
   `resource-planning` 和 `playwright-cli` 给 Codex 与 Claude，改造 `陪学流程.md`、`学习断点.md`、学习
   偏好及入口文档后，分别验证两棵生成目录。迁移不得触碰或顺手提交无关的用户工作。
6. **M5，中央删除旧入口**：只有两个消费者均通过 materializer 检查、programming-lab 完成一次新流程
   前向验证、PlanA 能从迁移时冻结的 Checkpoint 无漂移恢复并保存一次稀疏 Checkpoint，且 `study-log`
   两种模式均通过测试后，才删除两个旧目录与 catalog 条目。消费者随后升级中央指针并重新 materialize。

每个消费配置跨所有 host 最多只能选择一个不同的主学习 Skill 名称；同一个 `guide-learning` 同时分发给
Codex 与 Claude 合法。兼容窗口保留的是中央源码和固定提交，不是可发现的 alias wrapper。
programming-lab 已完成的 Lesson 01／02、原始对话和历史命令冻结为 legacy evidence；
不批量重写其中的旧 Skill 名称、旧绝对路径或已纳入哈希的正文，从 Lesson 03 起采用新结构。PlanA 则
在迁移时的真实暂停点做无损状态迁移，不等待整个专项完成；Pass C-1 仅是本次设计时的基线。

M3 与 M4 都必须先把旧跟踪目录的删除、消费配置和活跃文档变更提交完成，再运行 materializer 生成被
忽略的发现目录并执行 `--check`。不得在提交删除前把同路径生成回来；否则 Git 仍把生成内容视为受跟踪
文件，PlanA 的同名物理副本也会因无法证明受管所有权而被 materializer 拒绝覆盖。

回滚时先把当前消费配置临时设为空并运行 materializer 安全卸载受管目录，再回退消费仓库切换提交；
若只是中央版本回归，优先回退 submodule 指针并重新 materialize。PlanA 的状态适配与子模块基础设施
分开提交，允许只回退 schema 转换而不破坏中央接入。

### D20：开场只投影最小状态，独立 Session 不强制创建 Lesson

开场展示是既有逻辑状态的短投影，不是新的事实源，也不生成一份重复的“开课契约文件”。三种运行
范围采用不同的最小展示：

- **一次答疑**直接回答，默认不展示固定卡片、不创建 ID 或状态；只有来源、版本、假设或回答边界会
  实质改变答案时，才用一句话说明；
- **陪学 Session**开始或恢复时只展示当前上下文、精确恢复位置和唯一首动作；阻塞项、前进门槛、
  drift 分支及首次建立的 Agent-owned 状态／基础记录文件路径均为条件字段；
- **持久 Course**分开投影 Program 与 Lesson：首次只创建 Program 时，展示长期目标、范围、明确排除
  项、候选 Lesson、Agent-owned Program 文件路径，以及实际创建 Checkpoint 时的路径和下一授权动作，
  不虚构“当前 Lesson”；
  激活 Lesson 时才展示其 2–4 个目标、各目标所需 mastery 维度、teaching spine 与事实权威、Lesson
  专属证据目标、Agent-owned Lesson／event 文件路径、唯一首动作，以及“关闭本课需确认、下一课不
  自动启动”的边界。用户一次请求同时授权二者时可以合并展示。

正式练习的测试、rubric、fixture 和文件所有权不在开课时预加载；只有 D5 判断确实需要正式练习时，
才按 D21 展示完整练习契约。足够具体的自然语言开始请求可以构成新 Program／Lesson 的授权；目标、
范围、mastery、required gate、路径或所有权仍有重大歧义时才停下来确认。

状态记录定义逻辑字段和写入事务，不规定固定 Markdown 模板。消费仓库可以把多个逻辑对象映射到一个
文件，也可以分别保存，但同一语义只能有一个事实源。最小逻辑 schema 如下：

| 对象 | 必填 | 条件字段 | 明确禁止 |
| --- | --- | --- | --- |
| Program | ID／标题、状态、目标范围、`candidate_lessons[]` 的有序短描述、`authorized_lesson_refs[]`（可为空） | `active_lesson_ref`、`suspended_lesson_ref`、`checkpoint_ref`、已有预算的唯一引用、连续推进授权、专项 parent／return 引用 | Lesson 证据与 finding、精确游标、Session 历史、实际工时明细、把候选描述写成已授权 Lesson |
| Lesson | ID／能力标题、Program 引用、带角色与版本范围的来源、2–4 个目标及 required mastery 维度、阶段、本课专属证据目标 | 前置缺口、核心产物、已接受练习契约、durable findings、material assistance、event 索引、最终 mastery、无权威知识产物时的 3–6 行 fallback | 完整教学、逐题问答、命令输出、原始对话、暂停快照、逐轮 Review、重复 checklist／changelog、`paused` 状态 |
| Session event | event ID／日期、Lesson 引用或独立主题标签、覆盖范围、实质完成动作 | 证据链接、未关闭问题、用户明确确认的时长 | 精确游标、完整会话摘要、逐轮问答、全部产物和 Lesson 状态副本 |
| Checkpoint | 存在恢复任务时：前台上下文、精确语义位置、恰好一个下一动作、前进门槛 | 阻塞项、最近一项有效证据、专项返回点、随语义变化更新的 `as_of` | 完成内容长叙述、Session 历史、预算／cadence／隐私政策、finding 明细、多个下一动作、纯时间戳更新 |

Program 状态使用 `planned | active | frozen | closed`；Lesson 阶段使用
`teaching | synthesis | practice | review | mastery-gate | complete`。暂停 Session 不会把 Lesson 改成
`paused`。独立 Session 可以只保存“主题标签＋event＋Checkpoint”，不自动升级为 Lesson；若后续需要
长期目标、跨会话证据账本或正式 mastery，须由用户授权创建或并入 Course。

`candidate_lessons[]` 只保存候选 ID／标题／顺序，不创建 Lesson，也不构成推进授权；只有
`authorized_lesson_refs[]` 指向真实 Lesson；开放 Program 的两者至少一项非空。`active` Program 有前台
Lesson 时使用 `active_lesson_ref`，正在等待下一课授权时它可以为 `none`。临时专项冻结原 Program 时，
将原引用移入 `suspended_lesson_ref` 并保留其 `checkpoint_ref`／return capsule；`planned` 与 `closed`
Program 的两个 Lesson 指针均为 `none`。`checkpoint_ref` 在已有可恢复上下文时必填；`planned` 尚未开始
或 `closed` 且无返回任务时可以为 `none`。Lesson 边界等待用户决定时，Checkpoint 的唯一下一动作写成
“等待授权下一 Lesson”；真正终态不伪造下一动作，而是移除 Checkpoint 引用。

独立 Session 若进入正式练习，已接受的契约、测试或 rubric 可以作为练习工件单独保存并由 Checkpoint
引用，尤其是在需要跨会话恢复或发生仓库写入时；它们不是新的 Session 状态层，也不会自动形成 Lesson
或长期 mastery 账本。

时间预算是条件字段，不是每个 Course 的固定开场问题。已有计划时只引用其唯一预算来源；普通 Course
不为形式完整而追问预算。恢复已有状态只读且零写；新建状态、跨越耐久 gate、会话边界和关闭事务继续
遵循 D10 与 D14。

### D21：正式练习使用六块契约，Review 只维护稳定 finding

综合验收仍有证据缺口且正式练习是最低充分路径时，Agent 一次性展示并请求接受以下六块：

1. **为什么做**：目标 ID、缺失的 mastery 维度和现有证据缺口；
2. **你交付什么**：任务与 learner-owned 核心产物；
3. **怎样算通过**：带 ID 的可观察 acceptance，以及对应测试、rubric、命令或其他证据方法；
4. **文件边界**：你写（learner-owned）、我维护（agent-owned）、我只读（read-only）、本次不动
   （excluded）；
5. **帮助如何影响证据**：允许自然语言求助；material hint 或 Agent 接管只影响对应范围，之后以无提示
   同构新变式恢复独立证据；
6. **非目标与完成门槛**：optional 单列；required acceptance 通过、required blocking／major finding
   关闭，并满足已声明的解释、变式或实证要求。

练习的最小持久数据包含：`id`、单调递增 `revision`、规范化内容 `digest`、目标与证据缺口、任务与
交付、required `acceptance[]`、四类 scope、单列的 optional，以及绑定 `revision + digest` 的接受事件。
每个 acceptance 至少保存 ID、可观察 criterion 和 evidence method；optional 使用同样形状但不进入 gate。
每个 scope 条目至少保存相对路径／受限 pattern 或逻辑工件标识，以及该类别允许的操作；类别本身决定
owner，操作只可从 read、create、modify、run、record 中取所需最小集合。任何目标、交付、acceptance、
scope、optional 或 gate 的变化都生成新 revision／digest，并按 D7 重新授权，不能沿用旧接受事件。

旧流程的 must-satisfy、代表案例、validation 和 completion definition 不再成为四套重复字段，而是合并
进 required `acceptance[]`。代码练习在契约接受后由 Agent 建立验收工件；只有当验收目标是新增或待修
行为、失败由预期缺口而非环境／fixture／harness 引起时，才把对应失败记为有效 expected red。不适合
tests-first 的既有正确行为或非代码练习，改用基线、rubric、对照或其他可观察证据，并明确 expected red
不适用。该动作属于已经授权的 Agent-owned 范围，不再要求第二次契约确认。

每个 durable finding 只保存七类信息：

```text
ID；映射的目标／acceptance；严重度；责任人；状态；最小开启／终结证据；唯一下一动作
```

严重度为 `blocking | major | minor | suggestion`，状态为
`open | closed | deferred | dismissed`。修改但尚未验证时仍为 `open`；`closed` 保存最小验证证据，
`deferred`／`dismissed` 保存理由。同一根因只建一个 finding 并原地更新，不保存按轮复制的表或
`learner-revised`、`needs-more-work` 等过程状态。required blocking／major 若要 deferred，须先由用户
同意改变 gate。finding 是否 required 由其 `maps_to` 是否指向 required acceptance 或 required mastery
维度唯一推导；契约外 observation 不得成为 required finding。`next_action` 只对 `open` 状态必填，进入
终态后清空。Agent-owned 验收工件或环境故障由 Agent 自行处理，不伪装成 learner finding。

一轮可以登记全部 findings，并以紧凑摘要全部向用户透明展示，但只激活最多三个 learner-owned 当前
动作，按 blocking、major 和依赖顺序选择；Checkpoint 只指向其中第一个可执行动作。minor 和
suggestion 默认不占当前动作槽、不阻塞结课。契约外 observation 明确保持在 gate 之外，除非用户同意
扩大契约。

material assistance 只按受影响范围覆盖保存：实际透露到的最高程度（自然语言）、受影响目标／
acceptance／工件范围，以及 Agent 是否写入 learner-owned 核心工件。它不保存提示层号、轮数或提示全文；
Agent 修复自己的测试、fixture 或记录不算 assistance。后续无提示新变式是否恢复独立证据，只写入对应
mastery evidence，不在 assistance 中重复。

结课展示一行一个“目标 × required mastery 维度”的矩阵，包含最小证据锚点与“充分／不足”；随后只列
required blocking／major 未关闭数、assistance 影响是否已恢复、非阻塞余项和关闭建议。对于已授权
Lesson，用户确认后才一次写入 final mastery，并在当段唯一 Session event 上标记 `closure`，随后移动到
Lesson 边界 Checkpoint，不自动启动下一 Lesson；closure 不是额外的第二条 event。独立 Session 只展示
并保存会话级 evidence、练习工件引用及带 `practice-closed` 标记的唯一 event，不写 final Lesson
mastery；仍有后续恢复任务时才保留或覆盖 Checkpoint，真正终结时移除 Checkpoint。需要长期 mastery
时先取得创建或并入 Lesson 的授权。

### D22：`study-log` 只暴露自然语言模式，底层采用安全共享内核

用户不需要知道脚本或参数。自然语言按以下意图路由：

| 用户意图 | 模式与行为 |
| --- | --- |
| “整理学习记录、提取纠错／高价值问答、给制卡用” | `structured`；来源、边界和目标明确时直接生成新记录，已有逻辑记录先展示 diff 再确认 |
| “保存原始对话、逐轮可见文本、用于审计或研究复盘” | `raw`；每次写入前确认来源、边界、partial／final、消息数、隐私和目标位置 |
| “保存／存档这段对话” | 询问一次选择精炼学习记录，还是隐私风险更高的可追溯可见文本 |
| “两种都要” | 分别生成；`raw` 仍单独确认 |

`raw` 必须准确称为“可追溯可见文本对话”，不声称包含完整客户端 Session，也不声称已经匿名化；它默认
排除 system、developer、reasoning、工具事件、客户端注入和附件正文。

共享内核采用以下内部阶段，用户不需要记忆命令：

```text
list → preview → extract／render candidate → diff → atomic write
```

统一入口固定为 `scripts/study_log.py`。已实现的内部最小调用契约如下；具体 flag 拼写以脚本为准，
不得省略所列输入、前置条件和输出：

| 子命令 | 最小输入 | 输出／效果 |
| --- | --- | --- |
| `list` | provider（默认 auto）、规范化 project，date 可选 | 根会话候选、稳定 session ID、时间范围和消息数 |
| `preview` | project 与 session ID 或显式 source | 稳定消息 ID、边界候选、隐私风险类别和 source SHA-256 |
| `extract` | 已预览 source SHA-256、起止消息 ID、structured 清洗策略 | 仓库外临时的规范化可见消息及完整性告警，不直接写 structured 成品 |
| `archive` | 已确认 source SHA-256、起止消息 ID、状态、目标／archive root、隐私决定；刷新／终结时必须再带 `archive_id` 与目标 SHA-256 | 新建时返回 archive ID 与规范目标；刷新／终结时原子更新指定 raw，或安全拒绝 |
| `config archive-root get/set` | set 时为用户选择的绝对私有目录 | 读取或更新用户级配置，不修改消费仓库 |

机器调用提供稳定 JSON 输出和错误码；结构化蒸馏仍由 Agent 完成，不塞进脚本。共享内核必须：

- 自动发现 Claude Code 与 Codex 会话，并按规范化项目路径过滤根会话，修复 Windows Claude 路径映射
  和旧 CWD 默认值；
- 使用稳定消息 ID 作为首选边界；重复文本片段必须报歧义，不能任取第一个；
- `structured` 临时提取最多容忍一个残缺尾行并显式告警，中间坏行仍失败；`raw` 始终严格失败；
- 在预览与生成之间校验 source SHA-256，目标已存在时以已审阅目标 SHA-256 约束 overwrite；
- 检查输出根 containment、符号链接／Windows junction 逃逸，并使用同目录临时文件原子替换；
- 默认拒绝把 raw 写入仓库；用户坚持仓库内路径时先检查 Git 跟踪／忽略状态，绝不静默修改
  `.gitignore`；
- finalized raw 不覆盖；每个边界至多一个 partial，只有最终关闭时经 diff 和明确确认原位终结，不保存
  每次刷新快照。

私有 raw archive root 不设置隐式默认目录。首次真正保存 raw 时询问一次实际路径，随后保存在操作系统
用户级配置中，而不是消费仓库配置中。解析优先级固定为：

```text
单次明确目标 > STUDY_LOG_ARCHIVE_ROOT > 用户级配置 > 缺失时安全停止并询问
```

默认布局为 `<private-root>/<project-name>-<path-hash>/<year>/...`，以路径 hash 区分同名仓库；partial／
final 状态保存在元数据而不是文件名中。每条 raw 流使用稳定 `archive_id`，并至少保存 provider、project
fingerprint、source session ID、起始消息 ID、当前结束消息 ID、`partial | final` 状态、source SHA-256、
可见内容 SHA-256、目标前置 SHA-256 及清洗／脱敏策略版本。刷新 partial 必须保持 archive ID、source
session 和起始消息不变，只可推进当前结束消息并更新哈希；改变起点或清洗身份必须新建 archive ID。
`partial → final` 是一次经 diff 与确认的单向原子转换，final 不再覆盖。

高置信度发现密码、令牌、私钥等凭据时，默认阻止 raw，直到用户缩小边界、改用 structured、采用可
复现脱敏规则，或明确要求原样私存。公司代码、内部 API、未公开硬件／性能数据等专有内容触发显式警告
和单独确认；若所有权或适用政策不清楚则安全停止。普通个人信息只警告并纳入同一确认卡。脱敏规则及其
元数据必须可复现，不手工润色正文。

现有 `study-log` 的跨 provider 发现、日期切片和临时工具摘要，与 `learn-by-practice` exporter 的规范化、
phase、去重、语义／时间边界、哈希、严格解析和原子输出合并到这一内核。Exporter 参考与有效测试迁入
`study-log` 并扩展 Claude／Windows／strict／overwrite 覆盖；固定学习档案初始化器不迁入。

### D23：catalog 与验证采用机器可读替代关系，中央实现分四个独立边界

catalog 在中央兼容版本固定升级为 `schema_version: 2`，支持多来源 lineage、生命周期、退役名称和选择
互斥。机器可读形状至少包含顶层 `selection_groups`、`retired_names` 和 `skills[]`；每个 Skill 条目使用
`lifecycle.state`，枚举仅为 `active | rollback-only`，并以 `groups[]` 声明所属选择组：

- first-party 条目使用非空 `lineage[]`；每个来源保存仓库、原路径和 40 位固定提交，`guide-learning`
  同时保存 `study-companion` 与 `learn-by-practice` 两条来源；external 条目继续保存官方 submodule 与 URL；
- 活动条目标明 `active`；C2 中两个旧主学习入口标为 `rollback-only` 并提供
  `replacement: guide-learning`，当前 catalog 中不可被新配置选择；
- `selection_groups.primary-learning.max_distinct_per_config` 固定为 `1`；它允许同一个活动 Skill 同时
  配置给 Codex 与 Claude，但一个消费配置不得选择两个不同的主学习入口；
- M5 删除旧条目后，将旧名称移入机器可读 `retired_names` 映射，使 materializer 对旧配置给出替代建议，
  而不是普通的 unknown Skill；这不是可发现 alias，也不保留旧 frontmatter。

`replacement` 只允许出现在 rollback-only 条目或 `retired_names` 项中，并且沿替代链最终必须到达一个
active Skill；活动名称、rollback-only 名称和 retired 名称不得重叠，替代链不得成环或悬空。validator
必须检查这些约束以及 lineage、互斥组和现有路径规则；materializer 必须先拒绝 rollback-only／retired
名称并显示最终 active 替代项，再拒绝跨 host 汇总后的互斥冲突，最后才构建复制计划。迁移兼容期只允许
旧源码在中央树中供固定提交回滚，不允许同一消费仓库发现两个主学习入口。

中央仓库验证面分为四层：

1. **静态结构**：frontmatter、`agents/openai.yaml`、一级 references、catalog lineage／生命周期／互斥，
   并禁止 `guide-learning` 含 PlanA 硬编码、斜杠命令或 JSONL 解析；
2. **`study-log` 单元与安全测试**：两种 provider、Windows 项目映射、边界歧义、尾部残缺、raw strict、
   source／target SHA-256 竞态、私有根、Git 拒绝、凭据／专有数据政策、稳定 archive ID、partial 终结和
   临时文件清理；
3. **`guide-learning` 前向测试**：一次答疑、独立 Session、持久 Course、未知知识不猜测、D4 微循环、
   综合验收分流、带 revision／digest 的正式练习授权、material assistance、独立 Session 与 Lesson 的
   不同关闭分支、暂停恢复、Lesson 关闭、临时专项和来源冲突；
4. **集成测试**：活动与退役名称、同一 Skill 双 host、主入口互斥、空配置安全卸载，以及中央源码到两种
   discovery 目录的 materialize／check。

中央实现已经按四个可独立审查和回退的提交边界完成：**C0** 升级 catalog schema、validator、materializer
与测试但不切换入口；**C1** 升级 `study-log` 并复制、改造 exporter 能力和测试，暂不破坏当时仍为 active
的旧入口；**C2** 创建并验证 `guide-learning`，同时从旧所有者移除重复 exporter、把两个旧入口切为
rollback-only；**C3** 更新中央说明和迁移基线并运行完整验证。C0–C3 不包含任何消费仓库迁移。
M0–M5 仍须等待公开远端就绪，并由用户另行授权启动。

## 后续仍禁止事项

中央 C0–C3 已获用户授权并完成。以下外部与消费仓库动作仍持续禁止，直到公开远端已经由用户建立且
用户另行明确授权启动 M0–M5：

- 不创建、配置或推送 `agent-skills` 远端；
- 不修改 PlanA、programming-lab 或其他消费仓库的 submodule、Skill 配置、发现目录、文档或测试；
- 不修改任何真实学习状态、进度、Checkpoint、文章或其他用户学习产物；
- 不以本地路径 submodule、临时复制或提前 materialize 绕过独立迁移授权。

## 完成状态与后续边界

D1–D23 已完成本轮学习类 Skill 的职责边界、教学微循环、证据门槛、状态模型、事实源、日志策略、
最终身份、资源分层、最小 schema、内部接口、catalog 替代关系、验证矩阵、实现提交边界、旧入口退役与
分阶段迁移设计。当前没有仍需用户裁决的学习体验或实现方案缺口。

中央 C0–C3 已完成 catalog／工具基础、`study-log`、`guide-learning`、旧入口 rollback-only 切换、中央文档
和整体验证。下一阶段不是继续修改中央学习核心，而是在公开远端就绪且用户另行授权后执行 M0–M5；
在此之前不创建或推送远端，也不修改任何消费仓库。

本轮中央实现只覆盖 `guide-learning`、`study-log` 及两个旧主入口的 rollback-only 兼容状态；旧入口从
消费仓库退役仍属于 M3–M5。`english-coach`、`memo-cards`、`resource-planning` 保持独立的决定已经完成，
但它们各自进一步的质量升级仍属于后续独立评审阶段，不构成当前学习核心的阻塞项。
