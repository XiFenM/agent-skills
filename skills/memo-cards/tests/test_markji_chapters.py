"""Contract tests for append-only Markji chapter creation, with no live API calls."""
from __future__ import annotations

import copy
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_markji_api import api


STAMP = "2026-11-04T00:00:00Z"


class ChapterRemote:
    """An account model using the published deck/chapterset/chapter responses.

    Failure switches represent observable transport outcomes or other writers;
    they do not inspect the implementation's receipt or state machine.
    """

    def __init__(self, names=("已有章节",), *, empty_chapterset=True):
        self.deck = {
            "id": "Deck1", "name": "测试牌组", "source": "SELF", "status": "NORMAL",
            "is_private": True, "creator": "User1", "revision": 1,
            "created_time": STAMP, "updated_time": STAMP,
        }
        self.chapters = {}
        self.chapterset = None
        self.serial = 0
        self.calls = []
        self.failure = None
        self.list_transform = None
        self.response_transform = None
        self.detail_transform = None
        self.after_detail = None
        if empty_chapterset:
            self._ensure_chapterset()
        for name in names:
            self.add(name)

    def _ensure_chapterset(self):
        if self.chapterset is None:
            self.chapterset = {
                "id": "ChapterSet1", "deck_id": "Deck1", "revision": 0,
                "chapter_ids": [], "created_time": STAMP, "updated_time": STAMP,
            }

    def add(self, name):
        self._ensure_chapterset()
        self.serial += 1
        chapter_id = f"Chapter{self.serial}"
        chapter = {
            "id": chapter_id, "deck_id": "Deck1", "name": name, "revision": 1,
            "card_ids": [], "creator": "User1", "created_time": STAMP,
            "updated_time": STAMP,
        }
        self.chapters[chapter_id] = chapter
        self.chapterset["chapter_ids"].append(chapter_id)
        self.chapterset["revision"] += 1
        return chapter_id

    def remove(self, chapter_id):
        del self.chapters[chapter_id]
        self.chapterset["chapter_ids"].remove(chapter_id)
        self.chapterset["revision"] += 1

    def listing(self):
        if self.chapterset is None:
            return {"chapters": []}
        return {
            "chapterset": copy.deepcopy(self.chapterset),
            "chapters": [copy.deepcopy(self.chapters[key])
                         for key in self.chapterset["chapter_ids"]],
        }

    def request(self, method, path, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body), copy.deepcopy(query)))
        if method == "POST":
            assert path == "/decks/Deck1/chapters", "chapter creation must not mutate cards"
            assert set(body) == {"deck", "name", "order"}
            assert body["deck"] == "Deck1"
            assert body["order"] == len(self.chapters), "only append is authorized"
            if self.failure == "before-create":
                raise api.UploadError("测试超时，结果未知")
            if self.failure == "rejected":
                raise api.UploadError("测试参数被拒绝", http_status=400)
            chapter_id = self.add(body["name"])
            if self.failure == "after-create":
                raise api.UploadError("测试连接断开，结果未知")
            response = {
                "chapter": copy.deepcopy(self.chapters[chapter_id]),
                "chapterset": copy.deepcopy(self.chapterset),
            }
            return self.response_transform(response) if self.response_transform else response
        assert method == "GET", "no rename, reorder, delete or other mutation is authorized"
        if path == "/decks/Deck1":
            return {"deck": copy.deepcopy(self.deck)}
        if path == "/decks/Deck1/chapters":
            result = self.listing()
            return self.list_transform(result) if self.list_transform else result
        prefix = "/decks/Deck1/chapters/"
        assert path.startswith(prefix)
        chapter_id = path.removeprefix(prefix)
        result = {"chapter": copy.deepcopy(self.chapters[chapter_id]), "cards": []}
        if self.detail_transform:
            result = self.detail_transform(result)
        if self.after_detail:
            self.after_detail(chapter_id)
        return result


