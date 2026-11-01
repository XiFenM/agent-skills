# Opening

建新页（`new`）或给中途才开始用页面的课补导入时读取本参考；对应 `guide-learning` 的开课导入。完整示例见
[example-opening.html](example-opening.html)，块的通用写法见 [page-structure.md](page-structure.md)。

- **导入** `<section class="lp-narrative" id="intro">`：先说明具体场景、涉及的对象与核心问题，再放骨架图，图后一段讲将形成的
  能力和完成标准；连贯叙述，不写成目标清单或先贴一段抽象结论。路线由目录和骨架承担，不另写一段。尽量让首屏看到
  骨架图，但不为此删去理解场景所需的前提；骨架帮助定位，具体机制仍在后续节点逐步解释。
- **骨架** 导入里的 `<figure class="lp-figure is-wide" id="fig-0">`，用 `<ol class="lp-stages lp-flow">` 列出阶段：
  `<li id="st-…" data-label="短名"><b>阶段名</b><span>传什么、形状</span></li>`；输入输出的形状与精度写在图注里。阶段被节点
  讲到后成为通车的站，没讲的标“未开通”。
- **资料指路** `<section id="spine">`：用三列表格（资料、本课对应、什么时候读），资料名链接到与所用版本一致的公开地址，
  没有时用从页面出发的相对路径（页面目录搬走后会断）。锁定不了版本时写“未锁定”和它的含义；拿不准章节号时写章节标题并注明未核对。会直接回答开放题或计划中
  验收题的段落，安排在那道题关闭之后再读。没有教学主线资料时不写这一节。
- 中途才开始用页面时，导入之后另加 `#recap` 简述已讲节点，见 [upkeep.md](upkeep.md) 第 1 节。
- 多课课程的每页可以在导入末尾链接上一课的页面（用相对链接，只向前链接，不回头改已结课的页面），不做课程总览页。

命令从仓库根运行，页面参数相对 `--repo`；解释器按环境选 `python` 或 `python3`，其他宿主用实际 Skill 路径。
第一次在新确认的目录建页时加 `--make-parents`；建页参数见 `lesson_pages.py new --help`，续页与题目状态见 [upkeep.md](upkeep.md)。

以下使用 Codex 发现入口；其他宿主换成实际 Skill 路径：

```bash
python .agents/skills/lesson-pages/scripts/lesson_pages.py outline --page learning/pages/attn-03.html
python .agents/skills/lesson-pages/scripts/lesson_pages.py add --page learning/pages/attn-03.html --id attn-03 --fragment /tmp/segment.html
python .agents/skills/lesson-pages/scripts/lesson_pages.py check --page learning/pages/attn-03.html --anchor q-2
```
