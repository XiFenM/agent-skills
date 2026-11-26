---
name: lesson-pages
description: "Render guide-learning lessons as calm, interactive, offline single-file HTML lesson pages so dense teaching moves out of the chat: the page grows segment by segment as the lesson is taught, while the chat keeps a short pointer, the verbatim check question and feedback. Use together with guide-learning when the learner asks to learn with a web page or lesson page, to turn the current lesson into a page, to continue a lesson that already has a page, or when the learner profile prefers page-based lessons. Do not use for general website, UI or landing-page design, slides, learning articles, or content without a guide-learning lesson."
---

# Lesson Pages / 课程网页

把 `guide-learning` 的讲解从对话搬到一份安静、可交互、离线就能打开的单文件网页上：页面随课程逐段生长，
对话只留指路、检查题和反馈。目标是减轻读大段文字的压力，并用图和交互部件让机制看得见、摸得着。

## 首次启用

当前对话第一次启用本 Skill 时，处理完请求后用一句话附上本 Skill 说明和组合指南的链接：依次在本 Skill
目录的上两级目录、工作区仓库根、仓库根下的 `.agent-skills` 查找 `docs/user-guides/lesson-pages.md` 与
`docs/learning-skills-user-guide.md`，找到就给绝对路径链接，否则给[公开说明](https://github.com/XiFenM/agent-skills/blob/main/docs/user-guides/lesson-pages.md)与[公开组合指南](https://github.com/XiFenM/agent-skills/blob/main/docs/learning-skills-user-guide.md)。
不阻塞、不求确认、同一对话不重复；与 `guide-learning` 同时首次启用时合并成一句。Lesson 里随首次提出页面的开课确认
一起发；那一轮已经放了题目时，可以挪到下一轮。

## 与 guide-learning 的关系

- 讲什么、讲到第几层、怎样提问、节奏、补差、串讲、验收与结课，**完全按 `guide-learning`**。本 Skill 只决定
  内容放页面还是对话、页面怎样呈现、页面文件怎样写；两者冲突时以 `guide-learning` 为准。
- 本 Skill 是与 `guide-learning` 同时运行的呈现层，不是交接。没有 `guide-learning` 时不新写教学内容，只能把
  已经讲过、用户指定的内容排成页面。
- 页面不是状态，也不是证据：当前位置以断点为准，理解证据以学习者在对话里的回答为准。页面上不写目标与证据
  清单、进度、掌握判断、“当前课”标记或账本里的结论。

## 何时用页面

- 学习者要求用网页学、把本课做成页面，或本课已经有页面时使用。学习者画像写明偏好课程网页时，在开课确认中
  默认提出，并说明可以不用。
- 一次答疑默认在对话里回答、零写入；学习者要求答疑页并确认路径后，只写这一个页面，ID 用 `qa-<主题短名>`。
- 学习者随时可以说“这课不用网页”。页面从不阻塞教学：写入未获授权、检查反复失败或修页面会拖慢课程时，先在
  对话里紧凑地讲；页面恢复后补一段“前面讲过”，学习者想要完整讲解时再补写整节。

## 页面和对话怎样分工

| 写进页面 | 留在对话 |
| --- | --- |
| 开课导入、全流程骨架、资料指路 | 开场控制信息：目标、证据类型、记录与页面路径，一两行 |
| 节点讲解的全部层次，以及图、部件、代码与表格 | 核对前置时那一个最小问题 |
| 检查题全文 | 同一道题的全文，编号与页面一致、逐字相同 |
| 需要图、公式、表格、长代码或值得回看的补充 | 反馈：约 150 字说清差在哪里、更正后的结论；说得完的补差留在对话 |
| 导师串讲、综合验收题；题目关闭后的参考要点 | 指路：新增了什么、链接、阅读时间、下一步，不超过 3 行 |
| 随讲解增长的符号与名词、来源 | 学习者的追问与简短回答；值得回看的再问要不要加进页面 |

讲课的每轮对话以一屏为限：不放表格和标题，代码块不超过 6 行，不复述页面上的讲解，不贴更新记录。练习约定、
Review 报告和结课确认按 `guide-learning` 的要求完整留在对话里，不受这条限制。反馈里的诊断和更正结论必须出现在
对话中，学习记录只能看到对话。

## 教材式呈现

语言按 `vivid-language` 的 `references/language-contract.md`（课程网页体裁）：**先立后破**——先定前提与场景，直说确定因果，边界集中放边界层或批注，不在机制段堆叠防御性免责句。对话指路与反馈按对话体裁。写正文前按 [language-review.md](references/language-review.md) 审查（非 Gemini 宿主远程优先，Gemini 宿主及兜底走子 Agent）；结课前再审整页。未通过不改、不声称完成。

## 一课在页面上怎样展开

1. **开课**：`new` 建页，写整体导览（多课首课先交代阶段安排）、核心思想、全流程骨架和资料指路（见 opening.md）；一门课统一风格（`--look`，见 [page-design.md](references/page-design.md) 第 9 节）。核对前置在对话进行；无需提问时同轮追加第一段。
2. **每段**：把讲到下次提问前的节点连同该题一次 `add`。**拒绝纯文本加表格搬运**：每段至少配 1 个交互部件或舞台 SVG 图解（选型见 [interactive-widgets.md](references/interactive-widgets.md) 和 [widget-packs.md](references/widget-packs.md)）；每节点聚焦 1 个主实验台，可搭轻量类比卡、误区卡、句内可调段或对照图。节奏只听 `guide-learning`；超约 9 分钟先去重、拆段、用图组织，已讲可选细节移入 `<details>`，不删因果，不为篇幅加题。
3. **作答之后**：先 `state --to answered`；反馈在对话，需展开的补充用 `add --into node-N` 放进所属节点。复查题照常写页并逐字发对话；答完后用 `state --to closed --fragment <参考要点>` 关闭原题并写参考要点。
4. **串讲与验收**：导师串讲、综合验收按时机追加；正式练习只加一行指路（见 upkeep.md）。
5. **不提前写**：未讲节点不进页面。学习者要求“剩下的都写出来”时可提前写讲解（仍逐段 `add`），题目等提出时用 `add --after` 插入；串讲与验收题不提前写。结课后除非要求不再写入。

块与题目写法见 [page-structure.md](references/page-structure.md)。模板内置横排站牌与整节点 Markdown 复制（覆盖正文、补充和完整图示步骤，不夹带控件），验证见 [page-design.md](references/page-design.md) 和 [browser-checks.md](references/browser-checks.md)。

## 每次更新页面

1. 用 `outline` 看已有块、行号和题目状态；不读整页，不读模板。
2. 用写文件工具把内容块写成临时 UTF-8 片段（不放仓库、不写框架和基础样式）；公式写 TeX、代码标 `data-lang`，写入时渲染静态 HTML（需本机 Node，出错不写入）。部件包只写结构，脚本按需注入并将钩子移至运行时前。
3. `add` 插入片段或 `state` 改题态；检查不合格不写入，提示续页改用 `continue`。
4. 按下文“验证”检查，再在对话发指路（阅读时间取输出 `reading_minutes`）。命令见 opening.md，题态与续页见 upkeep.md。

## 文件、查看与授权

- **授权**：Lesson 把“本课用网页承载讲解，写入 <路径>（查看方式）”并入 `guide-learning` 的开课确认；独立 Session
  在第一次写页面时确认路径。确认后，本课的追加与题目状态更新自动进行。不覆盖已有文件，不改其他课的页面，不提交、
  不推送；启动 `serve` 和把页面发布到本机以外都要学习者先同意；配置给出的位置只是写入上限，不是授权。
- 文件名就是页面 ID（Lesson 用账本 ID）。选位置、定查看方式、受管配置与画像里能记什么见
  [files-and-viewing.md](references/files-and-viewing.md)。

## 题目与部件的底线

- 开放中的题目块里只放题目、题目用到的代码或静态图，以及口述计时；紧挨着它的位置不放折叠内容或部件。提示只在
  对话里给，这样帮助程度对 `guide-learning` 是可见的。`check` 会拒绝违反这两条的页面。
- 页面上的任何部件、推导、折叠内容或资料指路都不能提前给出开放题和后续验收变式的答案。部件触及开放题的变量时标
  `data-reveals`，题目关闭后才追加；会直接回答开放题的资料段落，等题目关闭后再安排阅读。
- 题目只在真正提出时写进页面。题意不清换题时，把原题标为 `replaced`，不算学习者的错。
- 部件里由公式算出的数字交给计算函数实时算，参数探索和可调段落附用 Python 等工具算好的 `data-cases`；正文里的真实规模数字和
  实测数字可以静态写出，用工具算好或测好，并注明来历。都不手算。

## 验证

1. **每次**：`check`，本机有 Node 时会一并检查内联脚本语法；在对话里引用锚点前用 `--anchor` 核对它存在。
2. **建页、增加部件、改布局或脚本时**：按 [浏览器检查](references/browser-checks.md) 检查长内容、组件窄宽度、浅深主题与交互；
   开启正常动画连续滚动并停留，不能只看静态截图或减少动态效果。纯文字追加不必重跑整套。
3. **没有浏览器工具时**：在指路里说一次“未在浏览器中验证”，不声称视觉或交互已通过。

## 与其他 Skill 的分工

教学内容、状态与授权归 `guide-learning`；学习过程记录归 `study-log`，制卡归 `memo-cards`，英语反馈归
`english-coach`。页面只在用户明确指定时才作为它们的素材，从不自动流入。学习文章仍按 `guide-learning` 的文章流程
单独请求。没有学习课程的一般网页、界面或落地页设计不使用本 Skill。

## 按需读取参考

- [page-structure.md](references/page-structure.md)：每次写片段前读。各块怎样对应课程结构、写法、编号、题目状态与对话指路。
- [upkeep.md](references/upkeep.md)：恢复一课、写串讲验收或练习指路、提示续页或课已分页、改错与换风格时读。
- [opening.md](references/opening.md)：每次建新页前读，写导入、骨架和资料指路。
- [example-opening.html](references/example-opening.html) 与 [example-segment.html](references/example-segment.html)：第一次建页前读。开课片段与一段讲解的完整示例。
- [interactive-widgets.md](references/interactive-widgets.md)：做交互部件前读。
- [widget-packs.md](references/widget-packs.md)：选择部件包时读；按信息结构选图，不默认每课使用全部部件。
- [source-browser.md](references/source-browser.md) 与 [源码浏览器片段](references/example-source-tree.html)：需要真实目录、文件职责与源码行号时读。
- [timelines.md](references/timelines.md) 与 [逐步时序片段](references/example-timeline.html)：需要展示参与者、状态、信号与跨步依赖时读。
- [page-design.md](references/page-design.md)：选风格、自绘图形、改样式或检查视觉时读。
- [files-and-viewing.md](references/files-and-viewing.md)：选位置、定查看方式、读受管配置或处理授权细节时读。
- `references/sample-pages/`：2026-10-24 的历史成品页，仅参照视觉与交互；讲解顺序以 page-structure.md 和
  example-segment.html 为准。每页约 500 KB，用浏览器看，不读进上下文。
