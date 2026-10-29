from __future__ import annotations

import html
import importlib.util
import json
import os
import hashlib
import re
import shutil
import stat
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references"
PAGE = "learning/pages/attn-03.html"
PAGE_ID = "attn-03"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="formulas and code colors are rendered with Node")


def _load_module() -> ModuleType:
    path = ROOT / "scripts" / "lesson_pages.py"
    spec = importlib.util.spec_from_file_location("lesson_pages_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.modules[spec.name] = module
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
    return module


lp = _load_module()


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = lp.main(list(argv))
    output = capsys.readouterr().out
    return code, json.loads(output)


def _fragment(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / "fragments" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _new(capsys, repo: Path, *extra: str) -> tuple[int, dict]:
    return _run(
        capsys,
        "new", "--repo", str(repo), "--page", PAGE, "--id", PAGE_ID,
        "--title", "分块 softmax", "--course", "Attention 算子", "--label", "第 3 课",
        "--date", "2026-10-22", *extra,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "learning" / "pages").mkdir(parents=True)
    return root


@pytest.fixture()
def built(repo: Path, tmp_path: Path, capsys) -> Path:
    if NODE is None:
        pytest.skip("the examples contain TeX, which is rendered with Node")
    opening = str(REFERENCES / "example-opening.html")
    code, result = _new(capsys, repo, "--fragment", opening)
    assert code == 0, result
    segment = str(REFERENCES / "example-segment.html")
    code, result = _run(capsys, "add", "--repo", str(repo), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", segment, "--date", "2026-10-23")
    assert code == 0, result
    return repo / PAGE


def _source(page: Path) -> str:
    return page.read_text(encoding="utf-8")


def _codes(source: str, page: Path | None = None) -> set[str]:
    return {item["code"] for item in lp.check_source(source, page).items}


def _error_codes(source: str, page: Path | None = None) -> set[str]:
    return {item["code"] for item in lp.check_source(source, page).errors}


# ---------------------------------------------------------------- new


def test_new_page_from_template_is_clean(repo: Path, capsys) -> None:
    code, result = _new(capsys, repo)
    assert code == 0
    assert result["check"] == {"ok": True, "errors": [], "warnings": []}
    source = _source(repo / PAGE)
    assert lp.CONTENT_MARKER not in source
    assert source.count(lp.APPEND_MARKER) == 1
    assert re.search(r'data-id="attn-03" data-key="[0-9a-f]{12}" data-rev="1" data-updated="2026-10-22"', source)
    assert "<title>分块 softmax · Attention 算子 · 第 3 课</title>" in source


def test_examples_build_into_a_clean_page(built: Path) -> None:
    source = _source(built)
    report = lp.check_source(source, built)
    assert report.as_dict() == {"ok": True, "errors": [], "warnings": []}
    outline = lp.outline_source(source)
    assert outline["rev"] == "2"
    ids = [block["id"] for block in outline["blocks"]]
    assert ids[:5] == ["intro", "spine", "node-1", "node-2", "q-1"]
    question = next(block for block in outline["blocks"] if block["id"] == "q-1")
    assert question["state"] == "open"
    # Routed template parts land in the glossary and the source list.
    assert re.search(r'<div id="g-m" data-rev="2">', source)
    assert source.index('id="g-m"') > source.index('id="glossary-list"')
    assert source.count("<li data-rev=") == 2


def test_new_never_replaces_a_page(repo: Path, capsys) -> None:
    assert _new(capsys, repo)[0] == 0
    before = _source(repo / PAGE)
    code, result = _new(capsys, repo)
    assert code == 2 and "already exists" in result["error"]
    assert _source(repo / PAGE) == before


def test_new_creates_directories_only_when_asked(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    code, result = _new(capsys, root)
    assert code == 2 and "--make-parents" in result["error"]
    assert not (root / "learning").exists()
    code, result = _new(capsys, root, "--make-parents")
    assert code == 0 and (root / PAGE).is_file()


@pytest.mark.parametrize(
    "page",
    [
        "/abs/page.html",
        "../outside.html",
        "learning/../x.html",
        "learning//x.html",
        "C:/x.html",
        ".git/x.html",
        ".agents/skills/x.html",
        ".claude/x.html",
        ".agent-skills/x.html",
        "learning/pages/page.txt",
    ],
)
def test_pages_stay_inside_safe_repository_paths(repo: Path, capsys, page: str) -> None:
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", page, "--id", "x",
                        "--title", "t", "--make-parents")
    assert code == 2, result


def test_pages_never_go_through_links_or_nested_repositories(repo: Path, tmp_path: Path, capsys) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (repo / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available")
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "linked/x.html", "--id", "x", "--title", "t")
    assert code == 2 and "symbolic link" in result["error"]
    nested = repo / "vendor" / "lib"
    (nested / ".git").mkdir(parents=True)
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "vendor/lib/x.html", "--id", "x", "--title", "t")
    assert code == 2 and "nested repository" in result["error"]


def test_new_rejects_invalid_ids(repo: Path, capsys) -> None:
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", PAGE, "--id", "Attn_03", "--title", "t")
    assert code == 2 and "--id" in result["error"]


# ---------------------------------------------------------------- add


def test_add_requires_the_page_id(built: Path, tmp_path: Path, capsys) -> None:
    fragment = _fragment(tmp_path, "a.html", '<section id="extra"><h2>补充一节</h2><p>正文</p></section>')
    before = _source(built)
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", "other",
                        "--fragment", fragment)
    assert code == 2 and "belongs to 'attn-03'" in result["error"]
    assert _source(built) == before


def test_add_stamps_revision_and_inserts_before_the_marker(built: Path, tmp_path: Path, capsys) -> None:
    fragment = _fragment(tmp_path, "a.html", '<section id="synthesis"><h2>导师串讲</h2><p>沿同一个例子走一遍。</p></section>')
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", fragment, "--date", "2026-10-24")
    assert code == 0, result
    assert result["rev"] == 3 and result["anchors"] == ["#synthesis"]
    source = _source(built)
    assert '<section id="synthesis" data-rev="3">' in source
    assert 'data-rev="3" data-updated="2026-10-24"' in source
    assert source.index('id="synthesis"') < source.index(lp.APPEND_MARKER) < source.index('id="glossary"')


def test_add_into_a_node_and_after_a_block(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    addendum = _fragment(tmp_path, "b.html", '<div class="lp-addendum" id="add-2-1"><h3>补充（回答检查 1 后）</h3><p>差值。</p></div>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", addendum, "--into", "node-2")[0] == 0
    page = lp.Page(_source(built))
    node = page.one("node-2")
    assert node is not None and node.children[-1].attrs["id"] == "add-2-1"
    question = _fragment(tmp_path, "c.html", '<section class="lp-check" id="q-2" data-state="open"><h3>检查 2</h3><p class="lp-ask">新题</p></section>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", question, "--after", "q-1")[0] == 0
    source = _source(built)
    assert source.index('id="q-1"') < source.index('id="q-2"') < source.index(lp.APPEND_MARKER)


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ('<section id="node-1"><h2>重复</h2></section>', "ids already used"),
        ('<p>a</p> stray', "outside its top-level"),
        ('<section id="x"><h2>t</h2><iframe src="a.html"></iframe></section>', "<iframe>"),
        ('<script>alert(1)</script>', "data-lp-hook"),
        ('<script data-lp-hook src="a.js"></script>', "data-lp-hook"),
        ('<style>p{}</style>', "data-lp-style"),
        ('<section id="x"><h2>t</h2><div>never closed</section>', "never closed"),
        ('<template><p>x</p></template>', "data-lp-into"),
        ('<section id="9bad"><h2>t</h2></section>', "must start with a letter"),
        ('', "no elements"),
    ],
)
def test_add_rejects_bad_fragments(built: Path, tmp_path: Path, capsys, fragment: str, message: str) -> None:
    before = _source(built)
    path = _fragment(tmp_path, "bad.html", fragment)
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--fragment", path)
    assert code == 2 and message in result["error"], result
    assert _source(built) == before


def test_add_refuses_a_result_that_would_fail_check(built: Path, tmp_path: Path, capsys) -> None:
    leak = _fragment(
        tmp_path, "leak.html",
        '<section class="lp-check" id="q-9" data-state="open"><h3>检查 9</h3><p class="lp-ask">题</p>'
        '<details class="lp-answer"><summary>参考要点</summary><p>答案</p></details></section>',
    )
    before = _source(built)
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--fragment", leak)
    assert code == 2 and "check.leak" in result["error"]
    assert _source(built) == before


def test_replace_refuses_a_page_that_changed_meanwhile(built: Path) -> None:
    original = built.read_bytes()
    built.write_text(_source(built) + "<!-- learner note -->", encoding="utf-8")
    with pytest.raises(lp.UsageError, match="changed while"):
        lp._replace(built, original, "new text")
    assert "learner note" in _source(built)
    assert not list(built.parent.glob(".*lp-tmp*"))


# ---------------------------------------------------------------- state


def test_question_state_moves_forward_only(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1",
                        "--to", "closed", "--date", "2026-10-24")
    assert code == 0 and result["rev"] == 3
    assert '<section class="lp-check" id="q-1" data-state="closed" data-rev="3">' in _source(built)
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1", "--to", "replaced")
    assert code == 2 and "cannot move" in result["error"]
    answer = _fragment(tmp_path, "answer.html", '<details class="lp-answer"><summary>参考要点</summary><p>交换 m、ℓ 与局部输出。</p></details>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", answer, "--into", "q-1")[0] == 0
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "node-1", "--to", "closed")
    assert code == 2 and "no question block" in result["error"]


# ---------------------------------------------------------------- check rules


def _with(source: str, old: str, new: str) -> str:
    assert old in source, old
    return source.replace(old, new, 1)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("<!doctype html>", "", "page.doctype"),
        ('<html lang="zh-CN">', "<html>", "page.lang"),
        ('<meta charset="utf-8">', "", "page.charset"),
        ('<meta http-equiv="Content-Security-Policy"', '<meta http-equiv="X-Other"', "page.csp"),
        ('<meta name="lesson-pages" content="v1"', '<meta name="other" content="v1"', "page.marker"),
        ('data-rev="2" data-updated', 'data-rev="1" data-updated', "rev.future"),
        (lp.APPEND_MARKER, "", "page.structure"),
        ('<section class="lp-node" id="node-2"', '<section class="lp-node" id="node-1"', "id.duplicate"),
        ("</main>", '<p><a href="#nowhere">x</a></p></main>', "anchor.missing"),
        ("</main>", '<p><a href="missing.html">x</a></p></main>', "link.missing"),
        ("</main>", '<script src="https://cdn.example/x.js"></script></main>', "script.src"),
        ("</head>", '<link rel="stylesheet" href="https://fonts.example/a.css"></head>', "resource.external"),
        ("</main>", '<img alt="x" src="https://img.example/a.png"></main>', "resource.external"),
        ("</main>", '<div style="background:url(https://x.example/a.png)"></div></main>', "resource.external"),
        ("</main>", "<style data-lp-style>@import 'x.css';</style></main>", "resource.external"),
        ("</main>", '<iframe src="x.html"></iframe></main>', "resource.forbidden"),
        ("</main>", '<svg role="img" aria-label="a"><image href="https://img.example/a.png"/></svg></main>', "resource.external"),
        ("</main>", '<style data-lp-style>.x{background:image-set("https://img.example/a.png" 1x)}</style></main>', "resource.external"),
        ("</head>", '<meta http-equiv="refresh" content="0;url=https://x.example"></head>', "page.refresh"),
        ("</main>", '<p><a href="javascript:alert(1)">x</a></p></main>', "link.script"),
        ("</main>", "<script>var a = 1;</script></main>", "script.hook"),
        ("</main>", '<img src="data:image/png;base64,AA=="></main>', "a11y.img-alt"),
        ("</main>", '<svg role="img" viewBox="0 0 10 10"></svg></main>', "a11y.svg-name"),
        ("</main>", '<button type="button"></button></main>', "a11y.button-name"),
        ("</main>", '<input type="range" name="n"></main>', "a11y.control-label"),
        ("</main>", "<p>{{lp:title}}</p></main>", "fill.leftover"),
        ('id="q-1" data-state="open"', 'id="q-1" data-state="pending"', "check.state"),
        ('id="q-1" data-state="open" data-rev="2">', 'id="q-1" data-state="open" data-rev="2"><div>', "html.unclosed"),
        ('<p class="lp-how">', '<details><summary>提示</summary><p>h</p></details><p class="lp-how">', "check.leak"),
        ('<p class="lp-how">', '<button type="button" class="lp-btn">揭晓</button><p class="lp-how">', "check.leak"),
        ('<figure class="lp-figure lp-stepper" id="fig-2-1">', '<figure class="lp-figure lp-stepper" id="fig-2-1" data-reveals="q-1">', "check.reveal"),
        ('<figure class="lp-figure lp-stepper" id="fig-2-1">', '<figure class="lp-figure lp-stepper" id="fig-2-1" data-reveals="q-7">', "check.reveal"),
        ('<p class="lp-lead"><b>结论</b>分块处理一行时', '<p>结论后置</p><p class="lp-lead"><b>结论</b>分块处理一行时', "node.lead"),
        ("</main>", '<svg role="img" aria-label="a" viewBox="0 0 10 10"><rect fill="#333" width="5" height="5"/></svg></main>', "svg.color"),
    ],
)
def test_check_detects_each_rule(built: Path, old: str, new: str, code: str) -> None:
    source = _source(built)
    assert code not in _error_codes(source, built)
    assert code in _error_codes(_with(source, old, new), built)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('<p class="lp-spine">FlashAttention-2 论文第 3.2 节', '<p>FlashAttention-2 论文第 3.2 节', "node.spine"),
        ("</main>", '<figure id="fig-x"><p>no caption</p></figure></main>', "figure.caption"),
        ("</main>", '<figure class="lp-explorer" id="fig-e"><figcaption>x</figcaption></figure></main>', "widget.hook"),
        ("</main>", "<p>看这里 \U0001F600</p></main>", "style.emoji"),
        ("</main>", "<p>" + "很" * 230 + "</p></main>", "text.wall"),
        ("</main>", '<svg role="img" aria-label="a" viewBox="0 0 1200 100"><text font-size="14">x</text></svg></main>', "svg.label-size"),
    ],
)
def test_check_warns_without_failing(built: Path, old: str, new: str, code: str) -> None:
    source = _with(_source(built), old, new)
    report = lp.check_source(source, built)
    assert code in {item["code"] for item in report.as_dict()["warnings"]}
    assert code not in {item["code"] for item in report.errors}


def test_lessons_about_templating_may_show_double_braces(built: Path) -> None:
    source = _with(_source(built), "</main>", "<p><code>{{ user.name }}</code>、<code>{{title}}</code> 与 <code>println!(\"{{}}\")</code></p></main>")
    assert "fill.leftover" not in _error_codes(source, built)


def test_new_without_breadcrumb_omits_it(repo: Path, capsys) -> None:
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", PAGE, "--id", PAGE_ID, "--title", "只有标题",
                        "--source", "资料 A", "--date", "2026-10-22")
    assert code == 0 and result["check"]["ok"], result
    source = _source(repo / PAGE)
    assert 'class="lp-crumb"' not in source and "<title>只有标题</title>" in source
    assert "<li>资料 A</li>" in source


def test_check_reports_runtime_drift(built: Path) -> None:
    source = _source(built)
    drifted = _with(source, '"use strict";', '"use strict"; window.drift = 1;')
    assert "runtime.drift" in _codes(drifted, built)


