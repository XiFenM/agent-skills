from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import materialize_skills


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "creator-workflow"
EXPECTED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/artifact-contract.md",
    "references/capability-routing.md",
    "references/context-contract.md",
    "references/workflow-contract.md",
    "scripts/context_config.py",
    "scripts/creator_workflow.py",
    "tests/test_context_config.py",
    "tests/test_creator_workflow.py",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _init(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Creator Fixture")
    _git(root, "config", "user.email", "creator@example.com")
    _git(root, "config", "core.autocrlf", "false")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def test_creator_workflow_has_exact_progressive_disclosure_tree() -> None:
    actual = {
        path.relative_to(SKILL).as_posix()
        for path in SKILL.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    assert actual == EXPECTED_FILES
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in sorted(path.name for path in (SKILL / "references").glob("*.md")):
        assert f"(references/{reference})" in main
    assert len(main.splitlines()) < 500
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py", ".yaml"} and "__pycache__" not in path.parts
    ).casefold()
    for forbidden in ("d" + "aily-work", "pnpm zenmux", "projects/<slug>", "outputs/<slug>"):
        assert forbidden not in combined


def test_creator_materializes_strict_context_and_enforces_protected_package(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    central = consumer / ".agent-skills"
    consumer.mkdir()
    central.mkdir()
    shutil.copy2(ROOT / "catalog.json", central / "catalog.json")
    shutil.copytree(SKILL, central / "skills" / "creator-workflow", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    playwright_worktree = central / "vendor" / "microsoft-playwright-cli"
    shutil.copytree(
        ROOT / "vendor" / "microsoft-playwright-cli" / "skills" / "playwright-cli",
        playwright_worktree / "skills" / "playwright-cli",
    )
    _init(playwright_worktree)
    _git(playwright_worktree, "add", "-A")
    _git(playwright_worktree, "commit", "-q", "-m", "playwright capability")
    _init(central)
    _git(central, "add", "-A")
    _git(central, "commit", "-q", "-m", "creator capability")

    repository = {
        "schema": "agent-skills.repository/v1",
        "repository_id": "creator-consumer",
        "facts": {
            "guidelines": {"path": "AGENTS.md"},
            "package": {"path": "package.json"},
            "project-template": {"path": "projects/_template"},
            "publication-contract": {"path": ".pathnote/contract-lock.json"},
            "publication-template": {"path": ".pathnote/templates/publication"},
        },
    }
    config = {
        "schema": "agent-skills.creator-workflow/v1",
        "skill": "creator-workflow",
        "repository_fact_refs": [
            {"fact_id": "guidelines", "role": "repository-instructions", "kind": "file"},
            {"fact_id": "package", "role": "package-manifest", "kind": "file"},
            {"fact_id": "project-template", "role": "project-template", "kind": "collection"},
            {"fact_id": "publication-contract", "role": "publication-contract", "kind": "file"},
            {"fact_id": "publication-template", "role": "publication-template", "kind": "collection"},
        ],
        "storage": {
            "state_root": ".creator-workflow",
            "project_roots": [{"id": "projects", "path": "projects/managed"}],
            "work_roots": [{"id": "work", "path": "work/managed"}],
            "output_roots": [{"id": "outputs", "path": "outputs/managed"}],
            "publication_roots": [{"id": "publications", "path": "publications"}],
        },
        "routes": [
            {
                "id": "browser",
                "adapter": "selected-skill-v1",
                "skill": "playwright-cli",
                "effects": {
                    "billable": False,
                    "remote": True,
                    "destructive": False,
                    "publish": False,
                },
            },
            {
                "id": "check",
                "adapter": "package-script-v2",
                "manifest_fact_ref": "package",
                "script": "check",
                "subcommands": ["run"],
                "argument_bindings": [
                    {
                        "key": "target-path",
                            "kind": "target-path",
                        "required": False,
                        "cardinality": "one",
                    }
                ],
                "output_bindings": [],
                "effects": {
                    "billable": False,
                    "remote": False,
                    "destructive": False,
                    "publish": False,
                },
            },
        ],
        "profiles": [
            {"id": "content", "adapter": "generic-content-project-v1", "project_root": "projects", "work_root": "work", "output_root": "outputs", "template_fact_ref": "project-template", "routes": ["browser", "check"]},
            {"id": "publication", "adapter": "pathnote-publication-v1", "publication_root": "publications", "template_fact_ref": "publication-template", "contract_fact_ref": "publication-contract", "routes": ["browser", "check"]},
        ],
        "protected_roots": ["publications/existing-draft"],
    }
    _write_json(consumer / ".agent-skills.json", {"version": 2, "source": ".agent-skills", "skills": {"creator-workflow": ["codex"], "playwright-cli": ["codex"]}, "config": {"repository": ".agent-skills-config/repository.json", "skills": {"creator-workflow": ".agent-skills-config/creator-workflow.json"}}})
    _write_json(consumer / ".agent-skills-config" / "repository.json", repository)
    _write_json(consumer / ".agent-skills-config" / "creator-workflow.json", config)
    files = {
        "AGENTS.md": "rules\n",
        "package.json": "{}\n",
        "projects/_template/brief.md": "brief\n",
        ".pathnote/contract-lock.json": "{}\n",
        ".pathnote/templates/publication/publication.json": "{}\n",
        "publications/existing-draft/publication.json": "{}\n",
    }
    for relative, text in files.items():
        path = consumer / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (consumer / ".gitignore").write_text(".agent-skills/\n.agents/\n.agent-skills.state.json\n.agent-skills.lock\n", encoding="utf-8")
    _init(consumer)
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "configure creator")

    config_path = consumer / ".agent-skills.json"
    materialize_skills.synchronize(consumer, central, config_path)
    assert materialize_skills.check(consumer, central, config_path) == []
    installed = consumer / ".agents" / "skills" / "creator-workflow"
    assert (consumer / ".agents" / "skills" / "playwright-cli" / "SKILL.md").is_file()
    context_path = installed / materialize_skills.CONTEXT_FILE
    wrapper = json.loads(context_path.read_text(encoding="utf-8"))
    assert wrapper["allowlist"]["write_paths"] == [
        ".creator-workflow", "outputs/managed", "projects/managed", "publications", "work/managed"
    ]
    assert "publications/existing-draft/publication.json" not in wrapper["allowlist"]["tracked_files"]

    runtime = _load_module(installed / "scripts" / "creator_workflow.py", "installed_creator_runtime")
    managed = runtime.load_managed_context(consumer, context_path)
    proposal = {
        "schema": runtime.PROPOSAL_SCHEMA,
        "workflow_id": "publication-work",
        "operation_id": "write-new-package",
        "kind": "package",
        "profile_id": "publication",
        "route_id": "check",
        "summary": "Prepare a new publication package.",
        "inputs": [{
            "path": "package.json",
            "sha256": runtime._sha((consumer / "package.json").read_bytes()),
            "authority": "managed-fact",
        }],
        "targets": [{"path": "publications/new-package/publication.json", "before_sha256": runtime.ABSENT}],
        "dependencies": [],
        "parameters": {"subcommand": "run", "arguments": {"target-path": "publications/new-package/publication.json"}},
        "billable": False,
        "destructive": False,
        "remote": False,
    }
    assert runtime.prepare_managed_operation(consumer, managed, proposal)["operation_id"] == "write-new-package"
    proposal["targets"] = [{"path": "publications/existing-draft/publication.json", "before_sha256": runtime.ABSENT}]
    proposal["parameters"]["arguments"]["target-path"] = "publications/existing-draft/publication.json"
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.prepare_managed_operation(consumer, managed, proposal)
    assert _git(consumer, "status", "--porcelain") == ""
