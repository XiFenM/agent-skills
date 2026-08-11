# 学习类 Skill 合并升级决策与评审记录

本文记录学习类 Skill 在质量评估与合并升级阶段的已确认决策、中央实现和后续迁移边界。
用户已授权并完成 D23 定义的中央 C0–C3；因此本文所述 `guide-learning`、`study-log`、catalog 和中央验证状态已经落地。2026-08-11 又经分阶段单独授权完成并发布 M0 中央来源、M1 迁移输入冻结、M2 消费仓库空管线、M3 programming-lab 金丝雀、M4 PlanA 双 host 切换与 M5 旧入口最终退役。

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
  D19 确定。中央兼容状态与 PlanA 的 M4 具体适配均已完成。

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
`../agent-skills.git`，使其随父仓库继承 SSH 或 HTTPS 协议，并允许公开消费仓库匿名递归克隆。C0–C3
没有创建远端、发布或加入本地路径 submodule；2026-08-11 经用户单独授权后，M0 已配置 HTTPS 远端并
发布完整中央历史。

中央实现已按 D23 的 C0–C3 在本地完成并验证；它不属于 M0–M5，也不要求远端提前存在。远端就绪后，
迁移按以下阶段执行：

1. **M0，发布中央来源（已完成）**：已推送通过 C0–C3 验证的完整历史；
   `learning-core-pre-implementation` 固定中央实现前基线，`learning-core-v1` 固定合并兼容版本。
2. **M1，冻结迁移输入（已完成）**：已从远端全新递归克隆并复验 `learning-core-v1`，确认
   `guide-learning`、升级后的 `study-log`、两个 rollback-only 旧源码、catalog、三个官方子模块及
   materializer 行为与本地验证一致；M2–M4 唯一固定输入为
   `b2afd92854d57a375fdf990028c31561118cf8ec`，本阶段没有重新实现 Skill 或修改真实消费仓库。
3. **M2，消费仓库空管线（已完成）**：PlanA `1245d0856bb480e929f00561c18a1c7c2cac2633`
   与 programming-lab `fec3e862dd41de3c1ec95d6d12fe5770581f6e1c` 已分别提交并发布 `.agent-skills`
   submodule、`.agent-skills.json`、生成目录／state／lock 忽略规则和安装校验说明；配置保持
   `"skills": {}`，dry-run、空同步和 `--check` 均确认没有改变当时的 Skill 发现状态。
4. **M3，programming-lab canary（已完成）**：原子提交
   `979b777a55579dcbb7771c474d2cce776796c781` 保持中央 gitlink 固定在 M1 输入，将
   `guide-learning` 与 `study-log` 配置给 Codex，删除本地 `learn-by-practice` 源码、
   Windows 上退化为文本的发现／exporter 链接和重复 exporter 测试，更新 pytest、
   VS Code 与活跃文档引用。提交后 materializer 仅生成两个受管 Codex 入口，
   `--check` 及针对性静态、单元、类型与全新会话前向测试通过；完成后发布至远端 `main`。
5. **M4，PlanA 切换（已完成）**：原子提交
   `f7e267d22cc626e4c79aeeac918ebb217d34be8e` 保持中央 gitlink 固定在 M1 输入，在 Pass C-1 真实暂停点
   保存唯一稀疏 Checkpoint，保持唯一下一动作、前进门槛和 PyTorch 返回点不变；移除两棵受 Git 跟踪的
   Skill 副本，把 `guide-learning`、`study-log`、`english-coach`、`memo-cards`、
   `resource-planning` 和 `playwright-cli` 同时配置给 Codex 与 Claude，并把流程、断点、学习偏好及入口
   文档改为中央行为规范的 PlanA 适配。提交后 materializer 生成 12 个受管入口，`--check`、结构校验、
   `study-log` 测试与全新会话恢复测试通过；恢复到 Pass C-1 唯一下一动作时零写且无 drift。受保护的
   Program、Lesson、证据和进度文件未改动，无关未跟踪用户工作未读取或提交；随后发布至远端 `main`。
6. **M5，中央删除旧入口（已完成）**：两个消费者的 materializer 检查、programming-lab 新流程前向验证、
   PlanA 稀疏 Checkpoint 保存与零漂移恢复、`study-log` 两种模式测试均通过后，中央提交
   `4ce419ced337b15937af03a93f26468c0ea2ddeb` 删除两个旧目录，并把 catalog 旧条目转为指向
   `guide-learning` 的 `retired_names`。programming-lab `a9dac09c744d94f11d20f8a6ee85404899a14099`
   与 PlanA `272e68cfc82cd91b26af12e46bb87609ea7bfb92` 随后固定该中央提交、重新 materialize 并通过
   `--check`、结构、单元和全新会话恢复验证；三个仓库均已发布并与远端 `main` 同步。

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
M0–M5 已经全部完成并发布。

## M5 完成边界

中央 C0–C3 与 M0–M5 已完成。M5 的最终结果继续受以下边界约束：

- 不借 M5 批量改写任何历史学习状态、进度、Checkpoint、文章或其他用户学习产物。
- 不修改 `guide-learning`、`study-log` 或其他 active Skill 的功能；只允许修复 active 文本中对已退役入口的机械引用。
- 不移动或删除 `learning-core-v1` 标签；消费者必须固定到已发布的中央提交并重新 materialize，不能引用未发布对象。

## 完成状态与后续边界

D1–D23 已完成本轮学习类 Skill 的职责边界、教学微循环、证据门槛、状态模型、事实源、日志策略、
最终身份、资源分层、最小 schema、内部接口、catalog 替代关系、验证矩阵、实现提交边界、旧入口退役与
分阶段迁移设计。当前没有仍需用户裁决的学习体验或实现方案缺口。

中央 C0–C3 已完成 catalog／工具基础、`study-log`、`guide-learning`、旧入口 rollback-only 切换、中央文档
和整体验证，M0 已完成公开远端发布，M1 已冻结并复验唯一迁移输入，M2 已接入两个消费仓库的空管线，
M3 已将 programming-lab 切换到两个中央 Codex Skill 并发布，M4 已将 PlanA 切换到六个中央双 host Skill
并发布，M5 已删除中央旧源码、登记 retired mapping，并把两个消费者升级到同一中央提交。分阶段迁移
M0–M5 至此完成；后续工作回到各独立 Skill 的质量评审，不再属于本轮学习核心迁移。

本轮中央实现覆盖 `guide-learning`、`study-log` 及两个旧主入口的完整退役链路；两个旧入口已从消费仓库
发现目录和中央源码树退出，旧名称只保留为指向 `guide-learning` 的机器可读 retired mapping，兼容源码由
`learning-core-v1` 标签保存。`english-coach`、`memo-cards`、`resource-planning` 保持独立的决定已经完成，
但它们各自进一步的质量升级仍属于后续独立评审阶段，不构成当前学习核心的阻塞项。

