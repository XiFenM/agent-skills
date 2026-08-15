from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from tools import materialize_skills

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIGURABLE_SKILLS = (
    "english-coach",
    "guide-learning",
    "memo-cards",
    "resource-planning",
    "study-log",
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _initialize_repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Context Fixture")
    _git(root, "config", "user.email", "context-fixture@example.com")
    _git(root, "config", "core.autocrlf", "false")


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _copy_clean_central(central: Path) -> None:
    central.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "catalog.json", central / "catalog.json")
    for name in CONFIGURABLE_SKILLS:
        shutil.copytree(
            REPOSITORY_ROOT / "skills" / name,
            central / "skills" / name,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
        )
    _initialize_repository(central)
    _commit_all(central, "copy configurable Skills")
    assert _git(central, "status", "--porcelain") == ""


def _repository_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "context-integration",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {
            "learning-goal": {
                "path": "facts/goal.md",
                "section": "Goal",
                "description": "Shared public learning goal",
            },
            "evidence-collection": {
                "path": "facts/evidence",
                "description": "Tracked evidence available to resource planning",
            },
        },
    }


def _english_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.english-coach/v1",
        "skill": "english-coach",
        "learner": {"cefr": "B2", "first_language": "zh-CN"},
        "target_registers": ["technical", "workplace"],
        "feedback_focus": ["collocation", "precision"],
        "repository_fact_refs": ["learning-goal"],
        "record_files": [
            {
                "id": "current-summary",
                "record_type": "lesson-summary",
                "path": "english/current-summary.md",
                "format": "markdown",
            }
        ],
        "record_collections": [
            {
                "id": "study-logs",
                "record_type": "structured-study-log",
                "path": "english/logs",
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


def _memo_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.memo-cards/v1",
        "skill": "memo-cards",
        "adapter": {
            "id": "markji",
            "client_version": "3.8.00",
            "profile": "default",
        },
        "input_collections": [
            {
                "id": "fixed-article",
                "kind": "article",
                "patterns": ["articles/fixed.md"],
            },
            {
                "id": "verified-notes",
                "kind": "verified-learning-note",
                "patterns": ["notes/*.md"],
            },
            {
                "id": "structured-study-logs",
                "kind": "structured-log",
                "patterns": ["english/logs/*.md"],
            }
        ],
        "output_collections": [
            {
                "id": "review-cards",
                "patterns": ["cards/*.md"],
                "inventory_patterns": ["cards/*.md"],
                "soft_target": {"minimum": 1, "maximum": 12},
            }
        ],
    }


def _guide_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.guide-learning/v1",
        "skill": "guide-learning",
        "repository_fact_refs": [
            {
                "fact_id": "learning-goal",
                "role": "learner-preferences",
                "kind": "file",
            },
            {
                "fact_id": "evidence-collection",
                "role": "evidence-artifacts",
                "kind": "collection",
            },
        ],
        "record_mappings": {
            "program": {
                "path": "learning/state.md",
                "kind": "file",
                "section": "Program",
            },
            "checkpoint": {
                "path": "learning/state.md",
                "kind": "file",
                "section": "Checkpoint",
            },
            "practice-artifacts": {
                "path": "learning/practice",
                "kind": "collection",
            },
        },
    }


def _study_log_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.study-log/v1",
        "skill": "study-log",
        "structured_targets": [
            {"id": "english-study-log", "path": "english/logs"}
        ],
    }


def _resource_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.resource-planning/v1",
        "skill": "resource-planning",
        "storage": {
            "registry_path": "managed/registry.json",
            "report_directory": "managed/reports",
            "research_brief_directory": "managed/briefs",
            "journal_path": "managed/.resource-planning-journal.json",
        },
        "preferences": {
            "bootstrap_days": 30,
            "decision_unit_soft_target": 5,
            "timezone": "Asia/Shanghai",
            "report_naming": "run-id",
        },
        "sources": [],
        "queries": [],
        "fact_refs": [
            {
                "fact_id": "evidence-collection",
                "kind": "collection",
                "required": False,
                "modules": ["systems"],
            }
        ],
        "overlays": [],
        "modules": [
            {
                "module_id": "systems",
                "display_name": "Systems",
                "aliases": ["distributed systems"],
                "portfolio_path": "curriculum/guide.md",
                "progress_projection": "curriculum/progress.md",
                "report_group": "core",
                "adapter": {
                    "adapter_id": "markdown-curriculum",
                    "version": 1,
                    "anchor": "## Resources",
                    "id_policy": "section-local-suffix",
                    "allowed_actions": ["add", "annotate", "replace", "retire"],
                    "status_terms": ["planned", "done"],
                    "priority_terms": ["high", "normal"],
                },
            }
        ],
    }


