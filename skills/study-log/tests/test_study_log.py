from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import study_log  # noqa: E402


def _jsonl(path: Path, rows: list[dict[str, object]], *, broken_tail: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    if broken_tail:
        text += '{"timestamp":"2026-08-10T10:00:09Z","type":"response_item"'
    path.write_text(text, encoding="utf-8")


def _codex_message(
    timestamp: str,
    role: str,
    text: str,
    *,
    phase: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "message",
        "role": role,
        "content": [
            {"type": "input_text" if role == "user" else "output_text", "text": text}
        ],
    }
    if phase:
        payload["phase"] = phase
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


def _codex_rows(project: Path | str, *, session_id: str = "codex-session-001") -> list[dict[str, object]]:
    return [
        {
            "timestamp": "2026-08-10T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": str(project)},
        },
        _codex_message("2026-08-10T10:00:01Z", "user", "开始学习调度器"),
        _codex_message(
            "2026-08-10T10:00:02Z", "assistant", "我先说明队列边界。", phase="commentary"
        ),
        _codex_message(
            "2026-08-10T10:00:03Z", "assistant", "请求先进入等待队列。", phase="final_answer"
        ),
        _codex_message("2026-08-10T10:00:04Z", "user", "我理解为请求会立刻执行。"),
        _codex_message(
            "2026-08-10T10:00:05Z", "assistant", "需要纠正：入队不等于执行。", phase="final_answer"
        ),
    ]


def _claude_rows(project: Path | str, *, session_id: str = "claude-session-001") -> list[dict[str, object]]:
    return [
        {
            "type": "user",
            "sessionId": session_id,
            "cwd": str(project),
            "timestamp": "2026-08-10T11:00:01Z",
            "message": {"role": "user", "content": "讲解张量并行"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "cwd": str(project),
            "timestamp": "2026-08-10T11:00:02Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "text", "text": "先按权重维度切分。"},
                    {"type": "tool_use", "name": "Read", "input": {"path": "notes.md"}},
                ],
            },
        },
    ]


@pytest.fixture
def isolated_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    roots = {
        "codex": tmp_path / "codex-sessions",
        "claude": tmp_path / "claude-projects",
        "config": tmp_path / "config",
        "private": tmp_path / "private",
        "project": tmp_path / "project",
    }
    roots["project"].mkdir()
    monkeypatch.setenv("STUDY_LOG_CODEX_SESSIONS_DIR", str(roots["codex"]))
    monkeypatch.setenv("STUDY_LOG_CLAUDE_PROJECTS_DIR", str(roots["claude"]))
    monkeypatch.setenv("STUDY_LOG_CONFIG_DIR", str(roots["config"]))
    monkeypatch.delenv("STUDY_LOG_ARCHIVE_ROOT", raising=False)
    return roots


def _run(capsys: pytest.CaptureFixture[str], arguments: list[str]) -> tuple[int, dict[str, object]]:
    code = study_log.main(arguments)
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def _preview(
    capsys: pytest.CaptureFixture[str], project: Path | str, source: Path
) -> dict[str, object]:
    code, result = _run(
        capsys,
        ["preview", "--project", str(project), "--source", str(source)],
    )
    assert code == 0
    assert result["ok"] is True
    return result["data"]  # type: ignore[return-value]


def _archive_arguments(
    *,
    project: Path | str,
    source: Path,
    preview: dict[str, object],
    root: Path | None,
    status: str = "partial",
) -> list[str]:
    messages = preview["messages"]
    assert isinstance(messages, list)
    arguments = [
        "archive",
        "--project",
        str(project),
        "--source",
        str(source),
        "--source-sha256",
        str(preview["source_sha256"]),
        "--start-id",
        str(messages[0]["message_id"]),
        "--end-id",
        str(messages[-1]["message_id"]),
        "--title",
        "调度器学习对话",
        "--status",
        status,
        "--privacy-confirmed",
    ]
    if root is not None:
        arguments.extend(["--archive-root", str(root)])
    return arguments


def test_discovers_both_providers_and_filters_root_sessions(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    codex = isolated_roots["codex"] / "2026" / "08" / "10" / "rollout-main.jsonl"
    _jsonl(codex, _codex_rows(project))
    _jsonl(
        codex.with_name("rollout-subagent.jsonl"),
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "subagent",
                    "cwd": str(project),
                    "parent_thread_id": "parent",
                },
            }
        ],
    )
    claude_dir = isolated_roots["claude"] / study_log.claude_project_slugs(project)[0]
    _jsonl(claude_dir / "claude-session-001.jsonl", _claude_rows(project))
    _jsonl(
        claude_dir / "agent-sidechain.jsonl",
        [
            {
                **_claude_rows(project, session_id="sidechain")[0],
                "isSidechain": True,
            }
        ],
    )

    code, result = _run(
        capsys, ["list", "--project", str(project), "--provider", "auto"]
    )

    assert code == 0
    sessions = result["data"]["sessions"]
    assert {(item["provider"], item["session_id"]) for item in sessions} == {
        ("codex", "codex-session-001"),
        ("claude", "claude-session-001"),
    }


