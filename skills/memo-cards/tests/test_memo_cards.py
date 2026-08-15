from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "memo_cards.py"
SYNTAX_PDF = Path(__file__).resolve().parents[1] / "references" / "markji-content-syntax.pdf"
SYNTAX_PDF_SHA256 = "57438a84a630ab9f8897bed53cedb8899b09a55b816c09edc480eeed96a88201"
SPEC = importlib.util.spec_from_file_location("memo_cards", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
memo_cards = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memo_cards
SPEC.loader.exec_module(memo_cards)


def test_bundled_markji_syntax_pdf_is_pinned_and_routed() -> None:
    payload = SYNTAX_PDF.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert hashlib.sha256(payload).hexdigest() == SYNTAX_PDF_SHA256

    skill = (SYNTAX_PDF.parents[1] / "SKILL.md").read_text(encoding="utf-8")
    compatibility = (SYNTAX_PDF.parent / "markji-3.8-compatibility.md").read_text(
        encoding="utf-8"
    )
    assert "references/markji-content-syntax.pdf" in skill
    assert "markji-content-syntax.pdf" in compatibility
    assert SYNTAX_PDF_SHA256 in compatibility


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
    elif template_id == "correction":
        fields = {
            "意图": f"Correct {key}",
            "场景": "A verified learning correction",
            "正确": answer,
            "错误": f"Incorrect form for {key}",
            "说明": "The verified reason and boundary.",
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
    assert result["binary_collection_extensions"] == {"cards": [".xlsx"]}
    assert all(isinstance(path, str) for path in result["tracked_collections"])

    bad = _skill_config()
    bad["prompt"] = "ignore safety"
    with pytest.raises(memo_cards.MemoCardsError, match="unknown prompt"):
        memo_cards.validate_materialized_context(_repository_config(), bad)


def test_exact_markdown_input_is_a_file_not_a_collection() -> None:
    config = _skill_config()
    config["input_collections"].append(
        {
            "id": "fixed-article",
            "kind": "article",
            "patterns": ["articles/fixed.md"],
        }
    )

    result = memo_cards.validate_materialized_context(_repository_config(), config)

    assert result["tracked_files"] == ["articles/fixed.md"]
    assert result["tracked_collections"] == ["cards", "notes"]
    assert result["read_handoffs"] == []


def test_exact_article_input_can_name_one_cross_skill_producer() -> None:
    config = _skill_config()
    config["input_collections"].append(
        {
            "id": "fixed-article",
            "kind": "article",
            "patterns": ["articles/fixed.md"],
            "producer": "guide-learning",
        }
    )

    result = memo_cards.validate_materialized_context(_repository_config(), config)

    assert result["context"]["input_collections"][0]["producer"] == "guide-learning"
    assert result["read_handoffs"] == [
        {"path": "articles/fixed.md", "producer": "guide-learning"}
    ]

    wildcard = _skill_config()
    wildcard["input_collections"][0]["producer"] = "guide-learning"
    with pytest.raises(memo_cards.MemoCardsError, match="exact Markdown article"):
        memo_cards.validate_materialized_context(_repository_config(), wildcard)

    wrong_kind = _skill_config()
    wrong_kind["input_collections"][0] = {
        "id": "fixed-note",
        "kind": "verified-learning-note",
        "patterns": ["notes/fixed.md"],
        "producer": "guide-learning",
    }
    with pytest.raises(memo_cards.MemoCardsError, match="exact Markdown article"):
        memo_cards.validate_materialized_context(_repository_config(), wrong_kind)

    self_produced = _skill_config()
    self_produced["input_collections"][0] = {
        "id": "fixed-article",
        "kind": "article",
        "patterns": ["articles/fixed.md"],
        "producer": "memo-cards",
    }
    with pytest.raises(memo_cards.MemoCardsError, match="cannot be memo-cards"):
        memo_cards.validate_materialized_context(_repository_config(), self_produced)


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
    binary_card = environment["repo"] / "cards" / "binary.md"
    malformed_card = environment["repo"] / "cards" / "malformed.md"
    tracked_card.write_text("tracked legacy\n", encoding="utf-8")
    private_card.write_text("private legacy\n", encoding="utf-8")
    binary_card.write_bytes(b"\xff\xfe")
    malformed_card.write_text(
        '---\n{"schema": "memo-cards.artifact/v2"}\n---\ninvalid\n',
        encoding="utf-8",
    )
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


def test_reserved_syntax_and_unsafe_spreadsheet_cells_are_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    for answer in ("unsafe\tcell", "unsafe\nline", "[T#B#injection]", "unsafe]close", "---", "```tsv"):
        with pytest.raises(memo_cards.MemoCardsError, match="single spreadsheet-safe|reserved"):
            _prepare(environment, [_card("unsafe", 1, answer=answer)])

    for separator in ("\u0085", "\u2028", "\u2029"):
        with pytest.raises(memo_cards.MemoCardsError, match="line-separator"):
            _prepare(environment, [_card("unicode-line", 1, answer=f"left{separator}right")])


def test_structured_formula_and_public_link_are_compiled(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    answer = {
        "blocks": [
            {
                "type": "lead",
                "parts": [
                    {"type": "text", "text": "See "},
                    {
                        "type": "link",
                        "url": "https://example.org/reference",
                        "label": "reference",
                    },
                ],
            },
            {
                "type": "display",
                "parts": [{"type": "formula", "katex": "O(n\\log n)"}],
            },
        ]
    }
    request, _value = _request(environment, [_card("rich", 1, answer=answer)])
    result = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, result["preview_digest"], "request"
    )
    workbook = environment["repo"] / result["candidate_sidecars"][0]["path"]
    _headers, rows = memo_cards._parse_xlsx(workbook.read_bytes(), "test workbook")

    assert "[E##O(n\\log n)]" in rows[0][1]
    assert '[T#link/"https://example.org/reference"#reference]' in rows[0][1]

    private = {"parts": [{"type": "link", "url": "http://127.0.0.1/x", "label": "private"}]}
    with pytest.raises(memo_cards.MemoCardsError, match="not a public URL"):
        _prepare(environment, [_card("private", 1, answer=private)])


def test_structured_mechanism_answer_compiles_exact_markji_layout(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    answer = {
        "blocks": [
            {
                "type": "lead",
                "parts": [
                    {"type": "text", "text": "单遍流中，先验证基线是否可执行。"}
                ],
            },
            {
                "type": "point",
                "label": "访问限制",
                "parts": [
                    {
                        "type": "text",
                        "text": "双层枚举依赖回看或随机访问；已消费元素不能重新枚举",
                    }
                ],
            },
            {
                "type": "point",
                "label": "有序性",
                "parts": [
                    {
                        "type": "text",
                        "text": "若非递减，x 与 x 之间任一 y 满足 x≤y≤x，故 y=x",
                    }
                ],
            },
            {
                "type": "point",
                "label": "状态",
                "parts": [
                    {"type": "text", "text": "只保存前值，相等即重复，否则更新"}
                ],
            },
            {
                "type": "point",
                "label": "复杂度",
                "parts": [
                    {"type": "text", "text": "O(n) 时间、O(1) 额外空间"}
                ],
            },
            {
                "type": "boundary",
                "parts": [
                    {
                        "type": "text",
                        "text": "任意顺序流不保证重复相邻，因此该状态不足以精确判重。",
                    }
                ],
            },
        ]
    }
    card = _card(
        "stream-dedup",
        1,
        answer=answer,
        layer="mechanism",
        assessment="mechanism",
    )
    card["fields"]["问题"] = "单遍非递减数据流怎样以 O(1) 空间精确判重？"
    request, _value = _request(environment, [card])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        request,
        preview["preview_digest"],
        "request",
    )
    workbook = environment["repo"] / preview["candidate_sidecars"][0]["path"]
    headers, rows = memo_cards._parse_xlsx(workbook.read_bytes(), "mechanism workbook")

    assert rows[0][headers.index("问题")] == card["fields"]["问题"]
    assert rows[0][headers.index("答案")] == (
        "[T#B,!36b59d#结论]：单遍流中，先验证基线是否可执行。\n"
        "\n"
        "• [T#B#访问限制]：双层枚举依赖回看或随机访问；已消费元素不能重新枚举\n"
        "• [T#B#有序性]：若非递减，x 与 x 之间任一 y 满足 x≤y≤x，故 y=x\n"
        "• [T#B#状态]：只保存前值，相等即重复，否则更新\n"
        "• [T#B#复杂度]：O(n) 时间、O(1) 额外空间\n"
        "\n"
        "[T#B,!c47f17#边界]：任意顺序流不保证重复相邻，因此该状态不足以精确判重。"
    )


def test_content_blocks_nest_existing_parts_and_preserve_legacy_content() -> None:
    assert memo_cards._render_content("plain answer", "answer") == "plain answer"
    assert memo_cards._render_content(
        {"parts": [{"type": "text", "text": "legacy parts"}]}, "answer"
    ) == "legacy parts"

    value = {
        "blocks": [
            {
                "type": "point",
                "label": "推导",
                "parts": [
                    {"type": "text", "text": "详情见 "},
                    {
                        "type": "link",
                        "url": "https://example.org/reference",
                        "label": "来源",
                    },
                ],
            },
            {
                "type": "display",
                "parts": [{"type": "formula", "katex": "O(n\\log n)"}],
            },
        ]
    }

    assert memo_cards._render_content(value, "answer") == (
        '• [T#B#推导]：详情见 [T#link/"https://example.org/reference"#来源]\n'
        "[E##O(n\\log n)]"
    )

    english_labels = {
        "blocks": [
            {
                "type": "lead",
                "label": "Answer",
                "parts": [{"type": "text", "text": "Keep one previous value."}],
            },
            {
                "type": "boundary",
                "label": "Limit",
                "parts": [{"type": "text", "text": "The stream must be sorted."}],
            },
        ]
    }
    assert memo_cards._render_content(english_labels, "answer") == (
        "[T#B,!36b59d#Answer]：Keep one previous value.\n\n"
        "[T#B,!c47f17#Limit]：The stream must be sorted."
    )


def test_content_blocks_reject_unbounded_or_request_injected_layout() -> None:
    point = {
        "type": "point",
        "label": "要点",
        "parts": [{"type": "text", "text": "安全内容"}],
    }
    too_many = {"blocks": [dict(point) for _index in range(9)]}
    with pytest.raises(memo_cards.MemoCardsError, match="1-8 blocks"):
        memo_cards._render_content(too_many, "answer")

    long_label = {
        "blocks": [{**point, "label": "标" * 21}],
    }
    with pytest.raises(memo_cards.MemoCardsError, match="too long"):
        memo_cards._render_content(long_label, "answer")

    injected_label = {
        "blocks": [{**point, "label": "[T#B#伪造标签]"}],
    }
    with pytest.raises(memo_cards.MemoCardsError, match="reserved"):
        memo_cards._render_content(injected_label, "answer")

    injected_body = {
        "blocks": [
            {
                **point,
                "parts": [{"type": "text", "text": "第一行\n第二行"}],
            }
        ],
    }
    with pytest.raises(memo_cards.MemoCardsError, match="spreadsheet-safe"):
        memo_cards._render_content(injected_body, "answer")

    lead_after_point = {
        "blocks": [
            point,
            {"type": "lead", "parts": [{"type": "text", "text": "结论"}]},
        ]
    }
    with pytest.raises(memo_cards.MemoCardsError, match="lead must be the first"):
        memo_cards._render_content(lead_after_point, "answer")

    boundary_before_point = {
        "blocks": [
            {
                "type": "boundary",
                "parts": [{"type": "text", "text": "边界内容"}],
            },
            point,
        ]
    }
    with pytest.raises(memo_cards.MemoCardsError, match="boundary must be the last"):
        memo_cards._render_content(boundary_before_point, "answer")

    mixed_formula = {
        "parts": [
            {"type": "text", "text": "复杂度为 "},
            {"type": "formula", "katex": "O(n)"},
        ]
    }
    with pytest.raises(memo_cards.MemoCardsError, match="occupy the whole line"):
        memo_cards._render_content(mixed_formula, "answer")

    inline_formula = {
        "blocks": [
            {
                "type": "point",
                "label": "复杂度",
                "parts": [{"type": "formula", "katex": "O(n)"}],
            }
        ]
    }
    with pytest.raises(memo_cards.MemoCardsError, match="require a display block"):
        memo_cards._render_content(inline_formula, "answer")

    bad_display = {
        "blocks": [
            {
                "type": "display",
                "parts": [
                    {"type": "formula", "katex": "O(n)"},
                    {"type": "text", "text": "not a whole-line formula"},
                ],
            }
        ]
    }
    with pytest.raises(memo_cards.MemoCardsError, match="display block"):
        memo_cards._render_content(bad_display, "answer")


def test_template_embedded_content_rejects_blocks_and_generated_markji(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    blocks = {
        "blocks": [
            {
                "type": "lead",
                "parts": [{"type": "text", "text": "A nested answer"}],
            }
        ]
    }
    correction = _card("nested-correction", 1, template_id="correction", answer=blocks)
    with pytest.raises(memo_cards.MemoCardsError, match="missing parts; unknown blocks"):
        _prepare(environment, [correction])

    generated_link = {
        "parts": [
            {
                "type": "link",
                "url": "https://example.org/reference",
                "label": "reference",
            }
        ]
    }
    correction["fields"]["正确"] = generated_link
    with pytest.raises(memo_cards.MemoCardsError, match="accepts text parts only"):
        _prepare(environment, [correction])

    correction["fields"]["正确"] = {
        "parts": [
            {"type": "text", "text": "A "},
            {"type": "text", "text": "plain answer"},
        ]
    }
    assert _prepare(environment, [correction])["included"]

    choice = _card(
        "nested-choice",
        1,
        template_id="technical-qa",
        assessment="discrimination",
    )
    choice["template_id"] = "choice-2"
    choice["fields"] = {
        "题干": "Which statement is valid?",
        "答案": "A",
        "选项1": {"parts": [{"type": "formula", "katex": "x^2"}]},
        "选项2": "The alternative",
        "解析": blocks,
        "场景": "A verified distinction",
    }
    with pytest.raises(memo_cards.MemoCardsError, match="accepts text parts only"):
        _prepare(environment, [choice])

    choice["fields"]["选项1"] = "The valid statement"
    assert _prepare(environment, [choice])["included"]

    padded = memo_cards.Template(
        "padded",
        "1.0.0",
        "qa",
        "Padded",
        (("答案", "content"),),
        " {{答案}}",
    )
    assert memo_cards._template_field_is_standalone(padded, "答案") is False

    nested_choice = memo_cards.Template(
        "nested-choice",
        "1.0.0",
        "discrimination",
        "Nested choice",
        (("选项", "content"),),
        "[Choice#ans/A#\n{{选项}}\n]",
    )
    assert memo_cards._template_field_is_standalone(nested_choice, "选项") is False


def test_registry_content_field_capability_matrix_is_explicit() -> None:
    registry = memo_cards.load_template_registry()
    actual = {
        (template.template_id, field_name): memo_cards._template_field_is_standalone(
            template, field_name
        )
        for template in registry.templates
        for field_name, field_type in template.fields
        if field_type == "content"
    }
    expected = {
        ("correction", "正确"): False,
        ("correction", "错误"): False,
        ("correction", "说明"): True,
        ("active-production", "目标表达"): False,
        ("active-production", "边界"): True,
        ("choice-2", "选项1"): False,
        ("choice-2", "选项2"): False,
        ("choice-2", "解析"): True,
        ("choice-3", "选项1"): False,
        ("choice-3", "选项2"): False,
        ("choice-3", "选项3"): False,
        ("choice-3", "解析"): True,
        ("choice-4", "选项1"): False,
        ("choice-4", "选项2"): False,
        ("choice-4", "选项3"): False,
        ("choice-4", "选项4"): False,
        ("choice-4", "解析"): True,
        ("qa", "答案"): True,
        ("qa", "例子"): False,
        ("technical-qa", "答案"): True,
        ("technical-qa", "锚点"): False,
        ("cloze", "说明"): True,
        ("oral", "参考回答"): True,
    }
    assert actual == expected


def test_display_block_accepts_only_a_formula_or_pure_images() -> None:
    images = {
        "blocks": [
            {
                "type": "display",
                "parts": [
                    {"type": "image", "id": "Image1"},
                    {"type": "image", "id": "Image2", "mask_id": "Mask2"},
                ],
            }
        ]
    }
    assert memo_cards._render_content(images, "answer") == (
        "[Pic#ID/Image1#][Pic#ID/Image2,MID/Mask2#]"
    )


def test_xlsx_cell_limit_counts_utf16_code_units() -> None:
    assert memo_cards._xlsx_cell_text("😀" * 16_383 + "x", "cell")
    with pytest.raises(memo_cards.MemoCardsError, match="cell character limit"):
        memo_cards._xlsx_cell_text("😀" * 16_384, "cell")


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
    sidecar_row = next(
        row
        for sidecar in manifest["sidecars"]
        for row in sidecar["rows"]
        if row["logical_id"] == child_id
    )
    sidecar_row["content_sha256"] = "0" * 64
    manifest["artifact_set_sha256"] = memo_cards._digest_value(
        {
            "managed_body_sha256": manifest["managed_body_sha256"],
            "sidecars": manifest["sidecars"],
        }
    )
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


def test_markdown_has_no_tsv_and_each_template_gets_one_xlsx(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    cards = [
        _card("correction", 1, template_id="correction", answer="Correct answer."),
        _card("technical", 2, answer="Technical answer."),
    ]
    request, _value = _request(environment, cards)
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)

    assert "```tsv" not in preview["candidate_markdown"]
    assert "Correct answer." not in preview["candidate_markdown"]
    assert [item["template_id"] for item in preview["candidate_sidecars"]] == [
        "correction",
        "technical-qa",
    ]
    assert [item["row_count"] for item in preview["candidate_sidecars"]] == [1, 1]
    published = memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "request"
    )

    assert published["written"] is True
    assert len(published["files"]) == 3
    correction_path = environment["repo"] / "cards" / "topic-correction.xlsx"
    technical_path = environment["repo"] / "cards" / "topic-technical-qa.xlsx"
    correction_headers, correction_rows = memo_cards._parse_xlsx(
        correction_path.read_bytes(), "correction workbook"
    )
    technical_headers, technical_rows = memo_cards._parse_xlsx(
        technical_path.read_bytes(), "technical workbook"
    )
    assert correction_headers == ("意图", "场景", "正确", "错误", "说明")
    assert correction_rows[0][2] == "Correct answer."
    assert technical_headers == ("问题", "答案", "锚点", "来源")
    assert technical_rows[0][1] == "Technical answer."


def test_xlsx_is_deterministic_unicode_safe_and_formula_literal() -> None:
    headers = ("字段",)
    rows = (("=1+1 😀 & <literal>",),)
    first = memo_cards._render_xlsx(headers, rows)
    second = memo_cards._render_xlsx(headers, rows)

    assert first == second
    assert memo_cards._parse_xlsx(first, "deterministic workbook") == (headers, rows)
    with zipfile.ZipFile(io.BytesIO(first), "r") as archive:
        worksheet = archive.read("xl/worksheets/sheet1.xml")
        assert b"<f" not in worksheet
        assert b't="inlineStr"' in worksheet
        assert b"=1+1" in worksheet


def test_missing_or_modified_sidecar_requires_confirmed_repair(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("repair", 1)])
    first = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, first["preview_digest"], "request"
    )
    workbook = environment["repo"] / "cards" / "topic-technical-qa.xlsx"
    workbook.unlink()

    missing = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert missing["operation"] == "update"
    assert "sidecar-missing" in missing["risk_reasons"]
    assert missing["required_authorization"] == "confirmed"
    memo_cards.publish(
        environment["repo"], environment["context"], request, missing["preview_digest"], "confirmed"
    )
    workbook.write_bytes(workbook.read_bytes() + b"drift")

    drifted = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert "sidecar-drift" in drifted["risk_reasons"]
    assert drifted["required_authorization"] == "confirmed"


