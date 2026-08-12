from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    path = SKILL_ROOT / "scripts" / "context_config.py"
    name = "study_log_context_config"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.modules[name] = module
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


context_config = _load_module()


def _repository() -> dict[str, object]:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "learning-lab",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {"goal": {"path": "docs/goal.md"}},
    }


def _skill() -> dict[str, object]:
    return {
        "schema": "agent-skills.study-log/v1",
        "skill": "study-log",
        "structured_targets": [
            {"id": "systems-log", "path": "systems/log"},
            {"id": "algorithms-log", "path": "algorithms/log"},
        ],
    }


def test_validator_returns_canonical_context_and_write_only_allowlist() -> None:
    result = context_config.validate_materialized_context(_repository(), _skill())

    assert set(result) == {
        "context",
        "tracked_files",
        "tracked_collections",
        "write_paths",
    }
    assert result["tracked_files"] == []
    assert result["tracked_collections"] == []
    assert result["write_paths"] == ["algorithms/log", "systems/log"]
    assert result["context"] == {
        "schema": "agent-skills.study-log-context/v1",
        "repository": {
            "repository_id": "learning-lab",
            "language": "zh-CN",
            "timezone": "Asia/Shanghai",
        },
        "structured_targets": [
            {
                "id": "algorithms-log",
                "record_type": "structured-study-log",
                "path": "algorithms/log",
                "format": "markdown",
                "include_patterns": ["*.md"],
                "filename_policy": "yyyy-mm-dd-topic",
            },
            {
                "id": "systems-log",
                "record_type": "structured-study-log",
                "path": "systems/log",
                "format": "markdown",
                "include_patterns": ["*.md"],
                "filename_policy": "yyyy-mm-dd-topic",
            },
        ],
    }
    json.dumps(result, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(
    "field",
    [
        "archive_root",
        "private_root",
        "raw_target",
        "source",
        "boundary",
        "command",
        "approval",
    ],
)
def test_public_skill_config_rejects_runtime_private_or_authority_fields(field: str) -> None:
    skill = _skill()
    skill[field] = "C:/private/study-log"
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), skill)


def test_public_target_rejects_unknown_fields_including_consumers() -> None:
    skill = _skill()
    targets = skill["structured_targets"]
    assert isinstance(targets, list)
    targets[0]["consumers"] = ["memo-cards"]
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), skill)


@pytest.mark.parametrize(
    "path",
    [
        "C:/private/log",
        "/private/log",
        "../private/log",
        "module/../log",
        r"module\log",
        "module/*/log",
        "module/log/",
        "module//log",
        "module/CON",
        "module/log.",
    ],
)
def test_target_path_must_be_a_portable_repository_relative_directory(path: str) -> None:
    skill = _skill()
    targets = skill["structured_targets"]
    assert isinstance(targets, list)
    targets[0]["path"] = path
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(_repository(), skill)


@pytest.mark.parametrize(
    "paths",
    [
        ("module/log", "module/log"),
        ("Module/Log", "module/log"),
        ("module", "module/log"),
        ("module/log", "module/log/archive"),
    ],
)
def test_target_paths_must_be_case_insensitively_disjoint(paths: tuple[str, str]) -> None:
    skill = _skill()
    skill["structured_targets"] = [
        {"id": "first", "path": paths[0]},
        {"id": "second", "path": paths[1]},
    ]
    with pytest.raises(context_config.ContextConfigError, match="must be separate"):
        context_config.validate_materialized_context(_repository(), skill)


def test_target_ids_must_be_unique_lowercase_hyphen_identifiers() -> None:
    skill = _skill()
    skill["structured_targets"] = [
        {"id": "same-id", "path": "first/log"},
        {"id": "same-id", "path": "second/log"},
    ]
    with pytest.raises(context_config.ContextConfigError, match="duplicate id"):
        context_config.validate_materialized_context(_repository(), skill)

    invalid = _skill()
    targets = invalid["structured_targets"]
    assert isinstance(targets, list)
    targets[0]["id"] = "Upper_Case"
    with pytest.raises(context_config.ContextConfigError, match="lowercase hyphen"):
        context_config.validate_materialized_context(_repository(), invalid)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "agent-skills.study-log/v2", "schema must equal"),
        ("skill", "other-skill", "skill must equal"),
        ("structured_targets", [], "non-empty array"),
    ],
)
def test_skill_identity_and_non_empty_targets_are_strict(
    field: str, value: object, message: str
) -> None:
    skill = _skill()
    skill[field] = value
    with pytest.raises(context_config.ContextConfigError, match=message):
        context_config.validate_materialized_context(_repository(), skill)


def test_validator_is_deterministic_and_does_not_mutate_sources() -> None:
    repository = _repository()
    skill = _skill()
    original_repository = copy.deepcopy(repository)
    original_skill = copy.deepcopy(skill)

    first = context_config.validate_materialized_context(repository, skill)
    second = context_config.validate_materialized_context(repository, skill)

    assert first == second
    assert repository == original_repository
    assert skill == original_skill


def test_repository_projection_rejects_unknown_fields_and_omits_facts() -> None:
    repository = _repository()
    repository["private_path"] = "C:/private"
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(repository, _skill())

    without_optional = {
        "schema": "agent-skills.repository/v1",
        "repository_id": "learning-lab",
    }
    result = context_config.validate_materialized_context(without_optional, _skill())
    assert result["context"]["repository"] == {"repository_id": "learning-lab"}