## 后续独立 Skill 质量评审（2026-08-11）

### D24：`english-coach` 采用窄触发、支架优先与默认零写入

`english-coach` 继续作为独立 Skill，但后续升级必须遵守以下已确认基础边界：

- **窄触发**：仅当用户实际使用英语，或以自然语言明确要求英语反馈、英语练习或英语回顾时激活。
  纯中文技术学习、普通技术讨论和仓库维护不自动追加英语反馈；与 `guide-learning` 同时适用时，前者只
  负责语言层，后者继续拥有技术教学流程。
- **支架优先**：英语回顾默认先提供 3–5 个与当前材料直接相关的核心表达支架，再进入主动表达和模拟
  对话；完整中英翻译范本不再默认展开，只在用户明确需要时提供。
- **默认零写入**：聊天反馈和英语回顾默认只存在于当前交互中，不自动创建或修改英语日志、卡片、
  学习记录或其他文件。需要持久化时再按具体目标取得授权；日志保存、`study-log` 素材提取与
  `memo-cards` 制卡是彼此独立的显式交接，不得由一次普通反馈隐式连锁触发。

此前已确认的自然语言交互偏好继续适用：升级后的 Skill 不保留 `/skip`、`/deep`、`/中文`、`/shadow`
或 `/quiz` 等快捷命令，等价控制全部通过正常对话表达。D24 只记录设计决策，尚未修改
`skills/english-coach`、消费仓库适配或 catalog 的 pending review 状态；其余教学细节、跨 Skill 接口和
验证方案继续共同评审后再实施。

### D25：`english-coach` 采用低打扰反馈、混合纠错与技术语义分流

在 D24 的窄触发、支架优先和默认零写入基础上，交互细节进一步确定为：

- **Ambient feedback 保持低打扰**：先完成用户当前的技术、学习或工作请求，再处理用户本人实际写出或
  说出的英语自然语言；代码、报错、引用、专有名词和 Agent 自己生成的文本不作为纠错样本。默认最多
  指出一个最高影响问题，并只在确有复用价值时补充一个词块；输入自然时保持安静，不固定追加
  “no changes” 占位反馈。
- **英语回顾采用混合纠错节奏**：标准回顾默认覆盖三个已学技术点，再做一次综合或迁移表达，约
  10–15 分钟，并允许用户用自然语言缩短、延长或随时停止。影响含义或命中本轮目标的问题立即纠正；
  轻微语法、节奏和低优先级问题延迟到两三轮后或收尾集中反馈。卡顿时按
  `关键词 → 句首 → 句型骨架 → 完整示范 → 延迟换一种说法` 逐级增加帮助，不把立即逐字复读当作掌握。
  收尾先由学习者作短总结，再按需提供 shadowing 范本。
- **技术语义与语言评价严格分开**：技术内容正确但英语不自然时只改语言；英语造成技术含义歧义时先
  澄清原意。高置信度技术错误只能先给一句独立警示并停止把错误结论用作英语范本；需要重新讲解、
  查证、练习或改变 mastery 时，先询问是否交给 `guide-learning`。`english-coach` 不修改 Lesson、
  Checkpoint、mastery、技术进度或学习时数，也不把语言卡顿记为技术理解失败。

D25 同样只记录已确认设计，不修改 Skill 实现或消费仓库文件。

### D26：自创 Skill 统一采用中央通用核心与消费环境可配置层

`english-coach` 不采用“中央核心 + PlanA 特例”的封闭结构，而采用可服务任意仓库或运行环境的两层架构：

- **中央通用核心**拥有不可因消费环境改变的触发、工作流、职责边界、安全规则、默认降级和验证语义；
- **消费环境可配置层**只提供该环境的学习者画像、目标语域、素材入口、路径映射、格式、工具能力和
  其他合法偏好，不复制或覆盖中央行为规则；缺少配置时核心仍能进行纯对话工作，并安全降级为零写入；
- PlanA 只是第一个配置实例，不在中央 Skill 中获得专用分支。后续其他自创 Skill 也应遵循同一原则，
  具体配置格式、发现协议和校验方式在实现前统一设计，而不是每个 Skill 各自发明适配机制。

`english-coach` 的素材读取权限同时确定为：明确开始英语回顾后，可直接使用当前可见对话，以及唯一、
已跟踪、与本次主题明确匹配的结构化学习记录；出现多个候选、本地修改、未跟踪文件、跨会话来源或
客户端历史时必须先确认。历史会话发现和提取始终交给 `study-log`，英语回顾本身不隐含该权限。

PlanA 的 `英语/ai-chat-prompt.md` 确认退出，不再作为无 Skill 平台的并列行为规范或生成兼容产物。
退役操作、引用清理和历史保留方式要在 `english-coach` 实施方案获确认后一起执行；D26 当前仍只记录
决策，不删除该文件，也不修改 Skill、消费配置或 catalog review 状态。

### D27：配置采用统一索引、受管上下文与三级授权边界

中央通用核心与消费环境配置层采用以下统一架构，作为 `english-coach` 及后续自创 Skill 的共同基础：

- **索引与内容分离**：消费仓库使用 `.agent-skills.json` 选择 Skill、host 并引用配置；仓库级公共事实与
  各 Skill 配置分别保存在 `.agent-skills-config/repository.json` 和
  `.agent-skills-config/<skill-name>.json`。每个配置文件采用带版本和 Skill 身份的严格 schema，只允许
  声明该 Skill 已登记的环境事实与偏好，拒绝未知字段。`english-coach` 可配置学习者水平、目标语域、
  反馈重点、允许使用的结构化记录种类和安全路径模式，以及获得当次保存授权后可使用的日志路径与格式；
  不得用任意 prompt、命令或配置字段覆盖触发、工作流、安全、隐私和默认零写入规则。复杂的人类可读
  仓库说明可以由配置安全引用，但只能补充环境事实，不能成为第二份行为规范。
- **生成受管上下文**：materializer 负责校验配置身份、版本、UTF-8、仓库内安全相对路径、链接／特殊
  文件和未知字段，并在 Codex 与 Claude 的生成 Skill 副本中写入逐字节一致的保留上下文快照
  `.agent-skills-context.json`。中央源码、消费配置和上下文摘要共同进入受管状态与完整性检查；配置变化后
  必须重新 materialize，`--check` 应能报告漂移。没有配置或没有经过 materializer 时，Skill 只运行
  中央通用核心，保持纯对话、零写入且不猜测消费仓库路径。