@pytest.fixture(autouse=True)
def no_live_account_access(monkeypatch, tmp_path):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    monkeypatch.setenv(api.TOKEN_FILE_ENV, str(tmp_path / "absent-token"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def deny_network(*args, **kwargs):
        pytest.fail("chapter tests must never contact a real API")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", deny_network)


@pytest.fixture
def chapter_case(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return repo, ChapterRemote()


def prepare(case, names=("新章节",)):
    repo, remote = case
    return api.prepare_chapters(repo, "Deck1", list(names), remote)


def create(case, plan, names=("新章节",), authorization="request"):
    repo, remote = case
    return api.create_chapters(repo, "Deck1", list(names), remote,
                               plan["preview_digest"], authorization)


def posts(remote):
    return [call for call in remote.calls if call[0] == "POST"]


def receipt(plan):
    return json.loads(Path(plan["receipt_path"]).read_text(encoding="utf-8"))


def test_prepare_only_reads_and_binds_the_exact_ordered_request(chapter_case, tmp_path):
    names = ["已有章节", "机制与取舍", "边界与诊断"]
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    plan = prepare(chapter_case, names)
    after = {str(path.relative_to(tmp_path)): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert not Path(plan["receipt_path"]).exists()
    assert all(call[0] == "GET" for call in chapter_case[1].calls)
    assert plan["names"] == names
    assert plan["deck"]["id"] == "Deck1" and plan["deck"]["is_private"] is True
    assert [(action["name"], action["operation"], action["order"])
            for action in plan["actions"]] == [
                ("已有章节", "skip", 0), ("机制与取舍", "create", 1),
                ("边界与诊断", "create", 2)]


def test_append_readback_and_repeat_preserve_existing_chapter_identity(chapter_case):
    names = ["机制与取舍", "已有章节", "边界与诊断"]
    remote = chapter_case[1]
    existing_id = remote.chapterset["chapter_ids"][0]
    plan = prepare(chapter_case, names)
    result = create(chapter_case, plan, names)
    assert result["verified"] is True
    assert (result["created"], result["skipped"]) == (2, 1)
    assert [(call[2]["name"], call[2]["order"]) for call in posts(remote)] == [
        ("机制与取舍", 1), ("边界与诊断", 2)]
    assert remote.chapterset["chapter_ids"][0] == existing_id
    assert [remote.chapters[key]["name"] for key in remote.chapterset["chapter_ids"]] == [
        "已有章节", "机制与取舍", "边界与诊断"]
    for entry in result["chapters"]:
        if entry["operation"] == "create":
            assert any(call[:2] == ("GET", f"/decks/Deck1/chapters/{entry['chapter_id']}")
                       for call in remote.calls), "a POST response is not independent readback"
    assert all(entry["status"] == "verified" for entry in receipt(plan)["chapters"].values())
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, names)
    again = prepare(chapter_case, names)
    repeated = create(chapter_case, again, names)
    assert (repeated["created"], repeated["skipped"]) == (0, 3)
    assert len(posts(remote)) == 2


@pytest.mark.parametrize("null_chapterset", [False, True])
def test_new_empty_deck_can_create_its_first_chapter(chapter_case, null_chapterset):
    repo, _ = chapter_case
    remote = ChapterRemote(names=(), empty_chapterset=False)
    if null_chapterset:
        remote.list_transform = lambda data: {**data, "chapterset": None}
    plan = prepare((repo, remote))
    # Only the original empty listing may lack a chapterset.
    remote.list_transform = None
    result = create((repo, remote), plan)
    assert result["created"] == 1 and posts(remote)[0][2]["order"] == 0


@pytest.mark.parametrize("names", [
    [], ["same", "same"], [""], [" leading"], ["trailing "], ["a\nb"],
    ["a\x00b"], [None], [True], ["x" * 201], [f"section-{i}" for i in range(101)],
    "a-name-is-not-a-list",
])
def test_invalid_names_stop_before_network(chapter_case, names):
    repo, remote = chapter_case
    with pytest.raises(api.UploadError):
        api.prepare_chapters(repo, "Deck1", names, remote)
    assert remote.calls == []


def test_duplicate_remote_name_requires_review(chapter_case):
    remote = chapter_case[1]
    remote.add("已有章节")
    with pytest.raises(api.UploadError):
        prepare(chapter_case, ["已有章节"])
    assert posts(remote) == []


@pytest.mark.parametrize("defect", [
    "missing-chapters", "missing-chapterset", "missing-list-member", "extra-list-member",
    "duplicate-id", "wrong-chapter-deck", "wrong-set-deck", "boolean-revision", "missing-card-ids",
])
def test_incomplete_or_invalid_listing_cannot_be_used_for_creation(chapter_case, defect):
    remote = chapter_case[1]

    def broken(data):
        if defect == "missing-chapters":
            del data["chapters"]
        elif defect == "missing-chapterset":
            del data["chapterset"]
        elif defect == "missing-list-member":
            data["chapters"] = []
        elif defect == "extra-list-member":
            data["chapters"].append({**data["chapters"][0], "id": "Unlisted"})
        elif defect == "duplicate-id":
            data["chapterset"]["chapter_ids"].append(data["chapterset"]["chapter_ids"][0])
        elif defect == "wrong-chapter-deck":
            data["chapters"][0]["deck_id"] = "OtherDeck"
        elif defect == "wrong-set-deck":
            data["chapterset"]["deck_id"] = "OtherDeck"
        elif defect == "boolean-revision":
            data["chapters"][0]["revision"] = True
        else:
            del data["chapters"][0]["card_ids"]
        return data

    remote.list_transform = broken
    with pytest.raises(api.UploadError):
        prepare(chapter_case)
    assert posts(remote) == []


@pytest.mark.parametrize("field,value", [
    ("source", "SHARED"), ("status", "DELETED"), ("is_private", "true"),
    ("id", "OtherDeck"), ("revision", True),
])
def test_only_a_verified_normal_self_deck_is_eligible(chapter_case, field, value):
    chapter_case[1].deck[field] = value
    with pytest.raises(api.UploadError):
        prepare(chapter_case)
    assert posts(chapter_case[1]) == []


@pytest.mark.parametrize("change", [
    "names", "name-order", "privacy", "deck-name", "chapter-name", "chapter-revision",
    "chapterset-revision", "remote-order", "remote-addition", "card-membership",
])
def test_changed_request_or_remote_snapshot_invalidates_old_digest(chapter_case, change):
    remote = chapter_case[1]
    remote.add("另一个已有章节")
    names = ["第一章", "第二章"]
    plan = prepare(chapter_case, names)
    first = remote.chapterset["chapter_ids"][0]
    if change == "names":
        names = ["不同章名", "第二章"]
    elif change == "name-order":
        names.reverse()
    elif change == "privacy":
        remote.deck["is_private"] = False
    elif change == "deck-name":
        remote.deck["name"] = "改过的牌组"
    elif change == "chapter-name":
        remote.chapters[first]["name"] = "远端改名"
    elif change == "chapter-revision":
        remote.chapters[first]["revision"] += 1
    elif change == "chapterset-revision":
        remote.chapterset["revision"] += 1
    elif change == "remote-order":
        remote.chapterset["chapter_ids"].reverse()
    elif change == "remote-addition":
        remote.add("外部新增")
    else:
        remote.chapters[first]["card_ids"] = ["ExternalCard1"]
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, names)
    assert posts(remote) == []


def test_receipt_change_invalidates_preview_before_another_post(chapter_case):
    first = prepare(chapter_case, ["已有章节"])
    create(chapter_case, first, ["已有章节"])
    plan = prepare(chapter_case)
    path = Path(plan["receipt_path"])
    changed = receipt(plan)
    changed["chapters"]["已有章节"]["order"] += 1
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(api.UploadError):
        create(chapter_case, plan)
    assert posts(chapter_case[1]) == []


@pytest.mark.parametrize("failure", ["before-create", "after-create"])
def test_uncertain_post_is_never_automatically_retried(chapter_case, failure):
    remote = chapter_case[1]
    plan = prepare(chapter_case)
    remote.failure = failure
    with pytest.raises(api.UploadError):
        create(chapter_case, plan)
    assert receipt(plan)["chapters"]["新章节"]["status"] == "pending"
    assert len(posts(remote)) == 1
    remote.failure = None
    if failure == "before-create":
        with pytest.raises(api.UploadError):
            prepare(chapter_case)
    else:
        recovered = prepare(chapter_case)
        assert recovered["actions"][0]["operation"] == "skip"
        assert recovered["actions"][0]["recovery"] is True
        result = create(chapter_case, recovered)
        assert (result["created"], result["skipped"]) == (0, 1)
        assert receipt(recovered)["chapters"]["新章节"]["status"] == "verified"
    assert len(posts(remote)) == 1


def test_uncertain_post_with_two_matching_chapters_does_not_guess(chapter_case):
    remote = chapter_case[1]
    plan = prepare(chapter_case)
    remote.failure = "after-create"
    with pytest.raises(api.UploadError):
        create(chapter_case, plan)
    remote.failure = None
    remote.add("新章节")
    with pytest.raises(api.UploadError):
        prepare(chapter_case)
    assert len(posts(remote)) == 1


@pytest.mark.parametrize("change", ["renamed", "deleted", "replaced-by-same-name"])
def test_recorded_chapter_id_is_not_replaced_by_name_matching(chapter_case, change):
    remote = chapter_case[1]
    plan = prepare(chapter_case)
    result = create(chapter_case, plan)
    chapter_id = result["chapters"][0]["chapter_id"]
    if change == "renamed":
        remote.chapters[chapter_id]["name"] = "人工改名"
        remote.chapters[chapter_id]["revision"] += 1
    else:
        remote.remove(chapter_id)
        if change == "replaced-by-same-name":
            assert remote.add("新章节") != chapter_id
    with pytest.raises(api.UploadError):
        prepare(chapter_case)
    assert len(posts(remote)) == 1


def test_explicit_http_400_needs_a_fresh_preview(chapter_case):
    remote = chapter_case[1]
    plan = prepare(chapter_case)
    remote.failure = "rejected"
    with pytest.raises(api.UploadError):
        create(chapter_case, plan)
    entry = receipt(plan)["chapters"]["新章节"]
    assert entry["status"] == "rejected" and entry["http_status"] == 400
    assert not entry.get("chapter_id")
    assert len(posts(remote)) == 1
    remote.failure = None
    with pytest.raises(api.UploadError):
        create(chapter_case, plan)
    assert len(posts(remote)) == 1
    fresh = prepare(chapter_case)
    assert fresh["preview_digest"] != plan["preview_digest"]
    assert create(chapter_case, fresh)["created"] == 1
    assert len(posts(remote)) == 2


@pytest.mark.parametrize("defect", [
    "missing-chapter", "missing-chapterset", "wrong-name", "wrong-deck",
    "unlisted-created-id", "unexpected-content",
])
def test_ambiguous_create_response_stops_the_batch(chapter_case, defect):
    remote = chapter_case[1]
    names = ["第一章", "第二章"]

    def malformed(data):
        if defect == "missing-chapter":
            del data["chapter"]
        elif defect == "missing-chapterset":
            del data["chapterset"]
        elif defect == "wrong-name":
            data["chapter"]["name"] = "不是申请的名称"
        elif defect == "wrong-deck":
            data["chapter"]["deck_id"] = "OtherDeck"
        elif defect == "unlisted-created-id":
            data["chapterset"]["chapter_ids"].remove(data["chapter"]["id"])
        else:
            data["chapter"]["card_ids"] = ["UnexpectedCard"]
        return data

    remote.response_transform = malformed
    plan = prepare(chapter_case, names)
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, names)
    assert len(posts(remote)) == 1
    assert receipt(plan)["chapters"]["第一章"]["status"] != "verified"


@pytest.mark.parametrize("defect", ["name", "id", "deck_id", "card_ids"])
def test_independent_readback_must_match_the_created_chapter(chapter_case, defect):
    remote = chapter_case[1]
    names = ["第一章", "第二章"]

    def corrupt(data):
        if data["chapter"]["name"] == "第一章":
            data["chapter"][defect] = ["UnexpectedCard"] if defect == "card_ids" else "Different"
        return data

    remote.detail_transform = corrupt
    plan = prepare(chapter_case, names)
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, names)
    assert len(posts(remote)) == 1
    assert receipt(plan)["chapters"]["第一章"]["status"] != "verified"


