# lesson-pages 维护说明

本文给维护 `skills/lesson-pages` 的人看：模板怎样组成、改样式时要守住什么、怎样重建示例页并检查画面。
行为规则以 [SKILL.md](../../skills/lesson-pages/SKILL.md) 和它的参考文件为准，决策背景见
[D55](../learning-skills-review.md)。

## 文件分工

| 文件 | 作用 |
| --- | --- |
| `assets/lesson-template.html` | 唯一的页面模板：内容安全策略、标记 meta、`#lp-boot`、`#lp-base`、`#lp-page-style`、页头、两个插入标记、符号表与来源、`#lp-runtime` |
| `scripts/lesson_pages.py` | `new`、`add`、`state`、`render`、`check`、`outline`、`find`、`serve`；只用标准库 |
| `scripts/render.cjs` | 写入时由 Node 运行：用 KaTeX 渲染 `.tex`，用 highlight.js 给 `pre.lp-code[data-lang]` 着色 |
| `assets/vendor/` | KaTeX 0.19.0 与 highlight.js 11.12.0 的发布文件，原样附带，许可与校验值见 `NOTICE.md` |
| `scripts/context_config.py` | 受管配置 `agent-skills.lesson-pages/v1` 的严格校验 |
| `references/example-*.html` | 片段示例；测试用它们经 `new` 与 `add` 生成完整页面并要求零错误、零警告 |

模板里的 `{{…}}` 槽位由 `new` 替换。页面里出现公式后，脚本在 `#lp-page-style` 之前写入 `<style id="lp-katex">`：
KaTeX 样式表、许可全文，以及按本页公式实际用到的字体（从 KaTeX 的字体规则推出，以 base64 内嵌；`.katex` 本身的
行高用 KaTeX_Main，所以它总在其中）；后来的公式用到新字体时只扩充这一块。块头记着 KaTeX 版本：版本变了，下一次写入
会先把全页公式按 `data-tex` 重新渲染，再换样式表，旧标记不会配上新样式。KaTeX 写进每个公式的 TeX 注记与 `data-tex`
不一致时，`check` 报 `math.stale`，`render` 会重排它；`render` 对没有变化的页面不升版本。`<!-- lp:content -->` 只在建页时使用，建页后删除；`<!-- lp:append -->` 是之后
每次追加的位置，每页恰好一个。

## 改模板时守住的约束

- 页面必须离线：内容安全策略为 `default-src 'none'`，只放行内联样式与脚本、同源与 `data:` 图片、`data:` 字体、同源
  连接（供本地服务的版本轮询）。`check` 要求页面中的策略与 `lesson_pages.py` 的 `CSP` 常量逐字相同，改策略时两处一起改。
- `#lp-boot`、`#lp-base`、`#lp-runtime` 是页面不能手改的三段。`check` 把页面里的这三段与当前模板比较，`#lp-katex`
  与按它记下的字体重新生成的结果比较，不同时给出 `runtime.drift` 警告；旧页面不会被自动迁移。
- 页面里没有 KaTeX 和 highlight.js 的脚本：渲染只发生在写入时。`render.cjs` 只放行 `\htmlClass` 的类名和
  `\htmlData` 的 `data-show` 步数，拒绝链接、内联样式和固定颜色（KaTeX 对不放行的命令只上错误色而不抛错，所以按
  输出里的颜色判断；错误色设成专用色值，连 `\phantom` 里和 MathML 副本里的也查得到）。片段在解析前统一为 LF，
  高亮结果再按页面的换行写回，避免孤立的 CR 让浏览器多出一行。
- 运行时的每个初始化步骤都包在 `try` 里，部件出错只在部件下显示一行提示；没有脚本时，所有内容（包括分步演示的
  每一步）都按顺序可读。
