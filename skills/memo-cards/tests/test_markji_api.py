from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import sys
import urllib.error
import warnings
from pathlib import Path

import pytest

from test_memo_cards import _card, _environment, _request, memo_cards as memo

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "markji_api.py"
SPEC = importlib.util.spec_from_file_location("markji_api", SCRIPT)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class Remote:
    """Models the published OpenAPI response shapes, not a live account."""
    def __init__(self):
        self.cards = {}
        self.name = "测试牌组"
        self.calls = []
        self.fail = None

    def request(self, method, path, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == "POST":
            assert path == "/decks/Deck1/chapters/Chapter1/cards"
            assert set(body) == {"deck", "chapter", "card"}
            assert body["deck"] == "Deck1" and body["chapter"] == "Chapter1"
            if self.fail == "before-create":
                raise api.UploadError("测试超时")
            key = "Card" + str(len(self.cards) + 1)
            card = {"id": key, "root_id": "Root" + key, "deck_id": "Deck1", "status": "NORMAL", **body["card"]}
            self.cards[key] = card
            if self.fail == "after-create":
                raise api.UploadError("测试连接断开")
            return {"card": copy.deepcopy(card), "chapter": self.chapter()}
        if path == "/decks/Deck1":
            return {"deck": {"id": "Deck1", "name": self.name, "source": "SELF", "status": "NORMAL",
                             "is_private": True, "creator": "User1"}}
        if path == "/decks/Deck1/chapters/Chapter1":
            return {"chapter": self.chapter(), "cards": copy.deepcopy(list(self.cards.values()))}
        return {"card": copy.deepcopy(self.cards[path.rsplit("/", 1)[1]])}

    def chapter(self):
        return {"id": "Chapter1", "name": "测试章节", "deck_id": "Deck1",
                "card_ids": list(self.cards), "revision": len(self.cards)}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    environment = _environment(tmp_path)
    request, _ = _request(environment, [_card("one", 1, answer="数组 [0,1] 的边界。")])
    plan = memo.prepare(environment["repo"], environment["context"], request)
    memo.publish(environment["repo"], environment["context"], request, plan["preview_digest"], "request")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    remote = Remote()
    # The version is test data, not a claimed production default.
    return (environment["repo"], environment["context"], request, "Deck1", "Chapter1", 7, remote)


def test_prepare_is_read_only_and_upload_readback_is_repeatable(ready):
    plan = api.prepare_upload(*ready)
    assert not Path(plan["receipt_path"]).exists()
    assert all(call[0] == "GET" for call in ready[-1].calls)
    content = plan["actions"][0]["content"]
    assert "\n---\n" in content and r"\[0,1\]" in content
    assert json.loads(json.dumps({"content": content}))["content"] == content
    assert api.upload(*ready, plan["preview_digest"], "request")["created"] == 1
    again = api.prepare_upload(*ready)
    result = api.upload(*ready, again["preview_digest"], "request")
    assert result["skipped"] == 1 and result["created"] == 0
    assert sum(call[0] == "POST" for call in ready[-1].calls) == 1
    receipt = json.loads(Path(plan["receipt_path"]).read_text())
    assert next(iter(receipt["cards"].values()))["root_id"] == "RootCard1"
    assert "content" not in next(iter(receipt["cards"].values()))


@pytest.mark.parametrize("failure", ["before-create", "after-create"])
def test_uncertain_create_is_never_replayed(ready, failure):
    plan = api.prepare_upload(*ready)
    remote = ready[-1]
    remote.fail = failure
    with pytest.raises(api.UploadError):
        api.upload(*ready, plan["preview_digest"], "confirmed")
    receipt = json.loads(Path(plan["receipt_path"]).read_text())
    assert next(iter(receipt["cards"].values()))["status"] == "pending"
    remote.fail = None
    if failure == "before-create":
        with pytest.raises(api.UploadError, match="停止重发"):
            api.prepare_upload(*ready)
    else:
        recovered = api.prepare_upload(*ready)
        assert api.upload(*ready, recovered["preview_digest"], "request")["skipped"] == 1
    assert sum(call[0] == "POST" for call in remote.calls) == 1


def test_changed_destination_invalidates_preview(ready):
    plan = api.prepare_upload(*ready)
    ready[-1].name = "不同的牌组名称"
    with pytest.raises(api.UploadError, match="已变化"):
        api.upload(*ready, plan["preview_digest"], "request")
    assert not any(call[0] == "POST" for call in ready[-1].calls)


def test_temporary_media_urls_do_not_invalidate_preview_but_content_does(ready):
    remote = ready[-1]
    remote.cards["Existing"] = {"id": "Existing", "deck_id": "Deck1", "status": "NORMAL",
        "grammar_version": 7, "content": "题目\n---\n[Pic#ID/Image1#]",
        "files": [{"id": "Image1", "url": "https://example.com/first", "expire_time": "first"}]}
    first = api.prepare_upload(*ready)
    remote.cards["Existing"]["files"][0].update(url="https://example.com/second", expire_time="second")
    assert api.prepare_upload(*ready)["preview_digest"] == first["preview_digest"]
    remote.cards["Existing"]["content"] = "人工修改"
    assert api.prepare_upload(*ready)["preview_digest"] != first["preview_digest"]


def test_local_drift_blocks_before_network(ready):
    plan = api.prepare_upload(*ready)
    (ready[0] / "notes/topic.md").write_text("内容已改变")
    ready[-1].calls.clear()
    with pytest.raises(memo.MemoCardsError):
        api.upload(*ready, plan["preview_digest"], "request")
    assert ready[-1].calls == []


def test_remote_manual_edit_never_overwritten(ready):
    plan = api.prepare_upload(*ready)
    api.upload(*ready, plan["preview_digest"], "request")
    ready[-1].cards["Card1"]["content"] = "人工修改的卡片"
    with pytest.raises(api.UploadError, match="停止重发"):
        api.prepare_upload(*ready)
    assert sum(call[0] == "POST" for call in ready[-1].calls) == 1


def test_duplicate_remote_content_requires_review(ready):
    plan = api.prepare_upload(*ready)
    api.upload(*ready, plan["preview_digest"], "request")
    ready[-1].cards["Card2"] = {**ready[-1].cards["Card1"], "id": "Card2"}
    with pytest.raises(api.UploadError, match="多张相同"):
        api.prepare_upload(*ready)


def test_receipt_change_invalidates_preview(ready):
    plan = api.prepare_upload(*ready)
    path = Path(plan["receipt_path"])
    api.atomic_private_json(path, {"schema": api.STATE_SCHEMA, "cards": {}, "changed": True})
    with pytest.raises(api.UploadError, match="已变化"):
        api.upload(*ready, plan["preview_digest"], "request")
    assert not any(call[0] == "POST" for call in ready[-1].calls)


def test_global_upload_lock_blocks_other_target(tmp_path):
    with api.upload_lock(tmp_path / "state" / "a.json"):
        with pytest.raises(api.UploadError, match="中断锁"):
            with api.upload_lock(tmp_path / "state" / "b.json"):
                pytest.fail("must not run two upload writers")


@pytest.mark.skipif(os.name != "posix", reason="file credentials require POSIX permissions")
def test_key_file_permissions_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    path = tmp_path / "credentials" / "token"
    api.private_directory(path.parent)
    path.write_text("test-token-only\n")
    path.chmod(0o600)
    monkeypatch.setenv(api.TOKEN_FILE_ENV, str(path))
    assert api.load_token() == "test-token-only"
    path.write_text("a" * 4096 + "\n")
    assert api.load_token() == "a" * 4096
    path.chmod(0o644)
    with pytest.raises(api.UploadError, match="0600"):
        api.load_token()
    monkeypatch.setenv(api.TOKEN_ENV, "test-environment-token")
    assert api.load_token() == "test-environment-token"
    monkeypatch.setenv(api.TOKEN_ENV, "bad\nheader")
    with pytest.raises(api.UploadError, match="格式无效"):
        api.load_token()


@pytest.mark.skipif(os.name != "posix", reason="symlink fixture requires POSIX")
def test_key_path_cannot_be_in_git_or_symlink(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setenv(api.TOKEN_FILE_ENV, str(repo / "token"))
    with pytest.raises(api.UploadError, match="Git 仓库之外"):
        api.token_path()
    linked = tmp_path / "link"
    linked.symlink_to(repo, target_is_directory=True)
    monkeypatch.setenv(api.TOKEN_FILE_ENV, str(linked / "token"))
    with pytest.raises(api.UploadError, match="符号链接"):
        api.token_path()


def test_auth_status_does_not_read_or_print_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(api.TOKEN_FILE_ENV, raising=False)
    monkeypatch.setenv(api.TOKEN_ENV, "test-secret-never-output")
    monkeypatch.setattr(api, "load_token", lambda: pytest.fail("status must not read key"))
    assert api.main(["auth-status"]) == 0
    output = capsys.readouterr().out
    assert "test-secret" not in output and json.loads(output)["ok"] is True


@pytest.mark.skipif(os.name != "posix", reason="file credentials require POSIX permissions")
def test_auth_set_requires_hidden_terminal_input(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(api.TOKEN_FILE_ENV, raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(api.UploadError, match="交互终端"):
        api.auth_set()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    def cannot_hide(_):
        warnings.warn("cannot hide input", api.getpass.GetPassWarning)
        pytest.fail("must stop before echoed input")
    monkeypatch.setattr(api.getpass, "getpass", cannot_hide)
    with pytest.raises(api.UploadError, match="关闭输入回显"):
        api.auth_set()
    assert not api.token_path().exists()
    monkeypatch.setattr(api.getpass, "getpass", lambda _: "test-terminal-token")
    result = api.auth_set()
    assert result["configured"] is True
    assert api.token_path().stat().st_mode & 0o777 == 0o600
    assert api.token_path().parent.stat().st_mode & 0o777 == 0o700
    assert "test-terminal-token" not in json.dumps(result)
    with pytest.raises(api.UploadError, match="已存在"):
        api.auth_set()


def test_rejected_cli_argument_does_not_echo_accidental_secret(capsys):
    assert api.main(["decks", "--token", "test-secret-never-output"]) == 2
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_transport_errors_do_not_echo_headers_body_or_retry(status, monkeypatch, capsys):
    client = api.Client("test-secret-never-output")
    calls = []
    def fail(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, "test-secret-never-output", {},
                                     io.BytesIO(b"test-secret-never-output"))
    monkeypatch.setattr(client._opener, "open", fail)
    monkeypatch.setenv(api.TOKEN_ENV, "test-secret-never-output")
    monkeypatch.setattr(api, "Client", lambda _: client)
    assert api.main(["decks"]) == 2
    assert "test-secret" not in capsys.readouterr().out
    assert len(calls) == 1
    assert calls[0].full_url.startswith(api.ORIGIN + api.BASE_PATH)


def test_transport_rejects_redirects_origins_and_mutations():
    client = api.Client("test-token")
    for method, path in [("GET", "https://example.com/"), ("GET", "/decks/../tokens"),
                         ("POST", "/decks/D/cards/C"), ("DELETE", "/decks/D")]:
        with pytest.raises(api.UploadError):
            client.request(method, path)
    with pytest.raises(api.UploadError, match="重定向"):
        api.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com/")


def test_syntax_regressions_and_multiselect_end_to_end(tmp_path):
    assert memo._render_content({"parts": [{"type": "audio", "id": "AaZ9", "text": "播放"}]}, "audio") == "[Audio#ID/AaZ9,M#播放]"
    assert memo._render_text("索引 [0,1]", "text") == r"索引 \[0,1\]"
    assert memo._plain_text("索引 [0,1]", "identity") == "索引 [0,1]"
    with pytest.raises(memo.MemoCardsError, match="one answer"):
        memo._render_field("AC", "choice-answer-4", "answer")
    environment = _environment(tmp_path)
    card = _card("multi", 1, assessment="discrimination")
    card["template_id"] = "choice-multi"
    card["fields"] = {"题干": "哪些条件成立？", "选择": {"options": ["第一项", "第二项", "第三项"], "answers": [1, 3], "fixed": True},
                      "解析": "第一项和第三项成立。", "场景": "核验材料"}
    request, _ = _request(environment, [card, _card("cloze", 2, template_id="cloze", answer="one word")])
    plan = memo.prepare(environment["repo"], environment["context"], request)
    memo.publish(environment["repo"], environment["context"], request, plan["preview_digest"], "request")
    bundle = api.local_bundle(environment["repo"], environment["context"], request)
    content = "\n".join(c["content"] for c in bundle["cards"])
    assert "[Choice#fixed,multi#\n* 第一项\n- 第二项\n* 第三项\n]" in content
    assert "[F#1#one word]" in content


@pytest.mark.parametrize("formula", ["$x$", "$$x$$", r"\(x\)", r"\[x\]", "x[0]"])
def test_formula_external_delimiters_are_rejected(formula):
    with pytest.raises(memo.MemoCardsError):
        memo._render_content({"parts": [{"type": "formula", "katex": formula}]}, "formula")


@pytest.mark.parametrize("url", ['https://example.com/a,b', 'https://example.com/a#b', 'https://example.com/a b'])
def test_unsafe_link_parameter_is_not_silently_rewritten(url):
    with pytest.raises(memo.MemoCardsError, match="URL parameter"):
        memo._public_url(url, "url")


def test_card_reference_preserves_root_id_case_and_deduplicates():
    content = {"parts": [{"type": "card-ref", "ids": ["aB12", "aB12", "Ab12"], "text": "参见"}]}
    assert memo._render_content(content, "reference") == "[Card#ID/aB12-Ab12#参见]"


def test_single_choice_api_conversion_preserves_body():
    template = memo.load_template_registry().by_id["choice-3"]
    content = api.render_card(template, {"题干": "哪一项？", "答案": "B", "选项1": "甲", "选项2": "乙", "选项3": "丙", "解析": "乙符合条件。", "场景": "来源"})
    assert "[Choice#fixed#\n- 甲\n* 乙\n- 丙\n]\n---\n乙符合条件。" in content


def test_production_response_envelope_and_opaque_ids(monkeypatch):
    client = api.Client("test-token")
    monkeypatch.setattr(client._opener, "open", lambda *_a, **_k: io.BytesIO(json.dumps(
        {"success": True, "data": {"decks": [{"id": "mkjd_aB.c_9-Z"}], "total": 1}, "errors": []}
    ).encode()))
    assert client.request("GET", "/decks")["decks"][0]["id"] == "mkjd_aB.c_9-Z"
    assert api.identifier("mkjd_aB.c_9-Z") == "mkjd_aB.c_9-Z"
    for bad in ("..", ".", "a/b", "a?key=x", "a#b", "https://example.com"):
        with pytest.raises(api.UploadError):
            api.identifier(bad)
    client._last_request = None
    monkeypatch.setattr(client._opener, "open", lambda *_a, **_k: io.BytesIO(b'{"success":true,"data":{"deck":{}},"errors":[]}'))
    assert client.request("GET", "/decks/mkjd_aB.c_9-Z") == {"deck": {}}


@pytest.mark.parametrize("payload", [
    {"success": False, "data": None, "errors": ["test-secret-never-output"]},
    {"success": "true", "data": {}},
    {"success": True, "data": None},
    {"success": True, "data": {}},
    {"success": True, "data": {"decks": [], "total": 0}, "errors": ["test-secret-never-output"]},
])
def test_business_failure_is_not_reported_as_empty_decks(payload, monkeypatch):
    client = api.Client("test-token")
    monkeypatch.setattr(client._opener, "open", lambda *_a, **_k: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(api.UploadError) as error:
        client.request("GET", "/decks")
    assert "test-secret" not in str(error.value)


def test_selected_cards_are_bound_to_preview_and_only_they_are_uploaded(ready):
    repo, context, request, *_ = ready
    value = json.loads(request.read_text())
    value["cards"].append(_card("two", 2))
    request.write_text(json.dumps(value))
    preview = memo.prepare(repo, context, request)
    memo.publish(repo, context, request, preview["preview_digest"], "confirmed")
    cards = api.local_bundle(repo, context, request)["cards"]
    first, second = [card["logical_id"] for card in cards]
    plan = api.prepare_upload(*ready, logical_ids=[first])
    assert plan["local"]["selected_logical_ids"] == [first]
    assert len(plan["actions"]) == 1
    with pytest.raises(api.UploadError, match="已变化"):
        api.upload(*ready, plan["preview_digest"], "request", logical_ids=[second])
    assert not ready[-1].cards
    result = api.upload(*ready, plan["preview_digest"], "request", logical_ids=[first])
    assert result["created"] == 1 and len(ready[-1].cards) == 1
    assert next(iter(ready[-1].cards.values()))["content"] == cards[0]["content"]
    for invalid in ([], [first, first], ["mc-" + "0" * 24], ["not-an-id"]):
        with pytest.raises(api.UploadError):
            api.prepare_upload(*ready, logical_ids=invalid)