@pytest.mark.parametrize("change", ["external-append", "rename-created", "privacy"])
def test_concurrent_change_after_first_readback_prevents_the_next_post(chapter_case, change):
    remote = chapter_case[1]
    names = ["第一章", "第二章"]
    changed = False

    def concurrent_writer(chapter_id):
        nonlocal changed
        if changed or remote.chapters[chapter_id]["name"] != "第一章":
            return
        changed = True
        if change == "external-append":
            remote.add("其他设备新建")
        elif change == "rename-created":
            remote.chapters[chapter_id]["name"] = "其他设备改名"
            remote.chapters[chapter_id]["revision"] += 1
        else:
            remote.deck["is_private"] = False

    remote.after_detail = concurrent_writer
    plan = prepare(chapter_case, names)
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, names)
    assert changed is True
    assert [call[2]["name"] for call in posts(remote)] == ["第一章"]


def test_chapter_writer_uses_the_existing_global_card_upload_lock(chapter_case):
    repo, remote = chapter_case
    plan = prepare(chapter_case)
    card_receipt = api.receipt_path(repo, "cards/unrelated.md", "OtherDeck", "OtherChapter")
    remote.calls.clear()
    with api.upload_lock(card_receipt):
        with pytest.raises(api.UploadError):
            create(chapter_case, plan)
    assert remote.calls == [], "writers must lock before fetching a supposedly stable snapshot"


