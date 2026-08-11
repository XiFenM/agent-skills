"""Strict, side-effect-free configuration adapter for english-coach.

The shared materializer imports ``validate_materialized_context`` and remains
responsible for filesystem, Git, link, and path-boundary validation.
"""

from __future__ import annotations

import re
from typing import Any


REPOSITORY_SCHEMA = "agent-skills.repository/v1"
SKILL_SCHEMA = "agent-skills.english-coach/v1"
SKILL_NAME = "english-coach"

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_TIMEZONE_PATTERN = re.compile(
    r"^(?:UTC|[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+)$"
)

_CEFR_LEVELS = frozenset({"A1", "A2", "B1", "B2", "C1", "C2"})
_TARGET_REGISTERS = frozenset(
    {
        "academic",
        "general-conversation",
        "interview",
        "presentation",
        "technical",
        "workplace",
        "writing",
    }
)
_FEEDBACK_FOCUS = frozenset(
    {
        "collocation",
        "concision",
        "fluency",
        "grammar",
        "idiomaticity",
        "precision",
        "pronunciation",
        "rhythm",
        "technical-clarity",
    }
)
_RECORD_TYPES = frozenset(
    {"lesson-summary", "practice-review", "structured-study-log"}
)
_RECORD_FORMATS = frozenset({"json", "markdown", "plain-text"})
_SAVE_KINDS = frozenset({"english-feedback-log", "english-review-log"})
_SAVE_FORMATS = frozenset({"markdown", "plain-text"})
_FORMAT_PATTERNS = {
    "json": ["*.json", "**/*.json"],
    "markdown": ["*.md", "**/*.md"],
    "plain-text": ["*.txt", "**/*.txt"],
}
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class ContextConfigError(ValueError):
    """Raised when public configuration does not match the declared schema."""


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


def _enum(value: Any, choices: frozenset[str], label: str) -> str:
    selected = _string(value, label, maximum=64)
    if selected not in choices:
        raise ContextConfigError(
            f"{label} must be one of: {', '.join(sorted(choices))}"
        )
    return selected


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
    return path


def _optional_language(value: Any, label: str) -> str:
    language = _string(value, label, maximum=35)
    if _LANGUAGE_PATTERN.fullmatch(language) is None:
        raise ContextConfigError(f"{label} must be a BCP-47-style language tag")
    return language


def _optional_timezone(value: Any, label: str) -> str:
    timezone = _string(value, label, maximum=80)
    if _TIMEZONE_PATTERN.fullmatch(timezone) is None:
        raise ContextConfigError(f"{label} must be UTC or an IANA-style timezone")
    return timezone


