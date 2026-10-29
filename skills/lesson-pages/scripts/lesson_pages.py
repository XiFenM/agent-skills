#!/usr/bin/env python3
"""Create, extend, check, find and serve lesson pages.

A lesson page is a derived reading surface for a guide-learning lesson. This
tool never decides what to teach and never records progress, evidence or
mastery. Every write touches only the one page named on the command line
(``continue`` also links the new part from that page), refuses symbolic links, refuses to produce a page that fails ``check``, and
refuses to replace a page that changed after it was read. Nothing is staged,
committed or published.
"""
from __future__ import annotations

import argparse
import ast
import base64
import datetime as _dt
import functools
import hashlib
import html
import json
import math
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
SOFT_PAGE_BYTES = 1536 * 1024
MAX_FRAGMENT_BYTES = 256 * 1024
MAX_FIND_BYTES = 4 * 1024 * 1024
# A long lesson continues on <ID>-part2.html, <ID>-part3.html, ... Minutes are content reading minutes as the
# page counts them (about normal reading speed; studying takes longer).
SPLIT_DUE_MINUTES = 30  # from here the next teaching segment starts a new part, unless it finishes the skeleton
SPLIT_LIMIT_MINUTES = 45  # no teaching segment takes a part past this
SPLIT_FILE_BYTES = 1024 * 1024  # a file this large starts a new part at the next segment, whatever the minutes
MAX_PARTS = 9
PART_ID = re.compile(r"^(.+)-part([2-9])$")
PART_LINK_IDS = ("part-prev", "next-part")  # written only by continue
# Ids that chat cites stay unique across all parts of a lesson.
CITABLE_ID = re.compile(r"^(?:node-[0-9]+|q-a?[0-9]+|add-[0-9]+-[0-9]+|fig-[1-9][0-9]*-[A-Za-z0-9_-]+|synthesis|acceptance|practice|recap)$")
ID_ATTRIBUTE = re.compile(r"""\sid\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
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
PACKS_DIR = SKILL_ROOT / "assets" / "packs"
PACK_PREFIX = "lp-pack-"
# Widget packs: a page carries a pack's style and script only while some element uses the class lp-<name>.
PACKS = ("analogy", "anatomy", "derive", "myth", "poster", "replay", "scale", "source-tree", "timeline", "zoom")
PACK_RUNTIME = 3  # the first "lesson-pages runtime vN" that starts widget packs
JS_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")  # what the browser's Number() reads
POSTER_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?")
# A replay trace separates name=value pairs with ASCII whitespace only; trace writes spaces inside values as U+00A0.
TRACE_GAP = re.compile(r"[ \t\n\r\f]+")
TRACE_PAIR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=[^ \t\n\r\f]*")  # an empty string value is written as name=
WIDGET_CLASSES = frozenset({"lp-stepper", "lp-explorer", "lp-toggle", "lp-timer", "lp-live",
                            "lp-analogy", "lp-anatomy", "lp-derive", "lp-replay", "lp-scale", "lp-source-tree", "lp-timeline", "lp-zoom"})
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
LOOKS_DIR = SKILL_ROOT / "assets" / "looks"
LOOK_STYLE_ID = "lp-look"
# The handout look is the template's own; the others carry their stylesheet in #lp-look.
LOOKS = ("handout", "blueprint", "vermilion")
KNOB_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
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


def _source_tree_markup(element: Element) -> list[str]:
    """Keep path ownership, node selection and the no-script outline in agreement."""
    problems: list[str] = []
    repos = [node for node in element.children if node.tag == "section" and "lp-source-repo" in node.classes]
    if element.tag != "figure" or not element.attrs.get("id") or not repos:
        return ["a source browser needs a figure id and one or more section.lp-source-repo"]

    for repo in repos:
        if not repo.attrs.get("id"):
            problems.append("each source repository needs a unique id")
        for tag, cls, label in (("h4", None, "repository name"), ("p", "lp-source-version", "fixed source version"),
                                ("p", "lp-source-about", "repository responsibility")):
            fields = [child for child in repo.children if child.tag == tag and (cls is None or cls in child.classes)]
            if len(fields) != 1 or not fields[0].text().strip():
                problems.append(f"each repository needs one {tag}{'.' + cls if cls else ''} with its {label}")
        outlines = [child for child in repo.children if child.tag == "ul" and "lp-source-outline" in child.classes]
        if len(outlines) != 1:
            problems.append("each repository needs exactly one ul.lp-source-outline")
            continue
        ids: set[str] = set()
        paths: set[str] = set()

        def visit(outline: Element, parent_path: str | None = None) -> None:
            entries = [child for child in outline.children if child.tag == "li"]
            if not entries or len(entries) != len(outline.children):
                problems.append("source directory lists contain one or more li nodes")
            for entry in entries:
                node_id, path, kind = (entry.attrs.get(name, "") for name in ("id", "data-path", "data-kind"))
                if not node_id or node_id in ids:
                    problems.append("each source node needs a unique id")
                ids.add(node_id)
                if (not path or path.startswith("/") or "\\" in path or
                        any(part in {"", ".", ".."} for part in path.rstrip("/").split("/"))):
                    problems.append(f"source data-path={path!r} must be a repository-relative path")
                normalized = path.rstrip("/")
                if normalized in paths:
                    problems.append(f"source path {path!r} appears more than once in one repository")
                paths.add(normalized)
                if parent_path and not normalized.startswith(parent_path + "/"):
                    problems.append(f"source path {path!r} is not inside its parent directory {parent_path!r}")
                if kind not in {"dir", "file", "context"}:
                    problems.append("source data-kind must be dir, file or context")
                if entry.attrs.get("data-main") not in (None, "true", "false"):
                    problems.append("source data-main is true or false when present")
                for tag in ("b", "p"):
                    fields = [child for child in entry.children if child.tag == tag]
                    if len(fields) != 1 or not fields[0].text().strip():
                        problems.append("each source node needs one direct <b> name and one <p> responsibility")
                lists = [child for child in entry.children if child.tag == "ul"]
                if kind == "dir":
                    if len(lists) != 1 or "lp-source-links" in lists[0].classes:
                        problems.append("a source directory needs one child <ul>; use context for an unexpanded side directory")
                    else:
                        visit(lists[0], normalized)
                elif kind == "file":
                    if len(lists) != 1 or "lp-source-links" not in lists[0].classes:
                        problems.append("a source file needs one ul.lp-source-links containing its source links")
                    else:
                        links = [child for child in lists[0].children if child.tag == "li"]
                        if not links or any(not any(node.tag == "a" and node.attrs.get("href") and node.text().strip()
                                                   for node in child.children) for child in links):
                            problems.append("each source link item needs a labeled <a href>")
                elif kind == "context" and lists:
                    problems.append("a context directory is a location cue and has no child list")

        visit(outlines[0])
        if repo.attrs.get("data-start") is not None and repo.attrs["data-start"] not in ids:
            problems.append("repository data-start must name a source node in that repository")
    return problems


def _timeline_markup(element: Element) -> list[str]:
    """A full state per step makes backward and random navigation deterministic."""
    if element.tag != "figure" or not element.attrs.get("id") or "lp-stepper" not in element.classes:
        return ["a timeline needs a figure id and the lp-stepper class"]
    problems: list[str] = []
    if element.attrs.get("data-timeline-kind") not in {"model", "observed"}:
        problems.append("data-timeline-kind is model or observed; explain the source in the caption")
    if element.attrs.get("data-timeline-surface") not in (None, "glass"):
        problems.append("data-timeline-surface is glass or left out")
    canvases = [child for child in element.children if child.tag == "div" and "lp-canvas" in child.classes]
    if len(canvases) != 1 or canvases[0].children or canvases[0].text().strip():
        problems.append("a timeline needs one empty div.lp-canvas; its board comes from the step snapshots")
    lists = [child for child in element.children if child.tag == "ol" and "lp-steps" in child.classes]
    steps = [child for child in lists[0].children if child.tag == "li"] if len(lists) == 1 else []
    if len(steps) < 2:
        return problems + ["a timeline needs one ol.lp-steps with at least two steps"]
    baseline: dict[tuple[str, str], tuple[str, str]] | None = None
    for index, step in enumerate(steps, start=1):
        if not step.attrs.get("data-title", "").strip():
            problems.append(f"timeline step {index} needs a data-title")
        for cls in ("lp-timeline-event", "lp-timeline-dependency"):
            fields = [child for child in step.children if child.tag == "p" and cls in child.classes]
            if len(fields) != 1 or not fields[0].text().strip():
                problems.append(f"timeline step {index} needs one p.{cls}")
        snapshots = [child for child in step.children if child.tag == "ul" and "lp-timeline-state" in child.classes]
        if len(snapshots) != 1:
            problems.append(f"timeline step {index} needs one ul.lp-timeline-state")
            continue
        state: dict[tuple[str, str], tuple[str, str]] = {}
        names: dict[str, str] = {}
        for cell in snapshots[0].children:
            actor, slot = cell.attrs.get("data-actor", ""), cell.attrs.get("data-slot", "")
            if cell.tag != "li" or not ELEMENT_ID_PATTERN.fullmatch(actor) or not ELEMENT_ID_PATTERN.fullmatch(slot):
                problems.append("timeline state items need data-actor/data-slot keys made of letters, digits, - or _")
            if (actor, slot) in state:
                problems.append(f"timeline step {index} repeats actor/slot {actor!r}/{slot!r}")
            if cell.attrs.get("data-status") not in {"idle", "writing", "ready", "reading", "waiting", "done"}:
                problems.append("timeline data-status is idle, writing, ready, reading, waiting or done")
            values: list[str] = []
            for tag, cls in (("span", "lp-timeline-owner"), ("b", "lp-timeline-slot"),
                             ("span", "lp-timeline-value"), ("span", "lp-timeline-signal")):
                fields = [child for child in cell.children if child.tag == tag and cls in child.classes]
                if len(fields) != 1 or fields[0].children or not fields[0].text().strip():
                    problems.append(f"timeline state needs one plain-text {tag}.{cls}")
                values.append(fields[0].text().strip() if fields else "")
            if actor in names and names[actor] != values[0]:
                problems.append("one timeline actor key must keep the same display name")
            names[actor] = values[0]
            state[(actor, slot)] = (values[0], values[1])
        if len(names) < 2:
            problems.append("a timeline snapshot needs at least two actors")
        if baseline is None:
            baseline = state
        elif state != baseline:
            problems.append(f"timeline step {index} must repeat the full actor/slot set and display names from step 1")
    return problems


def _pack_markup(name: str, element: Element, code_lines: Any) -> list[str]:
    """What is wrong with one widget's structure, in the terms references/widget-packs.md uses."""
    kids = element.children
    items = lambda parent, tag="li": [child for child in parent.children if child.tag == tag]  # noqa: E731
    if name == "source-tree":
        return _source_tree_markup(element)
    if name == "timeline":
        return _timeline_markup(element)
    if name == "poster":
        nums = [child for child in kids if "lp-poster-num" in child.classes]
        if not 1 <= len(nums) <= 2:
            return ["a poster needs one or two p.lp-poster-num"]
        if any(not items(num, "b") or not POSTER_NUMBER.fullmatch(items(num, "b")[0].text().strip()) for num in nums):
            return ["each .lp-poster-num needs a <b> holding only a number such as 512 or 2,700, with the unit in <small>"]
    elif name == "scale":
        lists = items(element, "ol")
        entries = items(lists[0]) if len(lists) == 1 else []
        raw = [entry.attrs.get("data-value", "").strip() for entry in entries]
        values = [float(text) if JS_NUMBER.fullmatch(text) else math.nan for text in raw]
        if len(entries) < 2 or not all(value > 0 and math.isfinite(value) for value in values):
            return ["a log scale needs one <ol> with at least two <li data-value> holding positive numbers"]
    elif name == "myth":
        if sum("lp-myth-wrong" in child.classes for child in kids) != 1 or sum("lp-myth-right" in child.classes for child in kids) != 1:
            return ["a myth card needs one .lp-myth-wrong and one .lp-myth-right"]
    elif name == "analogy":
        if sum("lp-analogy-limit" in child.classes for child in kids) != 1:
            return ["an analogy card needs one .lp-analogy-limit saying where the analogy breaks"]
    elif name == "anatomy":
        formulas = [node for node in element.iter() if node.tag == "div" and "tex" in node.classes]
        notes = [node for node in element.iter() if node.tag == "ol" and "lp-terms" in node.classes]
        count = len(items(notes[0])) if len(notes) == 1 else 0
        if len(formulas) != 1 or not 1 <= count <= 6:
            return ["formula anatomy needs one div.tex and one ol.lp-terms with one to six notes"]
        rendered = any("katex" in node.classes for node in formulas[0].iter())
        terms = {cls for node in formulas[0].iter() for cls in node.classes if re.fullmatch(r"lp-t[1-6]", cls)}
        if rendered and terms != {f"lp-t{n}" for n in range(1, count + 1)}:
            return [f"the formula marks {len(terms)} terms with \\tA–\\tF but ol.lp-terms has {count} notes; mark one term per note, in order"]
    elif name == "derive":
        lists = items(element, "ol")
        steps = items(lists[0]) if len(lists) == 1 else []
        if len(steps) < 2 or any(not any(node.tag == "div" and "tex" in node.classes for node in step.iter()) for step in steps):
            return ["a derivation needs one <ol> of at least two steps, each with a div.tex"]
    elif name == "replay":
        blocks = [node for node in element.iter() if node.tag == "pre" and "lp-code" in node.classes]
        traces = [node for node in element.iter() if node.tag == "ol" and "lp-trace" in node.classes]
        if len(blocks) != 1 or len(traces) != 1:
            return ["an execution replay needs one pre.lp-code and one ol.lp-trace"]
        lines, steps, problems = code_lines(blocks[0]), items(traces[0]), []
        if len(steps) < 2:
            problems.append("an execution replay needs at least two trace steps")
        if any(not KNOB_NAME.fullmatch(var) for var in traces[0].attrs.get("data-vars", "").split()):
            problems.append("data-vars lists identifiers separated by spaces")
        for step in steps:
            raw = step.attrs.get("data-line", "")
            if not REV_PATTERN.fullmatch(raw) or int(raw) not in lines:
                problems.append(f"trace step data-line={raw!r} is not a line of its code ({min(lines)}–{max(lines)})")
                break
            if any(not TRACE_PAIR.fullmatch(pair) for pair in TRACE_GAP.split(step.attrs.get("data-set", "")) if pair):
                problems.append("data-set holds name=value pairs separated by spaces; spaces inside a value are written as U+00A0, as trace does")
                break
        return problems
    elif name == "zoom":
        lists = items(element, "ul")
        tops = items(lists[0]) if len(lists) == 1 else []
        problems = []
        if len(tops) != 1:
            problems.append("a system diagram needs one <ul> whose single <li> is the whole system")
        elif any(not items(node, "b") for node in element.iter() if node.tag == "li"):
            problems.append("every part of a system diagram needs its name in a <b>")
        if element.attrs.get("data-domain") not in (None, "hardware", "software"):
            problems.append("data-domain is hardware or software, or left out")
        return problems
    return []


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


def _machine_path(url: str) -> bool:
    """A link that only works on this machine: file:, a drive letter, a /-rooted path or a network path (//host)."""
    local = _normalize_url(url)
    return bool(re.match(r"(?i)file:", local) or re.match(r"[A-Za-z]:/", local) or local.startswith("/"))


def _fragment_target(href: str) -> str | None:
    """The id a same-page link like "#node-2" points to, decoded as a browser does; None for other links."""
    from urllib.parse import unquote

    url = _normalize_url(href)
    return unquote(url[1:]) if url.startswith("#") and len(url) > 1 else None


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
        report.warn("page.size-soft", f"page is {size} bytes, close to the {MAX_PAGE_BYTES}-byte limit; keep later additions to it short")
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
    look = html_elements[0].attrs.get("data-look") if html_elements else None
    look_styles = [node for node in page.by_id.get(LOOK_STYLE_ID, []) if node.tag == "style"]
    if look is not None and look not in LOOKS[1:]:
        report.error("look.unknown", f"data-look={look!r} is not a look; use {' or '.join(LOOKS[1:])}, or leave it out for the handout look")
    elif look is not None and len(look_styles) != 1:
        report.error("look.css", f"data-look=\"{look}\" needs exactly one <style id=\"{LOOK_STYLE_ID}\">; set looks with new --look or the look command")
    elif look is None and look_styles:
        report.error("look.css", f"<style id=\"{LOOK_STYLE_ID}\"> belongs to a look, but <html> has no data-look; set looks with the look command")
    elif look is not None and look_styles[0].text().replace("\r\n", "\n").strip("\n") != _look_style(look):
        report.warn("runtime.drift", f"#{LOOK_STYLE_ID} differs from the {look} look; refresh it with look --to {look}", look_styles[0].line)
    used_packs = _used_packs(page)
    for node in _pack_blocks(page):
        node_id = node.attrs["id"]
        name, kind = _pack_of(node)
        if name is None:
            report.error("pack.unknown", f"#{node_id} is not a widget pack block; new, add, state and render write packs", node.line)
        elif name not in used_packs:
            report.warn("pack.unused", f"#{node_id} belongs to the {name} pack, which nothing on the page uses; render removes it", node.line)
        elif node.text().replace("\r\n", "\n").strip("\n") != _pack_part(name, kind):
            report.warn("runtime.drift", f"#{node_id} differs from the {name} pack; render refreshes it", node.line)
    runtime_version = re.search(r"lesson-pages runtime v([0-9]+)", _block(source, "script", "lp-runtime") or "")
    if used_packs and (runtime_version is None or int(runtime_version.group(1)) < PACK_RUNTIME):
        report.error("pack.runtime", "this page's runtime predates widget packs, so its widgets would never start; put new widgets on a page made with the current template")
    for name in used_packs:
        for kind, tag, block_id in (("css", "style", PACK_PREFIX + name), ("js", "script", PACK_PREFIX + name + "-js")):
            if _pack_part(name, kind) is not None and not any(node.tag == tag for node in page.by_id.get(block_id, [])):
                report.error("pack.missing", f".lp-{name} needs <{tag} id=\"{block_id}\">; write widgets with add, or run render after a hand edit")

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
            elif (element.attrs.get("id") not in {"lp-boot", "lp-runtime"} and not element.attrs.get("id", "").startswith(PACK_PREFIX)
                  and "data-lp-hook" not in element.attrs):
                report.error("script.hook", "page scripts must carry data-lp-hook", element.line)
            elif "data-lp-hook" in element.attrs and any(node.tag == "main" for node in element.ancestors()):
                report.warn("script.placement", "registration hook is inside reading content; render moves it before #lp-runtime", element.line)
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
        machine = [url for attribute in ("src", "poster", "href", "xlink:href", "srcset", "imagesrcset")
                   if attribute in element.attrs and element.tag != "a"
                   for url in (_srcset_urls(element.attrs[attribute]) if attribute.endswith("srcset") else [element.attrs[attribute]])
                   if _machine_path(url)]
        if machine:
            report.error("link.absolute", f"<{element.tag}> uses {machine[0]!r}, which points into this machine's file system; "
                         "inline it or use a relative path", element.line)
        elif element.tag in {"img", "source", "video", "audio"} and element.attrs.get("src") and not _is_external(element.attrs["src"]):
            target = _local_target(page_path, element.attrs["src"])
            if target is not None and not target.is_file():
                report.error("resource.missing", f"{element.attrs['src']!r} does not exist next to the page", element.line)
            elif not element.attrs["src"].startswith("data:"):
                report.warn("resource.local", f"{element.attrs['src']!r} is a separate file; inline it to keep one self-contained page", element.line)

    # Identifiers and links.
    for element_id, nodes in page.by_id.items():
        if len(nodes) > 1:
            report.error("id.duplicate", f"id {element_id!r} is used {len(nodes)} times", nodes[1].line)
    for note in (node for node in page.elements if "lp-note" in node.classes and "data-note-for" in node.attrs):
        anchor_id = note.attrs["data-note-for"].removeprefix("#")
        anchor = page.one(anchor_id)
        if (anchor is None or anchor.start >= note.start or anchor.tag in {"script", "style", "template"}
                or not any(node.tag == "main" for node in anchor.ancestors())):
            report.error("note.target", "data-note-for must name an earlier content element in this page", note.line)
    for element in page.find("a"):
        href = element.attrs.get("href", "")
        value = href or element.attrs.get("xlink:href", "")
        local = _normalize_url(value)
        if _machine_path(local):
            report.error("link.absolute", f"link {value!r} points into this machine's file system; use a relative link (or "
                         "https:// for the web) so the pages still open after the folder moves", element.line)
            continue
        if local.startswith("#"):
            target_id = _fragment_target(href)
            if target_id and target_id not in page.by_id:
                report.error("anchor.missing", f"link {href!r} has no target", element.line)
        elif href and not _is_external(href) and not href.startswith(("mailto:", "data:")):
            target = _local_target(page_path, href)
            if target is not None and not target.exists():
                report.error("link.missing", f"relative link {href!r} does not resolve from the page", element.line)
            elif target is not None and "#" in href:
                from urllib.parse import unquote

                anchor = unquote(href.split("#", 1)[1])
                same = page_path is not None and target.resolve() == page_path.resolve()
                ids = set(page.by_id) if same else _page_ids(target)
                if anchor and ids is not None and anchor not in ids:
                    report.error("link.anchor", f"link {href!r}: {target.name} has no element with id {anchor!r}", element.line)

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

    # A split lesson's page directory still matches the other pages (a hand fix to a title leaves it behind).
    if page_path is not None and marker is not None and page.one("lp-pager") is not None:
        try:
            _lesson, number, parts = _lesson_parts(page_path, marker.attrs.get("data-id", ""))
            if len(parts) > 1 and _pager_only(source, _pager_html(_lesson_directory(parts, {page_path: (source, page)}), number)) != source:
                report.warn("pager.stale", "the page directory in the header is out of date; run render on this page")
        except UsageError:
            pass

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
    elsewhere: dict[str, tuple[str, str]] | None = None
    for element in page.elements:
        target = element.attrs.get("data-reveals")
        if target is None:
            continue
        for question in [part.strip() for part in target.split(",") if part.strip()]:
            if question not in questions:
                if elsewhere is None:
                    # A widget may reveal a question that was asked and closed on an earlier page of the lesson.
                    elsewhere = _lesson_questions(page_path, marker.attrs.get("data-id", "")) if page_path and marker else {}
                found = elsewhere.get(question)
                if found is None:
                    report.error("check.reveal", f"data-reveals names unknown question {question!r}", element.line)
                elif found[1] != "closed":
                    report.error("check.reveal", f"this widget reveals {question} on {found[0]}, which is still {found[1]}", element.line)
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
        if element.tag == "style" and (element.attrs.get("id") in {"lp-base", KATEX_STYLE_ID, LOOK_STYLE_ID}
                                       or element.attrs.get("id", "").startswith(PACK_PREFIX)):
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
    for figure in [*page.find(cls="lp-explorer"), *page.find(cls="lp-live")]:
        figure_id = figure.attrs.get("id", "")
        if not figure_id or not re.search(rf"explorers\s*(?:\[\s*['\"]{re.escape(figure_id)}['\"]\s*\]|\.{re.escape(figure_id)}\b)", scripts):
            kind = "explorer" if "lp-explorer" in figure.classes else "live paragraph"
            report.warn("widget.hook", f"{kind} {figure_id or '(no id)'} has no registered compute function", figure.line)
    # Live paragraphs: each knob lists its values and shows one of them; results are [data-out].
    for box in page.find(cls="lp-live"):
        knobs = [node for node in box.iter() if "data-knob" in node.attrs]
        if not knobs or not any("data-out" in node.attrs for node in box.iter()):
            report.error("live.parts", f"live paragraph {box.attrs.get('id', '(no id)')} needs at least one [data-knob] and one [data-out]", box.line)
        for knob in knobs:
            name = knob.attrs["data-knob"]
            values = [value.strip() for value in knob.attrs.get("data-values", "").split(",") if value.strip()]
            labels = [value.strip() for value in knob.attrs["data-labels"].split(",")] if "data-labels" in knob.attrs else values
            if not KNOB_NAME.fullmatch(name):
                report.error("live.knob", f"data-knob={name!r} must be an identifier such as n or bytes", knob.line)
            elif len(values) < 2 or len(labels) != len(values):
                report.error("live.knob", f"knob {name} needs data-values with at least two values, and as many data-labels if it has them", knob.line)
            elif knob.children or knob.text().strip() not in labels:
                report.error("live.knob", f"knob {name} must show one of its {'labels' if 'data-labels' in knob.attrs else 'values'} as plain text", knob.line)
    for element in page.elements:
        if "data-knob" in element.attrs and not any("lp-live" in node.classes for node in element.ancestors()):
            report.error("live.knob", "[data-knob] works only inside a .lp-live paragraph", element.line)
    for element in page.elements:
        names = [cls[3:] for cls in sorted(element.classes) if cls.startswith("lp-") and cls[3:] in PACKS]
        if names and not any(node.tag in {"head", "template", "script", "style"} for node in element.ancestors()):
            for message in _pack_markup(names[0], element, code_lines):
                report.error("pack.markup", f"{element.attrs.get('id') or '.lp-' + names[0]}: {message}", element.line)
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


ATTRIBUTE_IN_TAG = re.compile(r"""(\s+)([^\s"'=<>/]+)(\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")
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


@functools.lru_cache(maxsize=None)
def _look_style(look: str) -> str:
    return (LOOKS_DIR / f"{look}.css").read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")


def _remove_attribute(start_tag: str, name: str) -> str:
    head = re.match(r"<[A-Za-z][A-Za-z0-9-]*", start_tag)
    assert head is not None
    position = head.end()
    end = len(start_tag) - (2 if start_tag.endswith("/>") else 1)
    while position < end:
        match = ATTRIBUTE_TOKEN.match(start_tag, position, end)
        if match is None or match.end() == position:
            break
        if match.group(1).lower() == name.lower():
            return start_tag[:match.start()] + start_tag[match.end():]
        position = match.end()
    return start_tag


def _apply_look(text: str, look: str) -> str:
    """Point <html data-look> at a look and put its stylesheet in #lp-look; the handout look needs neither."""
    page = Page(text)
    roots = page.find("html")
    bases = [node for node in page.by_id.get("lp-base", []) if node.tag == "style"]
    if not roots or not bases or bases[0].end is None:
        raise UsageError("page has no <html> or #lp-base to attach a look to")
    newline = "\r\n" if "\r\n" in text else "\n"
    blocks = [node for node in page.by_id.get(LOOK_STYLE_ID, []) if node.tag == "style"]
    block = "" if look == "handout" else f'<style id="{LOOK_STYLE_ID}">{newline}{_look_style(look).replace(chr(10), newline)}{newline}</style>'
    if blocks:
        assert blocks[0].end is not None
        start, end = blocks[0].start, blocks[0].end
        if not block and text.startswith(newline, end):
            end += len(newline)
        text = text[:start] + block + text[end:]
    elif block:
        text = text[:bases[0].end] + newline + block + text[bases[0].end:]
    tag = text[roots[0].start:roots[0].start_end]
    edited = _remove_attribute(tag, "data-look") if look == "handout" else _set_attribute(tag, "data-look", look)
    return text[:roots[0].start] + edited + text[roots[0].start_end:]


@functools.lru_cache(maxsize=None)
def _pack_part(name: str, kind: str) -> str | None:
    path = PACKS_DIR / f"{name}.{kind}"
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n") if path.is_file() else None


def _used_packs(page: Page) -> list[str]:
    """Packs whose widget class appears in the page body, in name order."""
    used: set[str] = set()
    for element in page.elements:
        names = {cls[3:] for cls in element.classes if cls.startswith("lp-")} & set(PACKS)
        if names and not any(node.tag in {"head", "template", "script", "style"} for node in element.ancestors()):
            used |= names
    return sorted(used)


def _pack_blocks(page: Page) -> list[Element]:
    return sorted((node for node_id, nodes in page.by_id.items() if node_id.startswith(PACK_PREFIX)
                   for node in nodes if node.tag in {"style", "script"}), key=lambda node: node.start)


def _pack_of(node: Element) -> tuple[str | None, str]:
    """(pack name, "css" or "js") for a pack block, or (None, kind) when the id names no pack."""
    stem = node.attrs.get("id", "")[len(PACK_PREFIX):]
    if node.tag == "script":
        return (stem[:-3] if stem.endswith("-js") and stem[:-3] in PACKS else None), "js"
    return (stem if stem in PACKS else None), "css"


def _place_hooks(text: str) -> str:
    """Move registration hooks out of reading flow, before runtime initialization.

    Keep already-centralized hooks in place and append newly inserted hooks in their
    source order. A script between a figure and a note must never become its layout
    anchor. Moving only misplaced hooks also preserves byte-stable repeated renders.
    """
    page = Page(text)
    hooks = [node for node in page.find("script") if "data-lp-hook" in node.attrs]
    if not hooks:
        return text
    runtime = next((node for node in page.by_id.get("lp-runtime", []) if node.tag == "script"), None)
    if runtime is None:
        raise UsageError("page has no #lp-runtime to put registration hooks before")
    boot = next((node for node in page.by_id.get("lp-boot", []) if node.tag == "script"), None)
    moved = [node for node in hooks if any(parent.tag == "main" for parent in node.ancestors())
             or node.start > runtime.start or (boot is not None and node.start < boot.start)]
    if not moved:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    blocks = [text[node.start:node.end] for node in moved]
    for node in reversed(moved):
        if node.end is None:
            raise UsageError("a registration hook is missing </script>")
        end = node.end + (len(newline) if text.startswith(newline, node.end) else 0)
        text = text[:node.start] + text[end:]
    runtime = Page(text).one("lp-runtime")
    assert runtime is not None
    return text[:runtime.start] + newline.join(blocks) + newline + text[runtime.start:]


def _ensure_packs(text: str) -> str:
    """Give the page the style and script of each widget pack it uses, refresh stale copies and drop unused ones.

    Styles go after #lp-look (or #lp-base), scripts right before #lp-runtime, both in pack-name order,
    so a page that already has the right packs comes back unchanged.
    """
    text = _place_hooks(text)
    page = Page(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    for node in reversed(_pack_blocks(page)):
        if _pack_of(node)[0] is None:
            continue
        assert node.end is not None
        end = node.end + (len(newline) if text.startswith(newline, node.end) else 0)
        text = text[:node.start] + text[end:]
    page = Page(text)
    used = _used_packs(page)
    block = lambda tag, block_id, body: f'<{tag} id="{block_id}">{newline}{body.replace(chr(10), newline)}{newline}</{tag}>'  # noqa: E731
    styles = [block("style", PACK_PREFIX + name, css) for name in used if (css := _pack_part(name, "css")) is not None]
    scripts = [block("script", PACK_PREFIX + name + "-js", js) for name in used if (js := _pack_part(name, "js")) is not None]
    if styles:
        anchor = next((node for node in [*page.by_id.get(LOOK_STYLE_ID, []), *page.by_id.get("lp-base", [])] if node.tag == "style"), None)
        if anchor is None or anchor.end is None:
            raise UsageError("page has no #lp-base to put widget styles after")
        text = text[:anchor.end] + newline + newline.join(styles) + text[anchor.end:]
        page = Page(text)
    if scripts:
        runtime = next((node for node in page.by_id.get("lp-runtime", []) if node.tag == "script"), None)
        if runtime is None:
            raise UsageError("page has no #lp-runtime to put widget scripts before")
        text = text[:runtime.start] + newline.join(scripts) + newline + text[runtime.start:]
    return text


def _prepare_fragment(fragment: str, page: Page, rev: int, elsewhere: dict[str, str] | None = None, *,
                      reserved: Iterable[str] = PART_LINK_IDS) -> tuple[str, list[tuple[str, str]], list[str], dict[str, Any], list[str]]:
    """Validate a fragment, render its formulas and code, and stamp its blocks with ``rev``.

    ``elsewhere`` maps the ids on the lesson's other parts to their files: cited
    ids may not repeat there, and ``href="#id"`` pointing to one of them is
    rewritten to ``file#id``. Returns the main HTML, the parts routed with
    ``<template data-lp-into>`` as ``(target id, html)`` pairs, every new element
    id, what was rendered, and the links rewritten.
    """
    elsewhere = elsewhere or {}
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
    # A link to a block on an earlier page of the lesson names that page's file.
    own = {element.attrs["id"] for element in parsed.elements if "id" in element.attrs}
    targets = {node.start: _fragment_target(node.attrs.get("href", "")) for node in parsed.find("a")}
    moved = [node for node in parsed.find("a") if targets[node.start] and targets[node.start] not in page.by_id
             and targets[node.start] not in own and targets[node.start] in elsewhere]
    relinked = sorted({f"{node.attrs['href']} -> {elsewhere[targets[node.start]]}#{targets[node.start]}" for node in moved})
    if moved:
        fragment = _edit_start_tags(fragment, {
            node.start: (node.start_end, {"href": f"{elsewhere[targets[node.start]]}#{targets[node.start]}"}) for node in moved
        })
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
    taken = sorted({element_id for element_id in new_ids if CITABLE_ID.fullmatch(element_id) and element_id in elsewhere})
    if taken:
        raise UsageError("ids already used on other pages of this lesson: "
                         + ", ".join(f"{element_id} ({elsewhere[element_id]})" for element_id in taken))
    generated = sorted(set(new_ids) & set(reserved))
    if generated:
        raise UsageError(", ".join(generated) + " link the pages of a long lesson; continue writes them")
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
    return "\n".join(main), routed, new_ids, rendered, relinked


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
    """Text a reader reads: no scripts, styles, ruby annotations or the MathML copy KaTeX keeps for screen readers."""
    parts: list[str] = []
    stack: list[str | Element] = list(reversed(element.chunks))
    while stack:
        chunk = stack.pop()
        if isinstance(chunk, Element):
            if chunk.tag not in {"script", "style", "template", "rt", "rp"} and "katex-mathml" not in chunk.classes:
                stack.extend(reversed(chunk.chunks))
        else:
            parts.append(chunk)
    return "".join(parts)


def _text_minutes(text: str) -> float:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+", re.sub(r"[\u3400-\u9fff]", " ", text)))
    return cjk / 320 + words / 180


def reading_minutes(html_text: str) -> int:
    return max(1, round(_text_minutes(_visible_text(Page(html_text).root))))


def _content_minutes(blocks: Iterable[Element]) -> float:
    """Unrounded reading minutes of lesson content: not the glossary, sources, contents or the links between parts."""
    return sum(
        _text_minutes(_visible_text(block)) for block in blocks
        if block.tag not in {"style", "script", "template"} and "lp-toc-inline" not in block.classes
        and block.attrs.get("id") not in {"glossary", "sources", *PART_LINK_IDS}
    )


def page_minutes(page: Page) -> float:
    mains = [node for node in page.find("main") if "lp-main" in node.classes]
    return _content_minutes(mains[0].children) if mains else 0.0


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
    for code in page.elements:
        in_main = mains and any(node is mains[0] for node in code.ancestors())
        if code.tag in {"style", "script"} and (in_main or "data-lp-hook" in code.attrs):
            owner = next((node.attrs.get("id", "") for node in code.ancestors() if mains and node.parent is mains[0]), "")
            page_code.append({"tag": code.tag, "lines": lines(code), **({"inside": owner} if owner else {})})
    if mains:
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
            pack_of = lambda node: next((pack for pack in PACKS if "lp-" + pack in node.classes), None)  # noqa: E731
            figures = [
                {"id": node.attrs.get("id", ""), **({"kind": "live"} if node.tag != "figure" else {}),
                 **({"kind": pack_of(node)} if node.tag == "figure" and pack_of(node) else {}),
                 **({"reveals": node.attrs["data-reveals"]} if "data-reveals" in node.attrs else {})}
                for node in element.iter() if node.tag == "figure" or "lp-live" in node.classes
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
        "page_minutes": round(page_minutes(page)),
        "look": (page.find("html")[0].attrs.get("data-look") if page.find("html") else None) or "handout",
        "packs": _used_packs(page),
        "head_style_lines": lines(style[0]) if style else None,
        "page_code": page_code,
        "append_marker_line": line_of(source.index(APPEND_MARKER)) if APPEND_MARKER in source else None,
        "blocks": blocks,
    }


# --------------------------------------------------------------------------
# Parts: a long lesson continues on <ID>-part2.html, <ID>-part3.html, ...
# --------------------------------------------------------------------------


def _marker_id(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        attributes = _marker_attributes(_head(path))
    except OSError:
        return None
    return attributes.get("data-id") if attributes else None


def _part_path(path: Path, lesson: str, number: int) -> Path:
    return path.parent / (f"{lesson}.html" if number == 1 else f"{lesson}-part{number}.html")


def _part_of(path: Path, page_id: str) -> tuple[str, int]:
    """The lesson a page belongs to and its part number; <ID>-partN.html continues <ID>.html in the same folder."""
    match = PART_ID.fullmatch(page_id)
    if match and _marker_id(path.parent / f"{match.group(1)}.html") == match.group(1):
        lesson, number = match.group(1), int(match.group(2))
        try:
            facts = _facts(path)
        except (OSError, UnicodeDecodeError):
            facts = None
        if facts is not None and facts[1] == _part_path(path, lesson, number - 1).name:
            return lesson, number
    return page_id, 1


def _lesson_parts(path: Path, page_id: str) -> tuple[str, int, list[tuple[int, Path]]]:
    """(lesson id, this page's part number, every part of the lesson in order). Parts are numbered without gaps."""
    lesson, number = _part_of(path, page_id)
    if path.name != _part_path(path, lesson, number).name:
        return lesson, number, [(number, path)]  # a copy under another name stands alone
    parts: list[tuple[int, Path]] = []
    for n in range(1, MAX_PARTS + 1):
        candidate = _part_path(path, lesson, n)
        expected = lesson if n == 1 else f"{lesson}-part{n}"
        if candidate.resolve() == path.resolve() or (_marker_id(candidate) == expected and (n == 1 or _part_of(candidate, expected) == (lesson, n))):
            parts.append((n, candidate))
        elif n > 1:
            break
    return lesson, number, parts


@functools.lru_cache(maxsize=32)
def _parsed_facts(path: str, _mtime: int, _size: int) -> tuple[frozenset[str], str | None, tuple[tuple[str, str, str, str], ...]] | None:
    source = Path(path).read_bytes().decode("utf-8", errors="replace")  # writing it reports a broken encoding
    if _marker_attributes(source[:16384]) is None:
        return None
    page = Page(source)
    back = page.one("part-prev")
    previous = next((node.attrs.get("href") for node in (back.iter() if back else [])
                     if node.tag == "a" and node.attrs.get("rel") == "prev"), None)
    return frozenset(page.by_id), previous, tuple(_directory_entries(page, source))


def _facts(path: Path) -> tuple[frozenset[str], str | None, tuple[tuple[str, str, str, str], ...]] | None:
    """(ids, link back to the previous part, directory entries) of another lesson page; None when it is not one.
    Raises OSError or UnicodeDecodeError when the file cannot be read."""
    if path.suffix.lower() != ".html" or path.is_symlink() or not path.is_file():
        return None
    status = path.stat()
    if status.st_size > MAX_PAGE_BYTES:
        return None
    return _parsed_facts(str(path.resolve()), status.st_mtime_ns, status.st_size)


def _page_ids(path: Path) -> frozenset[str] | None:
    """Every element id of another lesson page, or None when the file is not a lesson page."""
    try:
        facts = _facts(path)
    except (OSError, UnicodeDecodeError):
        return None
    return facts[0] if facts else None


def _elsewhere(path: Path, parts: list[tuple[int, Path]]) -> dict[str, str]:
    """Ids on the lesson's other parts, mapped to the first file that has them."""
    found: dict[str, str] = {}
    for _number, other in parts:
        if other.resolve() == path.resolve():
            continue
        for element_id in sorted(_page_ids(other) or ()):
            found.setdefault(element_id, other.name)
    return found


def _lesson_questions(page_path: Path, page_id: str) -> dict[str, tuple[str, str]]:
    """Question states on the lesson's other parts: id -> (file, state)."""
    _lesson, _number, parts = _lesson_parts(page_path, page_id)
    found: dict[str, tuple[str, str]] = {}
    for _n, other in parts:
        if other.resolve() == page_path.resolve():
            continue
        try:
            source, _data = _read(other)
        except (OSError, UsageError):
            continue
        for element in Page(source).find(cls="lp-check"):
            if element.attrs.get("id"):
                found.setdefault(element.attrs["id"], (other.name, element.attrs.get("data-state", "")))
    return found


def _split_ids(value: str) -> set[str]:
    return {part for part in re.split(r"[\s,]+", value) if part}


def _finishes_skeleton(page: Page, nodes: list[Element]) -> bool:
    """True when these nodes teach every skeleton stage that no earlier node (here or on an earlier part) taught."""
    stages = {node.attrs["id"] for node in page.find("li") if "id" in node.attrs
              and node.parent is not None and "lp-stages" in node.parent.classes}
    earlier = [*page.find(cls="lp-node"), *_other_page_links(page)]
    taught = set().union(*(_split_ids(node.attrs.get("data-stages", "")) for node in earlier))
    remaining = stages - taught
    return bool(remaining) and remaining <= set().union(*(_split_ids(node.attrs.get("data-stages", "")) for node in nodes))


def _split_reason(page: Page, size: int, segment: str) -> str | None:
    """Why a teaching segment appended to this part belongs on a new part, or None when it fits here."""
    fragment = Page(segment)
    nodes = fragment.find(cls="lp-node")
    adding = _content_minutes(fragment.root.children)
    if nodes and adding > SPLIT_LIMIT_MINUTES:
        raise UsageError(f"this segment alone reads about {round(adding)} minutes, past the {SPLIT_LIMIT_MINUTES}-minute limit "
                         "of a page; nothing was written. Write it in smaller segments, one add each")
    if not nodes or not page.find(cls="lp-node"):
        return None
    current = page_minutes(page)
    if size >= SPLIT_FILE_BYTES:
        return f"this page is already {size} bytes"
    if current + adding > SPLIT_LIMIT_MINUTES:
        return (f"this page holds about {round(current)} reading minutes and this segment adds about {round(adding)}, "
                f"past the {SPLIT_LIMIT_MINUTES}-minute limit")
    if current >= SPLIT_DUE_MINUTES and not _finishes_skeleton(page, nodes):
        return f"this page already holds about {round(current)} reading minutes"
    return None


def _no_split(path: Path, page_id: str, page: Page, lesson: str, number: int) -> str | None:
    """Why this page cannot continue on another page, or None when it can."""
    if number == 1 and lesson.startswith("qa-") and page.one("intro") is None:
        return "a Q&A page stays one page"
    if path.name != _part_path(path, lesson, number).name:
        return f"this page is not named {_part_path(path, lesson, number).name}, so no later page could find it"
    if number >= MAX_PARTS:
        return f"this lesson is at its {MAX_PARTS}-page limit; ask the learner whether to split the lesson itself"
    return None


def _node_label(element: Element, source: str) -> tuple[str, str]:
    """A node's number and its heading as inline HTML (formulas and code kept; number, badges, links and ids left out)."""
    heading = next((child for child in element.children if child.tag == "h2"), None)
    if heading is None or heading.end_start is None:
        return "", html.escape(element.attrs.get("id", ""))
    number = next((node for node in heading.iter() if "lp-no" in node.classes), None)
    cut = sorted((node.start, node.end or node.start) for node in heading.iter() if {"lp-no", "lp-new", "lp-kind"} & node.classes)
    pieces, cursor = [], heading.start_end
    for begin, finish in cut:
        if begin >= cursor:
            pieces.append(source[cursor:begin])
            cursor = finish
    pieces.append(source[cursor:heading.end_start])
    inline = re.sub(r"</?a\b[^>]*>", "", "".join(pieces))
    drop = lambda attribute: "" if attribute.group(2).lower() in {"id", "data-rev"} else attribute.group(0)  # noqa: E731
    inline = re.sub(r"<[A-Za-z][^>]*>", lambda tag: ATTRIBUTE_IN_TAG.sub(drop, tag.group(0)), inline)
    return (number.text().strip() if number is not None else ""), re.sub(r"\s+", " ", inline).strip()


def _main_of(page: Page) -> Element | None:
    return next((node for node in page.find("main") if "lp-main" in node.classes), None)


def _nodes_of(page: Page) -> list[Element]:
    main = _main_of(page)
    return [node for node in (main.iter() if main else []) if "lp-node" in node.classes and node.attrs.get("id")]


def _without_revs(markup: str) -> str:
    return re.sub(r'\sdata-rev="[0-9]*"', "", markup)


def _style_classes(css: str) -> set[str]:
    return set(re.findall(r"\.([A-Za-z_][\w-]*)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))


def _carried_styles(parts: list[tuple[str, str, Page]], classes: set[str], present: set[str]) -> list[str]:
    """Fragment styles written on earlier pages (not their copies) that define one of ``classes`` and are not here yet."""
    found: dict[str, str] = {}
    for name, source, page in parts:
        main = _main_of(page)
        for style in (node for node in (main.iter() if main else []) if node.tag == "style" and "data-lp-style" in node.attrs):
            css = style.text().strip()
            if "data-lp-copy" not in style.attrs and css not in present and classes & _style_classes(css):
                found.setdefault(css, _copy_of(source, style, name))
    return list(found.values())


def _with_carried_styles(path: Path, source: str, page: Page, parts: list[tuple[int, Path]], number: int,
                         fragment: str) -> tuple[str, int]:
    """On a later page, put in front of the fragment the earlier pages' styles for the classes it uses."""
    parsed = Page(fragment)
    if number < 2 or not any(node.tag != "template" for node in parsed.root.children):
        return fragment, 0
    used = {name for node in parsed.elements for name in node.classes if not name.startswith("lp-")}
    present = {node.text().strip() for node in [*page.find("style"), *parsed.find("style")] if "data-lp-style" in node.attrs}
    carried = _carried_styles(_earlier_parts(path, source, page, parts, number - 1), used, present) if used else []
    return "\n".join([*carried, fragment]), len(carried)


def _copy_of(source: str, entry: Element, name: str) -> str:
    """An entry copied from ``name``, marked so later copies are taken from the original, not from this copy."""
    start = _set_attribute(source[entry.start:entry.start_end], "data-lp-copy", name)
    return _without_revs(start + source[entry.start_end:entry.end])


def _opening(parts: list[tuple[str, str, Page]], number: int, first_no: str, classes: set[str], defined: set[str],
             present: set[str]) -> str:
    """The generated start of part ``number``: a link back, the skeleton and the earlier nodes, plus copies of the
    glossary entries and sources (taken from the pages that wrote them) and of the fragment styles defining ``classes``."""
    previous = parts[-1][0]
    first_name, first_source, first_page = parts[0]
    lines = ['<section class="lp-narrative" id="part-prev">', f"  <h2>接第 {number - 1} 页</h2>"]
    spine = f'资料怎样配合着读见第 1 页的<a href="{first_name}#spine">资料指路</a>。' if first_page.one("spine") is not None else ""
    start = f"从节点 {html.escape(first_no)} 讲起" if first_no else "接着讲"
    lines.append(f'  <p>这是本课的第 {number} 页，接着<a rel="prev" href="{previous}">第 {number - 1} 页</a>{start}。'
                 f"前面各页讲了什么，展开页头的分页目录就能看到并跳过去。{spine}</p>")
    skeleton = first_page.one("fig-0")
    stages = next((child for child in skeleton.children if child.tag == "ol" and "lp-stages" in child.classes), None) if skeleton else None
    if skeleton is not None and stages is not None:
        caption = next((child for child in skeleton.children if child.tag == "figcaption"), None)
        lines.append("  " + _without_revs(first_source[skeleton.start:skeleton.start_end]))
        lines.append("    " + _without_revs(first_source[stages.start:stages.end]))
        if caption is not None:
            lines.append("    " + _without_revs(first_source[caption.start:caption.end]))
        lines.append("  </figure>")
    lines.append("</section>")
    # Copies come from the page that wrote each entry, so a fix made there reaches every later copy.
    glossary: dict[str, str] = {}
    sources: dict[str, str] = {}
    for name, source, page in parts:
        listing = page.one("glossary-list")
        for entry in (listing.children if listing is not None else []):
            if entry.attrs.get("id") and "data-lp-copy" not in entry.attrs and entry.attrs["id"] not in defined:
                glossary[entry.attrs["id"]] = _copy_of(source, entry, name)
        listing = page.one("sources-list")
        for entry in (listing.children if listing is not None else []):
            if entry.tag == "li" and "data-lp-copy" not in entry.attrs:
                sources.setdefault(re.sub(r"\s+", " ", entry.text()).strip(), _copy_of(source, entry, name))
    if glossary:
        lines += ['<template data-lp-into="glossary-list">', *glossary.values(), "</template>"]
    if sources:
        lines += ['<template data-lp-into="sources-list">', *sources.values(), "</template>"]
    return "\n".join([*_carried_styles(parts, classes, present), *lines])


def _next_part_block(name: str, number: int, first: Element, source: str) -> str:
    no, title = _node_label(first, source)
    return (f'<section class="lp-narrative" id="next-part">\n  <h2>接第 {number} 页</h2>\n'
            f'  <p>这一课在<a rel="next" href="{name}#{first.attrs["id"]}">第 {number} 页</a>接着讲，'
            f"从{f'节点 {html.escape(no)}' if no else ''}「{title}」开始。</p>\n</section>")


def _directory_entries(page: Page, source: str) -> list[tuple[str, str, str, str]]:
    """(id, number, title as inline HTML, data-stages) of what a page directory lists: nodes, synthesis and acceptance."""
    main = _main_of(page)
    return [(node.attrs["id"], *_node_label(node, source), node.attrs.get("data-stages", ""))
            for node in (main.iter() if main else [])
            if node.attrs.get("id") and ("lp-node" in node.classes or node.attrs["id"] in {"synthesis", "acceptance"})]


def _lesson_directory(parts: list[tuple[int, Path]], current: dict[Path, tuple[str, Page]]) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """Each page's file name and entries; pages being written are taken from ``current`` (path -> (source, page))."""
    directory = []
    for _n, part in parts:
        written = next((value for key, value in current.items() if key.resolve() == part.resolve()), None)
        if written is not None:
            entries = _directory_entries(written[1], written[0])
        else:
            try:
                facts = _facts(part)
            except (OSError, UnicodeDecodeError) as exc:
                raise UsageError(f"{part.name}, another page of this lesson, cannot be read ({type(exc).__name__}); fix or move it, "
                                 "then retry") from exc
            if facts is None:
                raise UsageError(f"{part.name} is not a lesson page any more; restore it, then retry")
            entries = list(facts[2])
        directory.append((part.name, entries))
    return directory


def _pager_html(directory: list[tuple[str, list[tuple[str, str, str, str]]]], number: int) -> str:
    """Page ``number``'s directory block: previous and next page, and every page with what it teaches. Links are relative."""
    total = len(directory)
    row = []
    if number > 1:
        row.append(f'<a rel="prev" href="{directory[number - 2][0]}">‹ 第 {number - 1} 页</a>')
    row.append(f"<span>第 {number} 页，共 {total} 页</span>")
    if number < total:
        row.append(f'<a rel="next" href="{directory[number][0]}">第 {number + 1} 页 ›</a>')
    lines = ['<nav class="lp-pager" id="lp-pager" aria-label="本课分页">', f'  <p class="lp-pager-row">{"".join(row)}</p>',
             '  <details class="lp-pager-list">', "    <summary>分页目录：各页讲了什么</summary>", "    <ol>"]
    for k, (name, entries) in enumerate(directory, start=1):
        here = k == number
        items = "".join(
            f'<li><a href="{"" if here else name}#{element_id}"'
            + (f' data-stages="{html.escape(stages)}"' if stages else "")
            + f"><b>{html.escape(no)}</b><span>{title}</span></a></li>"
            for element_id, no, title, stages in entries)
        current = ' aria-current="page"' if here else ""
        listing = f"<ol>{items}</ol>" if items else ""
        lines.append(f'      <li{current}><a href="{"#top" if here else name}">第 {k} 页</a>{listing}</li>')
    lines += ["    </ol>", "  </details>", "</nav>"]
    return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def _pager_css() -> str:
    lines = [line for line in (_template_blocks().get("lp-base") or "").splitlines() if line.startswith(".lp-pager")]
    return "\n".join([*lines, ".lp-cover :focus-visible { outline-color: var(--band-ink); }",
                      "@media print { .lp-pager-list { display: none !important; } }"])


def _pager_of(source: str) -> Element | None:
    found = Page(source).one("lp-pager")
    return found if found is not None and found.tag == "nav" and found.end is not None else None


def _with_pager(source: str, pager: str) -> str:
    """The page with its directory block replaced (see _pager_only), plus the KaTeX fonts its titles need."""
    return _ensure_katex(_pager_only(source, pager))


def _pager_only(source: str, pager: str) -> str:
    """The page with its directory block replaced, or put under the header's meta line; a page whose stylesheet predates
    the directory gets the directory's styles inside the block."""
    if ".lp-pager-row" not in (_block(source, "style", "lp-base") or ""):
        pager = pager.replace(">", f">\n  <style data-lp-style>\n{_pager_css()}\n  </style>", 1)
    newline = "\r\n" if "\r\n" in source else "\n"
    pager = pager.replace("\n", newline)
    current = _pager_of(source)
    if current is not None:
        return source[:current.start] + pager + source[current.end:]
    meta = next((node for node in Page(source).find("div", cls="lp-meta") if any(a.tag == "header" for a in node.ancestors())), None)
    if meta is None or meta.end is None:
        raise UsageError("the page header has no .lp-meta line to put the page directory under")
    return source[:meta.end] + newline + "      " + pager + source[meta.end:]


def _other_page_links(page: Page) -> list[Element]:
    """The directory's links to nodes on the lesson's other pages."""
    pager = page.one("lp-pager")
    items = [node for node in (pager.iter() if pager else []) if node.tag == "li" and node.parent is not None
             and node.parent.parent is not None and "lp-pager-list" in node.parent.parent.classes]
    return [link for item in items if "aria-current" not in item.attrs for link in item.iter() if link.tag == "a" and link.attrs.get("data-stages")]


def _refresh_pagers(repo: Path, parts: list[tuple[int, Path]], directory: list[tuple[str, list[tuple[str, str, str, str]]]],
                    skip: set[Path], date: str) -> tuple[list[str], list[str]]:
    """Bring the directory on the lesson's other pages up to date; returns (pages refreshed, pages that could not be)."""
    refreshed, stale = [], []
    skipped = {item.resolve() for item in skip}
    for number, part in parts:
        if part.resolve() in skipped:
            continue
        try:
            source, data = _read(part)
            text = _with_pager(source, _pager_html(directory, number))
            if text == source:
                continue
            # Only the navigation changed, so the page keeps its revision, date and 本次新增.
            report, _scripts = full_check(text, part)
            if report.errors:
                raise UsageError("the result would fail check: " + "; ".join(f"{item['code']}: {item['message']}" for item in report.errors[:3]))
            _replace(part, data, text)
            refreshed.append(part.relative_to(repo).as_posix())
        except (UsageError, OSError, ValueError) as exc:
            stale.append(f"{part.relative_to(repo).as_posix()}: {exc}; run render on that page to retry")
    return refreshed, stale


def _refresh_runtime(source: str) -> str | None:
    """The page with the current template's tool-owned blocks, when its runtime is of the same generation; else None."""
    version = re.search(r"lesson-pages runtime v([0-9]+)", _block(source, "script", "lp-runtime") or "")
    if version is None or int(version.group(1)) < PACK_RUNTIME:
        return None
    newline = "\r\n" if "\r\n" in source else "\n"
    for tag, element_id in (("style", "lp-base"), ("script", "lp-boot"), ("script", "lp-runtime")):
        fresh = _template_blocks()[element_id].replace("\n", newline)
        source = re.sub(rf'(<{tag}\b[^>]*\bid="{element_id}"[^>]*>)(.*?)(</{tag}>)',
                        lambda match: match.group(1) + fresh + match.group(3), source, count=1, flags=re.S)
    return source


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def command_new(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    if not ID_PATTERN.fullmatch(args.id) or len(args.id) > 64:
        raise UsageError("--id must be a lowercase hyphen id of at most 64 characters")
    if PART_ID.fullmatch(args.id):
        raise UsageError("ids ending in -part2 to -part9 are kept for the later pages of a long lesson; choose another id "
                         "(for example -p2) and say so in the lesson confirmation")
    if not LANG_PATTERN.fullmatch(args.lang):
        raise UsageError("--lang must be a language tag such as zh-CN")
    path = _page_path(repo, args.page, must_exist=False, writing=True)
    if path.name != f"{args.id}.html":
        raise UsageError(f"the file name is the page id: name the page {args.id}.html")
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
        main, routed, fragment_ids, rendered, _relinked = _prepare_fragment(_read_fragment(args.fragment), shell, 1)
        text = _ensure_katex(_insert(text, shell, main, routed, marker=CONTENT_MARKER))
    else:
        rendered = {"tex": 0, "code": 0}
    text = text.replace(CONTENT_MARKER + "\n", "").replace(CONTENT_MARKER, "")
    text = _ensure_packs(_apply_look(text, args.look))
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
        "look": args.look,
        "inserted_ids": fragment_ids,
        "rendered": rendered,
        "reading_minutes": reading_minutes(text.split('<main', 1)[-1]),
        "page_minutes": round(page_minutes(Page(text))),
        "check": report.as_dict(),
        "scripts": scripts,
    }


def _on_other_part(page: Page, element_id: str | None, elsewhere: dict[str, str], command: str) -> None:
    if element_id and page.one(element_id) is None and element_id in elsewhere:
        raise UsageError(f"#{element_id} is on {elsewhere[element_id]}, another page of this lesson; run {command} on that page")


def _not_a_copy(page: Page, element_id: str | None) -> None:
    """Glossary entries and sources copied from an earlier page are supplemented where they were written."""
    element = page.one(element_id) if element_id else None
    copy = next((node for node in ([element, *element.ancestors()] if element else []) if node.attrs.get("data-lp-copy")), None)
    if copy is not None:
        raise UsageError(f"#{copy.attrs.get('id', element_id)} on this page is a copy of the entry on {copy.attrs['data-lp-copy']}; "
                         "supplement it there, and pages made later copy it from there")


def _routed_targets(fragment: str) -> list[str]:
    return [node.attrs.get("data-lp-into", "") for node in Page(fragment).root.children if node.tag == "template"]


def _earlier_parts(path: Path, source: str, page: Page, parts: list[tuple[int, Path]], upto: int) -> list[tuple[str, str, Page]]:
    """(file name, source, parsed page) of parts 1 to ``upto``; ``path`` is the page already read as ``source``."""
    earlier = []
    for n, part in parts:
        if n > upto:
            break
        if part.resolve() == path.resolve():
            earlier.append((part.name, source, page))
        else:
            part_source = _read(part)[0]
            earlier.append((part.name, part_source, Page(part_source)))
    return earlier


def command_add(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    lesson, number, parts = _lesson_parts(path, args.id)
    elsewhere = _elsewhere(path, parts)
    fragment = _read_fragment(args.fragment)
    targets = _routed_targets(fragment)
    for target in (args.into or args.after, *targets):
        _on_other_part(page, target, elsewhere, "add")
        _not_a_copy(page, target)
    appends = args.into is None and args.after is None
    has_main = any(node.tag != "template" for node in Page(fragment).root.children)
    if appends and number < len(parts) and has_main:
        raise UsageError(f"{path.name} continues on {parts[number][1].name}; append new blocks to the last page, "
                         f"{parts[-1][1].name}, and put supplements into their node with --into")
    fragment, carried = _with_carried_styles(path, source, page, parts, number, fragment)
    new_rev = rev + 1
    main, routed, ids, rendered, relinked = _prepare_fragment(fragment, page, new_rev, elsewhere)
    reason = _split_reason(page, len(data), main) if main and appends else None
    blocked = _no_split(path, args.id, page, lesson, number) if reason else None
    if reason and not blocked:
        following = _part_path(path, lesson, number + 1).relative_to(repo).as_posix()
        message = (f"{reason}, so this teaching segment starts a new page; nothing was written. Run the same command "
                   f"with continue in place of add; it creates {following}")
        local = [target for target in targets if target not in {"glossary-list", "sources-list"}]
        if local:
            message += (f". The fragment also routes parts into {', '.join('#' + target for target in local)} on this page: "
                        "add those parts here first, then continue with the rest")
        broken = full_check(source, path)[0].errors
        if broken:
            message += ". This page already fails check, which would also stop continue: " + "; ".join(
                f"{item['code']}: {item['message']}" for item in broken[:3])
        raise UsageError(message)
    text = _ensure_packs(_ensure_katex(_insert(source, page, main, routed, marker=APPEND_MARKER, into=args.into, after=args.after)))
    written = Page(text)
    directory = _lesson_directory(parts, {path: (text, written)}) if len(parts) > 1 else []
    if directory:
        text = _with_pager(text, _pager_html(directory, number))
        written = Page(text)
    text = _bump(text, written, new_rev, _today(args.date))
    result = _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"inserted_ids": ids, "anchors": ["#" + element_id for element_id in ids], "rendered": rendered,
                          **({"relinked": relinked} if relinked else {}),
                          **({"carried_styles": carried} if carried else {}),
                          **({"note": f"{reason}, but {blocked}; the segment stays on this page"} if blocked else {}),
                          "reading_minutes": reading_minutes(main + "".join(part for _target, part in routed)),
                          "page_minutes": round(page_minutes(written))})
    return _with_refreshed(result, repo, parts, directory, {path}, _today(args.date))


def _with_refreshed(result: dict[str, Any], repo: Path, parts: list[tuple[int, Path]],
                    directory: list[tuple[str, list[tuple[str, str, str, str]]]], skip: set[Path], date: str) -> dict[str, Any]:
    if not directory:
        return result
    refreshed, stale = _refresh_pagers(repo, parts, directory, skip, date)
    return {**result, **({"directory_refreshed": refreshed} if refreshed else {}), **({"directory_stale": stale} if stale else {})}


def _linked_text(path: Path, source: str, page: Page, rev: int, following: Path, number: int, first: Element,
                 first_source: str, date: str, pager: str) -> tuple[str, bool]:
    """This page with #next-part appended, its directory updated, and the current runtime when its runtime is of the
    same generation."""
    main, routed, _ids, _rendered, _relinked = _prepare_fragment(_next_part_block(following.name, number, first, first_source),
                                                                 page, rev + 1, reserved=())
    text = _with_pager(_ensure_katex(_insert(source, page, main, routed, marker=APPEND_MARKER)), pager)
    refreshed = _refresh_runtime(text)
    text = _bump(refreshed or text, Page(refreshed or text), rev + 1, date)
    return text, refreshed is not None


def _first_node(page: Page) -> Element | None:
    return next(iter(_nodes_of(page)), None)


PAGE_STYLE_FROM = "/* 以下照抄第 1 页的 #lp-page-style，改动写在第 1 页 */"
PAGE_STYLE_END = "/* 以上照抄第 1 页 */"
RUNTIME_KEPT = ("this page keeps an older runtime, so its header still says 全文约 and stations taught on later pages are not "
                "linked from it (they show 未开通, or no mark on the oldest pages); its 接第 N 页 block still leads on")


def command_continue(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    lesson, number, parts = _lesson_parts(path, args.id)
    rel = lambda target: target.relative_to(repo).as_posix()  # noqa: E731 - tiny local helper
    if path.name != _part_path(path, lesson, number).name:
        raise UsageError(f"continue works on {_part_path(path, lesson, number).name}; {path.name} is a copy under another name")
    if number == 1 and lesson.startswith("qa-") and page.one("intro") is None:
        raise UsageError("a Q&A page stays one page; continue is for lessons")
    following = _part_path(path, lesson, number + 1)
    date = _today(args.date)
    if not args.fragment:
        # Repair: the next part was written but the link to it from this page was not.
        if page.one("next-part") is not None or _marker_id(following) != f"{lesson}-part{number + 1}":
            raise UsageError(f"nothing to repair: {path.name} has no unlinked next page; pass --fragment to start one")
        later_source, _later_data = _read(following)
        later = Page(later_source)
        back = later.one("part-prev")
        first = _first_node(later)
        if back is None or first is None or not any(node.tag == "a" and node.attrs.get("rel") == "prev"
                                                    and node.attrs.get("href") == path.name for node in back.iter()):
            raise UsageError(f"{following.name} does not start by linking back to {path.name} with a node after it; link it by hand")
        whole = parts if any(part.resolve() == following.resolve() for _n, part in parts) else [*parts, (number + 1, following)]
        directory = _lesson_directory(whole, {})
        text, refreshed = _linked_text(path, source, page, rev, following, number + 1, first, later_source, date,
                                       _pager_html(directory, number))
        result = _finish(path, data, text, page_rel=rel(path), rev=rev + 1, extra={"linked": rel(following)})
        result = _with_refreshed(result, repo, whole, directory, {path}, date)
        return {**result, **({} if refreshed else {"note": RUNTIME_KEPT})}
    if number < len(parts):
        raise UsageError(f"{path.name} already continues on {parts[number][1].name}; continue from the last page, {parts[-1][1].name}")
    if following.exists():
        raise UsageError(f"{rel(following)} already exists and is not part of this lesson; move it away first")
    if number + 1 > MAX_PARTS:
        raise UsageError(f"a lesson has at most {MAX_PARTS} pages; ask the learner whether to split the lesson itself")
    fragment = _read_fragment(args.fragment)
    probe = Page(fragment)
    first_raw = next((node for node in probe.find(cls="lp-node") if node.attrs.get("id")), None)
    if first_raw is None:
        raise UsageError("continue starts a new page with a teaching segment, but the fragment has no .lp-node with an id")
    earlier = _earlier_parts(path, source, page, parts, number)
    elsewhere = _elsewhere(following, parts)
    for target in _routed_targets(fragment):
        if target not in {"glossary-list", "sources-list"} and target in elsewhere:
            raise UsageError(f"the fragment routes a part into #{target}, which is on {elsewhere[target]}; add that part there "
                             "first, then continue with the rest")
    # The header repeats page 1's title, crumb, spine line and language with the page number; the look is the last page's.
    first_name, first_source, first_page = earlier[0]
    title = next(iter(first_page.find("h1", cls="lp-title")), None)
    crumb = next(iter(first_page.find("p", cls="lp-crumb")), None)
    titles = first_page.find("title")
    meta = next(iter(first_page.find("div", cls="lp-meta")), None)
    crumb_html = first_source[crumb.start_end:crumb.end_start].strip() if crumb is not None and crumb.end_start else ""
    title_full = titles[0].text().strip() if titles else lesson
    label = f"第 {number + 1} 页"
    roots, first_roots = page.find("html"), first_page.find("html")
    values = {
        "lang": html.escape(first_roots[0].attrs.get("lang", "zh-CN") if first_roots else "zh-CN", quote=True),
        "id": f"{lesson}-part{number + 1}",
        "key": secrets.token_hex(6),
        "date": date,
        "title_full": html.escape(f"{title_full} · {label}"),
        "title": first_source[title.start_end:title.end_start] if title is not None and title.end_start else html.escape(lesson),
        "crumb": f"{crumb_html} · {label}" if crumb_html else label,
        "spine": "\n        ".join(first_source[node.start:node.end] for node in (meta.children if meta else [])
                                   if node.tag == "p" and "data-lp-auto" not in node.attrs),
        "sources": "",
    }
    text = SLOT_PATTERN.sub(lambda match: values[match.group(1)], TEMPLATE.read_text(encoding="utf-8"))
    # Page-wide adjustments: page 1's current ones (a fix there reaches pages made later), then those the last page wrote itself.
    own = _block(source, "style", "lp-page-style") or "" if number > 1 else ""
    own = re.sub(re.escape(PAGE_STYLE_FROM) + r".*?" + re.escape(PAGE_STYLE_END) + r"\n?", "", own, flags=re.S)
    own = own.replace(_block(TEMPLATE.read_text(encoding="utf-8"), "style", "lp-page-style") or "\0", "").strip("\n")
    first_css = (_block(first_source, "style", "lp-page-style") or "").strip("\n")
    css = f"\n{PAGE_STYLE_FROM}\n{first_css}\n{PAGE_STYLE_END}\n" + (own + "\n" if own.strip() else "")
    text = re.sub(r'(<style id="lp-page-style">)(.*?)(</style>)', lambda match: match.group(1) + css + match.group(3),
                  text, count=1, flags=re.S)
    shell = Page(text)
    used = {name for node in probe.elements for name in node.classes if not name.startswith("lp-")}
    defined = {node.attrs["id"] for node in probe.elements if node.attrs.get("id")}
    own_styles = {node.text().strip() for node in probe.find("style") if "data-lp-style" in node.attrs}
    opening = _opening(earlier, number + 1, _node_label(first_raw, fragment)[0], used, defined, own_styles)
    main, routed, _ids, _rendered, _relinked = _prepare_fragment(opening, shell, 1, elsewhere, reserved=())
    text = _insert(text, shell, main, routed, marker=CONTENT_MARKER)
    shell = Page(text)
    main, routed, ids, rendered, relinked = _prepare_fragment(fragment, shell, 2, elsewhere)
    reason = _split_reason(page, len(data), main)
    if reason is None:
        raise UsageError(f"{path.name} still has room for this segment (about {round(page_minutes(page))} reading minutes so far); "
                         "use add")
    text = _insert(text, shell, main, routed, marker=CONTENT_MARKER)
    text = text.replace(CONTENT_MARKER + "\n", "").replace(CONTENT_MARKER, "")
    look = (roots[0].attrs.get("data-look") if roots else None) or "handout"
    text = _ensure_packs(_apply_look(_ensure_katex(text), look))
    whole = [*parts, (number + 1, following)]
    directory = _lesson_directory(whole, {following: (text, Page(text))})
    text = _with_pager(text, _pager_html(directory, number + 1))
    written = Page(text)
    text = _bump(text, written, 2, date)
    report, scripts = full_check(text, following)
    if report.errors:
        raise UsageError("the new page would fail check; nothing was written:\n"
                         + "\n".join(f"  {item['code']}: {item['message']}" for item in report.errors))
    first = _first_node(written)
    assert first is not None  # the segment's node is on the new page
    # Check the previous page with its link before anything is written; only the link to the page not yet written may fail.
    linked, refreshed = _linked_text(path, source, page, rev, following, number + 1, first, text, date, _pager_html(directory, number))
    blocking = [item for item in full_check(linked, path)[0].errors
                if not (item["code"] in {"link.missing", "link.anchor"} and following.name in item["message"])]
    if blocking:
        raise UsageError(f"{path.name} already fails check, so it could not link the new page; nothing was written. Fix it first:\n"
                         + "\n".join(f"  {item['code']}: {item['message']}" for item in blocking))
    _write_new(following, text)
    try:
        previous = _finish(path, data, linked, page_rel=rel(path), rev=rev + 1, extra={})
    except UsageError as exc:
        raise UsageError(f"{rel(following)} was written, but linking it from {path.name} failed: {exc}\nRun continue "
                         f"--page {rel(path)} --id {args.id} without --fragment to add the link") from exc
    result = {
        "page": rel(following),
        "id": values["id"],
        "part": number + 1,
        "rev": 2,
        "look": look,
        "inserted_ids": ids,
        "anchors": ["#" + element_id for element_id in ids],
        "rendered": rendered,
        **({"relinked": relinked} if relinked else {}),
        "reading_minutes": reading_minutes(main + "".join(part for _target, part in routed)),
        "page_minutes": round(page_minutes(written)),
        "check": report.as_dict(),
        "scripts": scripts,
        "previous": {"page": previous["page"], "rev": previous["rev"], "check": previous["check"],
                     **({} if refreshed else {"note": RUNTIME_KEPT})},
    }
    return _with_refreshed(result, repo, whole, directory, {path, following}, date)


def command_state(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    _lesson, number, parts = _lesson_parts(path, args.id)
    elsewhere = _elsewhere(path, parts)
    _on_other_part(page, args.question, elsewhere, "state")
    element = page.one(args.question)
    if element is None or "lp-check" not in element.classes:
        raise UsageError(f"no question block with id {args.question!r}")
    current = element.attrs.get("data-state", "")
    if (current, args.to) not in TRANSITIONS:
        raise UsageError(f"{args.question} cannot move from {current or '(none)'} to {args.to}")
    new_rev = rev + 1
    text = _edit_start_tags(source, {element.start: (element.start_end, {"data-state": args.to, "data-rev": str(new_rev)})})
    ids: list[str] = []
    carried = 0
    if args.fragment:
        if args.to != "closed":
            raise UsageError("--fragment adds reference points, so it only goes with --to closed")
        edited = Page(text)
        fragment = _read_fragment(args.fragment)
        for target in _routed_targets(fragment):
            _on_other_part(edited, target, elsewhere, "add")
            _not_a_copy(edited, target)
        fragment, carried = _with_carried_styles(path, text, edited, parts, number, fragment)
        main, routed, ids, _rendered, _relinked = _prepare_fragment(fragment, edited, new_rev, elsewhere)
        text = _ensure_packs(_ensure_katex(_insert(text, edited, main, routed, marker=APPEND_MARKER, into=args.question)))
    text = _bump(text, Page(text), new_rev, _today(args.date))
    return _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"question": args.question, "state": args.to, "inserted_ids": ids,
                          **({"carried_styles": carried} if carried else {})})


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    blocks = [node for node in page.by_id.get(KATEX_STYLE_ID, []) if node.tag == "style"]
    outdated = bool(blocks) and _katex_block_version(blocks[0].text()) != KATEX_VERSION
    text, rendered = _render_fragment(source, page, force=outdated)
    text = _ensure_packs(_ensure_katex(text, redrawn=outdated))
    _lesson, number, parts = _lesson_parts(path, args.id)
    directory = _lesson_directory(parts, {path: (text, Page(text))}) if len(parts) > 1 else []
    if directory:
        text = _with_pager(text, _pager_html(directory, number))
    if text == source:
        result = {"page": path.relative_to(repo).as_posix(), "rev": rev, "rendered": rendered, "changed": False}
    elif directory and _with_pager(source, _pager_html(directory, number)) == text:
        # Only the navigation changed, as in a refresh of the other pages: keep the revision, date and 本次新增.
        report, scripts = full_check(text, path)
        if report.errors:
            raise UsageError("the result would fail check; nothing was written:\n"
                             + "\n".join(f"  {item['code']}: {item['message']}" for item in report.errors))
        _replace(path, data, text)
        result = {"page": path.relative_to(repo).as_posix(), "rev": rev, "rendered": rendered, "changed": True,
                  "check": report.as_dict(), "scripts": scripts}
    else:
        new_rev = rev + 1
        text = _bump(text, Page(text), new_rev, _today(args.date))
        result = _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                         extra={"rendered": rendered, "changed": True})
    return _with_refreshed(result, repo, parts, directory, {path}, _today(args.date))


def command_look(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path, source, data, page, rev = _load_page(repo, args.page, args.id)
    text = _apply_look(source, args.to)
    if text == source:
        return {"page": path.relative_to(repo).as_posix(), "rev": rev, "look": args.to, "changed": False}
    new_rev = rev + 1
    text = _bump(text, Page(text), new_rev, _today(args.date))
    return _finish(path, data, text, page_rel=path.relative_to(repo).as_posix(), rev=new_rev,
                   extra={"look": args.to, "changed": True})


# The replay trace is recorded by running the example in a separate isolated Python process.
TRACER = r'''
import json, math, sys
request = json.loads(sys.stdin.read())
names, function, limit = request["vars"], request["function"], request["limit"]
SKIP = {"<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>", "<lambda>"}
GENERATOR = 0x20 | 0x80 | 0x200
events, calls, serial = [], {}, [0]
class Stop(Exception):
    pass
def show(value):
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value in (math.inf, -math.inf):
            return ("−" if value < 0 else "") + "∞"
        if value == 0:
            return "0"
        # Four decimals; below 0.001 (and from 1e10 up) four significant digits instead, so no small value prints as 0.
        if abs(value) < 1e-3 or abs(value) >= 1e10:
            text = "%.4g" % value
        else:
            text = ("%.4f" % value).rstrip("0").rstrip(".")
        if "e" in text:
            mantissa, power = text.split("e")
            text = mantissa + "e" + str(int(power))
        return text.replace("-", "−")
    if isinstance(value, int):
        return str(value).replace("-", "−")
    if isinstance(value, (list, tuple)):
        inner = ",".join(show(item) for item in value)
        return "[" + inner + "]" if isinstance(value, list) else "(" + inner + ")"
    return "".join("\u00a0" if ch.isspace() else ch for ch in str(value))
def tracer(frame, event, arg):
    code = frame.f_code
    if code.co_filename != "<lesson-trace>" or code.co_name in SKIP or (function and code.co_name != function):
        return tracer
    # CPython reuses a finished frame's id, so each call gets its own number; generator frames are kept so a resumed
    # generator keeps its number.
    known = calls.get(id(frame))
    if known is None or known[0] is not frame:
        serial[0] += 1
        known = calls[id(frame)] = (frame, serial[0])
    if event in ("line", "return"):
        state = {name: show(frame.f_locals[name]) for name in names if name in frame.f_locals}
        if event == "return" and "return" in names:
            state["return"] = show(arg)
        events.append([event, frame.f_lineno, known[1], state])
        if event == "return" and not code.co_flags & GENERATOR:
            del calls[id(frame)]
        if len(events) > limit:
            raise Stop()
    return tracer
error = None
compiled = compile(request["source"], "<lesson-trace>", "exec")
sys.settrace(tracer)
try:
    exec(compiled, {"__name__": "__lesson_trace__"})
except Stop:
    error = "limit"
except BaseException as exc:
    error = "%s: %s" % (type(exc).__name__, exc)
finally:
    sys.settrace(None)
print(json.dumps({"events": events, "error": error}, ensure_ascii=False))
'''


def _crowded_loops(source: str) -> set[int]:
    """Lines where a loop body sits on the line each pass comes back to: the for line, or the line of the while test."""
    return {node.body[0].lineno for node in ast.walk(ast.parse(source))
            if (isinstance(node, (ast.For, ast.AsyncFor)) and node.body[0].lineno == node.lineno)
            or (isinstance(node, ast.While) and node.body[0].lineno == node.test.lineno)}


def command_trace(args: argparse.Namespace) -> dict[str, Any]:
    """Run a short example and list, line by line, what each executed line changed among the chosen variables."""
    names = args.vars.split()
    if not names or any(not KNOB_NAME.fullmatch(name) for name in names):
        raise UsageError('--vars must list identifiers separated by spaces, e.g. "m l acc" (add return for the return value)')
    source = _lf(Path(args.code).read_text(encoding="utf-8-sig"))
    try:
        result = subprocess.run([sys.executable, "-I", "-c", TRACER], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                input=json.dumps({"source": source, "vars": names, "function": args.function, "limit": args.max_steps}),
                                check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise UsageError("the example ran longer than 30 seconds; trace a smaller case") from exc
    try:
        report = json.loads(result.stdout)
    except ValueError as exc:
        raise UsageError("the example could not be traced: " + (result.stderr.strip().splitlines() or ["no output"])[-1]) from exc
    if report["error"] and report["error"] != "limit":
        raise UsageError(f"the example raised {report['error']}; fix it before recording a trace")
    events = report["events"]
    # Such a line is reported again on every pass and a repeated line merges into one step below, so the replay would
    # skip the whole loop. The source compiled in the run, so it parses here.
    crowded = sorted(_crowded_loops(source) & {line for event, line, _frame, _state in events if event == "line"})
    if crowded:
        raise UsageError("a loop body shares a line with its for/while header (line " + ", ".join(map(str, crowded))
                         + "), so the whole loop would replay as one step; put the body on its own line")
    steps: list[dict[str, Any]] = []
    entered: set[int] = set()
    for index, (event, line, frame, before) in enumerate(events):
        if event != "line":
            continue
        later_index = next((n for n in range(index + 1, len(events)) if events[n][2] == frame), None)
        if later_index is not None and any(events[n][2] != frame for n in range(index + 1, later_index)):
            raise UsageError("a traced line runs another traced frame (recursion, or module code calling the function), so the steps "
                             "would come out of order; trace one function that does not call itself, with --function")
        after = events[later_index][3] if later_index is not None else before
        call = 0
        if frame not in entered:
            # Arguments are already bound when the frame starts; report them on its first line. From the second call on,
            # the step is numbered so the replay clears what the earlier call left in the table.
            entered.add(frame)
            before = {}
            call = len(entered) if steps else 0
        # A line reported several times in a row (an inlined comprehension) is one step.
        if steps and steps[-1]["line"] == line and steps[-1]["frame"] == frame:
            merged = steps.pop()
            before, call = merged["before"], merged["call"]
        steps.append({"line": line, "frame": frame, "before": before, "call": call,
                      "set": {name: value for name, value in after.items() if before.get(name) != value}})
    rows = [{"line": step["line"], **({"call": step["call"]} if step["call"] else {}), "set": step["set"]} for step in steps]
    html_rows = [f'<li data-line="{row["line"]}"' + (f' data-call="{row["call"]}"' if "call" in row else "")
                 + (' data-set="' + html.escape(" ".join(f"{k}={v}" for k, v in row["set"].items())) + '"' if row["set"] else "")
                 + "></li>" for row in rows]
    return {"steps": rows, "count": len(rows), "truncated": report["error"] == "limit", "code_lines": len(source.rstrip("\n").split("\n")),
            "html": "\n".join(html_rows)}


def command_check(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path = _page_path(repo, args.page, must_exist=True)
    source, _data = _read(path)
    report, scripts = full_check(source, path)
    page = Page(source)
    marker = page.marker()
    elsewhere = _elsewhere(path, _lesson_parts(path, marker.attrs.get("data-id", ""))[2]) if args.anchor and marker else {}
    for anchor in args.anchor:
        element_id = anchor.lstrip("#")
        if element_id in elsewhere and element_id not in page.by_id:
            report.error("anchor.cited", f"#{element_id} is on {elsewhere[element_id]}, not this page; link that file in chat")
        elif element_id not in page.by_id:
            report.error("anchor.cited", f"#{element_id} does not exist; do not cite it in chat")
    result = {"page": path.relative_to(repo).as_posix(), **report.as_dict()}
    result["scripts"] = scripts
    return result


def command_outline(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo(args.repo)
    path = _page_path(repo, args.page, must_exist=True)
    source, _data = _read(path)
    result = {"page": path.relative_to(repo).as_posix(), **outline_source(source)}
    lesson, number, parts = _lesson_parts(path, result["id"])
    if len(parts) > 1:
        # One call shows every page of a long lesson: where each block is, and the next free numbers.
        summary = []
        numbers = {"node": 0, "q": 0, "q-a": 0}
        for n, part in parts:
            part_page = Page(source if part == path else _read(part)[0])
            main = _main_of(part_page)
            blocks = [node.attrs["id"] for node in (main.children if main else []) if node.attrs.get("id")
                      and node.attrs["id"] not in {"glossary", "sources"} and node.tag not in {"style", "script"}]
            questions = {node.attrs["id"]: node.attrs.get("data-state", "") for node in part_page.find(cls="lp-check") if node.attrs.get("id")}
            for element_id in [*blocks, *questions]:
                found = re.fullmatch(r"(node|q-a|q)-?([0-9]+)", element_id)
                if found:
                    numbers[found.group(1)] = max(numbers[found.group(1)], int(found.group(2)))
            summary.append({"page": part.relative_to(repo).as_posix(), "id": lesson if n == 1 else f"{lesson}-part{n}", "part": n,
                            "page_minutes": round(page_minutes(part_page)),
                            "blocks": blocks, "questions": questions})
        result["lesson"] = {"id": lesson, "part": number, "parts": summary,
                            "next": {"node": numbers["node"] + 1, "q": numbers["q"] + 1, "q-a": numbers["q-a"] + 1}}
    return result


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
                head_page = Page(head)
                marker = head_page.marker()
                if marker is None:
                    continue
                attributes = dict(marker.attrs)
                roots = head_page.find("html")
                if args.id and attributes.get("data-id") != args.id:
                    continue
                lesson, part = _part_of(candidate, attributes.get("data-id", ""))
                if args.lesson and lesson != args.lesson:
                    continue
                title = re.search(r"<title>(.*?)</title>", head, re.S)
                pages.append({
                    "page": candidate.relative_to(repo).as_posix(),
                    "id": attributes.get("data-id", ""),
                    "lesson": lesson,
                    "part": part,
                    **({"misnamed": True} if candidate.name != _part_path(candidate, lesson, part).name else {}),
                    "rev": int(attributes["data-rev"]) if REV_PATTERN.fullmatch(attributes.get("data-rev", "")) else None,
                    "updated": attributes.get("data-updated", ""),
                    "title": html.unescape(title.group(1).strip()) if title else "",
                    "look": (roots[0].attrs.get("data-look") if roots else None) or "handout",
                })
    # A lesson's pages are listed in reading order: page 1, then part 2, part 3, ...
    pages.sort(key=lambda item: (PurePosixPath(item["page"]).parent.as_posix(), item["lesson"], item.get("misnamed", False),
                                 item["part"], item["page"]))
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
            pages = []
            for entry in directory.iterdir():
                if entry.name.startswith(".") or entry.is_symlink() or not entry.is_file() or entry.suffix.lower() != ".html":
                    continue
                attributes = _marker_attributes(_head(entry))
                if attributes is not None:
                    pages.append((*_part_of(entry, attributes.get("data-id", "")), entry.name))
            names = [name for _lesson, _part, name in sorted(pages)]  # a lesson's pages in reading order
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
    new.add_argument("--page", required=True, help="page path relative to --repo")
    new.add_argument("--id", required=True, help="stable page id, e.g. the Lesson id")
    new.add_argument("--title", required=True)
    new.add_argument("--course", default="", help="breadcrumb: course or program name")
    new.add_argument("--label", default="", help="breadcrumb: e.g. 第 3 课")
    new.add_argument("--spine", default="", help="main teaching-spine material and version")
    new.add_argument("--source", action="append", default=[], help="initial source entry; repeatable")
    new.add_argument("--lang", default="zh-CN")
    new.add_argument("--look", default="handout", choices=LOOKS, help="page look; keep one look per course (default: handout)")
    new.add_argument("--fragment", help="initial content file, or - for stdin")
    new.add_argument("--make-parents", action="store_true", help="create the confirmed collection directory")
    new.add_argument("--date", help=argparse.SUPPRESS)

    add = sub.add_parser("add", help="insert a fragment, bump the revision and check")
    common(add)
    add.add_argument("--page", required=True, help="page path relative to --repo")
    add.add_argument("--id", required=True, help="the page id; must match the page's marker")
    add.add_argument("--fragment", required=True, help="fragment file, or - for stdin")
    where = add.add_mutually_exclusive_group()
    where.add_argument("--into", help="append inside the element with this id (e.g. node-2, glossary-list)")
    where.add_argument("--after", help="insert right after the element with this id")
    add.add_argument("--date", help=argparse.SUPPRESS)

    cont = sub.add_parser("continue", help="start the next page of a long lesson with a teaching segment, and link it from this page")
    common(cont)
    cont.add_argument("--page", required=True, help="the lesson's last page, relative to --repo")
    cont.add_argument("--id", required=True, help="the page id; must match the page's marker")
    cont.add_argument("--fragment", help="the teaching segment that add refused; without it, only a missing link is repaired")
    cont.add_argument("--date", help=argparse.SUPPRESS)

    state = sub.add_parser("state", help="move a question block: open to answered, closed or replaced; answered to closed or replaced")
    common(state)
    state.add_argument("--page", required=True, help="page path relative to --repo")
    state.add_argument("--id", required=True, help="the page id; must match the page's marker")
    state.add_argument("--question", required=True)
    state.add_argument("--to", required=True, choices=["answered", "closed", "replaced"])
    state.add_argument("--fragment", help="reference points to put inside the question in the same revision (with --to closed)")
    state.add_argument("--date", help=argparse.SUPPRESS)

    render = sub.add_parser("render", help="render TeX and color code that were written into the page by hand")
    common(render)
    render.add_argument("--page", required=True, help="page path relative to --repo")
    render.add_argument("--id", required=True, help="the page id; must match the page's marker")
    render.add_argument("--date", help=argparse.SUPPRESS)

    look = sub.add_parser("look", help="switch a page to another look, or refresh its look stylesheet")
    common(look)
    look.add_argument("--page", required=True, help="page path relative to --repo")
    look.add_argument("--id", required=True, help="the page id; must match the page's marker")
    look.add_argument("--to", required=True, choices=LOOKS)
    look.add_argument("--date", help=argparse.SUPPRESS)

    trace = sub.add_parser("trace", help="run a short Python example and list what each executed line changed, for an execution replay")
    trace.add_argument("--code", required=True, help="the example file; put the same text in the replay's pre.lp-code")
    trace.add_argument("--vars", required=True, help='variables to record, space-separated, e.g. "m l acc"; add return for the return value')
    trace.add_argument("--function", help="record only the lines run inside this function")
    trace.add_argument("--max-steps", type=int, default=400, help="stop recording after this many executed lines (default: 400)")

    check = sub.add_parser("check", help="validate one page")
    common(check)
    check.add_argument("--page", required=True, help="page path relative to --repo")
    check.add_argument("--anchor", action="append", default=[], help="an id you are about to cite in chat; repeatable")

    outline = sub.add_parser("outline", help="list blocks, line ranges and question states without reading the page")
    common(outline)
    outline.add_argument("--page", required=True, help="page path relative to --repo")

    find = sub.add_parser("find", help="list lesson pages inside confirmed collections")
    common(find)
    find.add_argument("--in", dest="collection", action="append", required=True)
    find.add_argument("--id")
    find.add_argument("--lesson", help="every page of one lesson, in reading order")

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
    "continue": command_continue,
    "state": command_state,
    "render": command_render,
    "look": command_look,
    "trace": command_trace,
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
