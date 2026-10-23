from __future__ import annotations

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

