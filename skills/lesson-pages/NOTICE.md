# Notice

`references/page-design.md` 与 `assets/lesson-template.html` 中的部分视觉规则改编自 oil-ui：

- 来源：https://github.com/oil-oil/oil-ui ，提交 7002e1a3b3e3bc19d4159e2a37917456dafd5ad4（v0.23.9）
- 改编的部分：`references/visual-language.md` 的可读性门槛、中文断行与控件语法，`references/motion.md` 的动效
  时长、呼应与“减少动态效果”规则，`references/tools.md` 列出的模型默认做法，以 `references/reviewer-manual.md`
  为参照的视觉检查要点。规则已按课程讲义的阅读场景改写，不包含 oil-ui 的脚本、素材、字体、版本检查或付费版提示。

oil-ui 以 MIT 许可证发布，原文如下：

```text
MIT License

Copyright (c) 2026 oil-oil

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 随附的渲染库

`assets/vendor/` 原样附带两个库的发布文件，只在 `scripts/render.cjs` 写入页面时于本机 Node 中运行，页面本身不加载
它们。KaTeX 的样式表和用到的字体会嵌进含公式的页面，嵌入块里带有下面两份许可的全文。

- KaTeX 0.19.0（npm 包 `katex`，完整性 `sha512-v6Tznz3zJ7u3niRCoDTsumM2+HA2XXcCu+WAacCeHD2z3p9A9Ks987o5FzfTGBN0e8A0vjEgIDvLbICrXpdw/Q==`）：
  `dist/katex.min.js` 与 `dist/katex.min.css` 为 MIT 许可，Copyright (c) 2013-2020 Khan Academy and other
  contributors，全文见 `assets/vendor/katex/LICENSE`。`dist/fonts/*.woff2` 为 SIL Open Font License, Version 1.1，
  Copyright (c) 2009-2010 Design Science, Inc. 与 (c) 2014-2018 Khan Academy，保留字体名 KaTeX_AMS、KaTeX_Caligraphic、
  KaTeX_Fraktur、KaTeX_Main、KaTeX_Math、KaTeX_SansSerif、KaTeX_Script、KaTeX_Size1–4、KaTeX_Typewriter；字体未经
  修改，全文见 `assets/vendor/katex/fonts/OFL.txt`。
- highlight.js 11.12.0（npm 包 `@highlightjs/cdn-assets`，完整性
  `sha512-KvOKXODaiFmId9xaq3xc5xCL66wVLUuOngDbO9B/kewbFTqdGbn2nJxNhN3H5R1cgDTVj6R8vH0zgiNDEGjpDw==`）：`highlight.min.js`
  （常用 36 种语言）。BSD 3-Clause 许可，Copyright (c) 2006, Ivan Sagalaev，全文见 `assets/vendor/highlight/LICENSE`。
  页面里只有它输出的 `hljs-*` 标记，配色是本 Skill 自己的令牌。

每个文件的 SHA-256 记在 `tests/test_lesson_pages.py` 的 `VENDORED` 里；升级步骤见仓库的
`docs/dev/lesson-pages-design.md`。