def _string_list(
    value: Any,
    *,
    choices: frozenset[str] | None,
    label: str,
    identifiers: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if identifiers:
            parsed = _identifier(item, item_label)
        elif choices is not None:
            parsed = _enum(item, choices, item_label)
        else:
            parsed = _string(item, item_label)
        if parsed in result:
            raise ContextConfigError(f"{label} contains duplicate value {parsed!r}")
        result.append(parsed)
    return result


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
    repository_id = _identifier(
        repository["repository_id"], "repository_config.repository_id"
    )

    result: dict[str, Any] = {
        "repository_id": repository_id,
        "facts": {},
    }
    if "language" in repository:
        result["language"] = _optional_language(
            repository["language"], "repository_config.language"
        )
    if "timezone" in repository:
        result["timezone"] = _optional_timezone(
            repository["timezone"], "repository_config.timezone"
        )

    facts = _object(repository.get("facts", {}), "repository_config.facts")
    parsed_facts: dict[str, dict[str, str]] = {}
    for raw_fact_id, raw_fact in facts.items():
        fact_id = _identifier(raw_fact_id, "repository_config fact id")
        fact = _object(raw_fact, f"repository_config.facts.{fact_id}")
        _exact_keys(
            fact,
            allowed=frozenset({"path", "section", "description"}),
            required=frozenset({"path"}),
            label=f"repository_config.facts.{fact_id}",
        )
        parsed: dict[str, str] = {
            "path": _relative_path(
                fact["path"], f"repository_config.facts.{fact_id}.path"
            )
        }
        if "section" in fact:
            parsed["section"] = _string(
                fact["section"],
                f"repository_config.facts.{fact_id}.section",
                maximum=160,
            )
        if "description" in fact:
            parsed["description"] = _string(
                fact["description"],
                f"repository_config.facts.{fact_id}.description",
                maximum=240,
            )
        parsed_facts[fact_id] = parsed
    result["facts"] = parsed_facts
    return result


def _learner(value: Any) -> dict[str, str]:
    learner = _object(value, "skill_config.learner")
    _exact_keys(
        learner,
        allowed=frozenset({"cefr", "first_language"}),
        required=frozenset(),
        label="skill_config.learner",
    )
    if not learner:
        raise ContextConfigError("skill_config.learner must not be empty")
    result: dict[str, str] = {}
    if "cefr" in learner:
        result["cefr"] = _enum(
            learner["cefr"], _CEFR_LEVELS, "skill_config.learner.cefr"
        )
    if "first_language" in learner:
        result["first_language"] = _optional_language(
            learner["first_language"], "skill_config.learner.first_language"
        )
    return result


def _record_entries(
    value: Any, label: str, *, collection: bool
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(value):
        entry_label = f"{label}[{index}]"
        entry = _object(raw_entry, entry_label)
        _exact_keys(
            entry,
            allowed=frozenset({"id", "record_type", "path", "format"}),
            required=frozenset({"id", "record_type", "path", "format"}),
            label=entry_label,
        )
        entry_id = _identifier(entry["id"], f"{entry_label}.id")
        if entry_id in seen:
            raise ContextConfigError(f"{label} contains duplicate id {entry_id!r}")
        seen.add(entry_id)
        record_format = _enum(
            entry["format"], _RECORD_FORMATS, f"{entry_label}.format"
        )
        parsed: dict[str, Any] = {
            "id": entry_id,
            "record_type": _enum(
                entry["record_type"], _RECORD_TYPES, f"{entry_label}.record_type"
            ),
            "path": _relative_path(entry["path"], f"{entry_label}.path"),
            "format": record_format,
        }
        if collection:
            parsed["include_patterns"] = list(_FORMAT_PATTERNS[record_format])
        result.append(parsed)
    return result


def _save_targets(value: Any) -> list[dict[str, str]]:
    label = "skill_config.save_targets"
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_target in enumerate(value):
        target_label = f"{label}[{index}]"
        target = _object(raw_target, target_label)
        _exact_keys(
            target,
            allowed=frozenset({"id", "kind", "path", "format"}),
            required=frozenset({"id", "kind", "path", "format"}),
            label=target_label,
        )
        target_id = _identifier(target["id"], f"{target_label}.id")
        if target_id in seen:
            raise ContextConfigError(f"{label} contains duplicate id {target_id!r}")
        seen.add(target_id)
        result.append(
            {
                "id": target_id,
                "kind": _enum(target["kind"], _SAVE_KINDS, f"{target_label}.kind"),
                "path": _relative_path(target["path"], f"{target_label}.path"),
                "format": _enum(
                    target["format"], _SAVE_FORMATS, f"{target_label}.format"
                ),
            }
        )
    return result


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Validate public config and return context plus materializer allowlists.

    This function is deterministic and performs no filesystem, Git, network, or
    environment access. Unknown fields are errors rather than ignored extensions.
    """

    repository = _repository_config(repository_config)
    skill = _object(skill_config, "skill_config")
    _exact_keys(
        skill,
        allowed=frozenset(
            {
                "schema",
                "skill",
                "learner",
                "target_registers",
                "feedback_focus",
                "repository_fact_refs",
                "record_files",
                "record_collections",
                "save_targets",
            }
        ),
        required=frozenset({"schema", "skill"}),
        label="skill_config",
    )
    if skill["schema"] != SKILL_SCHEMA:
        raise ContextConfigError(f"skill_config.schema must equal {SKILL_SCHEMA!r}")
    if skill["skill"] != SKILL_NAME:
        raise ContextConfigError(f"skill_config.skill must equal {SKILL_NAME!r}")

    learner = _learner(skill["learner"]) if "learner" in skill else {}
    target_registers = _string_list(
        skill.get("target_registers", []),
        choices=_TARGET_REGISTERS,
        label="skill_config.target_registers",
    )
    feedback_focus = _string_list(
        skill.get("feedback_focus", []),
        choices=_FEEDBACK_FOCUS,
        label="skill_config.feedback_focus",
    )
    fact_refs = _string_list(
        skill.get("repository_fact_refs", []),
        choices=None,
        identifiers=True,
        label="skill_config.repository_fact_refs",
    )
    missing_fact_refs = [item for item in fact_refs if item not in repository["facts"]]
    if missing_fact_refs:
        raise ContextConfigError(
            "skill_config.repository_fact_refs contains unknown facts: "
            + ", ".join(missing_fact_refs)
        )

    record_files = _record_entries(
        skill.get("record_files", []),
        "skill_config.record_files",
        collection=False,
    )
    record_collections = _record_entries(
        skill.get("record_collections", []),
        "skill_config.record_collections",
        collection=True,
    )
    all_record_ids = [entry["id"] for entry in record_files + record_collections]
    if len(all_record_ids) != len(set(all_record_ids)):
        raise ContextConfigError(
            "record_files and record_collections must not reuse an id"
        )
    save_targets = _save_targets(skill.get("save_targets", []))

    selected_facts = {
        fact_id: dict(repository["facts"][fact_id]) for fact_id in fact_refs
    }
    repository_context: dict[str, Any] = {
        "repository_id": repository["repository_id"],
        "facts": selected_facts,
    }
    for optional_key in ("language", "timezone"):
        if optional_key in repository:
            repository_context[optional_key] = repository[optional_key]

    tracked_files = {
        fact["path"] for fact in selected_facts.values()
    } | {entry["path"] for entry in record_files}

    return {
        "context": {
            "repository": repository_context,
            "learner": learner,
            "target_registers": target_registers,
            "feedback_focus": feedback_focus,
            "record_files": record_files,
            "record_collections": record_collections,
            "save_targets": save_targets,
        },
        "tracked_files": sorted(tracked_files),
        "tracked_collections": sorted(
            {entry["path"] for entry in record_collections}
        ),
        "write_paths": sorted({target["path"] for target in save_targets}),
    }
