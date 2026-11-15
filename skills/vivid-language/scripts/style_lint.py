#!/usr/bin/env python3
"""Heuristic style signals for technical prose.

This is a signal detector, not a grader. It deliberately avoids a single
"style score" so that agents and authors do not optimize for a number.

Usage:
    python style_lint.py draft.md
    python style_lint.py --json draft.md
    cat draft.md | python style_lint.py -
    python style_lint.py --terms "缓存,索引" draft.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s*.*$")
BLOCKQUOTE_RE = re.compile(r"(?m)^>\s?")
LIST_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+")
EMPHASIS_RE = re.compile(r"[*_~]{1,2}")
HTML_TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+|(?<=[.])\s+(?=[A-Z])")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")

NOMINALIZATION_RE = re.compile(
    r"(?:进行|加以|予以|实现|完成|得到|作出|给予)"
    r"(?:了|一个|一次|进一步|全面|有效|持续|相关|必要)?"
    r"(?![上下中里外后前时])"
    r"[\u4e00-\u9fff]{2,10}"
)
PASSIVE_RE = re.compile(
    r"(?:被[\u4e00-\u9fff]{1,8}(?:了|所)?"
    r"|受到[\u4e00-\u9fff]{1,8}"
    r"|遭到[\u4e00-\u9fff]{1,8}"
    r"|被认为|可以看出|可以发现|由此可见)"
)
FILLER_RE = re.compile(
    r"此外|然而|值得注意的是|综上所述|众所周知|总而言之|"
    r"在一定程度上|相对来说|从某种意义上说|需要指出的是"
)
HEDGE_RE = re.compile(
    r"可能|或许|也许|大概|似乎|一定程度上|在某种意义上|基本上|一般来说"
)
ABSTRACT_SUFFIX_RE = re.compile(r"[\u4e00-\u9fff]{1,4}(?:性|化|度)")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
NUMBER_WITH_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:ms|毫秒|秒|分钟|小时|天|年|万|亿|GB|MB|KB|倍|%|行|台|次)"
)


def strip_markdown(text: str) -> str:
    """Remove markup that should not affect prose signals."""

    text = FENCED_CODE_RE.sub("\n\n", text)
    text = INLINE_CODE_RE.sub("", text)
    text = IMAGE_RE.sub("", text)
    text = LINK_RE.sub(r"\1", text)
    text = URL_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    text = HEADING_RE.sub("", text)
    text = BLOCKQUOTE_RE.sub("", text)
    text = LIST_RE.sub("", text)
    text = EMPHASIS_RE.sub("", text)
    return text


def split_sentences(text: str) -> list[str]:
    """Split Chinese and simple English prose into sentences."""

    parts = SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    for part in parts:
        if part is None:
            continue
        sentence = part.strip()
        if not sentence:
            continue
        if CJK_RE.search(sentence) or WORD_RE.search(sentence):
            sentences.append(sentence)
    return sentences


def _cjk_length(text: str) -> int:
    return len(CJK_RE.findall(text))


def _word_length(text: str) -> int:
    return len(WORD_RE.findall(text))


def _unique_examples(matches: list[str], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    examples: list[str] = []
    for match in matches:
        value = match.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        examples.append(value[:40])
        if len(examples) >= limit:
            break
    return examples


def _signal(matches: list[str], chinese_chars: int) -> dict[str, Any]:
    count = len(matches)
    return {
        "count": count,
        "per_1000_chars": round(count * 1000 / max(chinese_chars, 1), 1),
        "examples": _unique_examples(matches),
    }


def analyze_text(
    text: str,
    *,
    path: str = "<text>",
    max_sentence_chars: int = 45,
    terms: list[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic style signals for *text*."""

    clean = strip_markdown(text)
    chinese_chars = _cjk_length(clean)
    sentences = split_sentences(clean)
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", clean)
        if paragraph.strip()
        and (CJK_RE.search(paragraph) or WORD_RE.search(paragraph))
    ]

    sentence_rows: list[dict[str, Any]] = []
    long_sentences: list[dict[str, Any]] = []
    for sentence in sentences:
        cjk = _cjk_length(sentence)
        words = _word_length(sentence)
        sentence_rows.append({"text": sentence, "chars": cjk, "words": words})
        if cjk > max_sentence_chars or (cjk == 0 and words > 40):
            long_sentences.append(
                {"text": sentence[:120], "chars": cjk, "words": words}
            )

    cjk_lengths = [row["chars"] for row in sentence_rows if row["chars"] > 0]
    avg_sentence = (
        round(sum(cjk_lengths) / len(cjk_lengths), 1) if cjk_lengths else 0.0
    )
    max_sentence = max(cjk_lengths) if cjk_lengths else 0

    nominalization = NOMINALIZATION_RE.findall(clean)
    passive = PASSIVE_RE.findall(clean)
    filler = FILLER_RE.findall(clean)
    hedge = HEDGE_RE.findall(clean)
    abstract_suffix = ABSTRACT_SUFFIX_RE.findall(clean)
    numbers = NUMBER_RE.findall(clean)
    numbers_with_unit = NUMBER_WITH_UNIT_RE.findall(clean)

    term_hits: dict[str, int] = {}
    if terms:
        for term in terms:
            if term:
                term_hits[term] = clean.count(term)

    long_ratio = round(len(long_sentences) / max(len(sentences), 1), 2)
    notes: list[str] = [
        "这些是信号，不是评分；技术文档、规范、论文可能合理地使用更多名词化和被动。"
    ]
    if nominalization and len(nominalization) >= 3:
        notes.append("名词化偏多：先挑最像“进行了……”的三处，改成“谁 + 动词 + 结果”。")
    if passive and len(passive) >= 3:
        notes.append("被动偏多：确认施事者是否可以说出来；能说就改成主动。")
    if filler:
        notes.append("有套话连接词：先删掉，再看逻辑是否还需要保留。")
    if len(long_sentences) >= 3 and long_ratio >= 0.25:
        notes.append(
            f"长句偏多（{len(long_sentences)} 句超过 {max_sentence_chars} 字）：先断句，再改词。"
        )
    if not numbers:
        notes.append("没有具体数字：确认这篇文章是否真的不需要可验证的量。")
    elif not numbers_with_unit:
        notes.append("有数字但没有单位：给数字补上单位或比较对象，读者才能感知大小。")
    second_person = len(re.findall(r"你|您", clean))
    first_person = len(re.findall(r"我们|我", clean))
    if second_person == 0 and first_person == 0:
        notes.append("没有第一/第二人称：如果体裁允许，考虑让作者或读者在场。")
    if len(abstract_suffix) >= 8 and chinese_chars:
        density = len(abstract_suffix) * 1000 / chinese_chars
        if density > 12:
            notes.append("抽象后缀（性/化/度）密度偏高：看看能否换成具体结果。")
    questions = len(re.findall(r"[？?]", clean))
    if questions == 0 and len(sentences) >= 8:
        notes.append("没有问句：如果文章需要悬念，可以考虑“先问后答”。")

    report: dict[str, Any] = {
        "path": path,
        "chars": len(text),
        "chinese_chars": chinese_chars,
        "sentences": len(sentences),
        "paragraphs": len(paragraphs),
        "avg_sentence_chars": avg_sentence,
        "max_sentence_chars": max_sentence,
        "long_sentence_count": len(long_sentences),
        "long_sentence_ratio": long_ratio,
        "long_sentence_threshold": max_sentence_chars,
        "long_sentences": long_sentences[:8],
        "signals": {
            "nominalization": _signal(nominalization, chinese_chars),
            "passive": _signal(passive, chinese_chars),
            "filler": _signal(filler, chinese_chars),
            "hedge": _signal(hedge, chinese_chars),
            "abstract_suffix": _signal(abstract_suffix, chinese_chars),
        },
        "concreteness": {
            "numbers": len(numbers),
            "numbers_with_units": len(numbers_with_unit),
            "numbers_per_1000_chars": round(
                len(numbers) * 1000 / max(chinese_chars, 1), 1
            ),
        },
        "person": {"second": second_person, "first": first_person},
        "questions": questions,
        "terms": None,
        "notes": notes,
    }
    if terms:
        total_hits = sum(term_hits.values())
        report["terms"] = {
            "provided": terms,
            "hits": term_hits,
            "per_1000_chars": round(total_hits * 1000 / max(chinese_chars, 1), 1),
        }
        if total_hits and total_hits * 1000 / max(chinese_chars, 1) > 25:
            notes.append("术语密度偏高：确认读者是否已经知道这些词，必要时先给经验再给名字。")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report as readable Markdown."""

    threshold = report["long_sentence_threshold"]
    lines = [
        "# Style signals",
        "",
        f"- 来源：`{report['path']}`",
        f"- 字符：{report['chars']}（中文 {report['chinese_chars']}）",
        (
            f"- 句子：{report['sentences']}；平均 {report['avg_sentence_chars']} 字；"
            f"最长 {report['max_sentence_chars']} 字"
        ),
        f"- 段落：{report['paragraphs']}",
        (
            f"- 长句（>{threshold} 字）："
            f"{report['long_sentence_count']}（{report['long_sentence_ratio']:.0%}）"
        ),
        "",
        "## 信号",
        "",
        "| 信号 | 次数 | 每千字 | 例子 |",
        "|---|---:|---:|---|",
    ]
    labels = {
        "nominalization": "名词化",
        "passive": "被动",
        "filler": "套话连接词",
        "hedge": "模糊限定",
        "abstract_suffix": "抽象后缀（性/化/度）",
    }
    for key, label in labels.items():
        item = report["signals"][key]
        examples = "、".join(item["examples"]) if item["examples"] else "—"
        lines.append(
            f"| {label} | {item['count']} | {item['per_1000_chars']} | {examples} |"
        )

    lines.extend(
        [
            "",
            "## 具体度与人称",
            "",
            (
                f"- 数字：{report['concreteness']['numbers']}"
                f"（带单位 {report['concreteness']['numbers_with_units']}）"
            ),
            (
                f"- 第二人称：{report['person']['second']}；"
                f"第一人称：{report['person']['first']}；"
                f"问句：{report['questions']}"
            ),
        ]
    )
    if report["terms"]:
        term_text = "、".join(
            f"{term}×{count}"
            for term, count in report["terms"]["hits"].items()
            if count
        )
        lines.append(
            f"- 术语：{term_text or '—'}"
            f"（每千字 {report['terms']['per_1000_chars']}）"
        )

    lines.extend(["", "## 建议", ""])
    for note in report["notes"]:
        lines.append(f"- {note}")

    if report["long_sentences"]:
        lines.extend(["", "## 长句示例", ""])
        for index, item in enumerate(report["long_sentences"], 1):
            lines.append(f"{index}. （{item['chars']} 字）{item['text']}")

    lines.append("")
    return "\n".join(lines)


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report heuristic style signals for technical prose."
    )
    parser.add_argument("path", nargs="?", default="-", help="UTF-8 file or - for stdin")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--max-sentence",
        type=int,
        default=45,
        help="long-sentence threshold in Chinese characters (default: 45)",
    )
    parser.add_argument(
        "--terms",
        default="",
        help="comma-separated terms to count (for example: 缓存,索引)",
    )
    args = parser.parse_args(argv)

    if args.max_sentence < 1:
        print("--max-sentence must be a positive integer", file=sys.stderr)
        return 2
    terms = [item.strip() for item in args.terms.split(",") if item.strip()]
    try:
        text = _read_input(args.path)
    except FileNotFoundError:
        print(f"file not found: {args.path}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"file is not valid UTF-8: {args.path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"cannot read {args.path}: {exc}", file=sys.stderr)
        return 2

    report = analyze_text(
        text,
        path=args.path,
        max_sentence_chars=args.max_sentence,
        terms=terms or None,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
