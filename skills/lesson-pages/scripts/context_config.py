"""Strict, side-effect-free repository context for ``lesson-pages``.

The shared materializer owns filesystem, Git, link, and path-boundary checks.
This module only validates the declared page directories and returns the
canonical context plus the materializer allowlists. A page directory is a
mechanical write ceiling: it never authorizes creating, overwriting,
scanning, serving, or publishing a page.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


REPOSITORY_SCHEMA = "agent-skills.repository/v1"
SKILL_SCHEMA = "agent-skills.lesson-pages/v1"
CONTEXT_SCHEMA = "agent-skills.lesson-pages-context/v1"
SKILL_NAME = "lesson-pages"
REQUIRED_SKILLS = ("guide-learning",)

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_TIMEZONE_PATTERN = re.compile(
    r"^(?:UTC|[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+)$"
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{prefix}{suffix}" for prefix in ("COM", "LPT") for suffix in "123456789\u00b9\u00b2\u00b3"}
)
_PROTECTED_ROOTS = frozenset({".git", ".agents", ".claude"})


class ContextConfigError(ValueError):
    """Raised when public configuration violates the strict schema."""


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


def _relative_path(value: Any, label: str) -> str:
    path = _string(value, label, maximum=512)
    parts = path.split("/")
    if (
        path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or ":" in path
        or "//" in path
        or any(part in {"", ".", ".."} for part in parts)
        or any(character in path for character in '<>"|?*')
    ):
        raise ContextConfigError(f"{label} must be a safe repository-relative path")
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        ):
            raise ContextConfigError(
                f"{label} contains a Windows-unsafe path component"
            )
        folded = part.rstrip(" .").casefold()
        if folded in _PROTECTED_ROOTS or folded.startswith(".agent-skills"):
            raise ContextConfigError(f"{label} must not live under {part}")
    return path


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
        "schema": REPOSITORY_SCHEMA,
        "repository_id": _identifier(
            repository["repository_id"], "repository_config.repository_id"
        ),
    }
    if "language" in repository:
        language = _string(
            repository["language"], "repository_config.language", maximum=35
        )
        if _LANGUAGE_PATTERN.fullmatch(language) is None:
            raise ContextConfigError(
                "repository_config.language must be a BCP-47-style language tag"
            )
        result["language"] = language
    if "timezone" in repository:
        timezone = _string(
            repository["timezone"], "repository_config.timezone", maximum=80
        )
        if _TIMEZONE_PATTERN.fullmatch(timezone) is None or any(
            part in {".", ".."} for part in timezone.split("/")
        ):
            raise ContextConfigError(
                "repository_config.timezone must be UTC or an IANA-style timezone"
            )
        result["timezone"] = timezone
    # Facts belong to other Skills; lesson-pages selects none, but the shared
    # repository document must still be an object of objects.
    facts = _object(repository.get("facts", {}), "repository_config.facts")
    for raw_fact_id, raw_fact in facts.items():
        _identifier(raw_fact_id, "repository_config fact id")
        _object(raw_fact, f"repository_config.facts.{raw_fact_id}")
    return result


def _folded_path(path: str) -> PurePosixPath:
    return PurePosixPath(*(part.casefold() for part in PurePosixPath(path).parts))


def _overlap(left: str, right: str) -> bool:
    left_path = _folded_path(left)
    right_path = _folded_path(right)
    if left_path == right_path:
        return True
    for ancestor, descendant in ((left_path, right_path), (right_path, left_path)):
        try:
            descendant.relative_to(ancestor)
        except ValueError:
            continue
        return True
    return False


def _page_targets(value: Any) -> list[dict[str, str]]:
    label = "skill_config.page_targets"
    if not isinstance(value, list) or not value:
        raise ContextConfigError(f"{label} must be a non-empty array")
    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw_target in enumerate(value):
        target_label = f"{label}[{index}]"
        target = _object(raw_target, target_label)
        _exact_keys(
            target,
            allowed=frozenset({"id", "collection"}),
            required=frozenset({"id", "collection"}),
            label=target_label,
        )
        target_id = _identifier(target["id"], f"{target_label}.id")
        if target_id in seen_ids:
            raise ContextConfigError(f"{label} contains duplicate id {target_id!r}")
        seen_ids.add(target_id)
        collection = _relative_path(target["collection"], f"{target_label}.collection")
        for existing in result:
            if _overlap(collection, existing["collection"]):
                raise ContextConfigError(
                    f"page target collections must be separate: {collection!r} "
                    f"and {existing['collection']!r}"
                )
        result.append(
            {
                "id": target_id,
                "collection": collection,
                "format": "html",
                "include_patterns": ["*.html"],
            }
        )
    return sorted(result, key=lambda item: item["id"])


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Validate config and return canonical context plus materializer allowlists.

    The returned write paths are mechanical ceilings only. They do not grant
    ownership, authorize page writes, start a Lesson, or turn a page into
    learning state or evidence.
    """

    repository = _repository_config(repository_config)
    skill = _object(skill_config, "skill_config")
    _exact_keys(
        skill,
        allowed=frozenset({"schema", "skill", "page_targets"}),
        required=frozenset({"schema", "skill", "page_targets"}),
        label="skill_config",
    )
    if skill["schema"] != SKILL_SCHEMA:
        raise ContextConfigError(f"skill_config.schema must equal {SKILL_SCHEMA!r}")
    if skill["skill"] != SKILL_NAME:
        raise ContextConfigError(f"skill_config.skill must equal {SKILL_NAME!r}")
    targets = _page_targets(skill["page_targets"])

    repository_context: dict[str, Any] = {
        "schema": REPOSITORY_SCHEMA,
        "repository_id": repository["repository_id"],
        "facts": {},
    }
    for optional_key in ("language", "timezone"):
        if optional_key in repository:
            repository_context[optional_key] = repository[optional_key]
    return {
        "context": {
            "schema": CONTEXT_SCHEMA,
            "repository": repository_context,
            "page_targets": targets,
        },
        "tracked_files": [],
        "tracked_collections": [],
        "write_paths": sorted(target["collection"] for target in targets),
        "required_skills": list(REQUIRED_SKILLS),
    }