- 页面级动效各只做一次：封面升起、滚入视野时淡入（只给图、表、引用块、行间公式、补充和题目块）、骨架逐点画出、导师
  划线、开放题标记轻闪三下。只有支持 IntersectionObserver 且未开启“减少动态效果”时，运行时才给根元素加 `lp-motion`，
  隐藏状态只在这个类下生效；打印前全部显示。不做自动循环；分步演示的播放由读者按下，最后一步停止。
- 体积预算：模板不超过 110,000 字节，由 `tests/test_learning_skills.py` 检查。Agent 不读模板，`new` 直接复制它。

## 视觉令牌

北极星是“安静的讲义，发亮的实验台”。下表是页面令牌，对比度按 WCAG 相对亮度计算，背景为 `--paper`（浅色
`#fbfbf8`，深色 `#181a1e`）。深色主题的 `--mark` 为 `#4d3f17`，正文在其上为 8.2。深色主题下封面 `#0d0f12`
与实验台 `#0c0e11` 都比页面深，封面靠底边线、实验台靠阴影、顶边高光和蓝色辉光与页面区分。打印只用浅色令牌：深色
主题的令牌限定在 `screen` 媒体里。

| 令牌 | 浅色 | 对比度 | 深色 | 对比度 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `--ink` | `#1e2024` | 15.7 | `#e7e5df` | 13.8 | 正文 |
| `--ink-soft` | `#474a52` | 8.6 | `#b9b7b0` | 8.7 | 次要文字 |
| `--ink-faint` | `#696c75` | 5.1 | `#8f8e89` | 5.3 | 说明、行号 |
| `--accent` | `#b23f27` | 5.6 | `#f08c6d` | 7.2 | 导师划线、批注“注”、层次圆点、代码讲到的行、开放题、主按钮 |
| `--accent-ink` | `#9a321e` | 7.1 | `#f4a286` | 8.6 | 朱红文字 |
| `--s1` | `#0062a3` | 6.2 | `#6cb6f0` | 8.0 | 符号色一 |
| `--s2` | `#00765a` | 5.4 | `#3fcf9f` | 8.8 | 符号色二 |
| `--s3` | `#a0407a` | 5.8 | `#e397c4` | 7.9 | 符号色三 |
| `--s4` | `#8f5b00` | 5.5 | `#e9b84a` | 9.5 | 符号色四 |

实验台（三种部件、`.is-stage` 的图、代码块与代码头）在两种主题下都换用一组深色令牌，底色为 `--stage`（浅色主题
`#121418`，深色主题 `#0c0e11`，比页面更深）。下表是实验台令牌在 `#121418` 上的对比度，括号里是在讲到的行
（`--accent-wash` `#3e231c`）上的对比度；代码配色只在实验台里使用，打印时整组换成浅底版本（都在 5.2 以上）。

| 令牌 | 色值 | 对比度 | 令牌 | 色值 | 对比度 |
| --- | --- | --- | --- | --- | --- |
| `--ink` | `#eceae4` | 15.3（11.9） | `--code-kw` | `#bb9af7` | 8.0（6.2） |
| `--ink-soft` | `#c2c0b9` | 10.1（7.9） | `--code-str` | `#9ece6a` | 10.1（7.9） |
| `--ink-faint` | `#8f8e89` | 5.6 | `--code-num` | `#ff9e64` | 9.1（7.1） |
| `--accent` | `#ff8f6b` | 8.2 | `--code-fn` | `#7aa2f7` | 7.3（5.7） |
| `--s1`–`--s4` | 与深色主题相同 | 8.3–10.0 | `--code-type` | `#73daca` | 11.1（8.6） |
| `--code-meta` | `#e0af68` | 9.2（7.2） | `--code-com` | `#8d94a6` | 6.1（4.7） |

讲到的行和行注聚焦的行，行号改用 `--ink-soft`。封面带 `--band` 上的 `--band-ink` 为 16.0（深色主题 16.5），
`--band-soft` 为 9.2（9.6）。开放题的题头条是 `--accent` 底上的 `--paper` 字：浅色 5.6，深色 7.2；条上“在对话中回答”
是 `--paper` 底上的 `--accent-ink`：7.1 与 8.6。

