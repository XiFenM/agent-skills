---
name: vivid-tech-writing
description: Draft, diagnose, or rewrite technical blog posts, tutorials, talks, and explainer video scripts so they read like a person rather than a textbook. Also the shared language contract for learner-facing teaching, lesson pages, and memo cards; those skills keep their own structure, state, and generation rules. Use when the user wants to write or improve 技术博客、科普文章、教程、技术分享、知识视频口播稿, complains about 教材腔、枯燥、翻译腔, or asks for 口语化、生活化、借喻, or wants to learn vivid technical exposition from examples. Do not use for API reference, release notes, pure copyediting, SEO, or marketing copy.
---

# Vivid Tech Writing

Turn technical knowledge back into experience: **scene, person, change**.

把知识放回经验。教材腔不是“太专业”，是“太抽象、太安全、太没有人在说话”。

生动 = 补回教材删掉的三样东西：**场景、人、变化**。

## 先选模式

| 模式 | 触发 | 交付 |
|---|---|---|
| `diagnose` | 用户给草稿，问“怎么样/哪里枯燥/帮我看看” | 诊断表 + 3 个优先手术；默认不改写 |
| `rewrite` | 用户说“改/重写/润色这一段” | 改写全文或指定段落 + 改动说明 |
| `draft` | 用户说“帮我写一篇/从零写” | brief → 结构 → 初稿 |
| `video` | 用户要口播稿、分镜、知识视频 | 口播稿 + 镜头表 |
| `coach` | 用户想练、想学方法、要书单 | 一个概念 + 一个样板 + 一个练习 |

用户给草稿说“帮我看看/哪里枯燥”时，先做 `diagnose`；说“改/重写/润色”时，直接进入 `rewrite`，但仍在心里先做一遍诊断。

## 先问清楚，最多四问

只问缺失的，不要审讯：

1. 体裁与长度：博客 / 教程 / 分享稿 / 视频口播？大概多少字或多少分钟？
2. 读者：谁会读，他们已经知道什么，读完后要能做什么？
3. 约束：哪些事实、数字、API 行为、结论不能动？有没有必须保留的结构？
4. 声音：用第一人称吗？有没有过往文章/口播可以作为语气样本？

能从草稿推断的就推断，并在开头写一句“我按……来改”。不要为了问全而停下。

## 七步工作流

1. **找承诺。** 用一句话写：读者读完能做什么、知道什么、改变什么。写不出，就先别写开头。
2. **找入口。** 从五个里选一个：具体场景、反常识事实、代价、问题、真实的失败。只选一个，不要五个都上。
3. **搭骨架。** 说明文用 ABT：本来（And）→ 但是（But）→ 所以（Therefore）。教程用 OCAR：共同背景 → 挑战 → 行动 → 世界发生了什么变化。技术决策用：现象 → 直觉解释 → 失败 → 真正的机制 → 代价。
4. **选 2–3 个动作。** 从下面九个里挑，不要全用。读 [references/moves.md](references/moves.md) 看样板、公式和坑。
5. **做句子手术。** 去名词化、给主语、把动作还给动词、加数字、断长句。中文读 [references/chinese-editing.md](references/chinese-editing.md)。有文件时运行 `scripts/style_lint.py`。
6. **过准确性闸门。** 每个数字、引文、API 行为、性能结论、个人经历都要有来源或标 `[待核实]`。保留原文的引用、限定条件、适用版本和 caveat，不要为了流畅删掉它们。不编造第一人称故事。
7. **交付。** 按下面的输出格式；改写必须附“改了什么/为什么”，让用户能拒绝。

## 九个动作（速查）

| 动作 | 什么时候用 | 一句话公式 |
|---|---|---|
| 1. 身体经验开场 | 概念离生活很远 | 你一定遇到过 [场景]。这背后是 [概念]。 |
| 2. 先画面后命名 | 术语太早出现 | 想象 [画面]。这种 [做法]，叫 [术语]。 |
| 3. 尺度锚点 | 数字太大/太小 | 把 [X] 放大到 [熟悉物]，[Y] 只有 [熟悉物] 那么大。 |
| 4. 类比三段式 | 需要解释结构 | 像什么 → 为什么像 → 哪里不像。 |
| 5. 让读者先猜 | 结论反常识 | 先别往下看，猜一下：[可错的问题]。 |
| 6. ABT / OCAR | 全文没冲突 | 本来 [A]，但是 [B]，所以 [C]。 |
| 7. 幽默与人格 | 内容太硬/太安全 | 自嘲 + 具体失败 + 反转。 |
| 8. 可视化即论证 | 关系是动态/空间的 | 让读者拖动 [变量]，看见 [结果]。 |
| 9. 结尾回响 | 结尾像总结 | 回到开头那个 [场景]，现在你知道 [变化]。 |

**不要九个全上。** 一篇 2000 字的文章，2–3 个动作就够；全上会变成杂技。

## 中文硬规则

- **去名词化。** “进行了优化” → “从 800ms 降到 120ms”；“具有较高的可维护性” → “改一行不用动三个文件”。
- **给主语。** “该问题被认为” → “我们认为/我们测到”。
- **删缓冲垫。** “此外、然而、值得注意的是、综上所述”先删，再看逻辑是否还在。
- **术语四条。** 先经验后命名；一段只引入一个新术语；出现三次才缩写；不用术语解释术语。
- **句号是呼吸。** 超过 45 个字就找地方断；破折号一段最多一个。
- 更细的翻译腔清单、改写表与标点规则在 [references/chinese-editing.md](references/chinese-editing.md)。

## 口语化与生活化

