#!/usr/bin/env python3
"""Discover, preview, extract, and safely archive visible learning dialogue.

This is an internal, machine-facing CLI used by the study-log skill.  It only
uses the Python standard library and emits one stable JSON envelope per call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Sequence, cast
from urllib.parse import unquote


SCHEMA_VERSION = 1
NORMALIZATION_VERSION = "study-log-visible-v1"
REDACTION_VERSION = "study-log-redaction-v1"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_AMBIGUOUS = 4
EXIT_INTEGRITY = 5
EXIT_SAFETY = 6
EXIT_CONFLICT = 7
EXIT_MALFORMED = 8

ERROR_EXIT_CODES = {
    "usage": EXIT_USAGE,
    "not_found": EXIT_NOT_FOUND,
    "ambiguous": EXIT_AMBIGUOUS,
    "integrity": EXIT_INTEGRITY,
    "safety": EXIT_SAFETY,
    "conflict": EXIT_CONFLICT,
    "malformed": EXIT_MALFORMED,
}

VISIBLE_ROLES = {"user", "assistant"}
TEXT_CONTENT_TYPES = {"input_text", "output_text", "text"}
PROVIDERS = {"auto", "claude", "codex"}

COMMON_STRIP_PATTERNS = (
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
    re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.DOTALL),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.DOTALL),
    re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
    re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
    re.compile(r"<ide_selection>.*?</ide_selection>", re.DOTALL),
)
CODEX_STRIP_PATTERNS = (
    re.compile(r"<recommended_plugins>.*?</recommended_plugins>", re.DOTALL),
    re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL),
    re.compile(
        r"# AGENTS\.md instructions for [^\n]+\s*<INSTRUCTIONS>.*?</INSTRUCTIONS>",
        re.DOTALL,
    ),
)
STANDALONE_SKILL_CONTEXT_RE = re.compile(r"<skill>.*?</skill>", re.DOTALL)
IDE_CONTEXT_PREFIX = "# Context from my IDE setup:"
IDE_REQUEST_HEADING_RE = re.compile(
    r"^(?:## My request for Codex:|# My request:|## My request:)\r?$", re.MULTILINE
)
COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    kind: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class StudyLogError(Exception):
    """A stable, user-safe CLI failure."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if kind not in ERROR_EXIT_CODES:
            raise ValueError(f"unknown error kind: {kind}")
        self.spec = ErrorSpec(kind, message, details or {})

    @property
    def exit_code(self) -> int:
        return ERROR_EXIT_CODES[self.spec.kind]


class JsonArgumentParser(argparse.ArgumentParser):
    """Turn argparse failures into the CLI's stable error envelope."""

    def error(self, message: str) -> None:
        raise StudyLogError("usage", message)


@dataclass(frozen=True, slots=True)
class ParsedRow:
    line_number: int
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SessionRef:
    provider: str
    path: Path
    session_id: str
    project: str


@dataclass(frozen=True, slots=True)
class DialogueMessage:
    message_id: str
    timestamp: str
    role: str
    phase: str | None
    text: str
    source_line: int
    is_tool: bool = False


@dataclass(frozen=True, slots=True)
class SessionData:
    ref: SessionRef
    source_sha256: str
    source_size: int
    messages: tuple[DialogueMessage, ...]
    warnings: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Selection:
    messages: tuple[DialogueMessage, ...]
    start_message_id: str
    end_message_id: str


@dataclass(frozen=True, slots=True)
class PrivacyReport:
    categories: tuple[str, ...]
    counts: dict[str, int]


def _schema_string_field(
    mapping: dict[str, Any],
    key: str,
    *,
    context: str,
    line_number: int | None = None,
    required: bool = False,
) -> str | None:
    if key not in mapping:
        if not required:
            return None
        raise StudyLogError(
            "malformed",
            f"{context}.{key} must be a string",
            details={"field": f"{context}.{key}", "line": line_number},
        )
    value = mapping[key]
    if not isinstance(value, str):
        raise StudyLogError(
            "malformed",
            f"{context}.{key} must be a string",
            details={
                "field": f"{context}.{key}",
                "line": line_number,
                "json_type": type(value).__name__,
            },
        )
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyLogError(
            "integrity", f"cannot read file for hashing: {path}", details={"path": str(path)}
        ) from exc


def _canonical_project(project: str | Path) -> str:
    raw = os.path.expandvars(os.path.expanduser(str(project)))
    if not raw.strip():
        raise StudyLogError("usage", "--project cannot be empty")
    path = Path(raw)
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise StudyLogError("usage", f"cannot resolve project path: {project}") from exc
    return os.path.normcase(os.path.normpath(str(resolved)))


def _project_identity(project: str | Path) -> str:
    canonical = _canonical_project(project)
    identity = canonical.replace("\\", "/")
    return identity.casefold() if os.name == "nt" else identity


def _same_project(left: str | Path, right: str | Path) -> bool:
    return _project_identity(left) == _project_identity(right)


def _project_fingerprint(project: str) -> str:
    return hashlib.sha256(_project_identity(project).encode("utf-8")).hexdigest()[:12]


def _project_name(project: str) -> str:
    name = Path(project).name or Path(project).drive.rstrip(":") or "project"
    cleaned = re.sub(r"[^\w.-]+", "-", name, flags=re.UNICODE).strip("-._")
    return (cleaned or "project")[:48]


def claude_project_slugs(project: str | Path) -> tuple[str, ...]:
    """Return known Claude project-directory encodings for a host-native path."""

    canonical = _canonical_project(project)
    slash = canonical.replace("\\", "/")
    encoded = re.sub(r"[:/.]", "-", slash)

    candidates = {encoded}
    if slash.startswith("/"):
        candidates.add("-" + slash.strip("/").replace("/", "-").replace(".", "-"))
    else:
        candidates.add(
            slash.replace(":", "-").replace("/", "-").replace(".", "-")
        )
    return tuple(sorted(item for item in candidates if item))


def _codex_sessions_root() -> Path:
    override = os.environ.get("STUDY_LOG_CODEX_SESSIONS_DIR")
    return Path(override).expanduser() if override else Path.home() / ".codex" / "sessions"