def test_posix_claude_mapping_and_exact_project_filter(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    slugs = study_log.claude_project_slugs(project)
    expected_slug = "-" + project.resolve().as_posix().strip("/").replace("/", "-").replace(
        ".", "-"
    )
    assert slugs == (expected_slug,)

    source_dir = isolated_roots["claude"] / expected_slug
    _jsonl(
        source_dir / "matching-session.jsonl",
        _claude_rows(project, session_id="matching-session"),
    )
    _jsonl(
        source_dir / "other-project-session.jsonl",
        _claude_rows(project.with_name("other-project"), session_id="other-project-session"),
    )

    code, result = _run(
        capsys, ["list", "--project", str(project), "--provider", "claude"]
    )

    assert code == 0
    assert [item["session_id"] for item in result["data"]["sessions"]] == [
        "matching-session"
    ]


def test_preview_message_ids_remain_stable_when_session_grows(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "2026" / "08" / "10" / "rollout.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    first = _preview(capsys, project, source)
    first_ids = [item["message_id"] for item in first["messages"]]

    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "继续下一题"))
    _jsonl(source, rows)
    second = _preview(capsys, project, source)

    assert [item["message_id"] for item in second["messages"]][:-1] == first_ids
    assert first["source_sha256"] != second["source_sha256"]


def test_stable_message_id_includes_assistant_phase() -> None:
    common = {
        "provider": "codex",
        "session_id": "phase-session",
        "source_line": 9,
        "role": "assistant",
        "timestamp": "2026-08-10T10:00:00Z",
        "text": "相同可见文本",
    }

    commentary = study_log._build_message(**common, phase="commentary")
    final = study_log._build_message(**common, phase="final_answer")

    assert commentary.message_id != final.message_id


def test_codex_normalization_preserves_request_and_excludes_client_injections(
    isolated_roots: dict[str, Path]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "normalized.jsonl"
    rows = [
        {
            "timestamp": "2026-08-10T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": "normalized", "cwd": str(project)},
        },
        _codex_message("2026-08-10T10:00:01Z", "developer", "hidden instruction"),
        _codex_message(
            "2026-08-10T10:00:02Z",
            "user",
            "<environment_context><cwd>hidden</cwd></environment_context>",
        ),
        _codex_message(
            "2026-08-10T10:00:03Z",
            "user",
            "<skill><name>example</name>injected instructions</skill>",
        ),
        _codex_message(
            "2026-08-10T10:00:04Z",
            "user",
            "<recommended_plugins>hidden</recommended_plugins>\n"
            "# AGENTS.md instructions for F:/work\n"
            "<INSTRUCTIONS>hidden</INSTRUCTIONS>",
        ),
        _codex_message(
            "2026-08-10T10:00:05Z",
            "user",
            "# Context from my IDE setup:\n\n## Active file: demo.py\n\n"
            "## My request for Codex:\n解释分页注意力",
        ),
        _codex_message(
            "2026-08-10T10:00:05.100Z",
            "user",
            "# Context from my IDE setup:\n\n## My request for Codex:\n解释分页注意力",
        ),
        _codex_message(
            "2026-08-10T10:00:06Z", "assistant", "先看页表。", phase="commentary"
        ),
        {
            "timestamp": "2026-08-10T10:00:07Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "read_file"},
        },
        _codex_message(
            "2026-08-10T10:00:08Z", "assistant", "页表映射逻辑块。", phase="final_answer"
        ),
    ]
    _jsonl(source, rows)

    data = study_log._load_session(
        source,
        provider="codex",
        project=str(project),
        tail_lenient=False,
    )

    assert [(message.role, message.phase, message.text) for message in data.messages] == [
        ("user", None, "解释分页注意力"),
        ("assistant", "commentary", "先看页表。"),
        ("assistant", "final_answer", "页表映射逻辑块。"),
    ]
    assert all("hidden" not in message.text for message in data.messages)