def _prepare_consumer(consumer: Path) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    repository = _repository_config()
    skill_configs = {
        "english-coach": _english_config(),
        "guide-learning": _guide_config(),
        "memo-cards": _memo_config(),
        "resource-planning": _resource_config(),
        "study-log": _study_log_config(),
    }
    paths = {
        "english-coach": ".agent-skills-config/english-coach.json",
        "guide-learning": ".agent-skills-config/guide-learning.json",
        "memo-cards": ".agent-skills-config/memo-cards.json",
        "resource-planning": ".agent-skills-config/resource-planning.json",
        "study-log": ".agent-skills-config/study-log.json",
    }
    config_path = consumer / ".agent-skills.json"
    _write_json(
        config_path,
        {
            "version": 2,
            "source": ".agent-skills",
            "skills": {name: ["codex", "claude"] for name in CONFIGURABLE_SKILLS},
            "config": {
                "repository": ".agent-skills-config/repository.json",
                "skills": paths,
            },
        },
    )
    _write_json(consumer / ".agent-skills-config" / "repository.json", repository)
    for name, value in skill_configs.items():
        _write_json(consumer / paths[name], value)

    tracked_files = {
        "articles/fixed.md": "# Fixed article\n\nA reviewed article.\n",
        "facts/goal.md": "# Goal\nLearn dependable systems concepts.\n",
        "facts/evidence/tracked.md": "tracked resource evidence\n",
        "notes/tracked.md": "# Verified note\n\nA reviewed source.\n",
        "cards/tracked.md": "# Existing legacy card\n",
        "english/current-summary.md": "# Current summary\n",
        "english/logs/tracked.md": "# Tracked study log\n",
        "learning/state.md": "# Learning state\n\n## Program\n\n## Checkpoint\n",
        "curriculum/guide.md": "# Guide\n\n## Resources\n",
    }
    for relative, body in tracked_files.items():
        path = consumer / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    binary_sibling = consumer / "articles" / "diagram.png"
    binary_sibling.write_bytes(b"\x89PNG\r\n\x1a\n\xff\x00")
    managed_workbook = consumer / "cards" / "tracked-technical-qa.xlsx"
    managed_workbook.write_bytes(b"PK\x03\x04\xff\x00 managed XLSX fixture")

    (consumer / ".gitignore").write_text(
        ".agent-skills/\n.agents/\n.claude/\n.agent-skills-state.json\n.agent-skills-sync.lock\n",
        encoding="utf-8",
    )
    _initialize_repository(consumer)
    _git(
        consumer,
        "add",
        ".gitignore",
        ".agent-skills.json",
        ".agent-skills-config",
        "articles/diagram.png",
        "cards/tracked-technical-qa.xlsx",
        *tracked_files,
    )
    _git(consumer, "commit", "-q", "-m", "configure shared Skills")

    # These deliberately match declared collection patterns but are neither staged
    # nor committed. Invalid UTF-8 makes accidental content reads fail loudly.
    for relative in (
        "notes/untracked.md",
        "cards/untracked.md",
        "facts/evidence/untracked.md",
    ):
        (consumer / relative).write_bytes(b"\xff\xfe private, untracked\n")
    return config_path, repository, skill_configs


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    old_dont_write_bytecode = sys.dont_write_bytecode
    sys.modules[name] = module
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old_dont_write_bytecode
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _assert_canonical_wrapper(
    wrapper_bytes: bytes,
    module: ModuleType,
    repository: dict[str, Any],
    skill_config: dict[str, Any],
) -> dict[str, Any]:
    wrapper = json.loads(wrapper_bytes.decode("utf-8"))
    assert wrapper_bytes == materialize_skills._json_bytes(wrapper)
    expected = module.validate_materialized_context(repository, skill_config)
    assert wrapper["version"] == 1
    assert wrapper["manager"] == "agent-skills"
    assert wrapper["repository_id"] == repository["repository_id"]
    assert wrapper["context"] == expected["context"]
    assert wrapper["allowlist"]["tracked_collections"] == expected["tracked_collections"]
    assert wrapper["allowlist"]["write_paths"] == expected["write_paths"]
    explicit = set(expected["tracked_files"])
    expanded = set(wrapper["allowlist"]["tracked_files"])
    assert explicit <= expanded
    assert all(
        any(path.startswith(collection + "/") for collection in expected["tracked_collections"])
        for path in expanded - explicit
    )
    return wrapper


