from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import resource_planning as rp  # noqa: E402


def _bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_bytes(value))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_slot(text: str, slot: str, content: str) -> str:
    start = f"<!-- resource-slot:{slot}:start -->\n"
    end = f"<!-- resource-slot:{slot}:end -->"
    prefix, remainder = text.split(start, 1)
    _old, suffix = remainder.split(end, 1)
    return prefix + start + content + end + suffix


def _configs() -> tuple[dict, dict]:
    repository = {
        "schema": "agent-skills.repository/v1",
        "repository_id": "synthetic-learning",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {
            "learning-goal": {"path": "facts/goal.md", "section": "Goal"},
            "evidence-collection": {"path": "facts/evidence", "description": "Tracked evidence notes"},
        },
    }
    skill = {
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
        "sources": [
            {
                "source_id": "official-feed",
                "kind": "feed",
                "locator": "https://example.test/feed",
                "modules": ["systems"],
                "role_hint": "normative-primary",
                "enabled": True,
                "cadence": "weekly",
                "resource_types": ["paper", "code"],
            }
        ],
        "queries": [
            {
                "query_id": "systems-query",
                "all_terms": ["distributed systems"],
                "any_terms": ["collective"],
                "exclude_terms": ["advertisement"],
                "domains": ["example.test"],
                "resource_types": ["paper"],
                "modules": ["systems"],
                "enabled": True,
            }
        ],
        "fact_refs": [
            {"fact_id": "learning-goal", "kind": "file", "required": True, "modules": ["systems"]},
            {"fact_id": "evidence-collection", "kind": "collection", "required": False, "modules": ["systems"]},
        ],
        "overlays": [
            {
                "overlay_id": "summer-focus",
                "fact_refs": ["learning-goal"],
                "modules": ["systems"],
                "source_ids": ["official-feed"],
                "query_ids": ["systems-query"],
                "priority": 10,
                "valid_from": "2026-08-01",
                "valid_until": "2026-08-31",
            }
        ],
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
    return repository, skill


@pytest.fixture()
def managed_repo(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "consumer"
    (repo / "facts").mkdir(parents=True)
    (repo / "curriculum").mkdir()
    (repo / "managed" / "reports").mkdir(parents=True)
    (repo / "managed" / "briefs").mkdir()
    (repo / "facts" / "goal.md").write_text("# Goal\nBuild systems knowledge.\n", encoding="utf-8")
    (repo / "facts" / "evidence").mkdir()
    (repo / "facts" / "evidence" / "tracked.md").write_text("tracked evidence\n", encoding="utf-8")
    (repo / "facts" / "evidence" / "untracked.tmp").write_text("must remain invisible\n", encoding="utf-8")
    slot = (
        "<!-- resource-slot:resources-after-existing:start -->\n"
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Existing\n"
        "<!-- resource-slot:resources-after-existing:end -->\n"
    )
    (repo / "curriculum" / "guide.md").write_bytes(
        f"# Guide\n\n## Resources\n\n{slot}".encode("utf-8")
    )
    (repo / "curriculum" / "progress.md").write_bytes(
        f"# Progress\n\n{slot}".encode("utf-8")
    )
    repository, skill = _configs()
    repository_path = repo / ".agent-skills-config" / "repository.json"
    skill_path = repo / ".agent-skills-config" / "resource-planning.json"
    _write_json(repository_path, repository)
    _write_json(skill_path, skill)
    validated = rp.validate_materialized_context(repository, skill)
    wrapper = {
        "version": 1,
        "manager": "agent-skills",
        "skill": "resource-planning",
        "repository_id": "synthetic-learning",
        "sources": {
            "repository": {"path": ".agent-skills-config/repository.json", "digest": _sha(repository_path)},
            "skill": {"path": ".agent-skills-config/resource-planning.json", "digest": _sha(skill_path)},
        },
        "context": validated["context"],
        "allowlist": {key: validated[key] for key in ("tracked_files", "tracked_collections", "write_paths")},
    }
    wrapper["allowlist"]["tracked_files"] = sorted([*wrapper["allowlist"]["tracked_files"], "facts/evidence/tracked.md"])
    context_path = repo / ".agents" / "skills" / "resource-planning" / ".agent-skills-context.json"
    _write_json(context_path, wrapper)
    return {"repo": repo, "wrapper": wrapper, "context": context_path.relative_to(repo).as_posix(), "repository": repository, "skill": skill}


def _resource() -> dict:
    return {
        "identity": {"kind": "doi", "value": "https://doi.org/10.1234/Example.1"},
        "revision_key": "published-2026",
        "title": "A Durable Systems Resource",
        "canonical_locator": "https://doi.org/10.1234/example.1",
        "aliases": ["https://example.test/resource"],
        "modules": ["systems"],
        "relations": [],
        "claims": [
            {
                "text": "The resource explains a concrete systems mechanism.",
                "status": "verified",
                "scope": "published-2026 text",
                "evidence": [
                    {
                        "locator": "https://doi.org/10.1234/example.1",
                        "role": "normative-primary",
                        "checked_at": "2026-08-11T10:00:00+08:00",
                        "direction": "supports",
                        "note": "method section",
                    }
                ],
            }
        ],
    }


def _refresh_proposal(*, source_status: str = "blocked") -> dict:
    source_coverage = {
        "scope_kind": "source",
        "scope_id": "official-feed",
        "status": source_status,
        "covered_from": "2026-08-01T10:00:00+08:00",
        "covered_to": "2026-08-11T10:00:00+08:00",
        "basis": "bootstrap",
        "detail": "synthetic partial failure" if source_status == "blocked" else "complete",
    }
    if source_status in {"covered", "no-hit"}:
        source_coverage["cursor_after"] = "2026-08-11T10:00:00+08:00"
    return {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "refresh",
        "prepared_at": "2026-08-11T10:00:00+08:00",
        "dependencies": [],
        "writes": [
            {
                "path": "managed/reports/refresh-001.md",
                "role": "report",
                "after_text": "# Refresh\n\nOne qualified candidate; one blocked source.\n",
                "decision_unit_ids": [],
            }
        ],
        "refresh": {
            "run_id": "refresh-001",
            "active_overlays": ["summer-focus"],
            "coverage": [
                source_coverage,
                {
                    "scope_kind": "query",
                    "scope_id": "systems-query",
                    "status": "no-hit",
                    "covered_from": "2026-08-01T10:00:00+08:00",
                    "covered_to": "2026-08-11T10:00:00+08:00",
                    "basis": "bootstrap",
                    "cursor_after": "2026-08-11T10:00:00+08:00",
                },
            ],
            "resources": [_resource()],
            "candidates": [
                {
                    "identity": {"kind": "doi", "value": "10.1234/example.1"},
                    "revision_key": "published-2026",
                    "module_id": "systems",
                    "action": "add",
                    "target_slot": "resources-after-existing",
                    "claim_refs": [
                        {
                            "text": "The resource explains a concrete systems mechanism.",
                            "scope": "published-2026 text",
                        }
                    ],
                    "preserve_learning_state": ["completion", "notes"],
                    "review_after": "2026-08-11T09:00:00+08:00",
                    "state": "qualified",
                    "reason": "identity, primary evidence, and scope passed hard gates",
                }
            ],
        },
    }


def _envelope(plan: dict) -> dict:
    return {
        "schema": "agent-skills.resource-execution/v1",
        "operation_kind": plan["operation_kind"],
        "txn_id": plan["txn_id"],
        "preview_digest": plan["preview_digest"],
        "decision_unit_ids": [unit["decision_unit_id"] for unit in plan["decision_units"]],
        "authorized": True,
    }


def _publish_refresh(state: dict[str, object]) -> dict:
    plan = rp.prepare_plan(state["repo"], state["wrapper"], state["context"], _refresh_proposal())
    result = rp.publish_plan(state["repo"], state["wrapper"], plan, _envelope(plan))
    assert result["status"] == "applied"
    return plan


def _apply_first_candidate(
    state: dict[str, object], *, run_id: str = "review-apply"
) -> tuple[dict, dict]:
    repo = state["repo"]
    registry = json.loads((repo / "managed" / "registry.json").read_text(encoding="utf-8"))
    candidate = registry["candidates"][0]
    guide = repo / "curriculum" / "guide.md"
    after = _replace_slot(
        guide.read_text(encoding="utf-8"),
        candidate["target_slot"],
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Existing\n"
        "- Applied durable resource\n",
    )
    proposal = {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "review",
        "prepared_at": "2026-08-11T12:00:00+08:00",
        "dependencies": [],
        "writes": [
            {
                "path": "curriculum/guide.md",
                "role": "portfolio",
                "after_text": after,
                "module_id": "systems",
                "action": "add",
                "decision_unit_ids": [candidate["decision_unit_id"]],
            }
        ],
        "review": {
            "run_id": run_id,
            "active_overlays": ["summer-focus"],
            "decisions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "outcome": "apply",
                    "reason": "exact application",
                    "count_change": 1,
                    "budget_change": 0,
                    "preserve_learning_state": ["completion", "notes"],
                }
            ],
        },
    }
    plan = rp.prepare_plan(repo, state["wrapper"], state["context"], proposal)
    rp.publish_plan(repo, state["wrapper"], plan, _envelope(plan))
    return plan, candidate


