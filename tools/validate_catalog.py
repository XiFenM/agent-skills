#!/usr/bin/env python3
"""Validate the central Skill catalog without third-party dependencies."""

from __future__ import annotations

import configparser
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .skill_names import validate_skill_name
except ImportError:  # Direct execution: python tools/validate_catalog.py
    from skill_names import validate_skill_name


ROOT = Path(__file__).resolve().parents[1]
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
NAME_LINE_RE = re.compile(r"(?m)^name:\s*['\"]?(?P<name>[a-z0-9-]+)['\"]?\s*$")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
LIFECYCLE_STATES = {"active", "rollback-only"}
PRIMARY_LEARNING_GROUP = "primary-learning"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _frontmatter_name(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{skill_md} is not valid UTF-8") from exc

    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{skill_md} has no valid YAML frontmatter block")
    name_match = NAME_LINE_RE.search(match.group("body"))
    if not name_match:
        raise ValueError(f"{skill_md} frontmatter has no simple name field")
    return name_match.group("name")


def _gitmodules(root: Path) -> dict[str, str]:
    path = root / ".gitmodules"
    parser = configparser.ConfigParser()
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (FileNotFoundError, configparser.Error) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    modules: dict[str, str] = {}
    for section in parser.sections():
        if not section.startswith("submodule "):
            continue
        module_path = parser.get(section, "path", fallback="").replace("\\", "/")
        url = parser.get(section, "url", fallback="")
        if module_path:
            modules[module_path] = url
    return modules


def _relative_directory(root: Path, raw_path: Any, label: str) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{label} must be a non-empty string")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must stay inside the repository: {raw_path!r}")
    normalized = relative.as_posix()
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the repository: {raw_path!r}") from exc
    return resolved, normalized


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_selection_groups(catalog: dict[str, Any], errors: list[str]) -> dict[str, int]:
    raw_groups = catalog.get("selection_groups")
    if not isinstance(raw_groups, dict):
        errors.append("catalog selection_groups must be an object")
        return {}

    groups: dict[str, int] = {}
    for raw_name, policy in raw_groups.items():
        try:
            name = validate_skill_name(raw_name, "selection group name")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(policy, dict):
            errors.append(f"selection_groups.{name} must be an object")
            continue
        maximum = policy.get("max_distinct_per_config")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            errors.append(
                f"selection_groups.{name}.max_distinct_per_config must be a positive integer"
            )
            continue
        groups[name] = maximum

    if groups.get(PRIMARY_LEARNING_GROUP) != 1:
        errors.append(
            "selection_groups.primary-learning.max_distinct_per_config must be 1"
        )
    return groups


def _validate_retired_names(
    catalog: dict[str, Any], errors: list[str]
) -> dict[str, str]:
    raw_retired = catalog.get("retired_names")
    if not isinstance(raw_retired, dict):
        errors.append("catalog retired_names must be an object")
        return {}

    retired: dict[str, str] = {}
    for raw_name, record in raw_retired.items():
        try:
            name = validate_skill_name(raw_name, "retired Skill name")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(record, dict):
            errors.append(f"retired_names.{name} must be an object")
            continue
        try:
            replacement = validate_skill_name(
                record.get("replacement"), f"retired_names.{name}.replacement"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        retired[name] = replacement
    return retired


def _validate_lineage(name: str, entry: dict[str, Any], errors: list[str]) -> None:
    lineage = entry.get("lineage")
    if not isinstance(lineage, list) or not lineage:
        errors.append(f"{name}: first-party lineage must be a non-empty array")
        return

    seen: set[tuple[str, str, str]] = set()
    for index, source in enumerate(lineage):
        label = f"{name}.lineage[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label} must be an object")
            continue
        repository = source.get("repository")
        path = source.get("path")
        commit = source.get("commit")
        if not _non_empty_string(repository):
            errors.append(f"{label}.repository must be a non-empty string")
        if not _non_empty_string(path):
            errors.append(f"{label}.path must be a non-empty string")
        elif Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(f"{label}.path must be repository-relative")
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            errors.append(f"{label}.commit must be a 40-character lowercase Git commit")
        if _non_empty_string(repository) and _non_empty_string(path) and isinstance(commit, str):
            identity = (repository, path, commit)
            if identity in seen:
                errors.append(f"{label} duplicates an earlier lineage source")
            seen.add(identity)


def _validate_replacement_chains(
    states: dict[str, str], retired: dict[str, str], replacements: dict[str, str]
) -> list[str]:
    errors: list[str] = []
    for source in sorted(replacements):
        cursor = source
        visited: list[str] = []
        while cursor in replacements:
            if cursor in visited:
                cycle = visited[visited.index(cursor) :] + [cursor]
                errors.append("replacement chain contains a cycle: " + " -> ".join(cycle))
                break
            visited.append(cursor)
            cursor = replacements[cursor]
        else:
            if states.get(cursor) != "active":
                errors.append(
                    f"replacement chain for {source!r} does not end at an active Skill: "
                    f"{cursor!r}"
                )
        # A cycle is already decisive; avoid also reporting it as a dangling chain.
    return errors