def test_semantic_time_and_final_only_selection() -> None:
    messages = [
        study_log._build_message(
            provider="codex",
            session_id="selection",
            source_line=index,
            role=role,
            timestamp=timestamp,
            phase=phase,
            text=text,
        )
        for index, (timestamp, role, phase, text) in enumerate(
            [
                ("2026-08-10T10:00:00Z", "user", None, "第一课开始"),
                ("2026-08-10T10:00:01Z", "assistant", "commentary", "过程"),
                ("2026-08-10T10:00:02Z", "assistant", "final_answer", "结论"),
                ("2026-08-10T10:00:03Z", "user", None, "第二课开始"),
            ],
            start=1,
        )
    ]

    selection = study_log.select_messages(
        messages,
        start_user="第一课",
        end_before_user="第二课",
        start_time="2026-08-10T10:00:00Z",
        end_time="2026-08-10T10:00:03Z",
        final_only=True,
    )

    assert [(message.role, message.text) for message in selection.messages] == [
        ("user", "第一课开始"),
        ("assistant", "结论"),
    ]


def test_preview_masks_credentials_but_reports_risk(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "rollout-secret.jsonl"
    rows = _codex_rows(project)
    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "api_key=abcdefghijklmnop1234"))
    _jsonl(source, rows)

    preview = _preview(capsys, project, source)

    assert "credential" in preview["privacy"]["categories"]
    rendered = json.dumps(preview, ensure_ascii=False)
    assert "abcdefghijklmnop1234" not in rendered
    assert "[CREDENTIAL]" in rendered