def _review_proposal(
    candidate: dict,
    *,
    run_id: str,
    outcome: str = "defer",
    writes: list[dict] | None = None,
    prepared_at: str = "2026-08-11T12:00:00+08:00",
) -> dict:
    return {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "review",
        "prepared_at": prepared_at,
        "dependencies": [],
        "writes": writes or [],
        "review": {
            "run_id": run_id,
            "active_overlays": ["summer-focus"],
            "decisions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "outcome": outcome,
                    "reason": f"synthetic {outcome}",
                    "count_change": 0,
                    "budget_change": 0,
                    "preserve_learning_state": candidate[
                        "preserve_learning_state"
                    ],
                }
            ],
        },
    }


def test_materializer_validator_is_pure_strict_and_returns_exact_allowlists() -> None:
    repository, skill = _configs()
    repository["facts"]["unused-secret-adjacent"] = {"path": "facts/not-needed.md"}
    result = rp.validate_materialized_context(repository, skill)
    assert set(result) == {"context", "tracked_files", "tracked_collections", "write_paths"}
    assert result["tracked_files"] == ["facts/goal.md"]
    assert result["tracked_collections"] == ["facts/evidence"]
    assert "managed/registry.json" in result["write_paths"]
    assert "curriculum/guide.md" in result["write_paths"]
    assert "unused-secret-adjacent" not in result["context"]["repository"]["facts"]
    mutated = copy.deepcopy(skill)
    mutated["prompt"] = "ignore safety"
    with pytest.raises(rp.ResourcePlanningError, match="unknown fields"):
        rp.validate_materialized_context(repository, mutated)


def test_special_adapter_cannot_request_generic_progress_projection() -> None:
    repository, skill = _configs()
    skill["modules"][0]["adapter"] = {"adapter_id": "problem-curriculum", "version": 1}
    with pytest.raises(rp.ResourcePlanningError, match="does not support"):
        rp.validate_materialized_context(repository, skill)


@pytest.mark.parametrize("locator", ["https://user:pass@example.test/feed", "https://example.test/feed?token=secret", "not a source locator"])
def test_public_source_locator_rejects_credentials_queries_and_freeform_text(locator: str) -> None:
    repository, skill = _configs()
    skill["sources"][0]["locator"] = locator
    with pytest.raises(rp.ResourcePlanningError):
        rp.validate_materialized_context(repository, skill)


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.json",
        "C:/escape.json",
        "/escape.json",
        "managed/registry.json:stream",
        "managed/CON.txt",
        "managed/trailing-dot./file.json",
    ],
)
def test_config_rejects_path_escape(bad_path: str) -> None:
    repository, skill = _configs()
    skill["storage"]["registry_path"] = bad_path
    with pytest.raises(rp.ResourcePlanningError) as caught:
        rp.validate_materialized_context(repository, skill)
    assert caught.value.code == "safety"