def test_closed_question_may_hold_reference_points_and_reveals(built: Path) -> None:
    source = _with(_source(built), 'id="q-1" data-state="open"', 'id="q-1" data-state="closed"')
    source = _with(source, '<p class="lp-how">', '<details class="lp-answer"><summary>参考要点</summary><p>a</p></details><p class="lp-how">')
    source = _with(source, '<figure class="lp-figure lp-stepper" id="fig-2-1">', '<figure class="lp-figure lp-stepper" id="fig-2-1" data-reveals="q-1">')
    assert lp.check_source(source, built).errors == []


def test_check_command_verifies_cited_anchors(built: Path, capsys) -> None:
    repo = str(built.parents[2])
    code, result = _run(capsys, "check", "--repo", repo, "--page", PAGE, "--anchor", "q-1")
    assert code == 0 and result["ok"]
    assert result["scripts"]["status"] in {"checked", "skipped"}
    code, result = _run(capsys, "check", "--repo", repo, "--page", PAGE, "--anchor", "#q-9")
    assert code == 1 and result["errors"][0]["code"] == "anchor.cited"


def test_inline_script_syntax_is_checked_when_node_exists(built: Path) -> None:
    broken = _with(_source(built), "</main>", "<script data-lp-hook>function (</script></main>")
    result = lp.check_scripts(broken)
    if result["status"] == "skipped":
        pytest.skip("node is not installed")
    assert any(item["code"] == "script.syntax" for item in result["errors"])
    assert lp.check_scripts(_source(built))["errors"] == []


# ---------------------------------------------------------------- outline, find, serve


def test_outline_reports_blocks_without_reading_the_page(built: Path, capsys) -> None:
    code, result = _run(capsys, "outline", "--repo", str(built.parents[2]), "--page", PAGE)
    assert code == 0
    assert result["id"] == PAGE_ID and result["rev"] == "2"
    node = next(block for block in result["blocks"] if block["id"] == "node-2")
    assert node["kind"] == "node" and node["title"] == "2 在线 softmax 为什么要保留两个统计量"
    assert {"id": "fig-2-1"} in node["figures"]
    question = next(block for block in result["blocks"] if block["id"] == "q-1")
    assert question["title"] == "检查 1 · 迁移" and question["has_reference_points"] is False
    assert [code["tag"] for code in result["page_code"]] == ["style", "script"]
    start, end = node["lines"]
    assert 'id="node-2"' in _source(built).splitlines()[start - 1] and end > start


def test_find_lists_marker_pages_only_inside_given_collections(built: Path, capsys) -> None:
    repo = built.parents[2]
    (repo / "learning" / "pages" / "plain.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (repo / "elsewhere").mkdir()
    (repo / "elsewhere" / "copy.html").write_bytes(built.read_bytes())
    code, result = _run(capsys, "find", "--repo", str(repo), "--in", "learning/pages")
    assert code == 0
    assert [page["page"] for page in result["pages"]] == [PAGE]
    assert result["pages"][0]["id"] == PAGE_ID and result["pages"][0]["rev"] == 2
    code, result = _run(capsys, "find", "--repo", str(repo), "--in", "learning/pages", "--id", "nope")
    assert result["pages"] == []


def test_serve_exposes_only_the_collection(built: Path) -> None:
    collection = built.parent
    (collection / ".hidden.html").write_text("secret", encoding="utf-8")
    (collection.parent / "private.md").write_text("secret", encoding="utf-8")
    server = lp.make_server(collection, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/attn-03.html") as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert b'name="lesson-pages"' in response.read()
        with urllib.request.urlopen(f"{base}/__lp/rev/attn-03.html") as response:
            assert json.load(response) == {"rev": 2}
        with urllib.request.urlopen(f"{base}/attn-03.html?lp-rev") as response:
            assert json.load(response) == {"rev": 2}
        for path in ("/.hidden.html", "/../private.md", "/%2e%2e/private.md", "/__lp/rev/../private.md"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code == 404, path
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- template


def test_template_keeps_its_slots_and_offline_policy() -> None:
    template = (ROOT / "assets" / "lesson-template.html").read_text(encoding="utf-8")
    for slot in lp.TEMPLATE_SLOTS:
        assert slot in template, slot
    assert template.count(lp.CONTENT_MARKER) == 1 and template.count(lp.APPEND_MARKER) == 1
    assert f'content="{lp.CSP}"' in template
    for element_id in ("lp-boot", "lp-base", "lp-page-style", "lp-runtime", "glossary-list", "sources-list"):
        assert f'id="{element_id}"' in template
    assert "prefers-reduced-motion" in template and "prefers-color-scheme: dark" in template
    assert not re.search(r"https?://", template)
    assert "\r\n" not in template


# ---------------------------------------------------------------- hardening


@pytest.mark.parametrize(
    ("addition", "code"),
    [
        ('<div class="lp-row"/><p>后面的文字</p>', "html.self-closing"),
        ('<p class="a" class="b">x</p>', "html.duplicate-attr"),
        ("<!--><p>x</p><!-- -->", "html.comment"),
        ('<img alt="x" src="data:image/png;base64,AA==" srcset="data:image/png;base64,AA== 1x, https://e.example/a.png 2x">', "resource.external"),
        ('<img alt="x" src="\\\\e.example/a.png">', "resource.external"),
        ('<p><a href="java&#x09;script:alert(1)">x</a></p>', "link.script"),
        ('<svg role="img" aria-label="a"><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>', "link.script"),
        ('<svg role="img" aria-label="a"><script data-lp-hook href="https://e.example/x.js"></script></svg>', "script.src"),
        ('<style data-lp-style>@import url(local.css);</style>', "resource.external"),
        ('<svg role="img" aria-label="a" viewBox="0 0 10 10"><rect fill="black" width="5" height="5"/></svg>', "svg.color"),
    ],
)
def test_check_catches_browser_behaviour_the_simple_model_missed(built: Path, addition: str, code: str) -> None:
    assert code in _error_codes(_with(_source(built), "</main>", addition + "</main>"), built)


@pytest.mark.parametrize(
    "addition",
    [
        '<svg role="img" aria-label="a" viewBox="0 0 10 10"><defs><linearGradient id="fade"/></defs><rect fill="url(#fade)" width="5" height="5"/><circle r="1"/></svg>',
        '<span id="lbl">下一步</span><button type="button" aria-labelledby="lbl"></button>',
        '<label>n <input type="button" value="下一步"></label><input type="button" value="重来">',
        '<input type="HIDDEN" name="a" value="1">',
        '<p><a href="#node%2D1">x</a></p>',
    ],
)
def test_check_accepts_legitimate_markup(built: Path, addition: str) -> None:
    assert lp.check_source(_with(_source(built), "</main>", addition + "</main>"), built).errors == []


def test_percent_encoded_local_files_resolve(built: Path) -> None:
    (built.parent / "my image.png").write_bytes(b"x")
    source = _with(_source(built), "</main>", '<img alt="x" src="my%20image.png"></main>')
    assert "resource.missing" not in _error_codes(source, built)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<p class="lp-how">', '<p class="lp-hint">提示：看 IB 带宽</p><p class="lp-how">'),
        ('<p class="lp-how">', '<div>多余的说明</div><p class="lp-how">'),
    ],
)
def test_open_questions_hold_only_the_question(built: Path, old: str, new: str) -> None:
    assert "check.leak" in _error_codes(_with(_source(built), old, new), built)


def test_open_question_may_carry_code_and_a_timer(built: Path) -> None:
    source = _with(_source(built), '<p class="lp-how">', '<pre class="lp-code"><code>let b = a;</code></pre><div class="lp-timer" data-seconds="90"></div><p class="lp-how">')
    assert lp.check_source(source, built).errors == []


def test_nothing_interactive_sits_right_after_an_open_question(built: Path, tmp_path: Path, capsys) -> None:
    hint = _fragment(tmp_path, "hint.html", '<details id="hint"><summary>提示</summary><p>看 m 和 ℓ</p></details>')
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", hint, "--after", "q-1")
    assert code == 2 and "check.leak" in result["error"]


def test_style_and_formula_width_warnings(built: Path) -> None:
    source = _with(_source(built), "</main>", '<style data-lp-style>.x { color: #333; }</style><pre class="lp-formula">' + "x" * 60 + "</pre></main>")
    warnings = {item["code"] for item in lp.check_source(source, built).as_dict()["warnings"]}
    assert {"style.color", "text.wide-formula"} <= warnings


@pytest.mark.parametrize("page", [".GIT/x.html", ".git./x.html", ".Claude/x.html", "learning/CON.html", "learning/x.html:ads.html", "learning/a?.html"])
def test_paths_are_safe_on_case_insensitive_and_windows_filesystems(repo: Path, capsys, page: str) -> None:
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", page, "--id", "x", "--title", "t", "--make-parents")
    assert code == 2, result


def test_fragments_with_stray_or_self_closed_tags_are_refused(built: Path, tmp_path: Path, capsys) -> None:
    for name, text in (
        ("stray.html", '<template data-lp-into="glossary-list"><div id="g-q"><dt>q</dt><dd>d</dd></div></dl></section></template>'),
        ("self.html", '<section id="x"><h2>t</h2><div class="lp-row"/><p>后文</p></section>'),
    ):
        before = _source(built)
        code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                            "--fragment", _fragment(tmp_path, name, text))
        assert code == 2, result
        assert _source(built) == before


def test_state_can_close_and_attach_reference_points_in_one_revision(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    answer = _fragment(tmp_path, "answer.html", '<details class="lp-answer"><summary>参考要点</summary><p>交换 m、ℓ 与局部输出。</p></details>')
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1",
                        "--to", "closed", "--fragment", answer)
    assert code == 0 and result["rev"] == 3, result
    question = lp.Page(_source(built)).one("q-1")
    assert question is not None and question.attrs["data-state"] == "closed"
    assert any("lp-answer" in node.classes and node.attrs.get("data-rev") == "3" for node in question.iter())
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1",
                        "--to", "replaced", "--fragment", answer)
    assert code == 2


