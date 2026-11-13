from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "style_lint.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import style_lint  # noqa: E402


TEXTBOOK = """# 缓存一致性

缓存一致性是指在多核处理器系统中，多个处理核心的私有缓存之间保持数据一致性的机制。当某一核心对其私有缓存中的数据进行修改时，需要通过总线嗅探或目录协议等方式通知其他核心，以保证系统对外表现出单一共享存储器的语义。该机制具有较高的复杂性，因此需要进行充分的设计与验证。此外，值得注意的是，不同处理器架构在实现上存在差异。
"""

CONCRETE = """# 凌晨两点的缓存

凌晨两点，告警群响了。核心 A 把变量 x 改成了 1，核心 B 的缓存里还躺着 x=0。如果 B 现在去读，它该读到什么？

读 0，程序就疯了；读 1，B 怎么知道 A 改过？我们查了 3 天，最后发现是缓存没同步。缓存一致性协议就是干这个的：谁改了数据，得喊一嗓子，让别人的副本作废。
"""


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def test_textbook_style_is_flagged() -> None:
    report = style_lint.analyze_text(TEXTBOOK, path="textbook.md")
    assert report["chinese_chars"] > 100
    assert report["signals"]["nominalization"]["count"] >= 2
    assert report["signals"]["filler"]["count"] >= 1
    assert report["long_sentence_count"] >= 1
    assert report["concreteness"]["numbers"] == 0
    notes = "\n".join(report["notes"])
    assert "名词化" in notes
    assert "没有具体数字" in notes


def test_concrete_style_has_numbers_people_and_questions() -> None:
    report = style_lint.analyze_text(CONCRETE, path="concrete.md")
    assert report["concreteness"]["numbers"] >= 3
    assert report["concreteness"]["numbers_with_units"] >= 1
    assert report["questions"] >= 1
    assert report["long_sentence_count"] == 0
    assert report["avg_sentence_chars"] < 25


def test_code_blocks_and_inline_code_are_ignored() -> None:
    text = """# 标题

真正的正文只有这一句。

```python
# 这里进行了优化，也实现了提升
def f():
    pass
```
"""
    report = style_lint.analyze_text(text, path="code.md")
    assert report["signals"]["nominalization"]["count"] == 0
    assert report["sentences"] == 1


def test_headings_are_not_counted_as_sentences() -> None:
    text = "# 一个很长的标题\n\n正文只有一句话。\n"
    report = style_lint.analyze_text(text, path="heading.md")
    assert report["sentences"] == 1


def test_inline_code_only_text_has_no_sentences() -> None:
    report = style_lint.analyze_text("`对系统进行了优化`", path="inline.md")
    assert report["sentences"] == 0
    assert report["signals"]["nominalization"]["count"] == 0


def test_links_keep_their_label_but_not_the_url() -> None:
    text = "你可以看[缓存入门](https://example.com/a?b=1)，它讲得很清楚。"
    cleaned = style_lint.strip_markdown(text)
    assert "缓存入门" in cleaned
    assert "example.com" not in cleaned


def test_terms_are_counted() -> None:
    report = style_lint.analyze_text(
        "缓存很重要。索引也很重要。缓存和索引不是一回事。",
        path="terms.md",
        terms=["缓存", "索引"],
    )
    assert report["terms"]["hits"] == {"缓存": 2, "索引": 2}


def test_json_cli(tmp_path: Path) -> None:
    path = tmp_path / "draft.md"
    path.write_text(CONCRETE, encoding="utf-8")
    result = _run("--json", str(path))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["path"] == str(path)
    assert report["long_sentence_threshold"] == 45
    assert report["person"]["first"] >= 1


def test_stdin_cli() -> None:
    result = _run("--json", "-", stdin="我们进行了优化。\n")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["signals"]["nominalization"]["count"] == 1
    assert report["path"] == "-"


def test_missing_file_returns_2(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "missing.md"))
    assert result.returncode == 2
    assert "file not found" in result.stderr


def test_empty_text_does_not_crash() -> None:
    report = style_lint.analyze_text("", path="empty.md")
    assert report["chinese_chars"] == 0
    assert report["sentences"] == 0
    assert report["long_sentence_count"] == 0


def test_markdown_render_contains_signal_table() -> None:
    report = style_lint.analyze_text(TEXTBOOK, path="textbook.md")
    rendered = style_lint.render_markdown(report)
    assert "# Style signals" in rendered
    assert "| 名词化 |" in rendered
    assert "## 建议" in rendered
    assert "## 长句示例" in rendered
