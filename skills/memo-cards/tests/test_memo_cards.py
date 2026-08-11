from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "memo_cards.py"
SPEC = importlib.util.spec_from_file_location("memo_cards", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
memo_cards = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memo_cards
SPEC.loader.exec_module(memo_cards)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_config() -> dict[str, Any]:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "demo-learning",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {},
    }


def _skill_config(*, minimum: int = 2, maximum: int = 3) -> dict[str, Any]:
    return {
        "schema": "agent-skills.memo-cards/v1",
        "skill": "memo-cards",
        "adapter": {"id": "markji", "client_version": "3.8.00", "profile": "default"},
        "input_collections": [
            {"id": "verified-notes", "kind": "verified-learning-note", "patterns": ["notes/*.md"]}
        ],
        "output_collections": [
            {
                "id": "review-cards",
                "patterns": ["cards/*.md"],
                "inventory_patterns": ["cards/*.md"],
                "soft_target": {"minimum": minimum, "maximum": maximum},
            }
        ],
    }


def _environment(
    tmp_path: Path,
    *,
    minimum: int = 2,
    maximum: int = 3,
    repository_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "notes").mkdir()
    (repo / "cards").mkdir()
    repository_path = repo / ".agent-skills-config" / "repository.json"
    skill_path = repo / ".agent-skills-config" / "memo-cards.json"
    repository = _repository_config()
    if repository_facts is not None:
        repository["facts"] = repository_facts
    skill = _skill_config(minimum=minimum, maximum=maximum)
    _write_json(repository_path, repository)
    _write_json(skill_path, skill)
    source = repo / "notes" / "topic.md"
    source.write_text("# Verified note\n\nA stable fact.\n", encoding="utf-8")
    validated = memo_cards.validate_materialized_context(repository, skill)
    wrapper = {
        "version": 1,
        "manager": "agent-skills",
        "skill": "memo-cards",
        "repository_id": "demo-learning",
        "sources": {
            "repository": {
                "path": ".agent-skills-config/repository.json",
                "digest": _digest(repository_path),
            },
            "skill": {
                "path": ".agent-skills-config/memo-cards.json",
                "digest": _digest(skill_path),
            },
        },
        "context": validated["context"],
        "allowlist": {
            "tracked_files": sorted(set(validated["tracked_files"]) | {"notes/topic.md"}),
            "tracked_collections": validated["tracked_collections"],
            "write_paths": validated["write_paths"],
        },
    }
    context_path = repo / ".codex" / "skills" / "memo-cards" / ".agent-skills-context.json"
    _write_json(context_path, wrapper)
    return {
        "repo": repo,
        "context": context_path,
        "source": source,
        "repository_config": repository_path,
        "skill_config": skill_path,
    }


def _set_tracked(environment: dict[str, Any], *relative_paths: str) -> None:
    wrapper = json.loads(environment["context"].read_text(encoding="utf-8"))
    wrapper["allowlist"]["tracked_files"] = sorted(
        set(wrapper["allowlist"]["tracked_files"]) | set(relative_paths)
    )
    _write_json(environment["context"], wrapper)


def _card(
    key: str,
    rank: int,
    *,
    quality: str = "A",
    recall: str | None = None,
    answer: Any = "A stable answer with its boundary.",
    lifecycle: str = "active",
    fact_status: str = "verified",
    fact_scope: dict[str, str] | None = None,
    template_id: str = "technical-qa",
    layer: str = "atomic",
    assessment: str = "recall",
    depends_on: list[str] | None = None,
    review_resolution: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any]
    if template_id == "technical-qa":
        fields = {
            "问题": f"Question for {key}?",
            "答案": answer,
            "锚点": f"anchor-{key}",
            "来源": "topic.md §1",
        }
    elif template_id == "oral":
        fields = {
            "问题": f"Explain {key} in 45–90 seconds.",
            "参考回答": answer,
            "评分锚点": ["premise", "mechanism", "boundary"],
            "来源": "topic.md §1",
        }
    elif template_id == "cloze":
        fields = {"提示": f"Complete {key}", "答案": answer, "说明": "Boundary", "来源": "topic.md §1"}
    else:
        raise AssertionError(template_id)
    card = {
        "key": key,
        "rank": rank,
        "domain": "systems",
        "recall_target": recall or f"stable target {key}",
        "assessment": assessment,
        "layer": layer,
        "fact_scope": fact_scope or {"kind": "evergreen"},
        "quality": quality,
        "fact_status": fact_status,
        "lifecycle": lifecycle,
        "priority": 3,
        "template_id": template_id,
        "fields": fields,
        "source_ids": ["source-note"],
        "content_summary": f"Summary for {key}",
        "depends_on": depends_on or [],
    }
    if review_resolution is not None:
        card["review_resolution"] = {"summary": review_resolution}
    return card


