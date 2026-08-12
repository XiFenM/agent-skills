"""Strict, side-effect-free repository context for ``guide-learning``.

The shared materializer owns filesystem, Git, link, and path-boundary checks.
This module only validates declarative repository locators and returns the
canonical context plus the materializer allowlists.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


REPOSITORY_SCHEMA = "agent-skills.repository/v1"
SKILL_SCHEMA = "agent-skills.guide-learning/v1"
CONTEXT_SCHEMA = "agent-skills.guide-learning-context/v1"
SKILL_NAME = "guide-learning"

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_TIMEZONE_PATTERN = re.compile(
    r"^(?:UTC|[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+)$"
)
_FACT_ROLES = frozenset(
    {
        "budget-source",
        "evidence-artifacts",
        "knowledge-artifacts",
        "learner-preferences",
        "legacy-evidence",
        "progress-source",
        "repository-instructions",
        "source-catalog",
        "validation-instructions",
    }
)
_RECORD_ROLES = frozenset(
    {
        "checkpoint",
        "lesson",
        "practice-artifacts",
        "practice-contracts",
        "practice-records",
        "practice-validation",
        "program",
        "session-events",
    }
)
_KINDS = frozenset({"collection", "file"})
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


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
        if _TIMEZONE_PATTERN.fullmatch(timezone) is None:
            raise ContextConfigError(
                "repository_config.timezone must be UTC or an IANA-style timezone"
            )
        result["timezone"] = timezone

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
            )
        parsed_facts[fact_id] = parsed
    result["facts"] = dict(sorted(parsed_facts.items()))
    return result


def _fact_refs(value: Any, repository: dict[str, Any]) -> list[dict[str, str]]:
    label = "skill_config.repository_fact_refs"
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_ref in enumerate(value):
        ref_label = f"{label}[{index}]"
        ref = _object(raw_ref, ref_label)
        _exact_keys(
            ref,
            allowed=frozenset({"fact_id", "role", "kind"}),
            required=frozenset({"fact_id", "role", "kind"}),
            label=ref_label,
        )
        fact_id = _identifier(ref["fact_id"], f"{ref_label}.fact_id")
        if fact_id in seen:
            raise ContextConfigError(f"{label} contains duplicate fact {fact_id!r}")
        if fact_id not in repository["facts"]:
            raise ContextConfigError(f"{ref_label} references unknown fact {fact_id!r}")
        seen.add(fact_id)
        kind = _enum(ref["kind"], _KINDS, f"{ref_label}.kind")
        if kind == "collection" and "section" in repository["facts"][fact_id]:
            raise ContextConfigError(
                f"{ref_label} collection fact must not declare a section"
            )
        result.append(
            {
                "fact_id": fact_id,
                "role": _enum(ref["role"], _FACT_ROLES, f"{ref_label}.role"),
                "kind": kind,
            }
        )
    return sorted(result, key=lambda item: item["fact_id"])


def _record_mappings(value: Any) -> dict[str, dict[str, str]]:
    label = "skill_config.record_mappings"
    mappings = _object(value, label)
    unknown = [role for role in mappings if role not in _RECORD_ROLES]
    if unknown:
        raise ContextConfigError(
            f"{label} contains unknown roles: "
            + ", ".join(sorted(repr(role) for role in unknown))
        )

    result: dict[str, dict[str, str]] = {}
    for role in sorted(mappings):
        mapping_label = f"{label}.{role}"
        mapping = _object(mappings[role], mapping_label)
        _exact_keys(
            mapping,
            allowed=frozenset({"path", "kind", "section"}),
            required=frozenset({"path", "kind"}),
            label=mapping_label,
        )
        kind = _enum(mapping["kind"], _KINDS, f"{mapping_label}.kind")
        if role == "checkpoint" and kind != "file":
            raise ContextConfigError(
                "skill_config.record_mappings.checkpoint must use kind 'file'"
            )
        parsed = {
            "path": _relative_path(mapping["path"], f"{mapping_label}.path"),
            "kind": kind,
        }
        if "section" in mapping:
            if kind != "file":
                raise ContextConfigError(
                    f"{mapping_label}.section is only valid for a file"
                )
            parsed["section"] = _string(
                mapping["section"], f"{mapping_label}.section", maximum=160
            )
        result[role] = parsed
    return result


def _folded_path(path: str) -> PurePosixPath:
    return PurePosixPath(*(part.casefold() for part in PurePosixPath(path).parts))


def _is_proper_ancestor(left: str, right: str) -> bool:
    left_path = _folded_path(left)
    right_path = _folded_path(right)
    if left_path == right_path:
        return False
    try:
        right_path.relative_to(left_path)
    except ValueError:
        return False
    return True


def _validate_mapping_boundaries(
    fact_refs: list[dict[str, str]],
    records: dict[str, dict[str, str]],
    repository: dict[str, Any],
) -> None:
    read_facts = [
        (ref["fact_id"], repository["facts"][ref["fact_id"]]["path"])
        for ref in fact_refs
    ]
    for role, mapping in records.items():
        for fact_id, fact_path in read_facts:
            if (
                _folded_path(mapping["path"]) == _folded_path(fact_path)
                or _is_proper_ancestor(mapping["path"], fact_path)
                or _is_proper_ancestor(fact_path, mapping["path"])
            ):
                raise ContextConfigError(
                    f"record mapping {role!r} overlaps read-only fact {fact_id!r}"
                )

    items = list(records.items())
    for index, (left_role, left) in enumerate(items):
        for right_role, right in items[index + 1 :]:
            same_path = _folded_path(left["path"]) == _folded_path(right["path"])
            if same_path:
                if left["path"] != right["path"]:
                    raise ContextConfigError(
                        f"record mappings {left_role!r} and {right_role!r} "
                        "differ only by path casing"
                    )
                sections = (left.get("section"), right.get("section"))
                if (
                    left["kind"] != "file"
                    or right["kind"] != "file"
                    or None in sections
                    or sections[0].casefold() == sections[1].casefold()
                ):
                    raise ContextConfigError(
                        f"record mappings {left_role!r} and {right_role!r} may "
                        "share a file only with distinct sections"
                    )
                continue
            if _is_proper_ancestor(left["path"], right["path"]) or _is_proper_ancestor(
                right["path"], left["path"]
            ):
                raise ContextConfigError(
                    f"record mappings {left_role!r} and {right_role!r} overlap"
                )


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Validate config and return canonical context plus materializer allowlists.

    The returned write paths are mechanical ceilings only. They do not grant
    ownership, authorize repository writes, start a Lesson, or establish
    acceptance or mastery.
    """

    repository = _repository_config(repository_config)
    skill = _object(skill_config, "skill_config")
    _exact_keys(
        skill,
        allowed=frozenset(
            {"schema", "skill", "repository_fact_refs", "record_mappings"}
        ),
        required=frozenset({"schema", "skill"}),
        label="skill_config",
    )
    if skill["schema"] != SKILL_SCHEMA:
        raise ContextConfigError(
            f"skill_config.schema must equal {SKILL_SCHEMA!r}"
        )
    if skill["skill"] != SKILL_NAME:
        raise ContextConfigError(
            f"skill_config.skill must equal {SKILL_NAME!r}"
        )

    fact_refs = _fact_refs(skill.get("repository_fact_refs", []), repository)
    records = _record_mappings(skill.get("record_mappings", {}))
    _validate_mapping_boundaries(fact_refs, records, repository)

    selected_facts = {
        ref["fact_id"]: dict(repository["facts"][ref["fact_id"]])
        for ref in fact_refs
    }
    repository_context: dict[str, Any] = {
        "schema": REPOSITORY_SCHEMA,
        "repository_id": repository["repository_id"],
        "facts": selected_facts,
    }
    for optional_key in ("language", "timezone"):
        if optional_key in repository:
            repository_context[optional_key] = repository[optional_key]

    tracked_files = {
        repository["facts"][ref["fact_id"]]["path"]
        for ref in fact_refs
        if ref["kind"] == "file"
    }
    tracked_collections = {
        repository["facts"][ref["fact_id"]]["path"]
        for ref in fact_refs
        if ref["kind"] == "collection"
    }
    return {
        "context": {
            "schema": CONTEXT_SCHEMA,
            "repository": repository_context,
            "repository_fact_refs": fact_refs,
            "record_mappings": records,
        },
        "tracked_files": sorted(tracked_files),
        "tracked_collections": sorted(tracked_collections),
        "write_paths": sorted({mapping["path"] for mapping in records.values()}),
    }