- **三类权限分开**：可提交的公共环境配置只保存适合进入仓库的事实；用户私有运行配置保存仓库外原始
  档案根等不能提交的信息；保存、覆盖、制卡、付费生成、发布、提交和推送等动作始终属于当次任务授权，
  不得由任何静态配置预先授予。优先级为“中央不可变约束 > 用户当前明确指令／授权 > 环境配置 >
  中央安全默认值”。`AGENTS.md`、`CLAUDE.md` 等入口只保留面向人的路由说明，不复制行为规则或机器路径；
  官方外部 Skill 继续原样引用上游，不注入这套自创 Skill 配置协议。

D27 只锁定配置架构和权限边界，尚未升级 `.agent-skills.json`、materializer、catalog、`english-coach`
或 PlanA。配置协议基础、Skill 改写、PlanA 实例与旧 prompt 退役必须在后续实施阶段分别验证并经用户授权。

### D28：`memo-cards` 采用通用质量核心、Markji 单一适配与受管生成产物

`memo-cards` 的产品边界与质量方向确定为：

- **通用核心、单一现役后端**：中央核心使用后端无关的卡片语义，负责显式触发、素材准入、原子化、
  事实状态、去重／冲突、预览和写入授权；第一版只实现 Markji 适配，不为尚不存在的第二个后端建设
  插件系统。PlanA 已完全以墨墨记忆卡为主，实施时清理仍把 Anki／cloze 写成现役事实的旧说明，
  不保留双后端分支。
- **严格素材与精选默认**：正式卡片只接收稳定、可追溯、已经核验且适合反复强化的结论；raw 对话、
  `[遗留]`、未作答题、猜测、冲突和未核验的时效事实只能进入 blocked preview。默认从候选中精选，
  全量转换必须由用户明确提出。每张原子卡只考一个回忆目标；需要较长回答的技术面试内容使用独立的
  综合口述卡，不把多个可独立考查的目标塞入普通原子卡。
- **受管生成、当次授权**：`cards/` 中由本 Skill 生成的目标是 generated-only 产物，但创建、刷新和覆盖
  仍须来自当次明确制卡请求，不能由学习收尾、`english-coach` 或其他 Skill 自动连锁触发。产物保存最小
  来源锚点／摘要、逻辑卡片身份和模板版本；来源范围变化、来源漂移或检测到人工修改时，必须展示
  add／change／remove／duplicate／conflict 差异并再次确认。幂等只承诺同一已批准候选集和同一适配版本
  的本地产物稳定渲染，不承诺重复导入 Markji 后仍自动去重。
- **PlanA 产物形态**：当前继续使用便于 Git 审阅的 Markdown 文档，每种卡型包含一个带表头的 TSV
  代码块。它应准确称为供粘贴进 Markji 下载表格的导入暂存文档，而不是可直接上传的 TSV 文件。

D28 只记录已确认方案；尚未修改 `memo-cards`、PlanA 的 Anki／Markji 重复事实、消费配置、历史卡片或
catalog review 状态。

### D29：Markji 适配固定为 3.8+ 精简兼容面

第一版 Markji 适配采用以下已确认兼容边界：

- 最低客户端版本为 `3.8.00`，默认支持答案线、行内／整行样式、`ans/...` 选择题、KaTeX 公式和
  已明确提供的公共链接；Markji 挖空作为可选卡型，不作为默认生成方式。
- Audio、图片和卡片引用依赖已有 Markji ID，第一版只能消费用户明确提供的 ID，不负责上传资产、发现
  ID 或自动建立跨卡引用。
- 官方内容语法 PDF／Markdown 作为本地评审证据保留，不整份复制进公开中央仓库。中央 Skill 只保存
  自行整理的最小兼容规范、官方来源链接、查阅日期与适配版本；PlanA 不再维护另一份会漂移的完整副本。
- 内容语法文档不等于表格导入规范；Markji 模板、字段顺序、TSV staging 和导入步骤继续由适配层的
  独立合同定义。由于官方文档未定义通用转义机制，验证器除 tab、裸换行和列数外，还必须检查
  `[T#`、`[F#`、`[Choice#`、`[P#` 等保留语法碰撞，无法证明安全时停止而不是猜测转义。

D29 只记录兼容方案，不复制第三方文档，也不修改现有模板、卡片或 Skill 实现。

### D30：PlanA 英语采用 8–12 张软目标而非每日硬上限

卡片生成数量与 Markji 实际安排的每日复习量分开处理。中央 `memo-cards` 通用核心不设置数量上限；
PlanA 英语在完成素材准入、原子化和去重后，默认以每个学习日 `8–12` 张**新增逻辑卡片**作为工作量
提示，而不是硬性截断或必须凑满的配额；刷新既有逻辑卡片不占新增数量：

- 所有 A 级高价值卡必须保留，不能因为达到数量目标而静默丢弃；强 B 级候选超过软目标时，预览应区分
  “建议本批导入”与“可延后导入”，展示总量与负担，并由用户决定全部导入或分批处理。
- 合格素材少于 8 张时按实际质量产出，不为凑数制造低价值卡；用户明确要求完整转换时，输出全部通过
  质量门槛且完成去重的卡片，不受软目标约束。
- 软目标只约束 PlanA 英语的默认精选体验，不进入中央通用质量规则，也不替代 Markji 自己的复习调度。
  数量选择本身也不构成创建、刷新、覆盖或导入授权。

D30 只修订评审方案；尚未修改 PlanA 英语指引、`memo-cards`、历史卡片或任何 Markji 数据。

### D31：卡片采用稳定语义身份、渐进接管与扩展后的 Markji 模板集

`memo-cards` 的卡片身份、历史产物刷新和第一版模板边界进一步确定为：

- **稳定逻辑身份**：一张卡由领域、稳定回忆目标、考查方式和事实范围共同确定；学习日期、来源路径、
  题面措辞、例句和场景不进入身份。同一目标跨日复发时保留 canonical 卡、提高优先级且不占 D30 的
  新增数量；只有含义、产出方向、考查能力或版本范围真正不同时才建立新卡。A 级卡超过 12 张时仍全部
  进入本批预览与可导入集合，分批只是用户可选项，不自动延后 A 级卡。
- **渐进接管历史产物**：机器元数据放在同一 Markdown 的 YAML frontmatter，不向 Markji TSV 增加
  身份或 hash 列；最小内容包括 schema、adapter／模板版本、来源摘要与 fingerprint、逻辑卡 ID、单卡
  内容摘要和受管正文摘要。现有无 manifest 的文件保持 legacy，不批量改写；只有用户明确刷新某个目标
  时，才展示 adoption diff 并经确认转成受管产物。人工修改、来源漂移、模板升级、拟删除卡片或预览后
  目标／来源变化都会使写入停止并要求重新确认；无语义差异时零写入。
- **跨日复发不自动改旧文件**：再次出现只抑制重复新行并报告 canonical 卡；只有新证据实质改善题面、
  答案、边界或例句时，才单独提议刷新旧目标。当前任务对新日制卡的授权不自动授权跨文件改写。