四种符号色取自 Okabe–Ito 色板并加深到足够的对比度。用 Machado 2009 的红绿色盲模拟，四色两两之间的 CIELAB 色差
最小约为 14（浅色）和 17（深色）；符号色总与符号文字一起出现，颜色只是第二线索。改色时重新计算这两项。

## 重建示例页并检查画面

```bash
mkdir -p /tmp/lp-demo/learning/pages
python skills/lesson-pages/scripts/lesson_pages.py new --repo /tmp/lp-demo \
  --page learning/pages/attn-03.html --id attn-03 --title "分块 softmax 与 FlashAttention 前向" \
  --course "Attention 算子" --label "第 3 课" --spine "FlashAttention-2 论文 v1" \
  --fragment skills/lesson-pages/references/example-opening.html
python skills/lesson-pages/scripts/lesson_pages.py add --repo /tmp/lp-demo \
  --page learning/pages/attn-03.html --id attn-03 \
  --fragment skills/lesson-pages/references/example-segment.html
```

`new` 和 `add` 需要本机有 Node，示例里的公式和代码在这一步渲染。然后用浏览器在 1280、768、390 像素宽度和深浅两种
主题下查看：首屏是封面带和导入，往下能看到骨架图；节点 1 的图 1.1 切到“分块实现”时
S、P 缩进片上存储；节点 2 的分步演示五步读数与算式一致，最后一步与“一次看完整行”的结果相同，按钮位置不跳；页边
批注与所属段落顶端对齐；节点 2 的行间公式对齐、符号色正确，代码块着色正确，悬停行注时对应行亮起、悬停符号 m
时全页的 m 一起亮起并浮出释义；检查题与符号表；控制台无报错、整页无横向滚动；开启“减少动态效果”或关闭脚本时
内容全部可见。再试一次 `add --into node-2` 加补充、
`state --to closed --fragment` 关题，确认“本次新增”列出它们。改了模板之后每次都按这个顺序看一遍。

## 升级随附的渲染库

1. 用 `npm pack katex@<版本>` 和 `npm pack @highlightjs/cdn-assets@<版本>` 取得发布包，核对 npm 给出的完整性值，
   先在临时目录解包。
2. 只复制现在附带的那些文件（`katex.min.js`、`katex.min.css`、`fonts/*.woff2`、`LICENSE`；`highlight.min.js`、
   `LICENSE`），不带 woff、ttf、mjs 或源码。字体是 OFL 1.1：核对字体名表里的版权行与保留字体名，必要时更新
   `fonts/OFL.txt` 的抬头，并把 `KATEX_VERSION` 改成新版本。
3. 更新 `NOTICE.md` 的版本与完整性值、`tests/test_lesson_pages.py` 的 `VENDORED` 校验值；字体增减时同步
   `tests/test_learning_skills.py` 的文件清单。
4. 跑全部测试，按上一节重建示例页并查看。KaTeX 的字体规则若有变化，`_katex_faces` 会按新样式表推出字体，已有页面的
   `#lp-katex` 会得到 `runtime.drift` 警告。

## 来源

视觉规则中有一部分改编自 oil-ui（https://github.com/oil-oil/oil-ui ，提交
`7002e1a3b3e3bc19d4159e2a37917456dafd5ad4`，MIT）：`visual-language.md` 的可读性门槛、中文断行与控件语法，
`motion.md` 的动效时长、呼应和“减少动态效果”，`tools.md` 列出的模型默认做法，以及参照 `reviewer-manual.md` 的
视觉检查要点。它们按阅读型讲义改写，许可全文随 Skill 放在 `NOTICE.md`。没有采用的部分：多方向探索与对比页、
落地页滚动叙事、生图与素材检索、版本检查、付费版提示，以及 oil-ui 的全部脚本、字体和图片。