def test_insertion_keeps_fragment_order_and_rejects_meaningless_flags(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    both = _fragment(tmp_path, "both.html", '<div id="g-a"><dt>a</dt><dd>main</dd></div><template data-lp-into="glossary-list"><div id="g-b"><dt>b</dt><dd>routed</dd></div></template>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", both, "--into", "glossary-list")[0] == 0
    text = _source(built)
    assert text.index('id="g-a"') < text.index('id="g-b"')
    routed = _fragment(tmp_path, "routed.html", '<template data-lp-into="glossary-list"><div id="g-c"><dt>c</dt><dd>c</dd></div></template>')
    code, result = _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", routed, "--into", "nowhere")
    assert code == 2 and "only routed parts" in result["error"]


def test_crlf_pages_and_file_modes_survive_updates(built: Path, tmp_path: Path, capsys) -> None:
    built.write_bytes(built.read_bytes().replace(b"\n", b"\r\n"))
    os.chmod(built, 0o664)
    assert "runtime.drift" not in _codes(built.read_bytes().decode("utf-8"), built)
    fragment = _fragment(tmp_path, "a.html", '<div class="lp-addendum" id="add-2-1">\n<h3>补充</h3>\n<p>差值。</p>\n</div>')
    assert _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--fragment", fragment, "--into", "node-2")[0] == 0
    data = built.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    assert stat.S_IMODE(built.stat().st_mode) == 0o664


def test_unexpected_revision_text_is_reported_not_crashed(built: Path, capsys) -> None:
    source = _with(_source(built), 'data-state="open" data-rev="2"', 'data-state="open" data-rev="²"')
    assert "rev.future" in _error_codes(source, built)
    built.write_text(_with(_source(built), 'data-rev="2" data-updated', 'data-rev="²" data-updated'), encoding="utf-8")
    code, result = _run(capsys, "outline", "--repo", str(built.parents[2]), "--page", PAGE)
    assert code == 0 and result["rev"] == "²"
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--fragment", str(REFERENCES / "example-opening.html"))
    assert code == 2 and "data-rev" in result["error"]


def test_scripts_are_parsed_as_classic_browser_scripts(built: Path, tmp_path: Path, capsys) -> None:
    broken = _with(_source(built), "</main>", "<script data-lp-hook>if (!window.LessonPage) return;</script></main>")
    result = lp.check_scripts(broken)
    if result["status"] == "skipped":
        pytest.skip("node is not installed")
    assert result["errors"] and result["errors"][0]["code"] == "script.syntax"
    fragment = _fragment(tmp_path, "bad-js.html", '<script data-lp-hook>LessonPage.explorers["x"] = function (</script>')
    before = _source(built)
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--fragment", fragment)
    assert code == 2 and "script.syntax" in result["error"]
    assert _source(built) == before


def test_find_reads_any_marker_quoting_and_skips_hidden_files(built: Path, capsys) -> None:
    repo = built.parents[2]
    single = built.parent / "single.html"
    single.write_text(_source(built).replace('<meta name="lesson-pages" content="v1" data-id="attn-03"', "<meta name='lesson-pages' content='v1' data-id='single'"), encoding="utf-8")
    (built.parent / ".draft.html").write_bytes(built.read_bytes())
    code, result = _run(capsys, "find", "--repo", str(repo), "--in", "learning/pages")
    assert code == 0
    assert [page["page"] for page in result["pages"]] == [PAGE, "learning/pages/single.html"]


def test_serve_checks_the_host_and_lists_only_pages(built: Path) -> None:
    collection = built.parent
    (collection / "notes.md").write_text("private", encoding="utf-8")
    server = lp.make_server(collection, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            listing = response.read().decode("utf-8")
        assert "attn-03.html" in listing and "notes.md" not in listing
        request = urllib.request.Request(base + "/attn-03.html", headers={"Host": "attacker.example"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_attribute_edits_never_touch_quoted_values(built: Path, capsys) -> None:
    source = _with(_source(built), 'id="q-1" data-state="open"', 'id="q-1" title="草稿 data-state=open" data-state="open"')
    built.write_text(source, encoding="utf-8")
    code, result = _run(capsys, "state", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--question", "q-1", "--to", "closed")
    assert code == 0, result
    question = lp.Page(_source(built)).one("q-1")
    assert question is not None
    assert question.attrs["data-state"] == "closed" and question.attrs["title"] == "草稿 data-state=open"


def test_oral_questions_with_timers_can_be_replaced(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    oral = _fragment(tmp_path, "oral.html", '<section class="lp-check" id="q-2" data-state="open"><h3>检查 2<span class="lp-kind">口述</span></h3><p class="lp-ask">用 90 秒讲清分块的代价。</p><ul><li>听众：面试官</li></ul><div class="lp-timer" data-seconds="90"></div></section>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", oral)[0] == 0
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-2", "--to", "replaced")
    assert code == 0, result


def test_highlight_ranges_use_source_line_numbers(built: Path) -> None:
    good = _with(_source(built), "</main>", '<pre class="lp-code" data-start="120" data-highlight="121-122"><code>\na\nb\nc</code></pre></main>')
    bad = _with(_source(built), "</main>", '<pre class="lp-code" data-start="120" data-highlight="2-3"><code>a\nb\nc</code></pre></main>')
    assert "code.highlight-range" not in _codes(good, built)
    assert "code.highlight-range" in _codes(bad, built)


def test_managed_context_limits_where_pages_are_written(repo: Path, capsys, monkeypatch) -> None:
    context = repo.parent / "context.json"
    context.write_text(json.dumps({
        "version": 1, "manager": "agent-skills", "repository_id": "r", "skill": "lesson-pages",
        "context": {"page_targets": [{"id": "pages", "collection": "learning/pages", "format": "html", "include_patterns": ["*.html"]}]},
        "allowlist": {"tracked_files": [], "tracked_collections": [], "write_paths": ["learning/pages"]},
    }), encoding="utf-8")
    monkeypatch.setattr(lp, "CONTEXT_FILE", context)
    (repo / "elsewhere").mkdir()
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "elsewhere/x.html", "--id", "x", "--title", "t")
    assert code == 2 and "page_targets" in result["error"]
    assert _new(capsys, repo)[0] == 0
    context.write_text("{not json", encoding="utf-8")
    code, result = _run(capsys, "add", "--repo", str(repo), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", str(REFERENCES / "example-opening.html"))
    assert code == 2 and "re-materialize" in result["error"]


def test_answered_questions_keep_the_open_rules_until_closed(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1", "--to", "answered")
    assert code == 0 and result["state"] == "answered"
    answer = _fragment(tmp_path, "answer.html", '<details class="lp-answer"><summary>参考要点</summary><p>交换 m、ℓ。</p></details>')
    code, result = _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", answer, "--into", "q-1")
    assert code == 2 and "check.leak" in result["error"]
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1",
                        "--to", "closed", "--fragment", answer)
    assert code == 0, result
    code, result = _run(capsys, "state", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--question", "q-1", "--to", "answered")
    assert code == 2 and "cannot move" in result["error"]


def test_wrapped_collapsibles_cannot_follow_an_open_question(built: Path) -> None:
    source = _source(built)
    wrapped = '<div class="lp-addendum" id="add-x"><h3>补充</h3><details><summary>展开</summary><p>答案</p></details></div>'
    page = lp.Page(source)
    question = page.one("q-1")
    assert question is not None and question.end is not None
    leaked = source[:question.end] + wrapped + source[question.end:]
    assert "check.leak" in _error_codes(leaked, built)


def test_outline_lists_page_code_anywhere_and_serve_lists_marker_pages(built: Path, tmp_path: Path, capsys) -> None:
    repo = str(built.parents[2])
    fragment = _fragment(tmp_path, "styled.html", '<div class="lp-addendum" id="add-2-1"><h3>补充</h3><p>差值。</p></div><style data-lp-style>.aa { color: var(--ink); }</style>')
    assert _run(capsys, "add", "--repo", repo, "--page", PAGE, "--id", PAGE_ID, "--fragment", fragment, "--into", "node-2")[0] == 0
    outline = lp.outline_source(_source(built))
    assert {"tag": "style", "inside": "node-2"} in [{key: code[key] for key in ("tag", "inside") if key in code} for code in outline["page_code"]]
    (built.parent / "handmade.html").write_text("<!doctype html><title>手工图解</title>", encoding="utf-8")
    server = lp.make_server(built.parent, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/") as response:
            listing = response.read().decode("utf-8")
        assert "attn-03.html" in listing and "handmade.html" not in listing
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- formulas and code

VENDORED = {
    "highlight/highlight.min.js": "8ab71eb09c51f501e5e25157d9cff100e46cc29bcbfc744d0b746d451fca7f53",
    "highlight/LICENSE": "6c081431591d9df696c82dc598fe1423765b8a299b200ed00b281afd0f64c490",
    "katex/fonts/OFL.txt": "9479e56acc2c5f503fc875749d5be6c444ae3aec11a54f6d076b95e267a432b8",
    "katex/fonts/KaTeX_AMS-Regular.woff2": "0cdd387c9590a1a9f9794560022dbb59654a7d86f187aa0c81495ad42d3a7308",
    "katex/fonts/KaTeX_Caligraphic-Bold.woff2": "de7701e42cf1f4cf0b766c03fb27977207eee2f4fd5d76fa82188406da43ea4c",
    "katex/fonts/KaTeX_Caligraphic-Regular.woff2": "5d53e70ad607c2352162dec9e0923fb54ecdafaccbf604cd8dcf7d00facb989b",
    "katex/fonts/KaTeX_Fraktur-Bold.woff2": "74444efd593c005e3f4573b44524704c0af0a937fe911cca9e94068d0d140d3f",
    "katex/fonts/KaTeX_Fraktur-Regular.woff2": "51814d270d06ff0255dba0799994fa4d8c84d11f09951d47595f4abb1f3602dc",
    "katex/fonts/KaTeX_Main-BoldItalic.woff2": "99cd42a3c072d918f2f44984a807cf7aa16e13545fd0875fc07c6c65f99e715b",
    "katex/fonts/KaTeX_Main-Bold.woff2": "0f60d1b897938ec918c8ce073092411baf9438f6739465693ff18b0f9d20b021",
    "katex/fonts/KaTeX_Main-Italic.woff2": "97479ca6cce906abc961ecac96faa5f9ca2e61b8e7670d475826bcdee9a7c267",
    "katex/fonts/KaTeX_Main-Regular.woff2": "c2342cd8b869e01752a9321dc17213fc40d4d04c79688c1d43f2cf316abd7866",
    "katex/fonts/KaTeX_Math-BoldItalic.woff2": "dc47344dbb6cb5b655c8460d561f4df5f501b90c804ad3c6cec65fe322351ab1",
    "katex/fonts/KaTeX_Math-Italic.woff2": "7af58c5ec8f132a2ddde9027c6d7814decce4d3b822a11192a42a20e2e973264",
    "katex/fonts/KaTeX_SansSerif-Bold.woff2": "e99ae51144bf1232efcc1bfe5add36262c6866b0faab24fa75740e1b98577a62",
    "katex/fonts/KaTeX_SansSerif-Italic.woff2": "00b26ac825e2095056396e0553b8ac26d3f8ad158c3826e28b4c45b385c4714a",
    "katex/fonts/KaTeX_SansSerif-Regular.woff2": "68e8c73ef42afd3ccec58bf0fba302cce448938e7fc020a5e31f8a952eee1342",
    "katex/fonts/KaTeX_Script-Regular.woff2": "036d4e95149b69ff9bcc0cd55771efeb25ffa3947293e69acd78d5ac328c684b",
    "katex/fonts/KaTeX_Size1-Regular.woff2": "6b47c40166b6dbe21a5dfca7718413f2147fd2399be1ba605d8ad39cedf25dfe",
    "katex/fonts/KaTeX_Size2-Regular.woff2": "d04c54219f9eaec6d4d4fd42dfb28785975a4794d6b2fc71e566b9cd6db842dd",
    "katex/fonts/KaTeX_Size3-Regular.woff2": "73d591271b1604960cb10bb90fee021670af7297017e0e98480b332d11f51995",
    "katex/fonts/KaTeX_Size4-Regular.woff2": "a4af7d414440a1c1790825cfb700cf9cf43b0f2c4b04f0ebc523011ad9853ec0",
    "katex/fonts/KaTeX_Typewriter-Regular.woff2": "71d517d67827787cfabdf186914cc3358eda539e37931941f2b2fd4a21f68c0b",
    "katex/katex.min.css": "d4ab5b8ee16989b070cdb0ea24bd6ad48fc8df1b787f280f29d3ae4f959f2c00",
    "katex/katex.min.js": "103a53763cc033bba8d175bf3f0ba597c3505c9b6747dd3f2c7bc2a6bfcc8ae7",
    "katex/LICENSE": "766ccc1f306c885aa45542a9846bbd0a505b27a0374f146778171c2254ce18e3",
}

FORMULA_SEGMENT = """<section class="lp-node" id="node-9" data-stages="st-online">
  <h2><span class="lp-no">9</span>公式与代码</h2>
  <p class="lp-spine">FlashAttention-2 论文第 3.1 节</p>
  <p class="lp-lead"><b>结论</b>行内 <span class="tex">\\sA{m} &lt; x</span>。</p>
  <div class="tex">\\sB{\\ell} = \\sum_j e^{x_j}</div>
  <pre class="lp-code" data-lang="python" data-symbols="m=1 l=2"><code>def f(m, l):
    s = "m"  # m stays plain in strings and comments
    return m &lt; l</code></pre>
  <ol class="lp-code-notes"><li data-lines="3">比较。</li></ol>
</section>
"""


def _add(capsys, built: Path, tmp_path: Path, text: str, *extra: str) -> tuple[int, dict]:
    fragment = _fragment(tmp_path, "segment.html", text)
    return _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                "--fragment", fragment, "--date", "2026-10-24", *extra)


def test_vendored_libraries_match_their_recorded_hashes() -> None:
    vendor = ROOT / "assets" / "vendor"
    found = {path.relative_to(vendor).as_posix() for path in vendor.rglob("*") if path.is_file()}
    assert found == set(VENDORED)
    for name, digest in VENDORED.items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name


@needs_node
def test_tex_and_code_are_rendered_once_when_written(built: Path, tmp_path: Path, capsys) -> None:
    code, result = _add(capsys, built, tmp_path, FORMULA_SEGMENT)
    assert code == 0, result
    assert result["rendered"] == {"tex": 2, "code": 1}
    assert result["check"]["warnings"] == []
    source = _source(built)
    assert source.count('<style id="lp-katex">') == 1
    assert 'data-tex="\\sA{m} &lt; x"' in source and 'class="enclosing lp-s1"' in source
    assert '<span class="hljs-keyword">def</span>' in source
    assert '<var class="lp-s1">m</var> &lt; <var class="lp-s2">l</var>' in source
    assert '<span class="hljs-string">&quot;m&quot;</span>' in source
    assert "# m stays plain" in source
    fonts = re.search(r"fonts: ([^*]+)\*/", source).group(1).split()
    assert "KaTeX_Main-Regular" in fonts and "KaTeX_Math-Italic" in fonts and "KaTeX_AMS-Regular" not in fonts
    assert source.count("@font-face") == len(fonts)
    # More formulas only add the fonts they need; the block stays single.
    more = '<p id="extra-1"><span class="tex">\\mathbb{R}^{N}</span></p>'
    code, result = _add(capsys, built, tmp_path, more, "--into", "node-9")
    assert code == 0, result
    source = _source(built)
    assert source.count('<style id="lp-katex">') == 1 and "KaTeX_AMS-Regular" in re.search(r"fonts: ([^*]+)\*/", source).group(1)


@needs_node
def test_reading_time_ignores_the_mathml_copy(built: Path, tmp_path: Path, capsys) -> None:
    formulas = "".join(f'<div class="tex">\\sum_{{j=1}}^{{N}} e^{{x_j - m}} \\cdot v_j + {i}</div>' for i in range(40))
    code, result = _add(capsys, built, tmp_path, f'<div class="lp-addendum" id="add-9-1"><h3>补充</h3>{formulas}</div>', "--into", "node-2")
    assert code == 0, result
    assert result["reading_minutes"] <= 2


@needs_node
@pytest.mark.parametrize("tex", [
    "\\href{https://example.com}{x}",
    "\\textcolor{red}{x}",
    "\\htmlId{a}{b}",
    "\\htmlStyle{color: red}{b}",
    "\\htmlClass{tex}{x}",
    "\\phantom{\\href{https://example.com}{x}}",
    "\\step{2,3}{x}",
    "\\frac{1",
])
def test_tex_refuses_parse_errors_links_and_fixed_colors(built: Path, tmp_path: Path, capsys, tex: str) -> None:
    before = built.read_bytes()
    code, result = _add(capsys, built, tmp_path, f'<p id="t-1"><span class="tex">{tex}</span></p>', "--into", "node-2")
    assert code == 2 and "could not render" in result["error"]
    assert built.read_bytes() == before


@needs_node
def test_step_macro_marks_formula_parts_for_steppers(built: Path, tmp_path: Path, capsys) -> None:
    fragment = """<figure class="lp-figure lp-stepper" id="fig-9-1"><div class="tex">a \\step{2-3}{+ b}</div>
<ol class="lp-steps"><li>一</li><li>二</li><li>三</li></ol><figcaption><b>图 9.1</b>公式随步骤出现。</figcaption></figure>"""
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0, result
    assert 'data-show="2-3"' in _source(built)


@needs_node
@pytest.mark.parametrize("fragment, message", [
    ('<pre class="lp-code" data-lang="fortran"><code>x = 1</code></pre>', "does not know"),
    ('<pre class="lp-code" data-lang="python" data-symbols="m=5"><code>m</code></pre>', "data-symbols"),
    ('<p id="t-2"><span class="tex"><b>x</b></span></p>', "plain TeX"),
    ('<p id="t-3"><span class="tex">  </span></p>', "empty"),
])
def test_render_inputs_are_validated(built: Path, tmp_path: Path, capsys, fragment: str, message: str) -> None:
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 2 and message in result["error"]


def test_without_node_tex_fails_clearly_and_code_stays_plain(repo: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(lp.shutil, "which", lambda name: None)
    tex = _fragment(tmp_path, "tex.html", '<section class="lp-narrative" id="intro"><h2>导入</h2><p><span class="tex">x</span></p></section>')
    code, result = _new(capsys, repo, "--fragment", tex)
    assert code == 2 and "Node.js" in result["error"]
    assert not (repo / PAGE).exists()
    plain = _fragment(tmp_path, "code.html", '<section class="lp-narrative" id="intro"><h2>导入</h2>'
                      '<pre class="lp-code" data-lang="python"><code>x = 1</code></pre></section>')
    code, result = _new(capsys, repo, "--fragment", plain)
    assert code == 0, result
    assert "node not found" in result["rendered"]["note"]
    assert '<code>x = 1</code>' in _source(repo / PAGE)


@needs_node
def test_check_flags_unrendered_tex_and_missing_formula_styles(built: Path, tmp_path: Path, capsys) -> None:
    source = _source(built)
    assert "math.unrendered" in _error_codes(_with(source, "<p class=\"lp-lead\"><b>结论</b>", "<p class=\"lp-lead\"><b>结论</b><span class=\"tex\">x</span>"))
    without = re.sub(r'<style id="lp-katex">.*?</style>\n', "", source, flags=re.S)
    assert "math.css" in _error_codes(without)
    fewer = re.sub(r"(fonts: [^*]*?)KaTeX_Math-Italic ?", r"\1", source)
    assert {"math.font", "runtime.drift"} <= _codes(fewer)
    edited = source.replace('<style id="lp-katex">\n', '<style id="lp-katex">\n.katex { color: inherit; }\n', 1)
    assert "runtime.drift" in _codes(edited)


@needs_node
def test_render_command_renders_hand_edited_tex(built: Path, capsys) -> None:
    source = _source(built)
    built.write_text(source.replace("<p class=\"lp-lead\"><b>结论</b>", "<p class=\"lp-lead\"><b>结论</b><span class=\"tex\">\\mathcal{O}(N^2)</span>", 1), encoding="utf-8")
    code, result = _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--date", "2026-10-24")
    assert code == 0 and result["changed"] and result["rendered"]["tex"] == 1, result
    assert result["check"]["ok"] and "KaTeX_Caligraphic-Regular" in _source(built)
    code, result = _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0 and result["changed"] is False


@needs_node
def test_code_notes_must_follow_their_code_and_name_its_lines(built: Path, tmp_path: Path, capsys) -> None:
    code, result = _add(capsys, built, tmp_path, FORMULA_SEGMENT)
    assert code == 0, result
    source = _source(built)
    assert "code.highlight-range" in _codes(source.replace('<li data-lines="3">', '<li data-lines="9">', 1))
    assert "code.notes" in _error_codes(source.replace('<li data-lines="3">', '<li data-lines="three">', 1))
    stray = '<ol class="lp-code-notes"><li data-lines="1">孤立的说明</li></ol>'
    assert "code.notes" in _error_codes(_with(source, "<p class=\"lp-lead\"><b>结论</b>", stray + "<p class=\"lp-lead\"><b>结论</b>"))
    assert "code.symbols" in _error_codes(source.replace('data-symbols="m=1 l=2"', 'data-symbols="m=one"', 1))


@needs_node
def test_open_questions_may_show_a_display_formula(built: Path) -> None:
    source = _source(built)
    rendered = re.search(r'<div class="tex" data-tex="[^"]*">.*?</div>(?=\s*<p>下面用)', source, re.S)
    assert rendered is not None
    edited = source.replace('<p class="lp-how">', rendered.group(0) + '<p class="lp-how">', 1)
    assert "check.leak" not in _codes(edited)


def _render(capsys, built: Path) -> tuple[int, dict]:
    return _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--date", "2026-10-24")


@needs_node
def test_render_redraws_edited_tex_and_restores_styles_without_churn(built: Path, tmp_path: Path, capsys) -> None:
    code, result = _add(capsys, built, tmp_path, FORMULA_SEGMENT.replace('data-lang="python"', 'data-lang="plaintext"'))
    assert code == 0, result
    code, result = _render(capsys, built)
    assert code == 0 and result["changed"] is False, result
    source = _source(built)
    edited = source.replace('data-tex="\\sA{m} &lt; x"', 'data-tex="\\sA{m} &gt; x"', 1)
    assert "math.stale" in _error_codes(edited)
    built.write_text(re.sub(r'<style id="lp-katex">.*?</style>\n', "", edited, flags=re.S), encoding="utf-8")
    code, result = _render(capsys, built)
    assert code == 0 and result["changed"] and result["rendered"]["tex"] == 1, result
    assert result["check"]["ok"] and result["check"]["warnings"] == []
    assert '<annotation encoding="application/x-tex">\\sA{m} &gt; x</annotation>' in _source(built)


@needs_node
def test_formulas_from_another_katex_are_redrawn_on_the_next_write(built: Path, tmp_path: Path, capsys) -> None:
    source = _source(built)
    old = source.replace(f"KaTeX {lp.KATEX_VERSION} stylesheet", "KaTeX 0.16.0 stylesheet", 1)
    assert "math.version" in _codes(old)
    built.write_text(old, encoding="utf-8")
    code, result = _add(capsys, built, tmp_path, '<p id="t-9">再加一段。</p>', "--into", "node-2")
    assert code == 0 and result["check"]["warnings"] == [], result
    assert f"KaTeX {lp.KATEX_VERSION} stylesheet" in _source(built)


def test_katex_version_matches_the_vendored_script() -> None:
    script = (ROOT / "assets" / "vendor" / "katex" / "katex.min.js").read_text(encoding="utf-8")
    assert f'version:"{lp.KATEX_VERSION}"' in script.replace(" ", "")


@needs_node
def test_tex_class_inside_code_svg_or_math_is_left_alone(built: Path, tmp_path: Path, capsys) -> None:
    fragment = '<pre class="lp-code" id="t-4"><code>\\begin{document} <span class="tex">x</span></code></pre>'
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0 and result["rendered"]["tex"] == 0, result


@needs_node
def test_crlf_fragments_keep_code_line_numbers(built: Path, tmp_path: Path, capsys) -> None:
    fragment = tmp_path / "crlf.html"
    fragment.write_bytes('<pre class="lp-code" id="t-5" data-lang="shell"><code>$ ls\r\nfoo\r\n$ echo hi\r\nhi</code></pre>'.encode("utf-8"))
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", str(fragment), "--into", "node-2")
    assert code == 0, result
    block = re.search(r'<pre class="lp-code" id="t-5".*?</pre>', _source(built), re.S).group(0)
    assert "\r" not in block and block.count("\n") == 3


def test_blocks_inside_paragraphs_through_inline_elements_are_refused() -> None:
    page = lp.Page('<section id="s"><p>前文 <b><div class="tex">x</div></b> 后文</p></section>')
    assert any(code == "html.block-in-p" for code, _message, _line in page.structure_problems())
    fine = lp.Page('<section id="s"><p>前文<button><div>x</div></button></p></section>')
    assert not any(code == "html.block-in-p" for code, _message, _line in fine.structure_problems())


@needs_node
def test_two_noted_code_blocks_in_one_figure_check_their_own_lines(built: Path, tmp_path: Path, capsys) -> None:
    fragment = """<figure class="lp-figure" id="fig-9-2">
<pre class="lp-code" id="t-6"><code>a
b</code></pre>
<ol class="lp-code-notes"><li data-lines="2">第二行。</li></ol>
<pre class="lp-code" id="t-7" data-start="10"><code>c
d
e</code></pre>
<ol class="lp-code-notes"><li data-lines="10-12">三行。</li></ol>
<figcaption><b>图 9.2</b>两段代码。</figcaption></figure>"""
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0 and result["check"]["warnings"] == [], result


@needs_node
def test_main_font_is_embedded_for_every_formula_page(repo: Path, tmp_path: Path, capsys) -> None:
    fragment = _fragment(tmp_path, "ams.html", '<section class="lp-narrative" id="intro"><h2>导入</h2><p><span class="tex">\\mathbb{R}</span></p></section>')
    code, result = _new(capsys, repo, "--fragment", fragment)
    assert code == 0, result
    fonts = re.search(r"fonts: ([^*]+)\*/", _source(repo / PAGE)).group(1).split()
    assert {"KaTeX_Main-Regular", "KaTeX_AMS-Regular"} <= set(fonts)


@needs_node
def test_symbol_colors_respect_unicode_and_dollar_identifiers(built: Path, tmp_path: Path, capsys) -> None:
    fragment = '<pre class="lp-code" id="t-8" data-lang="javascript" data-symbols="m=1"><code>$m + m$ + mα + m</code></pre>'
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0, result
    block = re.search(r'<pre class="lp-code" id="t-8".*?</pre>', _source(built), re.S).group(0)
    assert block.count('<var class="lp-s1">m</var>') == 1


@pytest.mark.parametrize("markup, flagged", [
    ('<svg viewBox="0 0 10 10"><text>a<sub>i</sub></text></svg>', True),
    ('<svg viewBox="0 0 10 10"><foreignObject><div>ok</div></foreignObject></svg>', False),
    ('<math><mtext><b>ok</b></mtext></math>', False),
    ('<math><mi>x</mi><span>no</span></math>', True),
])
def test_html_inside_svg_or_math_that_browsers_break_out_of_is_flagged(markup: str, flagged: bool) -> None:
    codes = {code for code, _message, _line in lp.Page(f'<section id="s">{markup}</section>').structure_problems()}
    assert ("html.foreign-breakout" in codes) is flagged


@pytest.mark.parametrize("markup, flagged", [
    ("<ul><li><p>一<li><div>二</div></ul>", False),
    ("<dl><dt><p>词<dd><div>释义</div></dl>", False),
    ("<p>前文 <span><li>项</li></span></p>", True),
])
def test_implied_end_tags_close_through_paragraphs_like_browsers(markup: str, flagged: bool) -> None:
    codes = {code for code, _message, _line in lp.Page(f'<section id="s">{markup}</section>').structure_problems()}
    assert ("html.block-in-p" in codes) is flagged


@needs_node
def test_stepper_steps_may_light_lines_of_any_code_block_in_the_figure(built: Path, tmp_path: Path, capsys) -> None:
    fragment = """<figure class="lp-figure lp-stepper" id="fig-9-3">
<pre class="lp-code" id="t-10"><code>a
b</code></pre>
<pre class="lp-code" id="t-11" data-start="10"><code>c
d</code></pre>
<ol class="lp-steps"><li data-lines="2">一</li><li data-lines="11">二</li></ol>
<figcaption><b>图 9.3</b>两段代码。</figcaption></figure>"""
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0 and result["check"]["warnings"] == [], result
    assert "code.highlight-range" in _codes(_source(built).replace('<li data-lines="11">', '<li data-lines="30">', 1))


@needs_node
def test_every_write_refreshes_the_visible_date(built: Path) -> None:
    assert "更新于 2026-10-23" in _source(built) and "更新于 2026-10-22" not in _source(built)


@needs_node
def test_crlf_pages_keep_multiline_formulas_current(built: Path, tmp_path: Path, capsys) -> None:
    built.write_bytes(built.read_bytes().replace(b"\n", b"\r\n"))
    fragment = '<div class="tex" id="t-12">\\begin{aligned}a &amp;= b \\\\ c &amp;= d\\end{aligned}</div>'
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-2")
    assert code == 0 and result["check"]["ok"], result
    assert b"\n" not in built.read_bytes().replace(b"\r\n", b"")
    code, result = _render(capsys, built)
    assert code == 0 and result["changed"] is False, result


@needs_node
def test_render_redraws_pages_from_another_katex(built: Path, capsys) -> None:
    built.write_text(_source(built).replace(f"KaTeX {lp.KATEX_VERSION} stylesheet", "KaTeX 0.16.0 stylesheet", 1), encoding="utf-8")
    code, result = _render(capsys, built)
    # Identical output is not counted as a change; the stylesheet header still moves to the current version.
    assert code == 0 and result["changed"], result
    assert result["check"]["warnings"] == [] and f"KaTeX {lp.KATEX_VERSION} stylesheet" in _source(built)


@needs_node
def test_old_katex_pages_need_node_and_say_so(built: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    built.write_text(_source(built).replace(f"KaTeX {lp.KATEX_VERSION} stylesheet", "KaTeX 0.16.0 stylesheet", 1), encoding="utf-8")
    monkeypatch.setattr(lp.shutil, "which", lambda name: None)
    code, result = _add(capsys, built, tmp_path, '<p id="t-13">纯文字。</p>', "--into", "node-2")
    assert code == 2 and "KaTeX 0.16.0" in result["error"] and "Node.js" in result["error"]


@needs_node
def test_embedded_formula_styles_carry_both_licences(built: Path) -> None:
    block = re.search(r'<style id="lp-katex">(.*?)</style>', _source(built), re.S).group(1)
    assert "Permission is hereby granted" in block and "SIL OPEN FONT LICENSE" in block



# ---------------------------------------------------------------- looks, live paragraphs, ruby


def _stable(source: str) -> str:
    """The page without what every write changes: revision, date and the visible update line."""
    source = re.sub(r'data-rev="\d+" data-updated="[0-9-]+"', "", source, count=1)
    return re.sub(r"更新于 [0-9-]+", "", source, count=1)


def _look(capsys, page: Path, look: str) -> tuple[int, dict]:
    return _run(capsys, "look", "--repo", str(page.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                "--to", look, "--date", "2026-10-24")


def test_new_with_a_look_carries_its_stylesheet(repo: Path, capsys) -> None:
    code, result = _new(capsys, repo, "--look", "blueprint")
    assert code == 0 and result["look"] == "blueprint"
    assert result["check"] == {"ok": True, "errors": [], "warnings": []}
    source = _source(repo / PAGE)
    assert '<html lang="zh-CN" data-look="blueprint">' in source
    style = (ROOT / "assets" / "looks" / "blueprint.css").read_text(encoding="utf-8").strip("\n")
    assert source.count('<style id="lp-look">') == 1 and f'<style id="lp-look">\n{style}\n</style>' in source
    assert source.index('id="lp-base"') < source.index('id="lp-look"') < source.index('id="lp-page-style"')
    with pytest.raises(SystemExit):
        lp.main(["new", "--repo", str(repo), "--page", "learning/pages/x.html", "--id", "x", "--title", "t", "--look", "neon"])


def test_look_command_switches_looks_and_back_without_residue(built: Path, capsys) -> None:
    handout = _source(built)
    code, result = _look(capsys, built, "vermilion")
    assert code == 0 and result["changed"] and result["rev"] == 3 and result["check"]["ok"], result
    assert result["check"]["warnings"] == []
    source = _source(built)
    assert 'data-look="vermilion"' in source and source.count('<style id="lp-look">') == 1
    code, result = _look(capsys, built, "blueprint")
    assert code == 0 and result["rev"] == 4
    source = _source(built)
    assert 'data-look="blueprint"' in source and source.count('<style id="lp-look">') == 1 and "--gold" not in source
    code, result = _look(capsys, built, "blueprint")
    assert code == 0 and result == {"page": PAGE, "rev": 4, "look": "blueprint", "changed": False}
    code, result = _look(capsys, built, "handout")
    assert code == 0 and result["rev"] == 5
    assert _stable(_source(built)) == _stable(handout)


def test_look_command_refreshes_a_hand_edited_look(built: Path, capsys) -> None:
    _look(capsys, built, "blueprint")
    edited = _with(_source(built), '<style id="lp-look">\n', '<style id="lp-look">\n.x { color: red; }\n')
    built.write_text(edited, encoding="utf-8")
    report = lp.check_source(edited, built)
    assert [item["code"] for item in report.as_dict()["warnings"]] == ["runtime.drift"]
    code, result = _look(capsys, built, "blueprint")
    assert code == 0 and result["changed"] and result["check"]["warnings"] == []


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('<html lang="zh-CN">', '<html lang="zh-CN" data-look="neon">', "look.unknown"),
        ('<html lang="zh-CN">', '<html lang="zh-CN" data-look="handout">', "look.unknown"),
        ('<html lang="zh-CN">', '<html lang="zh-CN" data-look="blueprint">', "look.css"),
        ('<style id="lp-page-style">', '<style id="lp-look">.lp-title { font-size: 9px; }</style>\n<style id="lp-page-style">', "look.css"),
    ],
)
def test_check_requires_a_known_look_with_its_stylesheet(built: Path, old: str, new: str, code: str) -> None:
    assert code in _error_codes(_with(_source(built), old, new), built)


def test_find_and_outline_report_each_page_look(built: Path, capsys) -> None:
    repo = built.parents[2]
    code, result = _run(capsys, "find", "--repo", str(repo), "--in", "learning/pages")
    assert result["pages"][0]["look"] == "handout"
    assert lp.outline_source(_source(built))["look"] == "handout"
    _look(capsys, built, "vermilion")
    code, result = _run(capsys, "find", "--repo", str(repo), "--in", "learning/pages")
    assert result["pages"][0]["look"] == "vermilion"
    assert lp.outline_source(_source(built))["look"] == "vermilion"


def test_example_live_paragraph_is_listed_with_the_node_figures(built: Path) -> None:
    node = next(block for block in lp.outline_source(_source(built))["blocks"] if block["id"] == "node-1")
    assert {"id": "live-1-1", "kind": "live"} in node["figures"]


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('data-values="2,4" data-labels="FP16,FP32">FP16</span>', 'data-values="2,4" data-labels="FP16">FP16</span>', "live.knob"),
        ('data-values="2,4" data-labels="FP16,FP32">FP16</span>', 'data-values="2" data-labels="FP16">FP16</span>', "live.knob"),
        ('data-values="2,4" data-labels="FP16,FP32">FP16</span>', 'data-values="2,4" data-labels="FP16,FP32">BF16</span>', "live.knob"),
        ('data-values="2,4" data-labels="FP16,FP32">FP16</span>', 'data-values="2,4" data-labels="FP16,FP32"><b>FP16</b></span>', "live.knob"),
        ('data-knob="bytes"', 'data-knob="2-bytes"', "live.knob"),
        ("</main>", '<p>N = <span class="lp-knob" data-knob="n" data-values="1,2">1</span></p></main>', "live.knob"),
        ("</main>", '<p class="lp-live" id="live-9">N = <span data-knob="n" data-values="1,2">1</span></p></main>', "live.parts"),
        ('<p class="lp-how">', '<p class="lp-live" id="live-q"><span data-knob="n" data-values="1,2">1</span> <span data-out="x">1</span></p><p class="lp-how">', "check.leak"),
    ],
)
def test_check_catches_broken_live_paragraphs(built: Path, old: str, new: str, code: str) -> None:
    source = _source(built)
    assert code not in _error_codes(source, built)
    assert code in _error_codes(_with(source, old, new), built)


def test_live_paragraph_without_a_compute_function_warns(built: Path) -> None:
    source = _with(_source(built), 'LessonPage.explorers["live-1-1"]', 'LessonPage.explorers["live-other"]')
    warnings = lp.check_source(source, built).as_dict()["warnings"]
    assert [item["message"] for item in warnings if item["code"] == "widget.hook"] == ["live paragraph live-1-1 has no registered compute function"]


def test_nothing_live_sits_right_after_an_open_question(built: Path, tmp_path: Path, capsys) -> None:
    live = _fragment(tmp_path, "live.html", '<p class="lp-live" id="live-q">n = <span data-knob="n" data-values="1,2">1</span>, x = <span data-out="x">1</span></p>')
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", live, "--after", "q-1")
    assert code == 2 and "check.leak" in result["error"]


@needs_node
def test_ruby_annotations_stay_out_of_reading_time_and_titles(built: Path, tmp_path: Path, capsys) -> None:
    words = " ".join(["throughput"] * 40)
    segment = ('<section class="lp-node" id="node-9" data-stages="st-online"><h2><span class="lp-no">9</span>'
               '<ruby>显存<rt>HBM</rt></ruby>带宽</h2><p class="lp-spine">第 3 节</p>'
               f'<p class="lp-lead"><b>结论</b><ruby>吞吐<rp>(</rp><rt>{words}</rt><rp>)</rp></ruby>受限于带宽。</p></section>')
    code, result = _add(capsys, built, tmp_path, segment)
    assert code == 0 and result["check"]["ok"], result
    assert result["reading_minutes"] == 1
    node = next(block for block in lp.outline_source(_source(built))["blocks"] if block["id"] == "node-9")
    assert node["title"] == "9 显存带宽"


def test_template_offers_strata_and_no_look_switcher() -> None:
    template = (ROOT / "assets" / "lesson-template.html").read_text(encoding="utf-8")
    assert '<button type="button" data-lp-strata aria-pressed="false">地层</button>' in template
    assert "data-lp-look" not in template and 'id="lp-look"' not in template
    for look in lp.LOOKS[1:]:
        style = (ROOT / "assets" / "looks" / f"{look}.css").read_text(encoding="utf-8")
        assert f':root[data-look="{look}"]' in style and not re.search(r"https?://|@import|url\(", style)


# ---------------------------------------------------------------- widget packs


MYTH = '<div class="lp-myth"><p class="lp-myth-wrong">分块会少算一部分分数。</p><p class="lp-myth-right">每个分数都算了，少的是显存读写。</p></div>'
SCALE = ('<figure class="lp-figure lp-scale" id="fig-9-1" data-unit="B/s"><ol><li data-value="1.5e12"><b>HBM</b>1.5 TB/s</li>'
         '<li data-value="1.9e13"><b>SRAM</b>19 TB/s</li></ol><figcaption><b>图 9.1</b>两级存储的带宽。</figcaption></figure>')


def _pack(name: str, kind: str) -> str:
    return (ROOT / "assets" / "packs" / f"{name}.{kind}").read_text(encoding="utf-8").strip("\n")


def test_widgets_bring_their_own_pack_and_no_other(built: Path, tmp_path: Path, capsys) -> None:
    source = _source(built)
    assert 'id="lp-pack-' not in source and lp.outline_source(source)["packs"] == []
    code, result = _add(capsys, built, tmp_path, MYTH)
    assert code == 0 and result["check"]["ok"] and result["check"]["warnings"] == [], result
    source = _source(built)
    assert f'<style id="lp-pack-myth">\n{_pack("myth", "css")}\n</style>' in source
    assert f'<script id="lp-pack-myth-js">\n{_pack("myth", "js")}\n</script>\n<script id="lp-runtime">' in source
    assert source.count('id="lp-pack-') == 2
    code, result = _add(capsys, built, tmp_path, SCALE, "--into", "node-1")
    assert code == 0 and result["check"]["warnings"] == [], result
    source = _source(built)
    assert source.index('id="lp-base"') < source.index('id="lp-pack-myth"') < source.index('id="lp-pack-scale"') < source.index('id="lp-katex"')
    assert source.index('id="lp-pack-myth-js"') < source.index('id="lp-pack-scale-js"') < source.index('id="lp-runtime"')
    outline = lp.outline_source(source)
    assert outline["packs"] == ["myth", "scale"]
    assert {"id": "fig-9-1", "kind": "scale"} in next(block for block in outline["blocks"] if block["id"] == "node-1")["figures"]


def test_packs_stay_after_the_look_and_writes_do_not_churn_them(built: Path, tmp_path: Path, capsys) -> None:
    _add(capsys, built, tmp_path, MYTH)
    handout = _source(built)
    assert lp._ensure_packs(handout) == handout
    code, result = _look(capsys, built, "vermilion")
    assert code == 0 and result["check"]["warnings"] == [], result
    source = _source(built)
    assert source.index('id="lp-base"') < source.index('id="lp-look"') < source.index('id="lp-pack-myth"')
    assert lp._ensure_packs(source) == source
    _look(capsys, built, "handout")
    assert _stable(_source(built)) == _stable(handout)
    crlf = handout.replace("\n", "\r\n")
    assert lp._ensure_packs(crlf) == crlf


def test_render_refreshes_stale_packs_and_drops_unused_ones(built: Path, tmp_path: Path, capsys) -> None:
    _add(capsys, built, tmp_path, MYTH)
    edited = _with(_source(built), '<style id="lp-pack-myth">\n', '<style id="lp-pack-myth">\n.lp-myth { border: 0; }\n')
    built.write_text(edited, encoding="utf-8")
    assert [item["code"] for item in lp.check_source(edited, built).as_dict()["warnings"]] == ["runtime.drift"]
    render = lambda: _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID, "--date", "2026-10-24")  # noqa: E731
    code, result = render()
    assert code == 0 and result["changed"] and result["check"]["warnings"] == [], result
    assert ".lp-myth { border: 0; }" not in _source(built)
    unused = re.sub(r'<div class="lp-myth" data-rev="\d+">.*?</div>\n', "", _source(built), flags=re.S)
    built.write_text(unused, encoding="utf-8")
    assert {item["code"] for item in lp.check_source(unused, built).as_dict()["warnings"]} == {"pack.unused"}
    code, result = render()
    assert code == 0 and result["changed"] and result["check"]["warnings"] == [], result
    assert 'id="lp-pack-' not in _source(built)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('<style id="lp-pack-myth">', '<style id="lp-pack-myth-gone">', "pack.missing"),
        ('<script id="lp-pack-myth-js">', '<script id="lp-pack-myth-gone">', "pack.missing"),
        ('<style id="lp-page-style">', '<style id="lp-pack-neon">.x { margin: 0; }</style>\n<style id="lp-page-style">', "pack.unknown"),
        ('<script id="lp-runtime">', '<script id="lp-pack-myth">void 0;</script>\n<script id="lp-runtime">', "pack.unknown"),
    ],
)
def test_check_flags_missing_and_unknown_packs(built: Path, tmp_path: Path, capsys, old: str, new: str, code: str) -> None:
    _add(capsys, built, tmp_path, MYTH)
    source = _source(built)
    assert code not in _error_codes(source, built)
    assert code in _error_codes(_with(source, old, new), built)


def test_interactive_packs_count_as_widgets_next_to_open_questions(built: Path, tmp_path: Path, capsys) -> None:
    code, result = _add(capsys, built, tmp_path, SCALE, "--after", "q-1")
    assert code == 2 and "check.leak" in result["error"]
    code, result = _add(capsys, built, tmp_path, MYTH, "--after", "q-1")
    assert code == 0, result


@needs_node
def test_anatomy_terms_render_with_their_own_classes(built: Path, tmp_path: Path, capsys) -> None:
    figure = ('<figure class="lp-figure lp-anatomy" id="fig-9-2"><div class="tex">y = \\tA{a}\\,\\tB{x} + \\tC{b}</div>'
              '<ol class="lp-terms"><li>斜率</li><li>输入</li><li>截距</li></ol><figcaption><b>图 9.2</b>直线。</figcaption></figure>')
    code, result = _add(capsys, built, tmp_path, figure, "--into", "node-2")
    assert code == 0 and result["check"]["warnings"] == [], result
    source = _source(built)
    for n in (1, 2, 3):
        assert re.search(rf'class="enclosing lp-t{n}"', source)
    assert 'id="lp-pack-anatomy"' in source and 'id="lp-pack-anatomy-js"' in source
    code, result = _add(capsys, built, tmp_path, '<div class="tex">\\htmlClass{lp-t7}{x}</div>', "--into", "node-2")
    assert code == 2 and "not allowed" in result["error"]


def test_every_pack_registers_itself_and_stays_offline() -> None:
    folder = ROOT / "assets" / "packs"
    assert sorted({path.stem for path in folder.iterdir()}) == sorted(lp.PACKS)
    for name in lp.PACKS:
        css, js = _pack(name, "css"), _pack(name, "js")
        assert f".lp-{name}" in css and not re.search(r"https?://|@import|url\(", css)
        assert f'push({{ name: "{name}", init: function (ui) {{' in js
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)|fetch\(|XMLHttpRequest|eval\(", js)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.S)), name


def test_trace_records_what_each_line_changes(tmp_path: Path, capsys) -> None:
    example = tmp_path / "running_max.py"
    example.write_text("def running_max(xs):\n    best = -float('inf')\n    for x in xs:\n        best = max(best, x)\n"
                       "    squares = [x * x for x in xs]\n    return best\n\nrunning_max([2.5, -1, 4])\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "best x squares return", "--function", "running_max")
    assert code == 0, result
    assert [row["line"] for row in result["steps"]] == [2, 3, 4, 3, 4, 3, 4, 3, 5, 6]
    assert result["steps"][0]["set"] == {"best": "−∞"}
    assert result["steps"][2]["set"] == {"best": "2.5"}
    assert result["steps"][8]["set"] == {"squares": "[6.25,1,16]"}
    assert result["steps"][-1]["set"] == {"return": "4"}
    assert result["html"].splitlines()[0] == '<li data-line="2" data-set="best=−∞"></li>'
    assert not result["truncated"] and result["code_lines"] == 8
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "best", "--function", "running_max", "--max-steps", "3")
    assert code == 0 and result["truncated"]


def test_trace_reports_arguments_and_refuses_nested_frames(tmp_path: Path, capsys) -> None:
    example = tmp_path / "scale.py"
    example.write_text("def scale(xs, k):\n    out = [x * k for x in xs]\n    return out\n\nscale([1, 2], 3)\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "xs k out", "--function", "scale")
    assert code == 0, result
    assert result["steps"][0] == {"line": 2, "set": {"xs": "[1,2]", "k": "3", "out": "[3,6]"}}
    recursive = tmp_path / "fact.py"
    recursive.write_text("def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\nfact(3)\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(recursive), "--vars", "n return", "--function", "fact")
    assert code == 2 and "out of order" in result["error"]


def test_trace_keeps_calls_apart_and_small_values_visible(tmp_path: Path, capsys) -> None:
    # CPython hands a finished frame's id to the next call; each call must still report its own arguments.
    example = tmp_path / "calls.py"
    example.write_text("import math\n\ndef sq(x): return x * x\n\ndef total(xs, start=0):\n    s = start\n    for x in xs:\n"
                       "        s += x\n    return s\n\ndef rescale(m, m_new):\n    return math.exp(m - m_new)\n\n"
                       "def count(n):\n    i = 0\n    while i < n:\n        yield i\n        i += 1\n\n"
                       "sq(3)\nsq(4)\ntotal([1, 2])\ntotal([4], 100)\nrescale(1.0, 13.0)\nlist(count(2))\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "x return", "--function", "sq")
    assert code == 0 and result["steps"] == [{"line": 3, "set": {"x": "3", "return": "9"}},
                                             {"line": 3, "call": 2, "set": {"x": "4", "return": "16"}}]
    # From the second call on, the first step is numbered so the replay clears what the earlier call left in the table.
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "xs start s x", "--function", "total")
    starts = [row for row in result["steps"] if row["line"] == 6]
    assert starts == [{"line": 6, "set": {"xs": "[1,2]", "start": "0", "s": "0"}},
                      {"line": 6, "call": 2, "set": {"xs": "[4]", "start": "100", "s": "100"}}]
    assert result["html"].count("data-call") == 1 and '<li data-line="6" data-call="2" data-set="xs=[4]' in result["html"]
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "return", "--function", "rescale")
    assert result["steps"][-1]["set"] == {"return": "6.144e−6"}
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "i n", "--function", "count")
    assert [row["set"] for row in result["steps"]][:5] == [{"i": "0", "n": "2"}, {}, {}, {"i": "1"}, {}]


@pytest.mark.parametrize(
    "figure",
    [
        '<figure class="lp-figure lp-anatomy" id="fig-9-4"><div class="tex">y = ax + b</div>'
        '<ol class="lp-terms"><li>斜率</li></ol><figcaption><b>图 9.4</b>直线。</figcaption></figure>',
        '<figure class="lp-figure lp-scale" id="fig-9-5"><ol><li data-value="\uff11e10">a</li><li data-value="1e12">b</li></ol>'
        '<figcaption><b>图 9.5</b>两个量。</figcaption></figure>',
    ],
)
def test_check_refuses_widgets_the_browser_cannot_start(built: Path, tmp_path: Path, capsys, figure: str) -> None:
    code, result = _add(capsys, built, tmp_path, figure, "--into", "node-2")
    assert code == 2 and "pack.markup" in result["error"], result


def test_trace_refuses_bad_names_and_failing_examples(tmp_path: Path, capsys) -> None:
    example = tmp_path / "broken.py"
    example.write_text("def f():\n    return 1 / 0\n\nf()\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "x-y")
    assert code == 2 and "identifiers" in result["error"]
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "x")
    assert code == 2 and "ZeroDivisionError" in result["error"]


def test_trace_refuses_a_loop_body_on_its_header_line(tmp_path: Path, capsys) -> None:
    # Every pass reports that line again and a repeated line is one step, so the whole loop would replay as one step.
    example = tmp_path / "total.py"
    for loop, line in [("for x in xs: s += x", 3), ("while s < 9: s += 4", 3), ("while \\\n            s < 9: s += 4", 4)]:
        example.write_text(f"def total(xs):\n    s = 0\n    {loop}\n    return s\n\ntotal([3, 5])\n", encoding="utf-8")
        code, result = _run(capsys, "trace", "--code", str(example), "--vars", "s", "--function", "total")
        assert code == 2 and f"header (line {line})" in result["error"], result
    # A header broken over lines still alternates with its body, and code outside --function is not replayed.
    example.write_text("def total(xs):\n    s = 0\n    for x in [3,\n              5]: s += x\n    return s\n\n"
                       "for xs in [[3, 5]]: total(xs)\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "s", "--function", "total")
    assert code == 0 and [row["line"] for row in result["steps"]] == [2, 3, 4, 3, 4, 3, 5], result


@needs_node
def test_every_widget_pack_builds_from_the_fixture(built: Path, capsys) -> None:
    fixtures = [ROOT / "tests" / "fixtures" / "widget-packs.html",
                REFERENCES / "example-source-tree.html", REFERENCES / "example-timeline.html"]
    for fixture in fixtures:
        code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                            "--fragment", str(fixture), "--date", "2026-10-29")
        assert code == 0 and result["check"]["ok"], result
        assert result["check"]["warnings"] == [], result
    source = _source(built)
    assert lp.outline_source(source)["packs"] == sorted(lp.PACKS)
    for name in lp.PACKS:
        assert source.count(f'<style id="lp-pack-{name}">') == 1 and source.count(f'<script id="lp-pack-{name}-js">') == 1


@pytest.mark.parametrize("look", ["handout", "blueprint", "vermilion"])
def test_sample_pages_are_valid_pages_in_each_look(look: str) -> None:
    # Snapshots of the second visual round for people to open in a browser; they do not follow later template changes.
    source = (ROOT / "references" / "sample-pages" / f"attn-03-{look}.html").read_text(encoding="utf-8")
    assert not lp.check_source(source, None).errors
    assert (lp.Page(source).find("html")[0].attrs.get("data-look") or "handout") == look


def test_fixture_replay_is_a_real_run(tmp_path: Path, capsys) -> None:
    text = (ROOT / "tests" / "fixtures" / "widget-packs.html").read_text(encoding="utf-8")
    example = tmp_path / "online_softmax.py"
    example.write_text(html.unescape(re.search(r"<code>(.*?)</code></pre>", text, re.S).group(1)) + "\n\n"
                       "attention_row([1.2, 3.1, 0.4, 2.0, 4.5, 0.8, 2.2, 1.0, 3.9, 5.6, 0.3, 2.7],\n"
                       "              [0.5, -1.0, 2.0, 0.3, 1.5, -0.4, 0.9, 1.1, -0.7, 0.8, 1.6, -0.2])\n", encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "s m m_new alpha p l acc return", "--function", "attention_row")
    assert code == 0, result
    shown = [(int(match.group(1)), dict(pair.split("=", 1) for pair in (match.group(2) or "").split()))
             for match in re.finditer(r'<li data-line="(\d+)"(?: data-set="([^"]*)")?', text)]
    assert shown == [(row["line"], row["set"]) for row in result["steps"]]


def _with_fixture(built: Path, capsys) -> str:
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", str(ROOT / "tests" / "fixtures" / "widget-packs.html"), "--date", "2026-10-24")
    assert code == 0, result
    return _source(built)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<p class="lp-poster-num"><b>512</b>', '<p class="lp-poster-num"><b>512 MiB</b>'),
        ('<li data-value="1.28e10">', '<li data-value="fast">'),
        ('<p class="lp-myth-right">', '<p class="lp-myth-other">'),
        ('<div class="lp-analogy-limit">', '<div class="lp-analogy-more">'),
        ("<li>本块的指数和，直接以新的最大值为基准。</li>", ""),
        ('id="fig-3-5">\n    <ol>\n      <li><div class="tex"', 'id="fig-3-5">\n    <ol>\n      <li><div class="formula"'),
        ('data-line="14"', 'data-line="44"'),
        ('data-set="m=−∞ l=0 acc=0"', 'data-set="m = −∞"'),
        ('id="fig-3-3" data-domain="software"', 'id="fig-3-3" data-domain="network"'),
    ],
)
def test_check_flags_broken_widget_markup(built: Path, capsys, old: str, new: str) -> None:
    source = _with_fixture(built, capsys)
    assert "pack.markup" not in _error_codes(source, built)
    assert "pack.markup" in _error_codes(_with(source, old, new), built)


def test_widgets_need_the_runtime_that_starts_them(built: Path, tmp_path: Path, capsys) -> None:
    _add(capsys, built, tmp_path, MYTH)
    source = _source(built)
    assert "pack.runtime" not in _error_codes(source, built)
    old = _with(source, "lesson-pages runtime v3", "lesson-pages runtime v2")
    assert "pack.runtime" in _error_codes(old, built)
    assert "pack.runtime" not in _error_codes(re.sub(r'<div class="lp-myth".*?</div>\n', "", old, flags=re.S), built)


def test_traced_values_with_spaces_pass_check_unchanged(built: Path, tmp_path: Path, capsys) -> None:
    example = tmp_path / "greet.py"
    example.write_text('def greet(name):\n    msg = ""\n    msg = "hi " + name\n    return msg\n\ngreet("bob")\n', encoding="utf-8")
    code, result = _run(capsys, "trace", "--code", str(example), "--vars", "msg return", "--function", "greet")
    assert code == 0 and 'data-set="msg="' in result["html"] and 'data-set="msg=hi\u00a0bob"' in result["html"], result
    figure = ('<figure class="lp-figure is-stage lp-replay" id="fig-9-3"><pre class="lp-code" data-lang="python"><code>'
              'def greet(name):\n    msg = ""\n    msg = "hi " + name\n    return msg</code></pre>\n<ol class="lp-trace">'
              + result["html"] + '</ol><figcaption><b>图 9.3</b>拼接字符串。</figcaption></figure>')
    code, result = _add(capsys, built, tmp_path, figure, "--into", "node-1")
    assert code == 0 and result["check"]["warnings"] == [], result


# ---------------------------------------------------------------- parts of a long lesson

PART2 = "learning/pages/attn-03-part2.html"
PART3 = "learning/pages/attn-03-part3.html"
PROSE = "这一段把页面撑长，讲在线 softmax 怎样在块之间传递两个统计量，并说明为什么最后才归一化。" * 3
OPENING = (
    '<section class="lp-narrative" id="intro"><h2>这一课要解决什么</h2><p>导入。</p>\n'
    '<figure class="lp-figure is-wide" id="fig-0"><ol class="lp-stages lp-flow">'
    '<li id="st-a" data-label="分块"><b>分块</b><span>第一站</span></li>'
    '<li id="st-b" data-label="在线更新"><b>在线更新</b><span>第二站</span></li>'
    '<li id="st-c" data-label="归一化"><b>归一化</b><span>第三站</span></li></ol>'
    '<figcaption><b>图 0</b>全流程骨架。</figcaption></figure></section>\n'
    '<template data-lp-into="glossary-list"><div id="g-m"><dt>m</dt><dd>每行见过的最大分数。</dd></div></template>\n'
)


def _segment(n: int, stages: str, q: int, paragraphs: int = 3, extra: str = "") -> str:
    body = "".join(f"  <p>{PROSE}</p>\n" for _ in range(paragraphs))
    return (f'<section class="lp-node" id="node-{n}" data-stages="{stages}">\n  <h2><span class="lp-no">{n}</span>第 {n} 个节点</h2>\n'
            f'  <p class="lp-lead">节点 {n} 的结论。</p>\n{body}{extra}</section>\n'
            f'<section class="lp-check" id="q-{q}" data-state="open">\n  <h3>检查 {q}<span class="lp-kind">预测</span></h3>\n'
            f'  <p class="lp-ask">节点 {n} 之后会怎样？</p>\n</section>\n')


def _write(capsys, repo: Path, tmp_path: Path, command: str, page: str, page_id: str, text: str, *extra: str) -> tuple[int, dict]:
    fragment = _fragment(tmp_path, f"{command}-{page_id}-{abs(hash(text))}.html", text)
    return _run(capsys, command, "--repo", str(repo), "--page", page, "--id", page_id, "--fragment", fragment,
                "--date", "2026-10-26", *extra)


@pytest.fixture()
def lesson(repo: Path, tmp_path: Path, capsys, monkeypatch) -> Path:
    """A page holding two nodes, with the split thresholds scaled down to a few minutes."""
    monkeypatch.setattr(lp, "SPLIT_DUE_MINUTES", 2)
    monkeypatch.setattr(lp, "SPLIT_LIMIT_MINUTES", 5)
    code, result = _new(capsys, repo, "--look", "blueprint", "--source", "FlashAttention-2，arXiv:2307.08691 v1。",
                        "--fragment", _fragment(tmp_path, "opening.html", OPENING))
    assert code == 0, result
    for n, stages in ((1, "st-a"), (2, "st-a,st-b")):
        code, result = _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(n, stages, n))
        assert code == 0, result
    return repo


def test_page_minutes_count_lesson_content_and_size_no_longer_splits() -> None:
    source = (REFERENCES / "sample-pages" / "attn-03-handout.html").read_text(encoding="utf-8")
    page = lp.Page(source)
    assert 12 < lp.page_minutes(page) < 15
    without_glossary = re.sub(r'<section class="lp-glossary".*?</section>', "", source, flags=re.S)
    assert abs(lp.page_minutes(lp.Page(without_glossary)) - lp.page_minutes(page)) < 0.01
    assert lp.outline_source(source)["page_minutes"] == round(lp.page_minutes(page))
    # The approved sample is 493 KB but reads in about 14 minutes; file size alone no longer warns.
    assert "page.size-soft" not in {item["code"] for item in lp.check_source(source, None).as_dict()["warnings"]}


def test_a_long_page_refuses_the_next_segment_and_continue_starts_part_two(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    before = page.read_bytes()
    segment = _segment(3, "st-b", 3, extra='  <p>回看<a href="#node-1">节点 1</a>。</p>\n')
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, segment)
    assert code == 2 and "continue in place of add" in result["error"] and PART2 in result["error"], result
    assert page.read_bytes() == before
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, segment)
    assert code == 0, result
    assert (result["page"], result["id"], result["part"], result["rev"]) == (PART2, "attn-03-part2", 2, 2)
    assert result["relinked"] == ["#node-1 -> attn-03.html#node-1"] and result["check"]["errors"] == []
    assert result["previous"]["page"] == PAGE and result["previous"]["rev"] == 4
    second = _source(lesson / PART2)
    marker = lp.Page(second).marker()
    assert marker.attrs["data-id"] == "attn-03-part2" and marker.attrs["data-key"] != lp.Page(_source(page)).marker().attrs["data-key"]
    assert 'data-look="blueprint"' in second and "<title>分块 softmax · Attention 算子 · 第 3 课 · 第 2 页</title>" in second
    assert '<p class="lp-crumb">Attention 算子 · 第 3 课 · 第 2 页</p>' in second
    opening = re.search(r'<section class="lp-narrative" id="part-prev".*?</section>', second, re.S).group(0)
    assert '<a rel="prev" href="attn-03.html">第 1 页</a>' in opening and 'id="st-c"' in opening
    assert 'data-rev' not in opening.split(">", 1)[1]
    assert "lp-back" not in opening and "分页目录" in opening
    # Both pages carry the directory: previous and next page, and each page's nodes, all as relative links.
    pager = re.search(r'<nav class="lp-pager" id="lp-pager".*?</nav>', second, re.S).group(0)
    assert '<a rel="prev" href="attn-03.html">‹ 第 1 页</a><span>第 2 页，共 2 页</span>' in pager
    assert '<a href="attn-03.html#node-1" data-stages="st-a"><b>1</b><span>第 1 个节点</span></a>' in pager
    assert '<li aria-current="page"><a href="#top">第 2 页</a><ol><li><a href="#node-3" data-stages="st-b">' in pager
    assert re.search(r'href="(?:/|file:)', pager) is None
    assert '<div id="g-m" data-lp-copy="attn-03.html" data-rev="1">' in second and "FlashAttention-2，arXiv:2307.08691 v1。" in second
    assert second.index('id="part-prev"') < second.index('id="node-3"') < second.index('id="glossary"')
    assert 'href="attn-03.html#node-1">节点 1</a>' in second
    first = _source(page)
    link = re.search(r'<section class="lp-narrative" id="next-part" data-rev="4">.*?</section>', first, re.S).group(0)
    assert '<a rel="next" href="attn-03-part2.html#node-3">第 2 页</a>' in link and "从节点 3「第 3 个节点」开始" in link
    assert first.index('id="next-part"') < first.index('id="glossary"')
    first_pager = re.search(r'<nav class="lp-pager" id="lp-pager".*?</nav>', first, re.S).group(0)
    assert '<span>第 1 页，共 2 页</span><a rel="next" href="attn-03-part2.html">第 2 页 ›</a>' in first_pager
    assert '<a href="attn-03-part2.html#node-3" data-stages="st-b"><b>3</b>' in first_pager
    for target in (page, lesson / PART2):
        assert lp.check_source(_source(target), target).errors == []


def test_a_segment_that_finishes_the_skeleton_stays_unless_it_passes_the_limit(lesson: Path, tmp_path: Path, capsys) -> None:
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-c", 3, paragraphs=8))
    assert code == 2 and "limit" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3, paragraphs=1).replace("st-b", "st-c"))
    assert code == 2 and "still has room" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-c", 3))
    assert code == 0 and result["page_minutes"] >= 3, result
    # Synthesis, acceptance and supplements never start a page, however long the page is.
    synthesis = '<section class="lp-narrative" id="synthesis"><h2>导师串讲</h2><p>' + PROSE * 6 + "</p></section>"
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, synthesis)
    assert code == 0, result
    supplement = '<aside class="lp-addendum" id="add-1-1"><h3>补充 1.1</h3><p>补一句。</p></aside>'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, supplement, "--into", "node-1")
    assert code == 0, result


