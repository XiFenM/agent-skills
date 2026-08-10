#!/usr/bin/env python3
"""Export user-visible dialogue from a Codex rollout JSONL session."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

ENVIRONMENT_CONTEXT_RE = re.compile(
    r"<environment_context>.*?</environment_context>",
    flags=re.DOTALL,
)
STANDALONE_SKILL_CONTEXT_RE = re.compile(
    r"<skill>.*?</skill>",
    flags=re.DOTALL,
)
RECOMMENDED_PLUGINS_CONTEXT_RE = re.compile(
    r"<recommended_plugins>.*?</recommended_plugins>",
    flags=re.DOTALL,
)
AGENTS_INSTRUCTIONS_CONTEXT_RE = re.compile(
    r"# AGENTS\.md instructions for [^\n]+\s*<INSTRUCTIONS>.*?</INSTRUCTIONS>",
    flags=re.DOTALL,
)
IDE_CONTEXT_PREFIX = "# Context from my IDE setup:"
IDE_REQUEST_MARKER = "## My request for Codex:"
TEXT_CONTENT_TYPES = {"input_text", "output_text"}
VISIBLE_ROLES = {"user", "assistant"}


class DialogueExportError(ValueError):
    """Raised when a session cannot be converted into a dialogue archive."""


@dataclass(frozen=True, slots=True)
class DialogueMessage:
    """One user-visible message extracted from a rollout file."""

    timestamp: str
    role: str
    phase: str | None
    text: str
    source_line: int


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    """Provenance retained for a dialogue export."""

    source_file: str
    source_sha256: str
    session_id: str | None


def normalize_user_text(text: str) -> str:
    """Remove Codex client context wrappers while preserving the user's request text."""
    text = ENVIRONMENT_CONTEXT_RE.sub("", text).strip()
    text = RECOMMENDED_PLUGINS_CONTEXT_RE.sub("", text).strip()
    text = AGENTS_INSTRUCTIONS_CONTEXT_RE.sub("", text).strip()
    if STANDALONE_SKILL_CONTEXT_RE.fullmatch(text):
        return ""
    if IDE_REQUEST_MARKER in text:
        text = text.split(IDE_REQUEST_MARKER, maxsplit=1)[1]
    elif text.startswith(IDE_CONTEXT_PREFIX):
        return ""
    return text.strip()


def _message_text(content: object) -> str:
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for part_object in cast(list[object], content):
        if not isinstance(part_object, dict):
            continue
        part = cast(dict[str, object], part_object)
        part_type = part.get("type")
        if part_type not in TEXT_CONTENT_TYPES:
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def load_dialogue(
    source: Path,
    *,
    keep_client_context: bool = False,
    keep_duplicates: bool = False,
) -> tuple[list[DialogueMessage], SessionMetadata]:
    """Load user and assistant messages from a Codex rollout JSONL file."""
    if not source.is_file():
        raise DialogueExportError(f"session file does not exist: {source}")

    source_bytes = source.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DialogueExportError(f"session is not valid UTF-8: {source}") from exc

    messages: list[DialogueMessage] = []
    session_id: str | None = None

    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            parsed_row: object = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise DialogueExportError(
                f"invalid JSON on line {line_number} of {source}: {exc.msg}"
            ) from exc
        if not isinstance(parsed_row, dict):
            continue
        row = cast(dict[str, object], parsed_row)

        outer_type = row.get("type")
        payload_object = row.get("payload")
        if not isinstance(payload_object, dict):
            continue
        payload = cast(dict[str, object], payload_object)

        if outer_type == "session_meta" and session_id is None:
            candidate_id = payload.get("session_id") or payload.get("id")
            if isinstance(candidate_id, str) and candidate_id:
                session_id = candidate_id
            continue

        if outer_type != "response_item" or payload.get("type") != "message":
            continue

        role_object = payload.get("role")
        if not isinstance(role_object, str) or role_object not in VISIBLE_ROLES:
            continue
        role = role_object

        text = _message_text(payload.get("content"))
        if role == "user" and not keep_client_context:
            text = normalize_user_text(text)
        if not text:
            continue

        phase = payload.get("phase")
        if not isinstance(phase, str):
            phase = None
        timestamp = row.get("timestamp")
        if not isinstance(timestamp, str):
            timestamp = ""

        message = DialogueMessage(
            timestamp=timestamp,
            role=role,
            phase=phase,
            text=text,
            source_line=line_number,
        )
        if (
            not keep_duplicates
            and messages
            and messages[-1].role == message.role
            and messages[-1].text == message.text
        ):
            continue
        messages.append(message)

    metadata = SessionMetadata(
        source_file=source.name,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        session_id=session_id,
    )
    return messages, metadata