def _claude_projects_root() -> Path:
    override = os.environ.get("STUDY_LOG_CLAUDE_PROJECTS_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "projects"


def _probe_codex_ref(source: Path, project: str) -> SessionRef | None:
    """Read only Codex session metadata while filtering unrelated projects."""

    try:
        with source.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    value: object = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise StudyLogError(
                        "malformed",
                        f"invalid Codex metadata JSON on line {line_number}",
                        details={"source": str(source), "line": line_number},
                    ) from exc
                if not isinstance(value, dict):
                    raise StudyLogError(
                        "malformed",
                        f"Codex JSONL record on line {line_number} must be an object",
                        details={"source": str(source), "line": line_number},
                    )
                if value.get("type") != "session_meta":
                    continue
                payload = value.get("payload")
                if not isinstance(payload, dict):
                    raise StudyLogError("malformed", "Codex session_meta payload is invalid")
                meta = cast(dict[str, Any], payload)
                if not _is_codex_root(meta):
                    return None
                cwd = meta.get("cwd")
                if not isinstance(cwd, str) or not _same_project(cwd, project):
                    return None
                candidate_id = meta.get("id") or meta.get("session_id")
                return SessionRef(
                    "codex",
                    source.resolve(strict=False),
                    str(candidate_id) if candidate_id else source.stem,
                    _canonical_project(project),
                )
    except UnicodeDecodeError as exc:
        raise StudyLogError("malformed", "Codex session metadata is not valid UTF-8") from exc
    except OSError as exc:
        raise StudyLogError("integrity", "cannot read Codex session metadata") from exc
    return None


def _config_file() -> Path:
    override = os.environ.get("STUDY_LOG_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "config.json"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "study-log" / "config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "study-log" / "config.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "study-log" / "config.json"


def _read_jsonl(source: Path, *, tail_lenient: bool) -> tuple[bytes, list[ParsedRow], list[dict[str, Any]]]:
    if not source.is_file():
        raise StudyLogError(
            "not_found", "session source does not exist", details={"source": str(source)}
        )
    try:
        source_bytes = source.read_bytes()
    except OSError as exc:
        raise StudyLogError(
            "integrity", "cannot read session source", details={"source": str(source)}
        ) from exc
    raw_lines = source_bytes.splitlines()
    nonempty = [(index, line) for index, line in enumerate(raw_lines, start=1) if line.strip()]
    rows: list[ParsedRow] = []
    warnings: list[dict[str, Any]] = []
    for position, (line_number, raw_bytes) in enumerate(nonempty):
        is_final_nonempty = position == len(nonempty) - 1
        try:
            raw_line = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            if tail_lenient and is_final_nonempty:
                warnings.append(
                    {
                        "code": "truncated_tail_ignored",
                        "line": line_number,
                        "reason": "utf8",
                        "message": "one malformed final JSONL record was ignored",
                    }
                )
                continue
            raise StudyLogError(
                "malformed",
                f"invalid UTF-8 in JSONL record on line {line_number}",
                details={"source": str(source), "line": line_number},
            ) from exc
        try:
            value: object = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            if tail_lenient and is_final_nonempty:
                warnings.append(
                    {
                        "code": "truncated_tail_ignored",
                        "line": line_number,
                        "reason": "json",
                        "message": "one malformed final JSONL record was ignored",
                    }
                )
                continue
            raise StudyLogError(
                "malformed",
                f"invalid JSONL record on line {line_number}",
                details={"source": str(source), "line": line_number, "reason": exc.msg},
            ) from exc
        if not isinstance(value, dict):
            raise StudyLogError(
                "malformed",
                f"JSONL record on line {line_number} must be an object",
                details={
                    "source": str(source),
                    "line": line_number,
                    "json_type": type(value).__name__,
                },
            )
        rows.append(ParsedRow(line_number, cast(dict[str, Any], value)))
    return source_bytes, rows, warnings


def _detect_provider(rows: Sequence[ParsedRow]) -> str:
    for parsed in rows:
        row = parsed.value
        row_type = _schema_string_field(
            row, "type", context="record", line_number=parsed.line_number
        )
        if row_type in {"session_meta", "response_item"}:
            if not isinstance(row.get("payload"), dict):
                raise StudyLogError(
                    "malformed",
                    "Codex record.payload must be an object",
                    details={"field": "record.payload", "line": parsed.line_number},
                )
            return "codex"
    for parsed in rows:
        row = parsed.value
        row_type = _schema_string_field(
            row, "type", context="record", line_number=parsed.line_number
        )
        if row_type in VISIBLE_ROLES:
            if not isinstance(row.get("message"), dict):
                raise StudyLogError(
                    "malformed",
                    "Claude record.message must be an object",
                    details={"field": "record.message", "line": parsed.line_number},
                )
            return "claude"
    raise StudyLogError("malformed", "could not identify session provider from JSONL schema")


def _codex_meta(rows: Sequence[ParsedRow]) -> dict[str, Any]:
    for parsed in rows:
        row = parsed.value
        row_type = _schema_string_field(
            row, "type", context="record", line_number=parsed.line_number
        )
        if row_type == "session_meta":
            if not isinstance(row.get("payload"), dict):
                raise StudyLogError(
                    "malformed",
                    "Codex session_meta.payload must be an object",
                    details={"field": "session_meta.payload", "line": parsed.line_number},
                )
            return cast(dict[str, Any], row["payload"])
    return {}


def _is_codex_root(meta: dict[str, Any]) -> bool:
    if meta.get("agent_path") or meta.get("parent_thread_id") or meta.get("forked_from_id"):
        return False
    source = meta.get("source")
    if isinstance(source, dict) and source.get("subagent"):
        return False
    if isinstance(source, str) and "subagent" in source.casefold():
        return False
    return True


def _claude_meta(rows: Sequence[ParsedRow], source: Path) -> tuple[str, str | None, bool]:
    session_id: str | None = None
    cwd: str | None = None
    root = True
    for parsed in rows:
        row = parsed.value
        candidate_id = row.get("sessionId") or row.get("session_id")
        if session_id is None and isinstance(candidate_id, str) and candidate_id:
            session_id = candidate_id
        candidate_cwd = row.get("cwd")
        if cwd is None and isinstance(candidate_cwd, str) and candidate_cwd:
            cwd = candidate_cwd
        if row.get("isSidechain"):
            root = False
    if source.name.startswith("agent-") or "subagents" in {part.casefold() for part in source.parts}:
        root = False
    return session_id or source.stem, cwd, root


def _clean_common_text(text: str) -> str:
    for pattern in COMMON_STRIP_PATTERNS:
        text = pattern.sub("", text)
    command_match = COMMAND_NAME_RE.search(text)
    if command_match:
        text = COMMAND_NAME_RE.sub("", text)
        command = command_match.group(1).strip()
        remainder = text.strip()
        text = f"> command: {command}" + (f"\n\n{remainder}" if remainder else "")
    return text.strip()


def _clean_codex_user_text(text: str, *, keep_client_context: bool) -> str:
    if keep_client_context:
        return _clean_common_text(text)
    for pattern in CODEX_STRIP_PATTERNS:
        text = pattern.sub("", text)
    text = text.strip()
    if STANDALONE_SKILL_CONTEXT_RE.fullmatch(text):
        return ""
    # Only unwrap a real IDE envelope; quoted headings in user prose are content.
    if text.split("\n", maxsplit=1)[0].removesuffix("\r") == IDE_CONTEXT_PREFIX:
        request_heading = IDE_REQUEST_HEADING_RE.search(text)
        if request_heading is None:
            return ""
        text = text[request_heading.end() :]
    return _clean_common_text(text)


def _content_text(
    content: object, *, allowed_types: set[str], source_line: int
) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        raise StudyLogError(
            "malformed",
            "message.content must be a string or array",
            details={"field": "message.content", "line": source_line},
        )
    parts: list[str] = []
    for part_index, part_object in enumerate(cast(list[object], content)):
        if not isinstance(part_object, dict):
            raise StudyLogError(
                "malformed",
                "message.content entries must be objects",
                details={
                    "field": f"message.content[{part_index}]",
                    "line": source_line,
                    "json_type": type(part_object).__name__,
                },
            )
        part = cast(dict[str, Any], part_object)
        part_type = _schema_string_field(
            part,
            "type",
            context=f"message.content[{part_index}]",
            line_number=source_line,
            required=True,
        )
        if part_type not in allowed_types:
            continue
        text = part.get("text")
        if not isinstance(text, str):
            raise StudyLogError(
                "malformed",
                f"message.content[{part_index}].text must be a string",
                details={
                    "field": f"message.content[{part_index}].text",
                    "line": source_line,
                    "json_type": type(text).__name__,
                },
            )
        if text.strip():
            parts.append(text)
    return "\n".join(parts).strip()


def _brief_tool_input(value: object) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return re.sub(r"\s+", " ", value)[:80]
    if isinstance(value, dict):
        for key in (
            "file_path",
            "path",
            "description",
            "skill",
            "pattern",
            "query",
            "command",
            "cmd",
        ):
            if key in value:
                return re.sub(r"\s+", " ", str(value[key]))[:80]
    return ""


def _tool_text(name: object, value: object) -> str:
    label = str(name or "tool")
    detail = _brief_tool_input(value)
    return f"> tool: {label}({detail})" if detail else f"> tool: {label}"


def _stable_message_id(
    provider: str,
    session_id: str,
    source_line: int,
    role: str,
    timestamp: str,
    phase: str | None,
    text: str,
) -> str:
    canonical = json.dumps(
        [provider, session_id, source_line, role, timestamp, phase, text],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "msg-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _build_message(
    *,
    provider: str,
    session_id: str,
    source_line: int,
    role: str,
    timestamp: str,
    phase: str | None,
    text: str,
    is_tool: bool = False,
) -> DialogueMessage:
    return DialogueMessage(
        message_id=_stable_message_id(
            provider, session_id, source_line, role, timestamp, phase, text
        ),
        timestamp=timestamp,
        role=role,
        phase=phase,
        text=text,
        source_line=source_line,
        is_tool=is_tool,
    )


def _codex_messages(
    rows: Sequence[ParsedRow],
    *,
    session_id: str,
    include_tools: bool,
    keep_client_context: bool,
) -> list[DialogueMessage]:
    messages: list[DialogueMessage] = []
    for parsed in rows:
        row = parsed.value
        row_type = _schema_string_field(
            row, "type", context="record", line_number=parsed.line_number
        )
        if row_type != "response_item":
            continue
        if not isinstance(row.get("payload"), dict):
            raise StudyLogError(
                "malformed",
                "Codex response_item.payload must be an object",
                details={"field": "response_item.payload", "line": parsed.line_number},
            )
        payload = cast(dict[str, Any], row["payload"])
        payload_type = _schema_string_field(
            payload,
            "type",
            context="response_item.payload",
            line_number=parsed.line_number,
            required=True,
        )
        timestamp = _schema_string_field(
            row, "timestamp", context="record", line_number=parsed.line_number
        ) or ""
        if payload_type == "message":
            role = _schema_string_field(
                payload,
                "role",
                context="message",
                line_number=parsed.line_number,
                required=True,
            )
            if role not in VISIBLE_ROLES:
                continue
            text = _content_text(
                payload.get("content"),
                allowed_types=TEXT_CONTENT_TYPES,
                source_line=parsed.line_number,
            )
            if role == "user":
                text = _clean_codex_user_text(text, keep_client_context=keep_client_context)
            else:
                text = _clean_common_text(text)
            if not text:
                continue
            phase = _schema_string_field(
                payload,
                "phase",
                context="message",
                line_number=parsed.line_number,
            )
            messages.append(
                _build_message(
                    provider="codex",
                    session_id=session_id,
                    source_line=parsed.line_number,
                    role=role,
                    timestamp=timestamp,
                    phase=phase,
                    text=text,
                )
            )
        elif include_tools and payload_type in {"function_call", "custom_tool_call"}:
            text = _tool_text(
                payload.get("name") or payload.get("namespace"),
                payload.get("input") or payload.get("arguments"),
            )
            messages.append(
                _build_message(
                    provider="codex",
                    session_id=session_id,
                    source_line=parsed.line_number,
                    role="tool",
                    timestamp=timestamp,
                    phase=None,
                    text=text,
                    is_tool=True,
                )
            )
    return messages


def _claude_message_text(
    row: dict[str, Any],
    *,
    include_tools: bool,
    keep_client_context: bool,
    source_line: int,
) -> tuple[str, list[str]]:
    message = row.get("message")
    if not isinstance(message, dict):
        raise StudyLogError(
            "malformed",
            "Claude record.message must be an object",
            details={"field": "record.message", "line": source_line},
        )
    message_role = _schema_string_field(
        message, "role", context="message", line_number=source_line
    )
    if message_role is not None and message_role != row.get("type"):
        raise StudyLogError(
            "malformed",
            "Claude record type and message.role disagree",
            details={"field": "message.role", "line": source_line},
        )
    content = message.get("content")
    text_parts: list[str] = []
    tool_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block_index, block_object in enumerate(cast(list[object], content)):
            if not isinstance(block_object, dict):
                raise StudyLogError(
                    "malformed",
                    "Claude message.content entries must be objects",
                    details={
                        "field": f"message.content[{block_index}]",
                        "line": source_line,
                        "json_type": type(block_object).__name__,
                    },
                )
            block = cast(dict[str, Any], block_object)
            block_type = _schema_string_field(
                block,
                "type",
                context=f"message.content[{block_index}]",
                line_number=source_line,
                required=True,
            )
            if block_type == "text":
                text_value = block.get("text")
                if not isinstance(text_value, str):
                    raise StudyLogError(
                        "malformed",
                        f"message.content[{block_index}].text must be a string",
                        details={
                            "field": f"message.content[{block_index}].text",
                            "line": source_line,
                            "json_type": type(text_value).__name__,
                        },
                    )
                text_parts.append(text_value)
            elif include_tools and block_type == "tool_use":
                tool_parts.append(_tool_text(block.get("name"), block.get("input")))
    else:
        raise StudyLogError(
            "malformed",
            "Claude message.content must be a string or array",
            details={"field": "message.content", "line": source_line},
        )
    text = "\n".join(part for part in text_parts if part.strip())
    if row.get("type") == "user" and not keep_client_context:
        text = _clean_common_text(text)
    else:
        text = _clean_common_text(text)
    return text, tool_parts


def _claude_messages(
    rows: Sequence[ParsedRow],
    *,
    session_id: str,
    include_tools: bool,
    keep_client_context: bool,
) -> list[DialogueMessage]:
    messages: list[DialogueMessage] = []
    for parsed in rows:
        row = parsed.value
        role = _schema_string_field(
            row, "type", context="record", line_number=parsed.line_number
        )
        if role not in VISIBLE_ROLES:
            continue
        if row.get("isSidechain") or row.get("isMeta") or row.get("isCompactSummary"):
            continue
        timestamp = _schema_string_field(
            row, "timestamp", context="record", line_number=parsed.line_number
        ) or ""
        text, tool_parts = _claude_message_text(
            row,
            include_tools=include_tools,
            keep_client_context=keep_client_context,
            source_line=parsed.line_number,
        )
        message_object = row.get("message")
        if not isinstance(message_object, dict):
            raise StudyLogError(
                "malformed",
                "Claude record.message must be an object",
                details={"field": "record.message", "line": parsed.line_number},
            )
        phase = _schema_string_field(
            message_object,
            "phase",
            context="message",
            line_number=parsed.line_number,
        )
        if text:
            messages.append(
                _build_message(
                    provider="claude",
                    session_id=session_id,
                    source_line=parsed.line_number,
                    role=cast(str, role),
                    timestamp=timestamp,
                    phase=phase,
                    text=text,
                )
            )
        for tool_index, tool_text in enumerate(tool_parts, start=1):
            messages.append(
                _build_message(
                    provider="claude",
                    session_id=session_id,
                    source_line=parsed.line_number * 1000 + tool_index,
                    role="tool",
                    timestamp=timestamp,
                    phase=None,
                    text=tool_text,
                    is_tool=True,
                )
            )
    return messages


def _deduplicate(messages: Iterable[DialogueMessage]) -> list[DialogueMessage]:
    result: list[DialogueMessage] = []
    for message in messages:
        if result and result[-1].role == message.role and result[-1].text == message.text:
            continue
        result.append(message)
    return result


def _load_session(
    source: Path,
    *,
    provider: str,
    project: str,
    tail_lenient: bool,
    include_tools: bool = False,
    keep_client_context: bool = False,
    keep_duplicates: bool = False,
    enforce_project: bool = True,
) -> SessionData:
    source = source.expanduser().resolve(strict=False)
    source_bytes, rows, warnings = _read_jsonl(source, tail_lenient=tail_lenient)
    detected = _detect_provider(rows)
    if provider != "auto" and provider != detected:
        raise StudyLogError(
            "malformed",
            "session schema does not match requested provider",
            details={"requested": provider, "detected": detected, "source": str(source)},
        )

    canonical_project = _canonical_project(project)
    if detected == "codex":
        meta = _codex_meta(rows)
        if not _is_codex_root(meta):
            raise StudyLogError("safety", "subagent or forked Codex sessions are excluded")
        recorded_project = meta.get("cwd")
        if enforce_project and (
            not isinstance(recorded_project, str)
            or not _same_project(recorded_project, canonical_project)
        ):
            raise StudyLogError(
                "safety",
                "Codex session project does not match --project",
                details={"source": str(source)},
            )
        candidate_id = meta.get("id") or meta.get("session_id")
        session_id = str(candidate_id) if candidate_id else source.stem
        messages = _codex_messages(
            rows,
            session_id=session_id,
            include_tools=include_tools,
            keep_client_context=keep_client_context,
        )
    else:
        session_id, recorded_project, root = _claude_meta(rows, source)
        if not root:
            raise StudyLogError("safety", "Claude sidechain or compact sessions are excluded")
        parent_matches = source.parent.name in claude_project_slugs(canonical_project)
        if enforce_project and not (
            (recorded_project and _same_project(recorded_project, canonical_project))
            or (recorded_project is None and parent_matches)
        ):
            raise StudyLogError(
                "safety",
                "Claude session project does not match --project",
                details={"source": str(source)},
            )
        messages = _claude_messages(
            rows,
            session_id=session_id,
            include_tools=include_tools,
            keep_client_context=keep_client_context,
        )

    if detected == "claude" and not messages:
        raise StudyLogError(
            "not_found", "Claude session contains no eligible root visible messages"
        )

    if not keep_duplicates:
        messages = _deduplicate(messages)
    ref = SessionRef(detected, source, session_id, canonical_project)
    return SessionData(
        ref=ref,
        source_sha256=_sha256_bytes(source_bytes),
        source_size=len(source_bytes),
        messages=tuple(messages),
        warnings=tuple(warnings),
    )


def discover_sessions(provider: str, project: str) -> tuple[list[SessionRef], list[dict[str, Any]]]:
    """Discover root sessions for exactly one normalized project."""

    if provider not in PROVIDERS:
        raise StudyLogError("usage", f"unsupported provider: {provider}")
    canonical_project = _canonical_project(project)
    paths: list[tuple[str, Path]] = []
    if provider in {"auto", "codex"}:
        root = _codex_sessions_root()
        if root.is_dir():
            paths.extend(("codex", path) for path in root.rglob("rollout-*.jsonl"))
    if provider in {"auto", "claude"}:
        root = _claude_projects_root()
        if root.is_dir():
            candidate_dirs = [root / slug for slug in claude_project_slugs(canonical_project)]
            for directory in candidate_dirs:
                if directory.is_dir():
                    paths.extend(("claude", path) for path in directory.glob("*.jsonl"))

    refs: list[SessionRef] = []
    warnings: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for expected_provider, path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        try:
            if expected_provider == "codex":
                ref = _probe_codex_ref(resolved, canonical_project)
                if ref is None:
                    continue
            else:
                session = _load_session(
                    resolved,
                    provider=expected_provider,
                    project=canonical_project,
                    tail_lenient=True,
                )
                ref = session.ref
        except StudyLogError as exc:
            if exc.spec.kind in {"safety", "malformed", "not_found"}:
                warnings.append(
                    {
                        "code": "session_skipped",
                        "provider": expected_provider,
                        "source": str(resolved),
                        "reason": exc.spec.kind,
                    }
                )
                continue
            raise
        refs.append(ref)

    def sort_key(ref: SessionRef) -> tuple[float, str]:
        try:
            mtime = ref.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (-mtime, f"{ref.provider}:{ref.session_id}")

    refs.sort(key=sort_key)
    return refs, warnings


def _resolve_session(
    *,
    provider: str,
    project: str,
    session: str | None,
    source: str | None,
    tail_lenient: bool,
    include_tools: bool = False,
    keep_client_context: bool = False,
    keep_duplicates: bool = False,
) -> SessionData:
    if source:
        return _load_session(
            Path(source),
            provider=provider,
            project=project,
            tail_lenient=tail_lenient,
            include_tools=include_tools,
            keep_client_context=keep_client_context,
            keep_duplicates=keep_duplicates,
        )
    if not session:
        raise StudyLogError("usage", "provide exactly one of --session or --source")
    refs, _warnings = discover_sessions(provider, project)
    qualified_provider: str | None = None
    prefix = session
    if ":" in session:
        qualified_provider, prefix = session.split(":", maxsplit=1)
    matches = [
        ref
        for ref in refs
        if ref.session_id.startswith(prefix)
        and (qualified_provider is None or ref.provider == qualified_provider)
    ]
    if not matches:
        raise StudyLogError(
            "not_found", "session ID did not match a discovered root session", details={"session": session}
        )
    if len(matches) > 1:
        raise StudyLogError(
            "ambiguous",
            "session ID prefix matched multiple sessions",
            details={
                "session": session,
                "candidates": [f"{item.provider}:{item.session_id}" for item in matches],
            },
        )
    return _load_session(
        matches[0].path,
        provider=matches[0].provider,
        project=project,
        tail_lenient=tail_lenient,
        include_tools=include_tools,
        keep_client_context=keep_client_context,
        keep_duplicates=keep_duplicates,
    )


def _parse_timestamp(value: str, option: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise StudyLogError("usage", f"{option} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _timestamp_for_message(message: DialogueMessage) -> datetime:
    if not message.timestamp:
        raise StudyLogError(
            "malformed",
            "a selected message has no timestamp",
            details={"message_id": message.message_id},
        )
    return _parse_timestamp(message.timestamp, "message timestamp")


def _unique_text_match(
    messages: Sequence[DialogueMessage],
    marker: str,
    *,
    start: int,
    option: str,
) -> int:
    matches = [
        index
        for index in range(start, len(messages))
        if messages[index].role == "user" and marker in messages[index].text
    ]
    if not matches:
        raise StudyLogError(
            "not_found", f"{option} did not match a user message", details={"marker": marker}
        )
    if len(matches) > 1:
        raise StudyLogError(
            "ambiguous",
            f"{option} matched multiple user messages; use stable message IDs",
            details={"marker": marker, "message_ids": [messages[index].message_id for index in matches]},
        )
    return matches[0]


def select_messages(
    messages: Sequence[DialogueMessage],
    *,
    date: str | None = None,
    start_id: str | None = None,
    end_id: str | None = None,
    start_user: str | None = None,
    end_before_user: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    final_only: bool = False,
) -> Selection:
    """Select an interval; ID boundaries are inclusive and semantic end is exclusive."""

    filtered = [message for message in messages if not date or message.timestamp.startswith(date)]
    if not filtered:
        raise StudyLogError("not_found", "no visible messages matched the requested date")
    if start_id and start_user:
        raise StudyLogError("usage", "--start-id and --start-user are mutually exclusive")
    if end_id and end_before_user:
        raise StudyLogError("usage", "--end-id and --end-before-user are mutually exclusive")

    start_index = 0
    if start_id:
        matches = [index for index, message in enumerate(filtered) if message.message_id == start_id]
        if not matches:
            raise StudyLogError("not_found", "--start-id did not match a visible message")
        start_index = matches[0]
    elif start_user:
        start_index = _unique_text_match(
            filtered, start_user, start=0, option="--start-user"
        )

    end_index = len(filtered) - 1
    if end_id:
        matches = [index for index, message in enumerate(filtered) if message.message_id == end_id]
        if not matches:
            raise StudyLogError("not_found", "--end-id did not match a visible message")
        end_index = matches[0]
    elif end_before_user:
        exclusive = _unique_text_match(
            filtered,
            end_before_user,
            start=start_index + 1,
            option="--end-before-user",
        )
        end_index = exclusive - 1

    if end_index < start_index:
        raise StudyLogError("usage", "the selected end precedes the selected start")
    selected = filtered[start_index : end_index + 1]

    start_datetime = _parse_timestamp(start_time, "--start-time") if start_time else None
    end_datetime = _parse_timestamp(end_time, "--end-time") if end_time else None
    if start_datetime and end_datetime and start_datetime >= end_datetime:
        raise StudyLogError("usage", "--start-time must be earlier than --end-time")
    bounded: list[DialogueMessage] = []
    for message in selected:
        timestamp = None
        if start_datetime or end_datetime:
            timestamp = _timestamp_for_message(message)
        if start_datetime and timestamp and timestamp < start_datetime:
            continue
        if end_datetime and timestamp and timestamp >= end_datetime:
            continue
        if final_only and message.role == "assistant" and message.phase == "commentary":
            continue
        bounded.append(message)
    if not bounded:
        raise StudyLogError("not_found", "the selected visible-message interval is empty")
    return Selection(tuple(bounded), bounded[0].message_id, bounded[-1].message_id)


CREDENTIAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:[A-Z][A-Z0-9]*[_-])*"
            r"(?:password|passwd|secret|token|access[_-]?token|api[_-]?key|"
            r"secret[_-]?access[_-]?key)\b"
            r"\s*[:=]\s*['\"]?[^\s'\"]{8,}"
        ),
    ),
    (
        "private-key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "bearer-token",
        re.compile(r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]{20,}(?=$|[\s,;])"),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
    ),
)
PERSONAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?\d{1,3}[- ]?)?"
            r"(?:1[3-9]\d{9}|\(?\d{3}\)?[- ]\d{3}[- ]\d{4})(?!\d)"
        ),
    ),
)
PROPRIETARY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "proprietary-marker",
        re.compile(
            r"(?i)\b(?:company confidential|proprietary|internal api|not for distribution)\b"
            r"|内部\s*API|公司机密|专有内容|未公开(?:硬件|性能|数据)"
        ),
    ),
    ("internal-host", re.compile(r"(?i)https?://[^\s/]+\.(?:internal|corp|local)(?:/|\b)")),
    ("source-code", re.compile(r"```(?:[A-Za-z0-9_+.-]+)?\r?\n[\s\S]*?```")),
)


