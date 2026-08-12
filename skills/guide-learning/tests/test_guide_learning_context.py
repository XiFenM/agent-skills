from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    path = ROOT / "scripts" / "context_config.py"
    spec = importlib.util.spec_from_file_location("guide_learning_context_config", path)
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
        "facts": {
            "preferences": {
                "path": "learning/preferences.md",
                "section": "Preferences",
            },
            "sources": {"path": "learning/sources", "description": "Sources"},
            "validation": {"path": "docs/validation.md"},
        },
    }


def _config(**updates: object) -> dict:
    value: dict = {
        "schema": "agent-skills.guide-learning/v1",
        "skill": "guide-learning",
    }
    value.update(updates)
    return value


def test_minimal_configuration_is_canonical_and_empty() -> None:
    result = context_config.validate_materialized_context(_repository(), _config())
    assert set(result) == {
        "context",
        "tracked_files",
        "tracked_collections",
        "write_paths",
    }
    assert result["context"] == {
        "schema": "agent-skills.guide-learning-context/v1",
        "repository": {
            "schema": "agent-skills.repository/v1",
            "repository_id": "learning-fixture",
            "language": "zh-CN",
            "timezone": "Asia/Shanghai",
            "facts": {},
        },
        "repository_fact_refs": [],
        "record_mappings": {},
    }
    assert result["tracked_files"] == []
    assert result["tracked_collections"] == []
    assert result["write_paths"] == []


def test_facts_and_records_produce_separate_allowlists() -> None:
    result = context_config.validate_materialized_context(
        _repository(),
        _config(
            repository_fact_refs=[
                {"fact_id": "validation", "role": "validation-instructions", "kind": "file"},
                {"fact_id": "sources", "role": "source-catalog", "kind": "collection"},
            ],
            record_mappings={
                "checkpoint": {"path": "learning/state.md", "kind": "file", "section": "Checkpoint"},
                "program": {"path": "learning/state.md", "kind": "file", "section": "Program"},
                "lesson": {"path": "learning/lessons", "kind": "collection"},
                "practice-validation": {"path": "learning/validation", "kind": "collection"},
            },
        ),
    )
    assert list(result["context"]["repository"]["facts"]) == ["sources", "validation"]
    assert result["tracked_files"] == ["docs/validation.md"]
    assert result["tracked_collections"] == ["learning/sources"]
    assert result["write_paths"] == [
        "learning/lessons",
        "learning/state.md",
        "learning/validation",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "acceptance",
        "authorized",
        "continuous_progression",
        "mastery",
        "operations",
        "owner",
        "stage",
    ],
)
def test_behavior_and_authorization_fields_are_rejected(field: str) -> None:
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(
            _repository(), _config(**{field: True})
        )


def test_unknown_or_duplicate_repository_facts_are_rejected() -> None:
    for refs, message in (
        ([{"fact_id": "missing", "role": "source-catalog", "kind": "file"}], "unknown fact"),
        (
            [
                {"fact_id": "validation", "role": "validation-instructions", "kind": "file"},
                {"fact_id": "validation", "role": "legacy-evidence", "kind": "file"},
            ],
            "duplicate fact",
        ),
    ):
        with pytest.raises(context_config.ContextConfigError, match=message):
            context_config.validate_materialized_context(
                _repository(), _config(repository_fact_refs=refs)
            )


def test_collection_fact_cannot_claim_a_section() -> None:
    with pytest.raises(context_config.ContextConfigError, match="must not declare a section"):
        context_config.validate_materialized_context(
            _repository(),
            _config(
                repository_fact_refs=[
                    {"fact_id": "preferences", "role": "learner-preferences", "kind": "collection"}
                ]
            ),
        )


def test_checkpoint_and_collection_sections_are_strict() -> None:
    cases = (
        ({"checkpoint": {"path": "state", "kind": "collection"}}, "must use kind 'file'"),
        (
            {"lesson": {"path": "learning/lessons", "kind": "collection", "section": "Current"}},
            "only valid for a file",
        ),
    )
    for records, message in cases:
        with pytest.raises(context_config.ContextConfigError, match=message):
            context_config.validate_materialized_context(
                _repository(), _config(record_mappings=records)
            )


@pytest.mark.parametrize(
    "path",
    ["/absolute.md", "../escape.md", "bad\\path.md", "records/CON.txt", "bad<name>.md"],
)
def test_record_paths_are_portable_repository_relative_paths(path: str) -> None:
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(
            _repository(),
            _config(record_mappings={"program": {"path": path, "kind": "file"}}),
        )


def test_read_facts_and_mutable_records_must_not_overlap() -> None:
    with pytest.raises(context_config.ContextConfigError, match="overlaps read-only fact"):
        context_config.validate_materialized_context(
            _repository(),
            _config(
                repository_fact_refs=[
                    {"fact_id": "sources", "role": "source-catalog", "kind": "collection"}
                ],
                record_mappings={
                    "lesson": {"path": "learning/sources/current.md", "kind": "file"}
                },
            ),
        )


def test_record_roots_cannot_overlap_and_shared_files_need_distinct_sections() -> None:
    invalid = (
        {
            "lesson": {"path": "learning", "kind": "collection"},
            "session-events": {"path": "learning/events", "kind": "collection"},
        },
        {
            "program": {"path": "learning/state.md", "kind": "file"},
            "checkpoint": {"path": "learning/state.md", "kind": "file"},
        },
        {
            "program": {"path": "learning/state.md", "kind": "file", "section": "State"},
            "checkpoint": {"path": "learning/state.md", "kind": "file", "section": "state"},
        },
    )
    for records in invalid:
        with pytest.raises(context_config.ContextConfigError):
            context_config.validate_materialized_context(
                _repository(), _config(record_mappings=records)
            )
