#!/usr/bin/env python3
"""Deterministically prepare, verify, and publish managed Markji card bundles.

The agent owns semantic judgement.  This standard-library tool owns the fragile
mechanics: strict configuration, stable identities, templates, deterministic
XLSX rendering, managed manifests, derived inventory, previews, CAS, and
artifact-set publication.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import ipaddress
import json
import os
import re
import tempfile
import unicodedata
import uuid
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, cast
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

REPOSITORY_SCHEMA = "agent-skills.repository/v1"
CONFIG_SCHEMA = "agent-skills.memo-cards/v1"
CONTEXT_SCHEMA = "memo-cards.context/v1"
REQUEST_SCHEMA = "memo-cards.request/v1"
ARTIFACT_SCHEMA_V1 = "memo-cards.artifact/v1"
ARTIFACT_SCHEMA = "memo-cards.artifact/v2"
ARTIFACT_SCHEMAS = {ARTIFACT_SCHEMA_V1, ARTIFACT_SCHEMA}
PREVIEW_SCHEMA = "memo-cards.preview/v2"
REGISTRY_SCHEMA = "memo-cards.markji-template-registry/v1"
WRAPPER_VERSION = 1
MINIMUM_MARKJI_VERSION = (3, 8, 0)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_INTEGRITY = 4
EXIT_SAFETY = 5
EXIT_CONFLICT = 6

ERROR_EXIT_CODES = {
    "usage": EXIT_USAGE,
    "config": EXIT_CONFIG,
    "integrity": EXIT_INTEGRITY,
    "safety": EXIT_SAFETY,
    "conflict": EXIT_CONFLICT,
}

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
LOGICAL_ID_RE = re.compile(r"^mc-[0-9a-f]{24}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
MARKJI_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
RESERVED_RE = re.compile(r"\[(?:T|F|Choice|P|Audio|Card|Pic|E)#")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}

INPUT_KINDS = {
    "structured-log",
    "verified-learning-note",
    "article",
    "question-bank",
    "guide",
    "source-bundle",
}
ASSESSMENTS = {"recall", "production", "discrimination", "mechanism", "oral"}
LAYERS = {"atomic", "mechanism", "oral"}
DEPENDENT_LAYERS = {"mechanism", "oral"}
DEPENDENCY_CHILD_LAYERS = {"atomic", "mechanism"}
DEPENDENCY_REVIEW_REASON = "dependency-drift"
QUALITIES = {"A", "B", "C"}
FACT_STATUSES = {"verified", "unverified", "conflict", "research"}
LIFECYCLES = {"candidate", "research", "active", "review", "archived"}
FIELD_TYPES = {
    "text",
    "content",
    "choice-answer-2",
    "choice-answer-3",
    "choice-answer-4",
    "cloze-answer",
    "anchors-3-5",
}
CONTENT_BLOCK_TYPES = {"lead", "point", "display", "boundary"}
CONTENT_BLOCK_MAXIMUM = 8
CONTENT_BLOCK_LABEL_MAXIMUM = 20
CONTENT_LEAD_COLOR = "36b59d"
CONTENT_BOUNDARY_COLOR = "c47f17"

TEMPLATE_ASSET = (
    Path(__file__).resolve().parents[1] / "assets" / "markji-3.8-templates.json"
)
XLSX_SHEET_NAME = "cards"
XLSX_MAX_BYTES = 32 * 1024 * 1024
XLSX_MAX_MEMBER_BYTES = 16 * 1024 * 1024
XLSX_MAX_CELL_CHARACTERS = 32_767
PUBLICATION_LOCK_NAME = ".memo-cards-publication.lock"
TRANSACTION_JOURNAL_SUFFIX = ".memo-cards-transaction.json"
XLSX_MEMBERS = (
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/worksheets/sheet1.xml",
)


class MemoCardsError(Exception):
    """A stable, user-safe tool failure."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if kind not in ERROR_EXIT_CODES:
            raise ValueError(f"unknown error kind: {kind}")
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = dict(details or {})

    @property
    def exit_code(self) -> int:
        return ERROR_EXIT_CODES[self.kind]


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise MemoCardsError("usage", message)


@dataclass(frozen=True, slots=True)
class Template:
    template_id: str
    version: str
    card_kind: str
    display_name: str
    fields: tuple[tuple[str, str], ...]
    body: str


@dataclass(frozen=True, slots=True)
class Registry:
    version: str
    digest: str
    adapter: dict[str, str]
    templates: tuple[Template, ...]

    @property
    def by_id(self) -> dict[str, Template]:
        return {template.template_id: template for template in self.templates}