def test_five_configurable_skills_materialize_shared_canonical_contexts(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    central = consumer / ".agent-skills"
    _copy_clean_central(central)
    config_path, repository, skill_configs = _prepare_consumer(consumer)

    messages = materialize_skills.synchronize(consumer, central, config_path)
    assert any("english-coach" in message for message in messages)
    assert any("guide-learning" in message for message in messages)
    assert any("memo-cards" in message for message in messages)
    assert any("resource-planning" in message for message in messages)
    assert any("study-log" in message for message in messages)
    assert materialize_skills.check(consumer, central, config_path) == []

    wrappers: dict[str, dict[str, Any]] = {}
    for name in CONFIGURABLE_SKILLS:
        codex_context = consumer / ".agents" / "skills" / name / materialize_skills.CONTEXT_FILE
        claude_context = consumer / ".claude" / "skills" / name / materialize_skills.CONTEXT_FILE
        codex_bytes = codex_context.read_bytes()
        assert codex_bytes == claude_context.read_bytes()
        script_name = {
            "english-coach": "context_config.py",
            "guide-learning": "context_config.py",
            "memo-cards": "memo_cards.py",
            "resource-planning": "resource_planning.py",
            "study-log": "context_config.py",
        }[name]
        module = _load_module(
            consumer / ".agents" / "skills" / name / "scripts" / script_name,
            f"context_integration_{name.replace('-', '_')}",
        )
        wrappers[name] = _assert_canonical_wrapper(
            codex_bytes, module, repository, skill_configs[name]
        )
        if name == "memo-cards":
            verified = module.verify(consumer, codex_context)
            assert [item["path"] for item in verified["legacy_inventory"]] == [
                "cards/tracked.md"
            ]
        elif name == "resource-planning":
            assert module.validate_runtime_wrapper(wrappers[name]) == wrappers[name]
            module._validate_source_binding(consumer, wrappers[name])

    memo_files = wrappers["memo-cards"]["allowlist"]["tracked_files"]
    assert "articles/fixed.md" in memo_files
    assert "articles/diagram.png" not in memo_files
    assert "notes/tracked.md" in memo_files
    assert "cards/tracked.md" in memo_files
    assert "cards/tracked-technical-qa.xlsx" in memo_files
    assert "english/logs/tracked.md" in memo_files
    assert "notes/untracked.md" not in memo_files
    assert "cards/untracked.md" not in memo_files

    resource_files = wrappers["resource-planning"]["allowlist"]["tracked_files"]
    assert "facts/evidence/tracked.md" in resource_files
    assert "facts/evidence/untracked.md" not in resource_files
    guide_files = wrappers["guide-learning"]["allowlist"]["tracked_files"]
    assert "facts/goal.md" in guide_files
    assert "facts/evidence/tracked.md" in guide_files
    assert "facts/evidence/untracked.md" not in guide_files
    assert wrappers["guide-learning"]["allowlist"]["write_paths"] == [
        "learning/practice",
        "learning/state.md",
    ]
    assert not (consumer / "learning" / "practice").exists()

    study_wrapper = wrappers["study-log"]
    assert study_wrapper["allowlist"] == {
        "tracked_files": [],
        "tracked_collections": [],
        "write_paths": ["english/logs"],
    }
    serialized_study = json.dumps(study_wrapper, ensure_ascii=False)
    for forbidden in ("archive_root", "private_root", "session_dirs", "boundary"):
        assert forbidden not in serialized_study
    assert materialize_skills.check(consumer, central, config_path) == []