- **补齐 Markji 模板**：在现有纠错、选择、Q&A 和技术 Q&A 基础上，增加无真实错误时使用的主动产出
  模板、2／3／4 选项辨析变体、仅用于上下文可唯一确定 1–3 个词或词形的可选挖空模板，以及用 3–5 个
  评分锚点支持 45–90 秒回答的综合口述模板。挖空与公式只是渲染提示，不另造语义卡型。
- **合法表达不伪造错误**：语法成立但不够地道或语域不合适的表达不得进入带红叉的纠错卡；只有存在
  稳定、可迁移的使用边界时才生成 B 级辨析卡，否则不进入正式卡片。

D31 只记录已确认方案；尚未为历史文件加入 manifest，也未新增模板、刷新卡片或修改 Skill。

### D32：技术卡采用双时效范围、三层学习结构与独立研究生命周期

技术制卡不再把版本、学习层级和生命周期混成单一“卡型”，而采用三个正交维度：

- **常青与固定版本快照并存**：只有不依赖内部符号、默认值、目录、具体版本或单一 commit 的稳定概念
  才能标为常青；函数／类／目录名、进程数、路由公式、特定 codegen 行为、源码观察和仅由固定 commit
  支撑的架构结论默认归为 `产品版本 @ commit` 快照。不确定时先归快照，取得稳定接口或跨版本证据后
  才能提升为常青。软件升级时为改变的事实建立后继卡，不用新答案静默覆盖旧版本问题；与当前项目、
  面试目标或学习基线仍有关的旧快照继续保留，其余归档而不是删除。
- **原子、机制、综合口述分层**：原子卡只考一个判断、映射、前提或单一对比轴；机制卡允许一条不可拆的
  2–5 步闭合因果链；综合口述卡组合 2–5 张原子／机制子卡，形成 45–90 秒回答和 3–5 个评分锚点。
  综合卡不得引入子卡未核验的新事实；精确源码符号应从常青机制中拆成版本快照。任一子卡发生实质漂移
  时，依赖它的机制卡和综合卡一起进入复核。
- **研究项与个人误区分流**：生命周期采用 `candidate/research → active → review → active 或 archived`。
  未验证观察、疑似 bug 和能力猜想不进入正常 Markji 复习，交回 `guide-learning` 继续验证；可以把
  “确认此类结论需要哪些证据”制成常青方法卡，但不得把未决结论伪装成事实卡。只有反复出现、能预测
  未来错误的技术误区才进入独立个人误区集合并指向规范主卡；一次性措辞错误只吸收到客观辨析卡中。
- **本地状态不冒充远端状态**：`review` 与 `archived` 只约束本地受管暂存、预览和后续建议；Skill 不得
  声称已暂停、替换或删除 Markji 中的远端卡片，相关操作仍需用户在 Markji 中手动完成。

现有 PyTorch 卡中被后续文章实质纠正的结论应在明确刷新时进入复核或建立后继卡；现有 vLLM 卡则应视为
有效的 `v0.26.0 @ 568afb3a` 快照，而不是无范围的“当前 vLLM”。D32 当前只记录方案，不刷新这些历史
卡片，也不更改 Markji 数据。

### D33：跨 Skill 只传无授权素材包，制卡采用风险分级确认与派生 inventory

`memo-cards` 与其他 Skill 的交接、当次授权和消费配置边界确定为：

- **bundle 只传素材与边界**：统一 envelope 可以保存 schema、生产者／预期消费者、逻辑仓库／主题范围、
  带版本或 fingerprint 的来源引用、稳定条目、事实状态和 blocked 原因；不得包含 `authorized: true`、
  写入命令、任意 prompt、私有 archive root、绝对目标路径或自动执行标记。`guide-learning` 只交已核验
  学习证据，`study-log` 只交 structured 内容且 raw 永不制卡，`english-coach` 只交真实语言错误、主动
  表达与稳定辨析候选。bundle 到达、上游建议和静态配置都不触发 `memo-cards`，仍需用户自然语言明确
  提出制卡。
- **显式请求加风险分级确认**：只要求查看候选时保持纯预览；用户明确指定清晰来源、新目标并要求创建／
  保存时，该请求本身可以授权当次写入，不强制无风险任务再做一次形式化确认。受管目标无语义变化时
  零写入并报告 `no-op`。legacy adoption、人工漂移、来源范围变化、模板升级、删除、事实冲突、跨文件
  刷新或目标变化必须展示精确 diff 并再次确认；预览后 source、target、template 或 candidate digest
  改变时，旧授权失效并重新预览。
- **多产物请求仍保持独立事务**：用户一次明确要求保存学习记录并制卡时，可以一次点名两个目标并授权；
  内部仍分别校验、分别写入，任一上游失败后不得继续依赖其结果写下游，也不得顺带导入 Markji、提交
  或推送。
- **配置只保存环境事实**：PlanA 配置拥有允许的输入／输出 collection、路径模式、Markji profile、英语
  `8–12` 软目标和受管卡片扫描范围；不能关闭中央质量门槛、放宽安全校验、注入任意模板／prompt 或
  预先授予写权限。`.agent-skills-context.json` 只是 materializer 生成的受管快照，不成为另一事实源。
- **inventory 从受管产物派生**：第一版不建立中央卡片索引；只扫描消费配置允许的 `cards/` 范围内各
  Markdown manifest，得到 canonical inventory。legacy 文件仅参与保守重复提示，明确 adoption 前不
  进入自动刷新或确定性去重；未配置的其他仓库不参与跨库去重。

D33 当前只记录协议；尚未实现 bundle schema、消费配置、materializer context 或任何跨 Skill 自动化，
现有 `english-coach` 与 `memo-cards` 中违反这些边界的旧自动链路留待分别实施时清理。

### D34：`memo-cards` 采用精简入口、按需参考、单一模板资产与确定性工具

未来实施固定为以下最小结构：`SKILL.md`、`agents/openai.yaml`、四份一级 reference、一个 Markji 模板
注册资产、一个标准库 Python 工具和一组测试。四份 reference 分别拥有卡片质量／身份模型、受管产物／
diff／CAS 合同、Markji 3.8 精简兼容面和 Markdown＋TSV 暂存合同；不新增 README、CHANGELOG、示例
大全、完整第三方文档或 PlanA 专属模板副本。

- **入口保持精简**：`SKILL.md` 只保留窄触发、授权、来源范围解析、候选分流、预览／风险确认／写入流程、
  按需 reference 路由和职责边界；PlanA 路径、模板列序、完整语法、manifest 字段、hash 算法和大段示例
  均不进入入口。