@dataclass(frozen=True, slots=True)
class Artifact:
    path: str
    text: str
    manifest: dict[str, Any]
    body: str
    sha256: str
    body_drifted: bool
    header_drifted: bool
    sidecar_reports: tuple[dict[str, Any], ...] = ()
    sidecar_issues: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class Inventory:
    artifacts: tuple[Artifact, ...]
    legacy: tuple[dict[str, str], ...]
    dependency_drift: tuple[dict[str, str], ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PlannedFile:
    relative_path: str
    path: Path
    role: str
    template_id: str | None
    current_sha256: str | None
    candidate_sha256: str | None
    candidate_bytes: bytes | None
    operation: str


@dataclass(frozen=True, slots=True)
class SourcePrecondition:
    relative_path: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class Plan:
    data: dict[str, Any]
    candidate_text: str | None
    candidate_sha256: str | None
    current_sha256: str | None
    target_path: Path
    files: tuple[PlannedFile, ...]
    source_preconditions: tuple[SourcePrecondition, ...]


@dataclass(frozen=True, slots=True)
class TemplateTable:
    template_id: str
    template_version: str
    display_name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    logical_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class XlsxArtifact:
    template_id: str
    relative_path: str
    content: bytes
    sha256: str
    byte_size: int
    table_sha256: str
    row_sha256: tuple[str, ...]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise MemoCardsError(
            "integrity", "cannot hash file", details={"path": str(path)}
        ) from exc


def _object(value: Any, label: str, *, kind: str = "config") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoCardsError(kind, f"{label} must be an object")
    return cast(dict[str, Any], value)


def _strict_keys(
    value: Mapping[str, Any],
    *,
    label: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
    kind: str = "config",
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    unknown = sorted(set(value) - allowed)
    if missing or unknown:
        pieces: list[str] = []
        if missing:
            pieces.append("missing " + ", ".join(missing))
        if unknown:
            pieces.append("unknown " + ", ".join(unknown))
        raise MemoCardsError(kind, f"{label} has invalid fields: {'; '.join(pieces)}")


def _string(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
    maximum: int = 500,
    kind: str = "config",
) -> str:
    if not isinstance(value, str):
        raise MemoCardsError(kind, f"{label} must be a string")
    if nonempty and not value.strip():
        raise MemoCardsError(kind, f"{label} cannot be empty")
    if len(value) > maximum:
        raise MemoCardsError(kind, f"{label} is too long")
    if "\x00" in value:
        raise MemoCardsError(kind, f"{label} contains a NUL byte")
    return value


def _id(value: Any, label: str, *, kind: str = "config") -> str:
    result = _string(value, label, maximum=80, kind=kind)
    if not ID_RE.fullmatch(result):
        raise MemoCardsError(kind, f"{label} must be a lowercase hyphen ID")
    return result


def _digest(value: Any, label: str, *, kind: str = "config") -> str:
    result = _string(value, label, maximum=64, kind=kind)
    if not DIGEST_RE.fullmatch(result):
        raise MemoCardsError(kind, f"{label} must be a lowercase SHA-256 digest")
    return result


def _version_tuple(value: Any, label: str) -> tuple[int, int, int]:
    text = _string(value, label, maximum=32)
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise MemoCardsError("config", f"{label} must be a three-part version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _safe_relative(value: Any, label: str, *, pattern: bool = False) -> str:
    raw = _string(value, label, maximum=500)
    if "\\" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise MemoCardsError("config", f"{label} must be a portable relative path")
    if any(character in raw for character in '<>:"|'):
        raise MemoCardsError("config", f"{label} contains a non-portable character")
    if not pattern and any(character in raw for character in "*?[]"):
        raise MemoCardsError("config", f"{label} cannot contain glob syntax")
    if pattern and any(character in raw for character in "?[]"):
        raise MemoCardsError(
            "config", f"{label} supports only literal text, * and ** glob components"
        )
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise MemoCardsError("config", f"{label} is not a safe relative path")
    for part in parts:
        if part.endswith((" ", ".")):
            raise MemoCardsError("config", f"{label} contains a trailing dot or space")
        stem = part.split(".", 1)[0].casefold()
        if "*" not in stem and stem in WINDOWS_RESERVED_NAMES:
            raise MemoCardsError("config", f"{label} contains a Windows reserved name")
    if pattern:
        for part in parts:
            if "**" in part and part != "**":
                raise MemoCardsError("config", f"{label} uses ** outside its own component")
    return PurePosixPath(*parts).as_posix()


def _patterns(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise MemoCardsError("config", f"{label} must be a non-empty array")
    result = [_safe_relative(item, f"{label}[{index}]", pattern=True) for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise MemoCardsError("config", f"{label} contains duplicate patterns")
    return sorted(result)


def _collection_root(pattern: str, label: str) -> str:
    parts = PurePosixPath(pattern).parts
    literal: list[str] = []
    for part in parts:
        if "*" in part:
            break
        literal.append(part)
    if literal and literal[-1].endswith(".md"):
        literal.pop()
    if not literal:
        raise MemoCardsError(
            "config",
            f"{label} must be anchored below an explicit collection directory",
        )
    return PurePosixPath(*literal).as_posix()


def _exact_markdown_input(pattern: str) -> bool:
    """Return whether an input pattern names one exact Markdown file."""

    return "*" not in pattern and pattern.endswith(".md")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts = pattern.split("/")
    expression = "^"
    for index, part in enumerate(parts):
        if part == "**":
            if index == len(parts) - 1:
                expression += ".*"
            else:
                expression += "(?:[^/]+/)*"
            continue
        for character in part:
            if character == "*":
                expression += "[^/]*"
            else:
                expression += re.escape(character)
        if index != len(parts) - 1:
            expression += "/"
    return re.compile(expression + "$")


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(_glob_regex(pattern).fullmatch(path) for pattern in patterns)


def _validate_repository_config(value: Any) -> dict[str, Any]:
    config = _object(value, "repository config")
    _strict_keys(
        config,
        label="repository config",
        required={"schema", "repository_id"},
        optional={"language", "timezone", "facts"},
    )
    if config["schema"] != REPOSITORY_SCHEMA:
        raise MemoCardsError("config", f"repository config schema must be {REPOSITORY_SCHEMA}")
    result: dict[str, Any] = {
        "repository_id": _id(config["repository_id"], "repository_config.repository_id"),
    }
    if "language" in config:
        language = _string(config["language"], "repository_config.language", maximum=32)
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
            raise MemoCardsError("config", "repository_config.language is not a language tag")
        result["language"] = language
    if "timezone" in config:
        timezone = _string(config["timezone"], "repository_config.timezone", maximum=80)
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", timezone):
            raise MemoCardsError("config", "repository_config.timezone is invalid")
        result["timezone"] = timezone
    if not isinstance(config.get("facts", {}), dict):
        raise MemoCardsError("config", "repository_config.facts must be an object")
    return result


def _validate_skill_config(value: Any) -> dict[str, Any]:
    config = _object(value, "memo-cards config")
    _strict_keys(
        config,
        label="memo-cards config",
        required={"schema", "skill", "adapter", "input_collections", "output_collections"},
    )
    if config["schema"] != CONFIG_SCHEMA:
        raise MemoCardsError("config", f"memo-cards config schema must be {CONFIG_SCHEMA}")
    if config["skill"] != "memo-cards":
        raise MemoCardsError("config", "memo-cards config has the wrong skill identity")

    adapter = _object(config["adapter"], "memo-cards config.adapter")
    _strict_keys(
        adapter,
        label="memo-cards config.adapter",
        required={"id", "client_version", "profile"},
    )
    if adapter["id"] != "markji":
        raise MemoCardsError("config", "the first memo-cards release supports only markji")
    client_version = _string(adapter["client_version"], "adapter.client_version", maximum=32)
    if _version_tuple(client_version, "adapter.client_version") < MINIMUM_MARKJI_VERSION:
        raise MemoCardsError("config", "adapter.client_version must be at least 3.8.00")
    normalized_adapter = {
        "id": "markji",
        "client_version": client_version,
        "profile": _id(adapter["profile"], "adapter.profile"),
    }

    inputs_raw = config["input_collections"]
    if not isinstance(inputs_raw, list) or not inputs_raw:
        raise MemoCardsError("config", "input_collections must be a non-empty array")
    inputs: list[dict[str, Any]] = []
    for index, raw in enumerate(inputs_raw):
        record = _object(raw, f"input_collections[{index}]")
        _strict_keys(
            record,
            label=f"input_collections[{index}]",
            required={"id", "kind", "patterns"},
            optional={"producer"},
        )
        collection_id = _id(record["id"], f"input_collections[{index}].id")
        kind = _string(record["kind"], f"input_collections[{index}].kind", maximum=50)
        if kind not in INPUT_KINDS:
            raise MemoCardsError("config", f"input collection {collection_id} has an unsupported kind")
        patterns = _patterns(record["patterns"], f"input_collections[{index}].patterns")
        normalized_input = {
            "id": collection_id,
            "kind": kind,
            "patterns": patterns,
        }
        if "producer" in record:
            producer = _id(record["producer"], f"input_collections[{index}].producer")
            if kind != "article" or not all(
                _exact_markdown_input(pattern) for pattern in patterns
            ):
                raise MemoCardsError(
                    "config",
                    "input producer is allowed only for exact Markdown article inputs",
                )
            if producer == "memo-cards":
                raise MemoCardsError("config", "input producer cannot be memo-cards itself")
            normalized_input["producer"] = producer
        inputs.append(normalized_input)

    outputs_raw = config["output_collections"]
    if not isinstance(outputs_raw, list) or not outputs_raw:
        raise MemoCardsError("config", "output_collections must be a non-empty array")
    outputs: list[dict[str, Any]] = []
    for index, raw in enumerate(outputs_raw):
        record = _object(raw, f"output_collections[{index}]")
        _strict_keys(
            record,
            label=f"output_collections[{index}]",
            required={"id", "patterns", "inventory_patterns"},
            optional={"soft_target"},
        )
        collection_id = _id(record["id"], f"output_collections[{index}].id")
        patterns = _patterns(record["patterns"], f"output_collections[{index}].patterns")
        inventory_patterns = _patterns(
            record["inventory_patterns"], f"output_collections[{index}].inventory_patterns"
        )
        if any(not pattern.endswith(".md") for pattern in patterns + inventory_patterns):
            raise MemoCardsError("config", "memo-cards output and inventory patterns must end in .md")
        output: dict[str, Any] = {
            "id": collection_id,
            "patterns": patterns,
            "inventory_patterns": inventory_patterns,
        }
        if "soft_target" in record:
            target = _object(record["soft_target"], f"output_collections[{index}].soft_target")
            _strict_keys(
                target,
                label=f"output_collections[{index}].soft_target",
                required={"minimum", "maximum"},
            )
            minimum = target["minimum"]
            maximum = target["maximum"]
            if (
                not isinstance(minimum, int)
                or isinstance(minimum, bool)
                or not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or minimum < 1
                or maximum < minimum
                or maximum > 1000
            ):
                raise MemoCardsError("config", "soft_target must satisfy 1 <= minimum <= maximum <= 1000")
            output["soft_target"] = {"minimum": minimum, "maximum": maximum}
        outputs.append(output)

    all_ids = [record["id"] for record in inputs + outputs]
    if len(all_ids) != len(set(all_ids)):
        raise MemoCardsError("config", "collection IDs must be unique across inputs and outputs")
    return {
        "schema": CONFIG_SCHEMA,
        "skill": "memo-cards",
        "adapter": normalized_adapter,
        "input_collections": sorted(inputs, key=lambda item: item["id"]),
        "output_collections": sorted(outputs, key=lambda item: item["id"]),
    }


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Pure D27 validator called by the shared materializer.

    It performs no filesystem, Git, or network access.  The materializer owns
    tracked-file checks, special-file rejection, and wrapper creation.
    """

    repository = _validate_repository_config(repository_config)
    skill = _validate_skill_config(skill_config)
    context = {
        "schema": CONTEXT_SCHEMA,
        "repository": repository,
        "adapter": skill["adapter"],
        "input_collections": skill["input_collections"],
        "output_collections": skill["output_collections"],
    }
    tracked_files = sorted(
        {
            pattern
            for record in skill["input_collections"]
            for pattern in record["patterns"]
            if _exact_markdown_input(pattern)
        }
    )
    tracked_collections = sorted(
        {
            _collection_root(pattern, f"collection {record['id']}")
            for record in skill["input_collections"]
            for pattern in record["patterns"]
            if not _exact_markdown_input(pattern)
        }
        | {
            _collection_root(pattern, f"inventory {record['id']}")
            for record in skill["output_collections"]
            for pattern in record["inventory_patterns"]
        }
    )
    write_paths = sorted(
        {
            _collection_root(pattern, f"output {record['id']}")
            for record in skill["output_collections"]
            for pattern in record["patterns"]
        }
    )
    binary_collection_extensions = {
        collection: [".xlsx"]
        for collection in sorted(
            {
                _collection_root(pattern, f"inventory {record['id']}")
                for record in skill["output_collections"]
                for pattern in record["inventory_patterns"]
            }
        )
    }
    read_handoffs = sorted(
        (
            {"path": pattern, "producer": record["producer"]}
            for record in skill["input_collections"]
            if "producer" in record
            for pattern in record["patterns"]
        ),
        key=lambda item: (item["path"], item["producer"]),
    )
    return {
        "context": context,
        "tracked_files": tracked_files,
        "tracked_collections": tracked_collections,
        "write_paths": write_paths,
        "binary_collection_extensions": binary_collection_extensions,
        "read_handoffs": read_handoffs,
    }


def _validate_context_wrapper(value: Any) -> dict[str, Any]:
    wrapper = _object(value, "materialized context")
    _strict_keys(
        wrapper,
        label="materialized context",
        required={
            "version",
            "manager",
            "skill",
            "repository_id",
            "sources",
            "context",
            "allowlist",
        },
    )
    if wrapper["version"] != WRAPPER_VERSION or wrapper["manager"] != "agent-skills":
        raise MemoCardsError("config", "materialized context ownership is invalid")
    if wrapper["skill"] != "memo-cards":
        raise MemoCardsError("config", "materialized context has the wrong skill identity")
    _id(wrapper["repository_id"], "materialized context.repository_id")

    sources = _object(wrapper["sources"], "materialized context.sources")
    _strict_keys(sources, label="materialized context.sources", required={"repository", "skill"})
    for source_name in ("repository", "skill"):
        source = _object(sources[source_name], f"materialized context.sources.{source_name}")
        _strict_keys(
            source,
            label=f"materialized context.sources.{source_name}",
            required={"path", "digest"},
        )
        _safe_relative(source["path"], f"materialized context.sources.{source_name}.path")
        _digest(source["digest"], f"materialized context.sources.{source_name}.digest")

    context = _object(wrapper["context"], "materialized context.context")
    _strict_keys(
        context,
        label="materialized context.context",
        required={"schema", "repository", "adapter", "input_collections", "output_collections"},
    )
    if context["schema"] != CONTEXT_SCHEMA:
        raise MemoCardsError("config", f"materialized context schema must be {CONTEXT_SCHEMA}")
    _object(context["repository"], "materialized context.context.repository")

    allowlist = _object(wrapper["allowlist"], "materialized context.allowlist")
    _strict_keys(
        allowlist,
        label="materialized context.allowlist",
        required={"tracked_files", "tracked_collections", "write_paths"},
    )
    for field in ("tracked_files", "tracked_collections", "write_paths"):
        values = allowlist[field]
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise MemoCardsError("config", f"materialized context.allowlist.{field} must be a string array")
        normalized = [
            _safe_relative(item, f"materialized context.allowlist.{field}[{index}]")
            for index, item in enumerate(values)
        ]
        if normalized != sorted(set(normalized)):
            raise MemoCardsError(
                "config",
                f"materialized context.allowlist.{field} must be sorted and unique",
            )
    return wrapper


def _path_is_within(relative: str, collection: str) -> bool:
    path_parts = PurePosixPath(relative).parts
    collection_parts = PurePosixPath(collection).parts
    return path_parts[: len(collection_parts)] == collection_parts


def _load_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MemoCardsError("integrity", f"cannot read {label}", details={"path": str(path)}) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoCardsError("integrity", f"{label} is not UTF-8", details={"path": str(path)}) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MemoCardsError(
            "integrity",
            f"{label} is not valid JSON",
            details={"path": str(path), "line": exc.lineno, "column": exc.colno},
        ) from exc


def _windows_alias_relative(root: Path, absolute_path: Path) -> str:
    if os.name != "nt":
        raise ValueError("Windows path aliases are unavailable")
    parts = [absolute_path.name]
    current = absolute_path
    while True:
        if (current.exists() or current.is_symlink()) and _is_link_or_junction(current):
            raise MemoCardsError(
                "safety",
                "materialized context path crosses a link or junction",
                details={"path": str(absolute_path)},
            )
        if current != absolute_path:
            try:
                if os.path.samefile(current, root):
                    return PurePosixPath(*reversed(parts)).as_posix()
            except OSError:
                pass
        parent = current.parent
        if parent == current:
            break
        if current != absolute_path:
            parts.append(current.name)
        current = parent
    raise ValueError("context has no repository-root ancestor")


def _load_runtime_context(
    root: Path,
    context_path: Path,
    *,
    check_tracked_files: bool = True,
) -> dict[str, Any]:
    try:
        absolute_context = Path(os.path.abspath(os.fspath(context_path)))
        common = Path(os.path.commonpath([root, absolute_context]))
        if os.path.normcase(os.fspath(common)) == os.path.normcase(os.fspath(root)):
            context_relative = Path(os.path.relpath(absolute_context, root)).as_posix()
        else:
            context_relative = _windows_alias_relative(root, absolute_context)
    except (OSError, ValueError) as exc:
        raise MemoCardsError(
            "safety", "materialized context must be inside the consumer repository"
        ) from exc
    safe_context = _resolve_under(
        root,
        context_relative,
        label="materialized context",
        must_exist=True,
    )
    if not safe_context.is_file() or _is_link_or_junction(safe_context):
        raise MemoCardsError("safety", "materialized context must be a regular non-link file")
    wrapper = _load_json(safe_context, "materialized context")
    wrapper = _validate_context_wrapper(wrapper)
    source_configs: dict[str, Any] = {}
    for source_name in ("repository", "skill"):
        source = wrapper["sources"][source_name]
        path = _resolve_under(
            root,
            source["path"],
            label=f"materialized context source {source_name}",
            must_exist=True,
        )
        if not path.is_file() or _is_link_or_junction(path):
            raise MemoCardsError("safety", "materialized context source must be a regular non-link file")
        actual = _sha256_file(path)
        if actual != source["digest"]:
            raise MemoCardsError(
                "conflict",
                "materialized context is stale; materialize again",
                details={"source": source_name, "expected": source["digest"], "actual": actual},
            )
        source_configs[source_name] = _load_json(
            path, f"materialized context source {source_name}"
        )

    expected = validate_materialized_context(
        source_configs["repository"], source_configs["skill"]
    )
    if wrapper["context"] != expected["context"]:
        raise MemoCardsError(
            "conflict", "materialized context does not match its source configs; materialize again"
        )
    if wrapper["repository_id"] != expected["context"]["repository"]["repository_id"]:
        raise MemoCardsError("conflict", "materialized context repository identity drifted")

    allowlist = wrapper["allowlist"]
    if allowlist["tracked_collections"] != expected["tracked_collections"]:
        raise MemoCardsError("conflict", "materialized tracked collections drifted")
    if allowlist["write_paths"] != expected["write_paths"]:
        raise MemoCardsError("conflict", "materialized write paths drifted")

    explicit_files = set(expected["tracked_files"])
    concrete_files = set(allowlist["tracked_files"])
    if not explicit_files <= concrete_files:
        raise MemoCardsError("conflict", "materialized context omitted an explicit tracked file")
    collections = expected["tracked_collections"]
    for relative in sorted(concrete_files):
        if relative not in explicit_files and not any(
            _path_is_within(relative, collection) for collection in collections
        ):
            raise MemoCardsError(
                "conflict",
                "materialized context contains a tracked file outside declared collections",
                details={"path": relative},
            )
        if check_tracked_files:
            path = _resolve_under(
                root, relative, label="materialized tracked file", must_exist=True
            )
            if not path.is_file() or _is_link_or_junction(path):
                raise MemoCardsError(
                    "safety",
                    "materialized tracked file must remain a regular non-link file",
                    details={"path": relative},
                )
    return wrapper


def load_template_registry(path: Path | None = None) -> Registry:
    asset = path or TEMPLATE_ASSET
    value = _load_json(asset, "template registry")
    registry = _object(value, "template registry")
    _strict_keys(
        registry,
        label="template registry",
        required={"schema", "registry_version", "adapter", "templates"},
        kind="integrity",
    )
    if registry["schema"] != REGISTRY_SCHEMA:
        raise MemoCardsError("integrity", "template registry schema is unsupported")
    version = _string(registry["registry_version"], "template registry.registry_version", maximum=32, kind="integrity")
    adapter = _object(registry["adapter"], "template registry.adapter")
    _strict_keys(
        adapter,
        label="template registry.adapter",
        required={"id", "minimum_client_version"},
        kind="integrity",
    )
    if adapter["id"] != "markji" or adapter["minimum_client_version"] != "3.8.00":
        raise MemoCardsError("integrity", "template registry adapter compatibility drifted")
    raw_templates = registry["templates"]
    if not isinstance(raw_templates, list) or not raw_templates:
        raise MemoCardsError("integrity", "template registry.templates must be non-empty")
    templates: list[Template] = []
    normalized_templates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_templates):
        item = _object(raw, f"template registry.templates[{index}]")
        _strict_keys(
            item,
            label=f"template registry.templates[{index}]",
            required={"id", "version", "card_kind", "display_name", "fields", "body"},
            kind="integrity",
        )
        template_id = _string(item["id"], f"template[{index}].id", maximum=80, kind="integrity")
        if not TEMPLATE_ID_RE.fullmatch(template_id):
            raise MemoCardsError("integrity", f"template {template_id!r} has an invalid ID")
        template_version = _string(item["version"], f"template[{index}].version", maximum=32, kind="integrity")
        if not re.fullmatch(r"\d+\.\d+\.\d+", template_version):
            raise MemoCardsError("integrity", f"template {template_id} has an invalid version")
        card_kind = _string(item["card_kind"], f"template[{index}].card_kind", maximum=80, kind="integrity")
        display_name = _string(item["display_name"], f"template[{index}].display_name", maximum=100, kind="integrity")
        fields_raw = item["fields"]
        if not isinstance(fields_raw, list) or not fields_raw:
            raise MemoCardsError("integrity", f"template {template_id} fields must be non-empty")
        fields: list[tuple[str, str]] = []
        normalized_fields: list[dict[str, str]] = []
        for field_index, field_raw in enumerate(fields_raw):
            field = _object(field_raw, f"template {template_id}.fields[{field_index}]")
            _strict_keys(
                field,
                label=f"template {template_id}.fields[{field_index}]",
                required={"name", "type"},
                kind="integrity",
            )
            name = _string(field["name"], f"template {template_id} field name", maximum=80, kind="integrity")
            field_type = _string(field["type"], f"template {template_id} field type", maximum=50, kind="integrity")
            if field_type not in FIELD_TYPES:
                raise MemoCardsError("integrity", f"template {template_id} has unsupported field type {field_type}")
            fields.append((name, field_type))
            normalized_fields.append({"name": name, "type": field_type})
        names = [name for name, _field_type in fields]
        if len(names) != len(set(names)):
            raise MemoCardsError("integrity", f"template {template_id} repeats a field")
        body = _string(item["body"], f"template {template_id}.body", maximum=10000, kind="integrity")
        if "\t" in body or "\r" in body:
            raise MemoCardsError("integrity", f"template {template_id} contains unsafe whitespace")
        if PLACEHOLDER_RE.findall(body) != names:
            raise MemoCardsError(
                "integrity",
                f"template {template_id} field order differs from placeholder order",
            )
        for color in re.findall(r"!{1,2}([0-9A-Fa-f]{6})", body):
            if color != color.lower():
                raise MemoCardsError("integrity", f"template {template_id} uses an uppercase color")
        templates.append(Template(template_id, template_version, card_kind, display_name, tuple(fields), body))
        normalized_templates.append(
            {
                "id": template_id,
                "version": template_version,
                "card_kind": card_kind,
                "display_name": display_name,
                "fields": normalized_fields,
                "body": body,
            }
        )
    ids = [template.template_id for template in templates]
    if len(ids) != len(set(ids)):
        raise MemoCardsError("integrity", "template registry repeats an ID")
    normalized = {
        "schema": REGISTRY_SCHEMA,
        "registry_version": version,
        "adapter": {"id": "markji", "minimum_client_version": "3.8.00"},
        "templates": normalized_templates,
    }
    return Registry(
        version=version,
        digest=_digest_value(normalized),
        adapter=cast(dict[str, str], normalized["adapter"]),
        templates=tuple(templates),
    )


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    try:
        return bool(checker()) if checker is not None else False
    except OSError:
        return True


def _repository_root(path: Path) -> Path:
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise MemoCardsError("safety", "repository root does not exist", details={"path": str(path)}) from exc
    if not root.is_dir() or _is_link_or_junction(path):
        raise MemoCardsError("safety", "repository root must be a real directory")
    return root


def _resolve_under(
    root: Path,
    relative: str,
    *,
    label: str,
    must_exist: bool,
) -> Path:
    safe = _safe_relative(relative, label)
    candidate = root.joinpath(*PurePosixPath(safe).parts)
    current = root
    for part in PurePosixPath(safe).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_link_or_junction(current):
                raise MemoCardsError("safety", f"{label} crosses a link or junction", details={"path": safe})
        else:
            break
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MemoCardsError("safety", f"{label} escapes the repository", details={"path": safe}) from exc
    if must_exist and not candidate.exists():
        raise MemoCardsError("integrity", f"{label} does not exist", details={"path": safe})
    return candidate


def _plain_text(value: Any, label: str, *, maximum: int = 5000) -> str:
    text = _string(value, label, maximum=maximum, kind="integrity")
    if "\t" in text or "\n" in text or "\r" in text:
        raise MemoCardsError("integrity", f"{label} must be a single spreadsheet-safe line")
    if any(unicodedata.category(character) in {"Cc", "Zl", "Zp"} for character in text):
        raise MemoCardsError(
            "integrity", f"{label} contains a control or Unicode line-separator character"
        )
    if "]" in text or RESERVED_RE.search(text) or "---" in text or "```" in text:
        raise MemoCardsError("integrity", f"{label} collides with reserved Markji or staging syntax")
    return text


def _public_url(value: Any, label: str) -> str:
    url = _plain_text(value, label, maximum=2000)
    if '"' in url:
        raise MemoCardsError("integrity", f"{label} cannot contain a quote")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise MemoCardsError("integrity", f"{label} is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MemoCardsError("integrity", f"{label} must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise MemoCardsError("integrity", f"{label} cannot contain credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise MemoCardsError("integrity", f"{label} is not a public URL")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            raise MemoCardsError("integrity", f"{label} must use a public hostname")
    else:
        if not address.is_global:
            raise MemoCardsError("integrity", f"{label} is not a public URL")
    return url


def _markji_id(value: Any, label: str) -> str:
    result = _plain_text(value, label, maximum=128)
    if not MARKJI_ID_RE.fullmatch(result):
        raise MemoCardsError("integrity", f"{label} is not an explicit Markji ID")
    return result


def _render_content_parts(parts: Any, label: str, *, mode: str = "single-line") -> str:
    if not isinstance(parts, list) or not parts:
        raise MemoCardsError("integrity", f"{label} must be a non-empty array")
    rendered: list[str] = []
    part_types: list[str] = []
    for index, raw in enumerate(parts):
        part_label = f"{label}[{index}]"
        part = _object(raw, part_label)
        part_type = _string(part.get("type"), f"{part_label}.type", maximum=30, kind="integrity")
        part_types.append(part_type)
        if part_type == "text":
            _strict_keys(part, label=part_label, required={"type", "text"}, kind="integrity")
            rendered.append(_plain_text(part["text"], f"{part_label}.text"))
        elif part_type == "formula":
            _strict_keys(part, label=part_label, required={"type", "katex"}, kind="integrity")
            katex = _plain_text(part["katex"], f"{part_label}.katex", maximum=2000)
            if "]" in katex:
                raise MemoCardsError("integrity", f"{part_label}.katex cannot contain ]")
            rendered.append(f"[E##{katex}]")
        elif part_type == "link":
            _strict_keys(part, label=part_label, required={"type", "url", "label"}, kind="integrity")
            url = _public_url(part["url"], f"{part_label}.url")
            display = _plain_text(part["label"], f"{part_label}.label")
            rendered.append(f'[T#link/"{url}"#{display}]')
        elif part_type == "audio":
            _strict_keys(
                part,
                label=part_label,
                required={"type", "id", "text"},
                optional={"autoplay"},
                kind="integrity",
            )
            media_id = _markji_id(part["id"], f"{part_label}.id")
            display = _plain_text(part["text"], f"{part_label}.text")
            autoplay = part.get("autoplay", False)
            if not isinstance(autoplay, bool):
                raise MemoCardsError("integrity", f"{part_label}.autoplay must be boolean")
            parameter = ",A" if autoplay else ""
            rendered.append(f"[Audio#ID/{media_id}{parameter}#{display}]")
        elif part_type == "image":
            _strict_keys(
                part,
                label=part_label,
                required={"type", "id"},
                optional={"mask_id"},
                kind="integrity",
            )
            image_id = _markji_id(part["id"], f"{part_label}.id")
            mask = ""
            if "mask_id" in part:
                mask = f",MID/{_markji_id(part['mask_id'], f'{part_label}.mask_id')}"
            rendered.append(f"[Pic#ID/{image_id}{mask}#]")
        elif part_type == "card-ref":
            _strict_keys(part, label=part_label, required={"type", "ids", "text"}, kind="integrity")
            ids = part["ids"]
            if not isinstance(ids, list) or not ids or len(ids) > 20:
                raise MemoCardsError("integrity", f"{part_label}.ids must contain 1-20 explicit IDs")
            normalized_ids = [_markji_id(item, f"{part_label}.ids[{item_index}]") for item_index, item in enumerate(ids)]
            display = _plain_text(part["text"], f"{part_label}.text")
            rendered.append(f"[Card#ID/{'-'.join(normalized_ids)}#{display}]")
        else:
            raise MemoCardsError("integrity", f"{part_label}.type is unsupported")
    display_types = {"formula", "image"}
    has_display_part = bool(display_types.intersection(part_types))
    if mode == "plain" and any(part_type != "text" for part_type in part_types):
        raise MemoCardsError(
            "integrity",
            f"{label} is embedded by its template and accepts text parts only",
        )
    if mode == "inline" and has_display_part:
        raise MemoCardsError(
            "integrity",
            f"{label} formula and image parts require a display block",
        )
    if mode == "display":
        is_formula_line = part_types == ["formula"]
        is_image_line = bool(part_types) and set(part_types) == {"image"}
        if not (is_formula_line or is_image_line):
            raise MemoCardsError(
                "integrity",
                f"{label} display block must contain one formula or only images",
            )
    elif mode == "single-line" and has_display_part:
        is_formula_line = part_types == ["formula"]
        is_image_line = bool(part_types) and set(part_types) == {"image"}
        if not (is_formula_line or is_image_line):
            raise MemoCardsError(
                "integrity",
                f"{label} formula and image parts must occupy the whole line",
            )
    result = "".join(rendered)
    if "\t" in result or "\n" in result or "\r" in result:
        raise MemoCardsError("integrity", f"{label} rendered unsafe spreadsheet whitespace")
    return result


def _content_block_label(value: Any, label: str) -> str:
    result = _plain_text(value, label, maximum=CONTENT_BLOCK_LABEL_MAXIMUM)
    if result != result.strip():
        raise MemoCardsError("integrity", f"{label} cannot have surrounding whitespace")
    return result


def _render_content_blocks(blocks: Any, label: str) -> str:
    if (
        not isinstance(blocks, list)
        or not blocks
        or len(blocks) > CONTENT_BLOCK_MAXIMUM
    ):
        raise MemoCardsError(
            "integrity",
            f"{label} must contain 1-{CONTENT_BLOCK_MAXIMUM} blocks",
        )
    rendered: list[tuple[str, str]] = []
    for index, raw in enumerate(blocks):
        block_label = f"{label}[{index}]"
        block = _object(raw, block_label)
        block_type = _string(
            block.get("type"),
            f"{block_label}.type",
            maximum=20,
            kind="integrity",
        )
        if block_type not in CONTENT_BLOCK_TYPES:
            raise MemoCardsError(
                "integrity", f"{block_label}.type is unsupported"
            )
        if block_type == "lead":
            _strict_keys(
                block,
                label=block_label,
                required={"type", "parts"},
                optional={"label"},
                kind="integrity",
            )
            if index != 0:
                raise MemoCardsError(
                    "integrity", f"{block_label} lead must be the first block"
                )
            body = _render_content_parts(
                block["parts"], f"{block_label}.parts", mode="inline"
            )
            lead_label = _content_block_label(
                block.get("label", "结论"), f"{block_label}.label"
            )
            rendered.append(
                (
                    block_type,
                    f"[T#B,!{CONTENT_LEAD_COLOR}#{lead_label}]：{body}",
                )
            )
            continue
        if block_type == "point":
            _strict_keys(
                block,
                label=block_label,
                required={"type", "label", "parts"},
                kind="integrity",
            )
            point_label = _content_block_label(
                block["label"], f"{block_label}.label"
            )
            body = _render_content_parts(
                block["parts"], f"{block_label}.parts", mode="inline"
            )
            rendered.append(
                (block_type, f"• [T#B#{point_label}]：{body}")
            )
            continue
        if block_type == "display":
            _strict_keys(
                block,
                label=block_label,
                required={"type", "parts"},
                kind="integrity",
            )
            rendered.append(
                (
                    block_type,
                    _render_content_parts(
                        block["parts"],
                        f"{block_label}.parts",
                        mode="display",
                    ),
                )
            )
            continue
        _strict_keys(
            block,
            label=block_label,
            required={"type", "parts"},
            optional={"label"},
            kind="integrity",
        )
        if index != len(blocks) - 1:
            raise MemoCardsError(
                "integrity", f"{block_label} boundary must be the last block"
            )
        boundary_label = _content_block_label(
            block.get("label", "边界"), f"{block_label}.label"
        )
        body = _render_content_parts(
            block["parts"], f"{block_label}.parts", mode="inline"
        )
        rendered.append(
            (
                block_type,
                f"[T#B,!{CONTENT_BOUNDARY_COLOR}#{boundary_label}]：{body}",
            )
        )
    lines: list[str] = []
    for index, (block_type, text) in enumerate(rendered):
        if index and (rendered[index - 1][0] == "lead" or block_type == "boundary"):
            lines.append("")
        lines.append(text)
    return "\n".join(lines)


def _render_content(value: Any, label: str) -> str:
    if isinstance(value, str):
        return _plain_text(value, label)
    content = _object(value, label)
    if "parts" in content:
        _strict_keys(content, label=label, required={"parts"}, kind="integrity")
        return _render_content_parts(content["parts"], f"{label}.parts")
    if "blocks" in content:
        _strict_keys(content, label=label, required={"blocks"}, kind="integrity")
        return _render_content_blocks(content["blocks"], f"{label}.blocks")
    raise MemoCardsError(
        "integrity", f"{label} must contain exactly one of parts or blocks"
    )


def _render_embedded_content(value: Any, label: str) -> str:
    if isinstance(value, str):
        return _plain_text(value, label)
    content = _object(value, label)
    _strict_keys(content, label=label, required={"parts"}, kind="integrity")
    return _render_content_parts(content["parts"], f"{label}.parts", mode="plain")


def _template_field_is_standalone(template: Template, field_name: str) -> bool:
    placeholder = "{{" + field_name + "}}"
    matching_contexts: list[tuple[str, bool]] = []
    inside_choice = False
    for line in template.body.splitlines():
        if placeholder in line:
            matching_contexts.append((line, inside_choice))
        if line.startswith("[Choice#"):
            inside_choice = True
        elif inside_choice and line == "]":
            inside_choice = False
    if len(matching_contexts) != 1:
        raise MemoCardsError(
            "integrity",
            f"template {template.template_id} field {field_name} must occur on one line",
        )
    line, nested_in_choice = matching_contexts[0]
    return line == placeholder and not nested_in_choice


def _render_field(
    value: Any,
    field_type: str,
    label: str,
    *,
    standalone_content: bool = False,
) -> str:
    if field_type == "text":
        return _plain_text(value, label)
    if field_type == "content":
        if standalone_content:
            return _render_content(value, label)
        return _render_embedded_content(value, label)
    if field_type.startswith("choice-answer-"):
        count = int(field_type.rsplit("-", 1)[1])
        answer = _plain_text(value, label, maximum=count)
        allowed = "ABCD"[:count]
        if not answer or any(character not in allowed for character in answer):
            raise MemoCardsError("integrity", f"{label} must use answer letters from {allowed}")
        if answer != "".join(sorted(set(answer))):
            raise MemoCardsError("integrity", f"{label} answer letters must be unique and ordered")
        return answer
    if field_type == "cloze-answer":
        answer = _plain_text(value, label, maximum=100)
        words = re.findall(r"\b\w+\b", answer, flags=re.UNICODE)
        if not 1 <= len(words) <= 3:
            raise MemoCardsError("integrity", f"{label} must be a uniquely determined 1-3 word answer")
        return answer
    if field_type == "anchors-3-5":
        if not isinstance(value, list) or not 3 <= len(value) <= 5:
            raise MemoCardsError("integrity", f"{label} must contain 3-5 scoring anchors")
        return "；".join(_plain_text(item, f"{label}[{index}]", maximum=500) for index, item in enumerate(value))
    raise MemoCardsError("integrity", f"{label} has an unsupported field type")


def _normalize_identity_text(value: Any, label: str) -> str:
    text = _plain_text(value, label, maximum=1000)
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _fact_scope(value: Any, label: str) -> dict[str, str]:
    scope = _object(value, label)
    kind = scope.get("kind")
    if kind == "evergreen":
        _strict_keys(scope, label=label, required={"kind"}, kind="integrity")
        return {"kind": "evergreen"}
    if kind == "snapshot":
        _strict_keys(
            scope,
            label=label,
            required={"kind", "product"},
            optional={"version", "commit"},
            kind="integrity",
        )
        product = _normalize_identity_text(scope["product"], f"{label}.product")
        result = {"kind": "snapshot", "product": product}
        if "version" in scope:
            result["version"] = _normalize_identity_text(scope["version"], f"{label}.version")
        if "commit" in scope:
            commit = _plain_text(scope["commit"], f"{label}.commit", maximum=64)
            if not COMMIT_RE.fullmatch(commit):
                raise MemoCardsError("integrity", f"{label}.commit must be a 7-64 digit hexadecimal commit")
            result["commit"] = commit.lower()
        if "version" not in result and "commit" not in result:
            raise MemoCardsError("integrity", f"{label} snapshot needs a version or commit")
        return result
    raise MemoCardsError("integrity", f"{label}.kind must be evergreen or snapshot")


def _logical_identity(card: Mapping[str, Any], label: str) -> tuple[dict[str, Any], str]:
    assessment = _string(card["assessment"], f"{label}.assessment", maximum=30, kind="integrity")
    if assessment not in ASSESSMENTS:
        raise MemoCardsError("integrity", f"{label}.assessment is unsupported")
    identity = {
        "domain": _normalize_identity_text(card["domain"], f"{label}.domain"),
        "recall_target": _normalize_identity_text(card["recall_target"], f"{label}.recall_target"),
        "assessment": assessment,
        "fact_scope": _fact_scope(card["fact_scope"], f"{label}.fact_scope"),
    }
    return identity, "mc-" + _digest_value(identity)[:24]


def _validate_request(value: Any, context: Mapping[str, Any], registry: Registry) -> dict[str, Any]:
    request = _object(value, "request")
    _strict_keys(
        request,
        label="request",
        required={"schema", "output_collection", "target", "selection", "sources", "cards"},
        kind="integrity",
    )
    if request["schema"] != REQUEST_SCHEMA:
        raise MemoCardsError("integrity", f"request.schema must be {REQUEST_SCHEMA}")
    outputs = {record["id"]: record for record in context["output_collections"]}
    output_id = _id(request["output_collection"], "request.output_collection", kind="integrity")
    if output_id not in outputs:
        raise MemoCardsError("safety", "request output collection is not allowed")
    target = _safe_relative(request["target"], "request.target")
    output = outputs[output_id]
    if not _matches(target, output["patterns"]):
        raise MemoCardsError("safety", "request target is outside the output collection")
    if not _matches(target, output["inventory_patterns"]):
        raise MemoCardsError("config", "request target is not covered by its inventory patterns")
    selection = _string(request["selection"], "request.selection", maximum=20, kind="integrity")
    if selection not in {"selected", "complete"}:
        raise MemoCardsError("integrity", "request.selection must be selected or complete")

    inputs = {record["id"]: record for record in context["input_collections"]}
    sources_raw = request["sources"]
    if not isinstance(sources_raw, list) or not sources_raw:
        raise MemoCardsError("integrity", "request.sources must be a non-empty array")
    sources: list[dict[str, str]] = []
    for index, raw in enumerate(sources_raw):
        source = _object(raw, f"request.sources[{index}]")
        _strict_keys(
            source,
            label=f"request.sources[{index}]",
            required={"id", "collection", "path", "sha256", "summary"},
            kind="integrity",
        )
        source_id = _id(source["id"], f"request.sources[{index}].id", kind="integrity")
        collection = _id(source["collection"], f"request.sources[{index}].collection", kind="integrity")
        if collection not in inputs:
            raise MemoCardsError("safety", f"source {source_id} uses an unallowed collection")
        path = _safe_relative(source["path"], f"request.sources[{index}].path")
        if not _matches(path, inputs[collection]["patterns"]):
            raise MemoCardsError("safety", f"source {source_id} is outside its collection")
        sources.append(
            {
                "id": source_id,
                "collection": collection,
                "path": path,
                "sha256": _digest(source["sha256"], f"request.sources[{index}].sha256", kind="integrity"),
                "summary": _plain_text(source["summary"], f"request.sources[{index}].summary", maximum=500),
            }
        )
    source_ids = [source["id"] for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise MemoCardsError("integrity", "request.sources repeats an ID")

    cards_raw = request["cards"]
    if not isinstance(cards_raw, list):
        raise MemoCardsError("integrity", "request.cards must be an array")
    templates = registry.by_id
    cards: list[dict[str, Any]] = []
    for index, raw in enumerate(cards_raw):
        label = f"request.cards[{index}]"
        card = _object(raw, label)
        _strict_keys(
            card,
            label=label,
            required={
                "key",
                "rank",
                "domain",
                "recall_target",
                "assessment",
                "layer",
                "fact_scope",
                "quality",
                "fact_status",
                "lifecycle",
                "priority",
                "template_id",
                "fields",
                "source_ids",
                "content_summary",
                "depends_on",
            },
            optional={"successor_to", "misconception_of", "review_resolution"},
            kind="integrity",
        )
        key = _id(card["key"], f"{label}.key", kind="integrity")
        rank = card["rank"]
        priority = card["priority"]
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise MemoCardsError("integrity", f"{label}.rank must be a positive integer")
        if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 5:
            raise MemoCardsError("integrity", f"{label}.priority must be in 1..5")
        identity, logical_id = _logical_identity(card, label)
        layer = _string(card["layer"], f"{label}.layer", maximum=20, kind="integrity")
        if layer not in LAYERS:
            raise MemoCardsError("integrity", f"{label}.layer is unsupported")
        quality = _string(card["quality"], f"{label}.quality", maximum=1, kind="integrity")
        if quality not in QUALITIES:
            raise MemoCardsError("integrity", f"{label}.quality is unsupported")
        fact_status = _string(card["fact_status"], f"{label}.fact_status", maximum=20, kind="integrity")
        if fact_status not in FACT_STATUSES:
            raise MemoCardsError("integrity", f"{label}.fact_status is unsupported")
        lifecycle = _string(card["lifecycle"], f"{label}.lifecycle", maximum=20, kind="integrity")
        if lifecycle not in LIFECYCLES:
            raise MemoCardsError("integrity", f"{label}.lifecycle is unsupported")
        template_id = _string(card["template_id"], f"{label}.template_id", maximum=80, kind="integrity")
        if template_id not in templates:
            raise MemoCardsError("integrity", f"{label}.template_id is not registered")
        template = templates[template_id]
        if (layer == "oral") != (template.card_kind == "oral"):
            raise MemoCardsError("integrity", f"{label} oral layer and template must agree")
        if (layer == "oral") != (identity["assessment"] == "oral"):
            raise MemoCardsError("integrity", f"{label} oral layer and assessment must agree")
        if template.card_kind == "cloze" and layer != "atomic":
            raise MemoCardsError("integrity", f"{label} cloze cards must be atomic")
        fields = _object(card["fields"], f"{label}.fields")
        expected_fields = [name for name, _field_type in template.fields]
        if set(fields) != set(expected_fields):
            raise MemoCardsError("integrity", f"{label}.fields do not exactly match template {template_id}")
        rendered_fields = {
            name: _render_field(
                fields[name],
                field_type,
                f"{label}.fields.{name}",
                standalone_content=_template_field_is_standalone(template, name),
            )
            for name, field_type in template.fields
        }
        references = card["source_ids"]
        if not isinstance(references, list) or not references:
            raise MemoCardsError("integrity", f"{label}.source_ids must be non-empty")
        normalized_references = [_id(item, f"{label}.source_ids[{item_index}]", kind="integrity") for item_index, item in enumerate(references)]
        if len(normalized_references) != len(set(normalized_references)) or not set(normalized_references) <= set(source_ids):
            raise MemoCardsError("integrity", f"{label}.source_ids are duplicated or unknown")
        depends = card["depends_on"]
        if not isinstance(depends, list):
            raise MemoCardsError("integrity", f"{label}.depends_on must be an array")
        normalized_depends = [_id(item, f"{label}.depends_on[{item_index}]", kind="integrity") for item_index, item in enumerate(depends)]
        if len(normalized_depends) != len(set(normalized_depends)):
            raise MemoCardsError("integrity", f"{label}.depends_on repeats a child")
        if layer == "oral" and not 2 <= len(normalized_depends) <= 5:
            raise MemoCardsError("integrity", f"{label} oral cards must depend on 2-5 child cards")
        if layer == "atomic" and normalized_depends:
            raise MemoCardsError(
                "integrity", f"{label} only mechanism and oral cards can declare depends_on"
            )
        normalized: dict[str, Any] = {
            "key": key,
            "rank": rank,
            "identity": identity,
            "logical_id": logical_id,
            "layer": layer,
            "quality": quality,
            "fact_status": fact_status,
            "lifecycle": lifecycle,
            "priority": priority,
            "template_id": template_id,
            "template_version": template.version,
            "rendered_fields": rendered_fields,
            "source_ids": sorted(normalized_references),
            "content_summary": _plain_text(card["content_summary"], f"{label}.content_summary", maximum=500),
            "depends_on_keys": normalized_depends,
            "successor_to": None,
            "misconception_of": None,
            "review_resolution": None,
        }
        for optional_id in ("successor_to", "misconception_of"):
            if optional_id in card:
                reference = _plain_text(card[optional_id], f"{label}.{optional_id}", maximum=27)
                if not LOGICAL_ID_RE.fullmatch(reference):
                    raise MemoCardsError("integrity", f"{label}.{optional_id} is not a logical card ID")
                normalized[optional_id] = reference
        if "review_resolution" in card:
            resolution = _object(card["review_resolution"], f"{label}.review_resolution")
            _strict_keys(
                resolution,
                label=f"{label}.review_resolution",
                required={"summary"},
                kind="integrity",
            )
            normalized["review_resolution"] = {
                "summary": _plain_text(
                    resolution["summary"],
                    f"{label}.review_resolution.summary",
                    maximum=500,
                )
            }
        cards.append(normalized)
    keys = [card["key"] for card in cards]
    ranks = [card["rank"] for card in cards]
    if len(keys) != len(set(keys)):
        raise MemoCardsError("integrity", "request.cards repeats a key")
    if len(ranks) != len(set(ranks)):
        raise MemoCardsError("integrity", "request.cards repeats a rank")
    by_key = {card["key"]: card for card in cards}
    for card in cards:
        missing = sorted(set(card["depends_on_keys"]) - set(by_key))
        if missing:
            raise MemoCardsError("integrity", f"card {card['key']} depends on unknown keys: {', '.join(missing)}")
        if card["key"] in card["depends_on_keys"]:
            raise MemoCardsError("integrity", f"card {card['key']} cannot depend on itself")
        for dependency_key in card["depends_on_keys"]:
            if by_key[dependency_key]["layer"] not in DEPENDENCY_CHILD_LAYERS:
                raise MemoCardsError(
                    "integrity",
                    f"card {card['key']} depends on a child with an unsupported layer",
                )

    dependency_state: dict[str, int] = {}

    def visit_dependency(key: str, trail: tuple[str, ...]) -> None:
        state = dependency_state.get(key, 0)
        if state == 2:
            return
        if state == 1:
            cycle_start = trail.index(key) if key in trail else 0
            cycle = trail[cycle_start:] + (key,)
            raise MemoCardsError(
                "integrity",
                "request.cards contains a dependency cycle",
                details={"keys": list(cycle)},
            )
        dependency_state[key] = 1
        for dependency_key in by_key[key]["depends_on_keys"]:
            visit_dependency(dependency_key, trail + (key,))
        dependency_state[key] = 2

    for key in sorted(by_key):
        visit_dependency(key, ())

    dependency_keys_by_key: dict[str, list[str]] = {}
    for card in cards:
        dependency_keys = card.pop("depends_on_keys")
        dependency_keys_by_key[card["key"]] = dependency_keys
        card["depends_on"] = sorted(
            by_key[key]["logical_id"] for key in dependency_keys
        )
        if len(card["depends_on"]) != len(set(card["depends_on"])):
            raise MemoCardsError(
                "integrity", f"card {card['key']} repeats one logical child through aliases"
            )
        if card["logical_id"] in card["depends_on"]:
            raise MemoCardsError(
                "integrity", f"card {card['key']} cannot depend on its own logical identity"
            )
        card["dependency_content_sha256"] = {}

    finalized_hashes: dict[str, str] = {}

    def finalize_content_hash(key: str) -> str:
        if key in finalized_hashes:
            return finalized_hashes[key]
        card = by_key[key]
        dependency_hashes = {
            by_key[dependency_key]["logical_id"]: finalize_content_hash(dependency_key)
            for dependency_key in dependency_keys_by_key[key]
        }
        card["dependency_content_sha256"] = dict(sorted(dependency_hashes.items()))
        content_basis = {
            "template_id": card["template_id"],
            "template_version": card["template_version"],
            "fields": card["rendered_fields"],
            "depends_on": card["depends_on"],
            "dependency_content_sha256": card["dependency_content_sha256"],
            "successor_to": card["successor_to"],
            "misconception_of": card["misconception_of"],
        }
        card["content_sha256"] = _digest_value(content_basis)
        finalized_hashes[key] = card["content_sha256"]
        return card["content_sha256"]

    for key in sorted(by_key):
        finalize_content_hash(key)
    return {
        "schema": REQUEST_SCHEMA,
        "output_collection": output_id,
        "target": target,
        "selection": selection,
        "sources": sorted(sources, key=lambda item: item["id"]),
        "cards": cards,
    }


def _verify_sources(
    root: Path,
    sources: Sequence[Mapping[str, str]],
    tracked_files: set[str],
) -> tuple[SourcePrecondition, ...]:
    preconditions: list[SourcePrecondition] = []
    for source in sources:
        if source["path"] not in tracked_files:
            raise MemoCardsError(
                "safety",
                "source is not in the materialized tracked-file allowlist",
                details={"path": source["path"]},
            )
        path = _resolve_under(root, source["path"], label=f"source {source['id']}", must_exist=True)
        if not path.is_file() or _is_link_or_junction(path):
            raise MemoCardsError("safety", "source must be a regular non-link file", details={"path": source["path"]})
        try:
            content = path.read_bytes()
            content.decode("utf-8")
        except UnicodeError as exc:
            raise MemoCardsError(
                "integrity",
                "source must be valid UTF-8 text",
                details={"path": source["path"]},
            ) from exc
        except OSError as exc:
            raise MemoCardsError(
                "integrity",
                "cannot read source",
                details={"path": source["path"]},
            ) from exc
        actual = _sha256_bytes(content)
        if actual != source["sha256"]:
            raise MemoCardsError(
                "conflict",
                "source changed after the request was prepared",
                details={"path": source["path"], "expected": source["sha256"], "actual": actual},
            )
        preconditions.append(SourcePrecondition(source["path"], path, actual))
    return tuple(preconditions)


def _check_source_preconditions(
    preconditions: Sequence[SourcePrecondition],
) -> None:
    for source in preconditions:
        if (
            not source.path.is_file()
            or _is_link_or_junction(source.path)
        ):
            raise MemoCardsError(
                "conflict",
                "source changed during publication",
                details={"path": source.relative_path, "expected": source.sha256, "actual": None},
            )
        try:
            actual = _sha256_file(source.path)
        except OSError as exc:
            raise MemoCardsError(
                "conflict",
                "source changed during publication",
                details={"path": source.relative_path, "expected": source.sha256, "actual": None},
            ) from exc
        if actual != source.sha256:
            raise MemoCardsError(
                "conflict",
                "source changed during publication",
                details={"path": source.relative_path, "expected": source.sha256, "actual": actual},
            )


def _artifact_text(manifest: Mapping[str, Any], body: str) -> str:
    header = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
    return f"---\n{header}\n---\n{body}"


def _validate_manifest(
    value: Any, body: str, path: str
) -> tuple[dict[str, Any], bool, bool]:
    manifest = _object(value, f"manifest {path}")
    schema = manifest.get("schema")
    if schema not in ARTIFACT_SCHEMAS:
        raise MemoCardsError("integrity", f"managed manifest {path} has an unsupported schema")
    required = {
        "schema",
        "adapter",
        "template_registry_version",
        "template_registry_sha256",
        "target_collection",
        "sources",
        "source_fingerprint",
        "candidate_sha256",
        "cards",
        "managed_body_sha256",
        "manifest_payload_sha256",
    }
    if schema == ARTIFACT_SCHEMA:
        required |= {"sidecars", "artifact_set_sha256"}
    _strict_keys(
        manifest,
        label=f"manifest {path}",
        required=required,
        kind="integrity",
    )
    _digest(manifest["template_registry_sha256"], f"manifest {path}.template_registry_sha256", kind="integrity")
    _digest(manifest["source_fingerprint"], f"manifest {path}.source_fingerprint", kind="integrity")
    _digest(manifest["candidate_sha256"], f"manifest {path}.candidate_sha256", kind="integrity")
    body_digest = _digest(manifest["managed_body_sha256"], f"manifest {path}.managed_body_sha256", kind="integrity")
    payload_digest = _digest(
        manifest["manifest_payload_sha256"],
        f"manifest {path}.manifest_payload_sha256",
        kind="integrity",
    )
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_payload_sha256"
    }
    header_drifted = _digest_value(payload) != payload_digest
    adapter = _object(manifest["adapter"], f"manifest {path}.adapter")
    _strict_keys(
        adapter,
        label=f"manifest {path}.adapter",
        required={"id", "profile", "client_version"},
        kind="integrity",
    )
    if adapter["id"] != "markji":
        raise MemoCardsError("integrity", f"managed manifest {path} has a foreign adapter")
    _id(adapter["profile"], f"manifest {path}.adapter.profile", kind="integrity")
    if _version_tuple(adapter["client_version"], f"manifest {path}.adapter.client_version") < MINIMUM_MARKJI_VERSION:
        raise MemoCardsError("integrity", f"managed manifest {path} has an unsupported client version")
    template_registry_version = _string(
        manifest["template_registry_version"],
        f"manifest {path}.template_registry_version",
        maximum=32,
        kind="integrity",
    )
    if not re.fullmatch(r"\d+\.\d+\.\d+", template_registry_version):
        raise MemoCardsError("integrity", f"manifest {path} has an invalid registry version")
    _id(manifest["target_collection"], f"manifest {path}.target_collection", kind="integrity")
    sources = manifest["sources"]
    if not isinstance(sources, list):
        raise MemoCardsError("integrity", f"manifest {path}.sources must be an array")
    normalized_sources: list[dict[str, str]] = []
    for index, raw in enumerate(sources):
        source = _object(raw, f"manifest {path}.sources[{index}]")
        _strict_keys(
            source,
            label=f"manifest {path}.sources[{index}]",
            required={"id", "collection", "path", "sha256", "summary"},
            kind="integrity",
        )
        normalized_source = {
            "id": _id(source["id"], f"manifest {path}.sources[{index}].id", kind="integrity"),
            "collection": _id(
                source["collection"],
                f"manifest {path}.sources[{index}].collection",
                kind="integrity",
            ),
            "path": _safe_relative(source["path"], f"manifest {path}.sources[{index}].path"),
            "sha256": _digest(
                source["sha256"],
                f"manifest {path}.sources[{index}].sha256",
                kind="integrity",
            ),
            "summary": _plain_text(
                source["summary"],
                f"manifest {path}.sources[{index}].summary",
                maximum=500,
            ),
        }
        normalized_sources.append(normalized_source)
    if len({source["id"] for source in normalized_sources}) != len(normalized_sources):
        raise MemoCardsError("integrity", f"manifest {path} repeats a source ID")
    if normalized_sources != sources:
        raise MemoCardsError("integrity", f"manifest {path} sources are not canonical")
    if _digest_value(normalized_sources) != manifest["source_fingerprint"]:
        raise MemoCardsError("integrity", f"manifest {path} source fingerprint is invalid")
    cards = manifest["cards"]
    if not isinstance(cards, list):
        raise MemoCardsError("integrity", f"manifest {path}.cards must be an array")
    card_ids: list[str] = []
    for index, raw in enumerate(cards):
        card = _object(raw, f"manifest {path}.cards[{index}]")
        _strict_keys(
            card,
            label=f"manifest {path}.cards[{index}]",
            required={
                "logical_id",
                "identity",
                "layer",
                "template_id",
                "template_version",
                "quality",
                "fact_status",
                "lifecycle",
                "priority",
                "source_ids",
                "content_summary",
                "content_sha256",
                "depends_on",
                "dependency_content_sha256",
                "successor_to",
                "misconception_of",
            },
            optional={"review_reason", "review_resolution"},
            kind="integrity",
        )
        logical_id = _plain_text(card["logical_id"], f"manifest {path} logical_id", maximum=27)
        if not LOGICAL_ID_RE.fullmatch(logical_id):
            raise MemoCardsError("integrity", f"manifest {path} contains an invalid logical ID")
        identity = _object(card["identity"], f"manifest {path}.cards[{index}].identity", kind="integrity")
        _strict_keys(
            identity,
            label=f"manifest {path}.cards[{index}].identity",
            required={"domain", "recall_target", "assessment", "fact_scope"},
            kind="integrity",
        )
        normalized_identity, expected_logical_id = _logical_identity(
            identity, f"manifest {path}.cards[{index}].identity"
        )
        if normalized_identity != identity or expected_logical_id != logical_id:
            raise MemoCardsError(
                "integrity", f"manifest {path} card identity does not match its logical ID"
            )
        layer = _string(card["layer"], f"manifest {path} card layer", maximum=20, kind="integrity")
        quality = _string(card["quality"], f"manifest {path} card quality", maximum=1, kind="integrity")
        fact_status = _string(
            card["fact_status"], f"manifest {path} card fact_status", maximum=20, kind="integrity"
        )
        lifecycle = _string(
            card["lifecycle"], f"manifest {path} card lifecycle", maximum=20, kind="integrity"
        )
        if layer not in LAYERS or quality not in QUALITIES or fact_status not in FACT_STATUSES or lifecycle not in LIFECYCLES:
            raise MemoCardsError("integrity", f"manifest {path} card contains an unsupported enum")
        if (layer == "oral") != (identity["assessment"] == "oral"):
            raise MemoCardsError("integrity", f"manifest {path} oral layer and assessment disagree")
        review_reason = card.get("review_reason")
        if review_reason is not None and review_reason != DEPENDENCY_REVIEW_REASON:
            raise MemoCardsError("integrity", f"manifest {path} card review reason is invalid")
        review_resolution = card.get("review_resolution")
        if review_resolution is not None:
            resolution = _object(
                review_resolution,
                f"manifest {path} card review_resolution",
                kind="integrity",
            )
            _strict_keys(
                resolution,
                label=f"manifest {path} card review_resolution",
                required={"summary"},
                kind="integrity",
            )
            if resolution != {
                "summary": _plain_text(
                    resolution["summary"],
                    f"manifest {path} card review_resolution.summary",
                    maximum=500,
                )
            }:
                raise MemoCardsError(
                    "integrity", f"manifest {path} card review resolution is not canonical"
                )
        if review_reason is not None and lifecycle != "review":
            raise MemoCardsError(
                "integrity", f"manifest {path} review reason requires review lifecycle"
            )
        if review_resolution is not None and lifecycle not in {"active", "archived"}:
            raise MemoCardsError(
                "integrity", f"manifest {path} review resolution requires resolved lifecycle"
            )
        if review_reason is not None and review_resolution is not None:
            raise MemoCardsError(
                "integrity", f"manifest {path} card cannot be pending and resolved together"
            )
        priority = card["priority"]
        if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 5:
            raise MemoCardsError("integrity", f"manifest {path} card priority is invalid")
        template_id = _string(
            card["template_id"], f"manifest {path} card template_id", maximum=80, kind="integrity"
        )
        if not TEMPLATE_ID_RE.fullmatch(template_id):
            raise MemoCardsError("integrity", f"manifest {path} card template ID is invalid")
        template_version = _string(
            card["template_version"],
            f"manifest {path} card template_version",
            maximum=32,
            kind="integrity",
        )
        if not re.fullmatch(r"\d+\.\d+\.\d+", template_version):
            raise MemoCardsError("integrity", f"manifest {path} card template version is invalid")
        _digest(card["content_sha256"], f"manifest {path} card content_sha256", kind="integrity")
        _plain_text(card["content_summary"], f"manifest {path} card content_summary", maximum=500)
        source_ids = card["source_ids"]
        if not isinstance(source_ids, list) or not source_ids:
            raise MemoCardsError("integrity", f"manifest {path} card source_ids must be non-empty")
        normalized_source_ids = [
            _id(item, f"manifest {path} card source_ids[{item_index}]", kind="integrity")
            for item_index, item in enumerate(source_ids)
        ]
        known_source_ids = {source["id"] for source in normalized_sources}
        if (
            normalized_source_ids != sorted(set(normalized_source_ids))
            or not set(normalized_source_ids) <= known_source_ids
        ):
            raise MemoCardsError("integrity", f"manifest {path} card source_ids are invalid")
        depends_on = card["depends_on"]
        if not isinstance(depends_on, list):
            raise MemoCardsError("integrity", f"manifest {path} card depends_on must be an array")
        normalized_depends = [
            _string(item, f"manifest {path} card depends_on[{item_index}]", maximum=27, kind="integrity")
            for item_index, item in enumerate(depends_on)
        ]
        if any(not LOGICAL_ID_RE.fullmatch(item) for item in normalized_depends) or normalized_depends != sorted(set(normalized_depends)):
            raise MemoCardsError("integrity", f"manifest {path} card dependencies are invalid")
        if logical_id in normalized_depends:
            raise MemoCardsError("integrity", f"manifest {path} card depends on itself")
        dependency_hashes = _object(
            card["dependency_content_sha256"],
            f"manifest {path} card dependency_content_sha256",
            kind="integrity",
        )
        normalized_dependency_hashes = {
            dependency_id: _digest(
                digest,
                f"manifest {path} card dependency_content_sha256.{dependency_id}",
                kind="integrity",
            )
            for dependency_id, digest in sorted(dependency_hashes.items())
            if isinstance(dependency_id, str) and LOGICAL_ID_RE.fullmatch(dependency_id)
        }
        if normalized_dependency_hashes != dependency_hashes:
            raise MemoCardsError("integrity", f"manifest {path} card dependency hashes are invalid")
        if layer == "oral":
            if not 2 <= len(normalized_depends) <= 5 or set(normalized_dependency_hashes) != set(normalized_depends):
                raise MemoCardsError("integrity", f"manifest {path} oral card dependencies are incomplete")
        elif layer == "mechanism":
            if set(normalized_dependency_hashes) != set(normalized_depends):
                raise MemoCardsError(
                    "integrity", f"manifest {path} mechanism card dependencies are incomplete"
                )
        elif normalized_depends or normalized_dependency_hashes:
            raise MemoCardsError("integrity", f"manifest {path} atomic card declares dependencies")
        for relation in ("successor_to", "misconception_of"):
            relation_value = card[relation]
            if relation_value is not None and (
                not isinstance(relation_value, str) or not LOGICAL_ID_RE.fullmatch(relation_value)
            ):
                raise MemoCardsError("integrity", f"manifest {path} card {relation} is invalid")
        card_ids.append(logical_id)
    if len(card_ids) != len(set(card_ids)):
        raise MemoCardsError("integrity", f"manifest {path} repeats a logical card ID")
    cards_by_id = {card["logical_id"]: card for card in cards}
    for card in cards:
        for dependency_id in card["depends_on"]:
            child = cards_by_id.get(dependency_id)
            if child is not None and child["layer"] not in DEPENDENCY_CHILD_LAYERS:
                raise MemoCardsError(
                    "integrity",
                    f"manifest {path} dependency {dependency_id} has an unsupported child layer",
                )
    dependency_state: dict[str, int] = {}

    def visit_manifest_dependency(logical_id: str) -> None:
        state = dependency_state.get(logical_id, 0)
        if state == 2:
            return
        if state == 1:
            raise MemoCardsError("integrity", f"manifest {path} contains a dependency cycle")
        dependency_state[logical_id] = 1
        for dependency_id in cards_by_id[logical_id]["depends_on"]:
            if dependency_id in cards_by_id:
                visit_manifest_dependency(dependency_id)
        dependency_state[logical_id] = 2

    for logical_id in sorted(cards_by_id):
        visit_manifest_dependency(logical_id)
    if schema == ARTIFACT_SCHEMA:
        sidecars = manifest["sidecars"]
        if not isinstance(sidecars, list):
            raise MemoCardsError("integrity", f"manifest {path}.sidecars must be an array")
        normalized_sidecars: list[dict[str, Any]] = []
        exported_ids: list[str] = []
        template_ids: list[str] = []
        for index, raw in enumerate(sidecars):
            label = f"manifest {path}.sidecars[{index}]"
            sidecar = _object(raw, label, kind="integrity")
            _strict_keys(
                sidecar,
                label=label,
                required={
                    "kind",
                    "path",
                    "sha256",
                    "byte_size",
                    "table_sha256",
                    "template_id",
                    "template_version",
                    "sheet_name",
                    "columns",
                    "row_count",
                    "rows",
                },
                kind="integrity",
            )
            template_id = _string(
                sidecar["template_id"], f"{label}.template_id", maximum=80, kind="integrity"
            )
            if not TEMPLATE_ID_RE.fullmatch(template_id):
                raise MemoCardsError("integrity", f"{label}.template_id is invalid")
            template_version = _string(
                sidecar["template_version"],
                f"{label}.template_version",
                maximum=32,
                kind="integrity",
            )
            if not re.fullmatch(r"\d+\.\d+\.\d+", template_version):
                raise MemoCardsError("integrity", f"{label}.template_version is invalid")
            relative = _safe_relative(sidecar["path"], f"{label}.path")
            if relative != _xlsx_relative_path(path, template_id):
                raise MemoCardsError("integrity", f"{label}.path is not derived from its Markdown target")
            byte_size = sidecar["byte_size"]
            row_count = sidecar["row_count"]
            if (
                not isinstance(byte_size, int)
                or isinstance(byte_size, bool)
                or not 1 <= byte_size <= XLSX_MAX_BYTES
                or not isinstance(row_count, int)
                or isinstance(row_count, bool)
                or row_count < 1
            ):
                raise MemoCardsError("integrity", f"{label} has invalid size or row count")
            columns = sidecar["columns"]
            if not isinstance(columns, list) or not columns:
                raise MemoCardsError("integrity", f"{label}.columns must be a non-empty array")
            normalized_columns = [
                _plain_text(column, f"{label}.columns[{column_index}]", maximum=100)
                for column_index, column in enumerate(columns)
            ]
            if normalized_columns != columns or len(set(columns)) != len(columns):
                raise MemoCardsError("integrity", f"{label}.columns are not canonical")
            raw_rows = sidecar["rows"]
            if not isinstance(raw_rows, list) or len(raw_rows) != row_count:
                raise MemoCardsError("integrity", f"{label}.rows do not match row_count")
            normalized_rows: list[dict[str, str]] = []
            for row_index, raw_row in enumerate(raw_rows):
                row = _object(raw_row, f"{label}.rows[{row_index}]", kind="integrity")
                _strict_keys(
                    row,
                    label=f"{label}.rows[{row_index}]",
                    required={"logical_id", "content_sha256", "row_sha256"},
                    kind="integrity",
                )
                logical_id = _plain_text(
                    row["logical_id"], f"{label}.rows[{row_index}].logical_id", maximum=27
                )
                if not LOGICAL_ID_RE.fullmatch(logical_id):
                    raise MemoCardsError("integrity", f"{label} contains an invalid logical ID")
                card = cards_by_id.get(logical_id)
                if (
                    card is None
                    or card["lifecycle"] != "active"
                    or card["template_id"] != template_id
                    or card["template_version"] != template_version
                    or card["content_sha256"] != row["content_sha256"]
                ):
                    raise MemoCardsError("integrity", f"{label} row does not match its active card")
                normalized_rows.append(
                    {
                        "logical_id": logical_id,
                        "content_sha256": _digest(
                            row["content_sha256"],
                            f"{label}.rows[{row_index}].content_sha256",
                            kind="integrity",
                        ),
                        "row_sha256": _digest(
                            row["row_sha256"],
                            f"{label}.rows[{row_index}].row_sha256",
                            kind="integrity",
                        ),
                    }
                )
                exported_ids.append(logical_id)
            normalized_sidecars.append(
                {
                    "kind": _string(sidecar["kind"], f"{label}.kind", maximum=50, kind="integrity"),
                    "path": relative,
                    "sha256": _digest(sidecar["sha256"], f"{label}.sha256", kind="integrity"),
                    "byte_size": byte_size,
                    "table_sha256": _digest(
                        sidecar["table_sha256"], f"{label}.table_sha256", kind="integrity"
                    ),
                    "template_id": template_id,
                    "template_version": template_version,
                    "sheet_name": _string(
                        sidecar["sheet_name"], f"{label}.sheet_name", maximum=31, kind="integrity"
                    ),
                    "columns": normalized_columns,
                    "row_count": row_count,
                    "rows": normalized_rows,
                }
            )
            if sidecar["kind"] != "markji-import-xlsx" or sidecar["sheet_name"] != XLSX_SHEET_NAME:
                raise MemoCardsError("integrity", f"{label} has an unsupported workbook contract")
            template_ids.append(template_id)
        expected_exported = [
            card["logical_id"]
            for template_id in template_ids
            for card in cards
            if card["lifecycle"] == "active" and card["template_id"] == template_id
        ]
        if (
            normalized_sidecars != sidecars
            or len(template_ids) != len(set(template_ids))
            or exported_ids != expected_exported
        ):
            raise MemoCardsError("integrity", f"manifest {path} sidecars are not canonical")
        artifact_set_basis = {
            "managed_body_sha256": manifest["managed_body_sha256"],
            "sidecars": sidecars,
        }
        artifact_set_digest = _digest(
            manifest["artifact_set_sha256"],
            f"manifest {path}.artifact_set_sha256",
            kind="integrity",
        )
        if _digest_value(artifact_set_basis) != artifact_set_digest:
            raise MemoCardsError("integrity", f"manifest {path} artifact-set digest is invalid")
    return manifest, _sha256_text(body) != body_digest, header_drifted


def _parse_artifact(text: str, path: str, *, file_sha256: str | None = None) -> Artifact | None:
    match = re.match(r"\A---\r?\n(?P<header>.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group("header"))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("schema") not in ARTIFACT_SCHEMAS:
        return None
    body = text[match.end() :]
    manifest, body_drifted, header_drifted = _validate_manifest(value, body, path)
    return Artifact(
        path,
        text,
        manifest,
        body,
        file_sha256 or _sha256_text(text),
        body_drifted,
        header_drifted,
    )


def _inspect_artifact_sidecars(
    root: Path, artifact: Artifact
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    if artifact.manifest["schema"] != ARTIFACT_SCHEMA:
        return (), ()
    reports: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for sidecar in artifact.manifest["sidecars"]:
        relative = sidecar["path"]
        path = _resolve_under(root, relative, label="managed XLSX sidecar", must_exist=False)
        report: dict[str, Any] = {
            "path": relative,
            "template_id": sidecar["template_id"],
            "expected_sha256": sidecar["sha256"],
            "actual_sha256": None,
            "row_count": sidecar["row_count"],
            "status": "missing",
        }
        if not path.exists():
            reports.append(report)
            issues.append(dict(report))
            continue
        if not path.is_file() or _is_link_or_junction(path):
            report["status"] = "unsafe-file-type"
            reports.append(report)
            issues.append(dict(report))
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            report["status"] = "unreadable"
            report["error"] = str(exc)
            reports.append(report)
            issues.append(dict(report))
            continue
        actual_sha256 = _sha256_bytes(content)
        report["actual_sha256"] = actual_sha256
        report["actual_byte_size"] = len(content)
        if actual_sha256 != sidecar["sha256"]:
            report["status"] = "sha256-mismatch"
            reports.append(report)
            issues.append(dict(report))
            continue
        if len(content) != sidecar["byte_size"]:
            report["status"] = "byte-size-mismatch"
            reports.append(report)
            issues.append(dict(report))
            continue
        try:
            headers, rows = _parse_xlsx(content, f"managed XLSX sidecar {relative}")
        except MemoCardsError as exc:
            report["status"] = "invalid-xlsx"
            report["error"] = exc.message
            reports.append(report)
            issues.append(dict(report))
            continue
        row_sha256 = [_digest_value(list(row)) for row in rows]
        table_sha256 = _digest_value(
            {"columns": list(headers), "rows": [list(row) for row in rows]}
        )
        expected_rows = [row["row_sha256"] for row in sidecar["rows"]]
        if (
            list(headers) != sidecar["columns"]
            or len(rows) != sidecar["row_count"]
            or row_sha256 != expected_rows
            or table_sha256 != sidecar["table_sha256"]
        ):
            report["status"] = "table-mismatch"
            reports.append(report)
            issues.append(dict(report))
            continue
        report["status"] = "ok"
        reports.append(report)
    return tuple(reports), tuple(issues)


def _inventory_files(
    root: Path, patterns: Sequence[str], tracked_files: set[str]
) -> list[Path]:
    relatives = {
        relative for relative in tracked_files if _matches(relative, patterns)
    }
    # A newly published managed target is intentionally usable before the next
    # Git add/materialization cycle.  Discover output candidates inside the
    # already-authorized inventory roots so sequential publishes cannot bypass
    # cross-file logical-ID uniqueness during that window.
    for pattern in patterns:
        for candidate in root.glob(pattern):
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError as exc:  # pragma: no cover - Path.glob is rooted
                raise MemoCardsError(
                    "safety", "inventory candidate escapes the repository"
                ) from exc
            relatives.add(relative)
    return [
        root.joinpath(*PurePosixPath(relative).parts)
        for relative in sorted(relatives)
    ]


def _scan_inventory(root: Path, runtime: Mapping[str, Any]) -> Inventory:
    context = runtime["context"]
    tracked_files = set(runtime["allowlist"]["tracked_files"])
    patterns = sorted(
        {
            pattern
            for output in context["output_collections"]
            for pattern in output["inventory_patterns"]
        }
    )
    artifacts: list[Artifact] = []
    legacy: list[dict[str, str]] = []
    seen_cards: dict[str, str] = {}
    fingerprint_rows: list[dict[str, Any]] = []
    for path in _inventory_files(root, patterns, tracked_files):
        relative = path.relative_to(root).as_posix()
        is_tracked = relative in tracked_files
        try:
            safe = _resolve_under(
                root, relative, label="inventory path", must_exist=True
            )
        except MemoCardsError:
            if not is_tracked:
                continue
            raise
        if not safe.is_file() or _is_link_or_junction(safe):
            if not is_tracked:
                continue
            raise MemoCardsError("safety", "inventory contains a link or special file", details={"path": relative})
        try:
            raw = safe.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            if not is_tracked:
                continue
            raise MemoCardsError("integrity", "cannot read inventory file", details={"path": relative}) from exc
        file_sha256 = _sha256_bytes(raw)
        try:
            artifact = _parse_artifact(text, relative, file_sha256=file_sha256)
        except MemoCardsError:
            if not is_tracked:
                continue
            raise
        if artifact is None:
            if not is_tracked:
                # Untracked arbitrary Markdown is not inventory.  Only a
                # self-validating managed artifact may bridge the short window
                # before the next materialization.
                continue
            digest = file_sha256
            legacy.append({"path": relative, "sha256": digest})
            fingerprint_rows.append({"path": relative, "sha256": digest, "kind": "legacy"})
            continue
        sidecar_reports, sidecar_issues = _inspect_artifact_sidecars(root, artifact)
        artifact = Artifact(
            artifact.path,
            artifact.text,
            artifact.manifest,
            artifact.body,
            artifact.sha256,
            artifact.body_drifted,
            artifact.header_drifted,
            sidecar_reports,
            sidecar_issues,
        )
        artifacts.append(artifact)
        fingerprint_rows.append(
            {
                "path": relative,
                "sha256": artifact.sha256,
                "body_drifted": artifact.body_drifted,
                "header_drifted": artifact.header_drifted,
                "sidecars": list(artifact.sidecar_reports),
                "kind": "managed",
            }
        )
        if artifact.header_drifted:
            continue
        for card in artifact.manifest["cards"]:
            logical_id = card["logical_id"]
            if logical_id in seen_cards:
                raise MemoCardsError(
                    "integrity",
                    "managed inventory contains the same logical card in multiple files",
                    details={"logical_id": logical_id, "paths": [seen_cards[logical_id], relative]},
                )
            seen_cards[logical_id] = relative
    trusted_cards = {
        card["logical_id"]: card
        for artifact in artifacts
        if not artifact.header_drifted
        for card in artifact.manifest["cards"]
    }
    dependency_state: dict[str, int] = {}

    def visit_inventory_dependency(logical_id: str) -> None:
        state = dependency_state.get(logical_id, 0)
        if state == 2:
            return
        if state == 1:
            raise MemoCardsError("integrity", "managed inventory contains a dependency cycle")
        dependency_state[logical_id] = 1
        card = trusted_cards[logical_id]
        for dependency_id in card["depends_on"]:
            child = trusted_cards.get(dependency_id)
            if child is None:
                continue
            if child["layer"] not in DEPENDENCY_CHILD_LAYERS:
                raise MemoCardsError(
                    "integrity",
                    "managed inventory dependency has an unsupported child layer",
                    details={
                        "logical_id": logical_id,
                        "dependency_id": dependency_id,
                    },
                )
            visit_inventory_dependency(dependency_id)
        dependency_state[logical_id] = 2

    for logical_id in sorted(trusted_cards):
        visit_inventory_dependency(logical_id)
    dependency_drift: list[dict[str, str]] = []
    for artifact in artifacts:
        if artifact.header_drifted:
            continue
        for card in artifact.manifest["cards"]:
            if not card["dependency_content_sha256"]:
                continue
            for dependency_id, expected_digest in card["dependency_content_sha256"].items():
                actual_card = trusted_cards.get(dependency_id)
                actual_digest = actual_card["content_sha256"] if actual_card else "missing"
                if actual_digest != expected_digest:
                    dependency_drift.append(
                        {
                            "path": artifact.path,
                            "logical_id": card["logical_id"],
                            "dependency_id": dependency_id,
                            "expected": expected_digest,
                            "actual": actual_digest,
                        }
                    )
    dependency_drift.sort(
        key=lambda item: (item["path"], item["logical_id"], item["dependency_id"])
    )
    fingerprint_rows.extend(
        {"kind": "dependency-drift", **record} for record in dependency_drift
    )
    return Inventory(
        tuple(artifacts),
        tuple(legacy),
        tuple(dependency_drift),
        _digest_value(fingerprint_rows),
    )


def _dedupe_request_cards(cards: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        grouped.setdefault(card["logical_id"], []).append(card)
    canonical: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    quality_order = {"A": 0, "B": 1, "C": 2}
    for logical_id, group in grouped.items():
        ordered = sorted(group, key=lambda item: (item["rank"], item["key"]))
        statuses = {
            (
                item["fact_status"],
                item["lifecycle"],
                item["content_sha256"],
                _digest_value(item["review_resolution"]),
            )
            for item in ordered
        }
        if len(statuses) != 1:
            blocked.append(
                {
                    "logical_id": logical_id,
                    "keys": [item["key"] for item in ordered],
                    "reasons": ["same-identity-candidate-conflict"],
                }
            )
            continue
        chosen = dict(ordered[0])
        chosen["priority"] = max(item["priority"] for item in ordered)
        chosen["quality"] = min((item["quality"] for item in ordered), key=lambda item: quality_order[item])
        chosen["source_ids"] = sorted({source_id for item in ordered for source_id in item["source_ids"]})
        canonical.append(chosen)
        if len(ordered) > 1:
            duplicates.append(
                {
                    "logical_id": logical_id,
                    "canonical_key": chosen["key"],
                    "suppressed_keys": [item["key"] for item in ordered[1:]],
                    "kind": "request-duplicate",
                }
            )
    return sorted(canonical, key=lambda item: (item["rank"], item["logical_id"])), duplicates, blocked


def _card_summary(card: Mapping[str, Any], *, reasons: Sequence[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": card.get("key"),
        "logical_id": card["logical_id"],
        "quality": card["quality"],
        "lifecycle": card["lifecycle"],
        "template_id": card["template_id"],
        "content_summary": card["content_summary"],
    }
    if card.get("review_reason") is not None:
        result["review_reason"] = card["review_reason"]
    if card.get("review_resolution") is not None:
        result["review_resolution_summary"] = card["review_resolution"]["summary"]
    if reasons:
        result["reasons"] = list(reasons)
    return result


def _lifecycle_allowed(previous: str | None, current: str) -> bool:
    if previous is None:
        return current == "active"
    allowed = {
        "active": {"active", "review"},
        "review": {"review", "active", "archived"},
        "archived": {"archived"},
    }
    return current in allowed.get(previous, set())


def _template_tables(
    cards: Sequence[Mapping[str, Any]], registry: Registry
) -> tuple[TemplateTable, ...]:
    active = [card for card in cards if card["lifecycle"] == "active"]
    tables: list[TemplateTable] = []
    for template in registry.templates:
        group = sorted(
            (card for card in active if card["template_id"] == template.template_id),
            key=lambda card: (card["rank"], card["logical_id"]),
        )
        if not group:
            continue
        headers = tuple(name for name, _field_type in template.fields)
        rows: list[tuple[str, ...]] = []
        logical_ids: list[str] = []
        for card in group:
            row = tuple(card["rendered_fields"][name] for name in headers)
            if len(row) != len(headers):
                raise MemoCardsError(
                    "integrity", f"card {card['logical_id']} rendered the wrong column count"
                )
            rows.append(row)
            logical_ids.append(card["logical_id"])
        tables.append(
            TemplateTable(
                template.template_id,
                template.version,
                template.display_name,
                headers,
                tuple(rows),
                tuple(logical_ids),
            )
        )
    return tuple(tables)


def _xlsx_relative_path(markdown_target: str, template_id: str) -> str:
    target = PurePosixPath(markdown_target)
    if target.suffix != ".md":
        raise MemoCardsError("integrity", "managed card target must end in .md")
    filename = f"{target.stem}-{template_id}.xlsx"
    if len(filename.encode("utf-8")) > 255 or len(filename.encode("utf-16-le")) // 2 > 255:
        raise MemoCardsError("safety", "derived XLSX filename is too long")
    return _safe_relative(
        (target.parent / filename).as_posix(),
        f"derived XLSX path for {template_id}",
    )


def _xlsx_column(index: int) -> str:
    if index < 1 or index > 16_384:
        raise MemoCardsError("integrity", "XLSX column index is outside Excel limits")
    result = ""
    remaining = index
    while remaining:
        remaining, remainder = divmod(remaining - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_cell_text(value: str, label: str) -> str:
    utf16_units = sum(2 if ord(character) > 0xFFFF else 1 for character in value)
    if utf16_units > XLSX_MAX_CELL_CHARACTERS:
        raise MemoCardsError("integrity", f"{label} exceeds the XLSX cell character limit")
    for character in value:
        point = ord(character)
        if not (
            point in {0x09, 0x0A, 0x0D}
            or 0x20 <= point <= 0xD7FF
            or 0xE000 <= point <= 0xFFFD
            or 0x10000 <= point <= 0x10FFFF
        ):
            raise MemoCardsError("integrity", f"{label} contains an XML-illegal character")
    return xml_escape(value)


def _xlsx_xml_documents(
    headers: Sequence[str], rows: Sequence[Sequence[str]]
) -> tuple[bytes, ...]:
    if not headers or len(headers) > 16_384:
        raise MemoCardsError("integrity", "XLSX headers must contain 1..16384 columns")
    if len(rows) + 1 > 1_048_576:
        raise MemoCardsError("integrity", "XLSX row count exceeds Excel limits")
    if len(set(headers)) != len(headers):
        raise MemoCardsError("integrity", "XLSX headers must be unique")
    normalized_rows: list[tuple[str, ...]] = []
    for row_index, raw_row in enumerate(rows, start=2):
        row = tuple(raw_row)
        if len(row) != len(headers):
            raise MemoCardsError("integrity", f"XLSX row {row_index} has the wrong column count")
        if not all(isinstance(cell, str) for cell in row):
            raise MemoCardsError("integrity", f"XLSX row {row_index} contains a non-string cell")
        normalized_rows.append(row)
    all_rows = [tuple(headers), *normalized_rows]
    row_xml: list[str] = []
    for row_index, row in enumerate(all_rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            reference = f"{_xlsx_column(column_index)}{row_index}"
            escaped = _xlsx_cell_text(value, f"XLSX cell {reference}")
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escaped}</t></is></c>"
            )
        row_xml.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")
    last_reference = f"{_xlsx_column(len(headers))}{len(all_rows)}"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>\n'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>\n'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{XLSX_SHEET_NAME}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>\n'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '</Relationships>\n'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last_reference}"/><sheetData>{"".join(row_xml)}</sheetData>'
        '</worksheet>\n'
    )
    return tuple(
        document.encode("utf-8")
        for document in (content_types, root_rels, workbook, workbook_rels, worksheet)
    )


def _render_xlsx(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    documents = _xlsx_xml_documents(headers, rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as archive:
        for name, payload in zip(XLSX_MEMBERS, documents, strict=True):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = 0x20
            info.internal_attr = 0
            info.extra = b""
            info.comment = b""
            archive.writestr(info, payload)
    content = buffer.getvalue()
    if len(content) > XLSX_MAX_BYTES:
        raise MemoCardsError("integrity", "generated XLSX exceeds the managed size limit")
    return content


def _xml_root(payload: bytes, label: str) -> ElementTree.Element:
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise MemoCardsError("integrity", f"{label} contains a forbidden XML declaration")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise MemoCardsError("integrity", f"{label} is malformed XML") from exc


def _parse_xlsx(content: bytes, label: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    if len(content) > XLSX_MAX_BYTES:
        raise MemoCardsError("integrity", f"{label} exceeds the managed XLSX size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            if archive.comment:
                raise MemoCardsError("integrity", f"{label} has a noncanonical ZIP comment")
            infos = archive.infolist()
            names = tuple(info.filename for info in infos)
            if names != XLSX_MEMBERS or len(names) != len(set(names)):
                raise MemoCardsError("integrity", f"{label} has unexpected XLSX package members")
            payloads: dict[str, bytes] = {}
            for info in infos:
                if (
                    info.flag_bits & 0x1
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.file_size > XLSX_MAX_MEMBER_BYTES
                    or info.extra
                    or info.comment
                ):
                    raise MemoCardsError("integrity", f"{label} has unsafe XLSX ZIP metadata")
                payloads[info.filename] = archive.read(info)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise MemoCardsError("integrity", f"{label} is not a readable XLSX package") from exc

    content_types = _xml_root(payloads[XLSX_MEMBERS[0]], f"{label} content types")
    relationships = _xml_root(payloads[XLSX_MEMBERS[1]], f"{label} package relationships")
    workbook = _xml_root(payloads[XLSX_MEMBERS[2]], f"{label} workbook")
    workbook_rels = _xml_root(payloads[XLSX_MEMBERS[3]], f"{label} workbook relationships")
    worksheet = _xml_root(payloads[XLSX_MEMBERS[4]], f"{label} worksheet")
    content_namespace = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    relationship_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    spreadsheet_namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    office_rel_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    overrides = {
        (item.attrib.get("PartName"), item.attrib.get("ContentType"))
        for item in content_types.findall(f"{content_namespace}Override")
    }
    if overrides != {
        (
            "/xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        ),
        (
            "/xl/worksheets/sheet1.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        ),
    }:
        raise MemoCardsError("integrity", f"{label} has unexpected XLSX content types")
    root_relationships = relationships.findall(f"{relationship_namespace}Relationship")
    workbook_relationships = workbook_rels.findall(f"{relationship_namespace}Relationship")
    if len(root_relationships) != 1 or root_relationships[0].attrib != {
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": "xl/workbook.xml",
    }:
        raise MemoCardsError("integrity", f"{label} has unexpected package relationships")
    if len(workbook_relationships) != 1 or workbook_relationships[0].attrib != {
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
        "Target": "worksheets/sheet1.xml",
    }:
        raise MemoCardsError("integrity", f"{label} has unexpected workbook relationships")
    sheets = workbook.findall(f"{spreadsheet_namespace}sheets/{spreadsheet_namespace}sheet")
    if len(sheets) != 1 or sheets[0].attrib != {
        "name": XLSX_SHEET_NAME,
        "sheetId": "1",
        f"{office_rel_namespace}id": "rId1",
    }:
        raise MemoCardsError("integrity", f"{label} must contain one '{XLSX_SHEET_NAME}' worksheet")

    sheet_data = worksheet.find(f"{spreadsheet_namespace}sheetData")
    dimensions = worksheet.findall(f"{spreadsheet_namespace}dimension")
    if sheet_data is None or len(dimensions) != 1:
        raise MemoCardsError("integrity", f"{label} has an invalid worksheet structure")
    parsed_rows: list[tuple[str, ...]] = []
    expected_width: int | None = None
    for row_index, row in enumerate(sheet_data.findall(f"{spreadsheet_namespace}row"), start=1):
        if row.attrib != {"r": str(row_index)}:
            raise MemoCardsError("integrity", f"{label} has nonsequential XLSX rows")
        parsed_cells: list[str] = []
        cells = row.findall(f"{spreadsheet_namespace}c")
        if expected_width is None:
            expected_width = len(cells)
        if not cells or len(cells) != expected_width:
            raise MemoCardsError("integrity", f"{label} has a sparse or ragged XLSX row")
        for column_index, cell in enumerate(cells, start=1):
            expected_reference = f"{_xlsx_column(column_index)}{row_index}"
            if cell.attrib != {"r": expected_reference, "t": "inlineStr"}:
                raise MemoCardsError("integrity", f"{label} contains a non-text XLSX cell")
            children = list(cell)
            if len(children) != 1 or children[0].tag != f"{spreadsheet_namespace}is":
                raise MemoCardsError("integrity", f"{label} contains an invalid inline string")
            text_children = list(children[0])
            if len(text_children) != 1 or text_children[0].tag != f"{spreadsheet_namespace}t":
                raise MemoCardsError("integrity", f"{label} contains rich or malformed text")
            parsed_cells.append(text_children[0].text or "")
        parsed_rows.append(tuple(parsed_cells))
    if not parsed_rows:
        raise MemoCardsError("integrity", f"{label} has no header row")
    headers = parsed_rows[0]
    rows = tuple(parsed_rows[1:])
    expected_dimension = f"A1:{_xlsx_column(len(headers))}{len(parsed_rows)}"
    if dimensions[0].attrib != {"ref": expected_dimension}:
        raise MemoCardsError("integrity", f"{label} has an invalid worksheet dimension")
    rebuilt = _render_xlsx(headers, rows)
    if rebuilt != content:
        raise MemoCardsError("integrity", f"{label} is not in canonical memo-cards XLSX form")
    return headers, rows


def _render_workbooks(
    markdown_target: str, tables: Sequence[TemplateTable]
) -> tuple[XlsxArtifact, ...]:
    result: list[XlsxArtifact] = []
    for table in tables:
        content = _render_xlsx(table.headers, table.rows)
        parsed_headers, parsed_rows = _parse_xlsx(
            content, f"generated XLSX for {table.template_id}"
        )
        if parsed_headers != table.headers or parsed_rows != table.rows:
            raise MemoCardsError("integrity", "generated XLSX failed semantic round-trip")
        row_sha256 = tuple(_digest_value(list(row)) for row in table.rows)
        result.append(
            XlsxArtifact(
                table.template_id,
                _xlsx_relative_path(markdown_target, table.template_id),
                content,
                _sha256_bytes(content),
                len(content),
                _digest_value(
                    {"columns": list(table.headers), "rows": [list(row) for row in table.rows]}
                ),
                row_sha256,
            )
        )
    return tuple(result)


def _render_body(
    tables: Sequence[TemplateTable], workbooks: Sequence[XlsxArtifact], registry: Registry
) -> str:
    templates = registry.by_id
    workbooks_by_template = {workbook.template_id: workbook for workbook in workbooks}
    lines = [
        "# Markji 表格导入卡片",
        "",
        "> Markdown 保留受管元数据与模板定义；卡片数据请使用下列按模板拆分的 XLSX 文件导入。",
        "",
    ]
    for table in tables:
        template = templates[table.template_id]
        workbook = workbooks_by_template[table.template_id]
        filename = PurePosixPath(workbook.relative_path).name
        lines.extend(
            [
                f"## {template.display_name}",
                "",
                f"模板 `{template.template_id}@{template.version}`：",
                "",
                "```text",
                template.body,
                "```",
                "",
                f"导入文件：[{filename}]({filename})（{len(table.rows)} 张卡）",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _manifest_card(card: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "logical_id": card["logical_id"],
        "identity": card["identity"],
        "layer": card["layer"],
        "template_id": card["template_id"],
        "template_version": card["template_version"],
        "quality": card["quality"],
        "fact_status": card["fact_status"],
        "lifecycle": card["lifecycle"],
        "priority": card["priority"],
        "source_ids": card["source_ids"],
        "content_summary": card["content_summary"],
        "content_sha256": card["content_sha256"],
        "depends_on": card["depends_on"],
        "dependency_content_sha256": card["dependency_content_sha256"],
        "successor_to": card["successor_to"],
        "misconception_of": card["misconception_of"],
    }
    if card.get("review_reason") is not None:
        result["review_reason"] = card["review_reason"]
    if card.get("review_resolution") is not None:
        result["review_resolution"] = card["review_resolution"]
    return result


def _manifest_sidecar(
    table: TemplateTable,
    workbook: XlsxArtifact,
    cards_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": "markji-import-xlsx",
        "path": workbook.relative_path,
        "sha256": workbook.sha256,
        "byte_size": workbook.byte_size,
        "table_sha256": workbook.table_sha256,
        "template_id": table.template_id,
        "template_version": table.template_version,
        "sheet_name": XLSX_SHEET_NAME,
        "columns": list(table.headers),
        "row_count": len(table.rows),
        "rows": [
            {
                "logical_id": logical_id,
                "content_sha256": cards_by_id[logical_id]["content_sha256"],
                "row_sha256": row_sha256,
            }
            for logical_id, row_sha256 in zip(
                table.logical_ids, workbook.row_sha256, strict=True
            )
        ],
    }


def _unified_diff(current: str, candidate: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
        )
    )


def _interrupted_transactions(
    root: Path, runtime: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Find journals even when their Markdown commit point is absent."""

    reports: dict[str, dict[str, Any]] = {}

    def scan_error(error: OSError) -> None:
        raise MemoCardsError(
            "integrity",
            "cannot scan memo-cards output roots for interrupted publications",
            details={"path": error.filename},
        ) from error

    for relative_root in runtime["allowlist"]["write_paths"]:
        output_root = _resolve_under(
            root, relative_root, label="memo-cards write path", must_exist=False
        )
        if not output_root.exists():
            continue
        if not output_root.is_dir() or _is_link_or_junction(output_root):
            raise MemoCardsError(
                "safety",
                "memo-cards write path must be a real directory",
                details={"path": relative_root},
            )
        for directory, names, filenames in os.walk(
            output_root, topdown=True, followlinks=False, onerror=scan_error
        ):
            directory_path = Path(directory)
            names[:] = [
                name
                for name in names
                if not _is_link_or_junction(directory_path / name)
            ]
            for filename in filenames:
                if not (
                    filename.startswith(".")
                    and filename.endswith(TRANSACTION_JOURNAL_SUFFIX)
                    and len(filename) > len(TRANSACTION_JOURNAL_SUFFIX) + 1
                ):
                    continue
                journal = directory_path / filename
                relative = journal.relative_to(root).as_posix()
                if journal.is_file() and not _is_link_or_junction(journal):
                    reports[relative] = {
                        "path": relative,
                        "sha256": _sha256_file(journal),
                        "status": "present",
                    }
                else:
                    reports[relative] = {
                        "path": relative,
                        "sha256": None,
                        "status": "unsafe-entry",
                    }
    return tuple(reports[path] for path in sorted(reports))


def _publication_lock_states(
    root: Path, runtime: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    reports: list[dict[str, Any]] = []
    for relative_root in runtime["allowlist"]["write_paths"]:
        output_root = _resolve_under(
            root, relative_root, label="memo-cards write path", must_exist=False
        )
        lock = output_root / PUBLICATION_LOCK_NAME
        if not lock.exists() and not lock.is_symlink():
            continue
        relative = lock.relative_to(root).as_posix()
        if lock.is_file() and not _is_link_or_junction(lock):
            try:
                digest = _sha256_file(lock)
            except OSError:
                digest = None
            reports.append({"path": relative, "sha256": digest, "status": "present"})
        else:
            reports.append(
                {"path": relative, "sha256": None, "status": "unsafe-entry"}
            )
    return tuple(sorted(reports, key=lambda report: report["path"]))


def _prepare_plan(
    root: Path,
    runtime: Mapping[str, Any],
    request_value: Any,
    registry: Registry,
) -> Plan:
    context = runtime["context"]
    tracked_files = set(runtime["allowlist"]["tracked_files"])
    request = _validate_request(request_value, context, registry)
    source_preconditions = _verify_sources(root, request["sources"], tracked_files)
    interrupted_transactions = _interrupted_transactions(root, runtime)
    if interrupted_transactions:
        raise MemoCardsError(
            "conflict",
            "an interrupted memo-cards publication requires recovery",
            details={"transactions": list(interrupted_transactions)},
        )
    inventory = _scan_inventory(root, runtime)
    target_relative = request["target"]
    target_path = _resolve_under(root, target_relative, label="request target", must_exist=False)
    if target_path.exists() and (not target_path.is_file() or _is_link_or_junction(target_path)):
        raise MemoCardsError("safety", "request target must be a regular non-link file")
    current_text = ""
    current_sha: str | None = None
    current_artifact: Artifact | None = None
    current_kind = "absent"
    if target_path.exists():
        try:
            current_bytes = target_path.read_bytes()
            current_text = current_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise MemoCardsError("integrity", "cannot read request target") from exc
        current_sha = _sha256_bytes(current_bytes)
        current_artifact = _parse_artifact(
            current_text, target_relative, file_sha256=current_sha
        )
        if current_artifact is not None:
            sidecar_reports, sidecar_issues = _inspect_artifact_sidecars(
                root, current_artifact
            )
            current_artifact = Artifact(
                current_artifact.path,
                current_artifact.text,
                current_artifact.manifest,
                current_artifact.body,
                current_artifact.sha256,
                current_artifact.body_drifted,
                current_artifact.header_drifted,
                sidecar_reports,
                sidecar_issues,
            )
        current_kind = "managed" if current_artifact else "legacy"

    cards, request_duplicates, blocked = _dedupe_request_cards(request["cards"])
    current_cards = {
        card["logical_id"]: card
        for card in (
            current_artifact.manifest["cards"]
            if current_artifact and not current_artifact.header_drifted
            else []
        )
    }
    inventory_cards: dict[str, tuple[str, dict[str, Any]]] = {}
    for artifact in inventory.artifacts:
        if artifact.header_drifted:
            continue
        for card in artifact.manifest["cards"]:
            inventory_cards[card["logical_id"]] = (artifact.path, card)

    dependency_review_ids: set[str] = set()
    dependency_review_child_ids: set[str] = set()
    review_resolution_ids: set[str] = set()
    normalized_cards: list[dict[str, Any]] = []
    for original in cards:
        card = dict(original)
        card["review_reason"] = None
        previous = current_cards.get(card["logical_id"])
        dependency_changed = (
            card["layer"] in DEPENDENT_LAYERS
            and previous is not None
            and previous.get("dependency_content_sha256")
            != card["dependency_content_sha256"]
        )
        if dependency_changed:
            if card["review_resolution"] is not None:
                raise MemoCardsError(
                    "conflict",
                    "review_resolution cannot resolve new dependency drift in the same preview",
                    details={"logical_id": card["logical_id"]},
                )
            dependency_review_ids.add(card["logical_id"])
            card["review_resolution"] = None
            card["review_reason"] = DEPENDENCY_REVIEW_REASON
            if card["lifecycle"] == "active":
                card["lifecycle"] = "review"
            if card["lifecycle"] == "review":
                dependency_review_child_ids.add(card["logical_id"])
        elif previous is None:
            if card["review_resolution"] is not None:
                raise MemoCardsError(
                    "integrity", "new cards cannot declare review_resolution"
                )
        elif previous["lifecycle"] == "review":
            previous_reason = previous.get("review_reason")
            if card["lifecycle"] == "active":
                if card["review_resolution"] is None:
                    card["lifecycle"] = "review"
                    card["review_reason"] = previous_reason
                    if previous_reason == DEPENDENCY_REVIEW_REASON:
                        dependency_review_child_ids.add(card["logical_id"])
                else:
                    review_resolution_ids.add(card["logical_id"])
            else:
                if card["review_resolution"] is not None:
                    raise MemoCardsError(
                        "integrity",
                        "review_resolution is only valid when restoring review to active",
                        details={"logical_id": card["logical_id"]},
                    )
                if card["lifecycle"] == "review":
                    card["review_reason"] = previous_reason
                    if previous_reason == DEPENDENCY_REVIEW_REASON:
                        dependency_review_child_ids.add(card["logical_id"])
        elif card["review_resolution"] is not None:
            if not (
                card["lifecycle"] == previous["lifecycle"]
                and card["lifecycle"] in {"active", "archived"}
                and card["review_resolution"] == previous.get("review_resolution")
            ):
                raise MemoCardsError(
                    "integrity",
                    "review_resolution does not match an already resolved review",
                    details={"logical_id": card["logical_id"]},
                )
        elif (
            card["lifecycle"] == previous["lifecycle"]
            and card["lifecycle"] in {"active", "archived"}
            and previous.get("review_resolution") is not None
        ):
            card["review_resolution"] = previous["review_resolution"]
        normalized_cards.append(card)
    cards = normalized_cards

    cards_by_id = {card["logical_id"]: card for card in cards}
    base_reasons: dict[str, list[str]] = {}
    for card in cards:
        reasons: list[str] = []
        if card["quality"] == "C":
            reasons.append("quality-C")
        if card["fact_status"] != "verified" and card["lifecycle"] == "active":
            reasons.append(f"fact-status-{card['fact_status']}")
        if card["lifecycle"] in {"candidate", "research"}:
            reasons.append(f"lifecycle-{card['lifecycle']}")
        previous = current_cards.get(card["logical_id"])
        previous_lifecycle = previous["lifecycle"] if previous else None
        if not _lifecycle_allowed(previous_lifecycle, card["lifecycle"]):
            reasons.append(
                f"invalid-lifecycle-{previous_lifecycle or 'new'}-to-{card['lifecycle']}"
            )
        base_reasons[card["logical_id"]] = reasons

    dependency_reasons: dict[str, list[str]] = {}
    for card in cards:
        if not card["depends_on"]:
            continue
        reasons: list[str] = []
        prefix = card["layer"]
        for dependency_id in card["depends_on"]:
            child = cards_by_id.get(dependency_id)
            if child is None:
                reasons.append(f"{prefix}-child-missing-{dependency_id}")
                continue
            if child["layer"] not in DEPENDENCY_CHILD_LAYERS:
                reasons.append(f"{prefix}-child-layer-{dependency_id}")
            child_review_is_part_of_same_dependency_review = (
                card["lifecycle"] == "review"
                and card.get("review_reason") == DEPENDENCY_REVIEW_REASON
                and child["logical_id"] in dependency_review_child_ids
            )
            if (
                child["quality"] not in {"A", "B"}
                or child["fact_status"] != "verified"
                or (
                    child["lifecycle"] != "active"
                    and not child_review_is_part_of_same_dependency_review
                )
                or base_reasons[dependency_id]
            ):
                reasons.append(f"{prefix}-child-ineligible-{dependency_id}")
            if (
                card["dependency_content_sha256"][dependency_id]
                != child["content_sha256"]
            ):
                reasons.append(f"{prefix}-child-content-mismatch-{dependency_id}")
            existing_child = inventory_cards.get(dependency_id)
            if (
                existing_child
                and existing_child[0] != target_relative
                and existing_child[1]["content_sha256"] != child["content_sha256"]
            ):
                reasons.append(f"{prefix}-child-conflict-{dependency_id}")
        dependency_reasons[card["logical_id"]] = sorted(set(reasons))

    included_candidates: list[dict[str, Any]] = []
    cross_duplicates: list[dict[str, Any]] = []
    eligible_new_b: list[dict[str, Any]] = []
    eligible_other: list[dict[str, Any]] = []
    for card in cards:
        reasons = base_reasons[card["logical_id"]] + dependency_reasons.get(
            card["logical_id"], []
        )
        existing = inventory_cards.get(card["logical_id"])
        if existing and existing[0] != target_relative:
            if existing[1]["content_sha256"] == card["content_sha256"]:
                cross_duplicates.append(
                    {
                        "logical_id": card["logical_id"],
                        "canonical_path": existing[0],
                        "kind": "cross-file-duplicate",
                    }
                )
            else:
                blocked.append(
                    {
                        **_card_summary(card),
                        "reasons": ["cross-file-refresh-requires-separate-request"],
                        "canonical_path": existing[0],
                    }
                )
            continue
        if reasons:
            blocked.append(_card_summary(card, reasons=reasons))
            continue
        is_new = (
            card["logical_id"] not in inventory_cards
            and card["logical_id"] not in current_cards
        )
        if card["lifecycle"] == "active" and card["quality"] == "B" and is_new:
            eligible_new_b.append(card)
        else:
            eligible_other.append(card)

    output = next(record for record in context["output_collections"] if record["id"] == request["output_collection"])
    included_candidates.extend(eligible_other)
    if request["selection"] == "complete" or "soft_target" not in output:
        included_candidates.extend(eligible_new_b)
    else:
        maximum = output["soft_target"]["maximum"]
        new_a_count = sum(
            1
            for card in eligible_other
            if card["quality"] == "A"
            and card["lifecycle"] == "active"
            and card["logical_id"] not in inventory_cards
            and card["logical_id"] not in current_cards
        )
        slots = max(0, maximum - new_a_count)
        ordered_b = sorted(eligible_new_b, key=lambda item: (item["rank"], item["logical_id"]))
        included_candidates.extend(ordered_b[:slots])

    eligible_by_id = {
        card["logical_id"]: card for card in eligible_other + eligible_new_b
    }
    selected_by_id = {card["logical_id"]: card for card in included_candidates}
    changed = True
    while changed:
        changed = False
        for card in list(selected_by_id.values()):
            if not card["depends_on"]:
                continue
            for dependency_id in card["depends_on"]:
                if dependency_id in selected_by_id:
                    continue
                existing = inventory_cards.get(dependency_id)
                if (
                    existing
                    and existing[1]["content_sha256"]
                    == card["dependency_content_sha256"][dependency_id]
                ):
                    continue
                child = eligible_by_id.get(dependency_id)
                if child is not None:
                    selected_by_id[dependency_id] = child
                    changed = True
    included_candidates = list(selected_by_id.values())
    selected_ids = set(selected_by_id)
    deferred = [
        _card_summary(card, reasons=["soft-target-attention-load"])
        for card in sorted(eligible_new_b, key=lambda item: (item["rank"], item["logical_id"]))
        if card["logical_id"] not in selected_ids
    ]

    included_candidates = sorted(included_candidates, key=lambda item: (item["rank"], item["logical_id"]))
    used_source_ids = sorted({source_id for card in included_candidates for source_id in card["source_ids"]})
    used_sources = [source for source in request["sources"] if source["id"] in used_source_ids]
    source_fingerprint = _digest_value(used_sources)
    candidate_basis = {
        "target_collection": request["output_collection"],
        "sources": used_sources,
        "cards": [_manifest_card(card) for card in included_candidates],
    }
    candidate_digest = _digest_value(candidate_basis)

    candidate_text: str | None
    candidate_sha: str | None
    tables: tuple[TemplateTable, ...] = ()
    workbooks: tuple[XlsxArtifact, ...] = ()
    sidecar_manifests: list[dict[str, Any]] = []
    artifact_set_sha256: str | None = None
    if not included_candidates and current_kind == "absent":
        candidate_text = None
        candidate_sha = None
    else:
        tables = _template_tables(included_candidates, registry)
        workbooks = _render_workbooks(target_relative, tables)
        candidate_cards_by_id = {
            card["logical_id"]: card for card in included_candidates
        }
        sidecar_manifests = [
            _manifest_sidecar(table, workbook, candidate_cards_by_id)
            for table, workbook in zip(tables, workbooks, strict=True)
        ]
        body = _render_body(tables, workbooks, registry)
        managed_body_sha256 = _sha256_text(body)
        artifact_set_sha256 = _digest_value(
            {
                "managed_body_sha256": managed_body_sha256,
                "sidecars": sidecar_manifests,
            }
        )
        manifest = {
            "schema": ARTIFACT_SCHEMA,
            "adapter": context["adapter"],
            "template_registry_version": registry.version,
            "template_registry_sha256": registry.digest,
            "target_collection": request["output_collection"],
            "sources": used_sources,
            "source_fingerprint": source_fingerprint,
            "candidate_sha256": candidate_digest,
            "cards": [_manifest_card(card) for card in included_candidates],
            "sidecars": sidecar_manifests,
            "managed_body_sha256": managed_body_sha256,
            "artifact_set_sha256": artifact_set_sha256,
        }
        manifest["manifest_payload_sha256"] = _digest_value(manifest)
        candidate_text = _artifact_text(manifest, body)
        candidate_sha = _sha256_text(candidate_text)

    current_owned_sidecars = {
        sidecar["path"]: sidecar
        for sidecar in (
            current_artifact.manifest["sidecars"]
            if current_artifact
            and not current_artifact.header_drifted
            and current_artifact.manifest["schema"] == ARTIFACT_SCHEMA
            else []
        )
    }
    candidate_file_values: dict[str, tuple[bytes, str, str | None]] = {}
    if candidate_text is not None:
        candidate_file_values[target_relative] = (
            candidate_text.encode("utf-8"),
            "markdown",
            None,
        )
    for workbook in workbooks:
        candidate_file_values[workbook.relative_path] = (
            workbook.content,
            "xlsx",
            workbook.template_id,
        )
    all_file_paths = sorted(
        {target_relative, *current_owned_sidecars, *candidate_file_values}
    )
    planned_files: list[PlannedFile] = []
    unmanaged_sidecars: list[str] = []
    for relative in all_file_paths:
        path = _resolve_under(root, relative, label="managed artifact file", must_exist=False)
        present = path.exists() or path.is_symlink()
        if present and (not path.is_file() or _is_link_or_junction(path)):
            raise MemoCardsError(
                "safety",
                "managed artifact file must be a regular non-link file",
                details={"path": relative},
            )
        actual_sha256 = _sha256_file(path) if present else None
        candidate_value = candidate_file_values.get(relative)
        candidate_bytes = candidate_value[0] if candidate_value is not None else None
        candidate_file_sha256 = (
            _sha256_bytes(candidate_bytes) if candidate_bytes is not None else None
        )
        if candidate_bytes is None:
            if relative == target_relative:
                file_operation = "no-op"
                role = "markdown"
                template_id = None
            else:
                file_operation = "remove" if present else "no-op"
                role = "xlsx"
                template_id = current_owned_sidecars[relative]["template_id"]
        else:
            role = candidate_value[1]
            template_id = candidate_value[2]
            if not present:
                file_operation = "create"
            elif actual_sha256 == candidate_file_sha256:
                file_operation = "no-op"
            else:
                file_operation = "update"
        if (
            role == "xlsx"
            and present
            and relative not in current_owned_sidecars
        ):
            unmanaged_sidecars.append(relative)
        planned_files.append(
            PlannedFile(
                relative,
                path,
                role,
                template_id,
                actual_sha256,
                candidate_file_sha256,
                candidate_bytes,
                file_operation,
            )
        )
    if all(file.operation == "no-op" for file in planned_files):
        operation = "no-op"
    elif current_kind == "absent":
        operation = "create"
    else:
        operation = "update"
    if candidate_text is None or candidate_text == current_text:
        diff = ""
    else:
        diff = _unified_diff(
            "" if current_kind == "absent" else current_text,
            candidate_text,
            target_relative,
        )

    old_by_id = current_cards
    new_by_id = {card["logical_id"]: card for card in included_candidates}
    additions = sorted(set(new_by_id) - set(old_by_id))
    removals = sorted(set(old_by_id) - set(new_by_id))
    changes = sorted(
        logical_id
        for logical_id in set(old_by_id) & set(new_by_id)
        if old_by_id[logical_id]["content_sha256"] != new_by_id[logical_id]["content_sha256"]
        or old_by_id[logical_id]["lifecycle"] != new_by_id[logical_id]["lifecycle"]
        or old_by_id[logical_id]["priority"] != new_by_id[logical_id]["priority"]
    )

    prospective_dependency_values: dict[str, str] = {
        logical_id: new_by_id[logical_id]["content_sha256"]
        for logical_id in set(old_by_id) & set(new_by_id)
        if old_by_id[logical_id]["content_sha256"]
        != new_by_id[logical_id]["content_sha256"]
    }
    prospective_dependency_values.update(
        {logical_id: "missing" for logical_id in set(old_by_id) - set(new_by_id)}
    )
    dependent_reviews: list[dict[str, str]] = []
    for artifact in inventory.artifacts:
        if artifact.header_drifted:
            continue
        for card in artifact.manifest["cards"]:
            if not card["dependency_content_sha256"]:
                continue
            if artifact.path == target_relative and card["logical_id"] in new_by_id:
                continue
            for dependency_id, expected_digest in card[
                "dependency_content_sha256"
            ].items():
                prospective = prospective_dependency_values.get(dependency_id)
                if prospective is not None and prospective != expected_digest:
                    dependent_reviews.append(
                        {
                            "path": artifact.path,
                            "logical_id": card["logical_id"],
                            "dependency_id": dependency_id,
                            "expected": expected_digest,
                            "prospective": prospective,
                        }
                    )
    dependent_reviews.sort(
        key=lambda item: (item["path"], item["logical_id"], item["dependency_id"])
    )

    risks: list[str] = []
    interrupted_transaction = (
        interrupted_transactions[0] if interrupted_transactions else None
    )
    if interrupted_transaction is not None:
        risks.append("interrupted-publication")
    if operation != "no-op" and current_kind == "legacy":
        risks.append("legacy-adoption")
    if (
        operation != "no-op"
        and current_artifact
        and current_artifact.manifest["schema"] == ARTIFACT_SCHEMA_V1
    ):
        risks.append("artifact-v1-migration")
    if operation != "no-op" and current_artifact and current_artifact.body_drifted:
        risks.append("manual-drift")
    if operation != "no-op" and current_artifact and current_artifact.header_drifted:
        risks.append("manual-header-drift")
    if operation != "no-op" and current_artifact and current_artifact.sidecar_issues:
        statuses = {issue["status"] for issue in current_artifact.sidecar_issues}
        if "missing" in statuses:
            risks.append("sidecar-missing")
        if statuses - {"missing"}:
            risks.append("sidecar-drift")
    if operation != "no-op" and unmanaged_sidecars:
        risks.append("unmanaged-sidecar-adoption")
    if operation != "no-op" and any(
        file.role == "xlsx" and file.operation == "remove" for file in planned_files
    ):
        risks.append("sidecar-removal")
    if operation != "no-op" and dependency_review_ids:
        risks.append("dependency-drift-review")
    if operation != "no-op" and review_resolution_ids:
        risks.append("review-resolution")
    if operation != "no-op" and dependent_reviews:
        risks.append("dependent-card-review-required")
    if operation != "no-op" and any(
        record["path"] == target_relative for record in inventory.dependency_drift
    ):
        risks.append("existing-dependent-card-drift")
    if operation != "no-op" and current_artifact and not current_artifact.header_drifted:
        if current_artifact.manifest["source_fingerprint"] != source_fingerprint:
            risks.append("source-scope-or-fingerprint-change")
        if current_artifact.manifest["template_registry_sha256"] != registry.digest:
            risks.append("template-registry-upgrade")
        old_templates = {
            (card["logical_id"], card["template_id"], card["template_version"])
            for card in current_artifact.manifest["cards"]
        }
        new_templates = {
            (card["logical_id"], card["template_id"], card["template_version"])
            for card in new_by_id.values()
        }
        shared_ids = set(old_by_id) & set(new_by_id)
        if any(
            old_by_id[logical_id]["template_id"] != new_by_id[logical_id]["template_id"]
            or old_by_id[logical_id]["template_version"] != new_by_id[logical_id]["template_version"]
            for logical_id in shared_ids
        ):
            risks.append("card-template-upgrade")
        _ = old_templates, new_templates
    if operation != "no-op" and removals:
        risks.append("card-removal")
    if operation != "no-op" and any(
        old_by_id[logical_id]["lifecycle"] != new_by_id[logical_id]["lifecycle"]
        for logical_id in set(old_by_id) & set(new_by_id)
    ):
        risks.append("lifecycle-deactivation-or-reactivation")
    risks = sorted(set(risks))
    required_authorization = (
        "confirmed"
        if interrupted_transaction is not None
        else "none"
        if operation == "no-op"
        else "confirmed"
        if risks
        else "request"
    )

    request_digest = _digest_value(request)
    runtime_digest = _digest_value(
        {"context": context, "allowlist": runtime["allowlist"]}
    )
    file_summaries = [
        {
            "path": file.relative_path,
            "role": file.role,
            "template_id": file.template_id,
            "operation": file.operation,
            "ownership": (
                "managed"
                if file.role == "markdown" and current_artifact is not None
                else "managed"
                if file.relative_path in current_owned_sidecars
                else "unmanaged"
                if file.current_sha256 is not None
                else "absent"
            ),
            "current_sha256": file.current_sha256,
            "candidate_sha256": file.candidate_sha256,
            "current_byte_size": (
                file.path.stat().st_size if file.current_sha256 is not None else None
            ),
            "candidate_byte_size": (
                len(file.candidate_bytes) if file.candidate_bytes is not None else None
            ),
        }
        for file in planned_files
    ]
    candidate_sidecars_by_path = {
        sidecar["path"]: sidecar for sidecar in sidecar_manifests
    }
    artifact_diffs: list[dict[str, Any]] = [
        {
            "path": target_relative,
            "kind": "unified",
            "diff": diff,
        }
    ]
    for file in planned_files:
        if file.role != "xlsx" or file.operation == "no-op":
            continue
        before = current_owned_sidecars.get(file.relative_path)
        after = candidate_sidecars_by_path.get(file.relative_path)
        before_rows = {
            row["logical_id"]: row["row_sha256"] for row in before["rows"]
        } if before else {}
        after_rows = {
            row["logical_id"]: row["row_sha256"] for row in after["rows"]
        } if after else {}
        artifact_diffs.append(
            {
                "path": file.relative_path,
                "kind": "xlsx",
                "template_id": file.template_id,
                "before": (
                    {
                        "sha256": file.current_sha256,
                        "row_count": before["row_count"] if before else None,
                    }
                    if file.current_sha256 is not None
                    else None
                ),
                "after": (
                    {
                        "sha256": file.candidate_sha256,
                        "row_count": after["row_count"],
                    }
                    if after is not None
                    else None
                ),
                "rows": {
                    "add": sorted(set(after_rows) - set(before_rows)),
                    "change": sorted(
                        logical_id
                        for logical_id in set(before_rows) & set(after_rows)
                        if before_rows[logical_id] != after_rows[logical_id]
                    ),
                    "remove": sorted(set(before_rows) - set(after_rows)),
                },
            }
        )
    current_artifact_schema = (
        current_artifact.manifest["schema"] if current_artifact else None
    )
    format_transition = (
        {"from": ARTIFACT_SCHEMA_V1, "to": ARTIFACT_SCHEMA}
        if current_artifact_schema == ARTIFACT_SCHEMA_V1 and operation != "no-op"
        else None
    )
    binding = {
        "schema": PREVIEW_SCHEMA,
        "context_sha256": runtime_digest,
        "request_sha256": request_digest,
        "template_registry_sha256": registry.digest,
        "inventory_sha256": inventory.fingerprint,
        "target": target_relative,
        "current_sha256": current_sha,
        "candidate_sha256": candidate_sha,
        "operation": operation,
        "risk_reasons": risks,
        "interrupted_transactions": interrupted_transactions,
        "files": [
            {
                "path": file["path"],
                "operation": file["operation"],
                "current_sha256": file["current_sha256"],
                "candidate_sha256": file["candidate_sha256"],
            }
            for file in file_summaries
        ],
    }
    preview_digest = _digest_value(binding)
    new_active_count = sum(
        1
        for card in included_candidates
        if card["lifecycle"] == "active"
        and card["logical_id"] not in inventory_cards
        and card["logical_id"] not in current_cards
    )
    soft_target_status: dict[str, Any] | None = None
    if "soft_target" in output:
        soft_target_status = {
            **output["soft_target"],
            "new_active_cards": new_active_count,
            "below_minimum": new_active_count < output["soft_target"]["minimum"],
            "above_maximum": new_active_count > output["soft_target"]["maximum"],
            "is_hard_limit": False,
        }
    data = {
        "preview_digest": preview_digest,
        "request_sha256": request_digest,
        "operation": operation,
        "required_authorization": required_authorization,
        "risk_reasons": risks,
        "target": target_relative,
        "target_state": current_kind,
        "current_sha256": current_sha,
        "candidate_sha256": candidate_sha,
        "artifact_set_sha256": artifact_set_sha256,
        "current_artifact_schema": current_artifact_schema,
        "candidate_artifact_schema": ARTIFACT_SCHEMA if candidate_text is not None else None,
        "format_transition": format_transition,
        "template_registry_sha256": registry.digest,
        "context_sha256": runtime_digest,
        "source_fingerprint": source_fingerprint,
        "inventory_fingerprint": inventory.fingerprint,
        "included": [_card_summary(card) for card in included_candidates],
        "deferred": deferred,
        "blocked": blocked,
        "duplicates": request_duplicates + cross_duplicates,
        "legacy_inventory": list(inventory.legacy),
        "dependency_drift": list(inventory.dependency_drift),
        "dependent_reviews": dependent_reviews,
        "soft_target": soft_target_status,
        "changes": {
            "add": additions,
            "change": changes,
            "remove": removals,
            "duplicate_count": len(request_duplicates) + len(cross_duplicates),
            "blocked_count": len(blocked),
        },
        "files": file_summaries,
        "artifact_diffs": artifact_diffs,
        "candidate_sidecars": sidecar_manifests,
        "interrupted_transaction": interrupted_transaction,
        "interrupted_transactions": list(interrupted_transactions),
        "diff": diff,
        "candidate_markdown": candidate_text,
    }
    return Plan(
        data,
        candidate_text,
        candidate_sha,
        current_sha,
        target_path,
        tuple(planned_files),
        source_preconditions,
    )


def _atomic_write(target: Path, content: str, expected_sha256: str | None) -> None:
    parent = target.parent
    if not parent.is_dir() or _is_link_or_junction(parent):
        raise MemoCardsError("safety", "target parent must already be a real directory")
    lock = parent / f".{target.name}.memo-cards.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MemoCardsError("conflict", "another memo-cards publication may be running") from exc
    temp_path: Path | None = None
    holding_path: Path | None = None
    candidate_sha256 = _sha256_text(content)

    def restore_holding() -> bool:
        nonlocal holding_path
        if holding_path is None or not holding_path.exists():
            return True
        try:
            os.link(holding_path, target)
        except FileExistsError:
            return False
        holding_path.unlink()
        holding_path = None
        return True

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        present = target.exists() or target.is_symlink()
        if expected_sha256 is None:
            if present:
                raise MemoCardsError("conflict", "target appeared after preview")
        else:
            if not present or _sha256_file(target) != expected_sha256:
                raise MemoCardsError("conflict", "target changed after preview")
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        if expected_sha256 is None:
            os.link(temp_path, target)
            if _sha256_file(target) != candidate_sha256:
                raise MemoCardsError("integrity", "new target changed during publication")
            temp_path.unlink()
            temp_path = None
        else:
            if _sha256_file(target) != expected_sha256:
                raise MemoCardsError("conflict", "target changed during publication")
            for _attempt in range(10):
                candidate_holding = parent / (
                    f".{target.name}.memo-cards-hold-{uuid.uuid4().hex}"
                )
                if not candidate_holding.exists() and not candidate_holding.is_symlink():
                    holding_path = candidate_holding
                    break
            if holding_path is None:
                raise MemoCardsError("integrity", "cannot allocate a recovery holding path")
            try:
                os.rename(target, holding_path)
            except FileNotFoundError as exc:
                raise MemoCardsError("conflict", "target disappeared during publication") from exc

            displaced_sha256 = _sha256_file(holding_path)
            if displaced_sha256 != expected_sha256:
                restored = restore_holding()
                raise MemoCardsError(
                    "conflict",
                    "target changed while it was being isolated for publication",
                    details={
                        "expected": expected_sha256,
                        "actual": displaced_sha256,
                        "recovery": None if restored else holding_path.name,
                    },
                )
            try:
                os.link(temp_path, target)
            except FileExistsError as exc:
                raise MemoCardsError(
                    "conflict",
                    "a competing target appeared during publication; old bytes were preserved",
                    details={"recovery": holding_path.name},
                ) from exc
            except Exception:
                if not (target.exists() or target.is_symlink()):
                    restore_holding()
                raise

            if _sha256_file(target) != candidate_sha256:
                raise MemoCardsError(
                    "conflict",
                    "published target changed before final verification; old bytes were preserved",
                    details={"recovery": holding_path.name},
                )
            temp_path.unlink()
            temp_path = None
            if holding_path.exists():
                holding_path.unlink()
            holding_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _repository_publication_locks(
    root: Path, runtime: Mapping[str, Any]
) -> Iterator[None]:
    """Serialize inventory planning using locks inside authorized output roots."""

    token = f"{os.getpid()}:{uuid.uuid4().hex}\n".encode("ascii")
    locks: list[Path] = []
    try:
        for relative_root in runtime["allowlist"]["write_paths"]:
            output_root = _resolve_under(
                root,
                relative_root,
                label="memo-cards write path",
                must_exist=False,
            )
            if not output_root.exists():
                continue
            if not output_root.is_dir() or _is_link_or_junction(output_root):
                raise MemoCardsError(
                    "safety",
                    "memo-cards write path must be a real directory",
                    details={"path": relative_root},
                )
            lock = output_root / PUBLICATION_LOCK_NAME
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(lock, flags, 0o600)
            except FileExistsError as exc:
                raise MemoCardsError(
                    "conflict",
                    "another memo-cards publication may be running or requires recovery",
                    details={"lock": lock.relative_to(root).as_posix()},
                ) from exc
            locks.append(lock)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
        yield
    finally:
        for lock in reversed(locks):
            # Never unlink a lock that was replaced after ours was created.
            try:
                if (
                    lock.is_file()
                    and not _is_link_or_junction(lock)
                    and lock.read_bytes() == token
                ):
                    lock.unlink()
            except OSError:
                # A surviving lock is fail-closed and is reported by verify.
                pass


def _atomic_publish_set(
    files: Sequence[PlannedFile],
    document_target: Path,
    source_preconditions: Sequence[SourcePrecondition] = (),
) -> None:
    parent = document_target.parent
    if not parent.is_dir() or _is_link_or_junction(parent):
        raise MemoCardsError("safety", "artifact-set parent must already be a real directory")
    if any(file.path.parent != parent for file in files):
        raise MemoCardsError("safety", "all managed sidecars must be siblings of the Markdown target")
    lock = parent / f".{document_target.name}.memo-cards.lock"
    journal = parent / f".{document_target.name}.memo-cards-transaction.json"
    if journal.exists() or journal.is_symlink():
        raise MemoCardsError(
            "conflict",
            "an interrupted memo-cards publication requires recovery",
            details={"journal": journal.name},
        )
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MemoCardsError("conflict", "another memo-cards publication may be running") from exc

    transaction_id = uuid.uuid4().hex
    temp_paths: dict[str, Path] = {}
    holding_paths: dict[str, Path] = {}
    installed: list[PlannedFile] = []
    journal_created = False
    committed = False

    def present(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    def allocate_holding(file: PlannedFile) -> Path:
        for _attempt in range(20):
            candidate = parent / (
                f".{file.path.name}.memo-cards-hold-{transaction_id}-{uuid.uuid4().hex}"
            )
            if not present(candidate):
                return candidate
        raise MemoCardsError("integrity", "cannot allocate a recovery holding path")

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
            handle.flush()
            os.fsync(handle.fileno())

        for file in files:
            is_present = present(file.path)
            if file.current_sha256 is None:
                if is_present:
                    raise MemoCardsError(
                        "conflict",
                        "artifact-set file appeared after preview",
                        details={"path": file.relative_path},
                    )
                continue
            if (
                not is_present
                or not file.path.is_file()
                or _is_link_or_junction(file.path)
                or _sha256_file(file.path) != file.current_sha256
            ):
                raise MemoCardsError(
                    "conflict",
                    "artifact-set file changed after preview",
                    details={"path": file.relative_path},
                )

        for file in files:
            if file.operation == "no-op" or file.candidate_bytes is None:
                continue
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=parent,
                prefix=f".{file.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(file.candidate_bytes)
                handle.flush()
                os.fsync(handle.fileno())
                temp_paths[file.relative_path] = Path(handle.name)

        # The request source snapshot participates in the same compare-and-swap
        # boundary as every output file.  Recheck after staging and again before
        # the Markdown commit point is accepted so a source edit cannot publish
        # a manifest that names stale source bytes.
        _check_source_preconditions(source_preconditions)

        journal_payload = {
            "schema": "memo-cards.transaction/v1",
            "transaction_id": transaction_id,
            "document": document_target.name,
            "files": [
                {
                    "path": file.path.name,
                    "operation": file.operation,
                    "current_sha256": file.current_sha256,
                    "candidate_sha256": file.candidate_sha256,
                }
                for file in files
                if file.operation != "no-op"
            ],
        }
        journal_descriptor = os.open(
            journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(journal_descriptor, "wb") as handle:
            handle.write(_canonical_bytes(journal_payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        journal_created = True

        for file in files:
            if file.operation == "no-op" or file.current_sha256 is None:
                continue
            holding = allocate_holding(file)
            try:
                os.rename(file.path, holding)
            except FileNotFoundError as exc:
                raise MemoCardsError(
                    "conflict",
                    "artifact-set file disappeared during publication",
                    details={"path": file.relative_path},
                ) from exc
            holding_paths[file.relative_path] = holding
            displaced_sha256 = _sha256_file(holding)
            if displaced_sha256 != file.current_sha256:
                raise MemoCardsError(
                    "conflict",
                    "artifact-set file changed while being isolated",
                    details={
                        "path": file.relative_path,
                        "expected": file.current_sha256,
                        "actual": displaced_sha256,
                    },
                )

        install_order = sorted(
            (
                file
                for file in files
                if file.operation != "no-op" and file.candidate_bytes is not None
            ),
            key=lambda file: (file.role == "markdown", file.relative_path),
        )
        for file in install_order:
            try:
                os.link(temp_paths[file.relative_path], file.path)
            except FileExistsError as exc:
                raise MemoCardsError(
                    "conflict",
                    "a competing artifact-set file appeared during publication",
                    details={"path": file.relative_path},
                ) from exc
            installed.append(file)
            if _sha256_file(file.path) != file.candidate_sha256:
                raise MemoCardsError(
                    "integrity",
                    "installed artifact-set file failed its digest check",
                    details={"path": file.relative_path},
                )

        for file in files:
            if file.candidate_sha256 is None:
                if file.operation == "remove" and present(file.path):
                    raise MemoCardsError(
                        "integrity",
                        "removed sidecar reappeared during publication",
                        details={"path": file.relative_path},
                    )
                continue
            if not present(file.path) or _sha256_file(file.path) != file.candidate_sha256:
                raise MemoCardsError(
                    "conflict",
                    "artifact-set changed before final verification",
                    details={"path": file.relative_path},
                )
        _check_source_preconditions(source_preconditions)
        committed = True

        cleanup_errors: list[str] = []
        for relative, temp_path in list(temp_paths.items()):
            try:
                temp_path.unlink()
                del temp_paths[relative]
            except OSError:
                cleanup_errors.append(temp_path.name)
        for relative, holding in list(holding_paths.items()):
            try:
                holding.unlink()
                del holding_paths[relative]
            except OSError:
                cleanup_errors.append(holding.name)
        if not cleanup_errors:
            try:
                journal.unlink()
                journal_created = False
            except OSError:
                cleanup_errors.append(journal.name)
        if cleanup_errors:
            raise MemoCardsError(
                "integrity",
                "artifact-set was committed but publication cleanup requires recovery",
                details={"recovery": sorted(set(cleanup_errors + [journal.name]))},
            )
    except Exception as exc:
        if committed:
            raise
        recovery: list[str] = []
        for file in reversed(installed):
            if not present(file.path):
                continue
            try:
                if _sha256_file(file.path) == file.candidate_sha256:
                    file.path.unlink()
                else:
                    recovery.append(file.relative_path)
            except OSError:
                recovery.append(file.relative_path)
        for relative, holding in list(holding_paths.items()):
            if not present(holding):
                continue
            file = next(item for item in files if item.relative_path == relative)
            if present(file.path):
                recovery.append(holding.name)
                continue
            try:
                os.link(holding, file.path)
                holding.unlink()
                del holding_paths[relative]
            except OSError:
                recovery.append(holding.name)
        if journal_created and not recovery:
            try:
                journal.unlink()
                journal_created = False
            except OSError:
                recovery.append(journal.name)
        if recovery:
            if isinstance(exc, MemoCardsError):
                details = dict(exc.details)
                details["recovery"] = sorted(set(recovery))
                raise MemoCardsError(exc.kind, exc.message, details=details) from exc
            raise MemoCardsError(
                "integrity",
                "artifact-set publication failed and requires recovery",
                details={"recovery": sorted(set(recovery))},
            ) from exc
        raise
    finally:
        for temp_path in temp_paths.values():
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def prepare(repo: Path, context_path: Path, request_path: Path) -> dict[str, Any]:
    root = _repository_root(repo)
    runtime = _load_runtime_context(
        root, context_path, check_tracked_files=False
    )
    interrupted_transactions = _interrupted_transactions(root, runtime)
    if interrupted_transactions:
        raise MemoCardsError(
            "conflict",
            "an interrupted memo-cards publication requires recovery",
            details={"transactions": list(interrupted_transactions)},
        )
    runtime = _load_runtime_context(root, context_path)
    registry = load_template_registry()
    plan = _prepare_plan(root, runtime, _load_json(request_path, "request"), registry)
    return plan.data


def verify(repo: Path, context_path: Path, request_path: Path | None = None) -> dict[str, Any]:
    root = _repository_root(repo)
    runtime = _load_runtime_context(
        root, context_path, check_tracked_files=False
    )
    publication_locks = _publication_lock_states(root, runtime)
    interrupted_transactions = _interrupted_transactions(root, runtime)
    inventory_unavailable = bool(publication_locks or interrupted_transactions)
    if not inventory_unavailable:
        runtime = _load_runtime_context(root, context_path)
    context = runtime["context"]
    registry = load_template_registry()
    inventory = (
        Inventory((), (), (), "")
        if inventory_unavailable
        else _scan_inventory(root, runtime)
    )
    runtime_digest = _digest_value(
        {"context": context, "allowlist": runtime["allowlist"]}
    )
    result: dict[str, Any] = {
        "repository_id": context["repository"]["repository_id"],
        "context_sha256": runtime_digest,
        "template_registry_version": registry.version,
        "template_registry_sha256": registry.digest,
        "managed_artifacts": [
            {
                "path": artifact.path,
                "sha256": artifact.sha256,
                "schema": artifact.manifest["schema"],
                "migration_required": artifact.manifest["schema"] == ARTIFACT_SCHEMA_V1,
                "body_drifted": artifact.body_drifted,
                "header_drifted": artifact.header_drifted,
                "artifact_set_drifted": bool(
                    artifact.body_drifted
                    or artifact.header_drifted
                    or artifact.sidecar_issues
                ),
                "card_count": len(artifact.manifest["cards"]),
                "sidecars": list(artifact.sidecar_reports),
            }
            for artifact in inventory.artifacts
        ],
        "legacy_inventory": list(inventory.legacy),
        "dependency_drift": list(inventory.dependency_drift),
        "sidecar_drift": [
            {"artifact": artifact.path, **issue}
            for artifact in inventory.artifacts
            for issue in artifact.sidecar_issues
        ],
        "interrupted_transactions": list(interrupted_transactions),
        "publication_lock": publication_locks[0] if publication_locks else None,
        "publication_locks": list(publication_locks),
        "inventory_fingerprint": None if inventory_unavailable else inventory.fingerprint,
        "inventory_unavailable": inventory_unavailable,
    }
    if request_path is not None:
        if inventory_unavailable:
            result["request_check"] = {
                "operation": "blocked",
                "would_write": True,
                "blocking_reasons": [
                    *(["publication-lock"] if publication_locks else []),
                    *(
                        ["interrupted-publication"]
                        if interrupted_transactions
                        else []
                    ),
                ],
            }
        else:
            plan = _prepare_plan(root, runtime, _load_json(request_path, "request"), registry)
            result["request_check"] = {
                "request_sha256": plan.data["request_sha256"],
                "target": plan.data["target"],
                "operation": plan.data["operation"],
                "would_write": plan.data["operation"] != "no-op",
                "preview_digest": plan.data["preview_digest"],
                "artifact_set_sha256": plan.data["artifact_set_sha256"],
                "files": plan.data["files"],
            }
            result["preview"] = plan.data
    return result


def _publish_under_repository_lock(
    repo: Path,
    context_path: Path,
    request_path: Path,
    preview_digest: str,
    authorization: str,
) -> dict[str, Any]:
    root = _repository_root(repo)
    runtime = _load_runtime_context(
        root, context_path, check_tracked_files=False
    )
    interrupted_transactions = _interrupted_transactions(root, runtime)
    if interrupted_transactions:
        raise MemoCardsError(
            "conflict",
            "an interrupted memo-cards publication requires recovery",
            details={"transactions": list(interrupted_transactions)},
        )
    runtime = _load_runtime_context(root, context_path)
    registry = load_template_registry()
    plan = _prepare_plan(root, runtime, _load_json(request_path, "request"), registry)
    expected_preview = _digest(preview_digest, "preview digest", kind="conflict")
    if plan.data["preview_digest"] != expected_preview:
        raise MemoCardsError(
            "conflict",
            "preview digest no longer matches; prepare and confirm again",
            details={"expected": expected_preview, "actual": plan.data["preview_digest"]},
        )
    if plan.data["interrupted_transaction"] is not None:
        raise MemoCardsError(
            "conflict",
            "an interrupted memo-cards publication requires recovery",
            details=plan.data["interrupted_transaction"],
        )
    if plan.data["operation"] == "no-op":
        return {
            "operation": "no-op",
            "target": plan.data["target"],
            "preview_digest": expected_preview,
            "written": False,
            "artifact_set_sha256": plan.data["artifact_set_sha256"],
            "files": plan.data["files"],
        }
    if plan.data["required_authorization"] == "confirmed" and authorization != "confirmed":
        raise MemoCardsError("conflict", "this preview requires explicit post-diff confirmation")
    if authorization not in {"request", "confirmed"}:
        raise MemoCardsError("usage", "authorization must be request or confirmed")
    if plan.candidate_text is None or plan.candidate_sha256 is None:
        raise MemoCardsError("integrity", "publication plan has no candidate artifact")
    _atomic_publish_set(
        plan.files, plan.target_path, plan.source_preconditions
    )
    actual = _sha256_file(plan.target_path)
    if actual != plan.candidate_sha256:
        raise MemoCardsError("integrity", "published target failed its final digest check")
    return {
        "operation": plan.data["operation"],
        "target": plan.data["target"],
        "preview_digest": expected_preview,
        "written": True,
        "sha256": actual,
        "artifact_set_sha256": plan.data["artifact_set_sha256"],
        "files": [
            {
                "path": file.relative_path,
                "role": file.role,
                "template_id": file.template_id,
                "operation": file.operation,
                "sha256": file.candidate_sha256,
                "written": file.operation != "no-op",
            }
            for file in plan.files
            if file.candidate_sha256 is not None
        ],
    }


def publish(
    repo: Path,
    context_path: Path,
    request_path: Path,
    preview_digest: str,
    authorization: str,
) -> dict[str, Any]:
    root = _repository_root(repo)
    coordination_runtime = _load_runtime_context(
        root, context_path, check_tracked_files=False
    )
    with _repository_publication_locks(root, coordination_runtime):
        # Planning happens after the repository-wide output lock set is held.
        # This makes the inventory fingerprint and cross-target logical-ID check
        # part of the same serialized boundary as artifact-set publication.
        return _publish_under_repository_lock(
            root,
            context_path,
            request_path,
            preview_digest,
            authorization,
        )


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = JsonArgumentParser(
        description="Prepare, verify, and publish managed Markji Markdown/XLSX bundles."
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=JsonArgumentParser
    )
    for command in ("verify", "prepare", "publish"):
        child = subparsers.add_parser(command)
        child.add_argument("--repo", type=Path, required=True)
        child.add_argument("--context", type=Path, required=True)
        if command in {"prepare", "publish"}:
            child.add_argument("--request", type=Path, required=True)
        elif command == "verify":
            child.add_argument("--request", type=Path)
        if command == "publish":
            child.add_argument("--preview-digest", required=True)
            child.add_argument("--authorization", choices=("request", "confirmed"), required=True)
    return parser.parse_args(argv)


def _emit_json(value: Mapping[str, Any]) -> None:
    # JSON escapes keep the wire output ASCII-safe even when Windows stdout is GBK.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    command: str | None = None
    try:
        args = _arguments(argv)
        command = args.command
        if command == "verify":
            data = verify(args.repo, args.context, args.request)
        elif command == "prepare":
            data = prepare(args.repo, args.context, args.request)
        else:
            data = publish(
                args.repo,
                args.context,
                args.request,
                args.preview_digest,
                args.authorization,
            )
        envelope = {"schema_version": 1, "ok": True, "command": command, "data": data}
        _emit_json(envelope)
        return EXIT_OK
    except MemoCardsError as exc:
        envelope = {
            "schema_version": 1,
            "ok": False,
            "command": command,
            "error": {"code": exc.kind, "message": exc.message, "details": exc.details},
        }
        _emit_json(envelope)
        return exc.exit_code
    except (OSError, UnicodeError) as exc:
        envelope = {
            "schema_version": 1,
            "ok": False,
            "command": command,
            "error": {"code": "integrity", "message": str(exc), "details": {}},
        }
        _emit_json(envelope)
        return EXIT_INTEGRITY


if __name__ == "__main__":
    raise SystemExit(main())
