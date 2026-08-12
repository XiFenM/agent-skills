"""Pure public-context validator for ``study-log``.

The shared materializer owns filesystem, Git, link, and protected-path checks.
This module only validates portable public configuration and returns a
JSON-serializable context plus allowlists.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


REPOSITORY_SCHEMA = "agent-skills.repository/v1"
SKILL_SCHEMA = "agent-skills.study-log/v1"
CONTEXT_SCHEMA = "agent-skills.study-log-context/v1"
SKILL_NAME = "study-log"

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


class ContextConfigError(ValueError):
    """Raised when public study-log configuration is invalid."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextConfigError(f"{label} must be an object")
    return value


def _exact_keys(
    value: dict[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    label: str,
) -> None:
    unknown = [key for key in value if not isinstance(key, str) or key not in allowed]
    missing = [key for key in sorted(required) if key not in value]
    if unknown:
        rendered = ", ".join(sorted(repr(key) for key in unknown))
        raise ContextConfigError(f"{label} contains unknown fields: {rendered}")
    if missing:
        raise ContextConfigError(f"{label} is missing fields: {', '.join(missing)}")


def _string(value: Any, label: str, *, maximum: int = 240) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character in value for character in "\r\n\x00")
    ):
        raise ContextConfigError(
            f"{label} must be a non-empty, trimmed single-line string"
        )
    return value


def _identifier(value: Any, label: str) -> str:
    identifier = _string(value, label, maximum=64)
    if _ID_PATTERN.fullmatch(identifier) is None:
        raise ContextConfigError(f"{label} must be a lowercase hyphen identifier")
    return identifier


def _relative_directory(value: Any, label: str) -> str:
    raw = _string(value, label, maximum=500)
    if (
        raw.startswith("/")
        or raw.endswith("/")
        or "\\" in raw
        or "//" in raw
        or re.match(r"^[A-Za-z]:", raw)
        or any(character in raw for character in '<>:"|?*')
    ):
        raise ContextConfigError(
            f"{label} must be a portable repository-relative directory"
        )
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ContextConfigError(
            f"{label} must be a portable repository-relative directory"
        )
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise ContextConfigError(f"{label} contains a Windows-unsafe component")
    return PurePosixPath(*parts).as_posix()


def _repository_config(value: Any) -> dict[str, Any]:
    repository = _object(value, "repository_config")
    _exact_keys(
        repository,
        allowed=frozenset(
            {"schema", "repository_id", "language", "timezone", "facts"}
        ),
        required=frozenset({"schema", "repository_id"}),
        label="repository_config",
    )
    if repository["schema"] != REPOSITORY_SCHEMA:
        raise ContextConfigError(
            f"repository_config.schema must equal {REPOSITORY_SCHEMA!r}"
        )
    result: dict[str, Any] = {
        "repository_id": _identifier(
            repository["repository_id"], "repository_config.repository_id"
        )
    }
    for key in ("language", "timezone"):
        if key in repository:
            result[key] = _string(repository[key], f"repository_config.{key}", maximum=80)
    if not isinstance(repository.get("facts", {}), dict):
        raise ContextConfigError("repository_config.facts must be an object")
    return result


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(part.casefold() for part in PurePosixPath(left).parts)
    right_parts = tuple(part.casefold() for part in PurePosixPath(right).parts)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _structured_targets(value: Any) -> list[dict[str, Any]]:
    label = "skill_config.structured_targets"
    if not isinstance(value, list) or not value:
        raise ContextConfigError(f"{label} must be a non-empty array")

    targets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_target in enumerate(value):
        target_label = f"{label}[{index}]"
        target = _object(raw_target, target_label)
        _exact_keys(
            target,
            allowed=frozenset({"id", "path"}),
            required=frozenset({"id", "path"}),
            label=target_label,
        )
        target_id = _identifier(target["id"], f"{target_label}.id")
        if target_id in seen_ids:
            raise ContextConfigError(f"{label} contains duplicate id {target_id!r}")
        seen_ids.add(target_id)
        path = _relative_directory(target["path"], f"{target_label}.path")
        for existing in targets:
            if _paths_overlap(path, existing["path"]):
                raise ContextConfigError(
                    f"structured target paths must be separate: {path!r} and "
                    f"{existing['path']!r}"
                )
        targets.append(
            {
                "id": target_id,
                "record_type": "structured-study-log",
                "path": path,
                "format": "markdown",
                "include_patterns": ["*.md"],
                "filename_policy": "yyyy-mm-dd-topic",
            }
        )
    return sorted(targets, key=lambda item: item["id"])


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Validate public config without filesystem, Git, environment, or I/O access."""

    repository = _repository_config(repository_config)
    skill = _object(skill_config, "skill_config")
    _exact_keys(
        skill,
        allowed=frozenset({"schema", "skill", "structured_targets"}),
        required=frozenset({"schema", "skill", "structured_targets"}),
        label="skill_config",
    )
    if skill["schema"] != SKILL_SCHEMA:
        raise ContextConfigError(f"skill_config.schema must equal {SKILL_SCHEMA!r}")
    if skill["skill"] != SKILL_NAME:
        raise ContextConfigError(f"skill_config.skill must equal {SKILL_NAME!r}")

    targets = _structured_targets(skill["structured_targets"])
    return {
        "context": {
            "schema": CONTEXT_SCHEMA,
            "repository": repository,
            "structured_targets": targets,
        },
        # Public study-log context deliberately grants no repository reads. Existing
        # files are handled only when the user identifies an exact target and grants
        # the current operation; the materializer must not scan target collections.
        "tracked_files": [],
        "tracked_collections": [],
        "write_paths": sorted({target["path"] for target in targets}),
    }