def validate(root: Path = ROOT) -> list[str]:
    """Return every structural catalog error found under *root*."""

    errors: list[str] = []
    try:
        catalog = _load_json(root / "catalog.json")
    except ValueError as exc:
        return [str(exc)]

    if not isinstance(catalog, dict):
        return ["catalog.json root must be an object"]
    if catalog.get("schema_version") != 2:
        errors.append("catalog schema_version must be 2")

    categories = catalog.get("categories")
    if not isinstance(categories, dict) or not categories:
        errors.append("catalog categories must be a non-empty object")
        categories = {}

    selection_groups = _validate_selection_groups(catalog, errors)
    retired = _validate_retired_names(catalog, errors)

    entries = catalog.get("skills")
    if not isinstance(entries, list):
        return errors + ["catalog skills must be an array"]

    try:
        gitmodules = _gitmodules(root)
    except ValueError as exc:
        errors.append(str(exc))
        gitmodules = {}

    names: set[str] = set()
    states: dict[str, str] = {}
    replacements: dict[str, str] = dict(retired)
    first_party_paths: set[str] = set()

    for index, entry in enumerate(entries):
        label = f"skills[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue

        try:
            name = validate_skill_name(entry.get("name"), f"{label}.name")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if name in names:
            errors.append(f"duplicate Skill name: {name}")
            continue
        names.add(name)

        category = entry.get("category")
        if not isinstance(category, str):
            errors.append(f"{name}: category must be a string")
        elif category not in categories:
            errors.append(f"{name}: unknown category {category!r}")

        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in {"first-party", "external"}:
            errors.append(f"{name}: kind must be first-party or external")

        lifecycle = entry.get("lifecycle")
        state: Any = None
        if not isinstance(lifecycle, dict):
            errors.append(f"{name}: lifecycle must be an object")
        else:
            state = lifecycle.get("state")
            if not isinstance(state, str) or state not in LIFECYCLE_STATES:
                errors.append(
                    f"{name}: lifecycle.state must be active or rollback-only"
                )
            else:
                states[name] = state

        has_replacement = "replacement" in entry
        if state == "rollback-only":
            if not has_replacement:
                errors.append(f"{name}: rollback-only Skill needs replacement")
            else:
                try:
                    replacements[name] = validate_skill_name(
                        entry.get("replacement"), f"{name}.replacement"
                    )
                except ValueError as exc:
                    errors.append(str(exc))
        elif has_replacement:
            errors.append(f"{name}: replacement is only valid for rollback-only Skills")

        groups = entry.get("groups")
        if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
            errors.append(f"{name}: groups must be a string array")
        else:
            if len(groups) != len(set(groups)):
                errors.append(f"{name}: groups must not contain duplicates")
            for group in groups:
                if group not in selection_groups:
                    errors.append(f"{name}: unknown selection group {group!r}")

        normalized_path: str | None = None
        skill_dir: Path | None = None
        try:
            skill_dir, normalized_path = _relative_directory(
                root, entry.get("path"), f"{name}.path"
            )
        except ValueError as exc:
            errors.append(str(exc))

        if skill_dir is not None and normalized_path is not None:
            skill_md = skill_dir / "SKILL.md"
            if not skill_dir.is_dir():
                errors.append(f"{name}: Skill directory does not exist: {normalized_path}")
            elif not skill_md.is_file():
                errors.append(f"{name}: SKILL.md does not exist: {normalized_path}/SKILL.md")
            else:
                try:
                    declared_name = _frontmatter_name(skill_md)
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    if declared_name != name:
                        errors.append(
                            f"{name}: directory/catalog name differs from frontmatter name "
                            f"{declared_name!r}"
                        )

        if kind == "first-party":
            if normalized_path is not None:
                expected = f"skills/{name}"
                if normalized_path != expected:
                    errors.append(f"{name}: first-party path must be {expected}")
                first_party_paths.add(normalized_path)
            if "origin" in entry:
                errors.append(f"{name}: first-party provenance must use lineage, not origin")
            _validate_lineage(name, entry, errors)
        elif kind == "external":
            if "lineage" in entry:
                errors.append(f"{name}: external provenance must use origin, not lineage")
            origin = entry.get("origin")
            if not isinstance(origin, dict):
                errors.append(f"{name}: external origin must be an object")
            elif normalized_path is not None:
                submodule = origin.get("submodule")
                repository_url = origin.get("repository_url")
                if not isinstance(submodule, str) or submodule not in gitmodules:
                    errors.append(f"{name}: unregistered submodule {submodule!r}")
                elif not (
                    normalized_path == submodule
                    or normalized_path.startswith(submodule.rstrip("/") + "/")
                ):
                    errors.append(f"{name}: path is outside its declared submodule")
                elif gitmodules[submodule] != repository_url:
                    errors.append(
                        f"{name}: catalog URL {repository_url!r} differs from .gitmodules "
                        f"URL {gitmodules[submodule]!r}"
                    )

        consumers = entry.get("consumers")
        if not isinstance(consumers, list) or not consumers or not all(
            isinstance(item, str) and item for item in consumers
        ):
            errors.append(f"{name}: consumers must be a non-empty string array")

    overlap = sorted(names & set(retired))
    if overlap:
        errors.append(
            "active/rollback-only and retired Skill names overlap: " + ", ".join(overlap)
        )

    errors.extend(_validate_replacement_chains(states, retired, replacements))

    skills_root = root / "skills"
    physical_first_party = (
        {
            f"skills/{path.name}"
            for path in skills_root.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        if skills_root.is_dir()
        else set()
    )

    unregistered = sorted(physical_first_party - first_party_paths)
    missing = sorted(first_party_paths - physical_first_party)
    if unregistered:
        errors.append("unregistered first-party Skill directories: " + ", ".join(unregistered))
    if missing:
        errors.append("cataloged first-party Skill directories are missing: " + ", ".join(missing))

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    catalog = _load_json(ROOT / "catalog.json")
    first_party = sum(item["kind"] == "first-party" for item in catalog["skills"])
    external = sum(item["kind"] == "external" for item in catalog["skills"])
    print(
        f"Catalog is valid: {len(catalog['skills'])} Skills "
        f"({first_party} first-party, {external} official external)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
