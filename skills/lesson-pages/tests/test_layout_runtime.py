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


def _page(tmp_path: Path, content: str, *, scale: bool = False) -> Path:
    source = (ASSETS / "lesson-template.html").read_text(encoding="utf-8")
    values = {"lang": "zh-CN", "id": "layout", "key": uuid.uuid4().hex[:12],
              "title": "布局回归", "title_full": "布局回归", "date": "2026-10-29"}
    source = re.sub(r"\{\{lp:([a-z_]+)\}\}", lambda m: values.get(m[1], ""), source)
    source = source.replace("<!-- lp:content -->", content)
    if scale:
        css = (ASSETS / "packs/scale.css").read_text(encoding="utf-8")
        js = (ASSETS / "packs/scale.js").read_text(encoding="utf-8")
        source = source.replace("</head>", "<style>" + css + "</style></head>")
        source = source.replace('<script id="lp-runtime">', "<script>" + js + '</script><script id="lp-runtime">')
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
