#!/usr/bin/env python3
"""Safely update and rematerialize agent-skills in a consumer repository.

The script intentionally uses only Python's standard library. It updates only the
central submodule declared by the consumer config, never stages, commits, or pushes
the consumer repository, and restores the previous version if an update step fails.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_CONFIG = ".agent-skills.json"
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
MATERIALIZER = Path("tools/materialize_skills.py")
REQUIRED_SOURCE_FILES = (
    Path("catalog.json"),
    MATERIALIZER,
    Path("tools/skill_names.py"),
)
FULL_OBJECT_ID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")


class UpdateError(RuntimeError):
    """Raised when an update cannot safely start or continue."""


class UpdateRolledBack(UpdateError):
    """Raised when an update failed and the previous version was restored."""


class RollbackError(UpdateError):
    """Raised when an update failed and automatic restoration was incomplete."""


@dataclass(frozen=True)
class UpdatePlan:
    repo: Path
    config_argument: Path
    source: Path
    source_relative: str
    consumer_head: str
    recorded_commit: str
    start_commit: str
    target_commit: str
    target_label: str
    start_nested_paths: frozenset[str]
    start_existing_paths: frozenset[str]
    start_path_types: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class NestedWorktree:
    relative: str
    parent: Path
    local_path: str
    worktree: Path


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        return os.path.normcase(os.fspath(_absolute(left))) == os.path.normcase(
            os.fspath(_absolute(right))
        )


def _relative_key(path: str) -> str:
    return PurePosixPath(
        *(
            unicodedata.normalize("NFC", part).casefold()
            for part in PurePosixPath(path).parts
        )
    ).as_posix()


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction_check = getattr(path, "is_junction", None)
    if junction_check is None:
        return False
    try:
        return bool(junction_check())
    except OSError:
        return True


def _command_text(command: Sequence[os.PathLike[str] | str]) -> str:
    arguments = [os.fspath(part) for part in command]
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _display_argument(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def _run(
    command: Sequence[os.PathLike[str] | str],
    *,
    cwd: Path,
    label: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [os.fspath(part) for part in command],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise UpdateError(f"cannot run {label}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise UpdateError(f"{label} failed ({_command_text(command)}){suffix}")
    return result


def _git(
    root: Path,
    *arguments: str,
    label: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["git", "-c", f"safe.directory={root}", "-C", root, *arguments],
        cwd=root,
        label=label or "Git command",
        check=check,
    )


def _git_output(root: Path, *arguments: str, label: str | None = None) -> str:
    return _git(root, *arguments, label=label).stdout.strip()


def _safe_path_under(repo: Path, raw: object, label: str) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw:
        raise UpdateError(f"{label} must be a non-empty relative path")
    if "\\" in raw:
        raise UpdateError(f"{label} must use forward slashes: {raw!r}")
    posix = PurePosixPath(raw)
    if (
        posix.is_absolute()
        or ".." in posix.parts
        or posix.as_posix() != raw
        or raw in {"", "."}
    ):
        raise UpdateError(f"{label} must stay inside the consumer repository: {raw!r}")
    for part in posix.parts:
        if any(ord(character) < 32 for character in part):
            raise UpdateError(f"{label} contains a control character: {raw!r}")

    relative = Path(*posix.parts)
    current = repo
    for part in relative.parts:
        current /= part
        if os.path.lexists(current) and _is_link_or_junction(current):
            raise UpdateError(f"{label} contains a symlink or junction: {current}")

    candidate = _absolute(repo / relative)
    try:
        common = Path(os.path.commonpath([repo, candidate]))
    except ValueError as exc:
        raise UpdateError(f"{label} escapes the consumer repository: {raw!r}") from exc
    if not _same_path(common, repo):
        raise UpdateError(f"{label} escapes the consumer repository: {raw!r}")
    return candidate, posix.as_posix()


def _read_config(repo: Path, argument: Path) -> tuple[Path, str]:
    config = argument if argument.is_absolute() else repo / argument
    config = _absolute(config)
    try:
        config_relative = config.relative_to(repo)
    except ValueError as exc:
        raise UpdateError(f"consumer config must stay inside {repo}: {config}") from exc
    current = repo
    for part in config_relative.parts:
        current /= part
        if os.path.lexists(current) and _is_link_or_junction(current):
            raise UpdateError(f"consumer config contains a symlink or junction: {current}")
    if _is_link_or_junction(config) or not config.is_file():
        raise UpdateError(f"consumer config must be a regular file: {config}")
    try:
        value = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"cannot read consumer config {config}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"consumer config must be a JSON object: {config}")
    source, source_relative = _safe_path_under(
        repo, value.get("source"), f"{config.name}.source"
    )
    return source, source_relative


def _assert_consumer_root(repo: Path) -> str:
    if not repo.is_dir():
        raise UpdateError(f"consumer repository does not exist: {repo}")
    top = _absolute(
        Path(
            _git_output(
                repo,
                "rev-parse",
                "--show-toplevel",
                label="locate consumer repository",
            )
        )
    )
    if not _same_path(top, repo):
        raise UpdateError(f"--repo must name the Git worktree root: {top}")
    return _git_output(repo, "rev-parse", "HEAD", label="read consumer HEAD")


def _gitlink_from_index(repo: Path, relative: str) -> str:
    output = _git(
        repo,
        "ls-files",
        "--stage",
        "-z",
        "--",
        relative,
        label="inspect central submodule in the index",
    ).stdout
    entries = [entry for entry in output.split("\0") if entry]
    if len(entries) != 1:
        raise UpdateError(
            f"configured source must be one registered Git submodule: {relative}"
        )
    metadata, separator, path = entries[0].partition("\t")
    fields = metadata.split()
    if separator != "\t" or path != relative or len(fields) != 3:
        raise UpdateError(f"cannot parse Git index entry for {relative}")
    mode, commit, stage = fields
    if mode != "160000" or stage != "0":
        raise UpdateError(f"configured source is not a stage-0 Git submodule: {relative}")
    return commit


def _gitlink_from_head(repo: Path, relative: str) -> str:
    output = _git(
        repo,
        "ls-tree",
        "-z",
        "HEAD",
        "--",
        relative,
        label="inspect central submodule in consumer HEAD",
    ).stdout
    entries = [entry for entry in output.split("\0") if entry]
    if len(entries) != 1:
        raise UpdateError(f"consumer HEAD does not record the submodule {relative}")
    output = entries[0]
    metadata, separator, path = output.partition("\t")
    fields = metadata.split()
    if separator != "\t" or path != relative or len(fields) != 3:
        raise UpdateError(f"consumer HEAD does not record the submodule {relative}")
    mode, kind, commit = fields
    if mode != "160000" or kind != "commit":
        raise UpdateError(f"consumer HEAD does not record a Git submodule at {relative}")
    return commit


def _ensure_initialized(
    repo: Path, source: Path, relative: str, *, initialize: bool
) -> None:
    initialized = False
    if source.is_dir():
        probe = _git(source, "rev-parse", "--show-toplevel", check=False)
        if probe.returncode == 0:
            initialized = _same_path(_absolute(Path(probe.stdout.strip())), source)
    if not initialized and not initialize:
        raise UpdateError(
            f"{relative} is not initialized; restore the pinned version before a dry run: "
            f"git submodule update --init -- {relative}"
        )
    if not initialized:
        if os.path.lexists(source):
            if _is_link_or_junction(source) or not source.is_dir():
                raise UpdateError(
                    f"cannot initialize {relative} over an existing non-directory path"
                )
            try:
                occupied = next(source.iterdir(), None) is not None
            except OSError as exc:
                raise UpdateError(f"cannot inspect uninitialized path {source}: {exc}") from exc
            if occupied:
                raise UpdateError(
                    f"cannot initialize {relative} over a non-empty directory"
                )
        print(f"Initializing {relative} at the version recorded by the consumer...")
        _git(
            repo,
            "submodule",
            "update",
            "--init",
            "--checkout",
            "--",
            relative,
            label=f"initialize {relative}",
        )
    top = _absolute(
        Path(
            _git_output(
                source,
                "rev-parse",
                "--show-toplevel",
                label="locate central submodule worktree",
            )
        )
    )
    if not _same_path(top, source):
        raise UpdateError(f"configured source is not its own Git worktree root: {source}")
    superproject_value = _git_output(
        source,
        "rev-parse",
        "--show-superproject-working-tree",
        label="verify central submodule ownership",
    )
    if not superproject_value or not _same_path(
        _absolute(Path(superproject_value)), repo
    ):
        raise UpdateError(
            f"configured source is not attached to this consumer as a submodule: {source}"
        )


def _assert_source_clean(source: Path) -> None:
    status = _git_output(
        source,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
        label="inspect central submodule worktree",
    )
    if status:
        raise UpdateError(
            "central submodule has local or nested changes; preserve or discard them "
            f"before updating:\n{status}"
        )


def _assert_source_files(source: Path) -> None:
    missing = [
        path.as_posix()
        for path in REQUIRED_SOURCE_FILES
        if not (source / path).is_file()
    ]
    if missing:
        raise UpdateError(
            "central submodule is missing required files: " + ", ".join(missing)
        )


def _assert_no_materializer_lock(repo: Path) -> None:
    lock = repo / ".agent-skills.lock"
    if os.path.lexists(lock):
        raise UpdateError(
            "Skill materialization is already running or left a stale lock; "
            f"inspect it before updating: {lock}"
        )


def _assert_target_files(source: Path, commit: str) -> None:
    for path in REQUIRED_SOURCE_FILES:
        result = _git(
            source,
            "cat-file",
            "-e",
            f"{commit}:{path.as_posix()}",
            label=f"inspect target {path.as_posix()}",
            check=False,
        )
        if result.returncode != 0:
            raise UpdateError(
                f"target commit {commit[:12]} is missing {path.as_posix()}"
            )


def _validate_remote(source: Path, remote: str) -> None:
    if not REMOTE_NAME.fullmatch(remote) or ".." in remote or remote.endswith("/"):
        raise UpdateError(f"invalid Git remote name: {remote!r}")
    result = _git(
        source,
        "remote",
        "get-url",
        remote,
        label=f"locate remote {remote}",
        check=False,
    )
    if result.returncode != 0:
        raise UpdateError(f"central submodule has no configured remote named {remote!r}")


def _fetch(source: Path, remote: str) -> None:
    _git(
        source,
        "fetch",
        "--prune",
        "--tags",
        remote,
        label=f"fetch central Skill remote {remote}",
    )


def _try_commit(source: Path, revision: str) -> str | None:
    result = _git(
        source,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if FULL_OBJECT_ID.fullmatch(value) else None


def _resolve_target(source: Path, remote: str, raw_ref: str | None) -> tuple[str, str]:
    if raw_ref is None:
        label = f"{remote}/{DEFAULT_BRANCH}"
        commit = _try_commit(source, f"refs/remotes/{label}")
        if commit is None:
            raise UpdateError(
                f"cannot resolve default remote branch {label!r}; use --ref explicitly"
            )
        return commit, label

    if not raw_ref or any(ord(character) < 32 for character in raw_ref):
        raise UpdateError("--ref must be a non-empty Git ref or full commit ID")
    if FULL_OBJECT_ID.fullmatch(raw_ref):
        commit = _try_commit(source, raw_ref)
        if commit is None:
            raise UpdateError(f"commit is not available after fetch: {raw_ref}")
        return commit, raw_ref

    if raw_ref.startswith(("refs/remotes/", "refs/tags/")):
        commit = _try_commit(source, raw_ref)
        if commit is None:
            raise UpdateError(f"cannot resolve Git ref: {raw_ref!r}")
        return commit, raw_ref

    remote_prefix = f"{remote}/"
    if raw_ref.startswith(remote_prefix):
        commit = _try_commit(source, f"refs/remotes/{raw_ref}")
        if commit is None:
            raise UpdateError(f"cannot resolve remote branch: {raw_ref!r}")
        return commit, raw_ref

    branch_check = _git(
        source,
        "check-ref-format",
        f"refs/heads/{raw_ref}",
        check=False,
    )
    tag_check = _git(
        source,
        "check-ref-format",
        f"refs/tags/{raw_ref}",
        check=False,
    )
    if branch_check.returncode != 0 and tag_check.returncode != 0:
        raise UpdateError(
            "--ref must be a branch name, tag name, remote ref, or full commit ID"
        )

    candidates: list[tuple[str, str]] = []
    if branch_check.returncode == 0:
        commit = _try_commit(source, f"refs/remotes/{remote}/{raw_ref}")
        if commit is not None:
            candidates.append((f"{remote}/{raw_ref}", commit))
    if tag_check.returncode == 0:
        commit = _try_commit(source, f"refs/tags/{raw_ref}")
        if commit is not None:
            candidates.append((f"tag {raw_ref}", commit))
    if not candidates:
        raise UpdateError(f"cannot resolve remote branch or tag: {raw_ref!r}")
    commits = {commit for _label, commit in candidates}
    if len(commits) > 1:
        labels = ", ".join(label for label, _commit in candidates)
        raise UpdateError(f"ambiguous --ref {raw_ref!r}; it matches {labels}")
    labels = " / ".join(label for label, _commit in candidates)
    return candidates[0][1], labels


def _assert_fast_forward(source: Path, start: str, target: str, *, allow: bool) -> None:
    if start == target or allow:
        return
    result = _git(
        source,
        "merge-base",
        "--is-ancestor",
        start,
        target,
        check=False,
    )
    if result.returncode == 1:
        raise UpdateError(
            f"target {target[:12]} is not a fast-forward from {start[:12]}; "
            "use --allow-non-fast-forward only after reviewing the change"
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"cannot compare current and target commits: {detail}")


def _checkout(source: Path, commit: str) -> None:
    _git(
        source,
        "checkout",
        "--detach",
        commit,
        label=f"check out central commit {commit[:12]}",
    )


def _declared_submodule_paths(root: Path) -> tuple[str, ...]:
    modules = root / ".gitmodules"
    if not modules.is_file():
        return ()
    result = _git(
        root,
        "config",
        "-z",
        "--file",
        ".gitmodules",
        "--get-regexp",
        r"^submodule\..*\.path$",
        label="read nested submodule paths",
        check=False,
    )
    if result.returncode == 1 and not result.stdout:
        return ()
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"cannot read nested submodule paths: {detail}")

    paths: list[str] = []
    for record in (item for item in result.stdout.split("\0") if item):
        _key, separator, raw_path = record.partition("\n")
        if separator != "\n" or not raw_path:
            raise UpdateError(f"cannot parse nested submodule entry in {modules}")
        _path, normalized = _safe_path_under(root, raw_path, ".gitmodules path")
        paths.append(normalized)
    if len(paths) != len(set(paths)):
        raise UpdateError(f"duplicate nested submodule path in {modules}")
    return tuple(sorted(paths))


def _is_own_worktree(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = _git(path, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return False
    return _same_path(_absolute(Path(result.stdout.strip())), path)


def _nested_worktrees(
    root: Path,
    *,
    prefix: PurePosixPath | None = None,
    depth: int = 0,
) -> list[NestedWorktree]:
    if depth > 32:
        raise UpdateError(f"nested submodule depth exceeds the safety limit under {root}")
    if prefix is None:
        prefix = PurePosixPath()
    result: list[NestedWorktree] = []
    for local_path in _declared_submodule_paths(root):
        worktree = root / Path(*PurePosixPath(local_path).parts)
        if not _is_own_worktree(worktree):
            continue
        relative = (prefix / PurePosixPath(local_path)).as_posix()
        result.append(
            NestedWorktree(
                relative=relative,
                parent=root,
                local_path=local_path,
                worktree=worktree,
            )
        )
        result.extend(
            _nested_worktrees(
                worktree,
                prefix=PurePosixPath(relative),
                depth=depth + 1,
            )
        )
    return result


def _nested_path_snapshot(source: Path) -> frozenset[str]:
    declared_top_level = {
        _relative_key(path) for path in _declared_submodule_paths(source)
    }
    initialized = {
        _relative_key(item.relative) for item in _nested_worktrees(source)
    }
    return frozenset(declared_top_level | initialized)


def _filesystem_path_snapshot(root: Path) -> dict[str, str]:
    paths: dict[str, str] = {}

    def visit(directory: Path, prefix: PurePosixPath, depth: int) -> None:
        if depth > 128:
            raise UpdateError(f"filesystem depth exceeds the safety limit under {root}")
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise UpdateError(f"cannot inspect central source path {directory}: {exc}") from exc
        for entry in entries:
            relative = (prefix / entry.name).as_posix()
            entry_path = Path(entry.path)
            key = _relative_key(relative)
            is_link = _is_link_or_junction(entry_path)
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                raise UpdateError(f"cannot inspect central source path {entry_path}: {exc}") from exc
            kind = "link" if is_link else "directory" if is_directory else "file"
            if key in paths:
                kind = "case-collision"
            paths[key] = kind
            if entry.name == ".git" or is_link:
                continue
            if is_directory:
                visit(entry_path, PurePosixPath(relative), depth + 1)

    visit(root, PurePosixPath(), 0)
    return paths


def _tree_entries(source: Path, commit: str) -> dict[str, tuple[str, str, str]]:
    output = _git(
        source,
        "ls-tree",
        "-r",
        "-t",
        "-z",
        "--full-tree",
        commit,
        label=f"inspect central tree {commit[:12]}",
    ).stdout
    entries: dict[str, tuple[str, str, str]] = {}
    for record in (item for item in output.split("\0") if item):
        metadata, separator, raw_path = record.partition("\t")
        fields = metadata.split()
        if separator != "\t" or len(fields) != 3 or not raw_path:
            raise UpdateError(f"cannot parse central tree entry at {commit[:12]}")
        mode, kind, _object_id = fields
        if "\\" in raw_path:
            raise UpdateError(f"central tree path must use forward slashes: {raw_path!r}")
        posix = PurePosixPath(raw_path)
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or posix.as_posix() != raw_path
            or any(
                ord(character) < 32
                for part in posix.parts
                for character in part
            )
        ):
            raise UpdateError(f"unsafe central tree path: {raw_path!r}")
        normalized = posix.as_posix()
        key = _relative_key(normalized)
        if key in entries:
            raise UpdateError(
                f"central tree {commit[:12]} contains paths that alias across platforms"
            )
        entries[key] = (normalized, mode, kind)
    return entries


def _assert_checkout_collisions(
    source: Path,
    current_commit: str,
    target_commit: str,
    filesystem: dict[str, str],
) -> None:
    current = _tree_entries(source, current_commit)
    target = _tree_entries(source, target_commit)
    current_keys = set(current)
    for key, (path, _mode, target_kind) in target.items():
        current_entry = current.get(key)
        filesystem_kind = filesystem.get(key)
        if current_entry is not None and current_entry[0] != path:
            raise UpdateError(
                f"target commit renames {current_entry[0]} to cross-platform alias "
                f"{path}; refusing an unsafe case-only path transition"
            )
        if current_entry is None and filesystem_kind is not None:
            if target_kind == "tree" and filesystem_kind == "directory":
                continue
            raise UpdateError(
                f"target commit would overwrite pre-existing untracked or ignored path: {path}"
            )
        if (
            current_entry is not None
            and current_entry[2] == "tree"
            and target_kind != "tree"
        ):
            prefix = key + "/"
            extra = next(
                (
                    existing
                    for existing in filesystem
                    if existing.startswith(prefix) and existing not in current_keys
                ),
                None,
            )
            if extra is not None:
                raise UpdateError(
                    f"target commit would replace directory {path} while it contains "
                    "untracked or ignored files"
                )


def _assert_checkout_still_safe(plan: UpdatePlan) -> None:
    current_filesystem = _filesystem_path_snapshot(plan.source)
    if tuple(sorted(current_filesystem.items())) != plan.start_path_types:
        raise UpdateError(
            "central source filesystem changed while the update was being prepared"
        )
    _assert_source_clean(plan.source)
    _assert_nested_worktrees_pristine(plan.source)
    _assert_checkout_collisions(
        plan.source,
        plan.start_commit,
        plan.target_commit,
        current_filesystem,
    )


def _assert_new_nested_path_available(
    worktree: Path,
    relative: str,
    *,
    initial_nested_paths: frozenset[str] | None,
    initial_existing_paths: frozenset[str] | None,
) -> None:
    if initial_nested_paths is None or initial_existing_paths is None:
        return
    key = _relative_key(relative)
    if key in initial_nested_paths:
        return
    if key in initial_existing_paths:
        raise UpdateError(
            f"target introduces nested submodule {relative} at a path that existed "
            "before the update; refusing to take ownership"
        )
    if not os.path.lexists(worktree):
        return
    if _is_link_or_junction(worktree) or not worktree.is_dir():
        raise UpdateError(
            f"target introduces nested submodule {relative} at a newly occupied path"
        )
    try:
        occupied = next(worktree.iterdir(), None) is not None
    except OSError as exc:
        raise UpdateError(f"cannot inspect new nested path {worktree}: {exc}") from exc
    if occupied:
        raise UpdateError(
            f"target introduces nested submodule {relative} at a non-empty path"
        )


def _update_nested(
    source: Path,
    *,
    initial_nested_paths: frozenset[str] | None = None,
    initial_existing_paths: frozenset[str] | None = None,
    prefix: PurePosixPath | None = None,
    depth: int = 0,
) -> None:
    if depth > 32:
        raise UpdateError(f"nested submodule depth exceeds the safety limit under {source}")
    if prefix is None:
        prefix = PurePosixPath()
    for local_path in _declared_submodule_paths(source):
        relative = (prefix / PurePosixPath(local_path)).as_posix()
        worktree = source / Path(*PurePosixPath(local_path).parts)
        _assert_new_nested_path_available(
            worktree,
            relative,
            initial_nested_paths=initial_nested_paths,
            initial_existing_paths=initial_existing_paths,
        )
        _git(
            source,
            "submodule",
            "sync",
            "--",
            local_path,
            label=f"synchronize nested submodule URL for {relative}",
        )
        _git(
            source,
            "submodule",
            "update",
            "--init",
            "--checkout",
            "--",
            local_path,
            label=f"update nested submodule {relative}",
        )
        if not _is_own_worktree(worktree):
            raise UpdateError(f"nested submodule did not initialize safely: {relative}")
        _update_nested(
            worktree,
            initial_nested_paths=initial_nested_paths,
            initial_existing_paths=initial_existing_paths,
            prefix=PurePosixPath(relative),
            depth=depth + 1,
        )


def _assert_removable_nested(item: NestedWorktree) -> None:
    status = _git(
        item.worktree,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
        "--ignore-submodules=none",
        label=f"inspect newly introduced nested submodule {item.relative}",
    ).stdout
    if status:
        raise UpdateError(
            f"new nested submodule {item.relative} gained local or ignored files; "
            "refusing to remove it during rollback"
        )


def _assert_nested_worktrees_pristine(source: Path) -> None:
    for item in _nested_worktrees(source):
        status = _git(
            item.worktree,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
            label=f"inspect nested submodule {item.relative}",
        ).stdout
        if status:
            raise UpdateError(
                f"nested submodule {item.relative} contains local or ignored files; "
                "remove or preserve them before changing its commit"
            )


def _cleanup_introduced_nested(plan: UpdatePlan) -> None:
    worktrees = _nested_worktrees(plan.source)
    candidates = [
        item
        for item in worktrees
        if _relative_key(item.relative) not in plan.start_nested_paths
        and _relative_key(item.relative) not in plan.start_existing_paths
    ]
    selected: list[NestedWorktree] = []
    for item in sorted(
        candidates, key=lambda entry: len(PurePosixPath(entry.relative).parts)
    ):
        item_path = PurePosixPath(item.relative)
        if any(
            item_path.is_relative_to(PurePosixPath(parent.relative))
            for parent in selected
        ):
            continue
        selected.append(item)

    for item in selected:
        item_path = PurePosixPath(item.relative)
        for descendant in worktrees:
            if PurePosixPath(descendant.relative).is_relative_to(item_path):
                _assert_removable_nested(descendant)
        _git(
            item.parent,
            "submodule",
            "deinit",
            "--",
            item.local_path,
            label=f"remove newly introduced nested submodule {item.relative}",
        )


def _materialize(
    repo: Path,
    source: Path,
    config_argument: Path,
    mode: str,
    *,
    show_output: bool = True,
) -> None:
    command: list[os.PathLike[str] | str] = [
        sys.executable,
        source / MATERIALIZER,
        "--repo",
        repo,
        "--config",
        config_argument,
    ]
    if mode:
        command.append(mode)
    result = _run(
        command,
        cwd=repo,
        label=f"Skill materialization {mode or 'apply'}",
    )
    if show_output and result.stdout.strip():
        print(result.stdout.rstrip())


def _assert_consumer_unchanged(plan: UpdatePlan) -> None:
    current_head = _git_output(
        plan.repo, "rev-parse", "HEAD", label="recheck consumer HEAD"
    )
    current_index = _gitlink_from_index(plan.repo, plan.source_relative)
    current_head_link = _gitlink_from_head(plan.repo, plan.source_relative)
    if current_head != plan.consumer_head:
        raise UpdateError("consumer HEAD changed while the update was running")
    if current_index != plan.recorded_commit or current_head_link != plan.recorded_commit:
        raise UpdateError("consumer submodule pointer was staged or committed unexpectedly")


def _rollback(plan: UpdatePlan) -> None:
    errors: list[str] = []
    try:
        _cleanup_introduced_nested(plan)
    except Exception as exc:
        errors.append(f"clean up new nested submodules: {exc}")
    source_restored = False
    try:
        _assert_nested_worktrees_pristine(plan.source)
        current_commit = _git_output(
            plan.source, "rev-parse", "HEAD", label="read failed update HEAD"
        )
        _assert_checkout_collisions(
            plan.source,
            current_commit,
            plan.start_commit,
            _filesystem_path_snapshot(plan.source),
        )
        _checkout(plan.source, plan.start_commit)
        _update_nested(plan.source)
        _assert_source_clean(plan.source)
        source_restored = True
    except Exception as exc:
        errors.append(f"restore central checkout: {exc}")
    if source_restored:
        try:
            _materialize(
                plan.repo,
                plan.source,
                plan.config_argument,
                "",
                show_output=False,
            )
            _materialize(
                plan.repo,
                plan.source,
                plan.config_argument,
                "--check",
                show_output=False,
            )
        except Exception as exc:
            errors.append(f"restore generated Skills: {exc}")
    try:
        _assert_consumer_unchanged(plan)
    except Exception as exc:
        errors.append(f"verify consumer repository: {exc}")
    if errors:
        raise RollbackError("; ".join(errors))


def _apply(plan: UpdatePlan) -> None:
    _assert_checkout_still_safe(plan)
    try:
        print(f"Checking out {plan.target_label} ({plan.target_commit[:12]})...")
        _checkout(plan.source, plan.target_commit)
        _update_nested(
            plan.source,
            initial_nested_paths=plan.start_nested_paths,
            initial_existing_paths=plan.start_existing_paths,
        )
        _assert_source_clean(plan.source)

        print("Previewing generated Skill changes...")
        _materialize(plan.repo, plan.source, plan.config_argument, "--dry-run")
        print("Applying and checking generated Skill changes...")
        _materialize(plan.repo, plan.source, plan.config_argument, "")
        _materialize(plan.repo, plan.source, plan.config_argument, "--check")
        _assert_source_clean(plan.source)
        _assert_nested_worktrees_pristine(plan.source)
        _assert_consumer_unchanged(plan)
    except BaseException as original:
        if isinstance(original, (SystemExit, GeneratorExit)):
            raise
        try:
            _rollback(plan)
        except Exception as rollback:
            raise RollbackError(
                f"update failed: {original}; automatic rollback was incomplete: {rollback}; "
                f"inspect {plan.source} before continuing"
            ) from original
        raise UpdateRolledBack(
            f"update failed: {original}; restored {plan.start_commit[:12]} and its "
            "generated Skills"
        ) from original


@contextmanager
def _update_lock(repo: Path) -> Iterator[None]:
    lock = Path(
        _git_output(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "agent-skills-update.lock",
            label="locate update lock",
        )
    )
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise UpdateError(
            f"another update may be running; if it is not, remove the stale lock: {lock}"
        ) from exc
    except OSError as exc:
        raise UpdateError(f"cannot create update lock {lock}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"warning: cannot remove update lock {lock}: {exc}", file=sys.stderr)


def _plan(args: argparse.Namespace) -> UpdatePlan:
    repo = _absolute(args.repo)
    consumer_head = _assert_consumer_root(repo)
    source, source_relative = _read_config(repo, args.config)
    recorded_commit = _gitlink_from_index(repo, source_relative)
    if _gitlink_from_head(repo, source_relative) != recorded_commit:
        raise UpdateError(
            f"the staged {source_relative} pointer differs from consumer HEAD; "
            "commit or unstage it before updating"
        )
    _ensure_initialized(
        repo, source, source_relative, initialize=not args.dry_run
    )
    _assert_source_clean(source)
    _assert_nested_worktrees_pristine(source)
    _assert_source_files(source)
    _assert_no_materializer_lock(repo)
    _validate_remote(source, args.remote)
    start_commit = _git_output(source, "rev-parse", "HEAD", label="read central HEAD")

    print(f"Fetching {args.remote} for {source_relative}...")
    _fetch(source, args.remote)
    target_commit, target_label = _resolve_target(source, args.remote, args.ref)
    _assert_target_files(source, target_commit)
    _assert_fast_forward(
        source,
        start_commit,
        target_commit,
        allow=args.allow_non_fast_forward,
    )
    config_argument = args.config
    filesystem = _filesystem_path_snapshot(source)
    _assert_checkout_collisions(source, start_commit, target_commit, filesystem)
    return UpdatePlan(
        repo=repo,
        config_argument=config_argument,
        source=source,
        source_relative=source_relative,
        consumer_head=consumer_head,
        recorded_commit=recorded_commit,
        start_commit=start_commit,
        target_commit=target_commit,
        target_label=target_label,
        start_nested_paths=_nested_path_snapshot(source),
        start_existing_paths=frozenset(filesystem),
        start_path_types=tuple(sorted(filesystem.items())),
    )


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update the central agent-skills submodule and regenerate selected Skills."
        )
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
        default=Path(DEFAULT_CONFIG),
        help=f"config path, relative to --repo (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--remote",
        default=DEFAULT_REMOTE,
        help=f"central Git remote name (default: {DEFAULT_REMOTE})",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help=f"remote branch, tag, or full commit ID (default: {DEFAULT_REMOTE}/{DEFAULT_BRANCH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch metadata and show the target without changing checked-out files",
    )
    parser.add_argument(
        "--allow-non-fast-forward",
        action="store_true",
        help="allow an explicit downgrade or unrelated target after manual review",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        repo = _absolute(args.repo)
        with _update_lock(repo):
            plan = _plan(args)
            print(
                f"Current {plan.source_relative}: {plan.start_commit[:12]}\n"
                f"Target  {plan.source_relative}: {plan.target_commit[:12]} "
                f"({plan.target_label})"
            )
            if args.dry_run:
                if plan.start_commit == plan.target_commit:
                    print("The central Skill checkout is already current.")
                else:
                    print("Dry run complete; no checkout or generated files were changed.")
                return 0

            _apply(plan)
            action = "Verified" if plan.start_commit == plan.target_commit else "Updated"
            source_argument = _display_argument(plan.source_relative)
            print(
                f"{action} {plan.source_relative} at {plan.target_commit[:12]}.\n"
                "The consumer repository was not staged, committed, or pushed.\n"
                "Review and publish the new pointer when ready:\n"
                f"  git diff --submodule=short -- {source_argument}\n"
                f"  git add -- {source_argument}\n"
                '  git commit --only -m "chore: update agent skills" -- '
                f"{source_argument}\n"
                "  git push"
            )
            return 0
    except UpdateRolledBack as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except RollbackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("error: update interrupted before checkout", file=sys.stderr)
        return 130
    except UpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