- **Agent 与工具分工**：Agent 负责素材价值、事实状态、语义等价、A／B／C 评级、常青／快照判断以及
  题面、答案、例句和口述锚点；工具不得替代这些语义判断。单一 `memo_cards.py` 使用 `prepare`、
  `verify`、`publish` 子命令，独占逻辑 ID、模板占位符／列序、TSV 与保留语法校验、manifest／hash、
  inventory、确定性 diff、legacy adoption、路径安全、CAS 和原子写入；Agent 不临时手写这些脆弱结果。
- **模板只有一个事实源**：`assets/markji-3.8-templates.json` 保存注册模板 ID／版本、有序字段、字段类型
  和模板正文；工具断言字段顺序与 `{{...}}` 出现顺序一致，并按需输出供用户复制的模板，不再维护并行
  Markdown 模板。官方 PDF／MD 仍只作为外部评审证据。
- **manifest 可审计且可稳定解析**：同一暂存 Markdown 的 frontmatter 保存完整身份四元组而不只保存
  ID／hash；实现可采用 JSON 作为 YAML 子集的严格格式，使标准库稳定解析且不向 TSV 增列。相同输入、
  候选和模板必须逐字节稳定，不写仅用于制造 churn 的生成时间。
- **验证覆盖完整安全面**：单元测试覆盖模板注册、TSV／reserved syntax、身份与软目标、manifest／
  稳定渲染、diff／接管、CAS／原子失败、路径／链接逃逸；完成后再用两个全新 Agent 分别处理合成英语
  日志和技术材料，且不给它们泄露预期结论，以验证可迁移行为。

D34 完成 `memo-cards` 的方案级质量评审；当前仍不修改 Skill、模板、配置、历史卡片或 Markji 数据，
实施须在后续单独授权后进行。

### D35：`resource-planning` 采用专题研究、按需刷新与组合评审三模式

`resource-planning` 保留为一个独立 Skill，但中央通用核心不再把固定周更和月底评审写死，而使用三种
共享资源身份与证据模型、同时严格隔离副作用的显式模式：

- **`research`／专题研究**：围绕用户当前问题搜索、比较和推荐资料，默认只在对话中预览；保存研究简报
  需要当次明确授权，保存结果也不自动进入长期候选池。
- **`refresh`／按需增量刷新**：从上次成功覆盖终点或用户指定起点扫描到本次截止点，生成一份候选快照；
  周日等日历节奏只可作为消费环境提醒，不是中央运行前置。不能为了补缺伪造未实际执行的历史报告，
  也不能因发现候选而修改稳定课程。
- **`review`／资源组合评审**：只处理已经进入候选池且经过适当冷却的待评资源，决定晋级、延后、拒绝、
  替代或标记过时；不再要求“当月至少三份周报”，日历月末只作默认提醒。任何稳定资源组合变化仍须
  先展示逐项建议与精确编辑集，再由用户拍板；晋级不会自动启动学习。

三种模式绝不自动串联：research 结果不自动入池，refresh 候选不自动晋级，review 结果不自动交给
`guide-learning`。组合评审禁止广泛搜索和发现新候选，但可以重新打开候选已经登记的一手／官方来源，
对撤稿、链接可用性、作者归属、版本／后继关系和关键主张做最小定向复核；复核中意外发现的新资料只可
登记为后续 observation，不能偷渡进本次晋级。无法完成必要复核时标记待验证并延后，而不是猜测晋级。

PlanA 可以继续使用 `YYYY-Wxx` 报告名、周日／月末提醒和自身展示格式，但这些都属于消费配置。实际三份
已提交报告 W18、W26、W32 保持历史原样；后两份补缺约 8 周和 6.5 周的事实作为 `refresh` 设计依据，
当前不重写报告、不执行未曾闭环的历史月评，也不修改 Skill。

### D36：资源候选采用两层身份、claim 级证据与软决策负担

`resource-planning` 的候选质量模型确定为：

- **作品身份与具体版本分离**：`work_id` 标识稳定作品／项目线，优先使用 DOI、去版本号的 arXiv ID、
  GitHub `owner/repo` 或官方源原生 ID；`revision_key` 标识 tag、commit、arXiv vN、出版／接收状态等
  具体版本。标题、板块、报告期、镜像 URL、宣传名称和别名不产生新身份。论文、代码、博客等不同资源
  即使讨论同一主题也不直接合并，而通过 `version_of`、`updates`、`successor_to`、`complements` 或
  `conflicts_with` 关系连接；`replace` 是用户确认后的课程组合动作，不是资源天然关系。
- **跨报告去重按身份和关系判断**：原生 ID、规范 URL 或已登记 alias 的精确命中可以自动归并；仅标题／
  语义相似时只能标为 `possible_duplicate`，不得自动合并。同一资源的新 release、接收或获奖是版本／
  状态增量，不伪装为新资源；一个资源跨多个模块只保存一次并附多个映射。无实质增量的复发只更新
  `last_seen`／来源报告；是否需要刷新、替代或补充稳定组合另行评估。
- **每个关键主张独立绑定证据**：来源角色区分发现线索／索引、规范性一手来源、第一方工程观察、独立
  验证和教学／综述；“官方”不等于整篇材料自动可信。影响推荐或晋级的 claim 必须记录直接证据、来源
  角色、版本／硬件／配置范围以及 `verified | qualified | unverified | conflict`。搜索摘要、Trending、
  新闻和社交媒体只负责发现，不能单独支撑稳定晋级。
- **时间与覆盖范围可审计**：分别记录事件／发布或状态变化时间、实际核验时间和有效范围；易变接口、
  支持状态与最新 benchmark 在推荐／晋级时最小复核，固定版本历史不因变旧而自动失效。每次 refresh
  按来源或查询族输出 `covered | no-hit | blocked | skipped`；局部失败不得表述为全局无更新，也不得
  推进失败来源的覆盖游标。
- **硬门槛先于排序**：身份、一手锚点、窗口内事件或明确更新关系、配置范围、技术实质、重复／后继
  判断、关键 claim 证据与冲突状态未过门槛时，不得靠分数补回。通过后分别展示目标相关性、相对现有
  组合的信息增量、持久性及学习／维护成本，不再使用简单 yes 总票制或 star 数硬阈值。
- **数量只控制本轮决策负担**：PlanA 默认以 5 个 decision units 作为组合评审的软注意力目标，0 个
  完全正常，重大替代或同分边界可以超过 5。所有过门槛但未进入本轮的候选明确列为
  `qualified-deferred` 并说明原因；一项若需要两个独立课程编辑动作就计为两个 decision units，不能用
  “Top 5”静默丢弃其他强候选。

D36 只记录候选模型；当前不接管 legacy 周报、不建立 registry、不重新核验历史条目，也不修改任何稳定
课程或 Skill 实现。

### D37：资源治理采用单一 registry、保守接管与可恢复发布事务