def _parse_timestamp(value: str, option_name: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DialogueExportError(
            f"{option_name} must be an ISO-8601 timestamp, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _message_timestamp(message: DialogueMessage) -> datetime:
    if not message.timestamp:
        raise DialogueExportError(
            f"message from source line {message.source_line} has no timestamp"
        )
    return _parse_timestamp(message.timestamp, "message timestamp")


def _find_user_marker(
    messages: list[DialogueMessage],
    marker: str,
    *,
    start_index: int,
    option_name: str,
) -> int:
    for index in range(start_index, len(messages)):
        message = messages[index]
        if message.role == "user" and marker in message.text:
            return index
    raise DialogueExportError(f"{option_name} did not match a user message: {marker!r}")


def select_dialogue(
    messages: list[DialogueMessage],
    *,
    start_user: str | None = None,
    end_before_user: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    final_only: bool = False,
) -> list[DialogueMessage]:
    """Select one lesson-sized interval from the extracted dialogue."""
    start_index = 0
    if start_user is not None:
        start_index = _find_user_marker(
            messages,
            start_user,
            start_index=0,
            option_name="--start-user",
        )

    end_index = len(messages)
    if end_before_user is not None:
        end_index = _find_user_marker(
            messages,
            end_before_user,
            start_index=start_index + 1,
            option_name="--end-before-user",
        )

    selected = messages[start_index:end_index]
    start_datetime = _parse_timestamp(start_time, "--start-time") if start_time else None
    end_datetime = _parse_timestamp(end_time, "--end-time") if end_time else None
    if start_datetime and end_datetime and start_datetime >= end_datetime:
        raise DialogueExportError("--start-time must be earlier than --end-time")

    filtered: list[DialogueMessage] = []
    for message in selected:
        message_datetime = None
        if start_datetime or end_datetime:
            message_datetime = _message_timestamp(message)
        if start_datetime and message_datetime and message_datetime < start_datetime:
            continue
        if end_datetime and message_datetime and message_datetime >= end_datetime:
            continue
        if final_only and message.role == "assistant" and message.phase == "commentary":
            continue
        filtered.append(message)

    if not filtered:
        raise DialogueExportError("the selected dialogue interval is empty")
    return filtered


def dialogue_sha256(messages: list[DialogueMessage]) -> str:
    """Hash the selected message sequence independently from the source file."""
    canonical = [
        {
            "timestamp": message.timestamp,
            "role": message.role,
            "phase": message.phase,
            "text": message.text,
        }
        for message in messages
    ]
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _role_label(message: DialogueMessage) -> str:
    if message.role == "user":
        return "用户"
    if message.phase == "commentary":
        return "助手 / 过程更新"
    if message.phase == "final_answer":
        return "助手 / 正式回答"
    return "助手"


def render_markdown(
    messages: list[DialogueMessage],
    metadata: SessionMetadata,
    *,
    title: str,
    lesson: str | None,
    keep_client_context: bool,
    keep_duplicates: bool,
    final_only: bool,
    exported_at: datetime | None = None,
) -> str:
    """Render a traceable Markdown archive without rewriting message bodies."""
    if exported_at is None:
        exported_at = datetime.now(UTC)
    title = " ".join(title.splitlines()).strip()
    if not title:
        raise DialogueExportError("archive title cannot be empty")

    session_id = metadata.session_id or "unknown"
    first_timestamp = messages[0].timestamp or "unknown"
    last_timestamp = messages[-1].timestamp or "unknown"
    frontmatter = [
        "---",
        'archive_type: "codex-raw-dialogue"',
        f"lesson: {_yaml_string(lesson or 'unspecified')}",
        f"source_file: {_yaml_string(metadata.source_file)}",
        f"session_id: {_yaml_string(session_id)}",
        f"source_sha256: {_yaml_string(metadata.source_sha256)}",
        f"dialogue_sha256: {_yaml_string(dialogue_sha256(messages))}",
        f"exported_at_utc: {_yaml_string(exported_at.isoformat())}",
        f"first_message_at: {_yaml_string(first_timestamp)}",
        f"last_message_at: {_yaml_string(last_timestamp)}",
        f"message_count: {len(messages)}",
        f"client_context: {_yaml_string('preserved' if keep_client_context else 'stripped')}",
        f"duplicates: {_yaml_string('preserved' if keep_duplicates else 'adjacent-removed')}",
        f"assistant_commentary: {_yaml_string('excluded' if final_only else 'included')}",
        "---",
        "",
        f"# {title}",
        "",
        "<!-- Generated by export_codex_dialogue.py; message bodies are not rewritten. -->",
    ]

    body: list[str] = []
    for index, message in enumerate(messages, start=1):
        timestamp = message.timestamp or "unknown"
        body.extend(
            [
                "",
                "---",
                "",
                f"**{index:03d} · {_role_label(message)}** · `{timestamp}`",
                "",
                message.text,
            ]
        )
    return "\n".join([*frontmatter, *body, ""])


def write_archive(output: Path, content: str, *, overwrite: bool) -> None:
    """Atomically write an archive and refuse accidental replacement by default."""
    if output.exists() and not overwrite:
        raise DialogueExportError(
            f"output already exists: {output}; pass --overwrite to replace it"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("session", type=Path, help="Codex rollout JSONL file")
    parser.add_argument(
        "--keep-client-context",
        action="store_true",
        help="preserve environment/IDE context messages and wrappers",
    )
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="preserve adjacent duplicate messages after normalization",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Export user-visible dialogue from a Codex rollout JSONL session."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list",
        help="list extractable messages and previews for choosing lesson boundaries",
    )
    _add_input_options(list_parser)
    list_parser.add_argument(
        "--role",
        choices=("all", "user", "assistant"),
        default="all",
        help="limit the preview to one role",
    )
    list_parser.add_argument(
        "--preview",
        type=int,
        default=120,
        help="maximum preview characters per message",
    )

    export_parser = subparsers.add_parser("export", help="write a Markdown dialogue archive")
    _add_input_options(export_parser)
    export_parser.add_argument("output", type=Path, help="Markdown archive output path")
    export_parser.add_argument("--title", required=True, help="archive document title")
    export_parser.add_argument("--lesson", help="stable lesson identifier stored in frontmatter")
    export_parser.add_argument(
        "--start-user",
        help="include from the first normalized user message containing this text",
    )
    export_parser.add_argument(
        "--end-before-user",
        help="stop before the next normalized user message containing this text",
    )
    export_parser.add_argument("--start-time", help="inclusive ISO-8601 timestamp")
    export_parser.add_argument("--end-time", help="exclusive ISO-8601 timestamp")
    export_parser.add_argument(
        "--final-only",
        action="store_true",
        help="exclude assistant commentary while retaining users and final answers",
    )
    export_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output archive",
    )
    return parser


def _list_messages(args: argparse.Namespace) -> int:
    messages, _ = load_dialogue(
        args.session,
        keep_client_context=args.keep_client_context,
        keep_duplicates=args.keep_duplicates,
    )
    if args.preview < 1:
        raise DialogueExportError("--preview must be at least 1")

    for index, message in enumerate(messages, start=1):
        if args.role != "all" and message.role != args.role:
            continue
        preview = re.sub(r"\s+", " ", message.text)[: args.preview]
        phase = message.phase or "-"
        print(
            f"{index:03d} {message.timestamp or 'unknown'} "
            f"{message.role}/{phase} line={message.source_line} | {preview}"
        )
    return 0


def _export_messages(args: argparse.Namespace) -> int:
    if args.session.resolve() == args.output.resolve():
        raise DialogueExportError("session input and archive output must be different files")

    messages, metadata = load_dialogue(
        args.session,
        keep_client_context=args.keep_client_context,
        keep_duplicates=args.keep_duplicates,
    )
    selected = select_dialogue(
        messages,
        start_user=args.start_user,
        end_before_user=args.end_before_user,
        start_time=args.start_time,
        end_time=args.end_time,
        final_only=args.final_only,
    )
    content = render_markdown(
        selected,
        metadata,
        title=args.title,
        lesson=args.lesson,
        keep_client_context=args.keep_client_context,
        keep_duplicates=args.keep_duplicates,
        final_only=args.final_only,
    )
    write_archive(args.output, content, overwrite=args.overwrite)
    print(f"exported {len(selected)} messages to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the dialogue exporter CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _list_messages(args)
        if args.command == "export":
            return _export_messages(args)
        raise DialogueExportError(f"unsupported command: {args.command}")
    except (DialogueExportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