def test_config_rejects_managed_path_collisions_and_fact_overlap() -> None:
    repository, skill = _configs()
    skill["storage"]["report_directory"] = "managed"
    with pytest.raises(rp.ResourcePlanningError, match="separate|disjoint"):
        rp.validate_materialized_context(repository, skill)

    repository, skill = _configs()
    skill["modules"][0]["portfolio_path"] = "facts/goal.md"
    with pytest.raises(rp.ResourcePlanningError, match="overlaps a repository fact"):
        rp.validate_materialized_context(repository, skill)

    repository, skill = _configs()
    skill["modules"][0]["portfolio_path"] = "FACTS/GOAL.MD"
    with pytest.raises(rp.ResourcePlanningError, match="overlaps a repository fact"):
        rp.validate_materialized_context(repository, skill)


def test_research_brief_is_independent_of_registry_and_reports(
    managed_repo: dict[str, object],
) -> None:
    repo = managed_repo["repo"]
    registry_path = repo / "managed" / "registry.json"
    registry_path.write_text("not registry JSON\n", encoding="utf-8")
    proposal = {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "research-brief",
        "prepared_at": "2026-08-11T10:00:00+08:00",
        "dependencies": [],
        "writes": [
            {
                "path": "managed/briefs/independent.md",
                "role": "research-brief",
                "after_text": "# Independent research brief\n",
                "decision_unit_ids": [],
            }
        ],
        "research": {
            "brief_id": "independent",
            "active_overlays": ["summer-focus"],
        },
    }

    plan = rp.prepare_plan(
        repo, managed_repo["wrapper"], managed_repo["context"], proposal
    )
    assert [target["role"] for target in plan["targets"]] == ["research-brief"]
    assert "managed/registry.json" not in {
        dependency["path"] for dependency in plan["dependencies"]
    }
    result = rp.publish_plan(
        repo, managed_repo["wrapper"], plan, _envelope(plan)
    )
    assert result["status"] == "applied"
    assert registry_path.read_text(encoding="utf-8") == "not registry JSON\n"


def test_identity_is_two_layered_and_exact() -> None:
    assert rp.normalize_work_id({"kind": "arxiv", "value": "arXiv:2401.01234v3"})[0] == "arxiv:2401.01234"
    assert rp.normalize_work_id({"kind": "github", "value": "https://github.com/Owner/Repo.git"})[0] == "github:owner/repo"
    first = rp.normalize_work_id({"kind": "url", "value": "HTTPS://Example.COM/a/#fragment"})[0]
    assert first == "url:https://example.com/a"


def test_qualified_candidate_requires_every_key_claim_to_have_direct_support(
    managed_repo: dict[str, object],
) -> None:
    proposal = _refresh_proposal()
    proposal["refresh"]["resources"][0]["claims"].append(
        {
            "text": "An unverified benchmark claim",
            "status": "unverified",
            "scope": "unknown hardware",
            "evidence": [
                {
                    "locator": "search snippet",
                    "role": "discovery-index",
                    "checked_at": "2026-08-11T10:00:00+08:00",
                    "direction": "context",
                }
            ],
        }
    )
    proposal["refresh"]["candidates"][0]["claim_refs"].append(
        {"text": "An unverified benchmark claim", "scope": "unknown hardware"}
    )
    with pytest.raises(rp.ResourcePlanningError, match="every key claim"):
        rp.prepare_plan(
            managed_repo["repo"],
            managed_repo["wrapper"],
            managed_repo["context"],
            proposal,
        )


def test_evidence_checked_after_prepare_is_rejected(
    managed_repo: dict[str, object],
) -> None:
    proposal = _refresh_proposal()
    proposal["refresh"]["resources"][0]["claims"][0]["evidence"][0][
        "checked_at"
    ] = "2026-08-11T10:00:01+08:00"
    with pytest.raises(rp.ResourcePlanningError, match="after prepared_at"):
        rp.prepare_plan(
            managed_repo["repo"],
            managed_repo["wrapper"],
            managed_repo["context"],
            proposal,
        )


def test_event_reducer_rejects_projection_drift() -> None:
    events: list[dict] = []
    rp._event("cand_x", events, "draft", at="2026-08-11T10:00:00+08:00", run_id="r1", operation_kind="refresh", reason="new")
    rp._event("cand_x", events, "qualified", at="2026-08-11T10:00:00+08:00", run_id="r1", operation_kind="refresh", reason="gates")
    assert rp.reduce_events(events) == "qualified"
    events[1]["from_state"] = "blocked"
    with pytest.raises(rp.ResourcePlanningError, match="disagrees"):
        rp.reduce_events(events)


def _candidate_with_state(candidate_id: str, state: str, action: str) -> dict:
    events: list[dict] = []
    rp._event(candidate_id, events, "draft", at="2026-08-11T08:00:00+08:00", run_id="seed", operation_kind="refresh", reason="seed")
    rp._event(candidate_id, events, "qualified", at="2026-08-11T08:00:00+08:00", run_id="seed", operation_kind="refresh", reason="qualified")
    if state == "applied":
        rp._event(candidate_id, events, "approved", at="2026-08-11T09:00:00+08:00", run_id="seed-review", operation_kind="review", reason="approved", preview_digest="a" * 64)
        rp._event(candidate_id, events, "applied", at="2026-08-11T09:00:00+08:00", run_id="seed-review", operation_kind="review", reason="applied")
    return {"candidate_id": candidate_id, "decision_unit_id": f"du-{candidate_id}", "action": action, "events": events, "current_state": state}