def test_writes_after_a_split_go_to_the_page_that_holds_the_block(lesson: Path, tmp_path: Path, capsys) -> None:
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 0, result
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(4, "st-c", 4))
    assert code == 2 and "continues on attn-03-part2.html" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(4, "st-c", 4))
    assert code == 2 and "already continues" in result["error"], result
    supplement = '<aside class="lp-addendum" id="add-1-1"><h3>补充 1.1</h3><p>补一句。</p></aside>'
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", supplement, "--into", "node-1")
    assert code == 2 and "#node-1 is on attn-03.html" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, supplement, "--into", "node-1")
    assert code == 0, result
    glossary = '<template data-lp-into="glossary-list"><div id="g-l"><dt>ℓ</dt><dd>指数和。</dd></div></template>'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, glossary)
    assert code == 0, result
    code, result = _run(capsys, "state", "--repo", str(lesson), "--page", PART2, "--id", "attn-03-part2", "--question", "q-1", "--to", "answered")
    assert code == 2 and "#q-1 is on attn-03.html" in result["error"], result
    code, result = _run(capsys, "state", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID, "--question", "q-1", "--to", "answered")
    assert code == 0, result
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(2, "st-c", 9))
    assert code == 2 and "node-2 (attn-03.html)" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", '<section class="lp-narrative" id="next-part"><h2>x</h2><p>x</p></section>')
    assert code == 2 and "continue writes them" in result["error"], result