def _privacy_report(messages: Sequence[DialogueMessage]) -> PrivacyReport:
    counts = {"credential": 0, "personal": 0, "proprietary": 0}
    for message in messages:
        for _name, pattern in CREDENTIAL_RULES:
            counts["credential"] += len(pattern.findall(message.text))
        for _name, pattern in PERSONAL_RULES:
            counts["personal"] += len(pattern.findall(message.text))
        for _name, pattern in PROPRIETARY_RULES:
            counts["proprietary"] += len(pattern.findall(message.text))
    categories = tuple(sorted(category for category, count in counts.items() if count))
    return PrivacyReport(categories, {key: value for key, value in counts.items() if value})


def _redact_text(
    text: str, rules: Sequence[tuple[str, re.Pattern[str]]], category: str
) -> tuple[str, list[dict[str, Any]]]:
    applications: list[dict[str, Any]] = []
    for rule_name, pattern in rules:
        count = 0

        def replace(_match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return f"[REDACTED:{category}:{rule_name}:{count:03d}]"

        text = pattern.sub(replace, text)
        if count:
            applications.append({"category": category, "rule": rule_name, "count": count})
    return text, applications


def redact_messages(
    messages: Sequence[DialogueMessage], *, credentials: bool, personal: bool
) -> tuple[tuple[DialogueMessage, ...], dict[str, Any]]:
    result: list[DialogueMessage] = []
    applications: dict[tuple[str, str], int] = {}
    for message in messages:
        text = message.text
        records: list[dict[str, Any]] = []
        if credentials:
            text, found = _redact_text(text, CREDENTIAL_RULES, "credential")
            records.extend(found)
        if personal:
            text, found = _redact_text(text, PERSONAL_RULES, "personal")
            records.extend(found)
        for record in records:
            key = (cast(str, record["category"]), cast(str, record["rule"]))
            applications[key] = applications.get(key, 0) + cast(int, record["count"])
        result.append(
            DialogueMessage(
                message_id=message.message_id,
                timestamp=message.timestamp,
                role=message.role,
                phase=message.phase,
                text=text,
                source_line=message.source_line,
                is_tool=message.is_tool,
            )
        )
    metadata = {
        "version": REDACTION_VERSION,
        "categories": [
            category
            for category, enabled in (("credential", credentials), ("personal", personal))
            if enabled
        ],
        "applications": [
            {"category": key[0], "rule": key[1], "count": applications[key]}
            for key in sorted(applications)
        ],
    }
    return tuple(result), metadata


def _safe_preview(text: str, limit: int) -> str:
    for _name, pattern in CREDENTIAL_RULES:
        text = pattern.sub("[CREDENTIAL]", text)
    for _name, pattern in PERSONAL_RULES:
        text = pattern.sub("[PERSONAL]", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _dialogue_sha256(messages: Sequence[DialogueMessage]) -> str:
    canonical = [
        {
            "message_id": message.message_id,
            "timestamp": message.timestamp,
            "role": message.role,
            "phase": message.phase,
            "text": message.text,
        }
        for message in messages
    ]
    return _sha256_bytes(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _normalization_metadata(*, final_only: bool = False) -> dict[str, Any]:
    return {
        "version": NORMALIZATION_VERSION,
        "client_context": "stripped",
        "adjacent_duplicates": "removed",
        "assistant_commentary": "excluded" if final_only else "included",
        "tools": "excluded",
        "attachments": "not_embedded",
    }


def _role_label(message: DialogueMessage) -> str:
    if message.role == "user":
        return "用户"
    if message.role == "tool":
        return "工具摘要"
    if message.phase == "commentary":
        return "助手 / 过程更新"
    if message.phase == "final_answer":
        return "助手 / 正式回答"
    return "助手"


def _render_scratch(data: SessionData, selection: Selection) -> str:
    lines = [
        "# study-log structured scratch",
        "",
        "> Temporary visible-message material. Distill it into a structured learning record, then delete it.",
        f"> provider: {data.ref.provider}",
        f"> session_id: {data.ref.session_id}",
        f"> source_sha256: {data.source_sha256}",
        f"> start_message_id: {selection.start_message_id}",
        f"> end_message_id: {selection.end_message_id}",
    ]
    for message in selection.messages:
        lines.extend(
            [
                "",
                "---",
                "",
                f"## {_role_label(message)} · `{message.message_id}` · `{message.timestamp or 'unknown'}`",
                "",
                message.text,
            ]
        )
    return "\n".join([*lines, ""])


def _frontmatter_lines(metadata: dict[str, Any]) -> list[str]:
    ordered_keys = (
        "archive_type",
        "schema_version",
        "archive_id",
        "status",
        "title",
        "provider",
        "project_name",
        "project_fingerprint",
        "source_session_id",
        "source_file",
        "start_message_id",
        "end_message_id",
        "message_count",
        "source_sha256",
        "visible_content_sha256",
        "target_precondition_sha256",
        "first_message_at",
        "last_message_at",
        "created_at_utc",
        "updated_at_utc",
        "normalization",
        "redaction",
        "privacy_risks",
        "structured_record",
        "message_phases",
        "migration",
    )
    lines = ["---"]
    for key in ordered_keys:
        lines.append(
            f"{key}: {json.dumps(metadata.get(key), ensure_ascii=False, separators=(',', ':'))}"
        )
    lines.append("---")
    return lines


def _render_archive(
    messages: Sequence[DialogueMessage], metadata: dict[str, Any]
) -> str:
    lines = [
        *_frontmatter_lines(metadata),
        "",
        f"# {metadata['title']}",
        "",
        "> 此文件是规则化提取的“可追溯可见文本对话”，不是完整客户端 Session，也不代表已经匿名化。",
        "> system、developer、reasoning、工具事件、客户端注入和附件正文默认不包含在内。",
    ]
    if metadata.get("structured_record"):
        record = Path(metadata["structured_record"])
        backlink = f"../{record.parent.name}/{record.name}"
        lines.extend(["", f"结构化学习记录：[查看记录](<{backlink}>)"])
    for index, message in enumerate(messages, start=1):
        lines.extend(
            [
                "",
                "---",
                "",
                f"**{index:03d} · {_role_label(message)}** · `{message.timestamp or 'unknown'}` · `{message.message_id}`",
                "",
                message.text,
            ]
        )
    return "\n".join([*lines, ""])


def _parse_archive_metadata(content: str) -> dict[str, Any]:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise StudyLogError("malformed", "target is not a study-log archive")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise StudyLogError("malformed", "archive frontmatter is not terminated") from exc
    metadata: dict[str, Any] = {}
    for line in lines[1:end]:
        if ":" not in line:
            raise StudyLogError("malformed", "archive frontmatter contains an invalid line")
        key, raw_value = line.split(":", maxsplit=1)
        if key in metadata:
            raise StudyLogError("malformed", "archive frontmatter contains a duplicate key")
        try:
            metadata[key] = json.loads(raw_value.strip())
        except json.JSONDecodeError as exc:
            raise StudyLogError(
                "malformed", f"archive frontmatter value is invalid: {key}"
            ) from exc
    if metadata.get("archive_type") != "study-log-visible-dialogue":
        raise StudyLogError("malformed", "target is not a study-log visible-dialogue archive")
    return metadata


def _is_within(child: Path, parent: Path) -> bool:
    child_resolved = child.resolve(strict=False)
    parent_resolved = parent.resolve(strict=False)
    try:
        common = os.path.commonpath([str(child_resolved), str(parent_resolved)])
        return os.path.normcase(common) == os.path.normcase(str(parent_resolved))
    except ValueError:
        return False


def _ensure_contained(target: Path, root: Path) -> tuple[Path, Path]:
    root_resolved = root.expanduser().resolve(strict=False)
    target_resolved = target.expanduser().resolve(strict=False)
    if not root_resolved.is_absolute() or not target_resolved.is_absolute():
        raise StudyLogError("safety", "archive root and target must be absolute paths")
    if not _is_within(target_resolved, root_resolved) or target_resolved == root_resolved:
        raise StudyLogError(
            "safety",
            "archive target escapes the selected root",
            details={"target": str(target), "root": str(root)},
        )
    if target.exists() and target.is_symlink():
        raise StudyLogError("safety", "archive target cannot be a symbolic link")
    if hasattr(target, "is_junction") and target.exists() and target.is_junction():
        raise StudyLogError("safety", "archive target cannot be a Windows junction")
    return target_resolved, root_resolved


def _project_output(target: Path, project: Path) -> Path:
    """Require an owned project path without symlink or nested-repository escapes."""
    root = Path(_canonical_project(project))
    if not root.is_dir() or root == root.parent:
        raise StudyLogError("safety", "project must be an existing non-root directory")
    lexical = Path(os.path.abspath(target if target.is_absolute() else root / target))
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise StudyLogError("safety", "output must stay inside the selected project") from exc
    if not relative.parts or ".git" in {part.casefold() for part in relative.parts}:
        raise StudyLogError("safety", "output cannot be the project root or Git metadata")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (
            hasattr(cursor, "is_junction") and cursor.is_junction()
        ):
            raise StudyLogError("safety", "output path cannot cross a symbolic link or junction")
        if cursor.is_dir() and (cursor / ".git").exists():
            raise StudyLogError("safety", "output cannot enter a nested Git worktree")
    resolved, _root = _ensure_contained(lexical, root)
    return resolved


def _paired_paths(project: str | Path, structured_record: str) -> tuple[Path, Path, str]:
    root = Path(_canonical_project(project))
    record = _project_output(Path(structured_record), root)
    if record.suffix.casefold() != ".md" or not record.is_file():
        raise StudyLogError("safety", "structured record must be an existing project Markdown file")
    if any(part == "raw" or part.endswith("-raw") or part in {".study-log", ".agent-skills", ".agents", ".claude"} for part in (part.casefold() for part in record.relative_to(root).parts[:-1])):
        raise StudyLogError("safety", "a raw dialogue cannot be used as its own structured record")
    if record.parent == root:
        raise StudyLogError("safety", "structured record must be inside a project log directory")
    raw_dir = record.parent.with_name(record.parent.name + "-raw")
    target = _project_output(raw_dir / record.name, root)
    return record, target, record.relative_to(root).as_posix()


def _atomic_write(path: Path, content: str, *, expected_sha256: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected_sha256 is None:
        if path.exists():
            raise StudyLogError("conflict", "target already exists")
    else:
        if not path.is_file():
            raise StudyLogError("conflict", "target disappeared before update")
        actual = _sha256_file(path)
        if actual != expected_sha256:
            raise StudyLogError(
                "conflict",
                "target SHA-256 changed after review",
                details={"expected": expected_sha256, "actual": actual},
            )

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        if expected_sha256 is None and path.exists():
            raise StudyLogError("conflict", "target appeared before atomic write")
        if expected_sha256 is not None and _sha256_file(path) != expected_sha256:
            raise StudyLogError("conflict", "target changed immediately before atomic write")
        if expected_sha256 is None:
            try:
                os.link(temporary_path, path)
            except FileExistsError as exc:
                raise StudyLogError("conflict", "target appeared before atomic write") from exc
            temporary_path.unlink()
            temporary_path = None
        else:
            os.replace(temporary_path, path)
            temporary_path = None
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _load_config() -> dict[str, Any]:
    path = _config_file()
    if not path.exists():
        return {}
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StudyLogError("malformed", "study-log user configuration is invalid") from exc
    if not isinstance(value, dict):
        raise StudyLogError("malformed", "study-log user configuration must be an object")
    return cast(dict[str, Any], value)


def _iter_archive_metadata(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    if not root.is_dir():
        return
    for path in root.rglob("*.md"):
        _project_output(path, root)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            raise
        except OSError as exc:
            raise StudyLogError(
                "integrity",
                "cannot read an archive candidate during root scan",
                details={"path": str(path)},
            ) from exc
        try:
            metadata = _parse_archive_metadata(content)
        except StudyLogError:
            continue
        yield path, metadata


def _ensure_no_parallel_partial(root: Path, identity: dict[str, Any]) -> None:
    for path, metadata in _iter_archive_metadata(root):
        if metadata.get("status") != "partial":
            continue
        if all(metadata.get(key) == value for key, value in identity.items()):
            raise StudyLogError(
                "conflict",
                "a partial archive already exists for this source boundary",
                details={"archive_id": metadata.get("archive_id"), "target": str(path)},
            )


def _redaction_identity(redaction: object) -> tuple[object, object]:
    if not isinstance(redaction, dict):
        return None, None
    return redaction.get("version"), redaction.get("categories")


def _ensure_no_duplicate_final(
    root: Path,
    *,
    provider: str,
    project_fingerprint: str,
    session_id: str,
    start_message_id: str,
    end_message_id: str,
    normalization: dict[str, Any],
    redaction: dict[str, Any],
) -> None:
    expected_redaction = _redaction_identity(redaction)
    for path, metadata in _iter_archive_metadata(root):
        if metadata.get("status") != "final":
            continue
        same_identity = (
            metadata.get("provider") == provider
            and metadata.get("project_fingerprint") == project_fingerprint
            and metadata.get("source_session_id") == session_id
            and metadata.get("start_message_id") == start_message_id
            and metadata.get("end_message_id") == end_message_id
            and metadata.get("normalization") == normalization
            and _redaction_identity(metadata.get("redaction")) == expected_redaction
        )
        if same_identity:
            raise StudyLogError(
                "conflict",
                "an equivalent finalized archive already exists",
                details={"archive_id": metadata.get("archive_id"), "target": str(path)},
            )


def _verify_partial_history_prefix(
    existing: dict[str, Any],
    current_messages: Sequence[DialogueMessage],
    *,
    requested_status: str,
) -> None:
    old_end = existing.get("end_message_id")
    if not isinstance(old_end, str) or not old_end:
        raise StudyLogError("conflict", "partial archive has no valid end message ID")
    matches = [
        index
        for index, message in enumerate(current_messages)
        if message.message_id == old_end
    ]
    if len(matches) != 1:
        raise StudyLogError(
            "conflict", "previous partial end message is absent or ambiguous in current selection"
        )
    old_end_index = matches[0]
    prefix = tuple(current_messages[: old_end_index + 1])

    old_count = existing.get("message_count")
    if isinstance(old_count, bool) or not isinstance(old_count, int) or old_count < 1:
        raise StudyLogError("conflict", "partial archive has an invalid message count")
    if len(prefix) != old_count:
        raise StudyLogError(
            "conflict",
            "current selection no longer preserves the complete partial history prefix",
            details={"expected_count": old_count, "actual_count": len(prefix)},
        )

    old_visible_hash = existing.get("visible_content_sha256")
    if not isinstance(old_visible_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", old_visible_hash
    ):
        raise StudyLogError("conflict", "partial archive has an invalid visible-content hash")
    current_prefix_hash = _dialogue_sha256(prefix)
    if current_prefix_hash != old_visible_hash:
        raise StudyLogError(
            "conflict",
            "current selection rewrites previously archived visible history",
            details={"expected": old_visible_hash, "actual": current_prefix_hash},
        )

    if requested_status == "partial" and old_end_index == len(current_messages) - 1:
        raise StudyLogError(
            "conflict", "partial refresh must strictly advance the end message"
        )


def _session_json(data: SessionData, *, date: str | None = None) -> dict[str, Any]:
    messages = [message for message in data.messages if not date or message.timestamp.startswith(date)]
    first = messages[0].timestamp if messages else None
    last = messages[-1].timestamp if messages else None
    first_user = next((message.text for message in messages if message.role == "user"), "")
    return {
        "provider": data.ref.provider,
        "session_id": data.ref.session_id,
        "source": str(data.ref.path),
        "source_sha256": data.source_sha256,
        "first_message_at": first,
        "last_message_at": last,
        "message_count": len(messages),
        "first_user_preview": _safe_preview(first_user, 120),
    }


def _command_list(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    refs, discovery_warnings = discover_sessions(args.provider, args.project)
    sessions: list[dict[str, Any]] = []
    warnings = list(discovery_warnings)
    for ref in refs:
        try:
            data = _load_session(
                ref.path,
                provider=ref.provider,
                project=args.project,
                tail_lenient=True,
            )
        except StudyLogError as exc:
            warnings.append(
                {
                    "code": "session_skipped",
                    "provider": ref.provider,
                    "source": str(ref.path),
                    "reason": exc.spec.kind,
                }
            )
            continue
        sessions.append(_session_json(data, date=args.date))
        warnings.extend(data.warnings)
    sessions = [item for item in sessions if item["message_count"]]
    return {"project": _canonical_project(args.project), "sessions": sessions}, warnings


def _resolve_for_read(
    args: argparse.Namespace, *, tail_lenient: bool, include_tools: bool = False
) -> SessionData:
    return _resolve_session(
        provider=args.provider,
        project=args.project,
        session=args.session,
        source=args.source,
        tail_lenient=tail_lenient,
        include_tools=include_tools,
        keep_client_context=getattr(args, "keep_client_context", False),
        keep_duplicates=getattr(args, "keep_duplicates", False),
    )


def _command_preview(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = _resolve_for_read(args, tail_lenient=True)
    selection = select_messages(data.messages, date=args.date)
    messages = []
    for message in selection.messages:
        report = _privacy_report([message])
        messages.append(
            {
                "message_id": message.message_id,
                "timestamp": message.timestamp or None,
                "role": message.role,
                "phase": message.phase,
                "preview": _safe_preview(message.text, args.preview_chars),
                "privacy_risks": list(report.categories),
            }
        )
    report = _privacy_report(selection.messages)
    result = {
        "provider": data.ref.provider,
        "session_id": data.ref.session_id,
        "source": str(data.ref.path),
        "source_sha256": data.source_sha256,
        "message_count": len(messages),
        "privacy": {"categories": list(report.categories), "counts": report.counts},
        "messages": messages,
    }
    return result, list(data.warnings)


def _verify_source_precondition(data: SessionData, expected: str) -> None:
    if data.source_sha256 != expected:
        raise StudyLogError(
            "integrity",
            "source SHA-256 changed after preview",
            details={"expected": expected, "actual": data.source_sha256},
        )


def _selection_from_args(data: SessionData, args: argparse.Namespace) -> Selection:
    return select_messages(
        data.messages,
        date=getattr(args, "date", None),
        start_id=getattr(args, "start_id", None),
        end_id=getattr(args, "end_id", None),
        start_user=getattr(args, "start_user", None),
        end_before_user=getattr(args, "end_before_user", None),
        start_time=getattr(args, "start_time", None),
        end_time=getattr(args, "end_time", None),
        final_only=getattr(args, "final_only", False),
    )


def _command_extract(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = _resolve_for_read(args, tail_lenient=True, include_tools=args.include_tools)
    _verify_source_precondition(data, args.source_sha256)
    selection = _selection_from_args(data, args)
    content = _render_scratch(data, selection)
    if args.output:
        output = _project_output(Path(args.output), Path(args.project))
    else:
        output = _project_output(
            Path(".study-log/scratch") / f"study-log-{uuid.uuid4().hex}.md", Path(args.project)
        )
    if output.suffix.casefold() != ".md":
        raise StudyLogError("usage", "structured scratch output must use the .md extension")
    _atomic_write(output, content, expected_sha256=None)
    if _sha256_file(data.ref.path) != data.source_sha256:
        output.unlink(missing_ok=True)
        raise StudyLogError("integrity", "source changed while structured extract was written")
    report = _privacy_report(selection.messages)
    result = {
        "mode": "structured",
        "temporary": True,
        "output": str(output),
        "provider": data.ref.provider,
        "session_id": data.ref.session_id,
        "source_sha256": data.source_sha256,
        "start_message_id": selection.start_message_id,
        "end_message_id": selection.end_message_id,
        "message_count": len(selection.messages),
        "privacy": {"categories": list(report.categories), "counts": report.counts},
        "cleanup_required": True,
    }
    return result, list(data.warnings)


def _resolve_archive_target(
    args: argparse.Namespace,
    *,
    project: str,
    title: str,
    archive_id: str,
    first_timestamp: str,
) -> tuple[Path, Path, str]:
    _record, target, _relative = _paired_paths(project, args.structured_record)
    if args.archive_root:
        raise StudyLogError("usage", "--archive-root is retired; output is paired with --structured-record")
    if args.output:
        explicit = _project_output(Path(args.output), Path(project))
        if explicit != target:
            raise StudyLogError("safety", "--output must equal the canonical paired raw path")
    return target, target.parent, "structured_record"


def _command_archive(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not args.start_id or not args.end_id:
        raise StudyLogError(
            "usage", "raw archive requires reviewed --start-id and --end-id boundaries"
        )
    data = _resolve_for_read(args, tail_lenient=False)
    _verify_source_precondition(data, args.source_sha256)
    selection = _selection_from_args(data, args)
    report = _privacy_report(selection.messages)
    if not args.privacy_confirmed:
        raise StudyLogError(
            "safety",
            "raw archive privacy review was not confirmed",
            details={"privacy": list(report.categories)},
        )
    if "credential" in report.categories and args.credential_action == "block":
        raise StudyLogError(
            "safety",
            "high-confidence credentials detected; narrow the range or redact before repository storage",
            details={"privacy": list(report.categories)},
        )
    if "proprietary" in report.categories and not args.proprietary_confirmed:
        raise StudyLogError(
            "safety",
            "possible proprietary content requires a separate ownership/policy confirmation",
            details={"privacy": list(report.categories)},
        )

    credential_redaction = args.credential_action == "redact"
    rendered_messages, redaction = redact_messages(
        selection.messages,
        credentials=credential_redaction,
        personal=args.redact_personal,
    )
    normalization = _normalization_metadata(final_only=args.final_only)
    project = _canonical_project(args.project)
    now = datetime.now(UTC).isoformat()
    updating = bool(args.archive_id)
    archive_id = args.archive_id or f"sl-{uuid.uuid4().hex}"

    target: Path
    root: Path
    root_source: str
    existing: dict[str, Any] | None = None
    expected_target_sha: str | None = None
    target, root, root_source = _resolve_archive_target(
        args, project=project, title=args.title, archive_id=archive_id,
        first_timestamp=selection.messages[0].timestamp,
    )
    record, _target, record_relative = _paired_paths(project, args.structured_record)
    record_sha = _sha256_file(record)
    if updating:
        if not target.is_file():
            raise StudyLogError("not_found", "archive update target does not exist")
    if data.ref.path.resolve(strict=False) == target.resolve(strict=False):
        raise StudyLogError("safety", "session source and archive target must differ")

    if updating:
        if not args.target_sha256:
            raise StudyLogError("usage", "archive update requires --target-sha256")
        expected_target_sha = args.target_sha256
        actual_target_sha = _sha256_file(target)
        if actual_target_sha != expected_target_sha:
            raise StudyLogError(
                "conflict",
                "target SHA-256 changed after review",
                details={"expected": expected_target_sha, "actual": actual_target_sha},
            )
        existing, _existing_messages = _read_verified_archive(target)
        if existing is None:
            raise StudyLogError("malformed", "archive metadata could not be loaded")
        required_equal = {
            "archive_id": archive_id,
            "status": "partial",
            "provider": data.ref.provider,
            "project_fingerprint": _project_fingerprint(project),
            "source_session_id": data.ref.session_id,
            "start_message_id": selection.start_message_id,
            "normalization": normalization,
            "structured_record": record_relative,
        }
        for key, expected_value in required_equal.items():
            if existing.get(key) != expected_value:
                raise StudyLogError(
                    "conflict",
                    f"partial archive identity changed: {key}",
                    details={"field": key},
                )
        existing_redaction = existing.get("redaction")
        if _redaction_identity(existing_redaction) != _redaction_identity(redaction):
            raise StudyLogError(
                "conflict", "redaction identity changed; create a new archive_id"
            )
        _verify_partial_history_prefix(
            existing,
            rendered_messages,
            requested_status=args.status,
        )
        created_at = existing.get("created_at_utc") or now
    else:
        if args.target_sha256:
            raise StudyLogError("usage", "new archive must not provide --target-sha256")
        identity = {
            "provider": data.ref.provider,
            "project_fingerprint": _project_fingerprint(project),
            "source_session_id": data.ref.session_id,
            "start_message_id": selection.start_message_id,
        }
        _ensure_no_parallel_partial(root, identity)
        created_at = now

    if args.status == "final":
        _ensure_no_duplicate_final(
            root,
            provider=data.ref.provider,
            project_fingerprint=_project_fingerprint(project),
            session_id=data.ref.session_id,
            start_message_id=selection.start_message_id,
            end_message_id=selection.end_message_id,
            normalization=normalization,
            redaction=redaction,
        )

    metadata: dict[str, Any] = {
        "archive_type": "study-log-visible-dialogue",
        "schema_version": SCHEMA_VERSION,
        "archive_id": archive_id,
        "status": args.status,
        "title": " ".join(args.title.splitlines()).strip(),
        "provider": data.ref.provider,
        "project_name": _project_name(project),
        "project_fingerprint": _project_fingerprint(project),
        "source_session_id": data.ref.session_id,
        "source_file": data.ref.path.name,
        "start_message_id": selection.start_message_id,
        "end_message_id": selection.end_message_id,
        "message_count": len(rendered_messages),
        "source_sha256": data.source_sha256,
        "visible_content_sha256": _dialogue_sha256(rendered_messages),
        "target_precondition_sha256": expected_target_sha,
        "first_message_at": selection.messages[0].timestamp or None,
        "last_message_at": selection.messages[-1].timestamp or None,
        "created_at_utc": created_at,
        "updated_at_utc": now,
        "normalization": normalization,
        "redaction": redaction,
        "privacy_risks": {"categories": list(report.categories), "counts": report.counts},
        "structured_record": record_relative,
        "message_phases": [message.phase for message in rendered_messages],
    }
    if not metadata["title"]:
        raise StudyLogError("usage", "archive title cannot be empty")
    content = _render_archive(rendered_messages, metadata)

    # Recheck the source immediately before the atomic target mutation.
    if _sha256_file(data.ref.path) != data.source_sha256:
        raise StudyLogError("integrity", "source changed while archive candidate was prepared")
    _paired_paths(project, args.structured_record)
    if _sha256_file(record) != record_sha:
        raise StudyLogError("integrity", "structured record changed while archive was prepared")
    _atomic_write(target, content, expected_sha256=expected_target_sha)
    target_sha = _sha256_file(target)
    result = {
        "mode": "raw",
        "archive_id": archive_id,
        "status": args.status,
        "operation": "update" if updating else "create",
        "target": str(target),
        "target_sha256": target_sha,
        "archive_root": str(root),
        "archive_root_source": root_source,
        "provider": data.ref.provider,
        "session_id": data.ref.session_id,
        "source_sha256": data.source_sha256,
        "start_message_id": selection.start_message_id,
        "end_message_id": selection.end_message_id,
        "message_count": len(rendered_messages),
        "privacy": {"categories": list(report.categories), "counts": report.counts},
        "redaction": redaction,
        "structured_record": record_relative,
    }
    return result, []


ARCHIVE_MESSAGE_RE = re.compile(
    r"^\*\*(\d{3,}) · (用户|助手 / 过程更新|助手 / 正式回答|助手)\*\* · `([^`]+)` · `(msg-[0-9a-f]+)`\n\n",
    re.MULTILINE,
)


def _read_verified_archive(path: Path) -> tuple[dict[str, Any], tuple[DialogueMessage, ...]]:
    """Decode only this export format and require the complete visible-content hash."""
    # Do not use Path.read_text: universal-newline translation would silently
    # change CRLF inside visible message text and invalidate historical hashes.
    content = path.read_bytes().decode("utf-8")
    metadata = _parse_archive_metadata(content)
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise StudyLogError("malformed", "archive schema_version is unsupported")
    for key in ("archive_id", "provider", "project_fingerprint", "source_session_id", "title"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise StudyLogError("malformed", f"archive {key} must be a nonempty string")
    if not re.fullmatch(r"sl-[0-9a-f]{32}", metadata["archive_id"]):
        raise StudyLogError("malformed", "archive archive_id is invalid")
    if not isinstance(metadata.get("status"), str) or metadata["status"] not in {"partial", "final"}:
        raise StudyLogError("malformed", "archive status is invalid")
    if type(metadata.get("message_count")) is not int or metadata["message_count"] < 1:
        raise StudyLogError("malformed", "archive message_count must be a positive integer")
    normalization = metadata.get("normalization")
    redaction = metadata.get("redaction")
    if not isinstance(normalization, dict) or not isinstance(normalization.get("version"), str):
        raise StudyLogError("malformed", "archive normalization is invalid")
    if not isinstance(redaction, dict) or not isinstance(redaction.get("version"), str):
        raise StudyLogError("malformed", "archive redaction is invalid")
    categories = redaction.get("categories")
    if not isinstance(categories, list) or any(not isinstance(category, str) for category in categories):
        raise StudyLogError("malformed", "archive redaction categories are invalid")
    if not isinstance(redaction.get("applications"), list):
        raise StudyLogError("malformed", "archive redaction applications are invalid")
    if metadata.get("migration") is not None and not isinstance(metadata["migration"], dict):
        raise StudyLogError("malformed", "archive migration provenance is invalid")
    matches = list(ARCHIVE_MESSAGE_RE.finditer(content))
    phases = metadata.get("message_phases")
    if phases is not None and (
        not isinstance(phases, list) or len(phases) != len(matches)
        or any(value is not None and not isinstance(value, str) for value in phases)
    ):
        raise StudyLogError("malformed", "archive message_phases is invalid")
    messages: list[DialogueMessage] = []
    role_phases = {
        "用户": ("user", None), "助手": ("assistant", None),
        "助手 / 过程更新": ("assistant", "commentary"),
        "助手 / 正式回答": ("assistant", "final_answer"),
    }
    for index, match in enumerate(matches):
        if int(match.group(1)) != index + 1:
            raise StudyLogError("integrity", "archive message numbering is not contiguous")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[match.end():end]
        suffix = "\n\n---\n\n" if index + 1 < len(matches) else "\n"
        if not text.endswith(suffix):
            raise StudyLogError("malformed", "archive message separators are invalid")
        role, phase = role_phases[match.group(2)]
        message = DialogueMessage(
            message_id=match.group(4),
            timestamp="" if match.group(3) == "unknown" else match.group(3),
            role=role, phase=phases[index] if phases is not None else phase,
            text=text[:-len(suffix)], source_line=0,
        )
        if _role_label(message) != match.group(2):
            raise StudyLogError("integrity", "archive role label disagrees with phase metadata")
        messages.append(message)
    if not messages or len({message.message_id for message in messages}) != len(messages):
        raise StudyLogError("integrity", "archive messages are empty or have duplicate IDs")
    expected = {
        "message_count": len(messages),
        "start_message_id": messages[0].message_id,
        "end_message_id": messages[-1].message_id,
        "visible_content_sha256": _dialogue_sha256(messages),
        "first_message_at": messages[0].timestamp or None,
        "last_message_at": messages[-1].timestamp or None,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise StudyLogError("integrity", f"archive {key} does not match its visible body")
    return metadata, tuple(messages)


def _markdown_destinations(content: str) -> list[str]:
    return [
        unquote((angle or plain).split("#", 1)[0])
        for angle, plain in re.findall(r"\]\((?:<([^>]+)>|([^\s)]+))\)", content)
    ]


def _verify_pair(project: str | Path, structured: str) -> dict[str, Any]:
    record, target, relative = _paired_paths(project, structured)
    if not target.is_file():
        raise StudyLogError("not_found", "paired raw archive does not exist", details={"target": str(target)})
    metadata, messages = _read_verified_archive(target)
    if metadata.get("structured_record") != relative:
        raise StudyLogError("integrity", "raw archive structured_record binding is incorrect")
    if metadata.get("project_fingerprint") != _project_fingerprint(str(project)):
        raise StudyLogError("integrity", "raw archive belongs to another project")
    raw_content = target.read_bytes().decode("utf-8")
    first_message = ARCHIVE_MESSAGE_RE.search(raw_content)
    raw_links = _markdown_destinations(raw_content[:first_message.start()] if first_message else "")
    if f"../{record.parent.name}/{record.name}" not in raw_links:
        raise StudyLogError("integrity", "raw archive is missing its relative structured-record backlink")
    structured_links = _markdown_destinations(record.read_text(encoding="utf-8"))
    expected_link = f"../{record.parent.name}-raw/{record.name}"
    # Existing structured records may be immutable card sources. Their missing
    # backlink is reported, not patched or treated as a migration failure.
    relevant_links = [link.removeprefix("./") for link in structured_links if link.removeprefix("./").startswith(f"../{record.parent.name}-raw/")]
    if relevant_links and any(link != expected_link for link in relevant_links):
        raise StudyLogError("integrity", "structured record links a different raw counterpart")
    return {
        "structured_record": relative, "target": str(target),
        "archive_id": metadata.get("archive_id"), "status": metadata.get("status"),
        "message_count": len(messages), "start_message_id": messages[0].message_id,
        "end_message_id": messages[-1].message_id,
        "visible_content_sha256": metadata["visible_content_sha256"],
        "target_sha256": _sha256_file(target),
        "structured_backlink_present": expected_link in relevant_links,
    }


def _command_verify_pairs(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pairs = [_verify_pair(args.project, record) for record in args.structured_record]
    if len({pair["target"] for pair in pairs}) != len(pairs):
        raise StudyLogError("usage", "structured records must be distinct")
    return {"pairs": pairs, "pair_count": len(pairs), "would_write": False}, []


def _migration_plan(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    request_path = Path(args.request).resolve(strict=True)
    try:
        request_bytes = request_path.read_bytes()
        request = json.loads(request_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise StudyLogError("malformed", "migration request is not valid JSON") from exc
    if not isinstance(request, dict) or request.get("schema") != "study-log.migration/v1":
        raise StudyLogError("malformed", "migration request schema must be study-log.migration/v1")
    for key in ("sources", "records"):
        if not isinstance(request.get(key), list) or not request[key]:
            raise StudyLogError("malformed", f"migration {key} must be a nonempty list")
    project = _canonical_project(args.project)
    sources: dict[str, dict[str, Any]] = {}
    all_message_ids: set[str] = set()
    for source in request["sources"]:
        if not isinstance(source, dict) or not all(isinstance(source.get(key), str) and source[key] for key in ("id", "path", "sha256")):
            raise StudyLogError("malformed", "migration source requires id, path and sha256 strings")
        if source["id"] in sources:
            raise StudyLogError("usage", "migration source IDs must be unique")
        path = Path(source["path"])
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise StudyLogError("safety", "migration source must be an explicit existing non-symlink file")
        if _sha256_file(path) != source["sha256"]:
            raise StudyLogError("integrity", "migration source SHA-256 changed after review")
        metadata, messages = _read_verified_archive(path)
        if _sha256_file(path) != source["sha256"]:
            raise StudyLogError("integrity", "migration source changed while it was parsed")
        if metadata.get("status") != "final":
            raise StudyLogError("safety", "migration accepts finalized source archives only")
        if metadata.get("project_fingerprint") != _project_fingerprint(project):
            raise StudyLogError("safety", "migration source belongs to another project")
        ids = {message.message_id for message in messages}
        if all_message_ids.intersection(ids):
            raise StudyLogError("conflict", "migration sources contain overlapping message IDs")
        all_message_ids.update(ids)
        sources[source["id"]] = {**source, "metadata": metadata, "messages": messages}
    assigned: set[tuple[str, str]] = set()
    plans: list[dict[str, Any]] = []
    targets: set[Path] = set()
    for record in request["records"]:
        if not isinstance(record, dict) or not all(isinstance(record.get(key), str) and record[key].strip() for key in ("structured_record", "title")):
            raise StudyLogError("malformed", "migration record requires structured_record and title strings")
        if not isinstance(record.get("segments"), list) or not record["segments"]:
            raise StudyLogError("malformed", "migration record segments must be a nonempty list")
        structured, target, relative = _paired_paths(project, record["structured_record"])
        if target in targets or target.exists():
            raise StudyLogError("conflict", "migration targets must be distinct and must not exist", details={"target": str(target)})
        targets.add(target)
        selected: list[DialogueMessage] = []
        provenance: list[dict[str, Any]] = []
        compatibility: tuple[Any, ...] | None = None
        for segment in record["segments"]:
            if not isinstance(segment, dict) or not all(isinstance(segment.get(key), str) and segment[key] for key in ("source_id", "start_id", "end_id")):
                raise StudyLogError("malformed", "migration segment requires source_id, start_id and end_id")
            if segment["source_id"] not in sources:
                raise StudyLogError("usage", "migration segment references an unknown source")
            source = sources[segment["source_id"]]
            identity = (source["metadata"]["normalization"], _redaction_identity(source["metadata"]["redaction"]))
            if compatibility is not None and identity != compatibility:
                raise StudyLogError("conflict", "segments paired with one structured record must use the same normalization and redaction policy")
            compatibility = identity
            selection = select_messages(source["messages"], start_id=segment["start_id"], end_id=segment["end_id"])
            for message in selection.messages:
                key = (segment["source_id"], message.message_id)
                if key in assigned:
                    raise StudyLogError("conflict", "migration assigns a source message more than once")
                assigned.add(key)
                selected.append(message)
            provenance.append({
                "source_id": segment["source_id"], "source_archive_id": source["metadata"]["archive_id"],
                "source_file": source["path"], "source_sha256": source["sha256"],
                "source_metadata": source["metadata"],
                "start_message_id": selection.start_message_id,
                "end_message_id": selection.end_message_id,
                "message_count": len(selection.messages),
                "visible_content_sha256": _dialogue_sha256(selection.messages),
            })
        timestamps = [_timestamp_for_message(message) for message in selected if message.timestamp]
        if timestamps != sorted(timestamps):
            raise StudyLogError("conflict", "migration segments must preserve chronological message order")
        report = _privacy_report(selected)
        plans.append({
            "structured_record": relative, "structured_sha256": _sha256_file(structured),
            "target": str(target), "title": " ".join(record["title"].splitlines()).strip(),
            "message_count": len(selected), "start_message_id": selected[0].message_id,
            "end_message_id": selected[-1].message_id,
            "visible_content_sha256": _dialogue_sha256(selected),
            "privacy": {"categories": list(report.categories), "counts": report.counts},
            "segments": provenance, "messages": selected,
        })
    expected = {(source_id, message.message_id) for source_id, source in sources.items() for message in source["messages"]}
    if assigned != expected:
        raise StudyLogError("conflict", "migration must assign every source message exactly once", details={"unassigned_count": len(expected - assigned)})
    public_plans = [{key: value for key, value in plan.items() if key != "messages"} for plan in plans]
    preview = {
        "schema": "study-log.migration-preview/v1", "project": project,
        "request_sha256": _sha256_bytes(request_bytes), "records": public_plans,
        "source_count": len(sources), "record_count": len(plans),
        "message_count": len(assigned), "sources_retained": True,
    }
    digest = _sha256_bytes(json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    preview["preview_digest"] = digest
    return preview, plans, list(sources.values())


def _command_migration(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    preview, plans, sources = _migration_plan(args)
    if args.command == "migrate-preview":
        return {**preview, "would_write": False}, []
    if args.preview_digest != preview["preview_digest"]:
        raise StudyLogError("conflict", "migration preview digest changed; review a fresh preview")
    if not args.privacy_confirmed:
        raise StudyLogError("safety", "migration into repository storage requires privacy confirmation")
    if any("credential" in plan["privacy"]["categories"] for plan in plans):
        raise StudyLogError("safety", "migration source still contains high-confidence credentials; use a separately reviewed redacted export")
    if any("proprietary" in plan["privacy"]["categories"] for plan in plans) and not args.proprietary_confirmed:
        raise StudyLogError("safety", "repository migration of possible proprietary content requires ownership/policy confirmation")
    candidates: list[tuple[Path, str]] = []
    now = datetime.now(UTC).isoformat()
    project = _canonical_project(args.project)
    for plan in plans:
        messages = plan["messages"]
        first_source = plan["segments"][0]["source_metadata"]
        session_ids = list(dict.fromkeys(segment["source_metadata"]["source_session_id"] for segment in plan["segments"]))
        providers = list(dict.fromkeys(segment["source_metadata"]["provider"] for segment in plan["segments"]))
        metadata = {
            "archive_type": "study-log-visible-dialogue", "schema_version": SCHEMA_VERSION,
            "archive_id": f"sl-{uuid.uuid4().hex}", "status": "final", "title": plan["title"],
            "provider": providers[0] if len(providers) == 1 else "mixed",
            "project_name": _project_name(project), "project_fingerprint": _project_fingerprint(project),
            "source_session_id": session_ids[0] if len(session_ids) == 1 else "multiple",
            "source_file": "study-log migration request", "source_sha256": preview["request_sha256"],
            "start_message_id": plan["start_message_id"], "end_message_id": plan["end_message_id"],
            "message_count": plan["message_count"], "visible_content_sha256": plan["visible_content_sha256"],
            "target_precondition_sha256": None,
            "first_message_at": messages[0].timestamp or None, "last_message_at": messages[-1].timestamp or None,
            "created_at_utc": now, "updated_at_utc": now,
            "normalization": first_source["normalization"],
            "redaction": {"version": first_source["redaction"]["version"], "categories": first_source["redaction"]["categories"], "applications": [], "preserved_from_sources": True},
            "privacy_risks": plan["privacy"], "structured_record": plan["structured_record"],
            "message_phases": [message.phase for message in messages],
            "migration": {"schema": "study-log.migration/v1", "preview_digest": preview["preview_digest"], "request_sha256": preview["request_sha256"], "segments": plan["segments"]},
        }
        candidates.append((Path(plan["target"]), _render_archive(messages, metadata)))
    # All inputs and all targets are checked before the first write. On failure,
    # rollback removes only files created by this operation whose hashes still match.
    if _sha256_file(Path(args.request)) != preview["request_sha256"]:
        raise StudyLogError("integrity", "migration request changed before publication")
    for source in sources:
        if _sha256_file(Path(source["path"])) != source["sha256"]:
            raise StudyLogError("integrity", "migration source changed before publication")
    for plan in plans:
        record, target, _relative = _paired_paths(project, plan["structured_record"])
        if target.exists() or _sha256_file(record) != plan["structured_sha256"]:
            raise StudyLogError("conflict", "migration target or structured source changed before publication")
    created: list[tuple[Path, str]] = []
    try:
        for target, content in candidates:
            _project_output(target, Path(project))
            _atomic_write(target, content, expected_sha256=None)
            created.append((target, _sha256_bytes(content.encode("utf-8"))))
        pairs = [_verify_pair(project, plan["structured_record"]) for plan in plans]
    except (StudyLogError, OSError, UnicodeError):
        for target, expected_sha in reversed(created):
            if target.is_file() and not target.is_symlink() and _sha256_file(target) == expected_sha:
                target.unlink()
        raise
    return {"operation": "migrate", "preview_digest": preview["preview_digest"], "pairs": pairs, "message_count": preview["message_count"], "sources_retained": True}, []


def _command_config(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if args.config_action == "get":
        configured = _load_config().get("archive_root")
        return {
            "configured": isinstance(configured, str) and bool(configured),
            "archive_root": configured if isinstance(configured, str) else None,
            "config_file": str(_config_file()),
            "historical_only": True,
            "affects_new_exports": False,
        }, []
    if args.config_action == "set":
        raise StudyLogError("usage", "archive-root configuration is read-only historical compatibility")
    raise StudyLogError("usage", "unsupported config action")


def _add_source_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="explicit project root")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="auto")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--session", help="stable session ID or unambiguous prefix")
    selector.add_argument("--source", help="explicit JSONL source path")


def _add_normalization_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keep-client-context", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--keep-duplicates", action="store_true", help=argparse.SUPPRESS)


def _add_boundary_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", help="YYYY-MM-DD visible-message slice")
    parser.add_argument("--start-id", help="inclusive stable message ID")
    parser.add_argument("--end-id", help="inclusive stable message ID")
    parser.add_argument("--start-user", help="unique user-text fragment, inclusive")
    parser.add_argument("--end-before-user", help="unique user-text fragment, exclusive")
    parser.add_argument("--start-time", help="inclusive ISO-8601 timestamp")
    parser.add_argument("--end-time", help="exclusive ISO-8601 timestamp")
    parser.add_argument("--final-only", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=JsonArgumentParser
    )

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--project", required=True)
    list_parser.add_argument("--provider", choices=sorted(PROVIDERS), default="auto")
    list_parser.add_argument("--date")

    preview_parser = subparsers.add_parser("preview")
    _add_source_selector(preview_parser)
    _add_normalization_flags(preview_parser)
    preview_parser.add_argument("--date")
    preview_parser.add_argument("--preview-chars", type=int, default=160)

    extract_parser = subparsers.add_parser("extract")
    _add_source_selector(extract_parser)
    _add_normalization_flags(extract_parser)
    _add_boundary_flags(extract_parser)
    extract_parser.add_argument("--source-sha256", required=True)
    extract_parser.add_argument("--include-tools", action="store_true")
    extract_parser.add_argument("--output")

    archive_parser = subparsers.add_parser("archive")
    _add_source_selector(archive_parser)
    _add_boundary_flags(archive_parser)
    archive_parser.add_argument("--source-sha256", required=True)
    archive_parser.add_argument("--title", required=True)
    archive_parser.add_argument("--status", choices=("partial", "final"), required=True)
    archive_parser.add_argument("--output")
    archive_parser.add_argument("--structured-record", required=True)
    archive_parser.add_argument("--archive-root")
    archive_parser.add_argument("--archive-id")
    archive_parser.add_argument("--target-sha256")
    archive_parser.add_argument("--privacy-confirmed", action="store_true")
    archive_parser.add_argument(
        "--credential-action", choices=("block", "redact"), default="block"
    )
    archive_parser.add_argument("--redact-personal", action="store_true")
    archive_parser.add_argument("--proprietary-confirmed", action="store_true")
    archive_parser.add_argument("--allow-repo-output", action="store_true")

    verify_parser = subparsers.add_parser("verify-pairs")
    verify_parser.add_argument("--project", required=True)
    verify_parser.add_argument("--structured-record", action="append", required=True)

    for command in ("migrate-preview", "migrate"):
        migration_parser = subparsers.add_parser(command)
        migration_parser.add_argument("--project", required=True)
        migration_parser.add_argument("--request", required=True)
        if command == "migrate":
            migration_parser.add_argument("--preview-digest", required=True)
            migration_parser.add_argument("--privacy-confirmed", action="store_true")
            migration_parser.add_argument("--proprietary-confirmed", action="store_true")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(
        dest="config_area", required=True, parser_class=JsonArgumentParser
    )
    archive_root_parser = config_subparsers.add_parser("archive-root")
    archive_root_subparsers = archive_root_parser.add_subparsers(
        dest="config_action", required=True, parser_class=JsonArgumentParser
    )
    archive_root_subparsers.add_parser("get")
    set_parser = archive_root_subparsers.add_parser("set")
    set_parser.add_argument("path")
    return parser


def _success(command: str, data: dict[str, Any], warnings: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "data": data,
        "warnings": list(warnings),
    }


def _failure(command: str | None, error: StudyLogError) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "command": command,
        "error": {
            "code": error.spec.kind,
            "message": error.spec.message,
            "details": error.spec.details,
        },
    }


def _emit_json(value: dict[str, Any]) -> None:
    # ASCII-only envelopes remain writable even when the active Windows console
    # encoding cannot represent a path or error message.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    command: str | None = None
    try:
        parser = build_parser()
        args = parser.parse_args(list(argv) if argv is not None else None)
        command = args.command
        if command == "list":
            data, warnings = _command_list(args)
        elif command == "preview":
            if args.preview_chars < 1 or args.preview_chars > 1000:
                raise StudyLogError("usage", "--preview-chars must be between 1 and 1000")
            data, warnings = _command_preview(args)
        elif command == "extract":
            data, warnings = _command_extract(args)
        elif command == "archive":
            data, warnings = _command_archive(args)
        elif command == "verify-pairs":
            data, warnings = _command_verify_pairs(args)
        elif command in {"migrate-preview", "migrate"}:
            data, warnings = _command_migration(args)
        elif command == "config":
            data, warnings = _command_config(args)
        else:
            raise StudyLogError("usage", f"unsupported command: {command}")
        _emit_json(_success(command, data, warnings))
        return EXIT_OK
    except StudyLogError as exc:
        _emit_json(_failure(command, exc))
        return exc.exit_code
    except UnicodeError as exc:
        error = StudyLogError(
            "malformed", "text encoding error", details={"reason": str(exc)}
        )
        _emit_json(_failure(command, error))
        return error.exit_code
    except OSError as exc:
        error = StudyLogError("integrity", "operating-system error", details={"reason": str(exc)})
        _emit_json(_failure(command, error))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
