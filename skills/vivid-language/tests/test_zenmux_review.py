from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "zenmux_review.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import zenmux_review  # noqa: E402


DEFAULT_CHAIN = [
    "google/gemini-4-neon",
    "google/gemini-4-hydrogen",
    "google/gemini-4-carbon",
    "google/gemini-4-argon",
]


def _chat(content: str, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _cli(*args: str, stdin: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    clean = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ZENMUX_", "VIVID_"))
    }
    if env:
        clean.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        env=clean,
    )


def _review(content, **overrides):
    calls: list[str] = []
    data = content if isinstance(content, dict) else {"default": content}

    def transport(url, payload, api_key, timeout):
        calls.append(payload["model"])
        value = data.get(payload["model"], data.get("default"))
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            return value
        return _chat(value)

    kwargs = dict(
        kind="page",
        api_key="test-key",
        transport=transport,
        sleep=lambda seconds: None,
    )
    kwargs.update(overrides)
    result = zenmux_review.review_text("这是一段需要审查的正文。", **kwargs)
    return result, calls


def test_default_chain_is_the_four_gemini_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zenmux_review.ENV_MODELS, raising=False)
    assert zenmux_review._resolve_models(None) == DEFAULT_CHAIN


def test_env_chain_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zenmux_review.ENV_MODELS, "a/one, b/two a/one")
    assert zenmux_review._resolve_models(None) == ["a/one", "b/two"]


def test_cli_without_key_falls_back_to_subagent() -> None:
    completed = _cli("--kind", "page", "--text", "一段正文。")
    assert completed.returncode == zenmux_review.EXIT_NOT_CONFIGURED
    payload = json.loads(completed.stdout)
    assert payload["status"] == "not-configured"
    assert payload["models"] == DEFAULT_CHAIN
    assert "sub-agent" in payload["next"]


def test_cli_disabled_env_forces_fallback() -> None:
    completed = _cli(
        "--kind", "page", "--text", "一段正文。",
        env={"ZENMUX_API_KEY": "test-key", zenmux_review.ENV_DISABLE: "off"},
    )
    assert completed.returncode == zenmux_review.EXIT_NOT_CONFIGURED
    assert json.loads(completed.stdout)["status"] == "not-configured"


def test_review_pass_uses_the_first_model() -> None:
    result, calls = _review(
        '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}'
    )
    assert result["status"] == "ok"
    assert result["model"] == DEFAULT_CHAIN[0]
    assert result["verdict"] == "PASS"
    assert calls == [DEFAULT_CHAIN[0]]


def test_review_revise_keeps_blocking_items() -> None:
    result, _ = _review(
        '{"verdict":"REVISE","blocking":[{"原文":"该机制具有较高的复杂性",'
        '"问题":"名词化","建议改法":"改一处要动三个文件"}],"non_blocking":[],'
        '"fact_risk":"无"}'
    )
    assert result["verdict"] == "REVISE"
    assert result["blocking"] == [
        {"原文": "该机制具有较高的复杂性", "问题": "名词化", "建议改法": "改一处要动三个文件"}
    ]