def test_widgets_on_a_later_page_may_reveal_a_question_closed_earlier(lesson: Path, tmp_path: Path, capsys) -> None:
    _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 0, result
    toggle = ('<details class="lp-toggle" id="add-3-1" data-reveals="q-1"><summary>展开</summary><p>与检查 1 有关。</p></details>')
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", toggle, "--into", "node-3")
    assert code == 2 and "reveals q-1 on attn-03.html, which is still open" in result["error"], result
    code, result = _run(capsys, "state", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID, "--question", "q-1", "--to", "closed")
    assert code == 0, result
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", toggle, "--into", "node-3")
    assert code == 0, result
    second = lesson / PART2
    broken = _with(_source(second), 'href="attn-03.html#node-1"', 'href="attn-03.html#node-99"')
    assert "link.anchor" in _error_codes(broken, second)
    (second.parent / "plain.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    assert "link.anchor" not in _error_codes(_with(_source(second), 'href="attn-03.html#node-1"', 'href="plain.html#nowhere"'), second)


def test_outline_find_and_check_see_every_page(lesson: Path, tmp_path: Path, capsys) -> None:
    _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4))
    assert code == 0, result
    code, result = _write(capsys, lesson, tmp_path, "continue", PART2, "attn-03-part2", _segment(5, "st-b", 5))
    assert code == 0 and result["page"] == PART3, result
    third = _source(lesson / PART3)
    assert '<a rel="prev" href="attn-03-part2.html">第 2 页</a>' in third
    assert '<a href="attn-03.html">第 1 页</a>' in third and '<a href="attn-03-part2.html">第 2 页</a>' in third
    assert 'href="attn-03-part2.html#node-4"' in third
    # Page 1's directory was refreshed when part 3 appeared, and again when part 3 gained a node.
    assert result["directory_refreshed"] == [PAGE] and 'href="attn-03-part3.html#node-5"' in _source(lesson / PAGE)
    code, result = _write(capsys, lesson, tmp_path, "add", PART3, "attn-03-part3", _segment(6, "st-c", 6, paragraphs=1))
    assert code == 0 and result["directory_refreshed"] == [PAGE, PART2], result
    assert 'href="attn-03-part3.html#node-6"' in _source(lesson / PAGE)
    assert 'href="attn-03-part3.html#node-5"' in _source(lesson / PART2)
    code, result = _run(capsys, "outline", "--repo", str(lesson), "--page", PART2)
    parts = result["lesson"]["parts"]
    assert [(part["page"], part["part"]) for part in parts] == [(PAGE, 1), (PART2, 2), (PART3, 3)]
    assert parts[0]["questions"] == {"q-1": "open", "q-2": "open"} and "next-part" in parts[0]["blocks"]
    assert result["lesson"]["next"] == {"node": 7, "q": 7, "q-a": 1} and result["lesson"]["part"] == 2
    code, result = _run(capsys, "find", "--repo", str(lesson), "--in", "learning/pages", "--lesson", PAGE_ID)
    assert [(page["page"], page["part"]) for page in result["pages"]] == [(PAGE, 1), (PART2, 2), (PART3, 3)]
    code, result = _run(capsys, "check", "--repo", str(lesson), "--page", PART3, "--anchor", "node-5", "--anchor", "node-1")
    assert code == 1 and [item["message"] for item in result["errors"]] == ["#node-1 is on attn-03.html, not this page; link that file in chat"]
    code, result = _run(capsys, "new", "--repo", str(lesson), "--page", "learning/pages/x-part2.html", "--id", "x-part2", "--title", "x")
    assert code == 2 and "choose another id" in result["error"]


