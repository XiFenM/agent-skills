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