每个消费仓库使用一个受管 registry 作为资源治理的唯一机器事实源；稳定学习指引继续拥有实际课程内容，
两者不互相复制职责。registry 保存资源与版本、claim／evidence、原子 decision-unit 候选、候选当前状态与
最小不可变决策事件、逐来源／查询族覆盖游标，以及 refresh run 对报告的引用与摘要。Markdown 报告只是带
`run_id` 与 registry generation／digest 的不可变人类可读快照，不拥有当前候选状态、游标或评审结果，
也不得从历史报告反向推导当前 registry。第一版不建立独立 review ledger；如需评审回执，只能从
registry 派生，不成为第二事实源。所有持久 lifecycle transition 与用户裁决都形成有序不可变 event；
event 序列是状态权威，`current_state` 只是 `reduce(events)` 的受校验投影。`verify`、`prepare`、
`publish`、`recover` 任一入口发现二者不一致都必须停止，不能猜测选择其中一份。

- **候选状态区分资格、批准与真正应用**：候选生命周期允许
  `draft -> blocked | qualified`；`qualified -> approved | blocked | deferred | rejected | superseded`；
  `blocked -> draft | qualified | rejected | superseded`；
  `deferred -> qualified | blocked | rejected | superseded`；`approved -> applied`；
  `applied -> stale | superseded`。`ready` 仅由
  `review_after` 与当前时间派生，`qualified-deferred` 只是当轮展示标签，二者均不落成额外状态。
  `approved -> applied` 只适用于 `add`、`annotate` 及 `replace` 的新资源／映射一侧；registry-only 的
  延后、拒绝或 supersede 裁决成功发布后，当前状态分别保持 `deferred`、`rejected` 或 `superseded`。
  `retire` 成功后旧资源／课程映射从 `applied` 进入 `stale`；`replace` 使新资源／映射进入 `applied`、
  旧映射从 `applied` 进入 `superseded`，不得把全部参与条目统一归约为 `applied`。
  `approved` 是绑定单次 `preview_digest` 的过渡与不可变决策事件，不是可长期复用的授权；用户确认形成
  仅限同一 `txn_id + preview_digest + decision units` 的 approval envelope。完整回滚后的同一事务重试
  和成功后的幂等检查仍可使用该 envelope，但不得跨事务、跨目标或在 CAS 漂移后复用。只有已确认的
  课程编辑集全部成功写入并通过验证后，当前状态才进入 `applied`；发布前漂移时 envelope 失效、registry
  保持批准前状态并重新预览。`refresh` 和独立 research brief 永不产生候选 `approved`／`applied`。
- **legacy 采用保守接管**：W18、W26、W32 保持原样，不补 manifest、不追加状态，也不把历史“晋级
  候选”自动变成当前 backlog。首次接管只提取可证明的身份、版本关系、来源与保守重复提示。中央核心
  要求每个尚无成功 cursor 的来源／查询族都有显式 bootstrap 窗口，但不写死天数；PlanA 的消费默认值
  为以实际截止点向前 30 天，并与 W32、稳定学习指引及 registry 中已接管身份去重。新增来源也独立使用
  该 bootstrap，用户明确指定的窗口优先。更早覆盖标为置信度未知，不伪造 legacy 的逐来源游标。只有
  某来源／查询族在本轮完整成功覆盖后，才为它建立或推进 cursor；失败来源保持原位置。
- **晋级预览绑定精确编辑集**：一次 review batch 的预览必须列出每个 decision unit、精确目标文件与
  slot、`add | replace | annotate | retire` 动作、计数／预算变化、必须保留的学习状态、逐文件 diff，
  并对候选、配置／adapter 版本和排序后的 before／after 文件摘要计算 `preview_digest`。用户确认的是
  该 digest；任一输入或目标变化都使确认失效并要求重新预览。
- **写面保持必要且不制造并行日志**：发布只更新 registry、确实发生课程组合变化的学习指引，以及消费
  配置明确要求且由该变化派生的模块进度投影。历史报告永不回写；不强制为现有指引新建 Changelog，
  不创建实际不存在的“月度评审日志”。总进度表只在配置声明且资料总数确实需要同步时更新；替代或注解
  默认保留原 slot、完成状态、日期和学习证据。Leetcode 等不同 schema 使用独立 adapter，不能套用
  统一红／黄／绿表格规则。资料晋级不等于开始学习，也不得修改 Lesson、Checkpoint 或 mastery。
- **多文件发布可恢复且幂等**：发布前对全部读取依赖与目标执行 CAS，在事务临时区准备完整 after bytes、
  验证结果与 rollback journal 后才原子替换。任一步失败都恢复原字节；进程中断后必须先恢复或完成遗留
  事务，不能直接启动新事务。`txn_id` 由已确认 decision units 与 `preview_digest` 确定，同一事务重试
  必须得到全量 no-op，不能重复分配 ID 或增加计数；后续撤销使用新的补偿决策，不改写历史。Git stage、
  commit 与 push 均不属于发布事务，仍分别需要用户明确授权。

D37 只记录 registry、legacy bootstrap 与发布合同；当前不创建 registry、不补扫最近 30 天、不修改历史
周报、稳定学习指引、进度、Skill 或消费配置，也不执行任何 Git 发布操作。

### D38：消费配置采用结构化 source/query 目录、声明式 adapter 与分层安全降级

`resource-planning` 继续使用 D27 的统一配置架构：`.agent-skills.json` 只选择 Skill／host 并引用配置，
仓库级公共事实放在 `.agent-skills-config/repository.json`，本 Skill 的环境映射放在严格校验的
`.agent-skills-config/resource-planning.json`。中央核心不认识 PlanA 的来源、八个模块、关键词、日历、
图标、路径或报告格式；PlanA 的 30 天 bootstrap 和 5 个 decision units 软目标都属于消费偏好。

- **source 与 query 由一个静态机器目录唯一拥有**：`sources[]` 使用稳定 `source_id`、受支持的来源类型、
  规范 locator、多模块映射、来源角色提示、启用状态和提醒偏好；共享来源只登记一次。URL 更新不更换
  `source_id`，来源拆分／合并必须显式迁移，不能静默继承 cursor。`queries[]` 使用稳定 `query_id`、
  provider-neutral 的 all／any／exclude terms、领域／资源类型范围和模块映射；不接受任意 prompt、shell、
  工具命令、页面选择器、凭据或私有令牌。配置中的“官方／第一方”只提示来源角色，不能跳过 D36 的
  claim 级证据门槛。cursor、last seen、candidate、run 和裁决状态只进入 D37 registry，不进入静态配置。
- **README 与模块订阅清单退为人类投影**：实施接管后，结构化 source/query 目录成为 source/query 静态
  定义的唯一事实源；D37 registry 继续独占动态治理状态。README §5 和各模块 `学习指引.md §长期订阅`
  只保留便于阅读的投影、说明或导航，不再互相声明权威，
  也不再由 Agent 解析 Markdown 来猜稳定 ID、来源类型或 cursor。现有 Markdown 在正式迁移前仍保持原样；
  迁移必须通过单独授权、对照预览和一致性验证，不能因本决策自动重写。