def test_continue_can_repair_a_missing_link(lesson: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    original = lp._replace

    def changed(path: Path, data: bytes, text: str) -> None:
        raise lp.UsageError(f"{path.name} changed after it was read")

    monkeypatch.setattr(lp, "_replace", changed)
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "was written, but linking it from attn-03.html failed" in result["error"], result
    assert (lesson / PART2).is_file() and 'id="next-part"' not in _source(lesson / PAGE)
    monkeypatch.setattr(lp, "_replace", original)
    code, result = _run(capsys, "continue", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID, "--date", "2026-10-26")
    assert code == 0 and result["linked"] == PART2, result
    assert '<a rel="next" href="attn-03-part2.html#node-3">' in _source(lesson / PAGE)
    code, result = _run(capsys, "continue", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID)
    assert code == 2 and "nothing to repair" in result["error"]


def test_runtime_follows_the_lesson_across_pages() -> None:
    template = (ROOT / "assets" / "lesson-template.html").read_text(encoding="utf-8")
    assert '#lp-pager .lp-pager-list > ol > li' in template and ".lp-pager-row" in template
    assert "本页约" in template and "全文约" not in template and "见续篇" not in template


def _split(capsys, lesson: Path, tmp_path: Path, segment: str) -> dict:
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, segment)
    assert code == 2 and "continue in place of add" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, segment)
    assert code == 0, result
    return result


