#!/usr/bin/env python3
"""Create, extend, check, find and serve lesson pages.

A lesson page is a derived reading surface for a guide-learning lesson. This
tool never decides what to teach and never records progress, evidence or
mastery. Every write touches only the one page named on the command line,
refuses symbolic links, refuses to produce a page that fails ``check``, and
refuses to replace a page that changed after it was read. Nothing is staged,
committed or published.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import functools
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_ROOT / "assets" / "lesson-template.html"
MARKER_NAME = "lesson-pages"
MARKER_VERSION = "v1"
APPEND_MARKER = "<!-- lp:append -->"
CONTENT_MARKER = "<!-- lp:content -->"
SLOT_NAMES = ("lang", "id", "key", "date", "title_full", "title", "crumb", "spine", "sources")
TEMPLATE_SLOTS = tuple("{{lp:" + name + "}}" for name in SLOT_NAMES)
SLOT_PATTERN = re.compile(r"\{\{lp:(" + "|".join(SLOT_NAMES) + r")\}\}")
MAX_PAGE_BYTES = 2 * 1024 * 1024
SOFT_PAGE_BYTES = 400 * 1024
MAX_FRAGMENT_BYTES = 256 * 1024
MAX_FIND_BYTES = 4 * 1024 * 1024
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ELEMENT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
REV_PATTERN = re.compile(r"[0-9]{1,9}")
LANG_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
QUESTION_STATES = ("open", "answered", "replaced", "closed")
TRANSITIONS = {
    ("open", "answered"), ("open", "closed"), ("open", "replaced"),
    ("answered", "closed"), ("answered", "replaced"),
}
WAITING_STATES = frozenset({"open", "answered", "replaced"})
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta source track wbr".split()
)
CLOSES_P = frozenset(
    "address article aside blockquote center details dd dialog dir div dl dt fieldset figcaption figure footer "
    "form h1 h2 h3 h4 h5 h6 header hgroup hr li listing main menu nav ol p plaintext pre search section summary "
    "table ul xmp".split()
)
# HTML start tags that end SVG or MathML content in browsers (outside integration points).
FOREIGN_BREAKOUT = frozenset(
    "b big blockquote body br center code dd div dl dt em embed h1 h2 h3 h4 h5 h6 head hr i img li listing "
    "menu meta nobr ol p pre ruby s small span strike strong sub sup table tt u ul var".split()
)
INTEGRATION_POINTS = frozenset({"foreignobject", "desc", "title", "mi", "mo", "mn", "ms", "mtext"})
# Elements an implied </li>, </dt> or </dd> may close through; anything else special stops the search.
IMPLIED_CLOSE_THROUGH = frozenset("address div p".split())
SPECIAL_STOPS = frozenset(
    "applet article aside blockquote body button caption center details dialog dir dl fieldset figcaption figure "
    "footer form header hgroup html main marquee menu nav object ol section table td template th ul".split()
)
OPTIONAL_END_TAGS = frozenset(
    "p li dt dd option optgroup tr td th thead tbody tfoot colgroup caption rb rt rtc rp html head body".split()
)
EXPLICIT_END_TAGS = frozenset(
    "section div figure aside footer header details main nav article blockquote dl ol ul".split()
)
FORBIDDEN_TAGS = frozenset("base embed frame frameset iframe object".split())
FRAGMENT_FORBIDDEN_TAGS = FORBIDDEN_TAGS | frozenset("html head body meta link title".split())
WIDGET_CLASSES = frozenset({"lp-stepper", "lp-explorer", "lp-toggle", "lp-timer"})
CONTROL_TAGS = frozenset({"input", "select", "textarea", "button"})
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F000-\U0001F2FF]"
)
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:; "
    "font-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'"
)
COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color)\(")
PAINT_KEYWORDS = frozenset({"currentcolor", "none", "transparent", "inherit", "initial", "unset", "revert",
                            "context-fill", "context-stroke"})
PROTECTED_PARTS = frozenset({".git", ".agents", ".claude"})
EXTERNAL_URL = re.compile(r"^\s*(?:[a-zA-Z][a-zA-Z0-9+.-]*:)?//")
RENDERER = SKILL_ROOT / "scripts" / "render.cjs"
KATEX_DIR = SKILL_ROOT / "assets" / "vendor" / "katex"
KATEX_STYLE_ID = "lp-katex"
KATEX_VERSION = "0.19.0"
SCOPE_BOUNDARIES = frozenset("applet button caption html marquee object table td template th".split())
TEX_EXCLUDED_CONTEXTS = frozenset({"svg", "math", "pre", "code", "script", "style"})
SYMBOL_MAP = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=[1-4](?:\s+[A-Za-z_][A-Za-z0-9_]*=[1-4])*")
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)|@import\s+['\"]([^'\"]+)['\"]", re.I)


class UsageError(ValueError):
    """Arguments, paths or preconditions are invalid; nothing was written."""


# --------------------------------------------------------------------------
# HTML model
# --------------------------------------------------------------------------


class Element:
    __slots__ = ("tag", "attrs", "start", "start_end", "end_start", "end", "children",
                 "parent", "chunks", "line", "implicit", "duplicates", "self_closed")

    def __init__(self, tag: str, attrs: dict[str, str], start: int, start_end: int,
                 line: int, parent: "Element | None"):
        self.tag = tag
        self.attrs = attrs
        self.start = start
        self.start_end = start_end
        self.end_start: int | None = None
        self.end: int | None = None
        self.children: list[Element] = []
        self.parent = parent
        self.chunks: list[str | Element] = []
        self.line = line
        self.implicit = False
        self.duplicates: list[str] = []
        self.self_closed = False

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts: list[str] = []
        stack: list[str | Element] = list(reversed(self.chunks))
        while stack:
            chunk = stack.pop()
            if isinstance(chunk, Element):
                stack.extend(reversed(chunk.chunks))
            else:
                parts.append(chunk)
        return "".join(parts)

    def iter(self) -> Iterable["Element"]:
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def ancestors(self) -> Iterable["Element"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


FOREIGN_ROOTS = frozenset({"svg", "math"})


class _Builder(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0]
        for match in re.finditer("\n", source):
            self.line_starts.append(match.end())
        self.root = Element("#root", {}, 0, 0, 1, None)
        self.stack = [self.root]
        self.doctype = False
        self.stray_end_tags: list[tuple[str, int]] = []
        self.misnested: list[tuple[str, int]] = []
        self.breakouts: list[tuple[str, int]] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def _close_until(self, tag: str, offset: int, end: int) -> bool:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                for node in self.stack[index + 1:]:
                    node.end_start = node.end_start or offset
                    node.end = node.end or offset
                    node.implicit = True
                element = self.stack[index]
                element.end_start = offset
                element.end = end
                del self.stack[index:]
                return True
        return False

    def _foreign(self) -> bool:
        return any(node.tag in FOREIGN_ROOTS for node in self.stack[1:])

    def _integration_point(self) -> bool:
        """True when the innermost foreign ancestor lets HTML content in (foreignObject, mtext, …)."""
        for node in reversed(self.stack[1:]):
            if node.tag in INTEGRATION_POINTS:
                return True
            if node.tag == "annotation-xml":
                return node.attrs.get("encoding", "").lower() in {"text/html", "application/xhtml+xml"}
            if node.tag in FOREIGN_ROOTS:
                return False
        return False

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() == "doctype html":
            self.doctype = True

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        start = self._offset()
        text = self.get_starttag_text() or ""
        line = self.getpos()[0]
        if self._foreign() and tag in FOREIGN_BREAKOUT and not self._integration_point():
            self.breakouts.append((tag, line))
        if tag == "li" or tag in {"dt", "dd"}:
            # An implied </li> (or </dt>, </dd>) closes through an open <p> or <div>, as browsers do.
            targets = {"li"} if tag == "li" else {"dt", "dd"}
            for node in reversed(self.stack[1:]):
                if node.tag in targets:
                    self._close_until(node.tag, start, start)
                    break
                if node.tag in SPECIAL_STOPS or node.tag in FOREIGN_ROOTS or (
                        node.tag not in IMPLIED_CLOSE_THROUGH and node.tag in CLOSES_P):
                    break
        if tag in CLOSES_P and self.stack[-1].tag == "p":
            self._close_until("p", start, start)
        elif tag in CLOSES_P:
            # Browsers close a <p> in button scope here and rebuild the inline wrappers around this block.
            for node in reversed(self.stack[1:]):
                if node.tag == "p":
                    self.misnested.append((tag, line))
                    break
                if node.tag in SCOPE_BOUNDARIES or node.tag in FOREIGN_ROOTS:
                    break
        values: dict[str, str] = {}
        duplicates: list[str] = []
        for key, value in attrs:
            if key in values:
                duplicates.append(key)
            else:
                values[key] = value or ""
        parent = self.stack[-1]
        element = Element(tag, values, start, start + len(text), line, parent)
        element.duplicates = duplicates
        parent.children.append(element)
        parent.chunks.append(element)
        # Browsers honour "/>" only on void elements and inside SVG or MathML.
        closes = tag in VOID_TAGS or (self_closing and (self._foreign() or tag in FOREIGN_ROOTS))
        element.self_closed = self_closing and tag not in VOID_TAGS
        if closes:
            element.end_start = element.start_end
            element.end = element.start_end
        else:
            self.stack.append(element)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        start = self._offset()
        close = self.source.find(">", start)
        end = close + 1 if close >= 0 else len(self.source)
        if not self._close_until(tag, start, end):
            self.stray_end_tags.append((tag, self.getpos()[0]))

    def handle_data(self, data: str) -> None:
        self.stack[-1].chunks.append(data)


class Page:
    def __init__(self, source: str):
        self.source = source
        builder = _Builder(source)
        builder.feed(source)
        builder.close()
        for node in builder.stack[1:]:
            node.implicit = True
        self.root = builder.root
        self.stray_end_tags = builder.stray_end_tags
        self.misnested = builder.misnested
        self.breakouts = builder.breakouts
        self.bogus_comment = bool(re.search(r"<!--(?:>|->)", source))
        self.doctype = builder.doctype
        self.elements = list(self.root.iter())
        self.by_id: dict[str, list[Element]] = {}
        for element in self.elements:
            if "id" in element.attrs:
                self.by_id.setdefault(element.attrs["id"], []).append(element)

    def find(self, tag: str | None = None, cls: str | None = None,
             scope: Element | None = None) -> list[Element]:
        nodes = scope.iter() if scope is not None else self.elements
        return [
            node for node in nodes
            if (tag is None or node.tag == tag) and (cls is None or cls in node.classes)
        ]

    def one(self, element_id: str) -> Element | None:
        found = self.by_id.get(element_id, [])
        return found[0] if len(found) == 1 else None

    def unclosed(self) -> list[Element]:
        """Elements whose end tag is missing although HTML requires it."""
        return [
            node for node in self.elements
            if node.implicit and node.tag not in OPTIONAL_END_TAGS and node.tag not in VOID_TAGS
        ]

    def structure_problems(self) -> list[tuple[str, str, int]]:
        """HTML that a browser would build differently from this model."""
        problems: list[tuple[str, str, int]] = []
        if self.bogus_comment:
            problems.append(("html.comment", "a comment opened with <!--> or <!---> closes at once in browsers", 1))
        for node in self.unclosed()[:5]:
            problems.append(("html.unclosed", f"<{node.tag}> opened on line {node.line} is never closed", node.line))
        for tag, line in self.breakouts[:5]:
            problems.append(("html.foreign-breakout", f"<{tag}> on line {line} inside SVG or MathML ends that figure in browsers; draw it with SVG elements or use <foreignObject>", line))
        for tag, line in self.misnested[:5]:
            problems.append(("html.block-in-p", f"<{tag}> on line {line} sits inside a <p> through an inline element; browsers move it out of the paragraph", line))
        for node in self.elements:
            if node.self_closed and not any(a.tag in FOREIGN_ROOTS for a in [node, *node.ancestors()]):
                problems.append(("html.self-closing", f"<{node.tag} .../> is not closed by '/>' in HTML; write </{node.tag}>", node.line))
            for name in node.duplicates:
                problems.append(("html.duplicate-attr", f"<{node.tag}> repeats the attribute {name!r}", node.line))
        return problems

    def marker(self) -> Element | None:
        for element in self.find("meta"):
            if element.attrs.get("name") == MARKER_NAME:
                return element
        return None


def _block(source: str, tag: str, element_id: str) -> str | None:
    match = re.search(
        rf"<{tag}\b[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>(.*?)</{tag}>",
        source,
        re.S,
    )
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# Check
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, level: str, code: str, message: str, line: int | None = None) -> None:
        item: dict[str, Any] = {"level": level, "code": code, "message": message}
        if line is not None:
            item["line"] = line
        self.items.append(item)

    def error(self, code: str, message: str, line: int | None = None) -> None:
        self.add("error", code, message, line)

    def warn(self, code: str, message: str, line: int | None = None) -> None:
        self.add("warning", code, message, line)

    @property
    def errors(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["level"] == "error"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "errors": self.errors,
            "warnings": [item for item in self.items if item["level"] == "warning"],
        }


def _template_blocks() -> dict[str, str]:
    try:
        source = TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return {}
    blocks = {}
    for tag, element_id in (("style", "lp-base"), ("script", "lp-runtime"), ("script", "lp-boot")):
        content = _block(source, tag, element_id)
        if content is not None:
            blocks[element_id] = content
    return blocks


def _normalize_url(url: str) -> str:
    """Apply the clean-up browsers do before resolving a URL."""
    url = url.strip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f"
                    "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f ")
    return re.sub(r"[\t\r\n]", "", url).replace("\\", "/")


def _is_external(url: str) -> bool:
    url = _normalize_url(url)
    return bool(EXTERNAL_URL.match(url)) or url.lower().startswith(("http:", "https:", "ftp:"))


def _is_script_url(url: str) -> bool:
    return _normalize_url(url).lower().startswith(("javascript:", "vbscript:"))


def _srcset_urls(value: str) -> list[str]:
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def _local_target(page_path: Path | None, url: str) -> Path | None:
    from urllib.parse import unquote

    if page_path is None:
        return None
    clean = unquote(_normalize_url(url).split("#", 1)[0].split("?", 1)[0])
    if not clean or clean.startswith("/") or ":" in clean.split("/", 1)[0]:
        return None
    return page_path.parent / clean


def _next_element(element: Element) -> Element | None:
    if element.parent is None:
        return None
    siblings = [node for node in element.parent.children if node.tag not in {"script", "style", "template"}]
    index = siblings.index(element)
    return siblings[index + 1] if index + 1 < len(siblings) else None


def _previous_element(element: Element) -> Element | None:
    if element.parent is None:
        return None
    siblings = [node for node in element.parent.children if node.tag not in {"script", "style", "template"}]
    index = siblings.index(element)
    return siblings[index - 1] if index else None


def _allowed_in_open_question(child: Element, state: str) -> bool:
    classes = child.classes
    if child.tag == "h3":
        return True
    if child.tag == "p":
        return bool({"lp-ask", "lp-how", "lp-code-src"} & classes)
    if child.tag == "pre":
        return bool({"lp-code", "lp-output", "lp-formula"} & classes)
    if child.tag == "div" and {"lp-table", "tex"} & classes:
        return True
    if child.tag == "div" and "lp-timer" in classes:
        return True
    if child.tag in {"ul", "ol"}:
        return not any(node.tag in CONTROL_TAGS or node.tag == "details" for node in child.iter())
    if child.tag == "figure":
        return not any(
            node.tag in CONTROL_TAGS or node.tag == "details" or WIDGET_CLASSES & node.classes
            for node in [child, *child.iter()]
        )
    return child.tag in {"script", "style"}


def _display_width(text: str) -> int:
    return sum(2 if "\u2e80" <= character <= "\uffef" else 1 for character in text)


def _has_name(element: Element) -> bool:
    if element.text().strip() or any(element.attrs.get(name) for name in ("aria-label", "aria-labelledby", "title")):
        return True
    for child in element.iter():
        if child.tag == "img" and child.attrs.get("alt"):
            return True
        if child.tag == "svg" and (child.attrs.get("aria-label") or any(node.tag == "title" for node in child.children)):
            return True
    return False


def check_source(source: str, page_path: Path | None = None) -> Report:
    report = Report()
    size = len(source.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        report.error("page.size", f"page is {size} bytes; the hard limit is {MAX_PAGE_BYTES}")
    elif size > SOFT_PAGE_BYTES:
        report.warn("page.size-soft", f"page is {size} bytes; continue the lesson in a part-2 page")
    page = Page(source)

    if not page.doctype:
        report.error("page.doctype", "missing <!doctype html>")
    for code, message, line in page.structure_problems():
        report.error(code, message, line)
    for tag, line in page.stray_end_tags[:5]:
        report.warn("html.stray-end", f"</{tag}> on line {line} has no matching start tag", line)
    html_elements = page.find("html")
    if not html_elements or not LANG_PATTERN.fullmatch(html_elements[0].attrs.get("lang", "")):
        report.error("page.lang", "<html> needs a lang attribute such as zh-CN")
    metas = page.find("meta")
    if not any(meta.attrs.get("charset", "").lower() == "utf-8" for meta in metas):
        report.error("page.charset", 'missing <meta charset="utf-8">')
    if not any(meta.attrs.get("name") == "viewport" for meta in metas):
        report.error("page.viewport", "missing viewport meta")
    csp = [meta for meta in metas if meta.attrs.get("http-equiv", "").lower() == "content-security-policy"]
    if len(csp) != 1 or csp[0].attrs.get("content") != CSP:
        report.error("page.csp", "need the template's exact Content-Security-Policy meta; it keeps the page offline")
    titles = page.find("title")
    if not titles or not titles[0].text().strip():
        report.error("page.title", "missing or empty <title>")

    marker = page.marker()
    rev = 0
    if marker is None:
        report.error("page.marker", 'missing <meta name="lesson-pages">; this is not a lesson page')
    else:
        if marker.attrs.get("content") != MARKER_VERSION:
            report.error("page.marker", f"lesson-pages marker must have content=\"{MARKER_VERSION}\"", marker.line)
        if not ID_PATTERN.fullmatch(marker.attrs.get("data-id", "")):
            report.error("page.marker", "marker data-id must be a lowercase hyphen id", marker.line)
        raw_rev = marker.attrs.get("data-rev", "")
        if not REV_PATTERN.fullmatch(raw_rev) or int(raw_rev) < 1:
            report.error("page.marker", "marker data-rev must be a positive integer", marker.line)
        else:
            rev = int(raw_rev)
        if not DATE_PATTERN.fullmatch(marker.attrs.get("data-updated", "")):
            report.error("page.marker", "marker data-updated must be YYYY-MM-DD", marker.line)
        if "data-key" in marker.attrs and not re.fullmatch(r"[0-9a-f]{12}", marker.attrs["data-key"]):
            report.error("page.marker", "marker data-key must be 12 lowercase hex digits", marker.line)

    mains = [node for node in page.find("main") if "lp-main" in node.classes]
    if len(mains) != 1:
        report.error("page.structure", 'need exactly one <main class="lp-main">')
    for tag, element_id in (("style", "lp-base"), ("script", "lp-boot"), ("script", "lp-runtime")):
        nodes = [node for node in page.by_id.get(element_id, []) if node.tag == tag]
        if len(nodes) != 1:
            report.error("page.structure", f"need exactly one <{tag} id=\"{element_id}\">")
    if source.count(APPEND_MARKER) != 1:
        report.error("page.structure", f"need exactly one {APPEND_MARKER} insertion marker")
    expected = _template_blocks()
    for tag, element_id in (("style", "lp-base"), ("script", "lp-boot"), ("script", "lp-runtime")):
        actual = _block(source, tag, element_id)
        if actual is not None and element_id in expected and actual.replace("\r\n", "\n") != expected[element_id]:
            report.warn("runtime.drift", f"#{element_id} differs from the current template; do not hand-edit it")

    # Resources and scripts.
    for element in page.elements:
        if element.tag in FORBIDDEN_TAGS:
            report.error("resource.forbidden", f"<{element.tag}> is not allowed in a lesson page", element.line)
        for attribute in ("src", "data", "poster", "srcset", "imagesrcset"):
            value = element.attrs.get(attribute)
            urls = _srcset_urls(value) if value and attribute.endswith("srcset") else [value] if value else []
            if any(_is_external(url) for url in urls):
                report.error("resource.external", f"<{element.tag} {attribute}> loads {value!r}; pages must open offline", element.line)
        if element.tag == "link":
            value = element.attrs.get("href", "")
            if value and _is_external(value):
                report.error("resource.external", f"<link href> loads {value!r}; pages must open offline", element.line)
        if element.tag in {"image", "use", "feimage", "script"}:
            for attribute in ("href", "xlink:href"):
                value = element.attrs.get(attribute, "")
                if value and _is_external(value):
                    report.error("resource.external", f"<{element.tag} {attribute}> loads {value!r}; pages must open offline", element.line)
        if element.tag == "meta" and element.attrs.get("http-equiv", "").lower() == "refresh":
            report.error("page.refresh", "<meta http-equiv=\"refresh\"> is not allowed", element.line)
        for attribute in ("href", "xlink:href", "action", "formaction", "src"):
            if _is_script_url(element.attrs.get(attribute, "")):
                report.error("link.script", f"script URLs are not allowed in {attribute}", element.line)
        if element.tag == "script":
            if "src" in element.attrs or "href" in element.attrs or "xlink:href" in element.attrs:
                report.error("script.src", "scripts must be inline; <script src> is not allowed", element.line)
            elif element.attrs.get("id") not in {"lp-boot", "lp-runtime"} and "data-lp-hook" not in element.attrs:
                report.error("script.hook", "page scripts must carry data-lp-hook", element.line)
        if element.tag == "style" or "style" in element.attrs:
            css = element.text() if element.tag == "style" else element.attrs.get("style", "")
            for match in CSS_URL.finditer(css):
                url = match.group(1) or match.group(2) or ""
                if _is_external(url) or match.group(2):
                    report.error("resource.external", f"CSS loads {url!r}; pages must open offline", element.line)
            if re.search(r"@import", css, re.I):
                report.error("resource.external", "CSS @import is not allowed; keep every style inline", element.line)
            if re.search(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
                report.error("resource.external", "CSS contains an absolute URL; pages must open offline", element.line)
        if element.tag in {"img", "source", "video", "audio"} and element.attrs.get("src") and not _is_external(element.attrs["src"]):
            target = _local_target(page_path, element.attrs["src"])
            if target is not None and not target.is_file():
                report.error("resource.missing", f"{element.attrs['src']!r} does not exist next to the page", element.line)
            elif not element.attrs["src"].startswith("data:"):
                report.warn("resource.local", f"{element.attrs['src']!r} is a separate file; inline it to keep one self-contained page", element.line)

    # Identifiers and links.
    for element_id, nodes in page.by_id.items():
        if len(nodes) > 1:
            report.error("id.duplicate", f"id {element_id!r} is used {len(nodes)} times", nodes[1].line)
    for element in page.find("a"):
        href = element.attrs.get("href", "")
        if href.startswith("#"):
            from urllib.parse import unquote

            if len(href) > 1 and unquote(href[1:]) not in page.by_id:
                report.error("anchor.missing", f"link {href!r} has no target", element.line)
        elif href and not _is_external(href) and not href.startswith(("mailto:", "data:")):
            target = _local_target(page_path, href)
            if target is not None and not target.exists():
                report.error("link.missing", f"relative link {href!r} does not resolve from the page", element.line)

    # Accessibility basics.
    labelled = {node.attrs.get("for") for node in page.find("label") if node.attrs.get("for")}
    for element in page.elements:
        if element.tag == "img" and "alt" not in element.attrs:
            report.error("a11y.img-alt", "<img> needs alt text", element.line)
        if element.tag == "svg" and element.attrs.get("role") == "img":
            has_title = any(child.tag == "title" and child.text().strip() for child in element.children)
            if not (element.attrs.get("aria-label") or element.attrs.get("aria-labelledby") or has_title):
                report.error("a11y.svg-name", "<svg role=\"img\"> needs aria-label or <title>", element.line)
        if element.tag == "button" and not _has_name(element):
            if not ({"data-lp-theme", "data-lp-review"} & set(element.attrs)):
                report.error("a11y.button-name", "<button> needs visible text or aria-label", element.line)
        input_type = element.attrs.get("type", "").lower()
        named_input = input_type in {"button", "submit", "reset", "image"} and (element.attrs.get("value") or element.attrs.get("alt"))
        if element.tag in {"input", "select", "textarea"} and input_type != "hidden" and not named_input:
            inside_label = any(node.tag == "label" for node in element.ancestors())
            if not (inside_label or element.attrs.get("aria-label") or element.attrs.get("aria-labelledby")
                    or element.attrs.get("id") in labelled):
                report.error("a11y.control-label", f"<{element.tag}> needs a label", element.line)
        if element.tag in {"h1", "h2", "h3"} and not element.text().strip():
            report.error("heading.empty", f"<{element.tag}> is empty", element.line)

    # Unfilled template slots (lessons about templating may legitimately show other braces).
    leftover = sorted({slot for slot in TEMPLATE_SLOTS if slot in source})
    if leftover or CONTENT_MARKER in source:
        report.error("fill.leftover", "template placeholder left in the page: " + ", ".join(leftover or [CONTENT_MARKER]))

    # Revision stamps never run ahead of the page revision.
    for element in page.elements:
        stamp = element.attrs.get("data-rev")
        if stamp is not None and element.tag != "meta":
            if not REV_PATTERN.fullmatch(stamp) or (rev and int(stamp) > rev):
                report.error("rev.future", f"data-rev={stamp!r} is not a revision of this page (current {rev})", element.line)

    # Questions: one canonical text, no answers, widgets or hints while open.
    questions: dict[str, str] = {}
    for element in page.find(cls="lp-check"):
        element_id = element.attrs.get("id", "")
        state = element.attrs.get("data-state", "")
        if not element_id:
            report.error("check.id", "every .lp-check needs an id such as q-1", element.line)
            continue
        if state not in QUESTION_STATES:
            report.error("check.state", f"{element_id}: data-state must be one of {', '.join(QUESTION_STATES)}", element.line)
            continue
        questions[element_id] = state
        if state in WAITING_STATES:
            for child in element.children:
                if not _allowed_in_open_question(child, state):
                    report.error("check.leak", f"{element_id} is {state}; it may hold only the question, its code or a static figure, and a timer", child.line)
            following = _next_element(element)
            if state in {"open", "answered"} and following is not None and following.tag != "section" and (
                following.tag == "details" or "lp-answer" in following.classes
                or WIDGET_CLASSES & following.classes
                or any(node.tag == "details" or "lp-answer" in node.classes or WIDGET_CLASSES & node.classes
                       for node in following.iter())
            ):
                report.error("check.leak", f"nothing interactive or collapsible may sit right after open question {element_id}", following.line)
            for child in element.iter():
                if child.tag == "details" or "lp-answer" in child.classes:
                    report.error("check.leak", f"{element_id} is {state}; reference points and <details> wait until it is closed", child.line)
                elif child.tag in CONTROL_TAGS or WIDGET_CLASSES & child.classes:
                    if "lp-timer" in child.classes:
                        continue
                    report.error("check.leak", f"{element_id} is {state}; it may not contain an interactive widget", child.line)
    for element in page.elements:
        target = element.attrs.get("data-reveals")
        if target is None:
            continue
        for question in [part.strip() for part in target.split(",") if part.strip()]:
            if question not in questions:
                report.error("check.reveal", f"data-reveals names unknown question {question!r}", element.line)
            elif questions[question] != "closed":
                report.error("check.reveal", f"this widget reveals {question}, which is still {questions[question]}", element.line)

    # Nodes: conclusion first, spine pointer when the page has one.
    has_spine = page.one("spine") is not None
    for node in page.find(cls="lp-node"):
        node_id = node.attrs.get("id")
        if not node_id:
            report.error("node.id", "every .lp-node needs an id such as node-1", node.line)
            continue
        headings = [child for child in node.children if child.tag == "h2"]
        if not headings:
            report.error("node.heading", f"{node_id} needs an <h2>", node.line)
        content = [
            child for child in node.children
            if child.tag not in {"h2"} and not ({"lp-spine", "lp-where"} & child.classes)
        ]
        if not content or "lp-lead" not in content[0].classes or not content[0].text().strip():
            report.error("node.lead", f"{node_id} must open with a non-empty .lp-lead conclusion", node.line)
        if has_spine and not any("lp-spine" in child.classes for child in node.children):
            report.warn("node.spine", f"{node_id} has no .lp-spine line naming its part of the teaching spine", node.line)
    spine = page.one("spine")
    if spine is not None and not any(child.tag == "a" and child.attrs.get("href") for child in spine.iter()):
        report.warn("spine.link", "#spine names no linked material location")

    # Figures must survive dark mode and narrow screens.
    for svg in page.find("svg"):
        for node in [svg, *svg.iter()]:
            for attribute in ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color"):
                value = re.sub(r"url\([^)]*\)", "", node.attrs.get(attribute, "")).strip()
                named = re.fullmatch(r"[A-Za-z]+", value) and value.lower() not in PAINT_KEYWORDS
                if COLOR_LITERAL.search(value) or named:
                    report.error("svg.color", f"<{node.tag} {attribute}=\"{value}\"> hard-codes a color; use currentColor or var(--token) so dark mode works", node.line)
            if COLOR_LITERAL.search(re.sub(r"url\([^)]*\)", "", node.attrs.get("style", ""))):
                report.error("svg.color", f"<{node.tag} style> hard-codes a color; use var(--token)", node.line)
        view_box = svg.attrs.get("viewbox") or svg.attrs.get("viewBox") or ""
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", view_box)]
        if len(numbers) == 4 and numbers[2] > 0:
            for text_node in [node for node in svg.iter() if node.tag == "text"]:
                size = re.search(r"(\d+(?:\.\d+)?)", text_node.attrs.get("font-size", "") or "")
                if size and float(size.group(1)) * 342 / numbers[2] < 11:
                    report.warn("svg.label-size", f"SVG label renders below 11px at phone width (font-size {size.group(1)} in a {numbers[2]:g}-wide viewBox)", text_node.line)
                    break
    for element in page.elements:
        if element.tag == "style" and element.attrs.get("id") in {"lp-base", KATEX_STYLE_ID}:
            continue
        css = element.text() if element.tag == "style" else element.attrs.get("style", "") if not any(a.tag == "svg" for a in [element, *element.ancestors()]) else ""
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        if css and COLOR_LITERAL.search(re.sub(r"url\([^)]*\)", "", css)):
            report.warn("style.color", "page styles hard-code a color; use var(--…) tokens so dark mode works", element.line)
    def code_lines(block: Element) -> set[int]:
        start_raw = block.attrs.get("data-start", "1")
        start = int(start_raw) if REV_PATTERN.fullmatch(start_raw) else 1
        count = len(re.sub(r"^\r?\n", "", _lf(block.text())).rstrip("\n").split("\n"))
        return set(range(start, start + count))

    for figure in page.find("figure"):
        blocks = [node for node in figure.iter() if node.tag == "pre" and "lp-code" in node.classes]
        steps = [node.attrs.get("data-lines", "") for node in figure.iter()
                 if node.tag == "li" and node.parent is not None and "lp-steps" in node.parent.classes]
        valid = set().union(*(code_lines(block) for block in blocks)) if blocks else set()
        if blocks and any(int(value) not in valid for text in steps for value in re.findall(r"[0-9]+", text)):
            report.warn("code.highlight-range", "a step's data-lines names lines that no code block in this figure has", figure.line)
    for block in page.find("pre", cls="lp-code"):
        lines = code_lines(block)
        start, count = min(lines), len(lines)
        ranges = [block.attrs.get("data-highlight", "")]
        notes = _next_element(block)
        if notes is not None and "lp-code-src" in notes.classes:
            notes = _next_element(notes)
        if notes is not None and "lp-code-notes" in notes.classes:
            ranges += [node.attrs.get("data-lines", "") for node in notes.children if node.tag == "li"]
        if "data-symbols" in block.attrs and not SYMBOL_MAP.fullmatch(block.attrs["data-symbols"].strip()):
            report.error("code.symbols", "data-symbols must look like \"m_i=1 l_i=2\" (identifier=1..4)", block.line)
        numbers = [int(value) for text in ranges for value in re.findall(r"[0-9]+", text)]
        if any(number < start or number >= start + count for number in numbers):
            report.warn("code.highlight-range", f"highlighted lines must use the block's own numbers ({start}–{start + count - 1})", block.line)
    for notes in page.find("ol", cls="lp-code-notes"):
        previous = _previous_element(notes)
        if previous is not None and "lp-code-src" in previous.classes:
            previous = _previous_element(previous)
        if previous is None or previous.tag != "pre" or "lp-code" not in previous.classes:
            report.error("code.notes", "ol.lp-code-notes must follow its pre.lp-code (or the pre's .lp-code-src line)", notes.line)
        if any(child.tag == "li" and not re.fullmatch(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*", child.attrs.get("data-lines", "")) for child in notes.children):
            report.error("code.notes", "every line note needs data-lines such as 3 or 3-5", notes.line)

    # Formulas: TeX is rendered at write time and its stylesheet carries the fonts it uses.
    for element in _tex_formulas(page):
        if not any("katex" in node.classes for node in element.iter()):
            report.error("math.unrendered", "a .tex formula was never rendered; write formulas with new, add or state, or run render after a hand edit", element.line)
        elif "data-tex" in element.attrs and _tex_annotation(element) != element.attrs["data-tex"]:
            report.error("math.stale", "a formula's data-tex differs from what is shown; run render to draw it again", element.line)
    if any("katex" in element.classes for element in page.elements):
        styles = [node for node in page.by_id.get(KATEX_STYLE_ID, []) if node.tag == "style"]
        if not styles:
            report.error("math.css", f"rendered formulas need the <style id=\"{KATEX_STYLE_ID}\"> that new, add and state write")
        else:
            content = styles[0].text().replace("\r\n", "\n").strip("\n")
            have = _katex_block_fonts(content)
            missing = sorted(_katex_faces(page) - have)
            if missing:
                report.warn("math.font", "formulas use fonts the page does not embed: " + ", ".join(missing), styles[0].line)
            if _katex_block_version(content) != KATEX_VERSION:
                report.warn("math.version", f"formulas were rendered by another KaTeX; run render to redraw them with {KATEX_VERSION}", styles[0].line)
            if content != _katex_style(have):
                report.warn("runtime.drift", f"#{KATEX_STYLE_ID} differs from the vendored KaTeX stylesheet; do not hand-edit it", styles[0].line)
    for block in page.find("pre", cls="lp-formula"):
        widest = max((_display_width(line) for line in block.text().splitlines()), default=0)
        if widest > 48:
            report.warn("text.wide-formula", f"a formula line is {widest} columns wide; keep it within about 40 so it fits a phone", block.line)
    for paragraph in page.find("p", scope=mains[0] if mains else None):
        cjk = len(re.findall(r"[\u3400-\u9fff]", paragraph.text()))
        if cjk > 220:
            report.warn("text.wall", f"a paragraph has {cjk} CJK characters; split it or move detail into a figure", paragraph.line)

    # Widgets.
    scripts = "\n".join(node.text() for node in page.find("script"))
    for figure in page.find(cls="lp-explorer"):
        figure_id = figure.attrs.get("id", "")
        if not figure_id or not re.search(rf"explorers\s*(?:\[\s*['\"]{re.escape(figure_id)}['\"]\s*\]|\.{re.escape(figure_id)}\b)", scripts):
            report.warn("widget.hook", f"explorer {figure_id or '(no id)'} has no registered compute function", figure.line)
    for figure in page.find("figure"):
        if not any(child.tag == "figcaption" for child in figure.children):
            report.warn("figure.caption", f"figure {figure.attrs.get('id', '')} has no <figcaption>", figure.line)
    for main in mains:
        if EMOJI_PATTERN.search(main.text()):
            report.warn("style.emoji", "emoji in page text; use words, numbers or a drawn mark instead")
    return report


# --------------------------------------------------------------------------
# Paths and atomic writes
# --------------------------------------------------------------------------


def _repo(raw: str) -> Path:
    path = Path(raw).resolve()
    if not path.is_dir():
        raise UsageError(f"--repo is not a directory: {raw}")
    return path


WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{prefix}{suffix}" for prefix in ("COM", "LPT") for suffix in "123456789\u00b9\u00b2\u00b3"}
)


def _relative_parts(raw: str) -> tuple[str, ...]:
    if not raw or any(ord(character) < 32 for character in raw):
        raise UsageError(f"not a repository-relative path: {raw!r}")
    if PureWindowsPath(raw).drive or PurePosixPath(raw).is_absolute() or raw.startswith("\\"):
        raise UsageError(f"path must be relative to --repo: {raw!r}")
    parts = tuple(re.split(r"[\\/]", raw))
    if any(part in {"", ".", ".."} for part in parts):
        raise UsageError(f"path must not contain empty, '.' or '..' parts: {raw!r}")
    for part in parts:
        if (any(character in part for character in ':<>"|?*') or part.endswith((" ", "."))
                or part.split(".", 1)[0].upper() in WINDOWS_RESERVED):
            raise UsageError(f"path part {part!r} is not portable to Windows")
    return parts


def _protected(part: str) -> bool:
    folded = part.rstrip(" .").casefold()
    return folded in PROTECTED_PARTS or folded.startswith(".agent-skills")


def _inside(repo: Path, raw: str, *, must_exist: bool) -> Path:
    parts = _relative_parts(raw)
    for part in parts:
        if _protected(part):
            raise UsageError(f"lesson pages never live under {part}: {raw}")
    current = repo
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise UsageError(f"path goes through a symbolic link: {'/'.join(parts[:index + 1])}")
        if index < len(parts) - 1 and current.exists() and not current.is_dir():
            raise UsageError(f"not a directory: {'/'.join(parts[:index + 1])}")
        if index < len(parts) - 1 and (current / ".git").exists():
            raise UsageError(f"{'/'.join(parts[:index + 1])} is a nested repository or submodule")
    if must_exist and not current.is_file():
        raise UsageError(f"page does not exist: {raw}")
    try:
        current.resolve().relative_to(repo)
    except ValueError as exc:
        raise UsageError(f"path leaves the repository: {raw}") from exc
    return current


CONTEXT_FILE = SKILL_ROOT / ".agent-skills-context.json"


def _page_ceiling() -> list[str] | None:
    """Page directories from the managed context of this generated copy, if any."""
    if not CONTEXT_FILE.exists():
        return None
    try:
        wrapper = json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))
        assert wrapper.get("manager") == "agent-skills" and wrapper.get("skill") == "lesson-pages"
        targets = wrapper["context"]["page_targets"]
        collections = [target["collection"] for target in targets]
        assert collections == sorted(wrapper["allowlist"]["write_paths"]) or set(collections) == set(wrapper["allowlist"]["write_paths"])
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        raise UsageError("the managed .agent-skills-context.json is unreadable or not for lesson-pages; re-materialize before writing pages") from exc
    return collections


def _page_path(repo: Path, raw: str, *, must_exist: bool, writing: bool = False) -> Path:
    path = _inside(repo, raw, must_exist=must_exist)
    if path.suffix.lower() != ".html":
        raise UsageError(f"lesson pages are .html files: {raw}")
    if writing:
        ceiling = _page_ceiling()
        relative = path.relative_to(repo).as_posix()
        if ceiling is not None and not any(relative.startswith(collection.rstrip("/") + "/") for collection in ceiling):
            raise UsageError(f"{relative} is outside the configured page_targets: {', '.join(ceiling)}")
    return path


def _read(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    if len(data) > MAX_PAGE_BYTES:
        raise UsageError(f"{path.name} is larger than {MAX_PAGE_BYTES} bytes")
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError as exc:
        raise UsageError(f"{path.name} is not UTF-8") from exc


def _write_new(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise UsageError(f"{path.name} already exists; lesson-pages never replaces a page with new") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def _replace(path: Path, original: bytes, text: str) -> None:
    temporary = path.with_name(f".{path.name}.lp-tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink() or path.read_bytes() != original:
            raise UsageError(f"{path.name} changed while it was being updated; nothing was written")
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


# --------------------------------------------------------------------------
# Fragments, revisions and states
# --------------------------------------------------------------------------


ATTRIBUTE_TOKEN = re.compile(
    r"""\s*([^\s"'>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?""",
)


def _set_attribute(start_tag: str, name: str, value: str) -> str:
    """Set one attribute, walking whole attributes so a quoted value is never edited."""
    escaped = html.escape(value, quote=True)
    head = re.match(r"<[A-Za-z][A-Za-z0-9-]*", start_tag)
    assert head is not None
    position = head.end()
    end = len(start_tag) - (2 if start_tag.endswith("/>") else 1)
    while position < end:
        match = ATTRIBUTE_TOKEN.match(start_tag, position, end)
        if match is None or match.end() == position:
            break
        if match.group(1).lower() == name.lower():
            value_start = match.start(1)
            return f'{start_tag[:value_start]}{name}="{escaped}"{start_tag[match.end():]}'
        position = match.end()
    stem = start_tag[:end].rstrip()
    return f'{stem} {name}="{escaped}"{start_tag[end:]}'


def _edit_start_tags(source: str, edits: dict[int, tuple[int, dict[str, str]]]) -> str:
    """Apply attribute edits keyed by start offset: {start: (start_end, attrs)}."""
    pieces: list[str] = []
    cursor = 0
    for start in sorted(edits):
        start_end, attrs = edits[start]
        tag = source[start:start_end]
        for name, value in attrs.items():
            tag = _set_attribute(tag, name, value)
        pieces.append(source[cursor:start])
        pieces.append(tag)
        cursor = start_end
    pieces.append(source[cursor:])
    return "".join(pieces)


def _bump(source: str, page: Page, rev: int, date: str) -> str:
    marker = page.marker()
    assert marker is not None
    text = _edit_start_tags(source, {marker.start: (marker.start_end, {"data-rev": str(rev), "data-updated": date})})
    # The runtime rewrites this line too; keeping it current matters when the page is read without scripts.
    return re.sub(r'(<p data-lp-auto="date">)更新于 [0-9]{4}-[0-9]{2}-[0-9]{2}(</p>)', rf"\g<1>更新于 {date}\g<2>", text, count=1)


# --------------------------------------------------------------------------
# Formulas and code: rendered once, when the fragment is written
# --------------------------------------------------------------------------


def _tex_formulas(page: Page) -> list[Element]:
    """``span.tex`` and ``div.tex`` that are formulas; inside code, SVG or MathML the class is just a class."""
    return [
        element for element in page.elements
        if element.tag in {"span", "div"} and "tex" in element.classes
        and not any(node.tag in TEX_EXCLUDED_CONTEXTS for node in element.ancestors())
    ]


def _tex_annotation(element: Element) -> str | None:
    """The TeX source KaTeX recorded inside a rendered formula."""
    for node in element.iter():
        if node.tag == "annotation" and node.attrs.get("encoding") == "application/x-tex":
            return node.text()
    return None


def _symbol_map(raw: str, line: int) -> dict[str, int]:
    if not SYMBOL_MAP.fullmatch(raw.strip()):
        raise UsageError(f"data-symbols on line {line} must look like \"m_i=1 l_i=2\" (identifier=1..4)")
    return {name: int(number) for name, number in (pair.split("=") for pair in raw.split())}


def _render_fragment(fragment: str, parsed: Page, *, force: bool = False) -> tuple[str, dict[str, Any]]:
    """Render ``.tex`` TeX with KaTeX and highlight ``pre.lp-code[data-lang]`` with highlight.js.

    A formula is rendered when it holds plain TeX, or when its ``data-tex`` no
    longer matches what was rendered (``force`` re-renders every formula, e.g.
    after a KaTeX upgrade). TeX is rendered or the write fails; code that
    already holds markup keeps it, and code is left plain with a note when Node
    is missing. Unchanged results are not counted.
    """
    newline = "\r\n" if "\r\n" in fragment else "\n"
    jobs: list[tuple[Element, dict[str, Any]]] = []
    for element in _tex_formulas(parsed):
        has_katex = any("katex" in node.classes for node in element.iter())
        if "data-tex" in element.attrs and (has_katex or element.children or not element.text().strip()):
            if has_katex and not force and _tex_annotation(element) == element.attrs["data-tex"]:
                continue
            source = element.attrs["data-tex"].strip()
        else:
            if element.children:
                raise UsageError(f"<{element.tag} class=\"tex\"> on line {element.line} must hold plain TeX; write < and & as &lt; and &amp;")
            source = element.text().strip()
        if not source:
            raise UsageError(f"<{element.tag} class=\"tex\"> on line {element.line} is empty")
        jobs.append((element, {"kind": "tex", "source": _lf(source), "display": element.tag == "div"}))
    for element in parsed.elements:
        if element.tag == "pre" and "lp-code" in element.classes and element.attrs.get("data-lang"):
            code = next((child for child in element.children if child.tag == "code"), None)
            symbols = _symbol_map(element.attrs["data-symbols"], element.line) if "data-symbols" in element.attrs else {}
            if code is None or code.children:
                continue
            jobs.append((code, {"kind": "code", "source": _lf(code.text()), "lang": element.attrs["data-lang"], "symbols": symbols}))
    info: dict[str, Any] = {"tex": 0, "code": 0}
    if not jobs:
        return fragment, info
    node = shutil.which("node")
    if node is None:
        if any(item["kind"] == "tex" for _element, item in jobs):
            raise UsageError("TeX in this fragment is rendered with Node.js, and node is not on PATH; install Node "
                             "or write the formula with HTML <sub>/<sup> or MathML")
        info["note"] = "node not found; code blocks were left without syntax colors"
        return fragment, info
    result = subprocess.run([node, str(RENDERER)], input=json.dumps({"items": [item for _element, item in jobs]}),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=120)
    if result.returncode != 0:
        detail = next((line for line in result.stderr.splitlines() if "Error" in line), result.stderr.strip()[:300])
        raise UsageError(f"render.cjs failed: {detail}")
    rendered = json.loads(result.stdout)["items"]
    problems = [f"line {element.line}: {reply['error']}" for (element, _item), reply in zip(jobs, rendered) if "error" in reply]
    if problems:
        raise UsageError("could not render the fragment; nothing was written:\n  " + "\n  ".join(problems[:5]))
    text = fragment
    for (element, item), reply in sorted(zip(jobs, rendered), key=lambda pair: pair[0][0].start, reverse=True):
        assert element.end_start is not None
        start_tag = text[element.start:element.start_end]
        if item["kind"] == "tex":
            start_tag = _set_attribute(start_tag, "data-tex", item["source"].replace("\n", newline))
        body = reply["html"].replace("\n", newline)
        if text[element.start:element.end_start] == start_tag + body:
            continue
        text = text[:element.start] + start_tag + body + text[element.end_start:]
        info[item["kind"]] += 1
    return text, info


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


@functools.lru_cache(maxsize=1)
def _katex_rules() -> tuple[list[tuple[int, int, frozenset[str], dict[str, str]]], dict[tuple[str, str, int], str], str]:
    """Font rules and faces of the vendored KaTeX stylesheet, plus the sheet without its @font-face rules."""
    css = (KATEX_DIR / "katex.min.css").read_text(encoding="utf-8")
    faces: dict[tuple[str, str, int], str] = {}
    for body in re.findall(r"@font-face\{([^}]*)\}", css):
        family = re.search(r"font-family:([^;]+)", body).group(1).strip().strip('"')  # type: ignore[union-attr]
        style = re.search(r"font-style:([^;]+)", body).group(1).strip()  # type: ignore[union-attr]
        weight = int(re.search(r"font-weight:([^;]+)", body).group(1).strip())  # type: ignore[union-attr]
        faces[(family, style, weight)] = re.search(r"url\(fonts/([^)]+)\.woff2\)", body).group(1)  # type: ignore[union-attr]
    sheet = re.sub(r"@font-face\{[^}]*\}", "", css)
    rules = []
    for order, (selectors, body) in enumerate(re.findall(r"([^{}@]+)\{([^{}]*)\}", sheet)):
        decls: dict[str, str] = {}
        shorthand = re.search(r"(?:^|;)font:([^;]+)", body)
        if shorthand:
            decls["style"] = "italic" if "italic" in shorthand.group(1) else "normal"
            decls["weight"] = "700" if re.search(r"\bbold\b|\b[6-9]00\b", shorthand.group(1)) else "400"
            family = re.search(r"[0-9.]+(?:em|px|%|rem)\s+([^,]+)", shorthand.group(1))
            if family:
                decls["family"] = family.group(1).strip().strip('"')
        for key, prop in (("family", "font-family"), ("style", "font-style"), ("weight", "font-weight")):
            found = re.search(rf"(?:^|;){prop}:([^;]+)", body)
            if found:
                decls[key] = found.group(1).split(",")[0].strip().strip('"')
        if not decls:
            continue
        for selector in selectors.split(","):
            selector = selector.strip()
            if not selector.startswith(".katex"):
                continue
            compounds = [part for part in re.split(r"[\s>+~]+", selector) if "." in part]
            classes = frozenset(re.findall(r"\.([\w-]+)", compounds[-1]))
            rules.append((selector.count("."), order, classes, decls))
    rules.sort(key=lambda rule: (rule[0], rule[1]))
    return rules, faces, sheet


def _katex_faces(page: Page) -> set[str]:
    """Font files the page's rendered formulas draw text with."""
    rules, faces, _sheet = _katex_rules()
    # The .katex box itself is set in KaTeX_Main, so browsers load it for line metrics even without Main glyphs.
    needed: set[str] = {faces[("KaTeX_Main", "normal", 400)]} if any("katex" in node.classes for node in page.elements) else set()

    def face(state: dict[str, str]) -> str | None:
        family, style = state.get("family", "KaTeX_Main"), state.get("style", "normal")
        weight = 700 if state.get("weight", "400") in {"bold", "bolder"} or state.get("weight", "400").isdigit() and int(state["weight"]) >= 600 else 400
        options = [key for key in faces if key[0] == family]
        for key in sorted(options, key=lambda key: (key[1] != style, key[2] != weight, key[2])):
            return faces[key]
        return None

    def walk(element: Element, state: dict[str, str]) -> None:
        if "katex-mathml" in element.classes:
            return
        state = dict(state)
        for _specificity, _order, classes, decls in rules:
            if classes <= element.classes:
                state.update(decls)
        if any(isinstance(chunk, str) and chunk.strip() for chunk in element.chunks):
            name = face(state)
            if name:
                needed.add(name)
        for child in element.children:
            walk(child, state)

    for element in page.elements:
        if "katex" in element.classes and not any("katex" in node.classes for node in element.ancestors()):
            walk(element, {})
    return needed


def _katex_style(fonts: Iterable[str]) -> str:
    """The #lp-katex block: the vendored stylesheet with only the named fonts, inlined as data URLs."""
    _rules, _faces, sheet = _katex_rules()
    chosen = sorted(set(fonts))
    css = (KATEX_DIR / "katex.min.css").read_text(encoding="utf-8")
    font_rules = []
    for body in re.findall(r"@font-face\{([^}]*)\}", css):
        name = re.search(r"url\(fonts/([^)]+)\.woff2\)", body).group(1)  # type: ignore[union-attr]
        if name not in chosen:
            continue
        data = base64.b64encode((KATEX_DIR / "fonts" / f"{name}.woff2").read_bytes()).decode("ascii")
        body = re.sub(r"src:[^;}]+", f'src:url(data:font/woff2;base64,{data}) format("woff2")', body)
        font_rules.append("@font-face{" + body + "}")
    header = f"/* lesson-pages: KaTeX {KATEX_VERSION} stylesheet and fonts, written by the script; do not edit. fonts: {' '.join(chosen)} */"
    license_text = (KATEX_DIR / "LICENSE").read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    font_license = (KATEX_DIR / "fonts" / "OFL.txt").read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    notices = "/*! KaTeX stylesheet: " + license_text + " */\n/*! KaTeX fonts: " + font_license + " */\n"
    return header + "\n" + notices + "".join(font_rules) + sheet.strip()


def _katex_block_fonts(content: str) -> set[str]:
    match = re.search(r"fonts:([^*]*)\*/", content)
    return set(match.group(1).split()) if match else set()


def _katex_block_version(content: str) -> str | None:
    match = re.search(r"lesson-pages: KaTeX ([0-9][0-9.]*) stylesheet", content)
    return match.group(1) if match else None


def _ensure_katex(text: str, *, redrawn: bool = False) -> str:
    """Add or refresh the head style that rendered formulas need, with only the fonts they use."""
    page = Page(text)
    if not any("katex" in element.classes for element in page.elements):
        return text
    blocks = [node for node in page.by_id.get(KATEX_STYLE_ID, []) if node.tag == "style"]
    current = blocks[0].text().replace("\r\n", "\n") if blocks else ""
    if blocks and not redrawn and _katex_block_version(current) != KATEX_VERSION:
        # Formulas rendered by another KaTeX would not match this stylesheet; render them again first.
        if shutil.which("node") is None:
            raise UsageError(f"this page's formulas were rendered by KaTeX {_katex_block_version(current) or '(unknown)'}; "
                             f"redrawing them with {KATEX_VERSION} needs Node.js, and node is not on PATH")
        text, _rendered = _render_fragment(text, page, force=True)
        page = Page(text)
        blocks = [node for node in page.by_id.get(KATEX_STYLE_ID, []) if node.tag == "style"]
    have = _katex_block_fonts(current)
    fonts = have | _katex_faces(page)
    content = _katex_style(fonts)
    if blocks and current.strip("\n") == content:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    block = f'<style id="{KATEX_STYLE_ID}">{newline}{content.replace(chr(10), newline)}{newline}</style>'
    if blocks:
        assert blocks[0].end is not None
        return text[:blocks[0].start] + block + text[blocks[0].end:]
    anchor = next((node for node in page.by_id.get("lp-page-style", []) if node.tag == "style"), None)
    if anchor is not None:
        return text[:anchor.start] + block + newline + text[anchor.start:]
    heads = page.find("head")
    if not heads or heads[0].end_start is None:
        raise UsageError("page has no <head> to hold the formula styles")
    return text[:heads[0].end_start] + block + newline + text[heads[0].end_start:]


def _prepare_fragment(fragment: str, page: Page, rev: int) -> tuple[str, list[tuple[str, str]], list[str], dict[str, Any]]:
    """Validate a fragment, render its formulas and code, and stamp its blocks with ``rev``.

    Returns the main HTML, the parts routed with ``<template data-lp-into>``
    as ``(target id, html)`` pairs, every new element id, and what was rendered.
    """
    if len(fragment.encode("utf-8")) > MAX_FRAGMENT_BYTES:
        raise UsageError(f"fragment is larger than {MAX_FRAGMENT_BYTES} bytes; add it in smaller parts")
    parsed = Page(fragment)
    top = parsed.root.children
    if not top:
        raise UsageError("fragment has no elements")
    problems = parsed.structure_problems()
    if problems:
        raise UsageError("fragment HTML is malformed: " + "; ".join(message for _code, message, _line in problems[:3]))
    if parsed.stray_end_tags:
        tag, line = parsed.stray_end_tags[0]
        raise UsageError(f"</{tag}> on line {line} has no matching start tag")
    stray = "".join(chunk for chunk in parsed.root.chunks if isinstance(chunk, str)).strip()
    if stray:
        raise UsageError("fragment has text outside its top-level elements")
    for element in parsed.elements:
        if element.tag in FRAGMENT_FORBIDDEN_TAGS:
            raise UsageError(f"fragments may not contain <{element.tag}>")
        if element.tag == "script" and ("src" in element.attrs or "data-lp-hook" not in element.attrs):
            raise UsageError("fragment scripts must be inline and carry data-lp-hook")
        if element.tag == "style" and "data-lp-style" not in element.attrs:
            raise UsageError("fragment styles must carry data-lp-style")
        if element.tag == "template" and (element.parent is not parsed.root or "data-lp-into" not in element.attrs):
            raise UsageError("<template> is only for top-level routing with data-lp-into")
        if element.end is None or (element.implicit and element.tag not in OPTIONAL_END_TAGS):
            raise UsageError(f"<{element.tag}> on line {element.line} is never closed")
    fragment, rendered = _render_fragment(fragment, parsed)
    if rendered["tex"] or rendered["code"]:
        parsed = Page(fragment)
        top = parsed.root.children
    blocks: list[Element] = []
    for element in top:
        if element.tag == "template":
            inner_stray = "".join(chunk for chunk in element.chunks if isinstance(chunk, str)).strip()
            if inner_stray or not element.children:
                raise UsageError(f"<template data-lp-into=\"{element.attrs['data-lp-into']}\"> must hold elements only")
            blocks.extend(element.children)
        elif element.tag not in {"script", "style"}:
            blocks.append(element)
    new_ids = [element.attrs["id"] for element in parsed.elements if "id" in element.attrs]
    for element_id in new_ids:
        if not ELEMENT_ID_PATTERN.fullmatch(element_id):
            raise UsageError(f"id {element_id!r} must start with a letter and use letters, digits, - or _")
    duplicates = sorted({element_id for element_id in new_ids if new_ids.count(element_id) > 1 or element_id in page.by_id})
    if duplicates:
        raise UsageError("ids already used: " + ", ".join(duplicates))
    stamped = _edit_start_tags(
        fragment, {element.start: (element.start_end, {"data-rev": str(rev)}) for element in blocks}
    )
    restamped = Page(stamped)
    main: list[str] = []
    routed: list[tuple[str, str]] = []
    for element in restamped.root.children:
        if element.tag == "template":
            assert element.end_start is not None
            routed.append((element.attrs["data-lp-into"], stamped[element.start_end:element.end_start].strip("\n")))
        else:
            assert element.end is not None
            main.append(stamped[element.start:element.end])
    return "\n".join(main), routed, new_ids, rendered


def _container(page: Page, target_id: str) -> Element:
    element = page.one(target_id)
    if element is None:
        raise UsageError(f"no unique element with id {target_id!r}")
    if element.tag not in EXPLICIT_END_TAGS or element.end_start is None or element.end is None:
        raise UsageError(f"#{target_id} is a <{element.tag}>; insert into or after a section, div, figure, aside, ol, ul, dl or details")
    if not any(node.tag == "main" for node in element.ancestors()):
        raise UsageError(f"#{target_id} is outside the lesson content")
    return element


def _insert(source: str, page: Page, main: str, routed: list[tuple[str, str]], *,
            marker: str, into: str | None = None, after: str | None = None) -> str:
    if not main and (into is not None or after is not None):
        raise UsageError("--into and --after place the fragment's main part, but the fragment has only routed parts")
    points: list[tuple[int, int, str]] = []
    if main:
        if into is not None:
            points.append((_container(page, into).end_start or 0, 0, main))
        elif after is not None:
            points.append((_container(page, after).end or 0, 0, main))
        else:
            if source.count(marker) != 1:
                raise UsageError(f"page needs exactly one {marker}")
            points.append((source.index(marker), 0, main))
    for sequence, (target_id, part) in enumerate(routed, start=1):
        points.append((_container(page, target_id).end_start or 0, sequence, part))
    if not points:
        raise UsageError("fragment adds nothing")
    newline = "\r\n" if "\r\n" in source else "\n"
    text = source
    # Later offsets first; at one offset, later parts first so fragment order is kept.
    for offset, _sequence, part in sorted(points, key=lambda item: (item[0], item[1]), reverse=True):
        part = part.replace("\r\n", "\n").replace("\n", newline)
        before, rest = text[:offset], text[offset:]
        text = before + ("" if before.endswith("\n") else newline) + part + newline + rest
    return text


def _load_page(repo: Path, raw: str, expected_id: str) -> tuple[Path, str, bytes, Page, int]:
    path = _page_path(repo, raw, must_exist=True, writing=True)
    source, data = _read(path)
    page = Page(source)
    marker = page.marker()
    if marker is None:
        raise UsageError(f"{raw} has no lesson-pages marker; it was not created by this tool")
    if marker.attrs.get("data-id") != expected_id:
        raise UsageError(f"{raw} belongs to {marker.attrs.get('data-id')!r}, not {expected_id!r}; nothing was written")
    raw_rev = marker.attrs.get("data-rev", "")
    if not REV_PATTERN.fullmatch(raw_rev):
        raise UsageError(f"{raw} has an invalid data-rev")
    return path, source, data, page, int(raw_rev)


def _finish(path: Path, data: bytes, text: str, *, page_rel: str, rev: int, extra: dict[str, Any]) -> dict[str, Any]:
    report, scripts = full_check(text, path)
    if report.errors:
        raise UsageError(
            "the result would fail check; nothing was written:\n"
            + "\n".join(f"  {item['code']}: {item['message']}" for item in report.errors)
        )
    _replace(path, data, text)
    return {"page": page_rel, "rev": rev, **extra, "check": report.as_dict(), "scripts": scripts}


def _read_fragment(raw: str) -> str:
    if raw == "-":
        data = sys.stdin.buffer.read(MAX_FRAGMENT_BYTES + 1)
    else:
        data = Path(raw).read_bytes()
    try:
        return _lf(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise UsageError("fragment is not UTF-8") from exc


def _today(raw: str | None) -> str:
    if raw is None:
        return _dt.date.today().isoformat()
    if not DATE_PATTERN.fullmatch(raw):
        raise UsageError("--date must be YYYY-MM-DD")
    return raw


CLASSIC_SCRIPT_CHECK = "new (require('vm').Script)(require('fs').readFileSync(0, 'utf8'), {filename: 'inline-script.js'})"


def check_scripts(source: str) -> dict[str, Any]:
    """Parse inline scripts exactly as a browser would, when Node is available."""
    node = shutil.which("node")
    page = Page(source)
    scripts = [
        element for element in page.find("script")
        if element.attrs.get("type", "").lower() in {"", "text/javascript", "application/javascript", "module"}
    ]
    if node is None:
        return {"status": "skipped", "reason": "node not found", "count": len(scripts), "errors": []}
    errors = []
    with tempfile.TemporaryDirectory(prefix="lesson-pages-") as directory:
        for index, element in enumerate(scripts):
            text = element.text()
            if element.attrs.get("type", "").lower() == "module":
                module = Path(directory) / f"script-{index}.mjs"
                module.write_text(text, encoding="utf-8")
                command, stdin = [node, "--check", str(module)], None
            else:
                command, stdin = [node, "-e", CLASSIC_SCRIPT_CHECK], text
            result = subprocess.run(command, input=stdin, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", check=False)
            if result.returncode != 0:
                detail = next((line for line in result.stderr.splitlines() if "Error" in line), result.stderr.strip()[:200])
                errors.append({"code": "script.syntax", "line": element.line, "message": f"script on line {element.line}: {detail}"})
    return {"status": "checked", "count": len(scripts), "errors": errors}


def full_check(text: str, path: Path | None) -> tuple[Report, dict[str, Any]]:
    report = check_source(text, path)
    scripts = check_scripts(text)
    for item in scripts["errors"]:
        report.error(item["code"], item["message"], item["line"])
    return report, {key: value for key, value in scripts.items() if key != "errors"}


def _visible_text(element: Element) -> str:
    """Text a reader sees: no scripts, styles or the MathML copy KaTeX keeps for screen readers."""
    parts: list[str] = []
    stack: list[str | Element] = list(reversed(element.chunks))
    while stack:
        chunk = stack.pop()
        if isinstance(chunk, Element):
            if chunk.tag not in {"script", "style", "template"} and "katex-mathml" not in chunk.classes:
                stack.extend(reversed(chunk.chunks))
        else:
            parts.append(chunk)
    return "".join(parts)


def reading_minutes(html_text: str) -> int:
    text = _visible_text(Page(html_text).root)
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+", re.sub(r"[\u3400-\u9fff]", " ", text)))
    return max(1, round(cjk / 320 + words / 180))


def _title(heading: Element) -> str:
    parts: list[str] = []
    for chunk in heading.chunks:
        if isinstance(chunk, Element):
            if {"lp-new", "lp-oral-time"} & chunk.classes:
                continue
            text = _visible_text(chunk).strip()
            if "lp-no" in chunk.classes:
                parts.append(text + " ")
            elif "lp-kind" in chunk.classes:
                parts.append(" · " + text)
            else:
                parts.append(_visible_text(chunk))
        else:
            parts.append(chunk)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def outline_source(source: str) -> dict[str, Any]:
    page = Page(source)
    marker = page.marker()
    mains = [node for node in page.find("main") if "lp-main" in node.classes]
    line_of = lambda offset: source.count("\n", 0, offset) + 1  # noqa: E731 - tiny local helper
    lines = lambda node: [node.line, line_of(node.end or node.start)]  # noqa: E731
    blocks = []
    page_code = []
    if mains:
        for code in mains[0].iter():
            if code.tag in {"style", "script"}:
                owner = next((node.attrs.get("id", "") for node in code.ancestors() if node.parent is mains[0]), "")
                page_code.append({"tag": code.tag, "lines": lines(code), **({"inside": owner} if owner else {})})
        for element in mains[0].children:
            if element.tag in {"style", "script"}:
                continue
            if element.tag not in {"section", "footer", "div", "figure"} or "id" not in element.attrs:
                continue
            heading = next((child for child in element.children if child.tag in {"h2", "h3"}), None)
            kind = next((name[3:] for name in ("lp-node", "lp-check", "lp-narrative", "lp-glossary", "lp-sources") if name in element.classes), element.tag)
            entry: dict[str, Any] = {
                "id": element.attrs["id"],
                "kind": kind,
                "title": _title(heading) if heading else "",
                "lines": lines(element),
            }
            if "data-rev" in element.attrs:
                entry["rev"] = element.attrs["data-rev"]
            if "lp-check" in element.classes:
                entry["state"] = element.attrs.get("data-state", "")
                entry["has_reference_points"] = any("lp-answer" in node.classes for node in element.iter())
            figures = [
                {"id": node.attrs.get("id", ""), **({"reveals": node.attrs["data-reveals"]} if "data-reveals" in node.attrs else {})}
                for node in element.iter() if node.tag == "figure"
            ]
            if figures:
                entry["figures"] = figures
            inner = [
                {"id": node.attrs.get("id", ""), "kind": node.tag if not node.classes else sorted(node.classes)[0][3:],
                 "lines": lines(node), "rev": node.attrs.get("data-rev", "")}
                for node in element.iter()
                if "data-rev" in node.attrs and node is not element and node.tag not in {"dt", "dd"}
            ]
            if inner:
                entry["inner"] = inner
            if element.attrs.get("id") == "glossary":
                entry["entries"] = len([node for node in element.iter() if node.tag == "dt"])
            blocks.append(entry)
    style = page.by_id.get("lp-page-style", [])
    return {
        "id": marker.attrs.get("data-id", "") if marker else "",
        "rev": marker.attrs.get("data-rev", "") if marker else "",
        "updated": marker.attrs.get("data-updated", "") if marker else "",
        "bytes": len(source.encode("utf-8")),
        "head_style_lines": lines(style[0]) if style else None,
        "page_code": page_code,
        "append_marker_line": line_of(source.index(APPEND_MARKER)) if APPEND_MARKER in source else None,
        "blocks": blocks,
    }


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def command_new(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    if not ID_PATTERN.fullmatch(args.id) or len(args.id) > 64:
        raise UsageError("--id must be a lowercase hyphen id of at most 64 characters")
    if not LANG_PATTERN.fullmatch(args.lang):
        raise UsageError("--lang must be a language tag such as zh-CN")
    path = _page_path(repo, args.page, must_exist=False, writing=True)
    if path.exists():
        raise UsageError(f"{args.page} already exists; continue it with add")
    if not path.parent.is_dir():
        if not args.make_parents:
            raise UsageError(f"{path.parent.relative_to(repo).as_posix()} does not exist; pass --make-parents after the location is confirmed")
        _inside(repo, path.parent.relative_to(repo).as_posix(), must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
    date = _today(args.date)
    template = TEMPLATE.read_text(encoding="utf-8")
    fragment_ids: list[str] = []
    crumb_parts = [part for part in (args.course, args.label) if part]
    title_full = " · ".join([args.title, *crumb_parts]) if crumb_parts else args.title
    spine = (
        f'<p>主线资料：{html.escape(args.spine)}</p>' if args.spine else ""
    )
    sources = "\n".join(f"        <li>{html.escape(source)}</li>" for source in args.source)
    values = {
        "lang": html.escape(args.lang, quote=True),
        "id": args.id,
        "key": secrets.token_hex(6),
        "date": date,
        "title_full": html.escape(title_full),
        "title": html.escape(args.title),
        "crumb": html.escape(" · ".join(crumb_parts)) if crumb_parts else "",
        "spine": spine,
        "sources": sources,
    }
    text = SLOT_PATTERN.sub(lambda match: values[match.group(1)], template)
    if not crumb_parts:
        text = re.sub(r'\s*<p class="lp-crumb"></p>', "", text)
    if args.fragment:
        shell = Page(text)
        main, routed, fragment_ids, rendered = _prepare_fragment(_read_fragment(args.fragment), shell, 1)
        text = _ensure_katex(_insert(text, shell, main, routed, marker=CONTENT_MARKER))
    else:
        rendered = {"tex": 0, "code": 0}
    text = text.replace(CONTENT_MARKER + "\n", "").replace(CONTENT_MARKER, "")
    report, scripts = full_check(text, path)
    if report.errors:
        raise UsageError(
            "the new page would fail check; nothing was written:\n"
            + "\n".join(f"  {item['code']}: {item['message']}" for item in report.errors)
        )
    _write_new(path, text)
    return {
        "page": path.relative_to(repo).as_posix(),
        "rev": 1,
        "inserted_ids": fragment_ids,
        "rendered": rendered,
        "reading_minutes": reading_minutes(text.split('<main', 1)[-1]),
        "check": report.as_dict(),
        "scripts": scripts,
    }


def command_add(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    new_rev = rev + 1
    main, routed, ids, rendered = _prepare_fragment(_read_fragment(args.fragment), page, new_rev)
    text = _ensure_katex(_insert(source, page, main, routed, marker=APPEND_MARKER, into=args.into, after=args.after))
    text = _bump(text, Page(text), new_rev, _today(args.date))
    return _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"inserted_ids": ids, "anchors": ["#" + element_id for element_id in ids], "rendered": rendered,
                          "reading_minutes": reading_minutes(main + "".join(part for _target, part in routed))})


def command_state(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    element = page.one(args.question)
    if element is None or "lp-check" not in element.classes:
        raise UsageError(f"no question block with id {args.question!r}")
    current = element.attrs.get("data-state", "")
    if (current, args.to) not in TRANSITIONS:
        raise UsageError(f"{args.question} cannot move from {current or '(none)'} to {args.to}")
    new_rev = rev + 1
    text = _edit_start_tags(source, {element.start: (element.start_end, {"data-state": args.to, "data-rev": str(new_rev)})})
    ids: list[str] = []
    if args.fragment:
        if args.to != "closed":
            raise UsageError("--fragment adds reference points, so it only goes with --to closed")
        edited = Page(text)
        main, routed, ids, _rendered = _prepare_fragment(_read_fragment(args.fragment), edited, new_rev)
        text = _ensure_katex(_insert(text, edited, main, routed, marker=APPEND_MARKER, into=args.question))
    text = _bump(text, Page(text), new_rev, _today(args.date))
    return _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"question": args.question, "state": args.to, "inserted_ids": ids})


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    blocks = [node for node in page.by_id.get(KATEX_STYLE_ID, []) if node.tag == "style"]
    outdated = bool(blocks) and _katex_block_version(blocks[0].text()) != KATEX_VERSION
    text, rendered = _render_fragment(source, page, force=outdated)
    text = _ensure_katex(text, redrawn=outdated)
    if text == source:
        return {"page": path.relative_to(repo).as_posix(), "rev": rev, "rendered": rendered, "changed": False}
    new_rev = rev + 1
    text = _bump(text, Page(text), new_rev, _today(args.date))
    return _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"rendered": rendered, "changed": True})


def command_check(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path = _page_path(repo, args.page, must_exist=True)
    source, _data = _read(path)
    report, scripts = full_check(source, path)
    for anchor in args.anchor:
        if anchor.lstrip("#") not in Page(source).by_id:
            report.error("anchor.cited", f"#{anchor.lstrip('#')} does not exist; do not cite it in chat")
    result = {"page": path.relative_to(repo).as_posix(), **report.as_dict()}
    result["scripts"] = scripts
    return result


def command_outline(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path = _page_path(repo, args.page, must_exist=True)
    source, _data = _read(path)
    return {"page": path.relative_to(repo).as_posix(), **outline_source(source)}


def _marker_attributes(head: str) -> dict[str, str] | None:
    marker = Page(head).marker()
    return dict(marker.attrs) if marker is not None else None


def _head(path: Path) -> str:
    with path.open("rb") as handle:
        return handle.read(16384).decode("utf-8", errors="replace")


def command_find(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    pages = []
    skipped = []
    for collection in args.collection:
        root = _inside(repo, collection, must_exist=False)
        if not root.is_dir():
            raise UsageError(f"collection does not exist: {collection}")
        for directory, subdirectories, files in os.walk(root, followlinks=False):
            subdirectories[:] = sorted(
                name for name in subdirectories
                if not name.startswith(".") and not (Path(directory) / name).is_symlink()
            )
            for name in sorted(files):
                candidate = Path(directory) / name
                if name.startswith(".") or not name.lower().endswith(".html") or candidate.is_symlink():
                    continue
                try:
                    if candidate.stat().st_size > MAX_FIND_BYTES:
                        continue
                    head = _head(candidate)
                except OSError as exc:
                    skipped.append({"page": candidate.relative_to(repo).as_posix(), "reason": type(exc).__name__})
                    continue
                attributes = _marker_attributes(head)
                if attributes is None:
                    continue
                if args.id and attributes.get("data-id") != args.id:
                    continue
                title = re.search(r"<title>(.*?)</title>", head, re.S)
                pages.append({
                    "page": candidate.relative_to(repo).as_posix(),
                    "id": attributes.get("data-id", ""),
                    "rev": int(attributes["data-rev"]) if REV_PATTERN.fullmatch(attributes.get("data-rev", "")) else None,
                    "updated": attributes.get("data-updated", ""),
                    "title": html.unescape(title.group(1).strip()) if title else "",
                })
    result: dict[str, Any] = {"pages": pages}
    if skipped:
        result["skipped"] = skipped
    return result


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})


def make_server(root: Path, host: str = "127.0.0.1", port: int = 8765, allowed_hosts: Iterable[str] = ()):
    """Return a read-only HTTP server for one page collection.

    Only GET and HEAD are served. Paths with dot segments, hidden names or
    symbolic links are refused, directory listings show only lesson pages, and
    requests must name a local host (or one passed with --allow-host) so a
    web page cannot read the collection through DNS rebinding.
    ``/__lp/rev/<page>`` reports a page revision so an open page can offer a
    refresh.
    """
    import functools
    import http.server
    import io
    from urllib.parse import quote, unquote

    root = root.resolve()
    hosts = LOCAL_HOSTS | {name.lower() for name in allowed_hosts}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _safe(self, url_path: str) -> Path | None:
            relative = unquote(url_path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
            current = root
            for part in relative.split("/"):
                if not part:
                    continue
                if part in {".", ".."} or part.startswith(".") or "\\" in part:
                    return None
                current = current / part
                if current.is_symlink():
                    return None
            try:
                current.resolve().relative_to(root)
            except ValueError:
                return None
            return current

        def _host_allowed(self) -> bool:
            raw = (self.headers.get("Host") or "").strip().lower()
            name = raw[: raw.find("]") + 1] if raw.startswith("[") else raw.split(":", 1)[0]
            return name in hosts or name == "[::1]"

        def send_head(self):  # noqa: N802 - stdlib name
            if not self._host_allowed():
                self.send_error(403, "unexpected Host header")
                return None
            path_part, _, query = self.path.partition("?")
            if self.path.startswith("/__lp/rev/") or query == "lp-rev":
                target = self._safe(self.path[len("/__lp/rev"):] if self.path.startswith("/__lp/rev/") else path_part)
                if target is None or not target.is_file() or target.suffix.lower() != ".html":
                    self.send_error(404)
                    return None
                attributes = _marker_attributes(_head(target)) or {}
                raw_rev = attributes.get("data-rev", "")
                body = json.dumps({"rev": int(raw_rev) if REV_PATTERN.fullmatch(raw_rev) else 0}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return io.BytesIO(body)
            if self._safe(self.path) is None:
                self.send_error(404)
                return None
            return super().send_head()

        def list_directory(self, path):  # noqa: ANN001 - stdlib signature
            directory = Path(path)
            names = sorted(
                entry.name for entry in directory.iterdir()
                if not entry.name.startswith(".") and not entry.is_symlink()
                and entry.is_file() and entry.suffix.lower() == ".html"
                and _marker_attributes(_head(entry)) is not None
            )
            items = "".join(f'<li><a href="{quote(name)}">{html.escape(name)}</a></li>' for name in names)
            body = f'<!doctype html><meta charset="utf-8"><title>课程网页</title><ul>{items}</ul>'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return io.BytesIO(body)

        def end_headers(self):  # noqa: N802 - stdlib name
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format, *items):  # noqa: A002 - stdlib signature
            return

    handler = functools.partial(Handler, directory=str(root))
    return http.server.ThreadingHTTPServer((host, port), handler)


def command_serve(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover - long-running
    repo = _repo(args.repo)
    root = _inside(repo, args.collection, must_exist=False)
    if not root.is_dir():
        raise UsageError(f"collection does not exist: {args.collection}")
    server = make_server(root, args.host, args.port, args.allow_host)
    host, port = server.server_address[:2]
    print(json.dumps({"serving": args.collection, "url": f"http://{host}:{port}/"}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"stopped": True}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lesson_pages.py",
        description="Create, extend, check, find and serve lesson pages. Paths are relative to --repo.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--repo", default=".", help="repository root (default: .)")

    new = sub.add_parser("new", help="create a page from the template; never replaces a file")
    common(new)
    new.add_argument("--page", required=True)
    new.add_argument("--id", required=True, help="stable page id, e.g. the Lesson id")
    new.add_argument("--title", required=True)
    new.add_argument("--course", default="", help="breadcrumb: course or program name")
    new.add_argument("--label", default="", help="breadcrumb: e.g. 第 3 课")
    new.add_argument("--spine", default="", help="main teaching-spine material and version")
    new.add_argument("--source", action="append", default=[], help="initial source entry; repeatable")
    new.add_argument("--lang", default="zh-CN")
    new.add_argument("--fragment", help="initial content file, or - for stdin")
    new.add_argument("--make-parents", action="store_true", help="create the confirmed collection directory")
    new.add_argument("--date", help=argparse.SUPPRESS)

    add = sub.add_parser("add", help="insert a fragment, bump the revision and check")
    common(add)
    add.add_argument("--page", required=True)
    add.add_argument("--id", required=True, help="the page id; must match the page's marker")
    add.add_argument("--fragment", required=True, help="fragment file, or - for stdin")
    where = add.add_mutually_exclusive_group()
    where.add_argument("--into", help="append inside the element with this id (e.g. node-2, glossary-list)")
    where.add_argument("--after", help="insert right after the element with this id")
    add.add_argument("--date", help=argparse.SUPPRESS)

    state = sub.add_parser("state", help="move a question block: open to answered, closed or replaced; answered to closed or replaced")
    common(state)
    state.add_argument("--page", required=True)
    state.add_argument("--id", required=True, help="the page id; must match the page's marker")
    state.add_argument("--question", required=True)
    state.add_argument("--to", required=True, choices=["answered", "closed", "replaced"])
    state.add_argument("--fragment", help="reference points to put inside the question in the same revision (with --to closed)")
    state.add_argument("--date", help=argparse.SUPPRESS)

    render = sub.add_parser("render", help="render TeX and color code that were written into the page by hand")
    common(render)
    render.add_argument("--page", required=True)
    render.add_argument("--id", required=True, help="the page id; must match the page's marker")
    render.add_argument("--date", help=argparse.SUPPRESS)

    check = sub.add_parser("check", help="validate one page")
    common(check)
    check.add_argument("--page", required=True)
    check.add_argument("--anchor", action="append", default=[], help="an id you are about to cite in chat; repeatable")

    outline = sub.add_parser("outline", help="list blocks, line ranges and question states without reading the page")
    common(outline)
    outline.add_argument("--page", required=True)

    find = sub.add_parser("find", help="list lesson pages inside confirmed collections")
    common(find)
    find.add_argument("--in", dest="collection", action="append", required=True)
    find.add_argument("--id")

    serve = sub.add_parser("serve", help="serve one collection read-only on localhost")
    common(serve)
    serve.add_argument("--in", dest="collection", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    serve.add_argument("--allow-host", action="append", default=[],
                       help="extra Host header name to accept, e.g. a forwarded-port domain; repeatable")
    return parser


COMMANDS = {
    "new": command_new,
    "add": command_add,
    "state": command_state,
    "render": command_render,
    "check": command_check,
    "outline": command_outline,
    "find": command_find,
    "serve": command_serve,
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = _parser().parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except UsageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:  # noqa: BLE001 - report every crash as JSON, never a bare traceback
        print(json.dumps({"ok": False, "error": f"internal error {type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "check" and not result.get("ok", False):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