- **事实引用与临时 overlay 不复制计划正文**：配置通过稳定 fact ID 引用长期目标、当前焦点、目标岗位和
  学习预算等已跟踪事实文件；module portfolio／progress 路径只在模块条目中声明一次。临时专项（例如
  JD 冲刺）使用带 ID、事实引用、适用范围、优先级和有效期的 overlay，只影响相关性排序，不覆盖长期
  主计划、不修改 Lesson／Checkpoint，也不自动扩大搜索范围。每次 research／refresh／review 明确记录
  实际启用的 overlay；缺失或过期时不得猜测沿用。
- **模块与投影只使用中央白名单 adapter**：每个 `modules[]` 条目声明稳定 module ID、显示名／别名、
  portfolio 路径、可选 progress projection、报告分组，以及中央登记的 adapter ID／version。配置只可
  声明 heading／anchor、ID policy、合法动作和状态／优先级词表，不能注入解析代码、模板逻辑或行为规范。
  精确课程内容归 `学习指引.md`，动态候选治理归 registry，扫描定义归静态目录；Leetcode 等不同 schema
  使用独立 adapter，不能被通用红／黄／绿投影强行改写。
- **按失败层级安全降级**：无配置、未 materialize 或 schema 非法时，只允许用户主题驱动的 `research`
  对话预览，禁止持久 refresh／review、registry／报告写入和路径猜测。配置有效但单个 source／query 因
  联网、登录或页面失败时，其余项可继续；失败项记 `blocked` 且不推进 cursor，明确无命中才记
  `no-hit`，未选择才记 `skipped`。缺 portfolio、匹配 adapter 或该候选 required hard-gate fact 时可以
  保留 observation，但受影响 candidate 不能通过门槛、获批或应用；可选 fact 缺失只披露不确定性并降低
  排序置信度，不阻塞无关候选。registry／报告目标不安全时退化为零写预览。
- **配置路径和权限保持最小可信面**：仓库事实文件必须是 UTF-8、Git tracked regular file；若配置声明
  目录／collection，其解析结果也只能包含 Git tracked regular files。拒绝绝对路径、`..`、符号链接／
  junction、未知字段、重复 ID、未跟踪文件及穿过 gitlink／submodule 的路径。manual／私有渠道默认只作
  discovery signal，内容由用户当次提供或通过仓库外私有运行配置获取。
  source／config／adapter／目标摘要都进入 D37 的 preview digest 与 CAS。静态配置永不预授权启动付费
  网络操作、写入、覆盖、接管 legacy、晋级、发布、提交或推送，也不得保存 approval token 或已确认摘要。

D38 当前只确定消费配置合同；尚未升级 `.agent-skills.json`、materializer、context snapshot、Skill、
README §5、模块订阅清单或任何 PlanA 文件，也未读取或接管未跟踪文件。

### D39：`resource-planning` 采用三份按需参考、单一确定性工具与无泄漏前向验证

未来实施固定为以下最小 Skill 包：

```text
resource-planning/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── resource-model.md
│   ├── evidence-and-ranking.md
│   └── registry-and-publishing.md
├── scripts/resource_planning.py
└── tests/test_resource_planning.py
```

不新增 `assets/`、README、CHANGELOG、示例大全、独立 schema 文件、adapter manifest、review ledger、
中央 registry 样本或 PlanA 模板副本。只有将来出现体量较大、几乎不含逻辑且直接复制进产物的稳定模板，
才重新评估 `assets/`。

- **入口只拥有路由与最短公共流程**：frontmatter 精确覆盖专题资料研究、受管来源刷新和资源组合评审；
  `SKILL.md` 只保存三模式路由、默认副作用、最短授权流程、与 `guide-learning` 的边界、工具调用顺序和
  reference 路由。`research` 的普通比较只加载 `evidence-and-ranking.md`，需要结构化身份时再加载
  `resource-model.md`；`refresh`／`review` 读取三份 reference，任何 registry、报告或课程组合写入前都
  必须读取 `registry-and-publishing.md`。三模式不再另建重复的 mode reference。
- **三份 reference 各自只有一个职责**：`resource-model.md` 只定义 `work_id + revision_key`、关系、
  claim、候选状态／事件与不变量；`evidence-and-ranking.md` 只指导 Agent 判断来源角色、技术实质、冲突、
  信息增量、持久性、成本与 decision-unit 顺序，不复制 schema；`registry-and-publishing.md` 统一拥有
  D37／D38 的 registry、消费配置映射、cursor、不可变报告、preview digest、CAS、事务恢复、legacy
  bootstrap 与路径安全。超过 100 行的 reference 在顶部提供目录，所有引用保持 SKILL 一级可达。
- **Agent 独占语义判断与用户沟通**：Agent 决定研究问题、搜索策略、来源／claim 含义、语义重复、资源
  关系、硬门槛是否满足、目标相关性、信息增量、成本、排序、课程编辑建议和人类可读理由；展示完整预览
  并取得用户对精确 decision units 的自然语言确认。Agent 不手写稳定 ID、状态跃迁、cursor、digest、
  registry merge 或多文件事务，也不把搜索摘要当成已核验事实。
- **单一标准库工具独占脆弱确定性操作**：`resource_planning.py` 提供 `verify`、`prepare`、`publish`、
  `recover` 四个子命令。`verify` 只读检查配置、registry、派生 ready、cursor 与未完成事务；`prepare`
  接收 Agent 已完成语义判断的 proposal 与 `operation_kind`，规范化精确原生 ID，并在仓库零写入的前提
  下生成 after bytes、完整 diff、全依赖摘要、`preview_digest` 与 `txn_id`。所有将写入的 event、状态、
  generation 和报告／registry bytes 都必须在 `prepare` 时完整确定并进入 digest；`publish` 不得临时追加
  timestamp、用户文本、actor 或重新计算的 generation。`publish` 只接受与 operation 和预览逐字节匹配、
  绑定同一事务的 execution envelope，重验全量 CAS 后执行可恢复原子发布：`research-brief` 只保存明确
  授权的独立简报，不入 registry／候选池；`refresh` 写 run、coverage、cursor、候选资格事件与不可变报告，
  不产生 `approved`／`applied`；`review` 才消费逐项 approval envelope，需要课程投影的成功动作记录
  `approved -> applied`，registry-only 的 defer／reject／supersede 则写入对应 outcome。`recover` 只机械
  处理现有 journal，不接收新候选、不重新分配 slot 或推断新编辑集。工具不提供 `--yes`、`--force`、
  `--skip-cas`、`--accept-latest`，也不联网、不调用 shell／Git、不判断技术真伪、不做语义近似合并或
  代替用户决定课程价值。
