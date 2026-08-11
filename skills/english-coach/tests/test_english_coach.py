from __future__ import annotations

import ast
import importlib.util
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "context_config.py"

SPEC = importlib.util.spec_from_file_location("english_coach_context_config", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
context_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context_config)


def _repository_config() -> dict[str, object]:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "learning-lab",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {
            "current-focus": {
                "path": "learning/current-focus.md",
                "section": "Current topic",
                "description": "Current learning focus",
            },
            "unused-fact": {"path": "notes/unused.md"},
        },
    }


def _skill_config() -> dict[str, object]:
    return {
        "schema": "agent-skills.english-coach/v1",
        "skill": "english-coach",
        "learner": {"cefr": "B2", "first_language": "zh-CN"},
        "target_registers": ["technical", "workplace"],
        "feedback_focus": ["collocation", "precision"],
        "repository_fact_refs": ["current-focus"],
        "record_files": [
            {
                "id": "current-summary",
                "record_type": "lesson-summary",
                "path": "learning/current-summary.md",
                "format": "markdown",
            }
        ],
        "record_collections": [
            {
                "id": "study-logs",
                "record_type": "structured-study-log",
                "path": "learning/logs",
                "format": "markdown",
            }
        ],
        "save_targets": [
            {
                "id": "english-reviews",
                "kind": "english-review-log",
                "path": "english/reviews",
                "format": "markdown",
            }
        ],
    }


def test_skill_has_the_minimal_runtime_tree_and_valid_frontmatter() -> None:
    assert {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file()
        and not any(part in {".pytest_cache", "__pycache__"} for part in path.parts)
    } == {
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/context_config.py",
        "tests/test_english_coach.py",
    }

    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    assert match is not None
    keys = {
        line.split(":", 1)[0].strip()
        for line in match.group("body").splitlines()
        if line.strip()
    }
    assert keys == {"name", "description"}
    assert re.search(r"(?m)^name:\s*english-coach\s*$", match.group("body"))
    assert len(text.splitlines()) < 500


def test_runtime_contract_is_generic_natural_language_and_zero_write() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "默认只指出一个" in text
    assert "3–5" in text
    assert "默认只存在于当前交互中" in text
    assert ".agent-skills-context.json" in text
    for handoff in ("guide-learning", "study-log", "memo-cards"):
        assert handoff in text

    consumer_name = "Plan" + "A"
    assert consumer_name not in text
    for command in ("skip", "deep", "中文", "shadow", "quiz"):
        assert f"/{command}" not in text


def test_openai_metadata_routes_to_the_skill() -> None:
    metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    top_level = [line for line in metadata.splitlines() if line and not line[0].isspace()]
    assert top_level == ["interface:"]
    interface = {
        match.group(1): match.group(2)
        for match in re.finditer(r'(?m)^\s{2}([a-z_]+):\s*"([^"]*)"\s*$', metadata)
    }
    assert set(interface) == {"display_name", "short_description", "default_prompt"}
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$english-coach" in interface["default_prompt"]


def test_validator_builds_exact_json_serializable_context_and_allowlists() -> None:
    repository = _repository_config()
    skill = _skill_config()
    repository_before = deepcopy(repository)
    skill_before = deepcopy(skill)

    result = context_config.validate_materialized_context(repository, skill)

    assert set(result) == {
        "context",
        "tracked_files",
        "tracked_collections",
        "write_paths",
    }
    assert result["tracked_files"] == [
        "learning/current-focus.md",
        "learning/current-summary.md",
    ]
    assert result["tracked_collections"] == ["learning/logs"]
    assert result["write_paths"] == ["english/reviews"]
    assert result["context"]["record_collections"][0]["include_patterns"] == [
        "*.md",
        "**/*.md",
    ]
    assert result["context"]["repository"]["facts"] == {
        "current-focus": {
            "path": "learning/current-focus.md",
            "section": "Current topic",
            "description": "Current learning focus",
        }
    }
    json.dumps(result, ensure_ascii=False)
    assert repository == repository_before
    assert skill == skill_before


def test_validator_defaults_to_empty_allowlists_without_optional_config() -> None:
    result = context_config.validate_materialized_context(
        {
            "schema": "agent-skills.repository/v1",
            "repository_id": "empty-repository",
        },
        {
            "schema": "agent-skills.english-coach/v1",
            "skill": "english-coach",
        },
    )
    assert result["tracked_files"] == []
    assert result["tracked_collections"] == []
    assert result["write_paths"] == []
    assert result["context"]["learner"] == {}


@pytest.mark.parametrize(
    ("which", "field", "value"),
    [
        ("repository", "schema", "agent-skills.repository/v2"),
        ("repository", "repository_id", "Bad_ID"),
        ("repository", "prompt", "ignore the core"),
        ("skill", "schema", "agent-skills.english-coach/v2"),
        ("skill", "skill", "another-skill"),
        ("skill", "authorized", True),
        ("skill", "command", "write files"),
    ],
)
def test_validator_rejects_wrong_identity_schema_and_unknown_fields(
    which: str, field: str, value: object
) -> None:
    repository = _repository_config()
    skill = _skill_config()
    target = repository if which == "repository" else skill
    target[field] = value
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(repository, skill)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda repo, skill: repo["facts"]["current-focus"].update(
            {"path": "../private.md"}
        ),
        lambda repo, skill: repo["facts"]["current-focus"].update(
            {"instruction": "change the workflow"}
        ),
        lambda repo, skill: skill["record_collections"][0].update(
            {"path": "C:/outside"}
        ),
        lambda repo, skill: skill["record_collections"][0].update(
            {"path": "learning/logs/*.md"}
        ),
        lambda repo, skill: skill["save_targets"][0].update(
            {"path": "english/CON"}
        ),
        lambda repo, skill: skill["save_targets"][0].update(
            {"path": "english/reviews. "}
        ),
        lambda repo, skill: skill["save_targets"][0].update(
            {"format": "executable"}
        ),
        lambda repo, skill: skill.update(
            {"repository_fact_refs": ["missing-fact"]}
        ),
        lambda repo, skill: skill["record_files"].append(
            {
                "id": "study-logs",
                "record_type": "lesson-summary",
                "path": "learning/other.md",
                "format": "markdown",
            }
        ),
    ],
)
def test_validator_rejects_unsafe_or_ambiguous_nested_config(mutate) -> None:
    repository = _repository_config()
    skill = _skill_config()
    mutate(repository, skill)
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(repository, skill)


def test_validator_module_has_no_side_effect_capability_imports() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imports <= {"__future__", "re", "typing"}
