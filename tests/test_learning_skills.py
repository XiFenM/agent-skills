from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_ROOT = ROOT / "skills" / "guide-learning"
RETIRED_SKILL_NAMES = {"learn-by-practice", "study-companion"}
LEARNING_USER_GUIDES = {
    "english-coach": "english-coach.md",
    "guide-learning": "guide-learning.md",
    "memo-cards": "memo-cards.md",
    "resource-planning": "resource-planning.md",
    "study-log": "study-log.md",
}

REFERENCE_FILES = {
    "article-artifacts.md",
    "material-reading.md",
    "practice-review-mastery.md",
    "repository-adaptation.md",
    "source-authority.md",
    "state-records.md",
    "teaching-cycle.md",
    "teaching-exemplars.md",
}
EXPECTED_GUIDE_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/context_config.py",
    "scripts/material_reader.py",
    "tests/test_guide_learning_context.py",
    "tests/test_material_reader.py",
    *(f"references/{name}" for name in REFERENCE_FILES),
}

# Size budgets keep the agent-facing text from growing by accretion. Raise them
# only together with a deliberate removal elsewhere.
GUIDE_MAIN_MAX_LINES = 170
GUIDE_TOTAL_MAX_BYTES = 85_000
FIRST_USE_SECTION_MAX_LINES = 8


def _relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    }


def _text_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py", ".yaml"}
    ]


def _h2_headings(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+?)\s*$", text)


def _section(text: str, heading_prefix: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading_prefix)}[^\n]*\n(?P<body>.*?)(?=^## |\Z)",
        text,
    )
    assert match is not None, heading_prefix
    return match.group("body")


def _index_of_heading(headings: list[str], prefix: str) -> int:
    for index, heading in enumerate(headings):
        if heading.startswith(prefix):
            return index
    raise AssertionError(f"missing heading starting with {prefix!r}: {headings}")


def test_guide_learning_has_the_exact_progressive_disclosure_tree() -> None:
    assert {path.name for path in GUIDE_ROOT.iterdir()} == {
        "SKILL.md",
        "agents",
        "references",
        "scripts",
        "tests",
    }
    assert _relative_files(GUIDE_ROOT) == EXPECTED_GUIDE_FILES


def test_guide_learning_frontmatter_and_main_are_compact() -> None:
    text = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    assert match is not None
    frontmatter_keys = {
        line.split(":", 1)[0].strip()
        for line in match.group("body").splitlines()
        if line.strip()
    }
    assert frontmatter_keys == {"name", "description"}
    assert re.search(r"(?m)^name:\s*[\"']?guide-learning[\"']?\s*$", match.group("body"))
    assert len(text.splitlines()) <= GUIDE_MAIN_MAX_LINES


def test_guide_learning_stays_within_its_size_budget() -> None:
    files = [GUIDE_ROOT / "SKILL.md", *sorted((GUIDE_ROOT / "references").glob("*.md"))]
    total = sum(len(path.read_bytes()) for path in files)
    assert total <= GUIDE_TOTAL_MAX_BYTES, total


def test_guide_learning_links_every_one_level_reference() -> None:
    main = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\(references/([^/)]+\.md)\)", main))
    assert linked == REFERENCE_FILES

    for name in REFERENCE_FILES:
        text = (GUIDE_ROOT / "references" / name).read_text(encoding="utf-8")
        if len(text.splitlines()) > 100:
            assert "## Contents" in text, name


def test_guide_learning_openai_metadata_routes_to_the_skill() -> None:
    metadata = (GUIDE_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    top_level = [line for line in metadata.splitlines() if line and not line[0].isspace()]
    assert top_level == ["interface:"]

    interface = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r'(?m)^\s{2}([a-z_]+):\s*"([^"]*)"\s*$',
            metadata,
        )
    }
    assert set(interface) == {"display_name", "short_description", "default_prompt"}
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$guide-learning" in interface["default_prompt"]


def test_guide_learning_puts_teaching_before_governance() -> None:
    main = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    headings = _h2_headings(main)

    teaching = [
        _index_of_heading(headings, prefix)
        for prefix in ("讲解标准", "提问", "按学习者调节节奏", "一堂课的结构")
    ]
    governance = [
        _index_of_heading(headings, prefix)
        for prefix in ("选择运行范围", "状态", "授权", "正式练习与结课")
    ]
    assert teaching == sorted(teaching)
    assert max(teaching) < min(governance)
    assert headings[_index_of_heading(headings, "首次启用") + 1].startswith("讲解标准")

    standard = _section(main, "讲解标准")
    assert len(re.findall(r"(?m)^\d\. \*\*", standard)) == 5
    assert "(references/teaching-exemplars.md)" in standard