def test_replace_and_retire_split_new_and_old_lifecycle() -> None:
    old = _candidate_with_state("old", "applied", "add")
    new = _candidate_with_state("new", "qualified", "replace")
    registry = {"candidates": [old, new]}
    rp._apply_review_decision(
        registry,
        {"candidate_id": "new", "outcome": "apply", "reason": "exact replacement approved", "replaces_candidate_id": "old"},
        at="2026-08-11T10:00:00+08:00",
        run_id="replace-review",
    )
    assert new["current_state"] == "applied"
    assert old["current_state"] == "superseded"

    retiring = _candidate_with_state("retiring", "applied", "add")
    rp._apply_review_decision(
        {"candidates": [retiring]},
        {"candidate_id": "retiring", "outcome": "retire", "reason": "confirmed retirement"},
        at="2026-08-11T11:00:00+08:00",
        run_id="retire-review",
    )
    assert retiring["current_state"] == "stale"


def test_prepare_refresh_is_zero_write_and_partial_failure_does_not_advance_cursor(managed_repo: dict[str, object]) -> None:
    repo = managed_repo["repo"]
    before = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))
    plan = rp.prepare_plan(repo, managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    after = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))
    assert before == after
    assert [target["role"] for target in plan["targets"]] == ["report", "registry"]
    dependency_paths = {item["path"] for item in plan["dependencies"]}
    assert "facts/evidence/tracked.md" in dependency_paths
    assert "facts/evidence/untracked.tmp" not in dependency_paths
    registry = json.loads(__import__("base64").b64decode(plan["targets"][-1]["after_base64"]).decode())
    assert registry["coverage"] == [
        {
            "cursor": "2026-08-11T10:00:00+08:00",
            "last_successful_run": "refresh-001",
            "scope_id": "systems-query",
            "scope_kind": "query",
            "updated_at": "2026-08-11T10:00:00+08:00",
        }
    ]
    assert all(candidate["current_state"] not in {"approved", "applied"} for candidate in registry["candidates"])
    report = __import__("base64").b64decode(plan["targets"][0]["after_base64"]).decode()
    assert '"registry_generation": 1' in report
    assert '"run_id": "refresh-001"' in report


@pytest.mark.parametrize("remaining", ["source", "query", "none"])
def test_refresh_must_account_for_every_configured_scope(
    managed_repo: dict[str, object], remaining: str
) -> None:
    proposal = _refresh_proposal()
    if remaining == "source":
        proposal["refresh"]["coverage"] = [
            item
            for item in proposal["refresh"]["coverage"]
            if item["scope_kind"] == "source"
        ]
    elif remaining == "query":
        proposal["refresh"]["coverage"] = [
            item
            for item in proposal["refresh"]["coverage"]
            if item["scope_kind"] == "query"
        ]
    else:
        proposal["refresh"]["coverage"] = []
    with pytest.raises(rp.ResourcePlanningError, match="every configured source and query"):
        rp.prepare_plan(
            managed_repo["repo"],
            managed_repo["wrapper"],
            managed_repo["context"],
            proposal,
        )


def test_possible_duplicate_relation_never_auto_merges_distinct_exact_identities(managed_repo: dict[str, object]) -> None:
    proposal = _refresh_proposal()
    second = copy.deepcopy(_resource())
    second.update(
        {
            "identity": {"kind": "url", "value": "https://example.test/independent-work"},
            "canonical_locator": "https://example.test/independent-work",
            "aliases": [],
            "relations": [
                {
                    "kind": "possible_duplicate",
                    "target_identity": {"kind": "doi", "value": "10.1234/example.1"},
                    "target_revision_key": "published-2026",
                }
            ],
        }
    )
    proposal["refresh"]["resources"].append(second)
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], proposal)
    registry = json.loads(__import__("base64").b64decode(plan["targets"][-1]["after_base64"]).decode())
    assert len(registry["resources"]) == 2
    independent = next(item for item in registry["resources"] if item["work_id"].startswith("url:"))
    assert independent["relations"][0]["kind"] == "possible_duplicate"


def test_soft_decision_target_does_not_truncate_six_qualified_units(managed_repo: dict[str, object]) -> None:
    proposal = _refresh_proposal(source_status="no-hit")
    proposal["refresh"]["resources"] = []
    proposal["refresh"]["candidates"] = []
    for index in range(6):
        resource = copy.deepcopy(_resource())
        resource.update(
            {
                "identity": {"kind": "native", "value": f"catalog:item-{index}"},
                "revision_key": "v1",
                "title": f"Resource {index}",
                "canonical_locator": f"catalog:item-{index}",
                "aliases": [],
            }
        )
        proposal["refresh"]["resources"].append(resource)
        proposal["refresh"]["candidates"].append(
            {
                "identity": {"kind": "native", "value": f"catalog:item-{index}"},
                "revision_key": "v1",
                "module_id": "systems",
                "action": "add",
                "target_slot": f"slot-{index}",
                "claim_refs": [
                    {
                        "text": "The resource explains a concrete systems mechanism.",
                        "scope": "published-2026 text",
                    }
                ],
                "preserve_learning_state": [],
                "review_after": "2026-08-11T09:00:00+08:00",
                "state": "qualified",
                "reason": "synthetic hard gates passed",
            }
        )
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], proposal)
    assert len(plan["decision_units"]) == 6


def test_no_configured_bootstrap_means_no_hidden_thirty_day_default(managed_repo: dict[str, object]) -> None:
    wrapper = copy.deepcopy(managed_repo["wrapper"])
    repository = copy.deepcopy(managed_repo["repository"])
    skill = copy.deepcopy(managed_repo["skill"])
    del skill["preferences"]["bootstrap_days"]
    skill_path = managed_repo["repo"] / ".agent-skills-config" / "resource-planning.json"
    _write_json(skill_path, skill)
    validated = rp.validate_materialized_context(repository, skill)
    wrapper["context"] = validated["context"]
    wrapper["allowlist"] = {key: validated[key] for key in ("tracked_files", "tracked_collections", "write_paths")}
    wrapper["allowlist"]["tracked_files"] = sorted([*wrapper["allowlist"]["tracked_files"], "facts/evidence/tracked.md"])
    wrapper["sources"]["skill"]["digest"] = _sha(skill_path)
    _write_json(managed_repo["repo"] / Path(managed_repo["context"]), wrapper)
    with pytest.raises(rp.ResourcePlanningError, match="without a configured bootstrap_days"):
        rp.prepare_plan(managed_repo["repo"], wrapper, managed_repo["context"], _refresh_proposal())