def test_revise_without_blocking_is_not_accepted() -> None:
    result, calls = _review(
        {
            DEFAULT_CHAIN[0]: '{"verdict":"REVISE","blocking":[],"non_blocking":[],"fact_risk":"无"}',
            DEFAULT_CHAIN[1]: '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        }
    )
    assert result["status"] == "ok"
    assert result["model"] == DEFAULT_CHAIN[1]
    assert calls.count(DEFAULT_CHAIN[0]) == 2


def test_review_falls_back_when_the_first_model_times_out() -> None:
    timeout = zenmux_review.TransportError("network: timed out", None, True)
    result, calls = _review(
        {
            "default": timeout,
            DEFAULT_CHAIN[1]: '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        }
    )
    assert result["status"] == "ok"
    assert result["model"] == DEFAULT_CHAIN[1]
    assert calls[:2] == [DEFAULT_CHAIN[0], DEFAULT_CHAIN[0]]
    assert [attempt["outcome"] for attempt in result["attempts"]] == ["transport", "transport", "ok"]


def test_all_models_failing_is_unavailable() -> None:
    result, calls = _review(zenmux_review.TransportError("network: timed out", None, True))
    assert result["status"] == "unavailable"
    assert len(calls) == 8  # four models, two attempts each
    assert "sub-agent" in result["next"]


def test_invalid_key_stops_the_chain() -> None:
    denied = zenmux_review.TransportError("HTTP 401", 401, False)
    result, calls = _review(denied)
    assert result["status"] == "unavailable"
    assert calls == [DEFAULT_CHAIN[0]]
    assert "rejected" in result["reason"]


def test_forbidden_model_falls_through_to_the_next_one() -> None:
    denied = zenmux_review.TransportError("HTTP 403: no permission", 403, False)
    result, calls = _review(
        {
            "default": denied,
            DEFAULT_CHAIN[1]: '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        }
    )
    assert result["status"] == "ok"
    assert result["model"] == DEFAULT_CHAIN[1]
    assert calls == [DEFAULT_CHAIN[0], DEFAULT_CHAIN[1]]


def test_json_in_a_fenced_block_is_parsed() -> None:
    result, _ = _review(
        '```json\n{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}\n```'
    )
    assert result["verdict"] == "PASS"
    assert result["parsed_json"] is True


def test_rewrite_returns_candidate_and_changes() -> None:
    result, _ = _review(
        '{"rewrite":"改好的正文。","changes":[{"原文":"甲","改成":"乙","为什么":"更直接"}],'
        '"fact_risk":"无"}',
        mode="rewrite",
    )
    assert result["mode"] == "rewrite"
    assert result["rewrite"] == "改好的正文。"
    assert result["changes"] == [{"原文": "甲", "改成": "乙", "为什么": "更直接"}]


def test_rewrite_without_json_keeps_the_plain_text_candidate() -> None:
    result, _ = _review("这就是一段纯文本改写稿。", mode="rewrite")
    assert result["status"] == "ok"
    assert result["rewrite"] == "这就是一段纯文本改写稿。"
    assert result["parsed_json"] is False


def test_truncated_rewrite_is_flagged() -> None:
    response = {
        "choices": [
            {"message": {"content": '{"rewrite":"半截","changes":[],"fact_risk":"无"}'},
             "finish_reason": "length"}
        ]
    }
    result = zenmux_review.review_text(
        "正文",
        kind="page",
        mode="rewrite",
        api_key="test-key",
        transport=lambda *args: response,
        sleep=lambda seconds: None,
    )
    assert result["status"] == "ok"
    assert result["truncated"] is True


def test_unparseable_answer_moves_to_the_next_model() -> None:
    result, calls = _review(
        {
            DEFAULT_CHAIN[0]: "我不知道该怎么审。",
            DEFAULT_CHAIN[1]: '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        }
    )
    assert result["status"] == "ok"
    assert result["model"] == DEFAULT_CHAIN[1]
    assert calls.count(DEFAULT_CHAIN[0]) == 2


def test_short_bare_verdict_is_accepted_without_json() -> None:
    result, _ = _review("PASS")
    assert result["status"] == "ok"
    assert result["verdict"] == "PASS"
    assert result["parsed_json"] is False


def test_prose_mentioning_both_verdicts_is_rejected() -> None:
    result, _ = _review("I cannot say PASS or REVISE until I see the whole section.")
    assert result["status"] == "unavailable"


def test_every_model_parse_failure_is_unavailable() -> None:
    result, _ = _review("这不是 JSON。")
    assert result["status"] == "unavailable"
    assert {attempt["outcome"] for attempt in result["attempts"]} == {"parse-error"}


def test_zero_budget_skips_the_models() -> None:
    result, calls = _review(
        "unused",
        max_total_seconds=0,
    )
    assert result["status"] == "unavailable"
    assert calls == []
    assert result["attempts"][0]["outcome"] == "budget-exhausted"


def test_input_limit_is_a_usage_error() -> None:
    completed = _cli("--max-input-chars", "3", "--text", "一二三四五")
    assert completed.returncode == zenmux_review.EXIT_USAGE
    assert "max-input-chars" in completed.stderr


def test_empty_input_is_a_usage_error() -> None:
    completed = _cli("-", stdin="   \n")
    assert completed.returncode == zenmux_review.EXIT_USAGE
    assert "empty" in completed.stderr


def test_check_reports_every_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zenmux_review.ENV_API_KEY, raising=False)
    checks: list[str] = []

    def transport(url, payload, api_key, timeout):
        checks.append(payload["model"])
        if payload["model"] == DEFAULT_CHAIN[0]:
            raise zenmux_review.TransportError("HTTP 404", 404, False)
        return _chat("OK")

    result = zenmux_review.check_models(api_key="test-key", transport=transport)
    assert result["status"] == "ok"
    assert checks == DEFAULT_CHAIN
    assert [item["ok"] for item in result["checks"]] == [False, True, True, True]


def test_check_without_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zenmux_review.ENV_API_KEY, raising=False)
    result = zenmux_review.check_models()
    assert result["status"] == "not-configured"


def test_default_transport_posts_a_chat_completion_with_the_bearer_token() -> None:
    import http.server
    import threading

    captured: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            length = int(self.headers["Content-Length"])
            captured["path"] = self.path
            captured["authorization"] = self.headers.get("Authorization")
            captured["payload"] = json.loads(self.rfile.read(length))
            body = json.dumps(
                _chat('{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}')
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = zenmux_review.review_text(
            "正文",
            kind="page",
            api_key="test-key",
            base_url=f"http://127.0.0.1:{server.server_address[1]}/api/v1",
            sleep=lambda seconds: None,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["status"] == "ok"
    assert result["verdict"] == "PASS"
    assert captured["path"] == "/api/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == DEFAULT_CHAIN[0]
    assert captured["payload"]["stream"] is False


def test_text_mode_explains_why_the_remote_is_skipped() -> None:
    missing = zenmux_review._render_text(
        {"status": "not-configured", "reason": "ZENMUX_API_KEY is not set"}
    )
    assert "没有配置 ZENMUX_API_KEY" in missing and "子 Agent" in missing
    disabled = zenmux_review._render_text(
        {"status": "not-configured", "reason": "VIVID_LANGUAGE_REMOTE_REVIEW disables the remote reviewer"}
    )
    assert "已关闭远程审查" in disabled
    rejected = zenmux_review._render_text(
        {"status": "unavailable", "reason": "ZenMux rejected ZENMUX_API_KEY (401)"}
    )
    assert "被拒绝（401）" in rejected


def test_dry_run_does_not_need_a_key() -> None:
    completed = _cli("--kind", "cards", "--mode", "rewrite", "--text", "索引是一种数据结构。", "--dry-run")
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["model"] == DEFAULT_CHAIN[0]
    assert payload["messages"][1]["content"].find("记忆卡片") >= 0


def test_prompts_carry_the_register_and_the_json_schema() -> None:
    review = zenmux_review._build_payload(
        DEFAULT_CHAIN[0], "正文", "page", "review", "", 0
    )
    assert "课程网页正文" in review["messages"][1]["content"]
    assert "verdict" in review["messages"][1]["content"]
    rewrite = zenmux_review._build_payload(
        DEFAULT_CHAIN[0], "正文", "cards", "rewrite", "", 0
    )
    assert "记忆卡片" in rewrite["messages"][1]["content"]
    assert "rewrite" in rewrite["messages"][1]["content"]
    assert "防御性免责" in review["messages"][1]["content"]


def test_gemini_host_skips_zenmux_without_calling_transport() -> None:
    calls: list[str] = []

    def transport(url, payload, api_key, timeout):
        calls.append(payload["model"])
        return _chat('{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}')

    result = zenmux_review.review_text(
        "这是一段正文。",
        kind="page",
        api_key="test-key",
        host_model="google/gemini-4-neon",
        transport=transport,
    )
    assert result["status"] == "skipped"
    assert result["host_model"] == "google/gemini-4-neon"
    assert "sub-agent" in result["next"]
    assert calls == []


def test_gemini_host_env_and_cli_return_exit_2() -> None:
    by_arg = _cli(
        "--kind", "page", "--host-model", "Gemini 4 Neon", "--text", "一段正文。",
        env={"ZENMUX_API_KEY": "test-key"},
    )
    assert by_arg.returncode == zenmux_review.EXIT_NOT_CONFIGURED
    assert json.loads(by_arg.stdout)["status"] == "skipped"

    by_env = _cli(
        "--kind", "page", "--text", "一段正文。",
        env={"ZENMUX_API_KEY": "test-key", zenmux_review.ENV_HOST_MODEL: "gemini-2.5-pro"},
    )
    assert by_env.returncode == zenmux_review.EXIT_NOT_CONFIGURED
    assert json.loads(by_env.stdout)["status"] == "skipped"

    text_out = _cli(
        "--kind", "page", "--host-model", "gemini", "--format", "text", "--text", "一段正文。",
        env={"ZENMUX_API_KEY": "test-key"},
    )
    assert text_out.returncode == zenmux_review.EXIT_NOT_CONFIGURED
    assert "已跳过远程审查" in text_out.stdout and "子 Agent" in text_out.stdout


def test_force_remote_and_non_gemini_host_still_call_zenmux() -> None:
    result_gpt, calls_gpt = _review(
        '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        host_model="gpt-6-astra",
    )
    assert result_gpt["status"] == "ok"
    assert calls_gpt == [DEFAULT_CHAIN[0]]

    result_forced, calls_forced = _review(
        '{"verdict":"PASS","blocking":[],"non_blocking":[],"fact_risk":"无"}',
        host_model="gemini-4-neon",
        force_remote=True,
    )
    assert result_forced["status"] == "ok"
    assert calls_forced == [DEFAULT_CHAIN[0]]


def test_check_models_skips_when_host_is_gemini() -> None:
    result = zenmux_review.check_models(api_key="test-key", host_model="gemini-4-neon")
    assert result["status"] == "skipped"
    assert result["checks"] == []