@pytest.mark.parametrize("authorization", [None, "", "implicit"])
def test_create_requires_explicit_supported_authorization(chapter_case, authorization):
    plan = prepare(chapter_case)
    chapter_case[1].calls.clear()
    with pytest.raises(api.UploadError):
        create(chapter_case, plan, authorization=authorization)
    assert chapter_case[1].calls == []


def test_chapter_create_wire_body_keeps_the_schema_required_deck(monkeypatch):
    client = api.Client("unit-test-token")
    sent = []

    def response(request, timeout):
        sent.append(request)
        return io.BytesIO(b'{"success":true,"data":{"chapter":{},"chapterset":{}},"errors":[]}')

    monkeypatch.setattr(client._opener, "open", response)
    body = {"deck": "Deck1", "name": "机制与取舍", "order": 2}
    original = copy.deepcopy(body)
    client.request("POST", "/decks/Deck1/chapters", body)
    assert len(sent) == 1
    assert sent[0].full_url == api.ORIGIN + api.BASE_PATH + "/decks/Deck1/chapters"
    assert json.loads(sent[0].data) == original
    assert body == original
    assert sent[0].get_header("Authorization") == "Bearer unit-test-token"


def test_chapter_wire_target_mismatch_is_rejected_before_http(monkeypatch):
    client = api.Client("unit-test-token")

    def should_not_send(*args, **kwargs):
        pytest.fail("a mismatched chapter target must not reach HTTP")

    monkeypatch.setattr(client._opener, "open", should_not_send)
    with pytest.raises(api.UploadError):
        client.request("POST", "/decks/Deck1/chapters",
                       {"deck": "OtherDeck", "name": "章节", "order": 0})