def test_artifact_v1_target_migrates_only_with_confirmation(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("migrate", 1)])
    candidate = memo_cards.prepare(environment["repo"], environment["context"], request)
    match = re.match(
        r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z",
        candidate["candidate_markdown"],
        re.DOTALL,
    )
    assert match is not None
    manifest = json.loads(match.group("header"))
    legacy_body = "# Legacy managed TSV staging\n"
    manifest["schema"] = memo_cards.ARTIFACT_SCHEMA_V1
    manifest.pop("sidecars")
    manifest.pop("artifact_set_sha256")
    manifest["managed_body_sha256"] = memo_cards._sha256_text(legacy_body)
    manifest["manifest_payload_sha256"] = memo_cards._digest_value(
        {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    )
    target = environment["repo"] / "cards" / "topic.md"
    target.write_text(memo_cards._artifact_text(manifest, legacy_body), encoding="utf-8")
    (environment["repo"] / "cards" / "topic-technical-qa.xlsx").write_bytes(
        b"unmanaged workbook"
    )

    migration = memo_cards.prepare(environment["repo"], environment["context"], request)
    assert migration["operation"] == "update"
    assert migration["format_transition"] == {
        "from": memo_cards.ARTIFACT_SCHEMA_V1,
        "to": memo_cards.ARTIFACT_SCHEMA,
    }
    assert "artifact-v1-migration" in migration["risk_reasons"]
    assert "unmanaged-sidecar-adoption" in migration["risk_reasons"]
    assert migration["required_authorization"] == "confirmed"
    with pytest.raises(memo_cards.MemoCardsError, match="requires explicit"):
        memo_cards.publish(
            environment["repo"], environment["context"], request, migration["preview_digest"], "request"
        )
    memo_cards.publish(
        environment["repo"], environment["context"], request, migration["preview_digest"], "confirmed"
    )
    assert memo_cards.verify(environment["repo"], environment["context"], request)[
        "request_check"
    ]["operation"] == "no-op"


def test_inventory_verify_reports_sidecar_drift(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("inventory-sidecar", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, preview["preview_digest"], "request"
    )
    _set_tracked(
        environment,
        "cards/topic.md",
        "cards/topic-technical-qa.xlsx",
    )
    workbook = environment["repo"] / "cards" / "topic-technical-qa.xlsx"
    workbook.write_bytes(workbook.read_bytes() + b"drift")

    verified = memo_cards.verify(environment["repo"], environment["context"])
    assert verified["managed_artifacts"][0]["artifact_set_drifted"] is True
    assert verified["managed_artifacts"][0]["sidecars"][0]["status"] == "sha256-mismatch"
    assert verified["sidecar_drift"][0]["path"] == "cards/topic-technical-qa.xlsx"


def test_removing_last_card_for_template_removes_owned_sidecar(tmp_path: Path) -> None:
    environment = _environment(tmp_path, maximum=10)
    request, _value = _request(
        environment,
        [
            _card("correction", 1, template_id="correction"),
            _card("technical", 2),
        ],
    )
    first = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"], environment["context"], request, first["preview_digest"], "request"
    )
    correction = environment["repo"] / "cards" / "topic-correction.xlsx"
    assert correction.is_file()

    second_request, _value = _request(environment, [_card("technical", 2)])
    second = memo_cards.prepare(environment["repo"], environment["context"], second_request)
    assert "card-removal" in second["risk_reasons"]
    assert "sidecar-removal" in second["risk_reasons"]
    assert any(
        file["path"] == "cards/topic-correction.xlsx" and file["operation"] == "remove"
        for file in second["files"]
    )
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        second_request,
        second["preview_digest"],
        "confirmed",
    )
    assert not correction.exists()


