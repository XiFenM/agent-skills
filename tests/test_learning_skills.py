from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE_ROOT = ROOT / "skills" / "guide-learning"
RETIRED_SKILL_NAMES = {"learn-by-practice", "study-companion"}

REFERENCE_FILES = {
    "examples.md",
    "practice-review-mastery.md",
    "repository-adaptation.md",
    "source-authority.md",
    "state-records.md",
    "teaching-cycle.md",
}
EXPECTED_GUIDE_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/context_config.py",
    "tests/test_guide_learning_context.py",
    *(f"references/{name}" for name in REFERENCE_FILES),
}


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
    assert len(text.splitlines()) < 500


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


def test_guide_learning_contains_no_consumer_or_session_format_coupling() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _text_files(GUIDE_ROOT)
        if "tests" not in path.relative_to(GUIDE_ROOT).parts
    )
    for forbidden in ("PlanA", "JSONL", ".jsonl", "TODO"):
        assert forbidden not in combined
    slash_command = re.compile(
        r"(?<![A-Za-z0-9_)])/(?!/)[A-Za-z0-9_\-\u3400-\u9fff]+"
    )
    assert slash_command.search(combined) is None


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
