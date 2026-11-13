# 技术写作的生动表达：研究底稿

> 2026-11-13 · 为 `vivid-tech-writing` Skill 提供来源、提炼与设计依据
> 状态：研究完成，Skill 已实现并通过本地校验，待提交

## 问题

面向技术博客、教程、技术分享与知识视频的作者，常见的失败不是“讲错”，而是“讲得像教材”：定义先行、名词化、无主语、信息平权、没有悬念，读者每字都懂，却不知道为什么要读下去。

需要回答三个问题：

1. 网上和书里那些“有趣又讲得清楚”的技术表达，有没有可迁移的共同动作？
2. 这些动作能不能拆成 Agent 可以执行、可以检查的步骤？
3. 中文技术写作有没有额外的、独立于英文的问题？

## 结论

**教材腔的根源不是专业，而是把知识从经验里抽走了。** 生动的技术表达，几乎都在补回三样东西：

- **场景**：读者今天已经经历过的一个画面。
- **人**：一个会犯错、会兴奋、会判断的作者。
- **变化**：从“不知道”到“知道”的过程，而不是整理好的结论。

一个可操作的公式：**教材的骨架 + 科普的血肉 + 童书的眼睛。**

由此提炼出 7 个诊断病灶、9 个可迁移动作、6 段逐句解剖、1 套文章转视频流程和 1 个中文翻译腔修正层。它们构成 Skill 的 `references/`，不是一份供人阅读的长文。

## 方法与核验

- 先中文、后英文检索：科普写作方法、科普书、童书、技术教材、技术博客、知识视频。
- 能回到原文的尽量回到原文：Feynman Lectures、Distill、Julia Evans、Bartosz Ciechanowski、Crafting Interpreters、曹天元第一章摘录等；找不到原文的用书评、书介或作者页，并在 `references/source-library.md` 标注入口性质。
- 引文只保留分析所需的最短片段；中文引文与英文引文都做了交叉核对。
- 不把“畅销”当作唯一标准；选材标准是：能拆出具体动作、有可获得的入口、跨媒介（书负责结构，文章负责句子，视频负责节奏）。

## lineage 说明

`catalog.json` 里本 Skill 的 `lineage` 记录的是**本文件的首次提交**（`57e7bb6b9e0e9907621a2cb67e7df5b0f9e9eb7c`）：它证明这套方法的提炼过程有可追溯的仓库内底稿，而不是“改编自某个 Git 仓库”。研究来源是下列公开书籍、文章与视频，无法用 Git commit 表示；`references/source-library.md` 逐条给出入口。这样登记是为了满足 schema 对 first-party 来源字段的要求，同时不伪造上游仓库。

## 核心语料