def test_runtime_rejects_wrapper_context_not_derived_from_bound_source_bytes(managed_repo: dict[str, object]) -> None:
    wrapper = copy.deepcopy(managed_repo["wrapper"])
    wrapper["context"]["configuration"]["preferences"]["decision_unit_soft_target"] = 7
    _write_json(managed_repo["repo"] / Path(managed_repo["context"]), wrapper)
    with pytest.raises(rp.ResourcePlanningError, match="does not match its bound config source bytes"):
        rp.prepare_plan(managed_repo["repo"], wrapper, managed_repo["context"], _refresh_proposal())


def test_refresh_publish_is_atomic_immutable_and_idempotent(managed_repo: dict[str, object]) -> None:
    plan = _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    report = repo / "managed" / "reports" / "refresh-001.md"
    report_bytes = report.read_bytes()
    registry = json.loads((repo / "managed" / "registry.json").read_text(encoding="utf-8"))
    assert registry["generation"] == 1
    assert registry["runs"][0]["report"]["sha256"] == hashlib.sha256(report_bytes).hexdigest()
    retry = rp.publish_plan(repo, managed_repo["wrapper"], plan, _envelope(plan))
    assert retry["status"] == "already-applied"
    assert report.read_bytes() == report_bytes
    verified = rp.verify_repository(repo, managed_repo["wrapper"], managed_repo["context"], "2026-08-11T11:00:00+08:00")
    assert len(verified["ready_candidate_ids"]) == 1


def test_cas_drift_invalidates_preview_without_writing(managed_repo: dict[str, object]) -> None:
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    guide = managed_repo["repo"] / "curriculum" / "guide.md"
    guide.write_text(guide.read_text(encoding="utf-8") + "human edit\n", encoding="utf-8")
    with pytest.raises(rp.ResourcePlanningError, match="dependency changed"):
        rp.publish_plan(managed_repo["repo"], managed_repo["wrapper"], plan, _envelope(plan))
    assert not (managed_repo["repo"] / "managed" / "registry.json").exists()
    assert not (managed_repo["repo"] / "managed" / "reports" / "refresh-001.md").exists()


def test_review_records_approved_then_applied_and_never_rewrites_report(managed_repo: dict[str, object]) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    report = repo / "managed" / "reports" / "refresh-001.md"
    report_before = report.read_bytes()
    registry = json.loads((repo / "managed" / "registry.json").read_text(encoding="utf-8"))
    candidate = registry["candidates"][0]
    guide = repo / "curriculum" / "guide.md"
    new_guide = _replace_slot(
        guide.read_text(encoding="utf-8"),
        "resources-after-existing",
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Existing\n"
        "- Durable resource (10.1234/example.1)\n",
    )
    proposal = {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "review",
        "prepared_at": "2026-08-11T12:00:00+08:00",
        "dependencies": [],
        "writes": [
            {
                "path": "curriculum/guide.md",
                "role": "portfolio",
                "after_text": new_guide,
                "module_id": "systems",
                "action": "add",
                "decision_unit_ids": [candidate["decision_unit_id"]],
            }
        ],
        "review": {
            "run_id": "review-001",
            "active_overlays": ["summer-focus"],
            "decisions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "outcome": "apply",
                    "reason": "user approved the exact addition",
                    "count_change": 1,
                    "budget_change": 1,
                    "preserve_learning_state": ["completion", "notes"],
                }
            ],
        },
    }
    plan = rp.prepare_plan(repo, managed_repo["wrapper"], managed_repo["context"], proposal)
    registry_after = json.loads(__import__("base64").b64decode(plan["targets"][-1]["after_base64"]).decode())
    states = [event["to_state"] for event in registry_after["candidates"][0]["events"]]
    assert states[-2:] == ["approved", "applied"]
    approved = registry_after["candidates"][0]["events"][-2]
    assert approved["preview_digest"] == plan["preview_digest"]
    rp.publish_plan(repo, managed_repo["wrapper"], plan, _envelope(plan))
    assert report.read_bytes() == report_before
    assert "Durable resource" in guide.read_text(encoding="utf-8")


def test_registry_only_review_outcome_cannot_modify_portfolio(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    candidate = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )["candidates"][0]
    guide = repo / "curriculum" / "guide.md"
    after = _replace_slot(
        guide.read_text(encoding="utf-8"),
        candidate["target_slot"],
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Illicit defer edit\n",
    )
    write = {
        "path": "curriculum/guide.md",
        "role": "portfolio",
        "after_text": after,
        "module_id": "systems",
        "action": "add",
        "decision_unit_ids": [candidate["decision_unit_id"]],
    }
    proposal = _review_proposal(
        candidate, run_id="defer-with-write", writes=[write]
    )
    with pytest.raises(rp.ResourcePlanningError, match="must not bind module writes"):
        rp.prepare_plan(repo, managed_repo["wrapper"], managed_repo["context"], proposal)


@pytest.mark.parametrize(
    "violation", ["outside-slot", "protected-state", "missing-slot"]
)
def test_adapter_enforces_scoped_diff_and_learning_state_preservation(
    managed_repo: dict[str, object], violation: str
) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    candidate = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )["candidates"][0]
    guide = repo / "curriculum" / "guide.md"
    if violation == "outside-slot":
        after = guide.read_text(encoding="utf-8") + "outside managed slot\n"
        expected = "outside authorized resource slots"
    elif violation == "protected-state":
        after = _replace_slot(
            guide.read_text(encoding="utf-8"),
            candidate["target_slot"],
            '<!-- resource-state:{"completion":"done","notes":"keep"} -->\n'
            "- Existing\n- Changed\n",
        )
        expected = "protected learning-state"
    else:
        unrelated = (
            "# Guide\n\n## Resources\n\n"
            "<!-- resource-slot:unrelated:start -->\n"
            "- Existing\n"
            "<!-- resource-slot:unrelated:end -->\n"
        )
        guide.write_bytes(unrelated.encode("utf-8"))
        after = _replace_slot(unrelated, "unrelated", "- Existing\n- Changed\n")
        expected = "absent from the adapter document"
    write = {
        "path": "curriculum/guide.md",
        "role": "portfolio",
        "after_text": after,
        "module_id": "systems",
        "action": "add",
        "decision_unit_ids": [candidate["decision_unit_id"]],
    }
    proposal = _review_proposal(
        candidate, run_id=f"adapter-{violation}", outcome="apply", writes=[write]
    )
    with pytest.raises(rp.ResourcePlanningError, match=expected):
        rp.prepare_plan(repo, managed_repo["wrapper"], managed_repo["context"], proposal)


