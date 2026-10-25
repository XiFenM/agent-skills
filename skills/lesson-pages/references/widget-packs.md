# Widget packs

用海报、对数尺、误区对照、类比卡、公式解剖、逐行推导、执行回放或系统结构图前读取本参考。它们是部件包：片段里只写
下面的结构，`new`、`add`、`state` 发现页面用到 `lp-<名字>` 时，把对应的样式和脚本写进这一页（`#lp-pack-<名字>`），
没用到的页面不带；`render` 刷新过期的部件包、删掉不再用的。不手写、不改动部件包的样式与脚本。

## Contents

1. [先选对部件](#1-先选对部件)
2. [共同规矩](#2-共同规矩)
3. [海报式开场](#3-海报式开场)
4. [对数尺](#4-对数尺)
5. [误区对照与类比卡](#5-误区对照与类比卡)
6. [公式解剖与逐行推导](#6-公式解剖与逐行推导)
7. [执行回放](#7-执行回放)
8. [系统结构图](#8-系统结构图)

## 1. 先选对部件

| 想让读者 | 用 | 通常放在 |
| --- | --- | --- |
| 一眼记住本课要解决的矛盾 | 海报 `div.lp-poster` | 开课片段第一块，全课至多一处 |
| 比较相差几个数量级的量 | 对数尺 `figure.lp-scale` | 讲“为什么慢、为什么放不下” |
| 拆掉一个真实存在的误解 | 误区对照 `div.lp-myth` | 为什么这样设计、边界 |
| 借熟悉的事物理解机制，也知道它在哪里不成立 | 类比卡 `aside.lp-analogy` | 机制之后 |
| 看懂一个公式的每一项 | 公式解剖 `figure.lp-anatomy` | 公式第一次完整出现 |
| 跟着一步步推出结论 | 逐行推导 `figure.lp-derive` | 需要推导的“为什么” |
| 看循环里的状态怎样一步步变 | 执行回放 `figure.lp-replay` | 代码讲解，代替静态代码块 |
| 看清一个系统的层次，硬件、软件都算系统 | 系统结构图 `figure.lp-zoom` | 真实系统 |

## 2. 共同规矩

- 对数尺、类比卡、公式解剖、逐行推导、执行回放和系统结构图算作节点的部件：每个节点至多一个，开放题里和紧挨开放题
  处都不放，`check` 会拒绝。海报和误区对照是静态块，同样不能提前说出开放题的答案。
- 都不用写脚本。没有脚本、打印和减少动态效果时，它们退回列表、提纲或静态排版，所以结构里的文字本身要完整。
- 数字用工具算好或测好并注明来历，规矩同 [interactive-widgets.md](interactive-widgets.md) 第 5 节。
- 执行回放和系统结构图放在深色台面上，`figure` 带 `is-stage`；代码较宽的执行回放再加 `is-wide`。
- 颜色由部件包按风格和深浅主题处理，片段不给它们写样式。结构写错时 `check` 报 `pack.markup` 并说明缺什么；页面的
  `#lp-runtime` 早于部件包时报 `pack.runtime`：这样的旧页面里部件不会动起来，新部件写进新页面。

## 3. 海报式开场

```html
<div class="lp-poster">
  <p class="lp-poster-kicker">序列长度 N = 16,384 时，单头一份 FP16 的分数矩阵 S</p>
  <p class="lp-poster-num"><b>512</b><small>MiB</small><span>N × N 个分数，每个 2 字节</span></p>
  <p class="lp-poster-num"><b>192</b><small>KB</small><span>A100 每个 SM 的片上存储</span></p>
  <p class="lp-poster-say">差了约 2,700 倍。整行放不进片上，softmax 的分母还怎么算？</p>
</div>
```

一个或两个 `lp-poster-num`：`<b>` 只写数字（可带千分位逗号与小数），单位写进 `<small>`，`<span>` 一句说明它是什么。数字
第一次出现时从 0 数到写下的值，只数一次。两个数的单位能换算（字节类按 1024 进位、SI 前缀、同名单位）且相差 10 到
20,000 倍时，下面铺一片格子：整片是大的量，亮起的一格是小的量。说出倍数时与两个数一致，倍数用工具算。

## 4. 对数尺

```html
<figure class="lp-figure lp-scale" id="fig-1-2" data-unit="B/s">
  <ol>
    <li data-value="1.28e10"><b>CPU 内存（DRAM）</b>12.8 GB/s</li>
    <li data-value="1.5e12"><b>GPU 显存（HBM）</b>1.5 TB/s</li>
    <li data-value="1.9e13"><b>GPU 片上 SRAM</b>19 TB/s</li>
  </ol>
  <figcaption><b>图 1.2</b>存储层次的带宽。数字取自 FlashAttention 论文图 1（A100）。</figcaption>
</figure>
```

2 到 6 个同一种量。`data-value` 是换算到 `data-unit` 的数值，大于 0，可写 `1.5e12`；显示文字写在 `li` 里。`data-unit` 是
B、B/s、FLOP/s、s 这类单位时刻度带 SI 前缀，不写时刻度是 10 的幂。运行时按大小排开，相邻两个量之间标出倍数，读者可以
切到线性刻度对照，看小的量怎样挤到一端。

## 5. 误区对照与类比卡

```html
<div class="lp-myth">
  <p class="lp-myth-wrong">FlashAttention 快，是因为它少算了一部分注意力，得到的是近似结果。</p>
  <p class="lp-myth-right">它是精确算法，每个分数都算了；快在不把 N×N 的 S、P 写回显存。</p>
</div>
```

误解写成学习者真会有的完整说法，不立稻草人；正解一两句，说清对在哪里、为什么。读到时误解被一笔划掉。一节至多一处。

```html
<aside class="lp-analogy">
  <p>分块像在一张小书桌上整理一大柜文件：桌面（片上存储）只摊得开一摞，就一摞一摞地从柜子（显存）里拿出来处理。</p>
  <div class="lp-analogy-limit"><p>文件可以一摞一摞各自处理完，softmax 却不行：每个概率要除以整行的指数和。</p></div>
</aside>
```

喻体后面紧跟括注写它对应的实物，运行时画成“≈ 片上存储”的小签；括注只放这个名词，不放数字、标点或“如、约”开头的
说明。`lp-analogy-limit` 必须写：类比在哪里不成立，最好正好指向接下来要讲的机制。读者按下按钮才展开。

## 6. 公式解剖与逐行推导

```html
<figure class="lp-figure lp-anatomy" id="fig-2-1">
  <div class="tex">\sB{\ell}_{\text{new}} = \tA{e^{\sA{m} - \sA{m}_{\text{new}}}}\,\tB{\sB{\ell}} + \tC{\sum_{k \in \text{新块}} e^{s_k - \sA{m}_{\text{new}}}}</div>
  <ol class="lp-terms">
    <li>缩放因子 α：把旧基准 <var class="lp-s1">m</var> 换到新基准的比例，不超过 1。</li>
    <li>旧的指数和，以旧的 <var class="lp-s1">m</var> 为基准。</li>
    <li>本块的指数和，直接以新的最大值为基准。</li>
  </ol>
  <figcaption><b>图 2.1</b>……</figcaption>
</figure>
```

`\tA`–`\tF` 依次圈出至多 6 项，与 `ol.lp-terms` 的各条按顺序一一对应；每条一句，说这一项是什么、为什么在这里。宽屏时
说明排在公式上下、引线连到各项，放不下时退回编号列表。

```html
<figure class="lp-figure lp-derive" id="fig-2-2">
  <ol>
    <li><div class="tex">\sB{\ell}_{\text{new}} = \sum_{k \in \text{旧块}} e^{s_k - \sA{m}_{\text{new}}} + \sum_{k \in \text{新块}} e^{s_k - \sA{m}_{\text{new}}}</div><p>按定义分成旧块与新块。</p></li>
    <li><div class="tex">= \sum_{k \in \text{旧块}} e^{s_k \hl{{} - \sA{m} + \sA{m}} - \sA{m}_{\text{new}}} + \cdots</div><p>指数里减一个 m 再加回来。</p></li>
    <li><div class="tex">= \hl{\alpha\,\sB{\ell}} + \operatorname{rowsum}\bigl(\exp(S_j - \sA{m}_{\text{new}})\bigr)</div><p>剩下的求和正是旧的 ℓ。</p></li>
  </ol>
  <figcaption><b>图 2.2</b>……</figcaption>
</figure>
```

每步一个行间公式加一句理由，3 到 8 步，更长就拆成两张图。续行以“=”开头，运行时把等号对齐到第一行；每步变化的部分用
`\hl` 标出；最后一步是结论，运行时把它框起来。读者逐步展开，也可以一次全部展开。

## 7. 执行回放

```html
<figure class="lp-figure is-wide is-stage lp-replay" id="fig-2-4">
  <pre class="lp-code" data-lang="python" data-title="online_softmax.py" data-symbols="m=1 l=2 acc=3"><code>……</code></pre>
  <ol class="lp-trace" data-vars="s m alpha l acc return">
    <li data-line="4" data-set="m=−∞ l=0 acc=0" data-group="初始化">三样状态的初值：还没看到任何分数。</li>
    <li data-line="5" data-group="第 1 块">进入第 1 块。</li>
    <li data-line="6" data-set="s=[1.2,3.1,0.4,2]">取出本块的 4 个分数。</li>
  </ol>
  <figcaption><b>图 2.4</b>……轨迹由 Python 3.12 实际运行记录。</figcaption>
</figure>
```

- 轨迹来自真实运行：把代码和一次调用写进一个文件，调用放在代码之后；运行 `lesson_pages.py trace --code <文件> --vars
  "m l acc return" --function <函数名>`，把输出的 `html` 放进 `ol.lp-trace`，再给每步写一句说明。页面里的代码到调用之前
  为止，行号不变。循环体另起一行：和 `for`／`while` 写在同一行时，整个循环在回放里只剩一步，`trace` 会拒绝。可以删去
  不需要的步，不改数值。
- `data-vars` 是变量表里的变量和顺序，`return` 是返回值；`data-set` 是这一步改变的变量，值里没有空格；小数保留四位，
  小于 0.001 的写成四位有效数字（如 `6.144e−6`）；数组写成 `[1,2,3]`，变量表把它画成一排小格。`data-group` 标在
  每段的第一步。函数被调用不止一次时，从第 2 次起每次调用的第一步带 `data-call`，回放到这里变量表先清空；这一步不要删。
- 不超过约 40 步；循环很长时只回放前几轮，图注里说明。

## 8. 系统结构图

```html
<figure class="lp-figure is-stage lp-zoom" id="fig-1-3" data-domain="hardware">
  <ul>
    <li><b>A100 GPU</b><p>108 个 SM 共用 40 MB 的 L2 缓存和 40 GB 或 80 GB 的 HBM。</p>
      <ul>
        <li data-size="2"><b>HBM 显存</b><p>Q、K、V、O 放在这里。</p></li>
        <li><b>L2 缓存</b><p>40 MB，所有 SM 共用。</p></li>
        <li data-size="2"><b>SM × 108</b><p>一个线程块落在一个 SM 上运行。</p>
          <ul><li><b>寄存器堆</b><p>每个 SM 256 KB。</p></li><li><b>共享内存 / L1</b><p>每个 SM 合计 192 KB。</p></li></ul>
        </li>
      </ul>
    </li>
  </ul>
  <figcaption><b>图 1.3</b>……数字取自 NVIDIA A100 架构白皮书。</figcaption>
</figure>
```

最外层恰好一个 `li`，代表整个系统；每层 2 到 6 个部件，至多四五层。每个部件写名字 `<b>` 和一两句说明 `<p>`，说它在
本课里起什么作用；`data-size`（1 到 3）是它在这一层所占的分量。`data-domain` 写 `hardware`（电路板与芯片）或
`software`（窗口与模块），别的系统不写。读者点一个部件就放大进去，外面几层留在四周，点哪一层就退回哪一层。