def test_multifile_install_failure_rolls_back_new_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path, maximum=10)
    request, _value = _request(
        environment,
        [
            _card("correction", 1, template_id="correction"),
            _card("technical", 2),
        ],
    )
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    original_link = memo_cards.os.link

    def fail_markdown_install(source: Path, destination: Path) -> None:
        if Path(destination).suffix == ".md":
            raise OSError("synthetic Markdown installation failure")
        original_link(source, destination)

    monkeypatch.setattr(memo_cards.os, "link", fail_markdown_install)
    with pytest.raises(OSError, match="synthetic Markdown"):
        memo_cards.publish(
            environment["repo"], environment["context"], request, preview["preview_digest"], "request"
        )

    assert not (environment["repo"] / "cards" / "topic.md").exists()
    assert list((environment["repo"] / "cards").glob("topic-*.xlsx")) == []
    assert list((environment["repo"] / "cards").glob("*.tmp")) == []
    assert list((environment["repo"] / "cards").glob("*transaction.json")) == []


def test_source_cas_detects_drift(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("source", 1)])
    environment["source"].write_text("changed", encoding="utf-8")

    with pytest.raises(memo_cards.MemoCardsError, match="source changed"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_source_must_be_utf8_even_when_collection_allows_binary_members(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["source"].write_bytes(b"\xff\xfebinary")
    request, _value = _request(environment, [_card("utf8-source", 1)])

    with pytest.raises(memo_cards.MemoCardsError, match="UTF-8"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_publish_rechecks_source_inside_artifact_set_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("source-window", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    original_publish_set = memo_cards._atomic_publish_set

    def mutate_before_transaction(
        files: Any, target: Path, source_preconditions: Any = ()
    ) -> None:
        environment["source"].write_text("changed during publication\n", encoding="utf-8")
        original_publish_set(files, target, source_preconditions)

    monkeypatch.setattr(memo_cards, "_atomic_publish_set", mutate_before_transaction)
    with pytest.raises(memo_cards.MemoCardsError, match="source changed during publication"):
        memo_cards.publish(
            environment["repo"],
            environment["context"],
            request,
            preview["preview_digest"],
            "request",
        )

    assert not (environment["repo"] / "cards" / "topic.md").exists()
    assert list((environment["repo"] / "cards").glob("topic-*.xlsx")) == []
    assert not (
        environment["repo"] / "cards" / memo_cards.PUBLICATION_LOCK_NAME
    ).exists()


def test_repository_lock_serializes_cross_target_inventory_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    request_a, value_a = _request(
        environment, [_card("shared-logical-id", 1)], target="cards/a.md"
    )
    request_a = environment["repo"] / "request-a.json"
    _write_json(request_a, value_a)
    request_b, value_b = _request(
        environment, [_card("shared-logical-id", 1)], target="cards/b.md"
    )
    request_b = environment["repo"] / "request-b.json"
    _write_json(request_b, value_b)
    preview_a = memo_cards.prepare(environment["repo"], environment["context"], request_a)
    preview_b = memo_cards.prepare(environment["repo"], environment["context"], request_b)

    entered = threading.Event()
    release = threading.Event()
    original_prepare = memo_cards._prepare_plan

    def block_first_plan(*args: Any, **kwargs: Any) -> Any:
        if threading.current_thread().name == "first-publisher":
            entered.set()
            assert release.wait(timeout=5)
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(memo_cards, "_prepare_plan", block_first_plan)
    first_result: list[Any] = []

    def run_first() -> None:
        try:
            first_result.append(
                memo_cards.publish(
                    environment["repo"],
                    environment["context"],
                    request_a,
                    preview_a["preview_digest"],
                    "request",
                )
            )
        except Exception as exc:  # pragma: no cover - asserted below
            first_result.append(exc)

    thread = threading.Thread(target=run_first, name="first-publisher")
    thread.start()
    assert entered.wait(timeout=5)
    assert (environment["repo"] / "cards" / memo_cards.PUBLICATION_LOCK_NAME).is_file()
    assert not (environment["repo"] / memo_cards.PUBLICATION_LOCK_NAME).exists()
    try:
        with pytest.raises(memo_cards.MemoCardsError, match="another memo-cards publication"):
            memo_cards.publish(
                environment["repo"],
                environment["context"],
                request_b,
                preview_b["preview_digest"],
                "request",
            )
    finally:
        release.set()
        thread.join(timeout=5)

    assert len(first_result) == 1 and isinstance(first_result[0], dict)
    assert (environment["repo"] / "cards" / "a.md").is_file()
    assert not (environment["repo"] / "cards" / "b.md").exists()
    with pytest.raises(memo_cards.MemoCardsError, match="preview digest no longer matches"):
        memo_cards.publish(
            environment["repo"],
            environment["context"],
            request_b,
            preview_b["preview_digest"],
            "request",
        )
    assert not (environment["repo"] / "cards" / "b.md").exists()


def test_verify_finds_orphan_transaction_without_markdown(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    journal = (
        environment["repo"]
        / "cards"
        / f".topic.md{memo_cards.TRANSACTION_JOURNAL_SUFFIX}"
    )
    journal.write_text("{}\n", encoding="utf-8")
    (environment["repo"] / "cards" / "topic-technical-qa.xlsx").write_bytes(b"orphan")

    verified = memo_cards.verify(environment["repo"], environment["context"])

    assert verified["inventory_unavailable"] is True
    assert verified["managed_artifacts"] == []
    assert verified["interrupted_transactions"] == [
        {
            "path": "cards/.topic.md.memo-cards-transaction.json",
            "sha256": _digest(journal),
            "status": "present",
        }
    ]
    request, _value = _request(environment, [_card("blocked-by-journal", 1)])
    with pytest.raises(memo_cards.MemoCardsError, match="requires recovery"):
        memo_cards.prepare(environment["repo"], environment["context"], request)


def test_verify_reports_update_journal_before_missing_tracked_markdown(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    request, _value = _request(environment, [_card("tracked-update", 1)])
    preview = memo_cards.prepare(environment["repo"], environment["context"], request)
    memo_cards.publish(
        environment["repo"],
        environment["context"],
        request,
        preview["preview_digest"],
        "request",
    )
    _set_tracked(
        environment,
        "cards/topic.md",
        "cards/topic-technical-qa.xlsx",
    )
    target = environment["repo"] / "cards" / "topic.md"
    target.rename(environment["repo"] / "cards" / ".topic.md.synthetic-hold")
    journal = (
        environment["repo"]
        / "cards"
        / f".topic.md{memo_cards.TRANSACTION_JOURNAL_SUFFIX}"
    )
    journal.write_text("{}\n", encoding="utf-8")

    verified = memo_cards.verify(environment["repo"], environment["context"], request)

    assert verified["inventory_unavailable"] is True
    assert verified["interrupted_transactions"][0]["path"] == (
        "cards/.topic.md.memo-cards-transaction.json"
    )
    assert verified["request_check"] == {
        "operation": "blocked",
        "would_write": True,
        "blocking_reasons": ["interrupted-publication"],
    }
    with pytest.raises(memo_cards.MemoCardsError, match="requires recovery"):
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
    assert [artifact["path"] for artifact in verified["managed_artifacts"]] == [
        "cards/topic.md"
    ]
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
    assert emoji not in payload["data"]["candidate_markdown"]
    assert payload["data"]["candidate_sidecars"][0]["row_count"] == 1