def test_problem_adapter_reuses_scoped_parser_without_progress(
    managed_repo: dict[str, object],
) -> None:
    repo = managed_repo["repo"]
    repository = copy.deepcopy(managed_repo["repository"])
    skill = copy.deepcopy(managed_repo["skill"])
    module = skill["modules"][0]
    module.pop("progress_projection")
    module["adapter"]["adapter_id"] = "problem-curriculum"
    repository_path = repo / ".agent-skills-config" / "repository.json"
    skill_path = repo / ".agent-skills-config" / "resource-planning.json"
    _write_json(skill_path, skill)
    validated = rp.validate_materialized_context(repository, skill)
    wrapper = {
        "version": 1,
        "manager": "agent-skills",
        "skill": "resource-planning",
        "repository_id": "synthetic-learning",
        "sources": {
            "repository": {
                "path": ".agent-skills-config/repository.json",
                "digest": _sha(repository_path),
            },
            "skill": {
                "path": ".agent-skills-config/resource-planning.json",
                "digest": _sha(skill_path),
            },
        },
        "context": validated["context"],
        "allowlist": {
            key: validated[key]
            for key in ("tracked_files", "tracked_collections", "write_paths")
        },
    }
    wrapper["allowlist"]["tracked_files"] = sorted(
        [*wrapper["allowlist"]["tracked_files"], "facts/evidence/tracked.md"]
    )
    _write_json(repo / Path(managed_repo["context"]), wrapper)
    managed_repo["wrapper"] = wrapper
    managed_repo["skill"] = skill

    _publish_refresh(managed_repo)
    plan, _candidate = _apply_first_candidate(managed_repo)
    module_targets = [
        target for target in plan["targets"] if target["role"] != "registry"
    ]
    assert [target["role"] for target in module_targets] == ["portfolio"]
    assert module_targets[0]["adapter_id"] == "problem-curriculum"


def test_tampered_historical_report_blocks_prepare_and_publish(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    registry = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )
    candidate = registry["candidates"][0]
    proposal = _review_proposal(candidate, run_id="defer-report-cas")
    plan = rp.prepare_plan(
        repo, managed_repo["wrapper"], managed_repo["context"], proposal
    )
    report = repo / "managed" / "reports" / "refresh-001.md"
    report.write_bytes(b"tampered after preview\n")
    with pytest.raises(rp.ResourcePlanningError, match="immutable report"):
        rp.publish_plan(repo, managed_repo["wrapper"], plan, _envelope(plan))