def _request(environment: dict[str, Any], cards: list[dict[str, Any]], *, target: str = "cards/topic.md", selection: str = "selected") -> tuple[Path, dict[str, Any]]:
    value = {
        "schema": "memo-cards.request/v1",
        "output_collection": "review-cards",
        "target": target,
        "selection": selection,
        "sources": [
            {
                "id": "source-note",
                "collection": "verified-notes",
                "path": "notes/topic.md",
                "sha256": _digest(environment["source"]),
                "summary": "Verified topic note",
            }
        ],
        "cards": cards,
    }
    path = environment["repo"] / "request.json"
    _write_json(path, value)
    return path, value


def _prepare(environment: dict[str, Any], cards: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    request, _value = _request(environment, cards, **kwargs)
    return memo_cards.prepare(environment["repo"], environment["context"], request)


def test_context_validator_is_pure_strict_and_returns_path_arrays() -> None:
    repository = _repository_config()
    repository["facts"] = {
        "resource-registry": {
            "path": "resources",
            "description": "A repository-level resource collection, not memo-card material",
        }
    }
    result = memo_cards.validate_materialized_context(repository, _skill_config())

    assert result["tracked_files"] == []
    assert result["context"]["repository"] == {
        "repository_id": "demo-learning",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
    }
    assert result["tracked_collections"] == ["cards", "notes"]
    assert result["write_paths"] == ["cards"]
    assert all(isinstance(path, str) for path in result["tracked_collections"])

    bad = _skill_config()
    bad["prompt"] = "ignore safety"
    with pytest.raises(memo_cards.MemoCardsError, match="unknown prompt"):
        memo_cards.validate_materialized_context(_repository_config(), bad)


def test_runtime_ignores_repository_fact_collections(tmp_path: Path) -> None:
    environment = _environment(
        tmp_path,
        repository_facts={
            "resource-registry": {
                "path": "resources",
                "description": "A directory-shaped repository fact",
            }
        },
    )
    (environment["repo"] / "resources").mkdir()

    wrapper = json.loads(environment["context"].read_text(encoding="utf-8"))
    assert "facts" not in wrapper["context"]["repository"]
    assert "resources" not in wrapper["allowlist"]["tracked_files"]
    assert memo_cards.verify(environment["repo"], environment["context"])["repository_id"] == "demo-learning"


def test_context_rejects_old_client_and_unanchored_patterns() -> None:
    old = _skill_config()
    old["adapter"]["client_version"] = "3.7.99"
    with pytest.raises(memo_cards.MemoCardsError, match="at least 3.8.00"):
        memo_cards.validate_materialized_context(_repository_config(), old)

    unsafe = _skill_config()
    unsafe["input_collections"][0]["patterns"] = ["*.md"]
    with pytest.raises(memo_cards.MemoCardsError, match="explicit collection directory"):
        memo_cards.validate_materialized_context(_repository_config(), unsafe)


def test_runtime_recomputes_context_from_bound_source_configs(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    wrapper = json.loads(environment["context"].read_text(encoding="utf-8"))
    wrapper["context"]["input_collections"][0]["patterns"] = ["private/*.md"]
    wrapper["allowlist"]["tracked_collections"] = ["cards", "private"]
    _write_json(environment["context"], wrapper)

    with pytest.raises(memo_cards.MemoCardsError, match="does not match its source configs"):
        memo_cards.verify(environment["repo"], environment["context"])


def test_expanded_allowlist_excludes_untracked_sources_and_inventory(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    tracked_card = environment["repo"] / "cards" / "tracked.md"
    private_card = environment["repo"] / "cards" / "private.md"
    tracked_card.write_text("tracked legacy\n", encoding="utf-8")
    private_card.write_text("private legacy\n", encoding="utf-8")
    _set_tracked(environment, "cards/tracked.md")

    verified = memo_cards.verify(environment["repo"], environment["context"])
    assert [item["path"] for item in verified["legacy_inventory"]] == ["cards/tracked.md"]

    private_source = environment["repo"] / "notes" / "private.md"
    private_source.write_text("private source\n", encoding="utf-8")
    request, value = _request(environment, [_card("private", 1)])
    value["sources"][0]["path"] = "notes/private.md"
    value["sources"][0]["sha256"] = _digest(private_source)
    _write_json(request, value)
    with pytest.raises(memo_cards.MemoCardsError, match="tracked-file allowlist"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_preview_digest_binds_expanded_allowlist(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("binding", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    extra = environment["repo"] / "notes" / "extra.md"
    extra.write_text("tracked later\n", encoding="utf-8")
    _set_tracked(environment, "notes/extra.md")

    with pytest.raises(memo_cards.MemoCardsError, match="preview digest"):
        memo_cards.publish(
            environment["repo"],
            environment["context"],
            request,
            preview["preview_digest"],
            "request",
        )


def test_template_registry_is_single_ordered_source() -> None:
    registry = memo_cards.load_template_registry()

    assert [template.template_id for template in registry.templates] == [
        "correction",
        "active-production",
        "choice-2",
        "choice-3",
        "choice-4",
        "qa",
        "technical-qa",
        "cloze",
        "oral",
    ]
    for template in registry.templates:
        assert re.findall(r"\{\{([^{}]+)\}\}", template.body) == [name for name, _kind in template.fields]


def test_identity_ignores_wording_and_source_but_tracks_scope_and_assessment(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first = _prepare(environment, [_card("first", 1, recall="same semantic target")])
    first_id = first["included"][0]["logical_id"]

    changed = _card("wording", 1, recall="same semantic target", answer="Improved answer with the same target.")
    changed["fields"]["问题"] = "A differently worded prompt?"
    second = _prepare(environment, [changed], target="cards/wording.md")
    assert second["included"][0]["logical_id"] == first_id

    snapshot = _card(
        "snapshot",
        1,
        recall="same semantic target",
        fact_scope={"kind": "snapshot", "product": "Engine", "version": "1.0.0"},
    )
    third = _prepare(environment, [snapshot], target="cards/snapshot.md")
    assert third["included"][0]["logical_id"] != first_id


def test_reserved_syntax_and_unsafe_tsv_are_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    for answer in ("unsafe\tcell", "unsafe\nline", "[T#B#injection]", "unsafe]close", "---", "```tsv"):
        with pytest.raises(memo_cards.MemoCardsError, match="single TSV-safe|reserved"):
            _prepare(environment, [_card("unsafe", 1, answer=answer)])


def test_structured_formula_and_public_link_are_compiled(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    answer = {
        "parts": [
            {"type": "text", "text": "Cost is "},
            {"type": "formula", "katex": "O(n\\log n)"},
            {"type": "text", "text": "; see "},
            {"type": "link", "url": "https://example.org/reference", "label": "reference"},
        ]
    }
    result = _prepare(environment, [_card("rich", 1, answer=answer)])

    assert "[E##O(n\\log n)]" in result["candidate_markdown"]
    assert '[T#link/"https://example.org/reference"#reference]' in result["candidate_markdown"]

    private = {"parts": [{"type": "link", "url": "http://127.0.0.1/x", "label": "private"}]}
    with pytest.raises(memo_cards.MemoCardsError, match="not a public URL"):
        _prepare(environment, [_card("private", 1, answer=private)])


def test_cloze_is_optional_and_limited_to_three_words(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    good = _card("cloze-good", 1, template_id="cloze", answer="three short words")
    assert _prepare(environment, [good])["included"]

    bad = _card("cloze-bad", 1, template_id="cloze", answer="four separate answer words")
    with pytest.raises(memo_cards.MemoCardsError, match="1-3 word"):
        _prepare(environment, [bad])


def test_soft_target_keeps_all_a_and_defers_only_new_b(tmp_path: Path) -> None:
    environment = _environment(tmp_path, minimum=2, maximum=3)
    cards = [
        _card("a1", 1),
        _card("a2", 2),
        _card("b1", 3, quality="B"),
        _card("b2", 4, quality="B"),
        _card("b3", 5, quality="B"),
    ]
    result = _prepare(environment, cards)

    assert [item["key"] for item in result["included"]] == ["a1", "a2", "b1"]
    assert [item["key"] for item in result["deferred"]] == ["b2", "b3"]
    assert result["soft_target"]["is_hard_limit"] is False

    all_a = _prepare(environment, [_card(f"a{index}", index) for index in range(1, 6)])
    assert len(all_a["included"]) == 5
    assert all_a["soft_target"]["above_maximum"] is True


def test_complete_conversion_ignores_soft_target_but_not_quality_gate(tmp_path: Path) -> None:
    environment = _environment(tmp_path, minimum=1, maximum=1)
    cards = [_card("a", 1), _card("b", 2, quality="B"), _card("c", 3, quality="C")]
    result = _prepare(environment, cards, selection="complete")

    assert [item["key"] for item in result["included"]] == ["a", "b"]
    assert result["deferred"] == []
    assert result["blocked"][0]["reasons"] == ["quality-C"]


def test_same_identity_is_deduplicated_or_blocked_on_content_conflict(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first = _card("first", 1, recall="one target")
    duplicate = _card("duplicate", 2, recall="one target")
    duplicate["fields"] = dict(first["fields"])
    result = _prepare(environment, [first, duplicate])

    assert len(result["included"]) == 1
    assert result["duplicates"][0]["kind"] == "request-duplicate"

    conflict = _card("conflict", 2, recall="one target", answer="Different content")
    result = _prepare(environment, [first, conflict])
    assert result["included"] == []
    assert result["blocked"][0]["reasons"] == ["same-identity-candidate-conflict"]


def test_unverified_research_and_c_cards_stay_in_blocked_preview(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    cards = [
        _card("unverified", 1, fact_status="unverified"),
        _card("research", 2, lifecycle="research", fact_status="research"),
        _card("low", 3, quality="C"),
    ]
    result = _prepare(environment, cards)

    assert result["operation"] == "no-op"
    assert result["candidate_markdown"] is None
    assert len(result["blocked"]) == 3


def test_oral_card_requires_two_to_five_verified_children(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    child_one = _card("child-one", 1)
    child_two = _card("child-two", 2)
    oral = _card(
        "oral",
        3,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["child-one", "child-two"],
    )
    result = _prepare(environment, [child_one, child_two, oral])
    assert len(result["included"]) == 3

    oral["depends_on"] = ["child-one"]
    with pytest.raises(memo_cards.MemoCardsError, match="2-5 child"):
        _prepare(environment, [child_one, oral])


def test_oral_card_is_blocked_when_its_children_are_not_eligible(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    child_one = _card("child-one", 1, lifecycle="research", fact_status="research")
    child_two = _card("child-two", 2, fact_status="unverified")
    oral = _card(
        "oral",
        3,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["child-one", "child-two"],
    )

    result = _prepare(environment, [child_one, child_two, oral])
    assert result["included"] == []
    blocked = {item.get("key"): item for item in result["blocked"]}
    assert any(reason.startswith("oral-child-ineligible-") for reason in blocked["oral"]["reasons"])


def test_mechanism_dependency_hashes_and_child_drift_require_review(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    child = _card("atomic-child", 1)
    mechanism = _card(
        "mechanism",
        2,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["atomic-child"],
    )
    first_request, _value = _request(environment, [child, mechanism])
    first = memo_cards.prepare(environment["repo"], environment["context"], first_request)
    first_artifact = memo_cards._parse_artifact(
        first["candidate_markdown"], "cards/topic.md"
    )
    assert first_artifact is not None
    first_cards = {
        card["logical_id"]: card for card in first_artifact.manifest["cards"]
    }
    mechanism_manifest = next(
        card for card in first_cards.values() if card["layer"] == "mechanism"
    )
    child_id = mechanism_manifest["depends_on"][0]
    assert mechanism_manifest["dependency_content_sha256"] == {
        child_id: first_cards[child_id]["content_sha256"]
    }
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        first_request,
        first["preview_digest"],
        "request",
    )

    changed_child = _card(
        "atomic-child", 1, answer="A materially improved verified atomic answer."
    )
    second_request, _value = _request(environment, [changed_child, mechanism])
    second = memo_cards.prepare(
        environment["repo"], environment["context"], second_request
    )

    included = {item["key"]: item for item in second["included"]}
    assert included["mechanism"]["lifecycle"] == "review"
    assert "dependency-drift-review" in second["risk_reasons"]
    assert second["required_authorization"] == "confirmed"


def test_verify_reports_mechanism_dependency_digest_drift(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    child = _card("atomic-child", 1)
    mechanism = _card(
        "mechanism",
        2,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["atomic-child"],
    )
    request, _value = _request(environment, [child, mechanism])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        request,
        preview["preview_digest"],
        "request",
    )
    target = environment["repo"] / "cards" / "topic.md"
    text = target.read_text(encoding="utf-8")
    header = re.match(r"\A---\n(?P<header>.*?)\n---\n", text, re.DOTALL)
    assert header is not None
    manifest = json.loads(header.group("header"))
    mechanism_manifest = next(
        card for card in manifest["cards"] if card["layer"] == "mechanism"
    )
    child_id = mechanism_manifest["depends_on"][0]
    child_manifest = next(
        card for card in manifest["cards"] if card["logical_id"] == child_id
    )
    child_manifest["content_sha256"] = "0" * 64
    payload = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_payload_sha256"
    }
    manifest["manifest_payload_sha256"] = memo_cards._digest_value(payload)
    target.write_text(
        memo_cards._artifact_text(manifest, text[header.end() :]), encoding="utf-8"
    )
    _set_tracked(environment, "cards/topic.md")

    verified = memo_cards.verify(environment["repo"], environment["context"])
    assert verified["dependency_drift"] == [
        {
            "path": "cards/topic.md",
            "logical_id": mechanism_manifest["logical_id"],
            "dependency_id": child_id,
            "expected": mechanism_manifest["dependency_content_sha256"][child_id],
            "actual": "0" * 64,
        }
    ]


def test_nested_child_drift_moves_mechanism_and_oral_cards_to_review(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path, maximum=10)
    first_child = _card("first-child", 1)
    second_child = _card("second-child", 2)
    mechanism = _card(
        "mechanism",
        3,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["first-child"],
    )
    oral = _card(
        "oral",
        4,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["mechanism", "second-child"],
    )
    first_request, _value = _request(
        environment, [first_child, second_child, mechanism, oral]
    )
    first = memo_cards.prepare(environment["repo"], environment["context"], first_request)
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        first_request,
        first["preview_digest"],
        "request",
    )

    changed_child = _card(
        "first-child", 1, answer="A materially improved verified prerequisite."
    )
    second_request, _value = _request(
        environment, [changed_child, second_child, mechanism, oral]
    )
    second = memo_cards.prepare(
        environment["repo"], environment["context"], second_request
    )
    included = {item["key"]: item for item in second["included"]}
    assert included["mechanism"]["lifecycle"] == "review"
    assert included["oral"]["lifecycle"] == "review"
    assert "dependency-drift-review" in second["risk_reasons"]


def test_dependency_review_persists_until_explicit_confirmed_resolution(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path, maximum=10)
    first_child = _card("first-child", 1)
    second_child = _card("second-child", 2)
    mechanism = _card(
        "mechanism",
        3,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["first-child"],
    )
    oral = _card(
        "oral",
        4,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["mechanism", "second-child"],
    )
    request, _value = _request(
        environment, [first_child, second_child, mechanism, oral]
    )
    initial = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        request,
        initial["preview_digest"],
        "request",
    )

    changed_child = _card(
        "first-child", 1, answer="A materially improved verified prerequisite."
    )
    drift_request, drift_value = _request(
        environment, [changed_child, second_child, mechanism, oral]
    )
    drift = memo_cards.prepare(
        environment["repo"], environment["context"], drift_request
    )
    drift_cards = {item["key"]: item for item in drift["included"]}
    assert drift_cards["mechanism"]["lifecycle"] == "review"
    assert drift_cards["oral"]["lifecycle"] == "review"
    assert drift_cards["mechanism"]["review_reason"] == "dependency-drift"
    assert drift["required_authorization"] == "confirmed"
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        drift_request,
        drift["preview_digest"],
        "confirmed",
    )

    persisted = memo_cards.verify(
        environment["repo"], environment["context"], drift_request
    )
    assert persisted["request_check"]["operation"] == "no-op"
    persisted_cards = {item["key"]: item for item in persisted["preview"]["included"]}
    assert persisted_cards["mechanism"]["lifecycle"] == "review"
    assert persisted_cards["oral"]["lifecycle"] == "review"

    resolved_mechanism = _card(
        "mechanism",
        3,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["first-child"],
        review_resolution="Rechecked the mechanism against the revised prerequisite.",
    )
    resolved_oral = _card(
        "oral",
        4,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["mechanism", "second-child"],
        review_resolution="Rehearsed and rechecked the integrated oral explanation.",
    )
    partial_request, _partial_value = _request(
        environment, [changed_child, second_child, mechanism, resolved_oral]
    )
    partial = memo_cards.prepare(
        environment["repo"], environment["context"], partial_request
    )
    partial_blocked = {item.get("key"): item for item in partial["blocked"]}
    assert any(
        reason.startswith("oral-child-ineligible-")
        for reason in partial_blocked["oral"]["reasons"]
    )

    resolution_request, _resolution_value = _request(
        environment,
        [changed_child, second_child, resolved_mechanism, resolved_oral],
    )
    resolution = memo_cards.prepare(
        environment["repo"], environment["context"], resolution_request
    )
    resolution_cards = {item["key"]: item for item in resolution["included"]}
    assert resolution_cards["mechanism"]["lifecycle"] == "active"
    assert resolution_cards["oral"]["lifecycle"] == "active"
    assert resolution_cards["mechanism"]["review_resolution_summary"].startswith(
        "Rechecked"
    )
    assert "review-resolution" in resolution["risk_reasons"]
    assert resolution["required_authorization"] == "confirmed"
    with pytest.raises(memo_cards.MemoCardsError, match="requires explicit"):
        memo_cards.publish(
            environment["repo"],
            environment["context"],
            resolution_request,
            resolution["preview_digest"],
            "request",
        )
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        resolution_request,
        resolution["preview_digest"],
        "confirmed",
    )
    resolved = memo_cards.verify(
        environment["repo"], environment["context"], resolution_request
    )
    assert resolved["request_check"]["operation"] == "no-op"

    _write_json(resolution_request, drift_value)
    original_active_request = memo_cards.verify(
        environment["repo"], environment["context"], resolution_request
    )
    assert original_active_request["request_check"]["operation"] == "no-op"


def test_mechanism_dependencies_reject_cycles_and_block_ineligible_children(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path, maximum=10)
    first = _card(
        "first-mechanism",
        1,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["second-mechanism"],
    )
    second = _card(
        "second-mechanism",
        2,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["first-mechanism"],
    )
    with pytest.raises(memo_cards.MemoCardsError, match="dependency cycle"):
        _prepare(environment, [first, second])

    unverified = _card("unverified-child", 1, fact_status="unverified")
    dependent = _card(
        "dependent-mechanism",
        2,
        layer="mechanism",
        assessment="mechanism",
        depends_on=["unverified-child"],
    )
    result = _prepare(environment, [unverified, dependent])
    blocked = {item.get("key"): item for item in result["blocked"]}
    assert any(
        reason.startswith("mechanism-child-ineligible-")
        for reason in blocked["dependent-mechanism"]["reasons"]
    )


def test_child_content_drift_moves_oral_card_to_review(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    children = [_card("child-one", 1), _card("child-two", 2)]
    oral = _card(
        "oral",
        3,
        template_id="oral",
        layer="oral",
        assessment="oral",
        depends_on=["child-one", "child-two"],
    )
    first_request, _value = _request(environment, [*children, oral])
    first = memo_cards.prepare(environment["repo"], environment["context"], first_request)
    memo_cards.publish(
        environment["repo"], environment["context"], first_request, first["preview_digest"], "request"
    )

    changed_child = _card("child-one", 1, answer="A materially improved verified answer.")
    second_request, _value = _request(environment, [changed_child, children[1], oral])
    second = memo_cards.prepare(environment["repo"], environment["context"], second_request)

    included = {item["key"]: item for item in second["included"]}
    assert included["oral"]["lifecycle"] == "review"
    assert "dependency-drift-review" in second["risk_reasons"]
    assert second["required_authorization"] == "confirmed"


def test_source_cas_detects_drift(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("source", 1)])
    environment["source"].write_text("changed", encoding="utf-8")

    with pytest.raises(memo_cards.MemoCardsError, match="source changed"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_new_publish_then_identical_request_is_noop_and_stable(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("stable", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)

    assert preview["operation"] == "create"
    assert preview["required_authorization"] == "request"
    assert "generated" not in preview["candidate_markdown"].lower()
    published = memo_cards.publish(
        environment["repo"],
        environment["context"],
        request,
        preview["preview_digest"],
        "request",
    )
    target = environment["repo"] / "cards" / "topic.md"
    original = target.read_bytes()
    assert published["written"] is True

    verified = memo_cards.verify(
        environment["repo"], environment["context"], request
    )
    assert verified["request_check"]["would_write"] is False
    assert verified["request_check"]["operation"] == "no-op"
    assert verified["preview"]["operation"] == "no-op"
    assert verified["preview"]["target"] == "cards/topic.md"

    second = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert second["operation"] == "no-op"
    assert memo_cards.publish(
        environment["repo"], environment["context"], request, second["preview_digest"], "request"
    )["written"] is False
    assert target.read_bytes() == original

    complete_request, complete_value = _request(environment, [_card("stable", 1)])
    complete_value["selection"] = "complete"
    _write_json(complete_request, complete_value)
    assert memo_cards.prepare(
        environment["repo"], environment["context"], complete_request
    )["operation"] == "no-op"


def test_legacy_adoption_requires_post_diff_confirmation(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    target = environment["repo"] / "cards" / "topic.md"
    target.write_text("# Hand-written legacy cards\n", encoding="utf-8")
    request, _value = _request(environment, [_card("adopt", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)

    assert preview["target_state"] == "legacy"
    assert preview["required_authorization"] == "confirmed"
    assert "legacy-adoption" in preview["risk_reasons"]
    with pytest.raises(memo_cards.MemoCardsError, match="requires explicit"):
        memo_cards.publish(
            environment["repo"], environment["context"], request, preview["preview_digest"], "request"
        )
    memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "confirmed"
    )
    assert target.read_text(encoding="utf-8").startswith("---\n{")


def test_preview_digest_invalidates_on_target_or_context_drift(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("drift", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    target = environment["repo"] / "cards" / "topic.md"
    target.write_text("competing writer\n", encoding="utf-8")

    with pytest.raises(memo_cards.MemoCardsError, match="preview digest"):
        memo_cards.publish(
            environment["repo"], environment["context"], request, preview["preview_digest"], "request"
        )

    target.unlink()
    environment["skill_config"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(memo_cards.MemoCardsError, match="stale"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_manual_body_drift_is_reported_and_requires_confirmation(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("manual", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "request"
    )
    target = environment["repo"] / "cards" / "topic.md"
    target.write_text(target.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

    drift = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert "manual-drift" in drift["risk_reasons"]
    assert drift["required_authorization"] == "confirmed"


def test_manifest_payload_drift_is_not_trusted_as_canonical(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("header", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "request"
    )
    target = environment["repo"] / "cards" / "topic.md"
    raw = target.read_bytes()
    match = re.match(rb"\A---\r?\n(?P<header>.*?)\r?\n---\r?\n", raw, re.DOTALL)
    assert match is not None
    manifest = json.loads(match.group("header"))
    manifest["cards"][0]["priority"] = 4
    target.write_bytes(
        b"---\n"
        + json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n---\n"
        + raw[match.end() :]
    )
    _set_tracked(environment, "cards/topic.md")

    verified = memo_cards.verify(environment["repo"], environment["context"])
    assert verified["managed_artifacts"][0]["header_drifted"] is True
    refreshed = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert "manual-header-drift" in refreshed["risk_reasons"]
    assert refreshed["required_authorization"] == "confirmed"

    manifest["cards"][0]["logical_id"] = "mc-" + "0" * 24
    target.write_bytes(
        b"---\n"
        + json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n---\n"
        + raw[match.end() :]
    )
    with pytest.raises(memo_cards.MemoCardsError, match="identity does not match"):
        memo_cards.verify(environment["repo"], environment["context"])


def test_cross_file_repeat_is_suppressed_without_rewriting_canonical(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first_request, _value = _request(environment, [_card("canonical", 1)], target="cards/first.md")
    first = memo_cards.prepare(environment["repo"], environment["context"], first_request)
    memo_cards.publish(
        environment["repo"], environment["context"], first_request, first["preview_digest"], "request"
    )
    _set_tracked(environment, "cards/first.md")
    canonical = environment["repo"] / "cards" / "first.md"
    before = canonical.read_bytes()

    repeated = _card("repeat-key", 1, recall="stable target canonical")
    repeated["fields"] = dict(_card("canonical", 1)["fields"])
    second = _prepare(environment, [repeated], target="cards/second.md")
    assert second["operation"] == "no-op"
    assert second["duplicates"][0]["kind"] == "cross-file-duplicate"
    assert not (environment["repo"] / "cards" / "second.md").exists()
    assert canonical.read_bytes() == before


def test_path_escape_and_source_symlink_are_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    with pytest.raises(memo_cards.MemoCardsError, match="relative path|outside"):
        _prepare(environment, [_card("escape", 1)], target="../outside.md")
    with pytest.raises(memo_cards.MemoCardsError, match="Windows reserved"):
        _prepare(environment, [_card("reserved", 1)], target="cards/CON.md")
    with pytest.raises(memo_cards.MemoCardsError, match="trailing dot or space"):
        _prepare(environment, [_card("trailing", 1)], target="cards/topic.md. ")

    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    source = environment["source"]
    source.unlink()
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("creating a file symlink is not permitted")
    request, value = _request(environment, [_card("link", 1)])
    value["sources"][0]["sha256"] = _digest(outside)
    _write_json(request, value)
    with pytest.raises(memo_cards.MemoCardsError, match="link"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_context_outside_repository_is_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    outside = tmp_path / "outside-context.json"
    outside.write_bytes(environment["context"].read_bytes())
    with pytest.raises(memo_cards.MemoCardsError, match="inside the consumer repository"):
        memo_cards.verify(environment["repo"], outside)


def test_context_directory_alias_is_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    alias = tmp_path / "repository-alias"
    try:
        alias.symlink_to(environment["repo"], target_is_directory=True)
    except OSError:
        pytest.skip("creating a directory symlink is not permitted")
    alias_context = alias / environment["context"].relative_to(environment["repo"])
    with pytest.raises(memo_cards.MemoCardsError, match="link|inside the consumer repository"):
        memo_cards.verify(environment["repo"], alias_context)


@pytest.mark.skipif(os.name != "nt", reason="Windows path identity semantics")
def test_windows_context_identity_fallback_preserves_repository_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    monkeypatch.setattr(
        memo_cards.os.path,
        "commonpath",
        lambda _paths: os.fspath(environment["repo"].parent),
    )

    verified = memo_cards.verify(environment["repo"], environment["context"])
    assert verified["repository_id"] == "demo-learning"


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 aliases are Windows-only")
def test_windows_short_context_path_matches_long_repository_path(tmp_path: Path) -> None:
    import ctypes

    long_parent = tmp_path / "memo cards eight dot three fixture"
    long_parent.mkdir()
    environment = _environment(long_parent)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel32.GetShortPathNameW
    required = get_short_path(str(environment["context"]), None, 0)
    if required == 0:
        pytest.skip("this volume does not provide a short path alias")
    buffer = ctypes.create_unicode_buffer(required)
    written = get_short_path(str(environment["context"]), buffer, required)
    if written == 0 or written >= required:
        pytest.skip("this volume did not return a usable short path alias")
    short_context = Path(buffer.value)
    assert os.path.samefile(short_context, environment["context"])

    root = memo_cards._repository_root(environment["repo"])
    absolute_short = Path(os.path.abspath(os.fspath(short_context)))
    lexical_common = Path(os.path.commonpath([root, absolute_short]))
    if os.path.normcase(os.fspath(lexical_common)) == os.path.normcase(os.fspath(root)):
        pytest.skip("the returned short path does not alias the repository prefix")

    verified = memo_cards.verify(environment["repo"], short_context)
    assert verified["repository_id"] == "demo-learning"

    repo_required = get_short_path(str(environment["repo"]), None, 0)
    if repo_required:
        repo_buffer = ctypes.create_unicode_buffer(repo_required)
        repo_written = get_short_path(
            str(environment["repo"]), repo_buffer, repo_required
        )
        if 0 < repo_written < repo_required:
            short_repo = Path(repo_buffer.value)
            assert os.path.samefile(short_repo, environment["repo"])
            reverse_verified = memo_cards.verify(short_repo, environment["context"])
            assert reverse_verified["repository_id"] == "demo-learning"


def test_atomic_install_failure_preserves_target_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "cards.md"
    target.write_text("old\n", encoding="utf-8")
    expected = _digest(target)

    original_link = memo_cards.os.link
    calls = 0

    def fail_candidate_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic installation failure")
        original_link(source, destination)

    monkeypatch.setattr(memo_cards.os, "link", fail_candidate_link)
    with pytest.raises(OSError, match="synthetic"):
        memo_cards._atomic_write(target, "new\n", expected)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".cards.md.*.tmp")) == []
    assert not (tmp_path / ".cards.md.memo-cards.lock").exists()


def test_atomic_update_never_overwrites_a_competing_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "cards.md"
    target.write_text("old\n", encoding="utf-8")
    expected = _digest(target)
    original_link = memo_cards.os.link

    def competing_link(source: Path, destination: Path) -> None:
        Path(destination).write_text("competitor\n", encoding="utf-8")
        original_link(source, destination)

    monkeypatch.setattr(memo_cards.os, "link", competing_link)
    with pytest.raises(memo_cards.MemoCardsError, match="competing target") as captured:
        memo_cards._atomic_write(target, "candidate\n", expected)

    assert target.read_text(encoding="utf-8") == "competitor\n"
    recovery = tmp_path / captured.value.details["recovery"]
    assert recovery.read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / ".cards.md.memo-cards.lock").exists()


def test_verify_reports_managed_body_drift_and_legacy(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("verify", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "request"
    )
    target = environment["repo"] / "cards" / "topic.md"
    target.write_text(target.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    (environment["repo"] / "cards" / "legacy.md").write_text("legacy\n", encoding="utf-8")
    _set_tracked(environment, "cards/topic.md", "cards/legacy.md")

    result = memo_cards.verify(environment["repo"], environment["context"])
    assert result["managed_artifacts"][0]["body_drifted"] is True
    assert result["legacy_inventory"][0]["path"] == "cards/legacy.md"


def test_cli_emits_stable_json_error_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    environment = _environment(tmp_path)
    code = memo_cards.main(
        ["verify", "--repo", str(environment["repo"]), "--context", str(environment["context"])]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["ok"] is True
    assert result["command"] == "verify"

    code = memo_cards.main([])
    result = json.loads(capsys.readouterr().out)
    assert code == memo_cards.EXIT_USAGE
    assert result == {
        "schema_version": 1,
        "ok": False,
        "command": None,
        "error": {"code": "usage", "message": "the following arguments are required: command", "details": {}},
    }


def test_cli_publish_then_verify_uses_the_same_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("cli-stable", 1)])
    shared = [
        "--repo",
        str(environment["repo"]),
        "--context",
        str(environment["context"]),
    ]

    assert memo_cards.main(["prepare", *shared, "--request", str(request)]) == 0
    prepared = json.loads(capsys.readouterr().out)["data"]
    assert prepared["operation"] == "create"

    assert (
        memo_cards.main(
            [
                "publish",
                *shared,
                "--request",
                str(request),
                "--preview-digest",
                prepared["preview_digest"],
                "--authorization",
                "request",
            ]
        )
        == 0
    )
    published = json.loads(capsys.readouterr().out)["data"]
    assert published["written"] is True

    assert memo_cards.main(["verify", *shared, "--request", str(request)]) == 0
    verified = json.loads(capsys.readouterr().out)["data"]
    assert verified["managed_artifacts"] == []
    assert verified["request_check"]["operation"] == "no-op"
    assert verified["request_check"]["would_write"] is False


def test_cli_prepare_is_ascii_safe_when_stdout_is_cp936(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    emoji = "😀"
    request, _value = _request(
        environment, [_card("emoji", 1, answer=f"A verified boundary {emoji}")]
    )
    child_env = os.environ.copy()
    child_env.pop("PYTHONUTF8", None)
    child_env.pop("PYTHONLEGACYWINDOWSSTDIO", None)
    child_env["PYTHONIOENCODING"] = "cp936:strict"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--repo",
            str(environment["repo"]),
            "--context",
            str(environment["context"]),
            "--request",
            str(request),
        ],
        cwd=environment["repo"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        check=False,
    )

    assert result.returncode == memo_cards.EXIT_OK, result.stdout.decode(
        "ascii", errors="backslashreplace"
    )
    assert result.stderr == b""
    assert result.stdout.isascii()
    payload = json.loads(result.stdout.decode("ascii"))
    assert payload["ok"] is True
    assert payload["command"] == "prepare"
    assert emoji in payload["data"]["candidate_markdown"]
