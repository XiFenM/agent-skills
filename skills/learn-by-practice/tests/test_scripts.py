from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = SKILL_ROOT / "scripts" / "init_learning_archive.py"
EXPORT_SCRIPT = SKILL_ROOT / "scripts" / "export_codex_dialogue.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _message_row(
    timestamp: str,
    role: str,
    text: str,
    *,
    phase: str | None = None,
) -> dict[str, object]:
    content_type = "output_text" if role == "assistant" else "input_text"
    payload: dict[str, object] = {
        "type": "message",
        "role": role,
        "content": [{"type": content_type, "text": text}],
    }
    if phase is not None:
        payload["phase"] = phase
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


def test_initializer_creates_rendered_archive_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    result = _run(
        str(INIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--subject",
        "Rust async programming",
        "--slug",
        "rust-async",
        "--source",
        "The Rust Async Book | local examples",
        "--start-date",
        "2026-07-21",
    )

    assert result.returncode == 0, result.stderr
    archive = tmp_path / "docs" / "learning" / "rust-async"
    index = (archive / "README.md").read_text(encoding="utf-8")
    assert "# Rust async programming learning archive" in index
    assert "The Rust Async Book \\| local examples" in index
    assert "2026-07-21" in index
    assert "AI agent write the minimal acceptance tests" in index
    assert "{{" not in index
    lesson_template = archive / "templates" / "lesson-record.md"
    assert lesson_template.is_file()
    lesson_text = lesson_template.read_text(encoding="utf-8")
    assert "Agent-authored acceptance tests or rubric ready" in lesson_text
    assert "Keep routine test authoring out of the learner task" in lesson_text
    assert (archive / "lessons").is_dir()
    assert (archive / "dialogues").is_dir()

    repeated = _run(
        str(INIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--subject",
        "Rust async programming",
        "--slug",
        "rust-async",
    )
    assert repeated.returncode == 2
    assert "already exists" in repeated.stderr


def test_initializer_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _run(
        str(INIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--subject",
        "Compiler Design",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "would create learning archive" in result.stdout
    assert not (tmp_path / "docs").exists()


def test_initializer_resolves_relative_archive_from_root(tmp_path: Path) -> None:
    result = _run(
        str(INIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--subject",
        "Operating Systems",
        "--archive",
        "notes/os-course",
        "--start-date",
        "2026-07-21",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "notes" / "os-course" / "README.md").is_file()


def test_initializer_requires_explicit_slug_for_non_ascii_subject(
    tmp_path: Path,
) -> None:
    result = _run(
        str(INIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--subject",
        "编译原理",
    )

    assert result.returncode == 2
    assert "provide --slug explicitly" in result.stderr


def test_exporter_keeps_visible_interval_and_provenance(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    output = tmp_path / "dialogue.md"
    rows = [
        {
            "timestamp": "2026-07-21T00:00:00Z",
            "type": "session_meta",
            "payload": {"session_id": "session-123"},
        },
        _message_row(
            "2026-07-21T00:00:01Z",
            "developer",
            "internal instruction",
        ),
        _message_row("2026-07-21T00:00:02Z", "user", "Start lesson"),
        _message_row(
            "2026-07-21T00:00:02.500Z",
            "user",
            "<skill>\n<name>example</name>\n# Injected instructions\n</skill>",
        ),
        _message_row(
            "2026-07-21T00:00:03Z",
            "assistant",
            "I will inspect the source.",
            phase="commentary",
        ),
        _message_row(
            "2026-07-21T00:00:04Z",
            "assistant",
            "Here is the explanation.",
            phase="final_answer",
        ),
        _message_row("2026-07-21T00:00:05Z", "user", "Next lesson"),
    ]
    session.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _run(
        str(EXPORT_SCRIPT),
        "export",
        str(session),
        str(output),
        "--title",
        "Lesson dialogue",
        "--lesson",
        "01-example",
        "--start-user",
        "Start lesson",
        "--end-before-user",
        "Next lesson",
    )

    assert result.returncode == 0, result.stderr
    rendered = output.read_text(encoding="utf-8")
    assert 'session_id: "session-123"' in rendered
    assert "message_count: 3" in rendered
    assert "Start lesson" in rendered
    assert "I will inspect the source." in rendered
    assert "Here is the explanation." in rendered
    assert "internal instruction" not in rendered
    assert "Injected instructions" not in rendered
    assert "Next lesson" not in rendered