def test_review_registry_evolution_cannot_discover_resources(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    registry_path = repo / "managed" / "registry.json"
    candidate = json.loads(registry_path.read_text(encoding="utf-8"))["candidates"][0]
    plan = rp.prepare_plan(
        repo,
        managed_repo["wrapper"],
        managed_repo["context"],
        _review_proposal(candidate, run_id="review-no-discovery"),
    )
    after_registry = json.loads(
        base64.b64decode(plan["targets"][-1]["after_base64"]).decode("utf-8")
    )
    after_registry["resources"][0]["title"] = "Illicit review discovery"
    with pytest.raises(rp.ResourcePlanningError, match="must not discover"):
        rp._validate_registry_evolution(
            registry_path.read_bytes(),
            rp.validate_registry(after_registry),
            plan["preview_digest"],
            plan["operation_kind"],
            plan["prepared_at"],
            plan["active_overlays"],
            [unit["decision_unit_id"] for unit in plan["decision_units"]],
        )


def test_refresh_registry_run_is_bound_to_exact_report_target(
    managed_repo: dict[str, object],
) -> None:
    plan = rp.prepare_plan(
        managed_repo["repo"],
        managed_repo["wrapper"],
        managed_repo["context"],
        _refresh_proposal(),
    )
    registry_target = plan["targets"][-1]
    registry = json.loads(
        base64.b64decode(registry_target["after_base64"]).decode("utf-8")
    )
    registry["runs"][-1]["report"]["path"] = "managed/reports/phantom.md"
    after = rp._render_json(registry)
    before = None
    registry_target["after_base64"] = base64.b64encode(after).decode("ascii")
    registry_target["after_sha256"] = rp._sha256(after)
    registry_target["diff"] = rp._unified_diff(
        registry_target["path"], before, after
    )
    plan["preview_digest"] = rp._plan_preview_digest(plan)
    decision_ids = [unit["decision_unit_id"] for unit in plan["decision_units"]]
    plan["txn_id"] = rp._stable_id(
        "txn", plan["operation_kind"], plan["preview_digest"], decision_ids
    )

    with pytest.raises(rp.ResourcePlanningError, match="exact immutable report"):
        rp.validate_plan(plan, managed_repo["wrapper"])


def test_tampered_historical_report_blocks_prepare(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    repo = managed_repo["repo"]
    candidate = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )["candidates"][0]
    (repo / "managed" / "reports" / "refresh-001.md").write_bytes(
        b"tampered before prepare\n"
    )
    with pytest.raises(rp.ResourcePlanningError, match="immutable report"):
        rp.prepare_plan(
            repo,
            managed_repo["wrapper"],
            managed_repo["context"],
            _review_proposal(candidate, run_id="defer-after-tamper"),
        )


def test_historical_approval_digest_does_not_block_later_transactions(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    first_review, _candidate = _apply_first_candidate(managed_repo)
    proposal = _refresh_proposal(source_status="no-hit")
    proposal["prepared_at"] = "2026-08-11T13:00:00+08:00"
    proposal["writes"][0]["path"] = "managed/reports/refresh-002.md"
    proposal["refresh"]["run_id"] = "refresh-002"
    proposal["refresh"]["resources"] = []
    proposal["refresh"]["candidates"] = []
    for coverage in proposal["refresh"]["coverage"]:
        coverage["covered_to"] = "2026-08-11T13:00:00+08:00"
        coverage["cursor_after"] = "2026-08-11T13:00:00+08:00"
        if coverage["scope_kind"] == "source":
            coverage["covered_from"] = "2026-08-11T12:00:00+08:00"
            coverage["basis"] = "bootstrap"
        else:
            coverage["covered_from"] = "2026-08-11T10:00:00+08:00"
            coverage["basis"] = "cursor"
    plan = rp.prepare_plan(
        managed_repo["repo"],
        managed_repo["wrapper"],
        managed_repo["context"],
        proposal,
    )
    registry_after = json.loads(
        __import__("base64").b64decode(plan["targets"][-1]["after_base64"])
    )
    historical_approval = next(
        event
        for candidate in registry_after["candidates"]
        for event in candidate["events"]
        if event["to_state"] == "approved"
    )
    assert historical_approval["preview_digest"] == first_review["preview_digest"]
    assert historical_approval["preview_digest"] != plan["preview_digest"]
    rp.publish_plan(
        managed_repo["repo"],
        managed_repo["wrapper"],
        plan,
        _envelope(plan),
    )


def test_review_decision_unit_cannot_write_another_module(
    managed_repo: dict[str, object],
) -> None:
    repo = managed_repo["repo"]
    repository = copy.deepcopy(managed_repo["repository"])
    skill = copy.deepcopy(managed_repo["skill"])
    skill["modules"].append(
        {
            "module_id": "algorithms",
            "display_name": "Algorithms",
            "aliases": [],
            "portfolio_path": "curriculum/algorithms.md",
            "adapter": {
                "adapter_id": "markdown-curriculum",
                "version": 1,
                "anchor": "## Resources",
            },
        }
    )
    algorithm_text = (
        "# Algorithms\n\n## Resources\n\n"
        "<!-- resource-slot:resources-after-existing:start -->\n"
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Existing algorithm\n"
        "<!-- resource-slot:resources-after-existing:end -->\n"
    )
    (repo / "curriculum" / "algorithms.md").write_bytes(
        algorithm_text.encode("utf-8")
    )
    skill_path = repo / ".agent-skills-config" / "resource-planning.json"
    _write_json(skill_path, skill)
    validated = rp.validate_materialized_context(repository, skill)
    wrapper = copy.deepcopy(managed_repo["wrapper"])
    wrapper["context"] = validated["context"]
    wrapper["allowlist"] = {
        key: validated[key]
        for key in ("tracked_files", "tracked_collections", "write_paths")
    }
    wrapper["allowlist"]["tracked_files"] = sorted(
        [*wrapper["allowlist"]["tracked_files"], "facts/evidence/tracked.md"]
    )
    wrapper["sources"]["skill"]["digest"] = _sha(skill_path)
    _write_json(repo / Path(managed_repo["context"]), wrapper)
    managed_repo["wrapper"] = wrapper
    _publish_refresh(managed_repo)

    candidate = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )["candidates"][0]
    after = _replace_slot(
        algorithm_text,
        candidate["target_slot"],
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Wrong-module edit\n",
    )
    write = {
        "path": "curriculum/algorithms.md",
        "role": "portfolio",
        "after_text": after,
        "module_id": "algorithms",
        "action": "add",
        "decision_unit_ids": [candidate["decision_unit_id"]],
    }
    proposal = _review_proposal(
        candidate, run_id="cross-module", outcome="apply", writes=[write]
    )
    with pytest.raises(rp.ResourcePlanningError, match="module disagrees"):
        rp.prepare_plan(repo, wrapper, managed_repo["context"], proposal)


def test_replace_binds_same_slot_and_both_decision_sides(
    managed_repo: dict[str, object],
) -> None:
    _publish_refresh(managed_repo)
    _first_review, old_candidate = _apply_first_candidate(managed_repo)
    repo = managed_repo["repo"]

    refresh = _refresh_proposal(source_status="covered")
    refresh["prepared_at"] = "2026-08-11T13:00:00+08:00"
    refresh["writes"][0]["path"] = "managed/reports/refresh-replace.md"
    refresh["refresh"]["run_id"] = "refresh-replace"
    replacement_resource = copy.deepcopy(_resource())
    replacement_resource.update(
        {
            "identity": {"kind": "native", "value": "catalog:replacement"},
            "revision_key": "v2",
            "title": "Replacement Resource",
            "canonical_locator": "catalog:replacement",
            "aliases": [],
        }
    )
    refresh["refresh"]["resources"] = [replacement_resource]
    refresh["refresh"]["candidates"] = [
        {
            "identity": {"kind": "native", "value": "catalog:replacement"},
            "revision_key": "v2",
            "module_id": "systems",
            "action": "replace",
            "target_slot": old_candidate["target_slot"],
            "claim_refs": [
                {
                    "text": "The resource explains a concrete systems mechanism.",
                    "scope": "published-2026 text",
                }
            ],
            "preserve_learning_state": ["completion", "notes"],
            "review_after": "2026-08-11T12:30:00+08:00",
            "state": "qualified",
            "reason": "replacement passed hard gates",
        }
    ]
    for coverage in refresh["refresh"]["coverage"]:
        coverage["covered_to"] = "2026-08-11T13:00:00+08:00"
        coverage["cursor_after"] = "2026-08-11T13:00:00+08:00"
        if coverage["scope_kind"] == "source":
            coverage["covered_from"] = "2026-08-11T12:00:00+08:00"
            coverage["basis"] = "bootstrap"
        else:
            coverage["covered_from"] = "2026-08-11T10:00:00+08:00"
            coverage["basis"] = "cursor"
    refresh_plan = rp.prepare_plan(
        repo, managed_repo["wrapper"], managed_repo["context"], refresh
    )
    rp.publish_plan(
        repo,
        managed_repo["wrapper"],
        refresh_plan,
        _envelope(refresh_plan),
    )

    registry = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )
    new_candidate = next(
        candidate
        for candidate in registry["candidates"]
        if candidate["action"] == "replace"
    )
    guide = repo / "curriculum" / "guide.md"
    after = _replace_slot(
        guide.read_text(encoding="utf-8"),
        new_candidate["target_slot"],
        '<!-- resource-state:{"completion":"planned","notes":"keep"} -->\n'
        "- Replacement resource\n",
    )
    review = {
        "schema": "agent-skills.resource-proposal/v1",
        "operation_kind": "review",
        "prepared_at": "2026-08-11T14:00:00+08:00",
        "dependencies": [],
        "writes": [
            {
                "path": "curriculum/guide.md",
                "role": "portfolio",
                "after_text": after,
                "module_id": "systems",
                "action": "replace",
                "decision_unit_ids": [new_candidate["decision_unit_id"]],
            }
        ],
        "review": {
            "run_id": "review-replace",
            "active_overlays": ["summer-focus"],
            "decisions": [
                {
                    "candidate_id": new_candidate["candidate_id"],
                    "outcome": "apply",
                    "reason": "exact replacement",
                    "count_change": 0,
                    "budget_change": 0,
                    "preserve_learning_state": ["completion", "notes"],
                    "replaces_candidate_id": old_candidate["candidate_id"],
                }
            ],
        },
    }
    plan = rp.prepare_plan(
        repo, managed_repo["wrapper"], managed_repo["context"], review
    )
    assert plan["decision_units"][0]["replaces_candidate_id"] == old_candidate[
        "candidate_id"
    ]
    assert plan["targets"][0]["replaces_decision_unit_ids"] == [
        old_candidate["decision_unit_id"]
    ]
    rp.publish_plan(repo, managed_repo["wrapper"], plan, _envelope(plan))
    final_registry = json.loads(
        (repo / "managed" / "registry.json").read_text(encoding="utf-8")
    )
    states = {
        candidate["candidate_id"]: candidate["current_state"]
        for candidate in final_registry["candidates"]
    }
    assert states[old_candidate["candidate_id"]] == "superseded"
    assert states[new_candidate["candidate_id"]] == "applied"


