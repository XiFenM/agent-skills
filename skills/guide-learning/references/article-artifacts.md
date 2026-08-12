# 按需学习文章

学习文章把一个已经形成完整心智模型的主题，整理成按问题与论点组织、可供以后阅读和应用的知识产物。
它不是教学流程的默认收尾，也不是学习过程日志、Lesson 状态或 mastery 证据本身。

## Contents

1. [先通过两个授权门](#先通过两个授权门)
2. [与其他产物分工](#与其他产物分工)
3. [通用骨架](#通用骨架)
4. [应用表达与领域透镜](#应用表达与领域透镜)
5. [选择目标与文件名](#选择目标与文件名)
6. [公共配置形状](#公共配置形状)
7. [最终核对](#最终核对)

## 先通过两个授权门

1. 只有主题已经完整到值得整理时，才自然提议文章。提议不创建文件，也不把文章列为完成 Lesson 的门槛。
2. 只有用户明确要求文章，并确认素材范围、目标读者或用途后，才起草。若要落盘，还需用户对本次目标文件
   的明确写入授权；配置中的 target 和 materializer allowlist 都不授予写入。

用户只要求草稿时在对话中交付，不要因为配置了目标目录而保存。用户一次性明确要求“根据这些素材写入这个
目标”时，可以把起草与写入视为同一次授权，但仍要核对目标位于已配置 collection 内且不会覆盖未知文件。

## 与其他产物分工

- **学习文章**按主题、问题和论点组织经过核验的理解；把纠错融入正确模型，而不是复刻纠错发生顺序。
- **`study-log`**保存学习者回答、误区、纠正、转折和高价值问题等过程证据。需要对话流水、消息边界或原始
  对话时交给它，不要把文章写成日志的另一份副本。
- **Lesson ledger**保存目标、授权、evidence 和 mastery。文章只链接这些事实，不拥有或改变它们。
- **`memo-cards`**负责从稳定、可核验材料生成记忆卡；文章完成不自动触发制卡。

生成文章不得自动关闭 Lesson、宣布 mastery、移动 Checkpoint，或把未验证推断升级为事实。

## 通用骨架

按配置选择下列 section，但只写有材料支持且对目标读者有价值的部分。不要为了填满模板创建空标题或重复内容。

### 必需 section

- `source-and-scope`：列出实际使用的来源、revision 或访问边界，并说明文章覆盖与不覆盖什么。不要把来源清单
  当成论证本身。
- `question-or-goal`：明确文章要解决的问题、形成的能力或面向的应用目标。
- `thematic-understanding`：按主题节点解释中心模型、机制和边界。把已确认的纠错合并进正确叙述，并在需要时
  保留反例、适用条件和不确定性；不要按对话轮次排列。

### 可选 section

- `retrospective`：提炼理解如何改变、哪些旧模型最容易误导以及可迁移的经验；不要复述整段学习过程。
- `practice-evidence`：只在实际完成练习或实验时写入。区分事前预测、运行条件、观察、解释和仍未验证的结论。
- `downstream-application`：说明如何用于后续工程、研究、决策或新的学习任务，不虚构已经完成的迁移。
- `question-and-answer`：只收录能澄清关键边界的少量问答，不复制完整对话。
- `summary`：给出与正文一致的短收束，不引入新事实。
- `open-items`：列出尚未验证的问题、适用范围或下一步核验；不要把它变成自动执行的 backlog。

默认前三项为 required，其余为 optional。配置可以在保持前三项 required 的前提下收窄或扩大选用范围。optional
表示“有证据且有价值时可用”，不是必须全填。

## 应用表达与领域透镜

- `language` 控制主要写作语言；缺失时结合仓库语言和用户本轮要求选择。
- `tone_profile` 只从 `neutral-explanatory`、`peer-explanatory`、`technical-reference`、
  `reflective-first-person` 中选择。语气不改变事实标准。
- `domain_lenses` 只允许中央枚举：
  - `engineering-practice`：突出实现边界、故障模式和验证方法；
  - `source-code`：突出代码所有权、调用关系和 revision 锚点；
  - `interview-transfer`：突出可解释的取舍和迁移问题，不把文章写成题库；
  - `historical-experience`：连接已经存在的经验，不杜撰经历；
  - `quantitative-example`：优先使用有条件、有单位、可复核的数字例子；
  - `counterexample`：用反例澄清边界，不为制造戏剧性而虚构失败。

透镜是选材与强调提示，不是新的固定 section。PyTorch、推理框架或其他仓库专有领域映射应放在一个只读
repository fact 中，并以 `article-profile` 角色引用；不要把具体领域、自由 prompt 或执行命令塞进公共配置。

## 选择目标与文件名

`article_profile.targets` 可以声明多个既有文章 collection。每个 target 只提供 ID、collection 和有限命名策略：

- `topic`：以主题命名；
- `yyyy-mm-dd-topic`：以日期和主题命名；
- `lesson-id-topic`：以稳定 Lesson ID 和主题命名；
- `sequence-topic`：沿用已有编号文章集合的顺序前缀。

多个 target 都可能适用时，根据已确认主题和只读仓库 profile 选择；仍有歧义就让用户选一个。不要为了适配
配置另建第二棵文章目录。使用 `sequence-topic` 时先核对现有命名约定和下一个可用编号，不能猜测编号或覆盖
旧文章。任何策略都只派生候选名称；写入前仍须展示或明确目标文件。

目标 collection 是机械写入上限，不是扫描、创建、覆盖或持续写入授权。若同一目录还要作为已有文章的只读
事实源，必须另以 `knowledge-artifacts` 角色显式引用完全相同的 collection；target 本身不授予读取。不要在
文章目标中保存当前 Lesson、Checkpoint 或 mastery 的唯一事实。

## 公共配置形状

`article_profile` 整体可选；缺失时保持原有 `guide-learning` 行为。存在时必须是非空、纯声明对象：

```yaml
article_profile:
  language: zh-CN
  tone_profile: peer-explanatory
  sections:
    required:
      - source-and-scope
      - question-or-goal
      - thematic-understanding
    optional:
      - retrospective
      - practice-evidence
      - downstream-application
      - open-items
  domain_lenses:
    - engineering-practice
    - source-code
  targets:
    - id: module-articles
      collection: learning/articles
      filename_policy: sequence-topic
```

`targets` 若出现必须是非空数组；不同 collection 必须大小写唯一且互不构成祖孙路径。公共配置拒绝未知字段、
自由 prompt、命令、绝对路径、父目录跳转和运行时授权字段。

## 最终核对

起草或写入前确认：

1. 素材边界、来源 revision、目标读者或用途已经确认；
2. 文章按主题综合，而不是伪装成文章的对话记录；
3. 事实、观察、推断和遗留问题没有混为一谈；
4. 只使用实际需要的 section 与透镜，没有为模板凑内容；
5. 若写入，目标 collection、候选文件名和本次授权均明确；
6. 没有因为文章完成而改写 Lesson 状态、Checkpoint 或 mastery。
