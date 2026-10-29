# Page structure

每次写片段前读取本参考。内容标准、深度和节奏一律以 `guide-learning` 为准；这里只规定它们落到页面上的位置、
写法和时机。

## Contents

1. [课程结构到页面的映射](#1-课程结构到页面的映射)
2. [讲解层次到节点块的映射](#2-讲解层次到节点块的映射)
3. [块的写法](#3-块的写法)
4. [题目的生命周期](#4-题目的生命周期)
5. [补充](#5-补充)
6. [对话指路](#6-对话指路)
7. [编号、标识与篇幅](#7-编号标识与篇幅)

导师串讲、综合验收、练习、恢复、长课分页与改错见 [upkeep.md](upkeep.md)。

## 1. 课程结构到页面的映射

左列是 `guide-learning`「一堂课的结构」的步骤名。

| guide-learning 步骤 | 页面 | 对话 | 什么时候写 |
| --- | --- | --- | --- |
| 开课导入 | `#intro` 叙述连同骨架图 `#fig-0`、`#spine` 资料指路 | 一两行开场控制信息 | `new` 建页时 |
| 核对画像与前置 | 不写 | 需要时问那一个最小问题 | — |
| 逐节点讲解与检查 | 节点块，连同这一段要问的那道题 | 指路与题目全文 | 讲到一次提问为止，一次 `add` |
| 导师串讲 | `#synthesis` | 指路 | 所有节点讲完后 |
| 综合验收 | `#acceptance` 说明与各题 | 指路与题目全文 | 串讲之后 |
| 按证据分流 | 进入练习时只加 `#practice` 一行指路 | 结课确认或练习约定 | 分流时 |

恢复已开始的课只在对话里用一句话挂回当前位置，页面不变。一次答疑不建页；学习者要求答疑页时，只写答案和可选
的一道检查题，不写导入和骨架。只有一个节点的独立 Session 不写导入。

## 2. 讲解层次到节点块的映射

左列是 `guide-learning`「讲解标准」的深度阶梯。按学习者画像的目标深度取层，没讲的层不留空标题。

| guide-learning 层次 | 节点块里的写法 |
| --- | --- |
| 机制 | `<p><b class="lp-layer">机制</b>…</p>`，后面可跟图、公式或部件 |
| 设计理由 | `<p><b class="lp-layer">为什么这样设计</b>…</p>` |
| 真实系统 | `<p><b class="lp-layer">真实系统</b>…</p>`，紧跟一条 `<aside class="lp-note" role="note">` 写来源与版本 |
| 边界 | `<p><b class="lp-layer">边界</b>…</p>`，集中一段，不加警示色 |
| 表达与迁移 | `<blockquote class="lp-oral">` 口述版，标注约多少秒 |

每个节点都以结论开头，结论在任何图和部件之前。

## 3. 块的写法

页头、目录、“本次新增”、阅读时间、主题切换都由模板生成，片段里不写。片段由下列块组成；完整示例见
[example-opening.html](example-opening.html) 与 [example-segment.html](example-segment.html)。

- **导入、骨架与资料指路**：只在建页时写，见 [opening.md](opening.md)。
- **节点** `<section class="lp-node" id="node-N" data-stages="st-a,st-b">`，依次是：
  `<h2><span class="lp-no">N</span>标题</h2>`；有资料指路时 `<p class="lp-spine">资料位置，建议先读或讲完再读</p>`；
  `<p class="lp-lead"><b>结论</b>…</p>`；然后按第 2 节的层次。`data-stages` 让页面在标题下挂出站牌；节点横跨两个阶段时写两个 id，
  那个阶段就成为换乘站。
- **符号**：新符号或新名词第一次出现时，经 `<template data-lp-into="glossary-list">` 加一条
  `<div id="g-…"><dt>符号</dt><dd>含义；维度或单位</dd></div>`；没有维度的名词写含义和学习者熟悉的对应物。一课里的关键量可以固定一种符号色
  （`<var class="lp-s1">m</var>`，共 `lp-s1`–`lp-s4`），正文、公式、代码标注和图里保持同一种。
- **导师划线** `<span class="lp-pen">…</span>`：朱红下划线，划在这一节最要记住的那半句上；每节至多一处，导入里的
  核心矛盾通常值得一处。可以跳过的深挖段落（例如一句话的边界）加 `class="lp-aside"`，字号和颜色退后一级。
- **圈注** `<span class="lp-ring">128 MiB</span>`：把这一节最关键的那个数字圈出来，每节至多一处，不与导师划线落在同一句。
- **术语注音** `<ruby>显存<rt>HBM</rt></ruby>`：中文术语第一次出现时，在上方注资料和代码里用的英文原名；全页每个术语只注
  一次，每段至多两处，常识词不注。阅读时间和标题不计注音。
- **来源**：每个节点在真实系统一层后写一条批注；全页来源经 `<template data-lp-into="sources-list"><li>…</li></template>`
  追加。推断、待验证用 `<span class="lp-tag">推断</span>` 标一次。
- **公式**：写 TeX，`new`、`add`、`state` 写入时用随 Skill 附带的 KaTeX 渲染成静态 HTML，页面只嵌入用到的字体。
  行内 `<span class="tex">S_{ij} = Q_i K_j^\top/\sqrt{d}</span>`，行间 `<div class="tex">…</div>`，多行对齐用
  `aligned`；`<`、`&` 写成 `&lt;`、`&amp;`。`\sA{m}`–`\sD{…}` 上符号色（对应 `lp-s1`–`lp-s4`），`\hl{…}` 加底色，
  分步演示里 `\step{2-3}{…}` 让一段公式只在第 2–3 步出现（只写一个范围）。颜色、链接和其他 HTML 命令会被拒绝，TeX 有错时整段不写入。
  行内公式要短，长的写成行间公式；指数里还有上下标时改写成 `\exp(…)`；同一句里的带下标符号统一用 TeX，不与
  `<sub>` 混用；手工改公式时只改 `data-tex`，再运行 `render`。
  渲染需要本机有 Node，没有时用 `<sub>`、`<sup>` 或 MathML。
- **代码**：`<pre class="lp-code" data-lang="python" data-title="文件名" data-start="120" data-highlight="122-124"><code>…</code></pre>`。
  `data-lang` 让写入时按语言着色（highlight.js 的常见语言，`cuda`、`triton` 按 C++、Python）；`data-symbols="m=1 l_i=2"`（要与 `data-lang` 同用，纯文本写 `plaintext`）
  把这些标识符染成对应的符号色，字符串和注释里的不染。`<code>` 里已有标记时保留原样、不着色。高亮范围和分步演示的
  `data-lines` 都用源文件里的行号，与 `data-start` 一致；下面跟
  `<p class="lp-code-src">路径 · <abbr title="完整提交号">前 12 位</abbr></p>`；示意代码没有仓库时写工具链和版本，例如
  “rustc 1.97.1 可编译”。要逐段讲时紧跟 `<ol class="lp-code-notes"><li data-lines="8-9">…</li></ol>`，读者指向一条
  说明，对应的行就亮起来。编译器或终端的原样输出用 `<pre class="lp-output">`，不加行号。
- **真实系统**：系统和算子课落到源码、配置与真实规模；语言和工具课落到真实的编译器或运行输出、实测数字和所用文档
  的版本。
- **页面专用样式与脚本**：样式和函数注册分别写在片段顶层的 `<style data-lp-style>`、`<script data-lp-hook>`；写入工具将钩子移到正文外、
  `#lp-runtime` 前。批注靠可见内容定位，也可用 `data-note-for="fig-2-1"` 指明前面的同页元素。整页少量调整用 `#lp-page-style`，颜色用令牌。

## 4. 题目的生命周期

复合题的 a、b、c 用 `<ol type="a" class="lp-ask"><li>…</li></ol>` 分开，题设放在列表前。
只改排版时保留题意、编号与历史作答；对话中的题目仍与页面一致。

题目块写法：

```html
<section class="lp-check" id="q-2" data-state="open">
  <h3>检查 2<span class="lp-kind">预测</span></h3>
  <p class="lp-ask">题目全文，条件写全</p>
  <p class="lp-how">怎样作答，例如：用自己的话回答，不需要计算。</p>
</section>
```

- **open**：刚提出。块里只能有 `h3`、`p.lp-ask`、`p.lp-how`、列出条件的 `ul` 或 `ol`、题目用到的 `pre.lp-code`、
  `pre.lp-output`、`div.tex`、`div.lp-table` 或静态图，口述题可以加 `<div class="lp-timer" data-seconds="90"></div>`
  计时；`check` 会拒绝其他内容。题目里的代码和条件算作题目原文，对话里逐字附上，因此代码不超过 6 行。紧挨着题目块
  之后也不放折叠内容和部件。
- **replaced**：题意不清被换掉。`state --to replaced`，再用 `add --after <原题 id>` 在原位置之后追加新题；原题不算
  学习者的错。
- **answered**：学习者已经作答、还在补差或等复查。`state --to answered` 后题头显示“已作答 · 补差中”，不再用朱红
  提示作答；块里的规则与 open 相同，不放参考要点。
- **复查**：补差之后的复查题按普通检查题编号写进页面（下一个 `q-N`，`lp-kind` 写题型），全文逐字发到对话。
- **closed**：差距已补上、复查题也答完（从 open 或 answered 关闭）。用 `state --to closed --fragment <参考要点>` 一次关闭并写进
  `<details class="lp-answer"><summary>参考要点</summary>…</details>`，内容就是 `guide-learning` 的判对标准；原题和
  复查题依次关闭。参考要点不能出现在与同一模型上后续问题相同的那条对话指路里：检验办法是参考要点里不含下一题要
  推理的量。
- 没有真正提出的题不写进页面；不记对错、分数或作答时间。综合验收的参考要点等全部验收题答完再加。

## 5. 补充

`<div class="lp-addendum" id="add-N-k"><h3>补充（回答检查 M 后）</h3>…</div>`，用 `add --into node-N` 放到所属节点
末尾。只在需要图、公式、表格、长代码或值得回看时写；对话里仍要说清诊断和更正结论。

## 6. 对话指路

```text
页面已更新：节点 3–4 与检查 2（约 6 分钟）→ <链接>#node-3
读完后在这里回答：
检查 2（预测）：<与页面逐字相同的题目全文>
```

反馈、关闭题目和下一段常在同一轮：

```text
<约 150 字：答对了什么、差在哪里、更正后的结论>
检查 1 已关闭，参考要点在题目下。下一段：节点 3 与检查 3（约 5 分钟）→ <链接>#node-3
检查 3（迁移）：<题目全文>
```

- 阅读时间取 `add` 输出的 `reading_minutes`。链接用当前查看方式下能打开的地址；同时写出块名，链接打不开时也找得到。
  带锚点打开页面时，目标块四周暗下来、自身亮起两秒多。分了页的课见 upkeep.md 第 3 节。
- 暂停时说下次从哪个块继续；恢复时一句话挂回当前位置并给出锚点。
- 不在对话里复述页面讲解，不列出改了哪些地方。

## 7. 编号、标识与篇幅

- 标识用 ASCII，写下后不再改：`intro`、`fig-0`、`spine`、`node-N`、`q-N`、`add-N-k`、`synthesis`、
  `acceptance`、`q-aN`、`practice`、`recap`、`fig-N-k`、`st-…`、`g-…`；`part-prev`、`next-part`、`lp-pager` 由脚本写。
- 图号按节点写死：骨架是图 0，节点 2 的第一张图是图 2.1，补充里的图是图 2.补1；对话可以放心引用。
- 页面篇幅不改变 `guide-learning` 的节奏。一次追加读起来超过约 9 分钟时，先删冗余，把长推导、API 细节放进
  `<details>`（仅限已讲内容，不能挨着开放题）或图里；单个段落不超过约 220 字。
