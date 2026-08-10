import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from scripts.export_codex_dialogue import (  # noqa: E402
    DialogueExportError,
    load_dialogue,
    main,
    normalize_user_text,
    render_markdown,
    select_dialogue,
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


def _write_session(path: Path) -> None:
    rows = [
        {
            "timestamp": "2026-07-20T00:00:00Z",
            "type": "session_meta",
            "payload": {"session_id": "session-123"},
        },
        _message_row(
            "2026-07-20T00:00:01Z",
            "developer",
            "internal instruction",
        ),
        _message_row(
            "2026-07-20T00:00:02Z",
            "user",
            "<environment_context><cwd>/workspace</cwd></environment_context>",
        ),
        _message_row("2026-07-20T00:00:03Z", "user", "开始第一课"),
        _message_row(
            "2026-07-20T00:00:03.500Z",
            "user",
            "<skill>\n<name>example</name>\n# Injected instructions\n</skill>",
        ),
        _message_row(
            "2026-07-20T00:00:03.750Z",
            "user",
            "<recommended_plugins>\n- Example\n</recommended_plugins>\n"
            "# AGENTS.md instructions for /workspace\n\n"
            "<INSTRUCTIONS>\n# Repository Guidelines\nInternal context\n</INSTRUCTIONS>",
        ),
        _message_row(
            "2026-07-20T00:00:04Z",
            "user",
            "# Context from my IDE setup:\n\n"
            "## Active file: demo.py\n\n"
            "## My request for Codex:\n开始第一课",
        ),
        _message_row(
            "2026-07-20T00:00:05Z",
            "assistant",
            "我先检查代码。",
            phase="commentary",
        ),
        {
            "timestamp": "2026-07-20T00:00:06Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command"},
        },
        _message_row(
            "2026-07-20T00:00:07Z",
            "assistant",
            "## 正式讲解\n\n这是正文。",
            phase="final_answer",
        ),
        _message_row("2026-07-20T00:00:08Z", "user", "结束本课"),
        _message_row(
            "2026-07-20T00:00:09Z",
            "assistant",
            "本课之后的消息。",
            phase="final_answer",
        ),
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_normalize_user_text_strips_client_wrappers() -> None:
    text = (
        "<environment_context><cwd>/workspace</cwd></environment_context>\n"
        "# Context from my IDE setup:\n\n"
        "## Active file: demo.py\n\n"
        "## My request for Codex:\n请解释 mask"
    )
    assert normalize_user_text(text) == "请解释 mask"
    assert normalize_user_text("# Context from my IDE setup:\nonly context") == ""
    assert (
        normalize_user_text(
            "<skill>\n<name>learn-by-practice</name>\n# Injected instructions\n</skill>"
        )
        == ""
    )
    assert (
        normalize_user_text(
            "<recommended_plugins>\n- Example\n</recommended_plugins>\n"
            "# AGENTS.md instructions for /workspace\n\n"
            "<INSTRUCTIONS>\n# Repository Guidelines\nInternal context\n</INSTRUCTIONS>"
        )
        == ""
    )
    assert (
        normalize_user_text(
            "<recommended_plugins>\n- Example\n</recommended_plugins>\n"
            "# AGENTS.md instructions for /workspace\n\n"
            "<INSTRUCTIONS>\n# Repository Guidelines\nInternal context\n</INSTRUCTIONS>\n"
            "请继续本课"
        )
        == "请继续本课"
    )


def test_load_and_select_dialogue_excludes_internal_events(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    _write_session(session)

    messages, metadata = load_dialogue(session)

    assert metadata.session_id == "session-123"
    assert len(metadata.source_sha256) == 64
    assert [message.text for message in messages] == [
        "开始第一课",
        "我先检查代码。",
        "## 正式讲解\n\n这是正文。",
        "结束本课",
        "本课之后的消息。",
    ]

    messages_with_context, _ = load_dialogue(session, keep_client_context=True)
    assert any(message.text.startswith("<skill>") for message in messages_with_context)

    selected = select_dialogue(
        messages,
        start_user="开始第一课",
        end_before_user="结束本课",
    )
    assert [message.role for message in selected] == ["user", "assistant", "assistant"]

    final_only = select_dialogue(
        messages,
        start_user="开始第一课",
        end_before_user="结束本课",
        final_only=True,
    )
    assert [message.text for message in final_only] == [
        "开始第一课",
        "## 正式讲解\n\n这是正文。",
    ]


def test_select_dialogue_rejects_missing_marker(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    _write_session(session)
    messages, _ = load_dialogue(session)

    with pytest.raises(DialogueExportError, match="--start-user"):
        select_dialogue(messages, start_user="不存在的开头")


def test_render_markdown_preserves_message_bodies(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    _write_session(session)
    messages, metadata = load_dialogue(session)
    selected = select_dialogue(
        messages,
        start_user="开始第一课",
        end_before_user="结束本课",
    )

    rendered = render_markdown(
        selected,
        metadata,
        title="第 01 课原始对话",
        lesson="01-vector-add",
        keep_client_context=False,
        keep_duplicates=False,
        final_only=False,
        exported_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert 'archive_type: "codex-raw-dialogue"' in rendered
    assert 'lesson: "01-vector-add"' in rendered
    assert "message_count: 3" in rendered
    assert "**001 · 用户**" in rendered
    assert "**002 · 助手 / 过程更新**" in rendered
    assert "**003 · 助手 / 正式回答**" in rendered
    assert "## 正式讲解\n\n这是正文。" in rendered
    assert "Generated by export_codex_dialogue.py" in rendered
    assert "internal instruction" not in rendered
    assert "exec_command" not in rendered


def test_cli_exports_and_refuses_accidental_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = tmp_path / "rollout.jsonl"
    output = tmp_path / "dialogue.md"
    _write_session(session)
    arguments = [
        "export",
        str(session),
        str(output),
        "--title",
        "原始对话",
        "--start-user",
        "开始第一课",
        "--end-before-user",
        "结束本课",
    ]

    assert main(arguments) == 0
    assert output.is_file()
    assert "exported 3 messages" in capsys.readouterr().out

    assert main(arguments) == 2
    assert "--overwrite" in capsys.readouterr().err