def test_recovery_rolls_back_a_provable_before_after_mix(managed_repo: dict[str, object]) -> None:
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    repo = managed_repo["repo"]
    journal_path = repo / "managed" / ".resource-planning-journal.json"
    journal = {"schema": rp.JOURNAL_SCHEMA, "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "phase": "prepared", "completed": [], "plan": plan}
    rp._create_journal(journal_path, journal)
    first = plan["targets"][0]
    target_path = repo / Path(first["path"])
    rp._atomic_replace(target_path, __import__("base64").b64decode(first["after_base64"]), rp.ABSENT)
    journal["phase"] = "replacing"
    journal["completed"] = [first["path"]]
    rp._update_journal(journal_path, journal)
    result = rp.recover_transaction(repo, managed_repo["wrapper"])
    assert result["status"] == "rolled-back"
    assert not target_path.exists()
    assert not journal_path.exists()


def test_publish_failure_at_registry_replacement_rolls_back_report(managed_repo: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    original = rp._atomic_replace

    def fail_registry(path: Path, content: bytes, expected_sha256: str) -> None:
        if path.name == "registry.json":
            raise OSError("synthetic registry replacement failure")
        original(path, content, expected_sha256)

    monkeypatch.setattr(rp, "_atomic_replace", fail_registry)
    with pytest.raises(rp.ResourcePlanningError, match="rolled back"):
        rp.publish_plan(managed_repo["repo"], managed_repo["wrapper"], plan, _envelope(plan))
    assert not (managed_repo["repo"] / "managed" / "reports" / "refresh-001.md").exists()
    assert not (managed_repo["repo"] / "managed" / "registry.json").exists()
    assert not (managed_repo["repo"] / "managed" / ".resource-planning-journal.json").exists()


def test_recovery_stops_on_third_state(managed_repo: dict[str, object]) -> None:
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    repo = managed_repo["repo"]
    journal_path = repo / "managed" / ".resource-planning-journal.json"
    journal = {"schema": rp.JOURNAL_SCHEMA, "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "phase": "prepared", "completed": [], "plan": plan}
    rp._create_journal(journal_path, journal)
    (repo / "managed" / "reports" / "refresh-001.md").write_text("third state\n", encoding="utf-8")
    with pytest.raises(rp.ResourcePlanningError, match="third-state"):
        rp.recover_transaction(repo, managed_repo["wrapper"])
    assert journal_path.exists()


def test_recovery_rejects_tampered_journal(managed_repo: dict[str, object]) -> None:
    plan = rp.prepare_plan(managed_repo["repo"], managed_repo["wrapper"], managed_repo["context"], _refresh_proposal())
    repo = managed_repo["repo"]
    journal_path = repo / "managed" / ".resource-planning-journal.json"
    journal = {"schema": rp.JOURNAL_SCHEMA, "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "phase": "prepared", "completed": [], "plan": plan}
    rp._create_journal(journal_path, journal)
    tampered = json.loads(journal_path.read_text(encoding="utf-8"))
    tampered["phase"] = "validating"
    _write_json(journal_path, tampered)
    with pytest.raises(rp.ResourcePlanningError, match="journal digest"):
        rp.recover_transaction(repo, managed_repo["wrapper"])
    assert journal_path.exists()


def test_source_has_no_network_subprocess_or_git_runtime() -> None:
    source = (SCRIPT_DIR / "resource_planning.py").read_text(encoding="utf-8")
    forbidden = ["import socket", "import subprocess", "from subprocess", "requests.", "http.client", "git "]
    assert all(token not in source for token in forbidden)
    assert "--force" not in source
    assert "--skip-cas" not in source
    assert "--accept-latest" not in source