| 来源 | 取什么 | 入口 |
|---|---|---|
| Carl Sagan, *Cosmos* | 不定义，先给身体反应；“We know”把读者拉进共同体 | [开篇引文](https://www.flavorwire.com/487357/astounding-carl-sagan-quotes-about-the-wonders-of-the-cosmos) |
| Bill Bryson, *A Short History of Nearly Everything* | 第二人称、恭喜读者、650,000 hours、用术语清单骂教科书 | [开篇原文](https://m.zhangyue.com/readbook/12780096/5.html) |
| Richard Feynman, *Lectures on Physics* I-1 | “只能留一句话”的极端约束；连续放大；网球代替分子 | [Caltech 在线版](https://www.feynmanlectures.caltech.edu/I_01.html) |
| Robert Nystrom, *Crafting Interpreters* | 第一人称兴奋、私人致歉、冷笑话、“魔法感把我排除在外” | [Introduction](https://craftinginterpreters.com/introduction.html) |
| Bartosz Ciechanowski, *Gears* | 热天风扇开场；滑块；先观察后命名 | [Gears](https://ciechanow.ski/gears/) |
| 曹天元《上帝掷骰子吗》第一章 | 把物理史写成帝国兴衰；排比制造全盛，短句制造转折 | [豆瓣摘录](https://book.douban.com/annotation/123587187/) |
| William Zinsser, *On Writing Well* | 删冗余；“clutter is the disease” | [全文存档](https://archive.org/stream/OnWritingWell/on-writing-well_djvu.txt) |
| Joseph Williams, *Style* | 主角作主语，动作作动词 | [教学 PDF](https://nus.edu.sg/nuslibraries/docs/default-source/writing-communication-hub/grammar-style-actions-characters.pdf) |
| Randy Olson, *Houston, We Have a Narrative* | ABT（And / But / Therefore） | [图书馆记录](https://ebooks.mpdl.mpg.de/ebooks/Record/EB002202904) |
| Julia Evans, jvns.ca | 第一人称、手写 zine、写“我不懂的时候” | [How I made a zine](https://jvns.ca/blog/2016/08/29/how-i-made-a-zine/) |
| Distill, *Research Debt* | 把解释当成研究工作；解释会改变想法 | [Research Debt](https://distill.pub/2017/research-debt/) |
| 余光中《论中文的常态与变态》 | 欧化中文的化简为繁；名词化与被动 | [节选](http://www.rmzxw.com.cn/c/2017-09-04/1768389.shtml) |

完整 40 条语料见 `skills/vivid-tech-writing/references/source-library.md`。

## 提炼结果

### 七个病灶

名词化、无主语、抽象悬空、信息平权、零悬念、术语前置、没有“我/你”。

### 九个动作

1. 从身体经验开场
2. 先给画面，再给名字
3. 尺度锚点
4. 类比三段式（像什么 / 为什么像 / 哪里不像）
5. 让读者先猜一次
6. 故事骨架（ABT / OCAR）
7. 幽默与人格
8. 可视化即论证
9. 结尾回响

### 六段精读

Sagan、Bryson、Feynman、Nystrom、Bartosz、曹天元。每段按“他先做了什么 / 他故意没做什么 / 我能偷什么”拆解。

### 视频改写

书面语靠从句，口播靠语序、重复、停顿；开场 15 秒 = 画面 + 反常识 + 承诺；每 30–45 秒一个变化；画面给“看见”，口播给“为什么”。

### 中文特化

空动词、抽象后缀、被动、“的”字链、连接词冗余；术语四条规矩；句号是呼吸，破折号是调味品。

## 两轮实践补充（2026-11-13）

Skill 发布后，用两份真实技术讲义做了两轮“口语化 / 生活化”改写，反过来补了方法。

### 案例一：量化映射

原文是“定义先行 + 公式先行”。最有趣的冲突——离群值 12 把整块刻度的精度拖粗，让 −0.8 和 −0.7 都重建为 0——被埋在第二张表和第八十八行。

改写做了三件事：

- 开头先给这个反直觉结果，再解释；
- 把五个码的具体映射表提到公式前，问“码 4 为什么是 0”；
- 用“尺子”贯穿 scale/zero point，用“全班合影”解释离群值，用“每行/每四人一把尺子”解释粒度；每个比喻都标边界。

指标：平均句长 18.2 → 15.5 字，长句 1 → 0，问句 0 → 3，第一/第二人称 0/0 → 3/3。原文 69 个数字全部保留。

### 案例二：AWQ 实际路径

原文最卡的地方是“先做等价变换”一节：读者能看懂 $X'W'^\top=XW^\top$，但不知道对角矩阵在真实实现里到底怎么落地。

改写把“实际怎么做”拆成：

- 一句话答案：重要通道权重放大，输入除回去，数学不变但量化器看到的权重变了；
- 一张流程图：校准 → 统计激活 → 搜 α → 权重乘 s → 量化 → 折进前一层；
- 两个阶段并排：搜索时用 $Q(W\cdot s)/s$ 模拟输入补偿；部署时把 $1/s$ 折进 LayerNorm/Linear/GELU；
- 两个 scale 并排：$d_k$ 是通道缩放，$s_g$ 是量化步长；
- 一个误导变量名的修正：代码里的 `x_max` 实际是 `mean(|x|)`，正文改用 $a_k$，保留原名注释。

指标：平均句长 18.6 → 15.3 字，长句 1 → 0，问句 0 → 4。原文 74 个数字全部保留。改写版更长，因为补的是“怎么落地”，不是修辞。

### 提炼出的新层

两轮都指向同一件事：**读者卡住，往往不是句子太长，而是“发现的顺序”被整理成了“定义的顺序”。** 口语化不是加段子，而是换顺序、换锚点、换句子。具体沉淀为 `references/plain-language.md`：

1. 难节开头先给一句话答案；
2. 给一张流程/阶段图；
3. 用一个日常物件当主线比喻，2–3 个辅助，每个标边界；
4. 把两个容易混的东西并排放；
5. 口语化是短句、直接称呼、具体动词，不是段子化；
6. 变量名误导时换符号，保留原名注释；
7. 比喻不能替代数字和 caveat。

## 跨 Skill 语言契约（2026-11-13）

`guide-learning`、`lesson-pages`、`memo-cards` 都输出解释性文字，原本各自带一部分语言指导。把这些指导收束成一个中心：

- 新增 `references/language-contract.md`：十条通用契约、难懂机制的四件套、按体裁（技术文章、教学讲解、课程网页、学习文章、记忆卡片、视频口播）、体裁对照表、共享检查清单、交接边界。
- 三个 Skill 只保留与自身结构强绑定的规则：教学深度阶梯、页面布局与交互、卡片拆分与 Markji 格式；语言原则改为短指针 + 2–4 条本地底线。
- 不在 Skill 目录之间写相对链接：materializer 可能只复制其中一个 Skill，跨目录相对路径会断。统一用“`vivid-tech-writing` 的 `references/language-contract.md`”这种具名引用；未启用时按本地底线执行。
- 冲突顺序：事实、边界、授权优先；其次是结构/状态；最后才是语言。

这次收束解决了一个真实矛盾：vivid 强调“短句”，guide-learning 和 lesson-pages 强调“清晰完整优先于句子短”。契约里的写法是：**短句是节奏工具，不是删信息的许可证；先保证主语、条件、因果完整，再把长句拆短。**

测试：`tests/test_vivid_tech_writing.py` 检查契约覆盖六种体裁；`tests/test_learning_skills.py` 检查三个 Skill 都指向契约。`lesson-pages` 的模板预算 179,818 > 170,000 是基线已有的失败，与本轮语言收束无关。

## 为什么做成一个 Skill，而不是多个

文章、视频、诊断、练习共享同一套底层动作。拆成多个 Skill 会造成三种重复：同一套九动作写三遍、触发边界互相重叠、用户要在“诊断/改写/视频”之间自己选。做成一个 Skill，用 `diagnose`、`rewrite`、`draft`、`video`、`coach` 五个模式分流；`references/` 按需读取，`SKILL.md` 只保留路由和硬约束。

## 为什么不做 context validator

`vivid-tech-writing` 是**无状态写作教练**：输入是用户给的草稿、素材和偏好，输出是文本、诊断和镜头表。它不读写消费仓库的学习记录、卡片、资源或发布状态，因此不需要受管上下文，也不应借配置获得任何写入授权。用户的声音样本在对话中提供；如果未来需要“仓库级风格指南”，应另立一个有明确写入边界的 Skill，而不是把风格样本藏进公共配置。

这也意味着它可以在任何宿主、任何仓库、甚至没有仓库的对话里使用。

## 边界

- 不虚构事实、数字、引文、来源或第一人称故事。需要个人经历时，向用户要真实的。
- 不为了生动牺牲技术准确性；改写前后必须保留原意，有疑问的断言标 `[待核实]`。
- 不把 API 参考、发布说明、法规文本强行故事化；这类文本走 clarity-first。
- 不模仿在世作者的签名句，只模仿结构动作。
- 幽默不拿读者、同行、受害者开刀；敏感话题不用荒诞化。

## 验证

- `scripts/style_lint.py` 对名词化、被动、套话、长句、抽象后缀、具体数字、人称、问句做确定性统计；`tests/test_style_lint.py` 覆盖教材体、具体体、代码块忽略、JSON 输出。
- 仓库级测试检查：frontmatter、`agents/openai.yaml`、references 链接、体积预算、catalog 元数据、与 README/用户指南的一致性。
- 设计上不做“文风评分”：linter 只给信号，避免把“好文风”简化成一个分数。
