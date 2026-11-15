from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "vivid-language"

EXPECTED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "assets/article-brief.md",
    "assets/rewrite-worksheet.md",
    "assets/video-shot-sheet.md",
    "references/chinese-editing.md",
    "references/close-readings.md",
    "references/conversation.md",
    "references/diagnosis.md",
    "references/language-contract.md",
    "references/moves.md",
    "references/output-formats.md",
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
    "conversation.md",
    "diagnosis.md",
    "language-contract.md",
    "moves.md",
    "output-formats.md",
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
        r"(?m)^name:\s*[\"']?vivid-language[\"']?\s*$", match.group("body")
    )


def test_main_text_stays_compact() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 180
    assert len(text.encode("utf-8")) <= 12_000


def test_main_text_claims_every_output_in_the_session() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "本 Skill 一旦启用，就管当前对话里你输出的所有文字" in text
    for register in ("对话反馈", "工程书面", "教学讲解", "课程网页", "记忆卡片", "参考文档"):
        assert register in text, register


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
    assert "$vivid-language" in interface["default_prompt"]


def test_moves_cover_the_nine_headings() -> None:
    text = (SKILL / "references" / "moves.md").read_text(encoding="utf-8")
    numbers = [int(match) for match in re.findall(r"(?m)^## (\d)\. ", text)]
    assert numbers == list(range(1, 10))


def test_language_contract_covers_every_register_and_skill() -> None:
    text = (SKILL / "references" / "language-contract.md").read_text(encoding="utf-8")
    for anchor in (
        "十条通用契约",
        "对话反馈",
        "工程书面",
        "技术文章",
        "教学讲解",
        "课程网页",
        "学习文章",
        "记忆卡片",
        "视频口播",
        "参考文档",
        "共享检查清单",
        "交接",
    ):
        assert anchor in text, anchor
    for skill in ("guide-learning", "lesson-pages", "memo-cards", "english-coach"):
        assert skill in text, skill
    assert "完整优先于短" in text
    assert "plain-language.md" in text
    assert "conversation.md" in text


def test_conversation_reference_covers_the_eight_moves() -> None:
    text = (SKILL / "references" / "conversation.md").read_text(encoding="utf-8")
    for anchor in (
        "开工",
        "确认",
        "进展",
        "提问",
        "汇报结果",
        "报错/失败",
        "拒绝/边界",
        "收尾",
        "五条硬规则",
        "结论先行",
        "自检 10 条",
    ):
        assert anchor in text, anchor
    assert "Before / after" in text
    assert "很抱歉给您带来不便" in text


def test_output_formats_cover_the_five_modes() -> None:
    text = (SKILL / "references" / "output-formats.md").read_text(encoding="utf-8")
    for mode in ("diagnose", "rewrite", "draft", "video", "coach"):
        assert f"## {mode}" in text, mode


def test_plain_language_reference_covers_all_outputs_and_the_two_passes() -> None:
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
        assert anchor in text, anchor
    assert "2–3 个主比喻" in text
    assert "API 参考" in text
    assert "对话、教学、页面、卡片、文章和视频" in text


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
    guide = ROOT / "docs" / "user-guides" / "vivid-language.md"
    assert guide.is_file()
    assert "vivid-language" in guide.read_text(encoding="utf-8")


def test_readme_lists_the_skill() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "vivid-language" in readme
