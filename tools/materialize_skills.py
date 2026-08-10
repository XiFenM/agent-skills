#!/usr/bin/env python3
"""Materialize selected central Skills into agent discovery directories.

The script intentionally uses only Python's standard library. It never updates Git,
fetches a remote, or overwrites a target that it cannot prove it owns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
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
    return os.path.normcase(os.fspath(_absolute(left))) == os.path.normcase(
        os.fspath(_absolute(right))
    )


def _load_json(path: Path, *, missing: Any = None) -> Any:
    if not _path_present(path):
        if missing is not None:
            return missing
        raise SyncError(f"missing file: {path}")
    if _is_link_or_junction(path) or not path.is_file():
        raise SyncError(f"expected a regular JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"invalid JSON in {path}: {exc}") from exc


def _assert_components_are_real(base: Path, relative: Path, label: str) -> None:
    current = _absolute(base)
    for part in relative.parts:
        current /= part
        if _path_present(current) and _is_link_or_junction(current):
            raise SyncError(f"{label} contains a symlink or junction: {current}")


def _resolve_under(base: Path, raw_path: Any, label: str) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path:
        raise SyncError(f"{label} must be a non-empty relative path")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SyncError(f"{label} must stay inside {base}: {raw_path!r}")

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
            if _is_link_or_junction(path):
                raise SyncError(f"Skill trees may not contain links or junctions: {path}")
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise SyncError(f"cannot inspect Skill file {path}: {exc}") from exc
            if not stat.S_ISREG(mode):
                raise SyncError(f"Skill trees may contain only regular files: {path}")
            yield path, path.relative_to(root)


def skill_digest(root: Path, *, managed_copy: bool = False) -> str:
    digest = hashlib.sha256()
    for path, relative in _walk_regular_files(root, managed_copy=managed_copy):
        relative_bytes = relative.as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


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


def _read_config(
    repo: Path, config_path: Path, central_root: Path
) -> tuple[dict[str, list[str]], str]:
    config = _load_json(config_path)
    if not isinstance(config, dict) or config.get("version") != 1:
        raise SyncError(f"{config_path} must use version 1")

    configured_source, source_relative = _resolve_under(
        repo, config.get("source"), f"{config_path.name}.source"
    )
    if not _same_path(configured_source, central_root):
        raise SyncError(
            f"configured source resolves to {configured_source}, but this tool is running "
            f"from {_absolute(central_root)}"
        )

    selected = config.get("skills")
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
    return normalized, source_relative


def build_plan(
    repo: Path, central_root: Path, config_path: Path
) -> tuple[list[DesiredTarget], str]:
    repo = _absolute(repo)
    central_root = _absolute(central_root)
    selected, source_relative = _read_config(repo, config_path, central_root)
    catalog = _catalog_policy(central_root)
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
        source, source_path = _resolve_under(
            central_root, catalog.skills[name].get("path"), f"catalog path for {name}"
        )
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise SyncError(
                f"source for {name} is unavailable at {source_path}; run "
                "git submodule update --init --recursive in the consumer repository"
            )
        digest = skill_digest(source)

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
                )
            )
    return desired, source_relative


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
    return {"skill": name, "host": host, "source": source, "digest": digest}


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
    desired, source_relative = build_plan(repo, central_root, config_path)
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
    return errors


def check(repo: Path, central_root: Path, config_path: Path) -> list[str]:
    repo = _absolute(repo)
    central_root = _absolute(central_root)
    with _consumer_lock(repo):
        return _check_locked(repo, central_root, config_path)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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
    desired, source_relative = build_plan(repo, central_root, config_path)
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
            staged_digest = skill_digest(stage)
            if staged_digest != item.digest:
                raise SyncError(
                    f"staged copy changed while reading {item.skill}: "
                    f"{staged_digest[:12]} != {item.digest[:12]}"
                )
            if skill_digest(item.source) != item.digest:
                raise SyncError(f"source Skill changed while copying: {item.source}")

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
