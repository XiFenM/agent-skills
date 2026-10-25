# Interactive widgets

做交互部件前读取本参考。部件只为让机制看得见：静态图能讲清的就用静态图。

## Contents

1. [先决定要不要做](#1-先决定要不要做)
2. [不能泄题](#2-不能泄题)
3. [内置部件](#3-内置部件)
4. [自定义计算](#4-自定义计算)
5. [数字要可信](#5-数字要可信)
6. [交互与可访问性](#6-交互与可访问性)

## 1. 先决定要不要做

- 默认用静态图、表格或分步文字。只有“亲手翻步、改条件、切换对照”能让人看到静态图看不到的东西时，才做部件。
- 每个节点至多一个部件，骨架图不算。写一句它的任务：看完这个部件，学习者能看见什么。说不出来就不做。
- 部件不点也要能读懂：没有脚本时步骤说明、两组对照和图注都按顺序可读，钩子画出的内容则不会出现；分步演示一次
  只显示一步，所以要点写进图注。
- 小算例只用来看清规则；部件后面紧接一句真实规模，与 `guide-learning` 的讲解标准一致。
- 部件是学习工具，不是测验：不计分、不记录、不当作理解证据；预测与解释留给对话里的检查题。

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

`data-values` 是至少两个取值，`data-labels` 是显示文字（与取值相同时省略），拨盘里写初值，必须是其中之一；`data-out` 是跟着
变的结果。计算函数注册在 `LessonPage.explorers[段落 id]`，收到各拨盘的取值，返回 `data-out` 要显示的文字，再附几项数值供
`data-cases` 自检。正文写下的结果就是初值算出的结果，格式与计算函数一致；不一致时运行时在控制台报错。运行时给段落加虚线
框和“可调”标签，把拨盘画成带 ‹ › 的小块，指向、聚焦或按住时浮出全部取值，第一次读到时在第一个拨盘上提示一次；拖动、
点按和方向键都能换值，改过后出现“还原”。没有脚本时它就是一段普通文字。拨盘只能放在 `.lp-live` 里。

**口述计时** `<div class="lp-timer" data-seconds="90"></div>`：只计时，不给提纲，可放进口述题块。

**代码** `pre.lp-code`：运行时加行号和写着语言、`data-title` 与“复制”按钮的代码头；`data-highlight` 静态高亮，分步
演示的 `data-lines` 逐步高亮，紧跟的 `ol.lp-code-notes` 让说明与代码行互相指认（悬停或聚焦时亮起，点一下固定）；
宽屏时说明移到批注栏，各自对齐到所讲的第一行，正文里提到它们时说“指向或点按说明”，不说左右。

**符号互认与释义**：指向任何带 `lp-s1`–`lp-s4` 的符号时，正文、公式、代码和图里同色的符号一起亮起；`var` 的文字与
符号表某条 `dt` 相同、链接指向符号表条目，或公式与代码里的符号色与某条 `dt` 的符号色相同时，悬停、聚焦或轻点会
浮出这条释义。所以符号表的 `dt` 写成与正文相同的符号文字，并带上同一种符号色。单个字母的 `var` 显示为数学斜体，与
公式一致。行间公式悬停时可以复制 TeX 原文。

**地铁线路与站牌**：节点的 `data-stages` 对应骨架里的阶段 `id`。讲过的阶段是通车的站，链接到第一次讲它的节点；被几个
节点讲到的是换乘站，列出各节；没讲的站标“未开通”并蒙雾，上次打开以来新通车的站当场散雾。每个节点标题下挂一块站牌：
上一站、本站、下一站。宽屏时目录栏顶上还有一条小地铁，读到哪一节，它讲的站就被套住。

**学习地层**：页头的“地层”按内容加入页面的版本给各块分层着色，图例里点一层只看这一层，拖图例顶上的滑块可以回看早先
某一层时的页面。不用写标记。

**部件包**：海报、对数尺、误区对照、类比卡、公式解剖、逐行推导、执行回放与系统结构图只写进用到它们的页面，写法与
取舍见 [widget-packs.md](widget-packs.md)。

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