- **恢复协议只有可证明的机械分支**：journal 只保存事务 phase、精确目标、before／after bytes 或受校验
  临时文件、摘要与已完成替换集合。新 publish 遇到未完成 journal 必须停止；全部目标已经是 after bytes
  时，必须先重验 journal 完整性、全部 after digests 与 adapter postconditions，成功后才完成收尾；只
  出现 journal 可证明的 before／after 混合时按替换逆序恢复全部 before bytes，任一目标既不是 before
  也不是 after 时停止并报告人工冲突。发布顺序固定为投影先、registry 最后：refresh 先写不可变报告，
  review 先写指引／必要进度投影，最后才替换声明 current state／cursor／`applied` 的 registry。后验验证
  失败保留 journal 并回滚，不能留下 registry 已声称成功而投影未完成的状态。成功后删除 journal；业务
  撤销使用新的补偿 decision，不把 recovery journal 变成第二事实源。
- **配置／adapter schema 只实现一次**：字段、adapter allowlist 与 context 校验由
  `resource_planning.py` 的只读接口唯一拥有；materializer 调用同一实现来验证并生成受管 context，
  不复制资源规划字段规则。运行时工具只消费 materializer 已验证、已纳入 digest 的 context／allowlist，
  不自行调用 Git 判断 tracked 状态。该集成会涉及 materializer 及其测试，但必须作为后续实施的明确
  提交边界，不借本次方案评审提前修改基础设施。
- **验证覆盖结构、安全与真实迁移行为**：单元测试覆盖精确身份／alias、`possible_duplicate` 不自动合并、
  claim 结构、合法与非法状态跃迁（含复核失败回到 blocked、retire 进入 stale、replace 的新旧分流）、
  派生 ready、`approved != applied`、局部失败与逐源 cursor、单一
  registry、事件归约与 `current_state` 一致、不可变报告、配置化 bootstrap 窗口与 decision-unit 软目标、
  无配置时不暗设 30 天、用户窗口优先、新来源独立 bootstrap、稳定渲染／零 churn、preview 后任一依赖
  漂移、每个原子替换点的故障／恢复／幂等、registry 最后替换、路径／链接逃逸、未授权目标、journal
  篡改和第三态目标。测试还必须封死 socket／HTTP、subprocess／Git 调用，并断言 refresh 不覆盖历史
  报告且不产生 `approved`／`applied`、review 不回写报告、blocked／skipped 不推进 cursor、特殊 adapter
  不产生未声明的通用进度投影。Skill 内可用 30 与 5 作为合成配置值，但不得硬编码 PlanA 路径、W18／
  W26／W32 或八模块事实；真实 PlanA 首次接管另属消费仓库集成验证。根级结构测试另检查精确文件树、
  三份 reference 均由 `SKILL.md` 一级链接、入口少于 500 行、`agents/openai.yaml` 字段和中央运行时文本
  不含 PlanA 或消费路径。

实施完成后使用两个全新 Agent 做无答案泄漏的前向验证：一个在无配置仓库中完成证据化专题研究且零写入；
另一个在合成 PlanA 型仓库中完成首次 refresh 与一次 review，覆盖 blocked 来源、legacy 重复、新 revision、
超过 5 个 decision units、预览后目标漂移和事务中断。验证任务只提供 Skill 与原始场景，不泄漏设计结论，
不访问真实网络或生产数据。

D39 完成 `resource-planning` 的方案级质量评审；当前仍不修改 Skill、materializer、配置、registry、
README §5、历史周报、学习指引或进度，也不执行首次 refresh、发布、提交或推送。未来实施必须另行授权，
并按配置基础设施、中央 Skill／工具、PlanA 接管和前向验证拆分为可独立审查与回滚的阶段。

## D24–D39 实施记录（2026-08-11）

用户随后单独授权实施三项学习辅助 Skill。中央仓库现已完成 `english-coach`、`memo-cards` 与
`resource-planning` 的通用核心、严格配置 validator、metadata、按需 reference／确定性工具及安全测试，
并为 materializer 增加向后兼容的 version 2 配置索引和受管上下文。三项中央运行时不含 PlanA 路径、
历史周报、八模块或旧英语 prompt 分支；静态配置仍不构成保存、覆盖、制卡、付费、发布、提交或推送授权。

最终中央验证为 `197 passed, 4 skipped, 46 subtests passed`；四个跳过项均是当前 Windows 环境缺少
符号链接／junction 权限的防护用例。catalog 校验为 11 Skills（6 first-party、5 official external），三项
Skill 的结构校验均通过。四个隔离的前向场景还分别覆盖英语制卡、技术卡多层依赖、无配置专题研究以及
受管 refresh／review／中断恢复；过程中发现的 GBK CLI 输出、复核状态 churn、漏 coverage、跨模块写入、
历史报告完整性和读写重叠问题均已修复并原场景复测通过。

本记录只表示中央实现已形成可提交候选。PlanA 的 version 2 配置、旧 prompt／资源 SOP 退役、资源 slot
标记、registry bootstrap、历史卡片渐进接管、中央子模块升级与重新 materialize 仍是后续消费适配阶段；
当前未修改消费仓库、未提交、未推送。

## 延期待办：`creator-workflow` 质量评审、通用化升级与 `daily-work` 适配迁移

`creator-workflow` 是当前唯一尚未完成方案级质量评审的 first-party Skill。按用户决定，本项暂缓到三个
学习类 Skill 的升级实施完成之后，不与当前学习类改造交叉推进。后续工作必须依次覆盖：

1. 只读审计中央 `skills/creator-workflow`、`daily-work` 的实际创作流程、入口、第三方官方 Skill 路由、
   产物写面与真实使用证据，区分可复用核心、消费环境事实和应退役的专用约定；
2. 与用户共同完成质量评审和升级方案设计，目标同样采用“中央通用核心＋严格消费配置层”，并确定触发、
   工作流阶段、授权、状态／产物所有权、失败恢复、官方 Skill 交接和验证门槛；
3. 在单独授权后升级中央 Skill、metadata、references／scripts／tests、catalog review 状态和配置协议，
   不把 `daily-work` 路径、品牌、频道、模板或发布凭据硬编码进中央核心；
4. 再单独实施 `daily-work` 适配迁移：新增消费配置与事实映射、清理旧行为副本、升级中央子模块指针、
   materialize／check 两个 host 所需入口，并保持用户工作产物与无关未提交改动不变；
5. 运行中央单元／结构测试、合成前向验证和 `daily-work` 集成验证，通过后才建议提交与推送。

当前只登记待办，不开始 `creator-workflow` 评审，不修改该 Skill、`daily-work`、其子模块指针或生成入口。