用户说“太书面”“太像教材”“能不能更口语”“打个生活里的比方”时，读 [references/plain-language.md](references/plain-language.md)。三条硬规则：

- **先给一句话答案。** 难节开头先说“到底在干什么”，再上步骤、公式或代码。
- **用一个日常物件当主线比喻。** 尺子、记账、合影、装修效果图；2–3 个就够，每个都标“哪里不像”。
- **并排容易混的东西。** 两个 scale、搜索 vs 部署、方法 vs 表示 vs 执行，用一张表横向对比。

口语化不是段子化：短句、直接称呼、具体动词，但不删数字、caveat 和引用。

## 跨体裁语言契约

`guide-learning`、`lesson-pages`、`memo-cards` 的讲解、页面和卡片，也用同一套语言底线。完整契约在 [references/language-contract.md](references/language-contract.md)：先场景/对象/问题，完整优先于短，一个主例贯穿，术语先定义，事实/推断分开，结论能自评。

体裁差异（文章／教学／页面／卡片／视频）见契约的“按体裁”一节；结构、状态、授权仍由各自 Skill 负责。

## 视频模式

- 开场 15 秒 = 画面 + 反常识 + 承诺；不要从“大家好，今天我们来聊聊”开始。
- 口播三句一节：事实 → 为什么 → 所以你会看到什么。
- 每 30–45 秒一个变化：新信息、新画面、新问题、反转、数字。
- 画面给“看见”，口播给“为什么”；画面上已有的字，口播不再念。
- 交付镜头表：时间 / 画面 / 口播 / 屏幕字。模板见 [assets/video-shot-sheet.md](assets/video-shot-sheet.md)。
- 完整方法、60 秒示例与自检在 [references/video-script.md](references/video-script.md)。

## 质量闸门

改写或初稿完成后，逐条过：

- [ ] 第一段有具体场景、数字或反常识吗？
- [ ] 一句话能说清“读者为什么要读”吗？
- [ ] 术语出现前有经验/画面吗？
- [ ] 有类比，且标了边界吗？
- [ ] 有“我”的判断、失败或偏好（如果体裁允许）吗？
- [ ] 句子有长短变化吗？
- [ ] 删掉了至少 30% 的废话吗？
- [ ] 结尾有回扣或升维吗？
- [ ] 每个数字、引文、结论都能追溯到来源吗？
- [ ] 读出声，有喘不过气的地方吗？

## 边界（硬约束）

- **不编造。** 不虚构事实、数字、引文、来源、用户经历或“我有一个朋友”。需要故事时，向用户要真实的。
- **不歪曲。** 生动不能改变技术结论；如果为了画面必须简化，写明简化在哪、代价是什么。
- **不越权。** 默认只在对话里交付文本；用户没要求就不要写入仓库、发布或改文件。
- **不硬套。** API 参考、发布说明、法规、事故报告走 clarity-first；不要给它们加段子和悬念。
- **不模仿签名句。** 可以学结构动作，不要复制在世作者的标志性措辞。
- **不俯视。** 不用“小白也能懂”“连我妈都会”这类居高临下的语气；用“我曾经也不懂”。

## 输出格式

### diagnose

1. **一句话判断**：最要命的 1 个问题。
2. **诊断表**：病灶 / 原文证据（引一句）/ 手术。
3. **三个优先动作**：先改哪三处，为什么。
4. 最后问：“要我直接改写吗？”

### rewrite

1. **改写**：全文或指定段落。
2. **改了什么**：3–5 条，对应到具体动作（如“去掉 7 处名词化”“把开头从定义换成场景”）。
3. **待核实**：列出需要用户确认的事实、数字、引文。
4. 可选：给一个不同风格的开头（A/B），让用户选。

### draft

1. **Brief**：读者、承诺、入口、约束（5 行以内）。
2. **结构**：每节一句话。
3. **初稿**。
4. **待核实**。

### video

1. **一句话承诺**。
2. **口播稿**（按三句一节分段）。
3. **镜头表**（时间 / 画面 / 口播 / 屏幕字）。
4. **待核实**。

### coach

1. 一个概念（不超过 200 字）。
2. 一个真实样板（引最短的必要片段 + 拆一个动作）。
3. 一个 10 分钟练习。
4. 请用户交作业，按“动作是否用对”反馈，不打文风分。

## 按需读取

| 文件 | 什么时候读 |
|---|---|
| [references/diagnosis.md](references/diagnosis.md) | 做诊断、需要病灶对照表或病文重写示例 |
| [references/moves.md](references/moves.md) | 选动作、需要样板/公式/坑 |
| [references/close-readings.md](references/close-readings.md) | 想学具体段落怎么拆、需要大师样本 |
| [references/chinese-editing.md](references/chinese-editing.md) | 中文翻译腔、术语、标点、句子手术 |
| [references/plain-language.md](references/plain-language.md) | 口语化、生活化、借喻、公式/表格的“读法” |
| [references/language-contract.md](references/language-contract.md) | 跨体裁语言契约：教学、页面、卡片、文章、视频的共同底线 |
| [references/video-script.md](references/video-script.md) | 视频口播、分镜、开场结尾 |
| [references/source-library.md](references/source-library.md) | 用户要书单/视频/博客推荐，或需要更多样板 |
| [references/practice.md](references/practice.md) | 用户要练、要 30 天计划、要语料卡 |
| [assets/article-brief.md](assets/article-brief.md) | 从零写一篇，先填 brief |
| [assets/rewrite-worksheet.md](assets/rewrite-worksheet.md) | 逐段诊断与改写 |
| [assets/video-shot-sheet.md](assets/video-shot-sheet.md) | 视频镜头表 |

只在需要时读；不要一次把所有 references 塞进上下文。
