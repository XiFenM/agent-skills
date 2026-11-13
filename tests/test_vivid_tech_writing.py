from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "vivid-tech-writing"

EXPECTED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "assets/article-brief.md",
    "assets/rewrite-worksheet.md",
    "assets/video-shot-sheet.md",
    "references/chinese-editing.md",
    "references/close-readings.md",
    "references/diagnosis.md",
    "references/moves.md",
    "references/plain-language.md",
    "references/practice.md",
    "references/source-library.md",
    "references/video-script.md",
    "scripts/style_lint.py",
    "tests/test_style_lint.py",
}

EXPECTED_REFERENCES = {
    "chinese-editing.md",
    "close-readings.md",
    "diagnosis.md",
    "moves.md",
    "plain-language.md",
    "practice.md",
    "source-library.md",
    "video-script.md",
}

EXPECTED_ASSETS = {
    "article-brief.md",
    "rewrite-worksheet.md",
    "video-shot-sheet.md",
}


def _relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    }


def test_exact_file_tree() -> None:
    assert _relative_files(SKILL) == EXPECTED_FILES


def test_frontmatter_is_minimal_and_names_the_skill() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    assert match is not None
    keys = {
        line.split(":", 1)[0].strip()
        for line in match.group("body").splitlines()
        if line.strip()
    }
    assert keys == {"name", "description"}
    assert re.search(
        r"(?m)^name:\s*[\"']?vivid-tech-writing[\"']?\s*$", match.group("body")
    )


def test_main_text_stays_compact() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 180
    assert len(text.encode("utf-8")) <= 12_000


def test_every_reference_and_asset_is_linked() -> None:
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    references = set(re.findall(r"\((references/[^)]+\.md)\)", main))
    assets = set(re.findall(r"\((assets/[^)]+\.md)\)", main))
    assert {path.split("/", 1)[1] for path in references} == EXPECTED_REFERENCES
    assert {path.split("/", 1)[1] for path in assets} == EXPECTED_ASSETS


def test_local_links_point_to_existing_files() -> None:
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\((?!https?://|#)([^)]+)\)", main)
    for link in links:
        assert (SKILL / link).is_file(), link


def test_openai_metadata_routes_to_the_skill() -> None:
    metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
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
    assert "$vivid-tech-writing" in interface["default_prompt"]


def test_moves_cover_the_nine_headings() -> None:
    text = (SKILL / "references" / "moves.md").read_text(encoding="utf-8")
    numbers = [int(match) for match in re.findall(r"(?m)^## (\d)\. ", text)]
    assert numbers == list(range(1, 10))


def test_plain_language_reference_covers_the_two_passes() -> None:
    text = (SKILL / "references" / "plain-language.md").read_text(encoding="utf-8")
    for anchor in (
        "先给一句话答案",
        "流程/阶段图",
        "日常物件",
        "比喻的三条规矩",
        "搜索",
        "部署",
        "x_max",
        "自检 8 条",
    ):
        assert anchor in text
    assert "2–3 个主比喻" in text
    assert "API 参考" in text


def test_close_readings_cover_six_passages() -> None:
    text = (SKILL / "references" / "close-readings.md").read_text(encoding="utf-8")
    numbers = [int(match) for match in re.findall(r"(?m)^## (\d)\. ", text)]
    assert numbers == list(range(1, 7))


def test_diagnosis_names_the_seven_symptoms() -> None:
    text = (SKILL / "references" / "diagnosis.md").read_text(encoding="utf-8")
    for symptom in (
        "名词化",
        "无主语",
        "抽象悬空",
        "信息平权",
        "零悬念",
        "术语前置",
        "没有“我/你”",
    ):
        assert symptom in text


def test_source_library_has_a_shortlist_and_entries() -> None:
    text = (SKILL / "references" / "source-library.md").read_text(encoding="utf-8")
    assert "如果只选五个" in text
    assert text.count("|") >= 40


def test_user_guide_is_registered() -> None:
    guide = ROOT / "docs" / "user-guides" / "vivid-tech-writing.md"
    assert guide.is_file()
    assert "vivid-tech-writing" in guide.read_text(encoding="utf-8")


def test_readme_lists_the_skill() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "vivid-tech-writing" in readme
