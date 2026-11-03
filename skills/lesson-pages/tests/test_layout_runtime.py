"""Browser regressions for the generated runtime (no server or network required).

These tests run when playwright-cli and a local Chromium are available. Set
PLAYWRIGHT_CHROMIUM_EXECUTABLE to select a browser outside Playwright's cache.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _chromium() -> Path | None:
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache/ms-playwright"))
    candidates = sorted(cache.glob("chromium-*/chrome-linux*/chrome"), reverse=True)
    if candidates:
        return candidates[0]
    system = shutil.which("chromium") or shutil.which("google-chrome")
    return Path(system) if system else None


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    cli, executable = shutil.which("playwright-cli"), _chromium()
    if not cli or executable is None:
        pytest.skip("layout tests require playwright-cli and local Chromium")
    work = tmp_path_factory.mktemp("lesson-layout-browser")
    config = work / "browser.json"
    config.write_text(json.dumps({
        "allowUnrestrictedFileAccess": True,
        "browser": {
            "browserName": "chromium",
            "launchOptions": {
                "executablePath": str(executable), "headless": True,
                "args": ["--no-sandbox"] if getattr(os, "geteuid", lambda: 1)() == 0 else [],
            },
        },
    }), encoding="utf-8")
    session = "layout-" + uuid.uuid4().hex[:12]

    def call(*args: str) -> str:
        result = subprocess.run(
            [cli, "-s=" + session, "--raw", *args], cwd=work,
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "### Error" not in result.stdout, result.stdout
        return result.stdout.strip()

    call("open", "about:blank", "--config=" + str(config))

    def run(script: str):
        path = work / "action.js"
        path.write_text(script, encoding="utf-8")
        output = call("run-code", "--filename=" + str(path))
        # --raw is JSON for returned objects; older CLI builds retain headings.
        if output.startswith("### Result\n"):
            output = output.split("\n", 1)[1].split("\n### ", 1)[0]
        return json.loads(output)

    yield run
    call("close")


def _page(tmp_path: Path, content: str, *, scale: bool = False,
          look: str = "handout", packs: tuple[str, ...] = ()) -> Path:
    source = (ASSETS / "lesson-template.html").read_text(encoding="utf-8")
    values = {"lang": "zh-CN", "id": "layout", "key": uuid.uuid4().hex[:12],
              "title": "布局回归", "title_full": "布局回归", "date": "2026-10-29"}
    source = re.sub(r"\{\{lp:([a-z_]+)\}\}", lambda m: values.get(m[1], ""), source)
    source = source.replace("<!-- lp:content -->", content)
    if look != "handout":
        css = (ASSETS / "looks" / (look + ".css")).read_text(encoding="utf-8")
        source = source.replace('<html lang="zh-CN">', '<html lang="zh-CN" data-look="' + look + '">')
        source = source.replace("</head>", '<style id="lp-look">' + css + "</style></head>")
    for pack in dict.fromkeys(packs + (("scale",) if scale else ())):
        css = ASSETS / "packs" / (pack + ".css")
        js = ASSETS / "packs" / (pack + ".js")
        if css.is_file():
            source = source.replace("</head>", "<style>" + css.read_text(encoding="utf-8") + "</style></head>")
        if js.is_file():
            source = source.replace('<script id="lp-runtime">', "<script>" + js.read_text(encoding="utf-8") + '</script><script id="lp-runtime">')
    path = tmp_path / "layout.html"
    path.write_text(source, encoding="utf-8")
    return path


def _start(path: Path, width: int = 1280) -> str:
    return ("async page => { await page.setViewportSize({width:" + str(width) + ",height:900});"
            "await page.emulateMedia({reducedMotion:'reduce'});"
            "await page.goto(" + json.dumps(path.as_uri()) + ");"
            "await page.waitForTimeout(200);")


def test_notes_skip_non_content_anchors_and_stay_at_document_coordinates(browser, tmp_path):
    page = _page(tmp_path, """
      <section id="notes"><h2>批注定位</h2><div style="height:1200px"></div>
      <figure id="anchor" class="lp-figure is-wide" style="height:180px">可见图</figure>
      <script>void 0;</script><style>.unused {color:inherit}</style><template>模板</template>
      <div hidden>隐藏内容</div><div style="visibility:hidden;height:1px">不可见</div>
      <div style="height:0;width:0"></div><script>void 0;</script>
      <aside id="fallback" class="lp-note">来源说明应紧跟可见图，而不是视口。</aside>
      <p id="explicit-anchor" style="margin-top:320px">显式关联段落</p>
      <p id="decoy" style="margin-top:100px">另一个可见段落</p>
      <aside id="explicit" class="lp-note" data-note-for="#explicit-anchor">显式来源</aside>
      <figure id="next" class="lp-figure is-wide" style="height:200px">后面的宽图</figure>
      <div style="height:1800px"></div></section>
    """)
    results = browser(_start(page) + """
      const samples=[];
      for (const top of [0,1500,2100,0]) {
        await page.evaluate(top => window.scrollTo({top,behavior:'instant'}), top);
        await page.evaluate(()=>document.dispatchEvent(new CustomEvent('lp:layout')));
        await page.waitForTimeout(120);
        samples.push(await page.evaluate(()=>{
          const y=id=>document.getElementById(id).getBoundingClientRect().top+scrollY;
          return {note:y('fallback'), anchorBottom:document.getElementById('anchor').getBoundingClientRect().bottom+scrollY,
            explicit:y('explicit'), explicitAnchor:y('explicit-anchor'), next:y('next')};
        }));
      }
      return samples;
    }""")
    for sample in results:
        assert abs(sample["note"] - sample["anchorBottom"] - 12) < 1
        assert abs(sample["explicit"] - sample["explicitAnchor"]) < 1
        for key in ("note", "explicit", "next"):
            assert abs(sample[key] - results[0][key]) < 1


def test_wrapped_toggle_thumb_tracks_keyboard_selection_and_resize(browser, tmp_path):
    buttons = "".join(f'<button type="button" data-view="v{i}" aria-pressed="{str(i == 0).lower()}">Choice {i}</button>' for i in range(6))
    panels = "".join(f'<div data-panel="v{i}">Panel {i}</div>' for i in range(6))
    page = _page(tmp_path, '<section><h2>切换</h2><figure id="tabs" class="lp-figure lp-toggle">'
                 '<div class="lp-seg" style="width:280px;flex-wrap:wrap">' + buttons + '</div>' + panels + '</figure></section>')
    result = browser(_start(page) + """
      const button=page.locator('#tabs button[data-view="v5"]');
      await button.focus(); await page.keyboard.press('Enter'); await page.waitForTimeout(350);
      const sample=()=>page.evaluate(()=>{
        const root=document.querySelector('#tabs'), selected=root.querySelector('[aria-pressed="true"]');
        const a=selected.getBoundingClientRect(), b=root.querySelector('.lp-seg-thumb').getBoundingClientRect();
        return {delta:[a.x-b.x,a.y-b.y,a.width-b.width,a.height-b.height],
          selected:selected.dataset.view, focus:document.activeElement===selected,
          rows:new Set([...root.querySelectorAll('button[data-view]')].map(x=>x.offsetTop)).size,
          visible:[...root.querySelectorAll('[data-panel]')].filter(x=>!x.hidden).map(x=>x.dataset.panel),
          pressed:root.querySelectorAll('[aria-pressed="true"]').length};
      });
      const wrapped=await sample();
      await page.evaluate(()=>document.querySelector('#tabs .lp-seg').style.width='620px');
      await page.waitForTimeout(150);
      return {wrapped, resized:await sample()};
    }""")
    assert result["wrapped"]["rows"] > 1
    assert result["resized"]["rows"] == 1
    for sample in result.values():
        assert sample["selected"] == "v5" and sample["visible"] == ["v5"]
        assert sample["pressed"] == 1 and sample["focus"]
        assert max(map(abs, sample["delta"])) < 1


def test_scale_fits_readouts_by_count_width_and_font_without_splitting_units(browser, tmp_path):
    def figure(id_: str, labels: list[str]) -> str:
        items = "".join(f'<li data-value="{10 ** (i + 1)}"><b>数值 {i}</b>{label}</li>' for i, label in enumerate(labels))
        return f'<figure id="{id_}" class="lp-figure lp-scale" data-unit="B" style="width:700px;max-width:100%"><ol>{items}</ol></figure>'
    page = _page(tmp_path, '<section><h2>数量尺</h2>'
                 + figure("short", ["3.5 MiB", "28 MiB", "112 MiB", "448 MiB", "3.5 GiB", "14 GiB"])
                 + figure("long", ["1 GiB", "12345678901234567890123456789012345678901234567890.125 GiB"])
                 + '</section>', scale=True)
    result = browser(_start(page, 1440) + """
      const measure=()=>page.evaluate(()=>['short','long'].map(id=>{
        const figure=document.getElementById(id), list=figure.querySelector('.lp-scale-view>ol');
        return {id, vertical:figure.classList.contains('is-vertical'),
          values:[...list.querySelectorAll('li[data-value]')].map(li=>{
            const value=li.querySelector('.lp-scale-value') || li.querySelector('.nb');
            const a=li.getBoundingClientRect(), b=value.getBoundingClientRect();
            const range=document.createRange(); range.selectNodeContents(value);
            return {text:value.textContent.trim(),font:parseFloat(getComputedStyle(li).fontSize),
              fits:b.left>=a.left && b.right<=a.right, noOverflow:value.scrollWidth<=value.clientWidth+1,
              nowrap:getComputedStyle(value).whiteSpace, lines:range.getClientRects().length};
          })};
      }));
      const desktop=await measure();
      await page.locator('#short button[data-mode="linear"]').click();
      await page.setViewportSize({width:390,height:900}); await page.waitForTimeout(200);
      const mobile=await measure();
      await page.setViewportSize({width:1440,height:900}); await page.waitForTimeout(200);
      return {desktop,mobile,again:await measure()};
    }""")
    assert not result["desktop"][0]["vertical"], result
    assert result["desktop"][1]["vertical"], result
    assert all(item["vertical"] for item in result["mobile"])
    assert result["desktop"] == result["again"]
    for layout in result.values():
        for item in layout:
            for value in item["values"]:
                assert value["fits"] and value["nowrap"] == "nowrap"
                assert value["font"] >= 16
                if item["id"] == "short":
                    assert value["noOverflow"]


def test_reusable_browser_check_reports_overflow_without_changing_reader_state(browser, tmp_path):
    helper = (ASSETS.parent / "scripts" / "browser_checks.js").read_text(encoding="utf-8")
    page = _page(tmp_path, '<section id="content"><h2>检查函数</h2><p>正常内容。</p><div style="height:1800px"></div></section>')
    result = browser(_start(page, 1024) + """
      await page.evaluate(()=>{document.documentElement.dataset.theme='dark'; localStorage.setItem('audit-marker','keep'); window.scrollTo(0,400);});
      const state=()=>page.evaluate(()=>({width:innerWidth,theme:document.documentElement.dataset.theme,y:scrollY,marker:localStorage.getItem('audit-marker'),url:location.href}));
      const before=await state();
      const audit=""" + helper + ";\n" + """
      const report=await audit(page,{widths:[390],themes:['light'],maxLandmarks:0,settleMs:900});
      return {before,after:await state(),report};
    }""")
    assert result["report"]["ok"] and result["report"]["visualReviewRequired"]
    assert result["before"] == result["after"]
    page = _page(tmp_path, '<section id="content"><h2>宽度错误</h2><div style="width:2000px">这段撑宽页面。</div></section>')
    result = browser(_start(page, 1024) + "const audit=" + helper + ";\n"
                     + "return await audit(page,{widths:[390],themes:['light'],maxLandmarks:0,settleMs:900});}")
    assert not result["ok"]
    assert any(issue["kind"] == "page-overflow" for issue in result["issues"])


def test_print_code_wraps_long_lines_and_preserves_pdf_tail(browser, tmp_path):
    ascii_tail = "END_OF_LONG_CODE_LINE"
    chinese_tail = "无原子与内存序保证。"
    long_token = "registered_buffer_dependency_" * 18
    code = ("const auto key = \"" + long_token + "\"; // " + ascii_tail + "\n"
            + "说明：" + "等待接收完成后才能复用缓冲区；" * 24 + chinese_tail)
    page = _page(tmp_path,
                 '<style>@page { size: A4; margin: 12mm; }</style>'
                 '<section id="code-print"><h2>打印长代码行</h2>'
                 '<pre class="lp-code" data-lang="text" data-title="buffer-cpp/README.md"><code>'
                 + html.escape(code) + '</code></pre></section>')
    pdf = tmp_path / "code-a4.pdf"
    result = browser(_start(page, 794) + """
      const measure=()=>page.evaluate(()=>{
        const pre=document.querySelector('#code-print pre'), block=pre.getBoundingClientRect();
        const code=pre.querySelector('code'), lines=[...pre.querySelectorAll('.lp-line')];
        const ranges=lines.flatMap(line=>{
          const range=document.createRange(); range.selectNodeContents(line);
          return [...range.getClientRects()].map(r=>({left:r.left,right:r.right}));
        });
        return {scrolls:pre.scrollWidth>pre.clientWidth+1, width:block.width,
          codeWidth:code.getBoundingClientRect().width,
          text:lines.map(line=>line.textContent).join('\\n'),
          wrapped:lines.map(line=>line.getBoundingClientRect().height>parseFloat(getComputedStyle(line).lineHeight)*1.5),
          contained:ranges.every(r=>r.left>=block.left-1 && r.right<=block.right+1)};
      });
      const screen=await measure();
      await page.emulateMedia({media:'print'}); await page.waitForTimeout(150);
      const print=await measure();
      await page.pdf({path:""" + json.dumps(str(pdf)) + """, format:'A4', preferCSSPageSize:true, printBackground:true});
      await page.emulateMedia({media:'screen'}); await page.waitForTimeout(100);
      return {screen,print,again:await measure()};
    }""")
    assert result["screen"]["scrolls"] and result["again"]["scrolls"]
    assert result["screen"]["text"] == result["print"]["text"] == result["again"]["text"] == code
    assert not result["print"]["scrolls"], result["print"]
    assert result["print"]["codeWidth"] <= result["print"]["width"] + 1
    assert result["print"]["contained"] and all(result["print"]["wrapped"])
    if pdftotext := shutil.which("pdftotext"):
        extracted = subprocess.run([pdftotext, "-layout", str(pdf), "-"],
                                   capture_output=True, text=True, check=True, timeout=20)
        text = re.sub(r"\s+", "", extracted.stdout)
        assert ascii_tail in text and chinese_tail in text, extracted.stdout
        assert long_token in text


COPY_CODE = "def schedule(request):\n    if request.ready:\n        return request.value\n\n    return None"


def _copy_content(extra: str = "") -> str:
    """Author markup only: runtime-generated controls must never enter the export."""
    return """
      <section id="spine"><h2>流程骨架</h2><ol class="lp-stages lp-flow">
        <li id="st-queue" data-label="排队"><b>排队</b><p>进入队列。</p></li>
        <li id="st-read" data-label="读取数据"><b>读取数据</b><p>准备输入。</p></li>
        <li id="st-run" data-label="执行任务"><b>执行任务</b><p>运行计算。</p></li>
        <li id="st-release" data-label="归还资源"><b>归还资源</b><p>释放持有。</p></li>
        <li id="st-end" data-label="结束"><b>结束</b><p>完成流程。</p></li>
      </ol></section>
      <section class="lp-node" id="node-copy" data-stages="st-read,st-run,st-release">
        <h2><span class="lp-no">1</span> 节点复制与数据依赖的完整说明</h2>
        <p class="lp-spine">资料位置：<a href="#spine">流程骨架</a>。</p>
        <p id="copy-body">原始正文包含 <strong>关键条件</strong>、<em>适用边界</em>和
          <code>buffer_id</code>；参考<a href="https://example.test/reference?q=a&amp;mode=b">接口说明</a>。</p>
        <ol><li>读取阶段<ul><li>等待信号</li><li>检查记录<ol><li>关联请求</li></ol></li></ul></li>
          <li>交付阶段</li></ol>
        <pre class="lp-code" data-lang="python" data-title="schedule.py" data-start="41"><code>""" + html.escape(COPY_CODE) + """</code></pre>
        <table><thead><tr><th>名称</th><th>状态</th></tr></thead>
          <tbody><tr><td>请求 A</td><td>ready | blocked</td></tr>
          <tr><td colspan="2">跨列说明</td></tr></tbody></table>
        <p>行内公式 <span data-tex="x_i"><span class="katex"><span class="katex-mathml" hidden>MATHML_DUPLICATE</span><span class="katex-html">VISUAL_DUPLICATE</span></span></span>。</p>
        <div class="tex" data-tex="a+b"><span class="katex"><span class="katex-mathml" hidden>DISPLAY_MATHML_DUPLICATE</span><span class="katex-html">DISPLAY_VISUAL_DUPLICATE</span></span></div>
        <section class="lp-addendum" id="copy-supplement-1" data-rev="2">
          <h3>补充一：额外约束</h3><p>第一处补充的完整正文。</p>
          <details><summary>隐藏补充</summary><p>关闭的 details 仍包含 <code>hidden_value</code>。</p>
            <details><summary>嵌套细节</summary><p>第二层折叠正文。</p></details>
          </details>
        </section>
        <section class="lp-addendum" id="copy-supplement-2" data-rev="3">
          <h3>补充二：完整性</h3><p>第二处补充也必须包含。</p>
        </section>
        """ + extra + """
        <p class="lp-lead"><b>本节归纳</b>同一节点保留完整说明。</p>
      </section>
      <section class="lp-node" id="node-other" data-stages="st-end">
        <h2><span class="lp-no">2</span> 相邻节点</h2><p>不得包含的相邻节点正文。</p>
      </section>
    """


@pytest.mark.parametrize("look", ["handout", "blueprint", "vermilion"])
def test_multi_stage_sign_and_node_copy_header_fit_all_looks(browser, tmp_path, look):
    page = _page(tmp_path, _copy_content(), look=look)
    result = browser(_start(page, 1440) + """
      await page.locator('#node-copy .lp-node-copy').waitFor();
      const measure=()=>page.evaluate(()=>{
        const node=document.getElementById('node-copy'), sign=node.querySelector('.lp-sign');
        const here=sign.querySelector('.lp-sign-here');
        const names=[...here.querySelectorAll('span')].filter(el=>el.textContent.trim());
        const box=el=>{const r=el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
        const overlaps=(a,b)=>a.left<b.right-1 && a.right>b.left+1 && a.top<b.bottom-1 && a.bottom>b.top+1;
        const labels=names.map(box), pieces=[...sign.children].filter(el=>!el.classList.contains('lp-sign-line')).map(box);
        const h2=node.querySelector(':scope > h2'), button=node.querySelector('.lp-node-copy');
        const signBox=box(sign), title=box(h2), copy=box(button);
        return {width:innerWidth, pageWidth:document.documentElement.scrollWidth,
          labels:labels.length, sameRow:labels.every(r=>Math.abs(r.top-labels[0].top)<1),
          labelsClear:labels.every((r,i)=>labels.slice(i+1).every(s=>!overlaps(r,s))),
          piecesClear:pieces.every((r,i)=>pieces.slice(i+1).every(s=>!overlaps(r,s))),
          contained:[...labels,...pieces,copy].every(r=>r.left>=-1 && r.right<=innerWidth+1),
          signFits:sign.scrollWidth<=sign.clientWidth+1 && signBox.left>=-1 && signBox.right<=innerWidth+1,
          headerClear:!overlaps(title,copy), copyVisible:copy.width>0 && copy.height>0,
          title:h2.textContent.trim(),
          toc:[...document.querySelectorAll('.lp-toc a[href="#node-copy"], .lp-toc-inline a[href="#node-copy"]')]
            .filter(a=>!a.closest('.lp-minimetro')).map(a=>a.textContent.trim())};
      });
      const desktop=await measure();
      await page.setViewportSize({width:390,height:900}); await page.waitForTimeout(200);
      const mobile=await measure();
      await page.setViewportSize({width:1440,height:900}); await page.waitForTimeout(200);
      return {desktop,mobile,again:await measure()};
    }""")
    assert result["desktop"]["sameRow"] and result["again"]["sameRow"], result
    for layout in result.values():
        assert layout["labels"] == 3 and layout["copyVisible"], layout
        assert layout["pageWidth"] <= layout["width"] + 1, layout
        for key in ("labelsClear", "piecesClear", "contained", "signFits", "headerClear"):
            assert layout[key], (look, key, layout)
        assert "节点复制与数据依赖的完整说明" in layout["title"]
        assert layout["toc"]
        assert all("节点复制与数据依赖的完整说明" in title for title in layout["toc"])
        assert not re.search(r"复制为|已复制|Markdown", layout["title"] + " ".join(layout["toc"]))


def test_node_markdown_preserves_authored_content_and_ignores_rendered_ui(browser, tmp_path):
    page = _page(tmp_path, _copy_content())
    result = browser(_start(page) + """
      return await page.evaluate(()=>{
        const node=document.getElementById('node-copy');
        return {byId:LessonPage.nodeMarkdown('node-copy'), byElement:LessonPage.nodeMarkdown(node),
          byHash:LessonPage.nodeMarkdown('#node-copy'),
          codeDecorated:!!node.querySelector('.lp-code-head') && !!node.querySelector('.lp-line'),
          stationGenerated:!!node.querySelector('.lp-sign'),
          closedDetails:[...node.querySelectorAll('details')].every(el=>!el.open)};
      });
    }""")
    md = result["byId"]
    assert md == result["byElement"] == result["byHash"]
    assert result["codeDecorated"] and result["stationGenerated"] and result["closedDetails"]
    assert re.match(r"##\s+1\s+节点复制与数据依赖的完整说明", md), md
    assert "原始正文包含" in md and "**关键条件**" in md and "*适用边界*" in md
    assert "`buffer_id`" in md
    assert any(link in md for link in (
        "[接口说明](https://example.test/reference?q=a&mode=b)",
        "[接口说明](<https://example.test/reference?q=a&mode=b>)",
    )), md
    assert re.search(r"(?m)^1\. 读取阶段", md), md
    nested = re.search(r"(?m)^( +)[-*] 等待信号", md)
    deeper = re.search(r"(?m)^( +)1\. 关联请求", md)
    assert nested and deeper and len(deeper[1]) > len(nested[1]) >= 2, md
    assert re.search(r"(?m)^2\. 交付阶段", md), md
    assert "```python\n" + COPY_CODE + "\n```" in md, md
    assert "| 名称 | 状态 |" in md and "| --- | --- |" in md, md
    assert "ready \\| blocked" in md and "跨列说明" in md, md
    for text in ("### 补充一：额外约束", "第一处补充的完整正文。", "隐藏补充",
                 "关闭的 details 仍包含 `hidden_value`。", "嵌套细节", "第二层折叠正文。",
                 "### 补充二：完整性", "第二处补充也必须包含。"):
        assert text in md, (text, md)
    assert md.count("$x_i$") == 1 and md.count("$$\na+b\n$$") == 1, md
    for noise in ("MATHML_DUPLICATE", "VISUAL_DUPLICATE", "复制 TeX", "复制为 Markdown",
                  "上一站", "下一站", "本站", "不得包含的相邻节点正文"):
        assert noise not in md, (noise, md)


def _copy_pack_content() -> str:
    steps = []
    for index, status in ((1, "waiting"), (2, "ready")):
        steps.append(f"""
          <li data-title="原始步骤{index}">
            <p class="lp-timeline-event">唯一事件{index}。</p>
            <p class="lp-timeline-dependency">唯一依赖{index}。</p>
            <ul class="lp-timeline-state">
              <li data-actor="producer" data-slot="buffer" data-status="{status}">
                <b class="lp-timeline-owner">生产者</b><span class="lp-timeline-slot">源缓存</span>
                <p class="lp-timeline-value">源值{index}</p><p class="lp-timeline-signal">源信号{index}</p>
              </li>
              <li data-actor="consumer" data-slot="buffer" data-status="{status}">
                <b class="lp-timeline-owner">消费者</b><span class="lp-timeline-slot">目的缓存</span>
                <p class="lp-timeline-value">目的值{index}</p><p class="lp-timeline-signal">目的信号{index}</p>
              </li>
            </ul>
          </li>""")
    return """
      <figure id="copy-timeline" class="lp-figure lp-stepper lp-timeline" data-timeline-kind="model">
        <figcaption>两步因果示意，不是运行记录。</figcaption><div class="lp-canvas"></div>
        <ol class="lp-steps">""" + "".join(steps) + """</ol>
      </figure>
      <figure id="copy-source" class="lp-figure lp-source-tree">
        <figcaption>示例源码的静态原文。</figcaption>
        <section class="lp-source-repo" id="copy-repo" data-start="copy-file-a">
          <h4>示例仓库</h4><p class="lp-source-version">固定版本 abc123</p>
          <p class="lp-source-about">展示两个互相独立的源码入口。</p>
          <ul class="lp-source-outline"><li id="copy-dir" data-kind="dir" data-path="src/">
            <b>src</b><p>唯一目录说明。</p><ul>
              <li id="copy-file-a" data-kind="file" data-path="src/first.py" data-main="true">
                <b>first.py</b><p>唯一首文件说明。</p>
                <ul class="lp-source-links"><li><a href="https://example.test/src/first.py#L1">首文件原文</a></li></ul>
              </li>
              <li id="copy-file-b" data-kind="file" data-path="src/second.py">
                <b>second.py</b><p>唯一第二文件说明。</p>
                <ul class="lp-source-links"><li><a href="https://example.test/src/second.py#L8">第二文件原文</a></li></ul>
              </li>
            </ul>
          </li></ul>
        </section>
      </figure>
    """


def test_node_markdown_snapshots_real_pack_source_before_runtime_controls(browser, tmp_path):
    page = _page(tmp_path, _copy_content(_copy_pack_content()), packs=("timeline", "source-tree"))
    result = browser(_start(page) + """
      await page.locator('#copy-timeline.is-timeline-ready').waitFor();
      await page.locator('#copy-source.is-ready .lp-st-workspace').waitFor();
      const before=await page.evaluate(()=>LessonPage.nodeMarkdown('node-copy'));
      await page.evaluate(()=>LessonPage.onStep['copy-timeline'](2));
      await page.locator('#copy-source [data-source-node="copy-file-b"]').click();
      return {before, after:await page.evaluate(()=>LessonPage.nodeMarkdown('node-copy')),
        rendered:await page.locator('#copy-timeline .lp-timeline-current').textContent(),
        selection:await page.locator('#copy-source .lp-st-title').textContent()};
    }""")
    assert "原始步骤2" in result["rendered"] and result["selection"] == "second.py"
    md = result["before"]
    assert result["after"] == md
    for index in (1, 2):
        for fragment in (f"原始步骤{index}", f"唯一事件{index}。", f"唯一依赖{index}。", f"源值{index}", f"目的值{index}"):
            assert md.count(fragment) == 1, (fragment, md)
    for fragment in ("唯一目录说明。", "唯一首文件说明。", "唯一第二文件说明。"):
        assert md.count(fragment) == 1, (fragment, md)
    for label, url in (("首文件原文", "https://example.test/src/first.py#L1"),
                       ("第二文件原文", "https://example.test/src/second.py#L8")):
        assert f"[{label}]({url})" in md or f"[{label}](<{url}>)" in md, md
    for noise in ("定位主线", "查看所选路径说明", "文件目录", "依赖与等待",
                  "信号／条件：", "第 1 / 2 步", "第 2 / 2 步", "上一站", "下一站", "复制为 Markdown"):
        assert noise not in md, (noise, md)


def test_node_copy_keyboard_and_review_mode_write_complete_markdown(browser, tmp_path):
    page = _page(tmp_path, _copy_content())
    result = browser(_start(page) + """
      await page.context().grantPermissions(['clipboard-read','clipboard-write']);
      await page.bringToFront();
      const button=page.locator('#node-copy .lp-node-copy');
      await button.focus(); await page.keyboard.press('Enter');
      await page.waitForFunction(()=>document.querySelector('#node-copy .lp-node-copy-status').textContent.includes('已复制'));
      const firstFocused=await button.evaluate(el=>document.activeElement===el);
      const first=await page.evaluate(()=>navigator.clipboard.readText());
      await page.locator('[data-lp-review]').click();
      await page.evaluate(()=>document.querySelector('#node-copy .lp-node-copy-status').textContent='');
      const hidden=await page.locator('#copy-body').isHidden();
      await button.focus(); await page.keyboard.press('Space');
      await page.waitForFunction(()=>document.querySelector('#node-copy .lp-node-copy-status').textContent.includes('已复制'));
      return {first, second:await page.evaluate(()=>navigator.clipboard.readText()), hidden,
        expected:await page.evaluate(()=>LessonPage.nodeMarkdown('node-copy')),
        firstFocused, focused:await button.evaluate(el=>document.activeElement===el),
        live:await page.locator('#node-copy .lp-node-copy-status').getAttribute('aria-live')};
    }""")
    assert result["hidden"] and result["firstFocused"] and result["focused"]
    assert result["live"] in ("polite", "assertive")
    assert result["first"] == result["second"] == result["expected"]
    assert "原始正文包含" in result["second"] and "第二层折叠正文。" in result["second"]
    assert "```python\n" + COPY_CODE + "\n```" in result["second"]


def test_node_copy_denied_clipboard_uses_legacy_then_selectable_manual_fallback(browser, tmp_path):
    page = _page(tmp_path, _copy_content())
    result = browser(_start(page) + """
      await page.context().grantPermissions(['clipboard-read','clipboard-write']);
      await page.bringToFront();
      await page.evaluate(()=>{
        window.copyAttempts=[];
        navigator.clipboard.writeText=()=>{copyAttempts.push('modern'); return Promise.reject(new DOMException('Denied in test','NotAllowedError'));};
        const execute=document.execCommand.bind(document);
        document.execCommand=(command,...args)=>{copyAttempts.push(command); return execute(command,...args);};
      });
      const button=page.locator('#node-copy .lp-node-copy');
      await button.scrollIntoViewIfNeeded();
      const before=await page.evaluate(()=>scrollY);
      await button.click();
      await page.waitForFunction(()=>document.querySelector('#node-copy .lp-node-copy-status').textContent.includes('已复制'));
      const legacy=await page.evaluate(async()=>({text:await navigator.clipboard.readText(), attempts:copyAttempts.slice(),
        focus:document.activeElement===document.querySelector('#node-copy .lp-node-copy'),y:scrollY}));
      await page.evaluate(()=>{
        window.copyAttempts=[];
        document.execCommand=command=>{copyAttempts.push(command); return false;};
        document.querySelector('#node-copy .lp-node-copy-status').textContent='';
      });
      await button.focus(); await page.keyboard.press('Enter');
      const dialog=page.locator('dialog.lp-node-copy-dialog[open]');
      await dialog.waitFor();
      const manual=await dialog.locator('textarea').evaluate(el=>({text:el.value,
        selected:el.selectionStart===0 && el.selectionEnd===el.value.length,focused:document.activeElement===el,
        attempts:window.copyAttempts.slice()}));
      await page.keyboard.press('Escape');
      await dialog.waitFor({state:'hidden'});
      const restored=await button.evaluate(el=>document.activeElement===el);
      const after=await page.evaluate(()=>scrollY);
      await button.click(); await dialog.waitFor();
      await dialog.getByRole('button',{name:'关闭',exact:true}).click();
      return {legacy,manual,before,after,restored,
        closedFocused:await button.evaluate(el=>document.activeElement===el),
        expected:await page.evaluate(()=>LessonPage.nodeMarkdown('node-copy'))};
    }""")
    assert result["legacy"]["attempts"] == ["modern", "copy"], result
    assert result["manual"]["attempts"] == ["modern", "copy"], result
    assert result["legacy"]["text"] == result["manual"]["text"] == result["expected"]
    assert result["manual"]["selected"] and result["manual"]["focused"]
    assert result["legacy"]["focus"] and result["restored"] and result["closedFocused"]
    assert abs(result["legacy"]["y"] - result["before"]) < 2
    assert abs(result["after"] - result["before"]) < 2