def test_preview_masks_prefixed_env_github_bearer_and_jwt_credentials(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "expanded-credentials.jsonl"
    secrets = [
        "my-password-value-123456",
        "aws-secret-value-1234567890",
        "github_pat_" + "A" * 30,
        "bearer-value-" + "b" * 24,
        "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
    ]
    credential_text = "\n".join(
        [
            f"MY_PASSWORD={secrets[0]}",
            f"AWS_SECRET_ACCESS_KEY={secrets[1]}",
            secrets[2],
            f"Authorization: Bearer {secrets[3]}",
            secrets[4],
        ]
    )
    rows = _codex_rows(project)
    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", credential_text))
    _jsonl(source, rows)

    code, result = _run(
        capsys,
        [
            "preview",
            "--project",
            str(project),
            "--source",
            str(source),
            "--preview-chars",
            "1000",
        ],
    )

    assert code == 0
    assert result["data"]["privacy"]["categories"] == ["credential"]
    assert result["data"]["privacy"]["counts"]["credential"] >= len(secrets)
    rendered = json.dumps(result, ensure_ascii=False)
    assert all(secret not in rendered for secret in secrets)
    assert rendered.count("[CREDENTIAL]") >= len(secrets)


def test_crlf_code_fence_is_reported_as_possible_proprietary_content(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "crlf-code-fence.jsonl"
    rows = _codex_rows(project)
    rows.append(
        _codex_message(
            "2026-08-10T10:00:06Z",
            "user",
            "```python\r\ncall_private_function()\r\n```",
        )
    )
    _jsonl(source, rows)

    preview = _preview(capsys, project, source)

    assert "proprietary" in preview["privacy"]["categories"]
    assert preview["privacy"]["counts"]["proprietary"] == 1


def test_structured_extract_tolerates_only_one_broken_tail_and_checks_source_hash(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "rollout-active.jsonl"
    _jsonl(source, _codex_rows(project), broken_tail=True)
    preview = _preview(capsys, project, source)
    output = tmp_path / "scratch" / "structured.md"
    arguments = [
        "extract",
        "--project",
        str(project),
        "--source",
        str(source),
        "--source-sha256",
        str(preview["source_sha256"]),
        "--output",
        str(output),
    ]

    code, result = _run(capsys, arguments)

    assert code == 0
    assert output.is_file()
    assert result["data"]["cleanup_required"] is True
    assert any(item["code"] == "truncated_tail_ignored" for item in result["warnings"])

    stale_output = tmp_path / "scratch" / "stale.md"
    stale_args = arguments[:-1] + [str(stale_output)]
    stale_args[stale_args.index("--source-sha256") + 1] = "0" * 64
    code, result = _run(capsys, stale_args)
    assert code == study_log.EXIT_INTEGRITY
    assert result["error"]["code"] == "integrity"
    assert not stale_output.exists()


def test_structured_tolerates_truncated_multibyte_tail_but_raw_is_strict(
    isolated_roots: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "multibyte-tail.jsonl"
    _jsonl(source, _codex_rows(project))
    with source.open("ab") as handle:
        handle.write(b'{"partial":"' + "学".encode("utf-8")[:2])

    code, preview_result = _run(
        capsys, ["preview", "--project", str(project), "--source", str(source)]
    )
    assert code == 0
    assert preview_result["warnings"] == [
        {
            "code": "truncated_tail_ignored",
            "line": len(_codex_rows(project)) + 1,
            "reason": "utf8",
            "message": "one malformed final JSONL record was ignored",
        }
    ]
    preview = preview_result["data"]
    scratch = tmp_path / "multibyte-scratch.md"
    code, extract_result = _run(
        capsys,
        [
            "extract",
            "--project",
            str(project),
            "--source",
            str(source),
            "--source-sha256",
            str(preview["source_sha256"]),
            "--output",
            str(scratch),
        ],
    )
    assert code == 0
    assert extract_result["warnings"][0]["reason"] == "utf8"
    assert scratch.is_file()

    archive_args = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    code, archive_result = _run(capsys, archive_args)
    assert code == study_log.EXIT_MALFORMED
    assert archive_result["error"]["code"] == "malformed"
    scratch.unlink()


def test_malformed_middle_record_fails_even_for_structured_preview(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "middle-broken.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    rows = _codex_rows(project)
    source.write_text(
        json.dumps(rows[0]) + "\n{" + "\n" + json.dumps(rows[1], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    code, result = _run(
        capsys, ["preview", "--project", str(project), "--source", str(source)]
    )

    assert code == study_log.EXIT_MALFORMED
    assert result["error"]["code"] == "malformed"


def test_valid_json_scalar_tail_is_not_treated_as_truncation(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "scalar-tail.jsonl"
    _jsonl(source, _codex_rows(project))
    with source.open("a", encoding="utf-8") as handle:
        handle.write("42\n")

    code, result = _run(
        capsys, ["preview", "--project", str(project), "--source", str(source)]
    )

    assert code == study_log.EXIT_MALFORMED
    assert result["error"]["code"] == "malformed"
    assert result["error"]["details"]["json_type"] == "int"


def test_preview_rejects_non_string_record_type_with_stable_json_error(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "array-record-type.jsonl"
    _jsonl(source, [{"type": []}, *_codex_rows(project)])

    code, result = _run(
        capsys, ["preview", "--project", str(project), "--source", str(source)]
    )

    assert code == study_log.EXIT_MALFORMED
    assert result["ok"] is False
    assert result["command"] == "preview"
    assert result["error"]["code"] == "malformed"
    assert result["error"]["details"]["field"] == "record.type"
    assert result["error"]["details"]["json_type"] == "list"


def test_raw_rejects_valid_json_scalar_in_the_middle(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "raw-scalar.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)
    raw_lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    raw_lines.insert(3, '"legal scalar"')
    source.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    arguments[arguments.index("--source-sha256") + 1] = study_log._sha256_file(source)

    code, result = _run(capsys, arguments)

    assert code == study_log.EXIT_MALFORMED
    assert result["error"]["code"] == "malformed"
    assert not isolated_roots["private"].exists()


def test_raw_rejects_object_content_type_with_stable_json_error(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "object-content-type.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)
    payload = rows[2]["payload"]
    assert isinstance(payload, dict)
    content = payload["content"]
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, dict)
    block["type"] = {}
    _jsonl(source, rows)
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    arguments[arguments.index("--source-sha256") + 1] = study_log._sha256_file(source)

    code, result = _run(capsys, arguments)

    assert code == study_log.EXIT_MALFORMED
    assert result["ok"] is False
    assert result["command"] == "archive"
    assert result["error"]["code"] == "malformed"
    assert result["error"]["details"]["json_type"] == "dict"
    assert not isolated_roots["private"].exists()


def test_duplicate_semantic_boundary_is_ambiguous(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "repeat.jsonl"
    rows = _codex_rows(project)
    rows.extend(
        [
            _codex_message("2026-08-10T10:00:06Z", "user", "重复问题"),
            _codex_message("2026-08-10T10:00:07Z", "assistant", "第一次回答"),
            _codex_message("2026-08-10T10:00:08Z", "user", "重复问题"),
        ]
    )
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)

    code, result = _run(
        capsys,
        [
            "extract",
            "--project",
            str(project),
            "--source",
            str(source),
            "--source-sha256",
            str(preview["source_sha256"]),
            "--start-user",
            "重复问题",
        ],
    )

    assert code == study_log.EXIT_AMBIGUOUS
    assert result["error"]["code"] == "ambiguous"


def test_raw_is_strict_when_active_session_has_a_broken_tail(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "strict.jsonl"
    _jsonl(source, _codex_rows(project), broken_tail=True)
    preview = _preview(capsys, project, source)

    code, result = _run(
        capsys,
        _archive_arguments(
            project=project,
            source=source,
            preview=preview,
            root=isolated_roots["private"],
        ),
    )

    assert code == study_log.EXIT_MALFORMED
    assert result["error"]["code"] == "malformed"
    assert not isolated_roots["private"].exists()


def test_claude_raw_archive_uses_same_strict_safe_pipeline(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = (
        isolated_roots["claude"]
        / study_log.claude_project_slugs(project)[0]
        / "claude-raw.jsonl"
    )
    _jsonl(source, _claude_rows(project))
    preview = _preview(capsys, project, source)

    code, result = _run(
        capsys,
        _archive_arguments(
            project=project,
            source=source,
            preview=preview,
            root=isolated_roots["private"],
            status="final",
        ),
    )

    assert code == 0
    assert result["data"]["provider"] == "claude"
    content = Path(result["data"]["target"]).read_text(encoding="utf-8")
    assert "先按权重维度切分。" in content
    assert "hidden" not in content
    assert "Read(notes.md)" not in content


def test_pure_claude_compact_summary_is_not_an_eligible_root_session(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = (
        isolated_roots["claude"]
        / study_log.claude_project_slugs(project)[0]
        / "compact-only.jsonl"
    )
    _jsonl(
        source,
        [
            {
                "type": "assistant",
                "sessionId": "compact-only",
                "cwd": str(project),
                "timestamp": "2026-08-10T11:00:00Z",
                "isCompactSummary": True,
                "message": {"role": "assistant", "content": "compressed history"},
            }
        ],
    )

    code, result = _run(
        capsys, ["preview", "--project", str(project), "--source", str(source)]
    )
    assert code == study_log.EXIT_NOT_FOUND
    assert result["error"]["code"] == "not_found"

    code, result = _run(
        capsys, ["list", "--project", str(project), "--provider", "claude"]
    )
    assert code == 0
    assert result["data"]["sessions"] == []
    assert result["warnings"][0]["reason"] == "not_found"


def test_archive_requires_private_root_and_privacy_confirmation(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "raw.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    arguments = _archive_arguments(
        project=project, source=source, preview=preview, root=None
    )

    code, result = _run(capsys, arguments)
    assert code == study_log.EXIT_SAFETY
    assert "archive root" in result["error"]["message"]

    arguments.extend(["--archive-root", str(isolated_roots["private"])])
    arguments.remove("--privacy-confirmed")
    code, result = _run(capsys, arguments)
    assert code == study_log.EXIT_SAFETY
    assert "privacy" in result["error"]["message"]


def test_credentials_block_then_reproducibly_redact(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "credential.jsonl"
    rows = _codex_rows(project)
    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "token=abcdefghijklmnop1234"))
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )

    code, result = _run(capsys, arguments)
    assert code == study_log.EXIT_SAFETY
    assert result["error"]["code"] == "safety"

    arguments.extend(["--credential-action", "redact"])
    code, result = _run(capsys, arguments)

    assert code == 0
    target = Path(result["data"]["target"])
    content = target.read_text(encoding="utf-8")
    assert "abcdefghijklmnop1234" not in content
    assert "[REDACTED:credential:assigned-secret:001]" in content
    metadata = study_log._parse_archive_metadata(content)
    assert metadata["redaction"]["version"] == study_log.REDACTION_VERSION
    assert metadata["redaction"]["applications"] == [
        {"category": "credential", "rule": "assigned-secret", "count": 1}
    ]


def test_proprietary_content_requires_separate_confirmation(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "proprietary.jsonl"
    rows = _codex_rows(project)
    rows.append(
        _codex_message(
            "2026-08-10T10:00:06Z", "user", "内部 API 示例：\n```python\ncall_internal()\n```"
        )
    )
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )

    code, result = _run(capsys, arguments)
    assert code == study_log.EXIT_SAFETY
    assert "proprietary" in result["error"]["message"]

    arguments.append("--proprietary-confirmed")
    code, _result = _run(capsys, arguments)
    assert code == 0


def test_partial_refresh_and_finalization_keep_archive_id_and_target(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "growing.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    first_preview = _preview(capsys, project, source)
    first_messages = first_preview["messages"]
    first_args = _archive_arguments(
        project=project,
        source=source,
        preview={**first_preview, "messages": first_messages[:3]},
        root=isolated_roots["private"],
    )
    code, created = _run(capsys, first_args)
    assert code == 0
    archive_id = created["data"]["archive_id"]
    target = Path(created["data"]["target"])
    first_target_sha = created["data"]["target_sha256"]

    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "新增的收尾问题"))
    _jsonl(source, rows)
    next_preview = _preview(capsys, project, source)
    refresh_args = _archive_arguments(
        project=project,
        source=source,
        preview=next_preview,
        root=isolated_roots["private"],
    )
    refresh_args.extend(
        ["--archive-id", archive_id, "--target-sha256", first_target_sha]
    )
    code, refreshed = _run(capsys, refresh_args)

    assert code == 0
    assert refreshed["data"]["archive_id"] == archive_id
    assert Path(refreshed["data"]["target"]) == target
    assert refreshed["data"]["operation"] == "update"
    refreshed_sha = refreshed["data"]["target_sha256"]

    same_end_args = refresh_args.copy()
    same_end_args[same_end_args.index(first_target_sha)] = refreshed_sha
    code, result = _run(capsys, same_end_args)
    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["code"] == "conflict"
    assert result["error"]["message"] == "partial refresh must strictly advance the end message"
    assert study_log._sha256_file(target) == refreshed_sha

    final_args = same_end_args.copy()
    final_args[final_args.index("partial")] = "final"
    code, finalized = _run(capsys, final_args)
    assert code == 0
    assert finalized["data"]["status"] == "final"
    assert study_log._parse_archive_metadata(target.read_text(encoding="utf-8"))["status"] == "final"

    final_sha = finalized["data"]["target_sha256"]
    retry = final_args.copy()
    retry[retry.index(refreshed_sha)] = final_sha
    code, result = _run(capsys, retry)
    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["code"] == "conflict"


def test_partial_update_rejects_rewritten_visible_history(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "rewritten-history.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    first_preview = _preview(capsys, project, source)
    first_messages = first_preview["messages"]
    create_args = _archive_arguments(
        project=project,
        source=source,
        preview={**first_preview, "messages": first_messages[:3]},
        root=isolated_roots["private"],
    )
    code, created = _run(capsys, create_args)
    assert code == 0
    target = Path(created["data"]["target"])
    original_target = target.read_bytes()

    rows[2] = _codex_message(
        "2026-08-10T10:00:02Z",
        "assistant",
        "被改写的历史讲解。",
        phase="commentary",
    )
    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "继续学习"))
    _jsonl(source, rows)
    next_preview = _preview(capsys, project, source)
    update_args = _archive_arguments(
        project=project,
        source=source,
        preview=next_preview,
        root=isolated_roots["private"],
    )
    update_args.extend(
        [
            "--archive-id",
            created["data"]["archive_id"],
            "--target-sha256",
            created["data"]["target_sha256"],
        ]
    )

    code, result = _run(capsys, update_args)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["code"] == "conflict"
    assert target.read_bytes() == original_target


def test_redaction_policy_version_is_part_of_partial_identity(
    isolated_roots: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "redaction-version.jsonl"
    rows = _codex_rows(project)
    _jsonl(source, rows)
    first_preview = _preview(capsys, project, source)
    create_args = _archive_arguments(
        project=project,
        source=source,
        preview={**first_preview, "messages": first_preview["messages"][:3]},
        root=isolated_roots["private"],
    )
    code, created = _run(capsys, create_args)
    assert code == 0
    target = Path(created["data"]["target"])
    original_target = target.read_bytes()

    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "继续学习"))
    _jsonl(source, rows)
    next_preview = _preview(capsys, project, source)
    monkeypatch.setattr(study_log, "REDACTION_VERSION", "study-log-redaction-v2")
    update_args = _archive_arguments(
        project=project,
        source=source,
        preview=next_preview,
        root=isolated_roots["private"],
    )
    update_args.extend(
        [
            "--archive-id",
            created["data"]["archive_id"],
            "--target-sha256",
            created["data"]["target_sha256"],
        ]
    )

    code, result = _run(capsys, update_args)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["message"] == "redaction identity changed; create a new archive_id"
    assert target.read_bytes() == original_target


def test_redaction_change_cannot_create_a_second_partial_for_same_boundary(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "one-partial.jsonl"
    rows = _codex_rows(project)
    rows.append(_codex_message("2026-08-10T10:00:06Z", "user", "联系 learner@example.com"))
    _jsonl(source, rows)
    preview = _preview(capsys, project, source)
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    code, _created = _run(capsys, arguments)
    assert code == 0

    changed = [*arguments, "--redact-personal"]
    code, result = _run(capsys, changed)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["code"] == "conflict"


def test_equivalent_final_cannot_be_created_twice_but_different_end_can(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "duplicate-final.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    first_messages = preview["messages"][:3]
    first_args = _archive_arguments(
        project=project,
        source=source,
        preview={**preview, "messages": first_messages},
        root=isolated_roots["private"],
        status="final",
    )
    code, _created = _run(capsys, first_args)
    assert code == 0
    before = list(isolated_roots["private"].rglob("*.md"))

    code, result = _run(capsys, first_args)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["message"] == "an equivalent finalized archive already exists"
    assert list(isolated_roots["private"].rglob("*.md")) == before

    later_end_args = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
        status="final",
    )
    code, _later = _run(capsys, later_end_args)
    assert code == 0
    assert len(list(isolated_roots["private"].rglob("*.md"))) == 2

    different_redaction_args = [*first_args, "--redact-personal"]
    code, _different_redaction = _run(capsys, different_redaction_args)
    assert code == 0
    assert len(list(isolated_roots["private"].rglob("*.md"))) == 3


def test_partial_cannot_finalize_into_an_existing_equivalent_final(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "duplicate-on-finalize.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    final_args = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
        status="final",
    )
    code, _final = _run(capsys, final_args)
    assert code == 0

    partial_args = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    code, partial = _run(capsys, partial_args)
    assert code == 0
    partial_target = Path(partial["data"]["target"])
    original_partial = partial_target.read_bytes()
    finalize_args = partial_args.copy()
    finalize_args[finalize_args.index("partial")] = "final"
    finalize_args.extend(
        [
            "--archive-id",
            partial["data"]["archive_id"],
            "--target-sha256",
            partial["data"]["target_sha256"],
        ]
    )

    code, result = _run(capsys, finalize_args)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["message"] == "an equivalent finalized archive already exists"
    assert partial_target.read_bytes() == original_partial


def test_target_sha_conflict_preserves_external_edit(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "conflict.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    args = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )
    code, created = _run(capsys, args)
    assert code == 0
    target = Path(created["data"]["target"])
    reviewed_sha = created["data"]["target_sha256"]
    target.write_text("human edit\n", encoding="utf-8")

    args.extend(
        [
            "--archive-id",
            created["data"]["archive_id"],
            "--target-sha256",
            reviewed_sha,
        ]
    )
    code, result = _run(capsys, args)

    assert code == study_log.EXIT_CONFLICT
    assert result["error"]["code"] == "conflict"
    assert target.read_text(encoding="utf-8") == "human edit\n"


def test_non_utf8_archive_during_root_scan_returns_stable_json_error(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "non-utf-root.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    root = isolated_roots["private"]
    root.mkdir()
    bad_archive = root / "not-utf8.md"
    bad_archive.write_bytes(b"\xff\xfe\xfa")
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=root,
    )

    code, result = _run(capsys, arguments)

    assert code == study_log.EXIT_MALFORMED
    assert result["ok"] is False
    assert result["command"] == "archive"
    assert result["error"]["code"] == "malformed"
    assert result["error"]["message"] == "text encoding error"
    assert list(root.rglob("*.md")) == [bad_archive]


def test_filesystem_failure_returns_stable_json_error(
    isolated_roots: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "filesystem-error.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    arguments = _archive_arguments(
        project=project,
        source=source,
        preview=preview,
        root=isolated_roots["private"],
    )

    def fail_archive_root(_explicit: str | None) -> tuple[Path, str]:
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(study_log, "_archive_root", fail_archive_root)
    code, result = _run(capsys, arguments)

    assert code == study_log.EXIT_INTEGRITY
    assert result["ok"] is False
    assert result["command"] == "archive"
    assert result["error"]["code"] == "integrity"
    assert "synthetic filesystem failure" in result["error"]["details"]["reason"]


def test_containment_rejects_explicit_escape(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "escape.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    root = isolated_roots["private"].resolve()
    output = root.parent / "escaped.md"
    args = _archive_arguments(project=project, source=source, preview=preview, root=root)
    args.extend(["--output", str(output)])

    code, result = _run(capsys, args)

    assert code == study_log.EXIT_SAFETY
    assert result["error"]["code"] == "safety"
    assert not output.exists()


def test_containment_rejects_symbolic_link_escape_when_supported(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "link-escape.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    root = isolated_roots["private"]
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating a directory symlink is not permitted")
    output = link / "dialogue.md"
    args = _archive_arguments(project=project, source=source, preview=preview, root=root)
    args.extend(["--output", str(output)])

    code, result = _run(capsys, args)

    assert code == study_log.EXIT_SAFETY
    assert result["error"]["code"] == "safety"
    assert not (outside / "dialogue.md").exists()


def test_existing_windows_junction_target_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    target = root / "archive.md"
    root.mkdir()
    target.write_text("existing", encoding="utf-8")
    if not hasattr(target, "is_junction"):
        pytest.skip("Path.is_junction is unavailable")
    monkeypatch.setattr(
        type(target), "is_junction", lambda self: self.resolve() == target.resolve()
    )

    with pytest.raises(study_log.StudyLogError) as caught:
        study_log._ensure_contained(target, root)

    assert caught.value.spec.kind == "safety"
    assert "junction" in caught.value.spec.message


def test_git_guard_requires_ignored_untracked_target(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    if not study_log.shutil.which("git"):
        pytest.skip("git is unavailable")
    project = isolated_roots["project"]
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    source = isolated_roots["codex"] / "repo-output.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    output = project / ".private" / "dialogue.md"
    args = _archive_arguments(project=project, source=source, preview=preview, root=None)
    args.extend(["--output", str(output)])

    code, _result = _run(capsys, args)
    assert code == study_log.EXIT_SAFETY
    assert not output.exists()

    args.append("--allow-repo-output")
    code, _result = _run(capsys, args)
    assert code == study_log.EXIT_SAFETY
    assert not output.exists()

    (project / ".gitignore").write_text(".private/\n", encoding="utf-8")
    code, result = _run(capsys, args)
    assert code == 0
    assert Path(result["data"]["target"]) == output.resolve()


def test_structured_scratch_is_refused_in_another_git_worktree(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    if not study_log.shutil.which("git"):
        pytest.skip("git is unavailable")
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "scratch-git.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    other_repo = tmp_path / "other-repo"
    subprocess.run(["git", "init", "--quiet", str(other_repo)], check=True)
    output = other_repo / "scratch.md"

    code, result = _run(
        capsys,
        [
            "extract",
            "--project",
            str(project),
            "--source",
            str(source),
            "--source-sha256",
            str(preview["source_sha256"]),
            "--output",
            str(output),
        ],
    )

    assert code == study_log.EXIT_SAFETY
    assert result["error"]["code"] == "safety"
    assert not output.exists()


def test_user_config_has_no_default_and_accepts_only_absolute_root(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    code, result = _run(capsys, ["config", "archive-root", "get"])
    assert code == 0
    assert result["data"]["configured"] is False
    assert result["data"]["archive_root"] is None

    code, result = _run(capsys, ["config", "archive-root", "set", "relative/path"])
    assert code == study_log.EXIT_USAGE
    assert result["error"]["code"] == "usage"

    root = isolated_roots["private"].resolve()
    code, result = _run(
        capsys, ["config", "archive-root", "set", str(root)]
    )
    assert code == 0
    assert result["data"]["archive_root"] == str(root)

    code, result = _run(capsys, ["config", "archive-root", "get"])
    assert code == 0
    assert result["data"]["archive_root"] == str(root)


def test_archive_root_resolution_prefers_environment_then_explicit(
    isolated_roots: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = isolated_roots["project"]
    source = isolated_roots["codex"] / "root-precedence.jsonl"
    _jsonl(source, _codex_rows(project))
    preview = _preview(capsys, project, source)
    configured = isolated_roots["private"] / "configured"
    environment = isolated_roots["private"] / "environment"
    explicit = isolated_roots["private"] / "explicit"
    code, _result = _run(
        capsys, ["config", "archive-root", "set", str(configured.resolve())]
    )
    assert code == 0
    monkeypatch.setenv("STUDY_LOG_ARCHIVE_ROOT", str(environment.resolve()))

    args = _archive_arguments(project=project, source=source, preview=preview, root=None)
    code, result = _run(capsys, args)
    assert code == 0
    assert result["data"]["archive_root"] == str(environment.resolve())
    assert result["data"]["archive_root_source"] == "environment"

    second_source = isolated_roots["codex"] / "root-explicit.jsonl"
    _jsonl(second_source, _codex_rows(project, session_id="codex-session-002"))
    second_preview = _preview(capsys, project, second_source)
    args = _archive_arguments(
        project=project, source=second_source, preview=second_preview, root=explicit.resolve()
    )
    code, result = _run(capsys, args)
    assert code == 0
    assert result["data"]["archive_root"] == str(explicit.resolve())
    assert result["data"]["archive_root_source"] == "explicit"

def test_json_error_contract_and_exit_codes_are_stable(
    capsys: pytest.CaptureFixture[str], isolated_roots: dict[str, Path]
) -> None:
    code, result = _run(capsys, ["preview", "--project", str(isolated_roots["project"])])

    assert code == study_log.EXIT_USAGE
    assert result == {
        "schema_version": 1,
        "ok": False,
        "command": None,
        "error": {
            "code": "usage",
            "message": "one of the arguments --session --source is required",
            "details": {},
        },
    }


def test_atomic_create_cleans_temporary_file_after_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "archive.md"

    def fail_link(_source: Path, _target: Path) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(study_log.os, "link", fail_link)

    with pytest.raises(OSError, match="synthetic publish failure"):
        study_log._atomic_write(target, "candidate\n", expected_sha256=None)

    assert not target.exists()
    assert list(tmp_path.glob(".archive.md.*.tmp")) == []


def test_atomic_update_cleans_temporary_file_after_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "archive.md"
    target.write_text("old\n", encoding="utf-8")
    expected = study_log._sha256_file(target)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(study_log.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        study_log._atomic_write(target, "candidate\n", expected_sha256=expected)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".archive.md.*.tmp")) == []
