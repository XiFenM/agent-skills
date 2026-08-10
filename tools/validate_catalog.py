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


def validate(root: Path = ROOT) -> list[str]:
    """Return every structural catalog error found under *root*."""

    errors: list[str] = []
    try:
        catalog = _load_json(root / "catalog.json")
    except ValueError as exc:
        return [str(exc)]

    if not isinstance(catalog, dict):
        return ["catalog.json root must be an object"]
    if catalog.get("schema_version") != 1:
        errors.append("catalog schema_version must be 1")

    categories = catalog.get("categories")
    if not isinstance(categories, dict) or not categories:
        errors.append("catalog categories must be a non-empty object")
        categories = {}

    entries = catalog.get("skills")
    if not isinstance(entries, list):
        return errors + ["catalog skills must be an array"]

    try:
        gitmodules = _gitmodules(root)
    except ValueError as exc:
        errors.append(str(exc))
        gitmodules = {}

    names: set[str] = set()
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
        if category not in categories:
            errors.append(f"{name}: unknown category {category!r}")

        kind = entry.get("kind")
        if kind not in {"first-party", "external"}:
            errors.append(f"{name}: kind must be first-party or external")

        try:
            skill_dir, normalized_path = _relative_directory(
                root, entry.get("path"), f"{name}.path"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

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

        origin = entry.get("origin")
        if not isinstance(origin, dict):
            errors.append(f"{name}: origin must be an object")
            continue

        if kind == "first-party":
            expected = f"skills/{name}"
            if normalized_path != expected:
                errors.append(f"{name}: first-party path must be {expected}")
            first_party_paths.add(normalized_path)
            if not origin.get("repository") or not origin.get("path"):
                errors.append(f"{name}: first-party origin needs repository and path")
            commit = origin.get("commit")
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append(f"{name}: first-party origin needs a 40-character commit")
        elif kind == "external":
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

    skills_root = root / "skills"
    physical_first_party = {
        f"skills/{path.name}"
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    } if skills_root.is_dir() else set()

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