def test_wrapped_nodes_and_rich_titles_carry_over(lesson: Path, tmp_path: Path, capsys) -> None:
    segment = _segment(3, "st-b", 3).replace("第 3 个节点", "<code>flash_attn_varlen_qkvpacked_func</code> 与 <a href=\"#node-1\">节点 1</a>"
                                             '，挂到 <code>&lt;div id="app"&gt;</code>')
    result = _split(capsys, lesson, tmp_path, '<div class="x-wrap">\n' + segment + "</div>\n")
    assert result["check"]["errors"] == [] and result["previous"]["check"]["errors"] == []
    first = _source(lesson / PAGE)
    assert ('从节点 3「<code>flash_attn_varlen_qkvpacked_func</code> 与 节点 1，挂到 <code>&lt;div id="app"&gt;</code>」开始' in first
            and 'href="attn-03-part2.html#node-3"' in first)
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4))
    code, result = _write(capsys, lesson, tmp_path, "continue", PART2, "attn-03-part2", _segment(5, "st-b", 5))
    assert code == 0, result
    assert '<b>3</b><span><code>flash_attn_varlen_qkvpacked_func</code> 与 节点 1，挂到 <code>&lt;div id="app"&gt;</code></span>' in _source(lesson / PART3)


def test_continue_writes_nothing_when_it_cannot_finish(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    page.write_text(_with(_source(page), "<p>导入。</p>", '<p>导入。见<a href="#my-note">我的笔记</a>。</p>'), encoding="utf-8")
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "already fails check" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "nothing was written" in result["error"] and "#my-note" in result["error"], result
    assert not (lesson / PART2).exists()
    page.write_text(_with(_source(page), '见<a href="#my-note">我的笔记</a>。', ""), encoding="utf-8")
    routed = _segment(3, "st-b", 3) + '<template data-lp-into="node-2"><aside class="lp-addendum" id="add-2-1"><h3>补充</h3><p>补。</p></aside></template>'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, routed)
    assert code == 2 and "add those parts here first" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, routed)
    assert code == 2 and "#node-2, which is on attn-03.html" in result["error"] and not (lesson / PART2).exists(), result


def test_split_points_follow_the_skeleton_and_the_lesson(repo: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(lp, "SPLIT_DUE_MINUTES", 2)
    monkeypatch.setattr(lp, "SPLIT_LIMIT_MINUTES", 8)
    code, result = _new(capsys, repo, "--fragment", _fragment(tmp_path, "opening.html", OPENING))
    for n, stages in ((1, "st-a,st-b,st-c"), (2, "st-a")):
        code, result = _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(n, stages, n))
        assert code == 0, result
    # Every station is already open, so a later segment finishes nothing and starts a new page at the due point.
    code, result = _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "continue in place of add" in result["error"], result
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "learning/pages/lesson-3.html", "--id", "attn-04", "--title", "t")
    assert code == 2 and "name the page attn-04.html" in result["error"]
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "learning/pages/qa-softmax.html", "--id", "qa-softmax", "--title", "答疑")
    for n in (1, 2, 3):
        code, result = _write(capsys, repo, tmp_path, "add", "learning/pages/qa-softmax.html", "qa-softmax", _segment(n, "", n))
        assert code == 0, result
    assert "a Q&A page stays one page" in result["note"]
    # A lesson whose id happens to start with qa- has an opening, so it still splits.
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "learning/pages/qa-basics.html", "--id", "qa-basics", "--title", "质量保证",
                        "--fragment", _fragment(tmp_path, "qa-opening.html", OPENING))
    for n, stages in ((1, "st-a"), (2, "st-a"), (3, "st-b")):
        code, result = _write(capsys, repo, tmp_path, "add", "learning/pages/qa-basics.html", "qa-basics", _segment(n, stages, n))
    assert code == 2 and "continue in place of add" in result["error"], result
    monkeypatch.setattr(lp, "MAX_PARTS", 1)
    code, result = _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 0 and "1-page limit" in result["note"], result  # the lesson cannot have another page


def test_new_pages_take_page_one_header_styles_and_current_copies(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    source = _with(_source(page), "<title>分块 softmax · Attention 算子 · 第 3 课</title>", "<title>&amp;lt;tag&amp;gt; · Attention 算子 · 第 3 课</title>")
    source = _with(source, "颜色只用 var(--…) 令牌。 */", "颜色只用 var(--…) 令牌。 */\n.attn-shape { white-space: nowrap; }")
    page.write_text(source, encoding="utf-8")
    style = '<style data-lp-style>\n.x-box { border: 1px solid var(--rule); }\n</style>\n'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, style + '<p class="x-box">框。</p>', "--into", "node-1")
    assert code == 0, result
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    second = _source(lesson / PART2)
    assert "<title>&amp;lt;tag&amp;gt; · Attention 算子 · 第 3 课 · 第 2 页</title>" in second
    assert ".attn-shape { white-space: nowrap; }" in second and ".x-box {" not in second
    # Page 1 changes after the split: a new glossary entry and a corrected one.
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID,
                          '<template data-lp-into="glossary-list"><div id="g-l"><dt>ℓ</dt><dd>指数和。</dd></div></template>')
    assert code == 0, result
    corrected = _with(_source(page), "<dd>每行见过的最大分数。</dd>", "<dd>每行见过的最大分数（已更正）。</dd>")
    page.write_text(_with(corrected, ".attn-shape { white-space: nowrap; }", ".attn-shape { white-space: normal; }"), encoding="utf-8")
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4))
    assert code == 0, result
    segment = (_segment(5, "st-b", 5, extra='  <p class="x-box">框。</p>\n')
               + '<template data-lp-into="glossary-list"><div id="g-l"><dt>ℓ</dt><dd>这一段的写法。</dd></div></template>')
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", segment)
    assert code == 2 and "continue in place of add" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PART2, "attn-03-part2", segment)
    assert code == 0, result
    third = _source(lesson / PART3)
    assert "每行见过的最大分数（已更正）。" in third and "这一段的写法。" in third and third.count('id="g-l"') == 1
    assert third.count(".x-box { border: 1px solid var(--rule); }") == 1
    page_style = re.search(r'<style id="lp-page-style">(.*?)</style>', third, re.S).group(1)
    assert ".attn-shape { white-space: normal; }" in page_style and "nowrap" not in page_style


def test_later_segments_on_a_part_bring_styles_and_links_resolve_like_a_browser(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    style = '<style data-lp-style>\n.x-box { border: 1px solid var(--rule); }\n</style>\n'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, style + '<aside class="lp-addendum x-box" id="add-1-1"><h3>补充</h3><p>见 <code>&lt;section id="recap"&gt;</code>。</p></aside>', "--into", "node-1")
    assert code == 0, result
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2",
                          '<aside class="lp-addendum x-box" id="add-3-1"><h3>补充</h3><p>回看<a href=" #node-1">节点 1</a>和<a href="#node%2D2">节点 2</a>。</p></aside>',
                          "--into", "node-3")
    assert code == 0 and result["carried_styles"] == 1, result
    second = _source(lesson / PART2)
    assert 'href="attn-03.html#node-1"' in second and 'href="attn-03.html#node-2"' in second
    assert second.count(".x-box { border: 1px solid var(--rule); }") == 1
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", '<section class="lp-narrative" id="recap"><h2>前面讲过</h2><p>回顾。</p></section>')
    assert code == 0, result  # id="recap" written as text on page 1 is not an id
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", '<template data-lp-into="node-1"><p>补一句。</p></template>')
    assert code == 2 and "#node-1 is on attn-03.html" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", "<dd>补充。</dd>", "--into", "g-m")
    assert code == 2 and "copy of the entry on attn-03.html" in result["error"], result
    answer = '<div class="lp-answer" id="q-3-ref"><p>要点。</p></div><template data-lp-into="node-1"><p>补一句。</p></template>'
    code, result = _run(capsys, "state", "--repo", str(lesson), "--page", PART2, "--id", "attn-03-part2", "--question", "q-3",
                        "--to", "closed", "--fragment", _fragment(tmp_path, "answer.html", answer))
    assert code == 2 and "#node-1 is on attn-03.html" in result["error"], result
    # A fragment that brings its own copy of an earlier page's style does not get a second copy.
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2",
                          style + '<aside class="lp-addendum x-box" id="add-3-2"><h3>补充</h3><p>框。</p></aside>', "--into", "node-3")
    assert code == 0 and "carried_styles" not in result, result


@needs_node
def test_continue_checks_the_previous_page_scripts_before_writing(lesson: Path, tmp_path: Path, capsys) -> None:
    hook = '<script data-lp-hook>\nvar x = ;\n</script>'
    page = lesson / PAGE
    page.write_text(_with(_source(page), "<p>导入。</p>", "<p>导入。</p>\n" + hook), encoding="utf-8")
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "script.syntax" in result["error"], result
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 2 and "nothing was written" in result["error"] and not (lesson / PART2).exists(), result


def test_continue_brings_an_older_page_one_runtime_up_to_date(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    page.write_text(_with(_source(page), "本页约 ", "全文约 "), encoding="utf-8")
    assert "runtime.drift" in _codes(_source(page), page)
    result = _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    assert "note" not in result["previous"] and "runtime.drift" not in _codes(_source(page), page)


def test_continue_keeps_an_older_generation_runtime_and_says_so(lesson: Path, tmp_path: Path, capsys) -> None:
    page = lesson / PAGE
    page.write_text(_with(_source(page), "lesson-pages runtime v3", "lesson-pages runtime v2"), encoding="utf-8")
    result = _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    assert "全文约" in result["previous"]["note"] and "not linked" in result["previous"]["note"]
    assert "lesson-pages runtime v2" in _source(page)


def test_serve_lists_a_lesson_in_reading_order(lesson: Path, tmp_path: Path, capsys) -> None:
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    server = lp.make_server(lesson / "learning" / "pages", "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/") as response:
            listing = response.read().decode("utf-8")
        assert listing.index("attn-03.html") < listing.index("attn-03-part2.html")
    finally:
        server.shutdown()
        server.server_close()



def test_later_page_rules_titles_and_oversized_segments(lesson: Path, tmp_path: Path, capsys) -> None:
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3, paragraphs=40))
    assert code == 2 and "Write it in smaller segments" in result["error"], result
    title = '<abbr title="页面里 id=app">挂载点</abbr>'
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3).replace("第 3 个节点", title))
    assert f"从节点 3「{title}」开始" in _source(lesson / PAGE)
    second = lesson / PART2
    second.write_text(_with(_source(second), "/* 以上照抄第 1 页 */\n", "/* 以上照抄第 1 页 */\n.part2-rule { color: var(--ink); }\n"),
                      encoding="utf-8")
    style = '<style data-lp-style>\n.x-box { border: 1px solid var(--rule); }\n</style>\n'
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, style + '<p class="x-box">框。</p>', "--into", "node-1")
    assert code == 0, result
    answer = '<div class="lp-answer x-box" id="q-3-ref"><p>要点。</p></div>'
    code, result = _run(capsys, "state", "--repo", str(lesson), "--page", PART2, "--id", "attn-03-part2", "--question", "q-3",
                        "--to", "closed", "--fragment", _fragment(tmp_path, "answer.html", answer))
    assert code == 0 and result["carried_styles"] == 1, result
    assert '<style data-lp-style data-lp-copy="attn-03.html">' in _source(second)
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4))
    code, result = _write(capsys, lesson, tmp_path, "continue", PART2, "attn-03-part2", _segment(5, "st-b", 5, paragraphs=40))
    assert code == 2 and "Write it in smaller segments" in result["error"] and not (lesson / PART3).exists(), result
    code, result = _write(capsys, lesson, tmp_path, "continue", PART2, "attn-03-part2", _segment(5, "st-b", 5))
    assert code == 0, result
    page_style = re.search(r'<style id="lp-page-style">(.*?)</style>', _source(lesson / PART3), re.S).group(1)
    assert page_style.count("以下照抄第 1 页") == 1 and ".part2-rule { color: var(--ink); }" in page_style



def test_links_into_this_machine_are_refused_and_render_repairs_a_stale_directory(lesson: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    for href in ("file:///home/me/pages/attn-02.html", "/home/me/pages/attn-02.html"):
        code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID,
                              f'<aside class="lp-addendum" id="add-1-9"><h3>补充</h3><p>见<a href="{href}">上一课</a>。</p></aside>', "--into", "node-1")
        assert code == 2 and "link.absolute" in result["error"], result
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    original = lp._replace

    def flaky(path: Path, *args, **kwargs):
        if path.name == "attn-03.html":
            raise lp.UsageError("the page changed after it was read")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(lp, "_replace", flaky)
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4, paragraphs=1))
    assert code == 0 and result["directory_stale"][0].startswith(PAGE) and "run render" in result["directory_stale"][0], result
    monkeypatch.setattr(lp, "_replace", original)
    assert "pager.stale" in _codes(_source(lesson / PAGE), lesson / PAGE)
    assert "#node-4" not in _source(lesson / PAGE)
    code, result = _run(capsys, "render", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0 and result["changed"] and 'href="attn-03-part2.html#node-4"' in _source(lesson / PAGE), result



def _pager(source: str) -> str:
    return re.search(r'<nav class="lp-pager" id="lp-pager".*?</nav>', source, re.S).group(0)


@needs_node
def test_directory_titles_bring_their_formula_fonts(lesson: Path, tmp_path: Path, capsys) -> None:
    title = '分块 <span class="tex">\\mathbb{R}^{N \\times d}</span> 的矩阵'
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3).replace("第 3 个节点", title))
    first = _source(lesson / PAGE)
    assert 'id="lp-katex"' in first and "KaTeX_AMS" in first and "katex" in _pager(first)
    assert lp.check_source(first, lesson / PAGE).errors == []


