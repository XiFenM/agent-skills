#!/usr/bin/env python3
"""Materialize selected central Skills into agent discovery directories.

The script intentionally uses only Python's standard library. It never updates Git,
fetches a remote, or overwrites a target that it cannot prove it owns.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

try:
    from .skill_names import validate_skill_name
except ImportError:  # Direct execution: python tools/materialize_skills.py
    from skill_names import validate_skill_name


CENTRAL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_FILE = "catalog.json"
DEFAULT_CONFIG = ".agent-skills.json"
STATE_FILE = ".agent-skills.state.json"
LOCK_FILE = ".agent-skills.lock"
MARKER_FILE = ".agent-skills-managed.json"
CONTEXT_FILE = ".agent-skills-context.json"
TARGET_ROOTS = {
    "codex": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
}
IGNORED_DIRECTORY_NAMES = {".git", ".pytest_cache", ".venv", "__pycache__"}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo"}
HEX_DIGEST_LENGTH = 64
LIFECYCLE_STATES = {"active", "rollback-only"}
PRIMARY_LEARNING_GROUP = "primary-learning"


class SyncError(RuntimeError):
    """Raised when synchronization cannot proceed safely."""


@dataclass(frozen=True)
class DesiredTarget:
    skill: str
    host: str
    source: Path
    source_relative: str
    target: Path
    target_relative: str
    digest: str
    source_digest: str
    context_digest: str | None
    context: dict[str, Any] | None


@dataclass(frozen=True)
class ConsumerConfig:
    selected: dict[str, list[str]]
    source_relative: str
    config_relative: str
    config_digest: str
    contexts: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class CatalogPolicy:
    skills: dict[str, dict[str, Any]]
    selection_groups: dict[str, int]
    retired_names: dict[str, str]
    replacements: dict[str, str]


def _path_present(path: Path) -> bool:
    """Use lstat semantics so broken links are still treated as present."""

    return os.path.lexists(os.fspath(path))


def _is_link_or_junction(path: Path) -> bool:
    if not _path_present(path):
        return False
    if path.is_symlink():
        return True
    junction_check = getattr(path, "is_junction", None)
    if junction_check is not None:
        try:
            if junction_check():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _absolute(path: Path) -> Path:
    """Return a normalized absolute path without resolving filesystem links."""

    return Path(os.path.abspath(os.fspath(path)))


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        pass
    return os.path.normcase(os.fspath(_absolute(left))) == os.path.normcase(
        os.fspath(_absolute(right))
    )


def _load_json(path: Path, *, missing: Any = None) -> Any:
    if not _path_present(path):
        if missing is not None:
            return missing
        raise SyncError(f"missing file: {path}")
    return _load_json_with_bytes(path)[0]


def _load_json_with_bytes(path: Path) -> tuple[Any, bytes]:
    if _is_link_or_junction(path) or not path.is_file():
        raise SyncError(f"expected a regular JSON file: {path}")
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), raw
    except json.JSONDecodeError as exc:
        raise SyncError(f"invalid JSON in {path}: {exc}") from exc
    except UnicodeError as exc:
        raise SyncError(f"JSON file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise SyncError(f"cannot read JSON file {path}: {exc}") from exc


def _assert_components_are_real(base: Path, relative: Path, label: str) -> None:
    current = _absolute(base)
    for part in relative.parts:
        current /= part
        if _path_present(current) and _is_link_or_junction(current):
            raise SyncError(f"{label} contains a symlink or junction: {current}")


def _resolve_under(base: Path, raw_path: Any, label: str) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path:
        raise SyncError(f"{label} must be a non-empty relative path")
    if "\\" in raw_path:
        raise SyncError(f"{label} must use forward slashes: {raw_path!r}")
    posix = PurePosixPath(raw_path)
    if (
        posix.is_absolute()
        or ".." in posix.parts
        or posix.as_posix() != raw_path
        or raw_path in {"", "."}
    ):
        raise SyncError(f"{label} must stay inside {base}: {raw_path!r}")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
    for part in posix.parts:
        if (
            any(character in part for character in ':<>"|?*')
            or any(ord(character) < 32 for character in part)
            or part.endswith((".", " "))
            or part.split(".", 1)[0].lower() in reserved
        ):
            raise SyncError(
                f"{label} contains a platform-unsafe path component: {raw_path!r}"
            )
    relative = Path(*posix.parts)

    normalized_base = _absolute(base)
    candidate = _absolute(normalized_base / relative)
    try:
        common = Path(os.path.commonpath([normalized_base, candidate]))
    except ValueError as exc:
        raise SyncError(f"{label} escapes {base}: {raw_path!r}") from exc
    if not _same_path(common, normalized_base):
        raise SyncError(f"{label} escapes {base}: {raw_path!r}")

    _assert_components_are_real(normalized_base, relative, label)
    return candidate, relative.as_posix()


def _relative_paths_overlap(left: str, right: str) -> bool:
    # Treat path identity with the strictest supported consumer semantics.
    # A config that is disjoint only by case on Linux would alias protected
    # inputs after the same repository is used on Windows.
    left_path = PurePosixPath(
        *(part.casefold() for part in PurePosixPath(left).parts)
    )
    right_path = PurePosixPath(
        *(part.casefold() for part in PurePosixPath(right).parts)
    )
    if left_path == right_path:
        return True
    try:
        left_path.relative_to(right_path)
        return True
    except ValueError:
        pass
    try:
        right_path.relative_to(left_path)
        return True
    except ValueError:
        return False


def _assert_context_writes_disjoint(
    contexts: dict[str, dict[str, Any]],
    protected_roots: dict[str, str],
) -> None:
    for skill, wrapper in sorted(contexts.items()):
        for write_path in wrapper["allowlist"]["write_paths"]:
            for protected_path, protected_label in sorted(protected_roots.items()):
                if _relative_paths_overlap(write_path, protected_path):
                    raise SyncError(
                        f"{skill} write path {write_path!r} overlaps protected "
                        f"{protected_label} {protected_path!r}"
                    )


def _walk_regular_files(
    root: Path, *, managed_copy: bool = False
) -> Iterator[tuple[Path, Path]]:
    if not _path_present(root) or _is_link_or_junction(root) or not root.is_dir():
        raise SyncError(f"Skill root must be a real directory: {root}")

    def raise_walk_error(error: OSError) -> None:
        raise error

    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False, onerror=raise_walk_error
    ):
        current = Path(directory)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = current / name
            if name in IGNORED_DIRECTORY_NAMES:
                continue
            if _is_link_or_junction(path):
                raise SyncError(f"Skill trees may not contain links or junctions: {path}")
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise SyncError(f"cannot inspect Skill directory {path}: {exc}") from exc
            if not stat.S_ISDIR(mode):
                raise SyncError(f"non-directory entry found in Skill tree: {path}")
            kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            path = current / name
            if Path(name).suffix in IGNORED_FILE_SUFFIXES:
                continue
            if name == MARKER_FILE:
                if managed_copy:
                    continue
                raise SyncError(f"source Skill contains reserved marker file: {path}")
            if name == CONTEXT_FILE and not managed_copy:
                raise SyncError(f"source Skill contains reserved context file: {path}")
            if _is_link_or_junction(path):
                raise SyncError(f"Skill trees may not contain links or junctions: {path}")
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise SyncError(f"cannot inspect Skill file {path}: {exc}") from exc
            if not stat.S_ISREG(mode):
                raise SyncError(f"Skill trees may contain only regular files: {path}")
            yield path, path.relative_to(root)


def _digest_entries(entries: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(entries, key=lambda item: item[0]):
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def skill_digest(root: Path, *, managed_copy: bool = False) -> str:
    entries = [
        (relative.as_posix(), path.read_bytes())
        for path, relative in _walk_regular_files(root, managed_copy=managed_copy)
    ]
    return _digest_entries(entries)


def _skill_digest_with_context(root: Path, context_bytes: bytes | None) -> str:
    entries = [
        (relative.as_posix(), path.read_bytes())
        for path, relative in _walk_regular_files(root)
    ]
    if context_bytes is not None:
        entries.append((CONTEXT_FILE, context_bytes))
    return _digest_entries(entries)


def _git_worktree_root(path: Path) -> Path:
    current = _absolute(path)
    while True:
        if _path_present(current / ".git"):
            return current
        if current.parent == current:
            raise SyncError(f"Skill source is not inside a Git worktree: {path}")
        current = current.parent


def _assert_source_is_tracked(source: Path, expected_worktree: Path) -> None:
    worktree = _git_worktree_root(source)
    if not _same_path(worktree, expected_worktree):
        raise SyncError(
            f"Skill source is bound to unexpected Git worktree: {worktree}; "
            f"expected {expected_worktree}"
        )
    reported = _absolute(Path(_run_git(worktree, "rev-parse", "--show-toplevel").strip()))
    if not _same_path(worktree, reported):
        raise SyncError(
            f"Skill source Git boundary is ambiguous: {worktree} != {reported}"
        )
    try:
        relative_root = source.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise SyncError(f"Skill source escapes its Git worktree: {source}") from exc
    tracked, gitlinks, intent_to_add = _git_index(worktree)
    prefix = "" if relative_root == "." else relative_root.rstrip("/") + "/"
    tracked_under = {
        path for path in tracked if not prefix or path.startswith(prefix)
    }
    gitlinks_under = {
        path for path in gitlinks if not prefix or path.startswith(prefix)
    }
    intent_under = {
        path for path in intent_to_add if not prefix or path.startswith(prefix)
    }
    if gitlinks_under:
        raise SyncError(
            f"Skill source contains nested Git submodules: {', '.join(sorted(gitlinks_under))}"
        )
    if intent_under:
        raise SyncError(
            "Skill source contains intent-to-add paths: "
            + ", ".join(sorted(intent_under)[:5])
        )
    present = {
        prefix + relative.as_posix() if prefix else relative.as_posix()
        for _path, relative in _walk_regular_files(source)
    }
    untracked = sorted(present - tracked_under)
    missing = sorted(tracked_under - present)
    if untracked or missing:
        details: list[str] = []
        if untracked:
            details.append("untracked=" + ", ".join(untracked[:5]))
        if missing:
            details.append("missing-or-excluded=" + ", ".join(missing[:5]))
        raise SyncError(
            f"Skill source must match its Git index exactly ({'; '.join(details)})"
        )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in IGNORED_DIRECTORY_NAMES
        or Path(name).suffix in IGNORED_FILE_SUFFIXES
    }


def _validated_name(value: Any, label: str) -> str:
    try:
        return validate_skill_name(value, label)
    except ValueError as exc:
        raise SyncError(str(exc)) from exc


def _catalog_policy(central_root: Path) -> CatalogPolicy:
    catalog = _load_json(central_root / CATALOG_FILE)
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 2:
        raise SyncError("unsupported or invalid catalog schema")

    raw_selection_groups = catalog.get("selection_groups")
    if not isinstance(raw_selection_groups, dict):
        raise SyncError("catalog selection_groups must be an object")
    selection_groups: dict[str, int] = {}
    for raw_name, raw_policy in raw_selection_groups.items():
        name = _validated_name(raw_name, "selection group name")
        if not isinstance(raw_policy, dict):
            raise SyncError(f"selection group {name!r} policy must be an object")
        maximum = raw_policy.get("max_distinct_per_config")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise SyncError(
                f"selection group {name!r} max_distinct_per_config must be a "
                "positive integer"
            )
        selection_groups[name] = maximum
    if selection_groups.get(PRIMARY_LEARNING_GROUP) != 1:
        raise SyncError(
            "catalog primary-learning selection group must have "
            "max_distinct_per_config 1"
        )

    raw_retired = catalog.get("retired_names")
    if not isinstance(raw_retired, dict):
        raise SyncError("catalog retired_names must be an object")
    retired_names: dict[str, str] = {}
    for raw_name, raw_record in raw_retired.items():
        name = _validated_name(raw_name, "retired Skill name")
        if not isinstance(raw_record, dict):
            raise SyncError(f"retired Skill {name!r} record must be an object")
        replacement = _validated_name(
            raw_record.get("replacement"), f"retired Skill {name!r} replacement"
        )
        retired_names[name] = replacement

    entries = catalog.get("skills")
    if not isinstance(entries, list):
        raise SyncError("catalog skills must be an array")

    index: dict[str, dict[str, Any]] = {}
    replacements: dict[str, str] = dict(retired_names)
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SyncError(f"catalog Skill entry {position} must be an object")
        name = _validated_name(entry.get("name"), f"catalog Skill {position} name")
        if name in index:
            raise SyncError(f"catalog contains duplicate Skill {name!r}")
        kind = entry.get("kind")
        if kind not in {"first-party", "external"}:
            raise SyncError(
                f"catalog Skill {name!r} kind must be first-party or external"
            )
        if kind == "external":
            origin = entry.get("origin")
            if not isinstance(origin, dict) or not isinstance(
                origin.get("submodule"), str
            ):
                raise SyncError(
                    f"catalog external Skill {name!r} must declare origin.submodule"
                )

        lifecycle = entry.get("lifecycle")
        state = lifecycle.get("state") if isinstance(lifecycle, dict) else None
        if not isinstance(state, str) or state not in LIFECYCLE_STATES:
            raise SyncError(
                f"catalog Skill {name!r} lifecycle.state must be active or rollback-only"
            )
        if state == "rollback-only":
            replacements[name] = _validated_name(
                entry.get("replacement"), f"catalog Skill {name!r} replacement"
            )
        elif "replacement" in entry:
            raise SyncError(
                f"catalog active Skill {name!r} must not declare a replacement"
            )

        groups = entry.get("groups")
        if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
            raise SyncError(f"catalog Skill {name!r} groups must be a string array")
        if len(groups) != len(set(groups)):
            raise SyncError(f"catalog Skill {name!r} groups contain duplicates")
        unknown_groups = sorted(set(groups) - set(selection_groups))
        if unknown_groups:
            raise SyncError(
                f"catalog Skill {name!r} uses unknown selection groups: "
                + ", ".join(unknown_groups)
            )

        context_policy = entry.get("context")
        if context_policy is not None:
            if entry.get("kind") != "first-party":
                raise SyncError(
                    f"catalog Skill {name!r} context validators are first-party only"
                )
            if not isinstance(context_policy, dict) or set(context_policy) != {
                "validator"
            }:
                raise SyncError(
                    f"catalog Skill {name!r} context must contain only validator"
                )
            validator = context_policy.get("validator")
            if not isinstance(validator, str) or not validator.endswith(".py"):
                raise SyncError(
                    f"catalog Skill {name!r} context.validator must be a Python path"
                )
            validator_path = Path(validator)
            if validator_path.is_absolute() or ".." in validator_path.parts:
                raise SyncError(
                    f"catalog Skill {name!r} context.validator must stay in its Skill"
                )
        index[name] = entry

    overlap = sorted(set(index) & set(retired_names))
    if overlap:
        raise SyncError(
            "catalog Skill and retired names overlap: " + ", ".join(overlap)
        )

    policy = CatalogPolicy(
        skills=index,
        selection_groups=selection_groups,
        retired_names=retired_names,
        replacements=replacements,
    )
    for name in sorted(replacements):
        _active_replacement(name, policy)
    return policy


def _catalog_index(central_root: Path) -> dict[str, dict[str, Any]]:
    """Return the schema-v2 Skill index for callers that only need entries."""

    return _catalog_policy(central_root).skills


def _active_replacement(name: str, catalog: CatalogPolicy) -> str:
    """Resolve a rollback/retired name to its final active Skill."""

    cursor = name
    visited: list[str] = []
    while True:
        if cursor in visited:
            cycle = visited[visited.index(cursor) :] + [cursor]
            raise SyncError(
                "catalog replacement chain contains a cycle: " + " -> ".join(cycle)
            )
        visited.append(cursor)

        if cursor in catalog.retired_names:
            cursor = catalog.retired_names[cursor]
            continue

        entry = catalog.skills.get(cursor)
        if entry is None:
            raise SyncError(
                f"catalog replacement chain for {name!r} is dangling at {cursor!r}"
            )
        if entry["lifecycle"]["state"] == "active":
            return cursor
        cursor = catalog.replacements[cursor]


def _file_under(repo: Path, path: Path, label: str) -> tuple[Path, str]:
    repo = _absolute(repo)
    path = _absolute(path)
    try:
        common = Path(os.path.commonpath([repo, path]))
    except ValueError as exc:
        raise SyncError(f"{label} escapes {repo}: {path}") from exc
    if not _same_path(common, repo):
        raise SyncError(f"{label} escapes {repo}: {path}")
    relative = Path(os.path.relpath(path, repo))
    _assert_components_are_real(repo, relative, label)
    if not _path_present(path) or _is_link_or_junction(path) or not path.is_file():
        raise SyncError(f"{label} must be a regular file inside {repo}: {path}")
    return path, relative.as_posix()


def _normalized_selected(selected: Any, config_path: Path) -> dict[str, list[str]]:
    if not isinstance(selected, dict):
        raise SyncError(f"{config_path}.skills must be an object")
    normalized: dict[str, list[str]] = {}
    for raw_name, hosts in selected.items():
        name = _validated_name(raw_name, "selected Skill name")
        if not isinstance(hosts, list) or not hosts:
            raise SyncError(f"{name}: host list must be non-empty")
        if not all(isinstance(host, str) for host in hosts):
            raise SyncError(f"{name}: every host must be a string")
        if len(hosts) != len(set(hosts)):
            raise SyncError(f"{name}: duplicate host in {hosts!r}")
        unknown_hosts = sorted(set(hosts) - set(TARGET_ROOTS))
        if unknown_hosts:
            raise SyncError(f"{name}: unknown hosts: {', '.join(unknown_hosts)}")
        normalized[name] = sorted(hosts)
    return normalized


def _git_index(repo: Path) -> tuple[set[str], set[str], set[str]]:
    output = _run_git(repo, "-c", "core.quotePath=false", "ls-files", "--stage", "-z")
    tracked: set[str] = set()
    gitlinks: set[str] = set()
    for raw_record in output.split("\0"):
        if not raw_record:
            continue
        try:
            metadata, raw_path = raw_record.split("\t", 1)
            mode, _object_name, stage = metadata.split()
        except ValueError as exc:
            raise SyncError(f"Git returned malformed index data for {repo}") from exc
        normalized = Path(raw_path).as_posix()
        if stage != "0":
            raise SyncError(
                f"Git index has an unresolved merge stage for {normalized}: {stage}"
            )
        if mode == "160000":
            gitlinks.add(normalized)
        else:
            tracked.add(normalized)
    intent_to_add = {
        Path(path).as_posix()
        for path in _run_git(
            repo,
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            "--diff-filter=A",
            "-z",
        ).split("\0")
        if path
    }
    return tracked, gitlinks, intent_to_add


def _crosses_gitlink(relative: str, gitlinks: set[str]) -> bool:
    return any(relative == link or relative.startswith(link + "/") for link in gitlinks)


def _declared_path(
    repo: Path,
    raw_path: Any,
    label: str,
    *,
    gitlinks: set[str],
) -> tuple[Path, str]:
    path, relative = _resolve_under(repo, raw_path, label)
    if _crosses_gitlink(relative, gitlinks):
        raise SyncError(f"{label} crosses a Git submodule: {relative}")
    return path, relative


def _tracked_file(
    repo: Path,
    raw_path: Any,
    label: str,
    *,
    tracked: set[str],
    gitlinks: set[str],
    intent_to_add: set[str],
) -> str:
    path, relative = _declared_path(repo, raw_path, label, gitlinks=gitlinks)
    if relative not in tracked:
        raise SyncError(f"{label} must be a Git tracked regular file: {relative}")
    if relative in intent_to_add:
        raise SyncError(f"{label} must not be intent-to-add: {relative}")
    if not _path_present(path) or _is_link_or_junction(path) or not path.is_file():
        raise SyncError(f"{label} must be a real regular file: {relative}")
    _validate_utf8_file(path, label)
    return relative


def _validate_utf8_file(path: Path, label: str) -> None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            while handle.read(1024 * 1024):
                pass
    except UnicodeError as exc:
        raise SyncError(f"{label} must be valid UTF-8: {path}") from exc
    except OSError as exc:
        raise SyncError(f"cannot read {label} as UTF-8: {path}: {exc}") from exc


def _tracked_collection(
    repo: Path,
    raw_path: Any,
    label: str,
    *,
    tracked: set[str],
    gitlinks: set[str],
    intent_to_add: set[str],
) -> tuple[str, list[str]]:
    path, relative = _declared_path(repo, raw_path, label, gitlinks=gitlinks)
    if not _path_present(path) or _is_link_or_junction(path) or not path.is_dir():
        raise SyncError(f"{label} must be a real directory: {relative}")
    prefix = relative.rstrip("/") + "/"
    members = sorted(item for item in tracked if item.startswith(prefix))
    if not members:
        raise SyncError(
            f"{label} must use the Git index's exact path casing and contain at "
            f"least one tracked member: {relative}"
        )
    intent_members = sorted(item for item in intent_to_add if item.startswith(prefix))
    if intent_members:
        raise SyncError(
            f"{label} contains intent-to-add members: {', '.join(intent_members[:5])}"
        )
    for member in members:
        member_path, normalized = _declared_path(
            repo, member, f"{label} member", gitlinks=gitlinks
        )
        if normalized != member or not member_path.is_file():
            raise SyncError(f"{label} contains a non-regular tracked entry: {member}")
        _validate_utf8_file(member_path, f"{label} member")
    return relative, members


def _write_path(
    repo: Path,
    raw_path: Any,
    label: str,
    *,
    tracked: set[str],
    gitlinks: set[str],
    intent_to_add: set[str],
) -> str:
    path, relative = _declared_path(repo, raw_path, label, gitlinks=gitlinks)
    if _path_present(path):
        if _is_link_or_junction(path):
            raise SyncError(f"{label} must not be a link or junction: {relative}")
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise SyncError(f"{label} is a special filesystem entry: {relative}")
        if stat.S_ISREG(mode):
            if relative not in tracked:
                raise SyncError(
                    f"{label} existing file must be Git tracked: {relative}"
                )
            if relative in intent_to_add:
                raise SyncError(f"{label} must not be intent-to-add: {relative}")
            _validate_utf8_file(path, label)
    return relative


def _repository_config(
    repo: Path,
    path: Path,
    relative: str,
    *,
    tracked: set[str],
    gitlinks: set[str],
) -> tuple[dict[str, Any], str]:
    if relative not in tracked:
        raise SyncError(f"repository config must be Git tracked: {relative}")
    raw, raw_bytes = _load_json_with_bytes(path)
    allowed = {"schema", "repository_id", "language", "timezone", "facts"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise SyncError(f"{relative} has unknown repository config fields")
    if raw.get("schema") != "agent-skills.repository/v1":
        raise SyncError(f"{relative}.schema must be agent-skills.repository/v1")
    repository_id = _validated_name(raw.get("repository_id"), "repository_id")
    language = raw.get("language")
    timezone = raw.get("timezone")
    if language is not None and (not isinstance(language, str) or not language):
        raise SyncError(f"{relative}.language must be a non-empty string")
    if timezone is not None and (not isinstance(timezone, str) or not timezone):
        raise SyncError(f"{relative}.timezone must be a non-empty string")
    facts = raw.get("facts", {})
    if not isinstance(facts, dict):
        raise SyncError(f"{relative}.facts must be an object")
    normalized_facts: dict[str, dict[str, str]] = {}
    for raw_id, raw_fact in facts.items():
        fact_id = _validated_name(raw_id, "repository fact ID")
        if not isinstance(raw_fact, dict) or not set(raw_fact) <= {
            "path",
            "section",
            "description",
        }:
            raise SyncError(f"repository fact {fact_id!r} has unknown fields")
        _fact_absolute, fact_path = _declared_path(
            repo,
            raw_fact.get("path"),
            f"repository fact {fact_id!r}.path",
            gitlinks=gitlinks,
        )
        normalized_fact = {"path": fact_path}
        for field in ("section", "description"):
            value = raw_fact.get(field)
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise SyncError(
                        f"repository fact {fact_id!r}.{field} must be a non-empty string"
                    )
                normalized_fact[field] = value
        normalized_facts[fact_id] = normalized_fact
    normalized: dict[str, Any] = {
        "schema": "agent-skills.repository/v1",
        "repository_id": repository_id,
        "facts": dict(sorted(normalized_facts.items())),
    }
    if language is not None:
        normalized["language"] = language
    if timezone is not None:
        normalized["timezone"] = timezone
    return normalized, _sha256_bytes(raw_bytes)


def _context_validator(skill_root: Path, entry: dict[str, Any], name: str):
    policy = entry.get("context")
    if not isinstance(policy, dict):
        raise SyncError(f"Skill {name!r} does not support consumer context")
    validator_path, validator_relative = _resolve_under(
        skill_root,
        policy.get("validator"),
        f"context validator for {name}",
    )
    if (
        not _path_present(validator_path)
        or _is_link_or_junction(validator_path)
        or not validator_path.is_file()
    ):
        raise SyncError(
            f"context validator for {name!r} is unavailable: {validator_relative}"
        )
    module_name = f"_agent_skills_context_{name.replace('-', '_')}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, validator_path)
    if spec is None or spec.loader is None:
        raise SyncError(f"cannot load context validator for {name!r}")
    module = importlib.util.module_from_spec(spec)
    old_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SyncError(f"context validator for {name!r} failed to load: {exc}") from exc
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
        sys.dont_write_bytecode = old_dont_write_bytecode
    validator = getattr(module, "validate_materialized_context", None)
    if not callable(validator):
        raise SyncError(
            f"context validator for {name!r} must expose validate_materialized_context"
        )
    return validator


def _materialized_context(
    repo: Path,
    central_root: Path,
    name: str,
    entry: dict[str, Any],
    repository: dict[str, Any],
    repository_relative: str,
    repository_digest: str,
    skill_config_path: Path,
    skill_config_relative: str,
    *,
    tracked: set[str],
    gitlinks: set[str],
    intent_to_add: set[str],
) -> tuple[dict[str, Any], list[str]]:
    if skill_config_relative not in tracked:
        raise SyncError(f"Skill config must be Git tracked: {skill_config_relative}")
    if skill_config_relative in intent_to_add:
        raise SyncError(f"Skill config must not be intent-to-add: {skill_config_relative}")
    skill_config, skill_config_bytes = _load_json_with_bytes(skill_config_path)
    if not isinstance(skill_config, dict):
        raise SyncError(f"{skill_config_relative} must be a JSON object")
    if skill_config.get("skill") != name:
        raise SyncError(
            f"{skill_config_relative}.skill must match selected Skill {name!r}"
        )
    schema = skill_config.get("schema")
    if not isinstance(schema, str) or not schema:
        raise SyncError(f"{skill_config_relative}.schema must be a non-empty string")

    skill_root, _ = _resolve_under(
        central_root, entry.get("path"), f"catalog path for {name}"
    )
    validator = _context_validator(skill_root, entry, name)
    try:
        result = validator(deepcopy(repository), deepcopy(skill_config))
    except Exception as exc:
        raise SyncError(f"invalid context config for {name!r}: {exc}") from exc
    expected_keys = {"context", "tracked_files", "tracked_collections", "write_paths"}
    if not isinstance(result, dict) or set(result) != expected_keys:
        raise SyncError(
            f"context validator for {name!r} must return exactly "
            + ", ".join(sorted(expected_keys))
        )
    if not isinstance(result["context"], dict):
        raise SyncError(f"context validator for {name!r} context must be an object")
    for field in ("tracked_files", "tracked_collections", "write_paths"):
        values = result[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SyncError(f"context validator for {name!r} {field} must be a string array")
        if len(values) != len(set(values)):
            raise SyncError(f"context validator for {name!r} {field} has duplicates")

    explicit_tracked = {
        _tracked_file(
            repo,
            raw_path,
            f"{name} tracked file",
            tracked=tracked,
            gitlinks=gitlinks,
            intent_to_add=intent_to_add,
        )
        for raw_path in result["tracked_files"]
    }
    declared_tracked = sorted(explicit_tracked)
    normalized_collections: list[str] = []
    for raw_path in result["tracked_collections"]:
        collection, members = _tracked_collection(
            repo,
            raw_path,
            f"{name} tracked collection",
            tracked=tracked,
            gitlinks=gitlinks,
            intent_to_add=intent_to_add,
        )
        normalized_collections.append(collection)
        explicit_tracked.update(members)
    normalized_writes = sorted(
        {
            _write_path(
                repo,
                raw_path,
                f"{name} write path",
                tracked=tracked,
                gitlinks=gitlinks,
                intent_to_add=intent_to_add,
            )
            for raw_path in result["write_paths"]
        }
    )

    skill_config_digest = _sha256_bytes(skill_config_bytes)
    wrapper = {
        "version": 1,
        "manager": "agent-skills",
        "skill": name,
        "repository_id": repository["repository_id"],
        "sources": {
            "repository": {
                "path": repository_relative,
                "digest": repository_digest,
            },
            "skill": {
                "path": skill_config_relative,
                "digest": skill_config_digest,
            },
        },
        "context": result["context"],
        "allowlist": {
            "tracked_files": sorted(explicit_tracked),
            "tracked_collections": sorted(normalized_collections),
            "write_paths": normalized_writes,
        },
    }
    try:
        _json_bytes(wrapper)
    except (TypeError, ValueError) as exc:
        raise SyncError(f"context validator for {name!r} returned non-JSON data") from exc
    return wrapper, declared_tracked


def _read_config(
    repo: Path,
    config_path: Path,
    central_root: Path,
    catalog: CatalogPolicy,
) -> ConsumerConfig:
    config_path, config_relative = _file_under(repo, config_path, "consumer config")
    config, config_bytes = _load_json_with_bytes(config_path)
    if not isinstance(config, dict):
        raise SyncError(f"{config_path} must be a JSON object")
    version = config.get("version")
    if version == 1:
        if set(config) != {"version", "source", "skills"}:
            raise SyncError(f"{config_path} version 1 has unknown fields")
    elif version == 2:
        if set(config) != {"version", "source", "skills", "config"}:
            raise SyncError(f"{config_path} version 2 has unknown fields")
    else:
        raise SyncError(f"{config_path} must use version 1 or 2")

    configured_source, source_relative = _resolve_under(
        repo, config.get("source"), f"{config_path.name}.source"
    )
    if not _same_path(configured_source, central_root):
        raise SyncError(
            f"configured source resolves to {configured_source}, but this tool is running "
            f"from {_absolute(central_root)}"
        )
    selected = _normalized_selected(config.get("skills"), config_path)
    contexts: dict[str, dict[str, Any]] = {}
    declared_tracked_by_skill: dict[str, list[str]] = {}
    protected_context_paths: dict[str, str] = {
        config_relative: "consumer config",
        STATE_FILE: "materializer state",
        LOCK_FILE: "materializer lock",
    }

    if version == 2:
        raw_context = config.get("config")
        if not isinstance(raw_context, dict) or set(raw_context) != {
            "repository",
            "skills",
        }:
            raise SyncError(
                f"{config_path}.config must contain exactly repository and skills"
            )
        raw_skill_configs = raw_context.get("skills")
        if not isinstance(raw_skill_configs, dict):
            raise SyncError(f"{config_path}.config.skills must be an object")
        configured_names = {
            _validated_name(name, "configured Skill context name")
            for name in raw_skill_configs
        }
        if configured_names != set(raw_skill_configs):
            raise SyncError(f"{config_path}.config.skills contains invalid names")
        unselected = sorted(configured_names - set(selected))
        if unselected:
            raise SyncError(
                "Skill context configured for unselected Skills: " + ", ".join(unselected)
            )
        tracked, gitlinks, intent_to_add = _git_index(repo)
        if config_relative not in tracked:
            raise SyncError(f"version 2 consumer config must be Git tracked: {config_relative}")
        if config_relative in intent_to_add:
            raise SyncError(
                f"version 2 consumer config must not be intent-to-add: {config_relative}"
            )
        if configured_names:
            repository_path, repository_relative = _declared_path(
                repo,
                raw_context.get("repository"),
                "repository config",
                gitlinks=gitlinks,
            )
            if (
                not _path_present(repository_path)
                or _is_link_or_junction(repository_path)
                or not repository_path.is_file()
            ):
                raise SyncError(
                    f"repository config must be a regular file: {repository_relative}"
                )
            if repository_relative in intent_to_add:
                raise SyncError(
                    f"repository config must not be intent-to-add: {repository_relative}"
                )
            repository, repository_digest = _repository_config(
                repo,
                repository_path,
                repository_relative,
                tracked=tracked,
                gitlinks=gitlinks,
            )
            protected_context_paths[repository_relative] = "repository config"
            for name in sorted(configured_names):
                entry = catalog.skills.get(name)
                if entry is None:
                    raise SyncError(f"unknown Skill context in {config_path.name}: {name}")
                skill_config_path, skill_config_relative = _declared_path(
                    repo,
                    raw_skill_configs[name],
                    f"config for {name}",
                    gitlinks=gitlinks,
                )
                if (
                    not _path_present(skill_config_path)
                    or _is_link_or_junction(skill_config_path)
                    or not skill_config_path.is_file()
                ):
                    raise SyncError(
                        f"Skill config must be a regular file: {skill_config_relative}"
                    )
                protected_context_paths[skill_config_relative] = (
                    f"Skill config for {name!r}"
                )
                context, declared_tracked = _materialized_context(
                    repo,
                    central_root,
                    name,
                    entry,
                    repository,
                    repository_relative,
                    repository_digest,
                    skill_config_path,
                    skill_config_relative,
                    tracked=tracked,
                    gitlinks=gitlinks,
                    intent_to_add=intent_to_add,
                )
                contexts[name] = context
                declared_tracked_by_skill[name] = declared_tracked
        elif raw_context.get("repository") is not None:
            raise SyncError(
                f"{config_path}.config.repository must be null when no Skill contexts exist"
            )

        for name, paths in declared_tracked_by_skill.items():
            for path in paths:
                protected_context_paths[path] = f"{name} explicit tracked fact"
        _assert_context_writes_disjoint(contexts, protected_context_paths)

    return ConsumerConfig(
        selected=selected,
        source_relative=source_relative,
        config_relative=config_relative,
        config_digest=_sha256_bytes(config_bytes),
        contexts=contexts,
    )


def build_plan(
    repo: Path, central_root: Path, config_path: Path
) -> tuple[list[DesiredTarget], ConsumerConfig]:
    repo = _absolute(repo)
    central_root = _absolute(central_root)
    catalog = _catalog_policy(central_root)
    consumer = _read_config(repo, config_path, central_root, catalog)
    selected = consumer.selected
    desired: list[DesiredTarget] = []

    # Reject non-selectable names before group checks or any source-tree work so
    # callers always receive the actionable final active replacement.
    for name in sorted(selected):
        if name in catalog.retired_names:
            replacement = _active_replacement(name, catalog)
            raise SyncError(
                f"retired Skill in {config_path.name}: {name}; "
                f"use active replacement {replacement!r}"
            )
        if (
            name in catalog.skills
            and catalog.skills[name]["lifecycle"]["state"] == "rollback-only"
        ):
            replacement = _active_replacement(name, catalog)
            raise SyncError(
                f"rollback-only Skill in {config_path.name}: {name}; "
                f"use active replacement {replacement!r}"
            )

    for name in sorted(selected):
        if name not in catalog.skills:
            raise SyncError(f"unknown Skill in {config_path.name}: {name}")

    # Count distinct Skill names, not host targets: the same Skill selected for
    # Codex and Claude is one choice, while two different primary entries conflict.
    for group, maximum in sorted(catalog.selection_groups.items()):
        members = sorted(
            name for name in selected if group in catalog.skills[name]["groups"]
        )
        if len(members) > maximum:
            raise SyncError(
                f"selection group {group!r} allows at most {maximum} distinct Skill "
                f"per config; selected: {', '.join(members)}"
            )

    for name in sorted(selected):
        entry = catalog.skills[name]
        source, source_path = _resolve_under(
            central_root, entry.get("path"), f"catalog path for {name}"
        )
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise SyncError(
                f"source for {name} is unavailable at {source_path}; run "
                "git submodule update --init --recursive in the consumer repository"
            )
        if entry.get("kind") == "first-party":
            expected_worktree = central_root
        else:
            origin = entry.get("origin")
            if not isinstance(origin, dict):
                raise SyncError(f"external Skill {name!r} has no origin policy")
            expected_worktree, _ = _resolve_under(
                central_root,
                origin.get("submodule"),
                f"catalog submodule for {name}",
            )
        _assert_source_is_tracked(source, expected_worktree)
        source_digest = skill_digest(source)
        context = consumer.contexts.get(name)
        context_bytes = _json_bytes(context) if context is not None else None
        context_digest = (
            _sha256_bytes(context_bytes) if context_bytes is not None else None
        )
        digest = _skill_digest_with_context(source, context_bytes)

        for host in selected[name]:
            target_relative_path = TARGET_ROOTS[host] / name
            target, target_relative = _resolve_under(
                repo, target_relative_path.as_posix(), f"target for {name}/{host}"
            )
            if Path(target_relative).parent.as_posix() != TARGET_ROOTS[host].as_posix():
                raise SyncError(f"target must be a direct child of {TARGET_ROOTS[host]}")
            desired.append(
                DesiredTarget(
                    skill=name,
                    host=host,
                    source=source,
                    source_relative=source_path,
                    target=target,
                    target_relative=target_relative,
                    digest=digest,
                    source_digest=source_digest,
                    context_digest=context_digest,
                    context=context,
                )
            )
    materialized_roots = {
        item.target_relative: f"materialized Skill target {item.skill!r}/{item.host}"
        for item in desired
    }
    _assert_context_writes_disjoint(consumer.contexts, materialized_roots)
    return desired, consumer


def _run_git(root: Path, *arguments: str) -> str:
    command = [
        "git",
        "-c",
        f"safe.directory={root.as_posix()}",
        "-C",
        os.fspath(root),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise SyncError("Git is required to verify the central Skill version") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"Git timed out while inspecting {root}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(f"Git could not inspect central source {root}: {detail}")
    return result.stdout


def _source_commit(central_root: Path) -> str:
    commit = _run_git(central_root, "rev-parse", "--verify", "HEAD").strip()
    if not commit:
        raise SyncError(f"central source has no committed HEAD: {central_root}")
    dirty = _run_git(
        central_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ).strip()
    if dirty:
        preview = "; ".join(dirty.splitlines()[:5])
        raise SyncError(
            "central Skill source is dirty; commit or discard its changes before "
            f"materializing ({preview})"
        )
    return commit


def _valid_digest(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == HEX_DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_record(record: Any, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SyncError(f"{label} must be an object")
    name = _validated_name(record.get("skill"), f"{label}.skill")
    host = record.get("host")
    if not isinstance(host, str) or host not in TARGET_ROOTS:
        raise SyncError(f"{label}.host is invalid: {host!r}")
    source = record.get("source")
    if not isinstance(source, str) or not source:
        raise SyncError(f"{label}.source must be a non-empty string")
    source_path = Path(source)
    if source_path.is_absolute() or ".." in source_path.parts:
        raise SyncError(f"{label}.source must be a safe relative path")
    digest = record.get("digest")
    if not _valid_digest(digest):
        raise SyncError(f"{label}.digest must be a lowercase SHA-256 hex digest")
    normalized = {"skill": name, "host": host, "source": source, "digest": digest}
    if "source_digest" in record:
        source_digest = record.get("source_digest")
        if not _valid_digest(source_digest):
            raise SyncError(
                f"{label}.source_digest must be a lowercase SHA-256 hex digest"
            )
        normalized["source_digest"] = source_digest
    if "context_digest" in record:
        context_digest = record.get("context_digest")
        if context_digest is not None and not _valid_digest(context_digest):
            raise SyncError(
                f"{label}.context_digest must be a lowercase SHA-256 digest or null"
            )
        normalized["context_digest"] = context_digest
    return normalized


def _marker_for_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "manager": "agent-skills",
        **record,
    }


def _state_record(item: DesiredTarget) -> dict[str, Any]:
    return {
        "skill": item.skill,
        "host": item.host,
        "source": item.source_relative,
        "digest": item.digest,
        "source_digest": item.source_digest,
        "context_digest": item.context_digest,
    }


def _state(repo: Path) -> tuple[dict[str, Any], bool]:
    path = repo / STATE_FILE
    exists = _path_present(path)
    state = _load_json(
        path,
        missing={
            "version": 1,
            "manager": "agent-skills",
            "source": None,
            "source_commit": None,
            "config": None,
            "config_digest": None,
            "managed": {},
        },
    )
    if not isinstance(state, dict) or state.get("version") != 1:
        raise SyncError(f"{path} has an unsupported format")
    if state.get("manager") != "agent-skills":
        raise SyncError(f"{path} is not owned by agent-skills")
    if state.get("source") is not None and not isinstance(state.get("source"), str):
        raise SyncError(f"{path}.source must be a string or null")
    if state.get("source_commit") is not None and not isinstance(
        state.get("source_commit"), str
    ):
        raise SyncError(f"{path}.source_commit must be a string or null")
    if not isinstance(state.get("managed"), dict):
        raise SyncError(f"{path}.managed must be an object")
    if state.get("config") is not None and not isinstance(state.get("config"), str):
        raise SyncError(f"{path}.config must be a string or null")
    if state.get("config_digest") is not None and not _valid_digest(
        state.get("config_digest")
    ):
        raise SyncError(f"{path}.config_digest must be a SHA-256 digest or null")
    return state, exists


def _expected_state_target(
    repo: Path, relative: Any, raw_record: Any
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(relative, str):
        raise SyncError("state target keys must be strings")
    record = _validate_record(raw_record, f"state record for {relative}")
    expected = (TARGET_ROOTS[record["host"]] / record["skill"]).as_posix()
    if relative != expected:
        raise SyncError(
            f"refusing unsafe state target {relative!r}; expected {expected!r} from its record"
        )
    target, normalized = _resolve_under(repo, relative, f"state target {relative}")
    if normalized != expected:
        raise SyncError(f"state target is not a direct discovery child: {relative}")
    return target, record


def _read_marker(target: Path) -> dict[str, Any] | None:
    marker_path = target / MARKER_FILE
    if not _path_present(marker_path):
        return None
    marker = _load_json(marker_path)
    if not isinstance(marker, dict):
        raise SyncError(f"invalid ownership marker: {marker_path}")
    return marker


def _marker_matches_record(target: Path, record: dict[str, Any]) -> bool:
    marker = _read_marker(target)
    return marker == _marker_for_record(record)


def _validate_managed_target(target: Path, record: dict[str, Any]) -> None:
    if not _path_present(target):
        raise SyncError(f"managed target is missing: {target}")
    if _is_link_or_junction(target) or not target.is_dir():
        raise SyncError(f"managed target is not a real directory: {target}")
    skill_digest(target, managed_copy=True)  # Also rejects nested links/special files.
    if not _marker_matches_record(target, record):
        raise SyncError(f"ownership marker does not match state: {target}")


def _scan_managed_markers(repo: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for host, relative_root in TARGET_ROOTS.items():
        root, _ = _resolve_under(repo, relative_root.as_posix(), f"{host} discovery root")
        if not _path_present(root):
            continue
        if _is_link_or_junction(root) or not root.is_dir():
            raise SyncError(f"discovery root must be a real directory: {root}")
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if _is_link_or_junction(child) or not child.is_dir():
                continue
            marker = _read_marker(child)
            if not marker or marker.get("manager") != "agent-skills":
                continue
            record = _validate_record(marker, f"marker for {child}")
            expected_marker = _marker_for_record(record)
            if marker != expected_marker:
                raise SyncError(f"malformed agent-skills marker: {child / MARKER_FILE}")
            if record["host"] != host or record["skill"] != child.name:
                raise SyncError(f"marker identity does not match discovery path: {child}")
            relative = (relative_root / child.name).as_posix()
            found[relative] = record
    return found


def _preflight(
    repo: Path,
    desired: list[DesiredTarget],
    old_state: dict[str, Any],
    source_relative: str,
) -> list[tuple[str, Path, dict[str, Any]]]:
    desired_by_path = {item.target_relative: item for item in desired}
    managed = old_state["managed"]
    if managed and old_state.get("source") != source_relative:
        raise SyncError(
            f"state source is {old_state.get('source')!r}, not {source_relative!r}; "
            "restore the original source or explicitly remove its managed targets first"
        )

    marked = _scan_managed_markers(repo)
    orphans = sorted(set(marked) - set(managed))
    if orphans:
        raise SyncError(
            "found generated Skill directories without state ownership: "
            + ", ".join(orphans)
            + f". Restore {STATE_FILE} or remove those directories explicitly."
        )

    validated_state: dict[str, tuple[Path, dict[str, Any]]] = {}
    for relative, raw_record in managed.items():
        validated_state[relative] = _expected_state_target(repo, relative, raw_record)

    for item in desired:
        if not _path_present(item.target):
            continue
        state_entry = validated_state.get(item.target_relative)
        if state_entry is None:
            raise SyncError(
                f"refusing to overwrite unmanaged target: {item.target}. "
                "Move or remove it explicitly before retrying."
            )
        _target, old_record = state_entry
        _validate_managed_target(item.target, old_record)

    stale: list[tuple[str, Path, dict[str, Any]]] = []
    for relative, (target, record) in validated_state.items():
        if relative in desired_by_path:
            continue
        if _path_present(target):
            _validate_managed_target(target, record)
        stale.append((relative, target, record))
    return stale


@contextmanager
def _consumer_lock(repo: Path) -> Iterator[None]:
    lock = repo / LOCK_FILE
    token = uuid.uuid4().hex
    payload = json.dumps({"manager": "agent-skills", "pid": os.getpid(), "token": token})
    try:
        descriptor = os.open(
            lock,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise SyncError(
            f"another materialize/check operation may be running ({lock}); "
            "if it crashed, verify no process is active and remove the stale lock"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        yield
    finally:
        try:
            if lock.read_text(encoding="utf-8") == payload:
                lock.unlink()
        except (FileNotFoundError, OSError, UnicodeError):
            pass


def _check_locked(
    repo: Path, central_root: Path, config_path: Path
) -> list[str]:
    source_commit = _source_commit(central_root)
    desired, consumer = build_plan(repo, central_root, config_path)
    source_relative = consumer.source_relative
    if _source_commit(central_root) != source_commit:
        raise SyncError("central source changed while the materialization plan was built")

    state, state_exists = _state(repo)
    errors: list[str] = []
    desired_by_path = {item.target_relative: item for item in desired}
    managed = state["managed"]

    if state_exists:
        if state.get("source") != source_relative:
            errors.append(
                f"state source is {state.get('source')!r}; expected {source_relative!r}"
            )
        if state.get("source_commit") != source_commit:
            errors.append(
                f"state central commit is {state.get('source_commit')!r}; "
                f"expected {source_commit!r}"
            )
        if state.get("config") != consumer.config_relative:
            errors.append(
                f"state config is {state.get('config')!r}; "
                f"expected {consumer.config_relative!r}"
            )
        if state.get("config_digest") != consumer.config_digest:
            errors.append(
                f"state config digest is {state.get('config_digest')!r}; "
                f"expected {consumer.config_digest!r}"
            )

    try:
        marked = _scan_managed_markers(repo)
    except SyncError as exc:
        errors.append(str(exc))
        marked = {}
    for relative in sorted(set(marked) - set(managed)):
        errors.append(f"generated Skill has no state ownership: {relative}")

    validated_state: dict[str, tuple[Path, dict[str, Any]]] = {}
    for relative, raw_record in managed.items():
        try:
            validated_state[relative] = _expected_state_target(
                repo, relative, raw_record
            )
        except SyncError as exc:
            errors.append(str(exc))

    for item in desired:
        state_entry = validated_state.get(item.target_relative)
        if state_entry is None:
            errors.append(f"unmanaged or missing state entry: {item.target_relative}")
            continue
        target, record = state_entry
        if not _path_present(target):
            errors.append(f"missing generated Skill: {item.target_relative}")
            continue
        try:
            _validate_managed_target(target, record)
        except SyncError as exc:
            errors.append(str(exc))
            continue
        actual_digest = skill_digest(target, managed_copy=True)
        if actual_digest != item.digest:
            errors.append(
                f"generated Skill drifted: {item.target_relative} "
                f"({actual_digest[:12]} != {item.digest[:12]})"
            )
        if record != _state_record(item):
            errors.append(f"state metadata drifted: {item.target_relative}")

    for relative, (target, _record) in validated_state.items():
        if relative not in desired_by_path:
            errors.append(f"stale managed target in state: {relative}")
            if _path_present(target):
                errors.append(f"stale generated Skill still exists: {relative}")
    refreshed_desired, refreshed_consumer = build_plan(repo, central_root, config_path)
    if refreshed_desired != desired or refreshed_consumer != consumer:
        errors.append("central source or consumer context changed while checking")
    if _source_commit(central_root) != source_commit:
        errors.append("central source commit changed while checking")
    return errors


def check(repo: Path, central_root: Path, config_path: Path) -> list[str]:
    repo = _absolute(repo)
    central_root = _absolute(central_root)
    with _consumer_lock(repo):
        return _check_locked(repo, central_root, config_path)


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _remove_readonly(function, path: str, _error_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_path(path: Path) -> None:
    if not _path_present(path):
        return
    if path.is_symlink():
        path.unlink()
        return
    if _is_link_or_junction(path):
        os.rmdir(path)
        return
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        shutil.rmtree(path, onerror=_remove_readonly)
    elif stat.S_ISREG(mode):
        path.unlink()
    else:
        raise SyncError(f"refusing to remove special filesystem entry: {path}")


def _synchronize_locked(
    repo: Path,
    central_root: Path,
    config_path: Path,
    *,
    dry_run: bool,
) -> list[str]:
    source_commit = _source_commit(central_root)
    desired, consumer = build_plan(repo, central_root, config_path)
    source_relative = consumer.source_relative
    old_state, _state_exists = _state(repo)
    stale = _preflight(repo, desired, old_state, source_relative)

    messages = [
        f"copy {item.skill} -> {item.target_relative} ({item.host})" for item in desired
    ]
    messages.extend(f"remove stale managed target {relative}" for relative, _, _ in stale)
    if _source_commit(central_root) != source_commit:
        raise SyncError("central source changed while the materialization plan was built")
    if dry_run:
        return messages

    staged: dict[str, Path] = {}
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    state_temp: Path | None = None

    try:
        for item in desired:
            item.target.parent.mkdir(parents=True, exist_ok=True)
            stage = item.target.parent / (
                f".{item.target.name}.agent-skills-tmp-{uuid.uuid4().hex}"
            )
            staged[item.target_relative] = stage
            shutil.copytree(
                item.source,
                stage,
                symlinks=True,
                ignore=_copy_ignore,
            )
            if item.context is not None:
                _write_json(stage / CONTEXT_FILE, item.context)
            staged_digest = skill_digest(stage, managed_copy=True)
            if staged_digest != item.digest:
                raise SyncError(
                    f"staged copy changed while reading {item.skill}: "
                    f"{staged_digest[:12]} != {item.digest[:12]}"
                )
            if skill_digest(item.source) != item.source_digest:
                raise SyncError(f"source Skill changed while copying: {item.source}")

        refreshed_desired, refreshed_consumer = build_plan(
            repo, central_root, config_path
        )
        if refreshed_desired != desired or refreshed_consumer != consumer:
            raise SyncError(
                "central source or consumer context changed while Skills were staged"
            )
        if _source_commit(central_root) != source_commit:
            raise SyncError("central source changed while Skills were being staged")

        # Staging may take long enough for another process or a user to alter a
        # discovery directory. Revalidate every target immediately before swaps.
        stale = _preflight(repo, desired, old_state, source_relative)

        for item in desired:
            _write_json(
                staged[item.target_relative] / MARKER_FILE,
                _marker_for_record(_state_record(item)),
            )

        for item in desired:
            target = item.target
            if _path_present(target):
                raw_record = old_state["managed"].get(item.target_relative)
                if raw_record is None:
                    raise SyncError(f"target became unmanaged before install: {target}")
                _state_target, record = _expected_state_target(
                    repo, item.target_relative, raw_record
                )
                _validate_managed_target(target, record)
                backup = target.parent / (
                    f".{target.name}.agent-skills-backup-{uuid.uuid4().hex}"
                )
                os.replace(target, backup)
                backups.append((target, backup))
            os.replace(staged[item.target_relative], target)
            installed.append(target)

        for _relative, target, _record in stale:
            if not _path_present(target):
                continue
            _validate_managed_target(target, _record)
            backup = target.parent / (
                f".{target.name}.agent-skills-backup-{uuid.uuid4().hex}"
            )
            os.replace(target, backup)
            backups.append((target, backup))

        new_state = {
            "version": 1,
            "manager": "agent-skills",
            "source": source_relative,
            "source_commit": source_commit,
            "config": consumer.config_relative,
            "config_digest": consumer.config_digest,
            "managed": {
                item.target_relative: _state_record(item)
                for item in sorted(desired, key=lambda entry: entry.target_relative)
            },
        }
        state_temp = repo / f".{STATE_FILE.lstrip('.')}.tmp-{uuid.uuid4().hex}"
        _write_json(state_temp, new_state)
        os.replace(state_temp, repo / STATE_FILE)
        state_temp = None
    except Exception as original:
        rollback_errors: list[str] = []
        for target in reversed(installed):
            try:
                _remove_path(target)
            except Exception as exc:  # Preserve the original failure and report rollback.
                rollback_errors.append(f"remove {target}: {exc}")
        for target, backup in reversed(backups):
            try:
                if _path_present(target):
                    _remove_path(target)
                if _path_present(backup):
                    os.replace(backup, target)
            except Exception as exc:
                rollback_errors.append(f"restore {target}: {exc}")
        if rollback_errors:
            raise SyncError(
                f"{original}; rollback was incomplete: " + "; ".join(rollback_errors)
            ) from original
        raise
    finally:
        for stage in staged.values():
            if _path_present(stage):
                try:
                    _remove_path(stage)
                except (OSError, SyncError):
                    pass
        if state_temp is not None and _path_present(state_temp):
            try:
                _remove_path(state_temp)
            except (OSError, SyncError):
                pass

    for _target, backup in backups:
        if not _path_present(backup):
            continue
        try:
            _remove_path(backup)
        except (OSError, SyncError) as exc:
            messages.append(
                f"warning: synchronization committed but backup cleanup failed: {backup} ({exc})"
            )
    return messages


def synchronize(
    repo: Path,
    central_root: Path,
    config_path: Path,
    *,
    dry_run: bool = False,
) -> list[str]:
    repo = _absolute(repo)
    central_root = _absolute(central_root)
    with _consumer_lock(repo):
        return _synchronize_locked(
            repo, central_root, config_path, dry_run=dry_run
        )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy selected central Skills into Codex and Claude discovery paths."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="consumer repository root (default: current directory)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"config path, relative to --repo (default: {DEFAULT_CONFIG})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify without writing")
    mode.add_argument("--dry-run", action="store_true", help="show the planned writes")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repo = _absolute(args.repo)
    if args.config is None:
        config_path = repo / DEFAULT_CONFIG
    elif args.config.is_absolute():
        config_path = args.config
    else:
        config_path = repo / args.config
    config_path = _absolute(config_path)

    try:
        if not repo.is_dir():
            raise SyncError(f"consumer repository does not exist: {repo}")
        if args.check:
            errors = check(repo, CENTRAL_ROOT, config_path)
            if errors:
                print("Skill materialization check failed:", file=sys.stderr)
                for error in errors:
                    print(f"- {error}", file=sys.stderr)
                return 1
            print("Skill materialization is current.")
            return 0

        messages = synchronize(
            repo, CENTRAL_ROOT, config_path, dry_run=args.dry_run
        )
        prefix = "would " if args.dry_run else ""
        for message in messages:
            print(prefix + message)
        if not args.dry_run:
            print("Skill materialization completed.")
        return 0
    except (SyncError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
