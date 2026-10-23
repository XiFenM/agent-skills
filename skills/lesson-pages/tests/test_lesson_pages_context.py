from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    path = ROOT / "scripts" / "context_config.py"
    spec = importlib.util.spec_from_file_location("lesson_pages_context_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.modules[spec.name] = module
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
    return module


context_config = _load_module()


def _repository() -> dict:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "learning-fixture",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {"preferences": {"path": "learning/preferences.md", "section": "Preferences"}},
    }


def _config(**updates: object) -> dict:
    value: dict = {
        "schema": "agent-skills.lesson-pages/v1",
        "skill": "lesson-pages",
        "page_targets": [{"id": "triton-pages", "collection": "docs/triton-learning/pages"}],
    }
    value.update(updates)
    return value


def test_configuration_is_canonical_and_requires_guide_learning() -> None:
    result = context_config.validate_materialized_context(_repository(), _config())
    assert result == {
        "context": {
            "schema": "agent-skills.lesson-pages-context/v1",
            "repository": {
                "schema": "agent-skills.repository/v1",
                "repository_id": "learning-fixture",
                "facts": {},
                "language": "zh-CN",
                "timezone": "Asia/Shanghai",
            },
            "page_targets": [
                {
                    "id": "triton-pages",
                    "collection": "docs/triton-learning/pages",
                    "format": "html",
                    "include_patterns": ["*.html"],
                }
            ],
        },
        "tracked_files": [],
        "tracked_collections": [],
        "write_paths": ["docs/triton-learning/pages"],
        "required_skills": ["guide-learning"],
    }


def test_targets_are_sorted_so_reordering_does_not_drift() -> None:
    targets = [
        {"id": "rust-pages", "collection": "docs/rust/pages"},
        {"id": "algo-pages", "collection": "docs/algo/pages"},
    ]
    forward = context_config.validate_materialized_context(_repository(), _config(page_targets=targets))
    backward = context_config.validate_materialized_context(_repository(), _config(page_targets=list(reversed(targets))))
    assert forward == backward
    assert [target["id"] for target in forward["context"]["page_targets"]] == ["algo-pages", "rust-pages"]
    assert forward["write_paths"] == ["docs/algo/pages", "docs/rust/pages"]


@pytest.mark.parametrize(
    "config",
    [
        _config(page_targets=[]),
        _config(page_targets="docs/pages"),
        {"schema": "agent-skills.lesson-pages/v1", "skill": "lesson-pages"},
        _config(schema="agent-skills.lesson-pages/v2"),
        _config(skill="guide-learning"),
        _config(authorization="always"),
        _config(repository_fact_refs=[]),
        _config(page_targets=[{"id": "a", "collection": "docs/pages", "filename_policy": "topic"}]),
        _config(page_targets=[{"id": "A", "collection": "docs/pages"}]),
        _config(page_targets=[{"id": "a"}]),
    ],
)
def test_unknown_missing_or_authority_fields_are_rejected(config: dict) -> None:
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(_repository(), config)


@pytest.mark.parametrize(
    "collection",
    [
        "/abs/pages",
        "../pages",
        "docs/../pages",
        "docs\\pages",
        "docs/pages/",
        "C:/pages",
        "docs//pages",
        "docs/CON/pages",
        ".git/pages",
        ".agents/skills/pages",
        ".claude/pages",
        ".agent-skills/pages",
        ".GIT/pages",
        ".git./pages",
        "docs/COM1/pages",
    ],
)
def test_collections_are_portable_and_outside_managed_roots(collection: str) -> None:
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(
            _repository(), _config(page_targets=[{"id": "a", "collection": collection}])
        )


@pytest.mark.parametrize(
    "second",
    ["docs/pages", "DOCS/Pages", "docs/pages/rust", "docs"],
)
def test_targets_must_not_overlap(second: str) -> None:
    targets = [{"id": "a", "collection": "docs/pages"}, {"id": "b", "collection": second}]
    with pytest.raises(context_config.ContextConfigError, match="separate"):
        context_config.validate_materialized_context(_repository(), _config(page_targets=targets))


def test_duplicate_target_ids_are_rejected() -> None:
    targets = [{"id": "a", "collection": "docs/one"}, {"id": "a", "collection": "docs/two"}]
    with pytest.raises(context_config.ContextConfigError, match="duplicate"):
        context_config.validate_materialized_context(_repository(), _config(page_targets=targets))


@pytest.mark.parametrize(
    "repository",
    [
        {"schema": "agent-skills.repository/v2", "repository_id": "x"},
        {"schema": "agent-skills.repository/v1", "repository_id": "Bad_Id"},
        {"schema": "agent-skills.repository/v1", "repository_id": "x", "extra": 1},
        {"schema": "agent-skills.repository/v1", "repository_id": "x", "language": "中文"},
        {"schema": "agent-skills.repository/v1", "repository_id": "x", "facts": []},
        {"schema": "agent-skills.repository/v1", "repository_id": "x", "timezone": "Asia/../../etc/passwd"},
    ],
)
def test_repository_config_stays_strict(repository: dict) -> None:
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(repository, _config())


def test_validator_never_selects_repository_facts() -> None:
    result = context_config.validate_materialized_context(_repository(), _config())
    assert result["context"]["repository"]["facts"] == {}
    assert result["tracked_files"] == [] and result["tracked_collections"] == []