def test_guide_learning_references_keep_their_teaching_structure() -> None:
    cycle = (GUIDE_ROOT / "references" / "teaching-cycle.md").read_text(encoding="utf-8")
    numbered = [
        int(match)
        for match in re.findall(r"(?m)^## (\d+)\. ", cycle)
    ]
    assert numbered == list(range(1, 11))

    exemplars = (GUIDE_ROOT / "references" / "teaching-exemplars.md").read_text(
        encoding="utf-8"
    )
    exemplar_headings = _h2_headings(exemplars)
    assert sum(heading.startswith("示例") for heading in exemplar_headings) >= 2
    assert any(heading.startswith("写法对照") for heading in exemplar_headings)
    assert exemplars.count("### 检查题") >= 2


def test_guide_learning_keeps_core_behavior_anchors() -> None:
    main = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    teaching = (GUIDE_ROOT / "references" / "teaching-cycle.md").read_text(encoding="utf-8")
    practice = (GUIDE_ROOT / "references" / "practice-review-mastery.md").read_text(
        encoding="utf-8"
    )
    user_guide = (ROOT / "docs" / "user-guides" / "guide-learning.md").read_text(
        encoding="utf-8"
    )

    # Validation and experiment methods stay agent-owned by default.
    assert "测试驱动" in main and "harness" in main
    assert "warm-up" in teaching
    assert all(term in practice for term in ("expected red", "我维护", "支持", "否定", "证据不足"))
    assert "实验方法" in user_guide
    # Practice contracts are versioned without hand-computed digests.
    assert "digest" not in practice.lower()
    assert "sha-256" not in practice.lower()


def test_guide_learning_requires_a_learner_profile() -> None:
    main = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    headings = _h2_headings(main)

    # The profile is established before a lesson is structured.
    assert _index_of_heading(headings, "学习者画像") < _index_of_heading(headings, "一堂课的结构")
    profile = _section(main, "学习者画像")
    assert "learner-preferences" in profile
    assert "(references/repository-adaptation.md)" in profile
    assert "学习者画像" in _section(main, "授权")

    adaptation = (GUIDE_ROOT / "references" / "repository-adaptation.md").read_text(
        encoding="utf-8"
    )
    interview = _section(adaptation, "6. 学习者画像")
    assert "learner-preferences" in interview
    assert len(re.findall(r"(?m)^\d\. ", interview)) == 6


def test_guide_learning_points_the_learner_at_the_teaching_spine() -> None:
    main = (GUIDE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    cycle = (GUIDE_ROOT / "references" / "teaching-cycle.md").read_text(encoding="utf-8")

    # Once in the opening and once per node.
    structure = re.sub(r"\s+", "", _section(main, "一堂课的结构"))
    assert structure.count("教学主线资料") >= 2
    assert "先指路" in _section(cycle, "2. 开课导入")
    assert "教学主线资料" in _section(cycle, "5. 讲一个节点")


def test_guide_learning_contains_no_consumer_or_session_format_coupling() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _text_files(GUIDE_ROOT)
        if "tests" not in path.relative_to(GUIDE_ROOT).parts
    )
    for forbidden in ("PlanA", "JSONL", ".jsonl", "TODO"):
        assert forbidden not in combined
    slash_command = re.compile(
        r"(?<![A-Za-z0-9_)])/(?!/)[A-Za-z0-9_\-㐀-鿿]+"
    )
    # Slash commands are a user-facing instruction concern. Python shebangs and
    # filesystem handling are not commands being required of the learner.
    instructions = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _text_files(GUIDE_ROOT)
        if path.suffix in {".md", ".yaml"}
    )
    without_urls = re.sub(r"https?://[^\s)>]+", "", instructions)
    assert slash_command.search(without_urls) is None


def test_learning_skills_announce_user_guides_once_per_conversation() -> None:
    combined_guide = ROOT / "docs" / "learning-skills-user-guide.md"
    assert combined_guide.is_file()
    public_root = "https://github.com/XiFenM/agent-skills/blob/main/docs/"

    for skill_name, guide_name in LEARNING_USER_GUIDES.items():
        skill = (ROOT / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert (ROOT / "docs" / "user-guides" / guide_name).is_file()

        section = _section(skill, "首次启用")
        compact = re.sub(r"\s+", "", section)
        assert f"docs/user-guides/{guide_name}" in compact, skill_name
        assert "docs/learning-skills-user-guide.md" in compact, skill_name
        assert f"{public_root}user-guides/{guide_name}" in compact, skill_name
        assert f"{public_root}learning-skills-user-guide.md" in compact, skill_name
        non_empty = [line for line in section.splitlines() if line.strip()]
        assert len(non_empty) <= FIRST_USE_SECTION_MAX_LINES, skill_name


def test_retired_learning_skills_leave_no_runtime_entry_or_route() -> None:
    skills_root = ROOT / "skills"
    for name in RETIRED_SKILL_NAMES:
        assert not (skills_root / name).exists()

    assert list(skills_root.rglob("export_codex_dialogue.py")) == []
    assert list(skills_root.rglob("dialogue-archive.md")) == []

    active_text = "\n".join(
        path.read_text(encoding="utf-8") for path in _text_files(skills_root)
    )
    for name in RETIRED_SKILL_NAMES:
        assert name not in active_text