def test_directory_refresh_is_quiet_and_robust(lesson: Path, tmp_path: Path, capsys) -> None:
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    page = lesson / PAGE
    marker = lp.Page(_source(page)).marker().attrs
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(4, "st-b", 4, paragraphs=1))
    assert code == 0 and result["directory_refreshed"] == [PAGE], result
    after = lp.Page(_source(page)).marker().attrs
    assert (after["data-rev"], after["data-updated"]) == (marker["data-rev"], marker["data-updated"])  # only the navigation changed
    # The tool finds its directory by id, whatever the attribute order.
    page.write_text(_with(_source(page), '<nav class="lp-pager" id="lp-pager"', '<nav id="lp-pager" class="lp-pager"'), encoding="utf-8")
    code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2", _segment(5, "st-b", 5, paragraphs=1))
    assert code == 0 and _source(page).count('id="lp-pager"') == 1 and "#node-5" in _source(page), result
    # A hand fix to a title leaves the other pages' directories behind until render runs.
    second = lesson / PART2
    second.write_text(_with(_source(second), "第 4 个节点</h2>", "第 4 个节点（改）</h2>"), encoding="utf-8")
    assert "pager.stale" in _codes(_source(page), page)
    code, result = _run(capsys, "render", "--repo", str(lesson), "--page", PART2, "--id", "attn-03-part2")
    assert code == 0 and result["directory_refreshed"] == [PAGE] and "第 4 个节点（改）" in _pager(_source(page)), result
    # A copy under another name stands alone and never rewrites the real pages.
    copy = page.parent / "attn-03 (1).html"
    copy.write_bytes(page.read_bytes())
    code, result = _run(capsys, "find", "--repo", str(lesson), "--in", "learning/pages", "--lesson", PAGE_ID)
    assert [entry.get("misnamed", False) for entry in result["pages"]][:2] == [False, True] or any(e.get("misnamed") for e in result["pages"])
    before = second.read_bytes()
    code, result = _write(capsys, lesson, tmp_path, "add", "learning/pages/attn-03 (1).html", PAGE_ID,
                          '<aside class="lp-addendum" id="add-1-1"><h3>补充</h3><p>补。</p></aside>', "--into", "node-1")
    assert code == 0 and "directory_refreshed" not in result and second.read_bytes() == before, result
    copy.unlink()
    # A sibling that cannot be read is named.
    second.write_bytes(second.read_bytes().replace(b"</body>", b"<!-- \xb2\xe2 --></body>"))
    code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID, '<aside class="lp-addendum" id="add-1-2"><h3>补充</h3><p>补。</p></aside>', "--into", "node-1")
    assert code == 0 and "attn-03-part2.html is not UTF-8" in result["directory_stale"][0], result


def test_parts_need_their_link_back_and_old_stylesheets_get_directory_styles(repo: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    # A lesson whose id merely ends in -part2 (made before this rule) is not page 2 of another lesson.
    code, result = _run(capsys, "new", "--repo", str(repo), "--page", "learning/pages/linalg.html", "--id", "linalg", "--title", "线代")
    other = repo / "learning" / "pages" / "linalg-part2.html"
    other.write_text((repo / "learning" / "pages" / "linalg.html").read_text(encoding="utf-8").replace('data-id="linalg"', 'data-id="linalg-part2"'),
                     encoding="utf-8")
    code, result = _write(capsys, repo, tmp_path, "add", "learning/pages/linalg.html", "linalg", _segment(1, "", 1, paragraphs=1))
    assert code == 0 and "directory_refreshed" not in result, result
    assert lp._part_of(other, "linalg-part2") == ("linalg-part2", 1)
    # A page whose stylesheet predates the directory gets the directory's styles inside the block.
    monkeypatch.setattr(lp, "SPLIT_DUE_MINUTES", 2)
    monkeypatch.setattr(lp, "SPLIT_LIMIT_MINUTES", 5)
    code, result = _new(capsys, repo, "--fragment", _fragment(tmp_path, "opening.html", OPENING))
    for n, stages in ((1, "st-a"), (2, "st-a")):
        _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(n, stages, n))
    page = repo / PAGE
    page.write_text(re.sub(r"(?m)^\.lp-pager.*\n", "", _source(page)), encoding="utf-8")
    _write(capsys, repo, tmp_path, "add", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    monkeypatch.setattr(lp, "_refresh_runtime", lambda source: None)
    code, result = _write(capsys, repo, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    assert code == 0, result
    assert "<style data-lp-style>\n.lp-pager" in _pager(_source(page)) and "<style data-lp-style>" not in _pager(_source(repo / PART2))


def test_repair_lists_each_page_once_and_machine_links_are_refused(lesson: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    original = lp._replace
    monkeypatch.setattr(lp, "_replace", lambda path, data, text: (_ for _ in ()).throw(lp.UsageError("changed")))
    code, result = _write(capsys, lesson, tmp_path, "continue", PAGE, PAGE_ID, _segment(3, "st-b", 3))
    monkeypatch.setattr(lp, "_replace", original)
    code, result = _run(capsys, "continue", "--repo", str(lesson), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0, result
    assert "第 1 页，共 2 页" in _pager(_source(lesson / PAGE)) and 'rel="next"' not in _pager(_source(lesson / PART2))
    for href in ("C:\\Users\\me\\attn-02.html", "C:/Users/me/attn-02.html", "\\\\server\\share\\attn-02.html", "//server/share/attn-02.html"):
        code, result = _write(capsys, lesson, tmp_path, "add", PAGE, PAGE_ID,
                              f'<aside class="lp-addendum" id="add-1-8"><h3>补充</h3><p>见<a href="{href}">上一课</a>。</p></aside>', "--into", "node-1")
        assert code == 2 and "link.absolute" in result["error"], (href, result)


def test_render_keeps_the_revision_for_the_directory_and_copies_never_continue(lesson: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    _split(capsys, lesson, tmp_path, _segment(3, "st-b", 3))
    page, second = lesson / PAGE, lesson / PART2
    second.write_text(_with(_source(second), "第 3 个节点</h2>", "第 3 个节点（改）</h2>"), encoding="utf-8")
    marker = lp.Page(_source(second)).marker().attrs
    code, result = _run(capsys, "render", "--repo", str(lesson), "--page", PART2, "--id", "attn-03-part2")
    after = lp.Page(_source(second)).marker().attrs
    assert code == 0 and result["changed"] and (after["data-rev"], after["data-updated"]) == (marker["data-rev"], marker["data-updated"]), result
    assert "第 3 个节点（改）" in _pager(_source(page))
    copy = second.parent / "attn-03-part2 (1).html"
    copy.write_bytes(second.read_bytes())
    code, result = _write(capsys, lesson, tmp_path, "continue", "learning/pages/attn-03-part2 (1).html", "attn-03-part2", _segment(4, "st-b", 4))
    assert code == 2 and "is a copy under another name" in result["error"], result
    copy.unlink()
    for markup in ('<img alt="图" srcset="/home/me/x.png 2x">', '<video poster="C:/Users/me/p.png"></video>',
                   '<svg role="img" aria-label="图" viewBox="0 0 10 10"><image href="/home/me/x.png" width="10" height="10"/></svg>'):
        code, result = _write(capsys, lesson, tmp_path, "add", PART2, "attn-03-part2",
                              f'<aside class="lp-addendum" id="add-3-9"><h3>补充</h3><p>图。</p>{markup}</aside>', "--into", "node-3")
        assert code == 2 and "link.absolute" in result["error"], (markup, result)


# Reusable source browsers, causal timelines and registration-hook placement.
def test_add_moves_hooks_out_of_content_and_keeps_registration_order(built: Path, tmp_path: Path, capsys) -> None:
    original_hooks = [node.text() for node in lp.Page(_source(built)).find("script") if "data-lp-hook" in node.attrs]
    first = '<script data-lp-hook id="hook-first">LessonPage.onStep["fig-x"] = function () {};</script>'
    code, result = _add(capsys, built, tmp_path, first, "--into", "node-1")
    assert code == 0, result
    second = '<script data-lp-hook id="hook-second">LessonPage.onStep["fig-9-8"] = function () {};</script>'
    fragment = ('<div class="lp-addendum" id="add-1-9"><h3>补充</h3>'
                '<figure id="fig-9-8"><p>一张图。</p><figcaption>图9.8</figcaption></figure>'
                + second + '<aside class="lp-note" id="note-9" data-note-for="fig-9-8">来源。</aside></div>')
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-1")
    assert code == 0 and result["check"]["warnings"] == [], result
    text, parsed = _source(built), lp.Page(_source(built))
    hooks = [node for node in parsed.find("script") if "data-lp-hook" in node.attrs]
    assert [node.text() for node in hooks[:len(original_hooks)]] == original_hooks
    assert [node.attrs.get("id") for node in hooks[len(original_hooks):]] == ["hook-first", "hook-second"]
    runtime = parsed.one("lp-runtime")
    assert runtime is not None
    assert all(not any(parent.tag == "main" for parent in node.ancestors()) and node.start < runtime.start for node in hooks)
    note = parsed.one("note-9")
    assert note is not None and note.parent is not None
    assert note.parent.children[note.parent.children.index(note) - 1].attrs.get("id") == "fig-9-8"
    assert first in text and second in text
    assert lp._ensure_packs(text) == text
    assert lp._ensure_packs(text.replace("\n", "\r\n")) == text.replace("\n", "\r\n")


def test_render_repairs_legacy_hook_placement_without_changing_hook_or_content(built: Path, tmp_path: Path, capsys) -> None:
    _add(capsys, built, tmp_path, MYTH)
    hook = '<script data-lp-hook id="legacy-hook">LessonPage.onStep["legacy"] = function () { return 1; };</script>'
    original = _source(built)
    legacy = _with(original, lp.APPEND_MARKER, hook + '\n' + lp.APPEND_MARKER)
    built.write_text(legacy, encoding="utf-8")
    assert "script.placement" in _codes(legacy, built)
    code, result = _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0 and result["changed"], result
    repaired = _source(built)
    assert hook in repaired and "script.placement" not in _codes(repaired, built)
    assert repaired.index('id="legacy-hook"') < repaired.index('id="lp-pack-myth-js"') < repaired.index('id="lp-runtime"')
    assert lp._visible_text(lp.Page(repaired).find("main")[0]).split() == lp._visible_text(lp.Page(legacy).find("main")[0]).split()
    code, repeat = _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0 and not repeat["changed"] and _source(built) == repaired


@pytest.mark.parametrize("target", ["missing", "lp-runtime", "q-1"])
def test_note_explicit_target_is_an_earlier_content_element(built: Path, tmp_path: Path, capsys, target: str) -> None:
    fragment = f'<aside class="lp-note" data-note-for="{target}">来源。</aside>'
    before = built.read_bytes()
    code, result = _add(capsys, built, tmp_path, fragment, "--into", "node-1")
    assert code == 2 and "note.target" in result["error"], result
    assert built.read_bytes() == before


@pytest.mark.parametrize("example,pack", [("example-source-tree.html", "source-tree"), ("example-timeline.html", "timeline")])
def test_declarative_examples_build_and_stay_stable(built: Path, capsys, example: str, pack: str) -> None:
    original_hooks = [node.text() for node in lp.Page(_source(built)).find("script") if "data-lp-hook" in node.attrs]
    code, result = _run(capsys, "add", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID,
                        "--fragment", str(REFERENCES / example))
    assert code == 0 and result["check"]["warnings"] == [], result
    text = _source(built)
    assert lp.outline_source(text)["packs"] == [pack]
    assert [node.text() for node in lp.Page(text).find("script") if "data-lp-hook" in node.attrs] == original_hooks
    assert lp._ensure_packs(text) == text
    code, repeated = _run(capsys, "render", "--repo", str(built.parents[2]), "--page", PAGE, "--id", PAGE_ID)
    assert code == 0 and not repeated["changed"] and _source(built) == text


@pytest.mark.parametrize(
    "old,new",
    [
        ('data-start="lp-tree-json-api"', 'data-start="lp-tree-lua-api"'),
        ('data-path="Lib/json/decoder.py"', 'data-path="elsewhere/decoder.py"'),
        ('data-path="Objects"', 'data-path="../Objects"'),
        ('data-kind="context"', 'data-kind="unknown"'),
        ('class="lp-source-version"', 'class="version-missing"'),
        ('class="lp-source-links"', 'class="links-missing"'),
    ],
)
def test_source_browser_rejects_inconsistent_ownership_and_links(built: Path, tmp_path: Path, capsys, old: str, new: str) -> None:
    fragment = (REFERENCES / "example-source-tree.html").read_text(encoding="utf-8")
    assert old in fragment
    before = built.read_bytes()
    code, result = _add(capsys, built, tmp_path, fragment.replace(old, new, 1))
    assert code == 2 and "pack.markup" in result["error"], result
    assert built.read_bytes() == before


@pytest.mark.parametrize("mutation", ["missing-cell", "duplicate-cell", "renamed-actor", "unknown-state", "no-kind", "no-dependency"])
def test_timeline_requires_complete_consistent_snapshots(built: Path, tmp_path: Path, capsys, mutation: str) -> None:
    fragment = (REFERENCES / "example-timeline.html").read_text(encoding="utf-8")
    parsed = lp.Page(fragment)
    timeline = parsed.one("fig-5-1")
    assert timeline is not None
    steps = next(node for node in timeline.children if "lp-steps" in node.classes).children
    second = steps[1]
    state = next(node for node in second.children if "lp-timeline-state" in node.classes)
    cell = state.children[0]
    if mutation == "missing-cell":
        fragment = fragment[:cell.start] + fragment[cell.end:]
    elif mutation == "duplicate-cell":
        fragment = fragment[:cell.end] + fragment[cell.start:cell.end] + fragment[cell.end:]
    elif mutation == "renamed-actor":
        owner = next(node for node in cell.children if "lp-timeline-owner" in node.classes)
        fragment = fragment[:owner.start_end] + "不同的参与者" + fragment[owner.end_start:]
    elif mutation == "unknown-state":
        fragment = fragment.replace('data-status="ready"', 'data-status="guessing"', 1)
    elif mutation == "no-kind":
        fragment = fragment.replace('data-timeline-kind="model"', '', 2)
    else:
        dependency = next(node for node in second.children if "lp-timeline-dependency" in node.classes)
        fragment = fragment[:dependency.start] + fragment[dependency.end:]
    before = built.read_bytes()
    code, result = _add(capsys, built, tmp_path, fragment)
    assert code == 2 and "pack.markup" in result["error"], result
    assert built.read_bytes() == before


@pytest.mark.parametrize("example", ["example-source-tree.html", "example-timeline.html"])
def test_new_widgets_respect_open_question_boundaries(built: Path, tmp_path: Path, capsys, example: str) -> None:
    source = (REFERENCES / example).read_text(encoding="utf-8")
    figure = lp.Page(source).find("figure")[0]
    fragment = source[figure.start:figure.end]
    code, result = _add(capsys, built, tmp_path, fragment, "--after", "q-1")
    assert code == 2 and "check.leak" in result["error"], result
