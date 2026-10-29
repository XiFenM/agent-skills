# 逐步时序图

当“谁先做了什么、谁仍在等待、哪些状态允许复用”是理解关键时，用 `lp-timeline`。时间点是事件边界，
不必是实测毫秒；图上必须分清依据源码／协议整理的因果模型与真实运行轨迹。完整片段见
[example-timeline.html](example-timeline.html)。

## 先决定每一步要让读者看见什么

- 先定义参与者、资源归属、槽位和轮次。任务批次、API调用序号、物理缓冲区应使用不同名字，不能因为同样是两个就混为一层。
- 每步写三个问题的答案：本步发生什么、各参与者持有什么状态、下一动作被哪条依赖允许或阻塞。
  区分“发送已提交”“信号已可观察”“本地消费已完成”“资源可复用”等会改变判断的时点。
- 用一方较慢的合法调度展示等待位置，再说明违反哪条依赖会出错。不要替真实实现画一个源码中没有的全局 barrier、空闲检测或回执。
- 模型只说明声明前提下的机制；性能结论需要对应实测。实际执行且逐行记录的程序轨迹继续使用 `lp-replay` 与 `trace`。
  本部件不要求把每个通信协议伪装成可运行模拟。

## 声明式合同

```html
<figure class="lp-figure lp-stepper lp-timeline is-wide" id="fig-5-1" data-timeline-kind="model">
  <div class="lp-canvas"></div>
  <ol class="lp-steps">
    <!-- 每个 li 都写本步事件、依赖，以及全部参与者／槽位的完整快照。 -->
  </ol>
  <figcaption><b>图5.1</b>按本节给定协议整理的因果顺序，没有测量时长。</figcaption>
</figure>
```

`data-timeline-kind` 必须为 `model` 或 `observed`；后者只用于有实际运行来源的轨迹。
图注写明固定源码／协议依据或运行条件。默认实色；用户要求玻璃外观时可加 `data-timeline-surface="glass"`。
保留空 `div.lp-canvas`，运行时从快照构造状态板，不另写业务钩子。

每个 `ol.lp-steps > li`：

1. `data-title` 是本步短标题。
2. `p.lp-timeline-event` 说明事件与状态变化。
3. `p.lp-timeline-dependency` 说明谁在等什么，或下一步可以发生的条件。
4. `ul.lp-timeline-state` 列出全部槽位，不能省略本步未变的槽。

每个快照项为 `li[data-actor][data-slot][data-status]`。参与者与槽位使用以字母开头的短 key，
只含字母、数字、`-`、`_`；同一 actor 内 slot 唯一。可用状态为 `idle`、`writing`、`ready`、`reading`、`waiting`、`done`，
状态名只服务于呈现，不代替具体说明。每项直接包含四个纯文本字段：

```html
<li data-actor="consumer" data-slot="a" data-status="reading">
  <span class="lp-timeline-owner">消费者</span>
  <b class="lp-timeline-slot">接收槽 A</b>
  <span class="lp-timeline-value">正在读取第0批，尚未允许覆盖。</span>
  <span class="lp-timeline-signal">就绪信号已到；归还回执尚未发出。</span>
</li>
```

首步定义至少两个参与者及各自的槽位，后续每步完整重复同一组 key 和显示名。参与者可以有不同数量的槽位，
不必都是双缓冲。完整快照让跳到中间、退回再前进都得到相同状态，不会继承未来一步的残留。
动态状态不是公式计算器：若展示推导数值，先用工具核算，并在讲解中给出定义与前提。

## 交互与检查

复用 `lp-stepper` 的上一步、下一步、圆点、播放及方向键／Home／End。控件放在图顶；长图和手机上仍可到达，
默认不自动播放。运行时显示当前事件、参与者和槽位、信号及依赖，颜色同时配文字。

无脚本或打印时，所有步骤的完整事件与状态仍可读；减少动态效果保留手动操作，状态直接更新。
输入结构错误时显示错误并回退到静态步骤，不能留下部分更新的状态板。

`check` 校验参与者／槽位集合、显示名、状态枚举及每步说明。按 [browser-checks.md](browser-checks.md)
测试首次显示、跨步跳转、回退再进、末步重播、键盘、长字段、窄屏与无脚本阅读。样式与数据必须分离：
换一套参与者和协议时只换片段，不复制上一课的业务脚本或未经核验的机制。