@pytest.mark.parametrize("method,path", [
    ("POST", "/decks"), ("POST", "/decks/Deck1"),
    ("POST", "/decks/Deck1/chapters/Chapter1"),
    ("PUT", "/decks/Deck1/chapters"), ("DELETE", "/decks/Deck1/chapters/Chapter1"),
    ("POST", "/decks/Deck1/chaptersets/Set1"),
])
def test_chapter_feature_does_not_enable_other_write_routes(method, path):
    client = api.Client("unit-test-token")
    with pytest.raises(api.UploadError):
        client.request(method, path, {"deck": "Deck1", "name": "章节", "order": 0})


def test_cli_accepts_repeated_names_without_card_artifact_arguments(chapter_case, monkeypatch, capsys):
    repo, remote = chapter_case
    monkeypatch.setattr(api, "load_token", lambda: "unit-test-token")
    monkeypatch.setattr(api, "Client", lambda token: remote)
    arguments = ["--repo", str(repo), "--deck", "Deck1", "--name", "第一章", "--name", "第二章"]
    assert api.main(["chapters-prepare", *arguments]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["ok"] is True and preview["result"]["names"] == ["第一章", "第二章"]
    assert posts(remote) == []
    assert api.main(["chapters-create", *arguments, "--preview-digest",
                     preview["result"]["preview_digest"], "--authorization", "confirmed"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True and result["result"]["created"] == 2


@pytest.mark.parametrize("command", ["chapters-prepare", "chapters-create"])
def test_cli_bad_arguments_never_echo_accidental_token(command, capsys):
    secret = "unit-test-secret-that-must-not-be-printed"
    assert api.main([command, "--token", secret]) == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert json.loads(output.out)["ok"] is False


@pytest.mark.parametrize("status", [401, 403])
def test_cli_authentication_errors_never_print_credentials(chapter_case, monkeypatch, capsys, status):
    repo, _ = chapter_case
    secret = "unit-test-secret-that-must-not-be-printed"
    client = api.Client(secret)

    def reject(request, timeout):
        body = {"errors": [{"code": "AUTH", "msg": f"Bearer {secret}", "info": secret}]}
        raise urllib.error.HTTPError(request.full_url, status, secret, {},
                                     io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(client._opener, "open", reject)
    monkeypatch.setattr(api, "load_token", lambda: secret)
    monkeypatch.setattr(api, "Client", lambda token: client)
    assert api.main(["chapters-prepare", "--repo", str(repo), "--deck", "Deck1",
                     "--name", "章节"]) == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert json.loads(output.out)["ok"] is False
