# Interactive widgets

做交互部件前读取本参考。课程网页的核心价值，就是把文字里看不见的状态演化、分支对比和参数敏感度变成**可步进、可切换、可拖动**的画面。

## Contents

1. [按机制选动态交互](#1-按机制选动态交互)
2. [不能泄题](#2-不能泄题)
3. [内置部件](#3-内置部件)
4. [自定义计算](#4-自定义计算)
5. [数字要可信](#5-数字要可信)
6. [交互与可访问性](#6-交互与可访问性)

## 1. 按机制选动态交互

- **动态与图示优先**：每段讲解至少配 1 个交互部件或深色舞台 SVG，不把页面写成纯文字加表格。只要涉及步骤流转、双方案对比或参数敏感度，优先用交互部件。
- **机制 → 部件速查**：
  - 步骤流转、树分裂、队列进出、生命周期、异步依赖 → `lp-stepper`（配 SVG `data-show`）或 `lp-timeline`；
  - 两种模式、开关前后、跨框架对照 → `lp-toggle`（面板内放图解或状态条，不只放字）；
  - 参数变化决定结论（预算、页/块大小、并发、量化、Roofline） → `lp-explorer`（预设 + 滑块 + 实时计算/柱条）或 `lp-live`；
  - 循环回放 / 数量级 / 公式 / 推导 / 源码 / 架构 → 对应 [widget-packs.md](widget-packs.md)。
- **节制分工**：每节点聚焦 **1 个主交互实验台**（骨架图不算），可按需搭 `lp-analogy`、`lp-myth`、`lp-live` 或静态舞台对比 SVG。
- **可降级与真实规模**：无脚本/打印时按顺序可读；小算例后紧接真实规模。部件是学习工具，不计分、不当证据。

## 2. 不能泄题

- 部件的控件、预设和分步内容，不能覆盖开放题或计划中的验收变式要学习者推理的那个条件。先定题，再定部件。
- 部件确实会触及某道题时，在部件上写 `data-reveals="q-2"`；`check` 会拒绝这道题仍开放时的页面。等题目关闭后，再把
  这个部件追加进来；只多出几组预设时，另加一张图而不是改旧图。会触及计划中验收变式的部件，等那道验收题关闭后再加。
- 不做“先预测再揭晓”的页面部件，预测放在对话里，由 `guide-learning` 判断。
- 开放题的块里和紧挨着它的位置，不放部件和 `<details>`。

## 3. 内置部件

模板的运行时会自动接管下列标记，片段里只写结构，不写通用脚本。分步演示、对照切换和参数探索都放在深色的实验台上，
里面照常写 `var(--…)`，令牌会自动换成深色版本。

**分步演示** `figure.lp-stepper`：

```html
<figure class="lp-figure lp-stepper" id="fig-2-1">
  <div class="lp-canvas">
    <!-- 静态内容；data-show 写这一元素在哪些步出现，如 "2-4,6" -->
    <span data-show="2-5">…</span>
  </div>
  <ol class="lp-steps">
    <li>第 1 步说明</li>
    <li data-lines="3-5">第 2 步说明；data-lines 高亮本图中代码块的行</li>
  </ol>
  <figcaption><b>图 2.1</b>说明这个部件让人看见什么。</figcaption>
</figure>
```

运行时在步骤说明下面加上一步、下一步、播放（每 2.2 秒一步，到最后一步停下，之后变成“重播”）、可以点击跳转的
步骤圆点和步数，聚焦后可用 ← →、Home、End 键；没有脚本时所有步骤按顺序显示。行间公式里用 `\step{2-3}{…}` 标出的部分和 `data-show` 一样随步出现。不在当前步的 `data-show` 元素隐藏但保留位置，画面不跳动；想让后面的状态以
淡影预告，在 figure 上加 `lp-dim`。同一个对象只画一个元素，状态变化放在它里面的小元素上切换，不要为每个状态各画
一行。每一步的说明写出这一步变了什么。

**对照切换** `figure.lp-toggle`：A、B 两种做法共用一个画面时使用。按钮是按下状态的按钮组；初始选中项写
`aria-pressed="true"`。面板写 `data-label`（与按钮文字相同），不写 `hidden`，由运行时隐藏没选中的那个；没有脚本和打印时
两组都带着标签显示，示例图 1.1 就是这样做的。也可以不分面板，只画一张图，用 `.js #图id[data-view="…"]` 选择器让
同一批图形随视图变化；
这种写法在没有脚本和打印时把两种状态叠在一张图里显示，图注要把两种状态都说清。

```html
<figure class="lp-figure lp-toggle" id="fig-1-1">
  <div class="lp-controls"><div class="lp-seg">
    <button type="button" data-view="naive" aria-pressed="true">朴素实现</button>
    <button type="button" data-view="tiled" aria-pressed="false">分块实现</button>
  </div></div>
  <div class="lp-canvas"><div data-panel="naive" data-label="朴素实现">…</div><div data-panel="tiled" data-label="分块实现">…</div></div>
  <figcaption><b>图 1.1</b>…</figcaption>
</figure>
```

**参数探索** `figure.lp-explorer`：先给真实配置的预设，再给滑块；输出带单位。预设按控件类型赋值（单选选中对应项，
复选框取真假），超出滑块范围时部件报错而不是悄悄截断；学习者手动改动后预设按钮不再显示为按下。读数变化时从旧值
过渡到新值并闪一下；输出上加 `data-bar="上限"` 会在下面画一条按比例填充的读数条。

```html
<figure class="lp-figure lp-explorer" id="fig-3-1" data-cases='[{"in":{"n":8192,"bytes":2},"out":{"s":134217728}}]'>
  <div class="lp-controls">
    <button type="button" class="lp-btn" data-preset='{"n":8192}'>8K 序列</button>
    <label>序列长度 <input type="range" name="n" min="1024" max="32768" step="1024" value="4096"> <span class="lp-out" data-value-of="n"></span></label>
    <input type="hidden" name="bytes" value="2">
  </div>
  <dl class="lp-readout"><dt>单头 S 的大小</dt><dd><span class="lp-out" data-out="s_text"></span></dd></dl>
  <figcaption><b>图 3.1</b>…</figcaption>
</figure>
```

**可调段落** `p.lp-live`：正文一句话里有一两个参数、想让读者看结论怎样随它变时使用。比参数探索轻，不上实验台，算作这个
节点的部件。

```html
<p class="lp-live" id="live-1-1" data-cases='[{"in":{"n":8192,"bytes":2},"out":{"mib":128}}]'>N = <span class="lp-knob"
  data-knob="n" data-label="序列长度 N" data-values="1024,4096,8192,32768">8192</span> 时，一份 <span class="lp-knob" data-knob="bytes"
  data-label="每个元素的精度" data-values="2,4" data-labels="FP16,FP32">FP16</span> 的 S 是 <span data-out="s">128 MiB</span>。</p>
```

`data-values` 至少两个取值，`data-labels` 写显示文字（同值可省），初值须在其中；`data-out` 放随动结果。计算函数注册在 `LessonPage.explorers[段落 id]`，返回显示文字及供 `data-cases` 自检的数值；正文初值须与函数一致，否则控制台报错。运行时画成可拖动/点按/方向键切换的 ‹ › 拨盘，改过后出现“还原”；无脚本时退化为普通文字。拨盘只能放在 `.lp-live` 内。

**口述计时** `<div class="lp-timer" data-seconds="90"></div>`：只计时不给提纲，可放口述题块。

**代码与符号**：`pre.lp-code` 自动加行号、代码头与复制，`data-highlight` 静态高亮，`ol.lp-code-notes` 与代码行悬停互亮（正文说“指向或点按说明”，不说左右）。带 `lp-s1`–`lp-s4` 的符号悬停全页互亮，匹配符号表 `dt` 时浮出释义；行间公式悬停可复制 TeX。

**导航与部件包**：`data-stages` 驱动骨架地铁通车与节点站牌；页头“地层”按版本分层回看，均自动生成。其余 10 个部件包见 [widget-packs.md](widget-packs.md)。

## 4. 自定义计算

只有内置部件画不出、需要按公式算出状态时，才在片段里写 `<script data-lp-hook>`，并只注册函数：

```js
LessonPage.onStep["fig-2-1"] = function (step, figure) { /* 按第 step 步重画 figure 里的内容 */ };
LessonPage.explorers["fig-3-1"] = function (values) {
  var s = values.n * values.n * values.bytes;
  return { s: s, s_text: LessonPage.fmt.bytes(s) };
};
```

- 分步演示的钩子 `LessonPage.onStep[id](步号, figure)` 在初始化和每次翻步时调用；对照切换用同一个注册表，收到视图名，
  在初始化和每次切换时调用。参数探索的钩子收到所有带 `name` 的输入值，返回要填进 `data-out` 的值，缺的输出显示“—”。
  `LessonPage.fmt.num(x, 位数)` 与 `LessonPage.fmt.bytes(x)` 负责格式，加载时就能用；钩子自己写的读数用
  `LessonPage.setNumber(元素, 数值, 位数)`，与参数探索的输出一样平滑过渡。
- 写入工具把注册钩子移到正文外、运行时之前；不把脚本留在图与批注之间。
- 钩子出错时运行时在部件下显示一行提示，恢复正常后提示自动消失；有输出却没注册计算函数也会提示。不要让钩子去改
  部件以外的页面。
- 不引入任何外部库或网络请求，页面的内容安全策略也会拦下它们。公式和代码着色已在写入时完成，页面里没有这两个库。

## 5. 数字要可信

- 部件里由公式得出的数字由钩子实时计算，不把算好的数字手抄进分步内容。部件需要不靠脚本也能读的静态数字时，用工具
  算好写进页面，再让钩子按公式复核，不一致就抛错。正文里的真实规模数字用工具算好，注明“按定义计算”或出处。
- 参数探索写 `data-cases`：输入和期望输出用 Python 等工具算好再填，不手算。页面加载时逐条自检，不一致就显示
  错误、停用这个部件。
- 实测得到的数字（编译器输出、`size_of`、计时）可以静态写出，并在图注或批注里写明工具、版本和测法。
- 单位写清：字节用 KiB、MiB 等二进制单位时明说，与资料单位不同时注明换算。
- 真实配置的数字附来源和版本，写在部件说明或节点批注里。

## 6. 交互与可访问性

- 控件都用真正的 `<button>`、`<input>`、`<select>`，有可见文字或 `aria-label`；输入框放在 `<label>` 里。
- 部件自己的动画只解释变化，时长与分工按 [page-design.md](page-design.md) 第 6 节；页面级动效由模板完成，片段不再自加。
- 触屏上按钮不小于 44 像素高，模板已处理；窄屏下内容改成竖排或换行，不要求横向拖动整页。
- 部件只用模板令牌里的颜色，符号色与正文保持一致；颜色之外还要有文字或形状区分。
