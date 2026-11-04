#!/usr/bin/env python3
"""Create chapters and upload verified cards through the official Markji OpenAPI.

No token argument, arbitrary API origin, or automatic POST retry. Remote content is
overwritten only for a card this tool uploaded whose remote text still matches its receipt.
The local journal is written before each POST so uncertain outcomes stop safely.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import http.client
import json
import os
import re
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import warnings
from contextlib import contextmanager
from pathlib import Path

import memo_cards as memo

ORIGIN = "https://open.maimemo.com"
BASE_PATH = "/open/api/v1/markji"
PLAN_SCHEMA = "memo-cards.markji-upload/v1"
STATE_SCHEMA = "memo-cards.markji-receipt/v1"
CHAPTER_PLAN_SCHEMA = "memo-cards.markji-chapters/v1"
CHAPTER_STATE_SCHEMA = "memo-cards.markji-chapter-receipt/v1"
TOKEN_ENV = "MAIMEMO_API_TOKEN"
TOKEN_FILE_ENV = "MAIMEMO_API_TOKEN_FILE"
MAX_BATCH = 200
MAX_RESPONSE = 16 * 1024 * 1024
# Local review/response bounds, not claims about official API quotas.
MAX_CHAPTER_BATCH = 100
MAX_CHAPTER_NAME = 200


class UploadError(Exception):
    """Only fixed, credential-free messages may cross the CLI boundary."""

    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected argument values, including a token
        # accidentally supplied on the command line.
        raise UploadError("命令参数无效，请查看 --help；密钥只能由环境变量或私有文件提供。")


def digest(value):
    return hashlib.sha256(memo._canonical_bytes(value)).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise UploadError("需要官方接口返回的有效 OpenAPI ID。")
    return value


def outside_git(path):
    path = Path(os.path.abspath(path.expanduser()))
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise UploadError("凭据和上传回执路径不能经过符号链接。")
        marker = parent / ".git"
        if parent.is_dir() and (marker.is_file() or (marker / "HEAD").is_file()):
            raise UploadError("凭据和上传回执必须存放在 Git 仓库之外。")
    return path


def private_directory(path):
    path = outside_git(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise UploadError("专用目录须归当前用户所有且权限为 0700。")
    return path


def token_path():
    configured = os.environ.get(TOKEN_FILE_ENV)
    if configured and not Path(configured).is_absolute():
        raise UploadError("MAIMEMO_API_TOKEN_FILE 必须是仓库外的绝对路径。")
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return outside_git(Path(configured) if configured else base / "memo-cards" / "maimemo-token")


def read_private(path, *, secret=False):
    path = outside_git(path)
    if secret and os.name != "posix":
        raise UploadError("当前平台请从系统凭据管理器注入 MAIMEMO_API_TOKEN；文件凭据仅支持 POSIX 权限校验。")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UploadError("凭据或回执必须是普通文件，不能是链接或设备。")
        if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise UploadError("凭据或回执须归当前用户所有且权限为 0600。")
        limit = 4097 if secret else MAX_RESPONSE  # 4096 token bytes plus auth-set's newline.
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise UploadError("凭据或回执长度超过限制。")
        return raw


def valid_token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,4096}", value):
        raise UploadError("请求凭据为空或格式无效；只输入 token 本身，不含 Bearer 前缀。")
    return value


def load_token():
    if TOKEN_ENV in os.environ:
        return valid_token(os.environ[TOKEN_ENV])
    try:
        return valid_token(read_private(token_path(), secret=True).decode("ascii").rstrip("\n"))
    except (OSError, UnicodeError):
        raise UploadError("无法读取请求凭据；请在本机终端配置，勿把密钥发到对话中。") from None


def atomic_private_json(path, value):
    parent = private_directory(path.parent)
    outside_git(path)
    fd, temporary = tempfile.mkstemp(prefix=".memo-upload-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(memo._canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def auth_set():
    if os.name != "posix" or not sys.stdin.isatty() or not sys.stderr.isatty():
        raise UploadError("请在本机交互终端运行 auth-set；其他平台使用系统凭据管理器注入环境变量。")
    path = token_path()
    private_directory(path.parent)
    if path.exists():
        raise UploadError("凭据文件已存在；轮换时先在官方撤销旧 token，再由本人移除旧凭据文件并重新设置。")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            token = valid_token(getpass.getpass("墨墨 API token（输入不显示）："))
        except getpass.GetPassWarning:
            raise UploadError("终端无法关闭输入回显，已取消；请换用支持隐藏输入的终端。") from None
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(token + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"configured": True, "storage": "private-file", "path": str(path)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UploadError("官方接口发生重定向；已停止，未向新地址发送凭据。")


class Client:
    def __init__(self, token):
        self._token = valid_token(token)
        # TLS verification stays enabled. Ambient proxy configuration is not used.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self._last_request = None

    def request(self, method, path, body=None, query=None):
        opaque_id = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        get_path = rf"/decks(?:/{opaque_id}(?:/chapters(?:/{opaque_id})?|/cards/{opaque_id})?)?"
        create_path = rf"/decks/{opaque_id}/chapters/{opaque_id}/cards"
        update_path = rf"/decks/{opaque_id}/cards/{opaque_id}"
        chapter_create_path = rf"/decks/{opaque_id}/chapters"
        if not ((method == "GET" and re.fullmatch(get_path, path)) or
                (method == "POST" and (re.fullmatch(create_path, path) or re.fullmatch(update_path, path)
                                       or re.fullmatch(chapter_create_path, path)))):
            raise UploadError("操作不在当前已核验的官方接口范围内。")
        if method == "POST" and re.fullmatch(chapter_create_path, path):
            if (not isinstance(body, dict) or set(body) - {"deck", "name", "order"}
                    or body.get("deck") != path.split("/")[2]):
                raise UploadError("章节创建请求的路径与正文目标不一致，或包含不支持的字段。")
            chapter_names([body.get("name")])
            if "order" in body and (type(body["order"]) is not int or body["order"] < 0):
                raise UploadError("章节插入位置必须是非负整数。")
            # Production accepted deck/name/order on 2026-11-04. Keep the deck
            # after binding it to the path; CreateCard's ID stripping is separate.
        url = ORIGIN + BASE_PATH + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        if self._last_request is not None:
            time.sleep(max(0, 1.6 - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()
        wire_body = body
        if method == "POST" and re.fullmatch(create_path, path) and isinstance(body, dict):
            # Production binds these IDs from the URL. Repeating encoded IDs
            # in JSON returns common_invalid_param, although the schema export
            # includes them in the operation's request message.
            parts = path.split("/")
            if body.get("deck") != parts[2] or body.get("chapter") != parts[4]:
                raise UploadError("创建请求的路径与正文目标不一致。")
            wire_body = {key: value for key, value in body.items() if key not in {"deck", "chapter"}}
        if method == "POST" and re.fullmatch(update_path, path) and isinstance(body, dict):
            # UpdateCard's schema repeats deck_id/card_id in the body like CreateCard does; bind
            # them from the URL the same way and check that the two agree.
            parts = path.split("/")
            if body.get("deck_id") != parts[2] or body.get("card_id") != parts[4]:
                raise UploadError("更新请求的路径与正文目标不一致。")
            wire_body = {key: value for key, value in body.items() if key not in {"deck_id", "card_id"}}
        request = urllib.request.Request(url, method=method,
            data=None if wire_body is None else json.dumps(wire_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Authorization": "Bearer " + self._token,
                     "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise UploadError("官方响应过大，已停止。")
            data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = ""
            try:
                error_body = json.loads(exc.read(8192))
                errors = error_body.get("errors", []) if isinstance(error_body, dict) else []
                if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                    parts = []
                    for key in ("code", "msg", "info"):
                        value = errors[0].get(key)
                        if isinstance(value, (str, int)):
                            safe = str(value).replace(self._token, "[redacted]")
                            safe = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", safe)
                            if re.search(r"(?i)token|api.?key|authorization|bearer|密钥|凭据", safe):
                                safe = "[credential-related error redacted]"
                            safe = " ".join(safe.split())[:300]
                            if safe:
                                parts.append(f"{key}={safe}")
                    detail = "；".join(parts)
            except (ValueError, OSError):
                pass
            exc.close()
            if status in (401, 403):
                raise UploadError("认证失败或没有目标权限；检查 token 与自建牌组权限。") from None
            if status == 429:
                raise UploadError("官方限流，已停止；不自动重试创建请求。") from None
            message = f"官方接口返回 HTTP {status}，已停止；不自动重试。"
            if detail:
                message += " 结构化错误（已脱敏）：" + detail
            raise UploadError(message, http_status=status) from None
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
            raise UploadError("请求未获得可验证的响应；写入请求的结果可能不确定，请先核对回执与远端。") from None
        if not isinstance(data, dict):
            raise UploadError("官方响应结构不符合已核验合同。")
        # The published operation schemas describe the payload; production
        # responses wrap it in {success, data, errors}.
        if "success" in data:
            if (data["success"] is not True or not isinstance(data.get("data"), dict)
                    or data.get("errors") not in (None, [])):
                raise UploadError("官方接口未返回成功业务结果；已停止，不输出原始错误正文。")
            data = data["data"]
        if path == "/decks" and (not isinstance(data.get("decks"), list)
                                 or type(data.get("total")) is not int):
            raise UploadError("官方牌组列表响应不完整，不能视为空牌库。")
        return data


def render_card(template, fields):
    content = memo.PLACEHOLDER_RE.sub(lambda match: fields[match.group(1)], template.body)
    # The API consumes the entire card, whereas XLSX contains placeholder values.
    # Translate the legacy table ans syntax to the documented * / - block form.
    def choice(match):
        answer, options = match.group(1), match.group(2).splitlines()
        if len(answer) != 1 or answer not in "ABCD"[:len(options)]:
            raise UploadError("单选答案无效；多选必须使用 choice-multi 模板。")
        return "[Choice#fixed#\n" + "\n".join(
            ("* " if index == ord(answer) - ord("A") else "- ") + line[2:]
            for index, line in enumerate(options)) + "\n]"
    content = re.sub(r"\[Choice#ans/([A-D]+)#\n((?:- [^\n]+\n)+)\]", choice, content)
    if re.search(r"\[F##|\[Choice#ans/", content) or "\n---\n" not in content:
        raise UploadError("卡片骨架不符合上传语法，请重新制卡预览。")
    return content


def local_bundle(repo, context, request, *, logical_ids=None):
    checked = memo.verify(repo, context, request)
    check = checked["request_check"]
    if check["operation"] != "no-op" or check["would_write"]:
        raise UploadError("先发布并验证同一 request 的本地 Markdown 与全部 XLSX。")
    preview = checked["preview"]
    root = memo._repository_root(repo)
    target = memo._resolve_under(root, check["target"], label="upload target", must_exist=True)
    artifact = memo._parse_artifact(target.read_text(encoding="utf-8"), check["target"])
    if artifact is None or artifact.manifest["schema"] != memo.ARTIFACT_SCHEMA:
        raise UploadError("上传只接受已核验的受管 v2 卡片文件集。")
    registry = memo.load_template_registry()
    cards = []
    for sidecar in artifact.manifest["sidecars"]:
        path = memo._resolve_under(root, sidecar["path"], label="upload workbook", must_exist=True)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != sidecar["sha256"]:
            raise UploadError("读取期间 XLSX 内容发生变化，请重新预览。")
        headers, rows = memo._parse_xlsx(payload, "upload workbook")
        template = registry.by_id[sidecar["template_id"]]
        for row, meta in zip(rows, sidecar["rows"], strict=True):
            content = render_card(template, dict(zip(headers, row, strict=True)))
            cards.append({"logical_id": meta["logical_id"], "content": content,
                          "content_sha256": digest(content)})
    selection = None
    if logical_ids is not None:
        if (not isinstance(logical_ids, (list, tuple)) or not logical_ids
                or any(not isinstance(item, str) or not memo.LOGICAL_ID_RE.fullmatch(item) for item in logical_ids)
                or len(set(logical_ids)) != len(logical_ids)):
            raise UploadError("指定卡片必须是非空、无重复的本地逻辑 ID 列表。")
        selection = sorted(logical_ids)
        if not set(selection) <= {card["logical_id"] for card in cards}:
            raise UploadError("指定卡片不属于当前文件集的可导出 active 卡片。")
        cards = [card for card in cards if card["logical_id"] in set(selection)]
    if not cards or len(cards) > MAX_BATCH:
        raise UploadError("每次上传需包含 1–200 张已核验的 active 卡片；请按明确素材范围分批。")
    if len({card["content_sha256"] for card in cards}) != len(cards):
        raise UploadError("不同逻辑卡片生成了相同内容，请先复核去重。")
    result = {"repository_id": checked["repository_id"], "target": check["target"],
            "request_sha256": check["request_sha256"],
            "artifact_set_sha256": check["artifact_set_sha256"],
            "context_sha256": checked["context_sha256"],
            "source_fingerprint": preview["source_fingerprint"],
            "template_registry_sha256": checked["template_registry_sha256"], "cards": cards}
    if selection is not None:
        result["selected_logical_ids"] = selection
    return result


def destination(client, deck_id, chapter_id):
    deck = client.request("GET", f"/decks/{identifier(deck_id)}").get("deck")
    data = client.request("GET", f"/decks/{deck_id}/chapters/{identifier(chapter_id)}", query={"with_cards": "true"})
    chapter, cards = data.get("chapter"), data.get("cards")
    if (not isinstance(deck, dict) or deck.get("id") != deck_id or deck.get("source") != "SELF"
            or deck.get("status") != "NORMAL" or type(deck.get("is_private")) is not bool):
        raise UploadError("目标必须是状态正常的自建牌组，且隐私状态可核验。")
    if (not isinstance(chapter, dict) or chapter.get("id") != chapter_id
            or chapter.get("deck_id") != deck_id or not isinstance(cards, list)
            or not isinstance(chapter.get("card_ids"), list)):
        raise UploadError("未取得目标章节和完整卡片列表。")
    card_ids = [card.get("id") for card in cards if isinstance(card, dict)]
    if (len(card_ids) != len(cards) or len(set(card_ids)) != len(cards)
            or set(card_ids) != set(chapter["card_ids"])):
        raise UploadError("章节卡片列表不完整，无法安全去重或恢复。")
    for card in cards:
        identifier(card.get("id"))
        if (card.get("deck_id") != deck_id or not isinstance(card.get("content"), str)
                or type(card.get("grammar_version")) is not int):
            raise UploadError("远端卡片缺少必要的内容或版本信息。")
    return ({key: deck.get(key) for key in ("id", "name", "creator", "is_private")},
            {key: chapter.get(key) for key in ("id", "deck_id", "name", "revision", "card_ids")}, cards)


def receipt_path(repo, target, deck, chapter):
    scope = {"repository": str(repo.resolve()), "target": target, "deck": deck, "chapter": chapter}
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return outside_git(base / "memo-cards" / (digest(scope) + ".json"))


def load_receipt(path):
    if not path.exists():
        return {"schema": STATE_SCHEMA, "cards": {}}
    try:
        value = json.loads(read_private(path))
    except (OSError, ValueError):
        raise UploadError("上传回执不可读取；请保留文件并检查，不要删除后重试。") from None
    if (not isinstance(value, dict) or value.get("schema") != STATE_SCHEMA
            or not isinstance(value.get("cards"), dict)):
        raise UploadError("上传回执结构异常，请先检查。")
    for key, item in value["cards"].items():
        if (not memo.LOGICAL_ID_RE.fullmatch(key) or not isinstance(item, dict)
                or item.get("status") not in {"pending", "created", "verified", "rejected", "updating", "updated"}
                or not isinstance(item.get("content_sha256"), str)
                or not memo.DIGEST_RE.fullmatch(item["content_sha256"])):
            raise UploadError("上传回执条目异常，请先检查。")
        if item.get("card_id") is not None:
            identifier(item["card_id"])
        if item.get("status") == "rejected" and (item.get("card_id") is not None or item.get("http_status") != 400):
            raise UploadError("已拒绝回执必须记录 HTTP 400 且没有成功创建的 ID。")
        if item.get("status") == "updating" and (
                item.get("card_id") is None or not isinstance(item.get("previous_content_sha256"), str)
                or not memo.DIGEST_RE.fullmatch(item["previous_content_sha256"])
                or type(item.get("previous_grammar_version")) is not int):
            raise UploadError("更新中的回执必须记录原卡 ID 与更新前的内容摘要。")
        if item.get("update_rejected") not in (None, 400):
            raise UploadError("被拒绝的更新只能记录 HTTP 400。")
    return value


def plan_update(card, prior, remote, matches):
    """Plan replacing a card this tool uploaded whose local content has since changed."""
    if prior.get("status") not in {"verified", "updating"} or not prior.get("card_id"):
        raise UploadError("同一逻辑卡片的上次上传尚未核验完成，且内容已改变；先核对回执与远端。")
    # An update may answer with a new card ID for the same root card, so locate the card by
    # either ID; ambiguity stops rather than guessing.
    holders = [item for item in remote if item.get("status") == "NORMAL" and (
        item["id"] == prior["card_id"] or (prior.get("root_id") and item.get("root_id") == prior["root_id"]))]
    if len(holders) != 1:
        raise UploadError("内容已改变的卡片在目标章节中找不到唯一的原卡；可能已被移动或删除，停止更新。")
    current = holders[0]
    if matches:
        if matches[0]["id"] != current["id"]:
            raise UploadError("新内容已存在于另一张远端卡片；先核对重复项，不更新。")
        # An earlier update landed but its result was not recorded; recover by read-back.
        return {**card, "operation": "skip", "card_id": current["id"], "root_id": current.get("root_id")}
    known = {(prior["content_sha256"], prior["grammar_version"])}
    if prior["status"] == "updating":
        known.add((prior["previous_content_sha256"], prior["previous_grammar_version"]))
    if (digest(current["content"]), current["grammar_version"]) not in known:
        raise UploadError("远端卡片内容与上传记录不一致，可能已被人工修改；不覆盖。")
    return {**card, "operation": "update", "card_id": current["id"], "root_id": current.get("root_id"),
            "previous_content": current["content"], "previous_grammar_version": current["grammar_version"]}


def prepare_upload(repo, context, request, deck_id, chapter_id, grammar_version, client, *, logical_ids=None):
    if type(grammar_version) is not int or grammar_version < 0:
        raise UploadError("grammar_version 必须来自当前可正常渲染的卡片，不是客户端版本。")
    bundle = local_bundle(repo, context, request, logical_ids=logical_ids)
    deck, chapter, remote = destination(client, deck_id, chapter_id)
    path = receipt_path(repo, bundle["target"], deck_id, chapter_id)
    receipt = load_receipt(path)
    actions = []
    for card in bundle["cards"]:
        prior = receipt["cards"].get(card["logical_id"])
        matches = [item for item in remote if item.get("status") == "NORMAL"
                   and item["content"] == card["content"] and item["grammar_version"] == grammar_version]
        if len(matches) > 1:
            raise UploadError("目标章节中有多张相同内容卡片，请先核对重复项。")
        if prior and prior["status"] == "rejected":
            if prior["content_sha256"] != card["content_sha256"]:
                raise UploadError("该卡片上次创建被拒绝，且内容已改变；先核对拒绝原因与远端。")
        elif prior and (prior["content_sha256"] != card["content_sha256"]
                        or prior["grammar_version"] != grammar_version or prior["status"] == "updating"):
            actions.append(plan_update(card, prior, remote, matches))
            continue
        if prior and not matches and prior.get("status") != "rejected":
            raise UploadError("已有上传记录但远端未找到唯一匹配；可能发生中断、移动或人工修改，停止重发。")
        if (prior and not matches and prior.get("status") == "rejected"
                and any(item.get("status") == "NORMAL" and digest(item["content"]) == prior["content_sha256"] for item in remote)):
            raise UploadError("先前被拒绝的内容在远端存在不同语法版本，停止重复创建。")
        if prior and prior.get("card_id") and prior["card_id"] != matches[0]["id"]:
            raise UploadError("已记录的远端卡片身份发生变化，停止自动处理。")
        actions.append({**card, "operation": "skip" if matches else "create",
                        "card_id": matches[0]["id"] if matches else None,
                        "root_id": matches[0].get("root_id") if matches else None})
    # File URLs and expire_time can change on every read. Bind the card's
    # persistent content/identity/version, not temporary media access URLs.
    remote_snapshot = sorted(
        ({key: card.get(key) for key in ("id", "deck_id", "root_id", "status", "content", "grammar_version", "revision")}
         for card in remote), key=lambda card: card["id"])
    plan = {"schema": PLAN_SCHEMA, "origin": ORIGIN, "local": {k: v for k, v in bundle.items() if k != "cards"},
            "deck": deck, "chapter": chapter, "grammar_version": grammar_version,
            "remote_sha256": digest(remote_snapshot), "receipt_sha256": digest(receipt),
            "receipt_path": str(path), "actions": actions,
            # Overwriting remote cards is riskier than appending, so it needs explicit confirmation.
            "required_authorization": "confirmed" if any(a["operation"] == "update" for a in actions) else "request"}
    plan["preview_digest"] = digest(plan)
    return plan


@contextmanager
def upload_lock(path):
    private_directory(path.parent)
    lock = path.parent / "upload.lock"
    outside_git(lock)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise UploadError("该目标正在上传或存在中断锁；先核对进程和回执，再由本人移除遗留锁。") from None
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def upload(repo, context, request, deck_id, chapter_id, grammar_version, client, preview_digest, authorization, *, logical_ids=None):
    if authorization not in {"request", "confirmed"}:
        raise UploadError("上传需要用户明确授权目标和本批内容。")
    # Compute the lock path without network access; don't allow two writers to
    # both validate an unchanged remote snapshot before obtaining the lock.
    bundle = local_bundle(repo, context, request, logical_ids=logical_ids)
    path = receipt_path(repo, bundle["target"], deck_id, chapter_id)
    with upload_lock(path):
        plan = prepare_upload(repo, context, request, deck_id, chapter_id, grammar_version, client, logical_ids=logical_ids)
        if plan["preview_digest"] != preview_digest:
            raise UploadError("来源、本地产物、目标章节或回执已变化，请重新展示上传预览。")
        if plan["required_authorization"] == "confirmed" and authorization != "confirmed":
            raise UploadError("本批包含覆盖远端卡片的更新，需要用户看过新旧内容后以 confirmed 授权。")
        receipt = load_receipt(path)
        results = []
        for action in plan["actions"]:
            logical_id = action["logical_id"]
            entry = {"content_sha256": action["content_sha256"], "grammar_version": grammar_version,
                     "status": "pending", "card_id": action["card_id"], "root_id": action["root_id"]}
            if action["operation"] == "create":
                if local_bundle(repo, context, request, logical_ids=logical_ids) != bundle:
                    raise UploadError("上传期间本地产物或来源发生变化，已停止后续创建。")
                # Durable write BEFORE POST; never retry an unknown create result.
                receipt["cards"][logical_id] = entry
                atomic_private_json(path, receipt)
                try:
                    data = client.request("POST", f"/decks/{deck_id}/chapters/{chapter_id}/cards",
                        {"deck": deck_id, "chapter": chapter_id,
                         "card": {"content": action["content"], "grammar_version": grammar_version},
                         "order": len(plan['chapter']['card_ids']) + sum(item['operation'] == 'create' for item in results)})
                except UploadError as error:
                    if error.http_status == 400:
                        entry.update(status="rejected", http_status=400)
                        atomic_private_json(path, receipt)
                    raise
                created = data.get("card")
                if not isinstance(created, dict):
                    raise UploadError("创建响应缺少卡片；已保留 pending 回执，请先核对远端。")
                entry.update(status="created", card_id=identifier(created.get("id")), root_id=created.get("root_id"))
                atomic_private_json(path, receipt)
            elif action["operation"] == "update":
                if local_bundle(repo, context, request, logical_ids=logical_ids) != bundle:
                    raise UploadError("上传期间本地产物或来源发生变化，已停止后续写入。")
                prior = receipt["cards"][logical_id]
                # Durable write BEFORE POST: keep what the remote held so recovery can tell whether
                # the update landed. An unknown result is never re-sent in the same call.
                entry.update(status="updating", previous_content_sha256=digest(action["previous_content"]),
                             previous_grammar_version=action["previous_grammar_version"])
                receipt["cards"][logical_id] = entry
                atomic_private_json(path, receipt)
                try:
                    data = client.request("POST", f"/decks/{deck_id}/cards/{action['card_id']}",
                        {"deck_id": deck_id, "card_id": action["card_id"],
                         "card": {"content": action["content"], "grammar_version": grammar_version}})
                except UploadError as error:
                    if error.http_status == 400:
                        # The remote card is unchanged; restore its record, but mark the rejection
                        # so that this preview cannot be replayed.
                        receipt["cards"][logical_id] = {**prior, "update_rejected": 400}
                        atomic_private_json(path, receipt)
                    raise
                updated = data.get("card")
                if not isinstance(updated, dict):
                    raise UploadError("更新响应缺少卡片；已保留 updating 回执，请先核对远端。")
                entry = {"content_sha256": action["content_sha256"], "grammar_version": grammar_version,
                         "status": "updated", "card_id": identifier(updated.get("id")), "root_id": updated.get("root_id")}
                receipt["cards"][logical_id] = entry
                atomic_private_json(path, receipt)
            card = client.request("GET", f"/decks/{deck_id}/cards/{identifier(entry['card_id'])}").get("card")
            if (not isinstance(card, dict) or card.get("id") != entry["card_id"] or card.get("deck_id") != deck_id
                    or card.get("status") != "NORMAL" or card.get("content") != action["content"]
                    or card.get("grammar_version") != grammar_version):
                raise UploadError("上传后读回校验不一致；保留回执并停止后续写入。")
            entry.update(status="verified", root_id=card.get("root_id"))
            receipt["cards"][logical_id] = entry
            atomic_private_json(path, receipt)
            results.append({"logical_id": logical_id, "operation": action["operation"],
                            "card_id": entry["card_id"], "root_id": entry["root_id"]})
        _deck, chapter, _cards = destination(client, deck_id, chapter_id)
        if not {item["card_id"] for item in results} <= set(chapter["card_ids"]):
            raise UploadError("最终章节归属核验失败；已保留回执，停止重发。")
        return {"verified": True, "created": sum(item["operation"] == "create" for item in results),
                "updated": sum(item["operation"] == "update" for item in results),
                "skipped": sum(item["operation"] == "skip" for item in results),
                "receipt_path": str(path), "cards": results}


def _chapter_text(value, *, maximum=4096):
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum
            or any(unicodedata.category(ch).startswith("C")
                   or unicodedata.category(ch) in {"Zl", "Zp"} for ch in value)):
        raise UploadError("章节名称或元数据必须是非空单行字符串，不能含首尾空白或控制字符。")
    return value


def chapter_names(names):
    """Local review bounds; the API does not document these as server quotas."""
    if not isinstance(names, (list, tuple)) or not 1 <= len(names) <= MAX_CHAPTER_BATCH:
        raise UploadError("本地每批需提供 1–100 个章节名称；这不是官方 API 配额。")
    values = [_chapter_text(name, maximum=MAX_CHAPTER_NAME) for name in names]
    if len(set(values)) != len(values):
        raise UploadError("章节名称不能重复；请提供明确且有序的名称列表。")
    return values


def _chapter_ids(value):
    if not isinstance(value, list):
        raise UploadError("章节或卡片 ID 列表缺失，不能当成空列表。")
    values = [identifier(item) for item in value]
    if len(set(values)) != len(values):
        raise UploadError("章节或卡片 ID 列表包含重复项，无法核验完整顺序。")
    return values


def _chapter_revision(value):
    if type(value) is not int or value < 0:
        raise UploadError("章节或牌组版本必须是非负整数。")
    return value


def _chapter_json_copy(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError):
        raise UploadError("章节元数据不是有效 JSON，已停止。") from None


def _chapter_record(value, deck_id):
    if not isinstance(value, dict) or value.get("deck_id") != deck_id:
        raise UploadError("章节缺少可核验的牌组归属。")
    identifier(value.get("id"))
    identifier(value.get("creator"))
    _chapter_text(value.get("name"))
    _chapter_revision(value.get("revision"))
    _chapter_ids(value.get("card_ids"))
    for key in ("created_time", "updated_time"):
        _chapter_text(value.get(key))
    # Retain all metadata, not just the fields needed to choose a destination.
    return _chapter_json_copy(value)


def _chapterset_record(value, deck_id):
    if not isinstance(value, dict) or value.get("deck_id") != deck_id:
        raise UploadError("章节集缺少可核验的牌组归属与完整顺序。")
    identifier(value.get("id"))
    _chapter_revision(value.get("revision"))
    _chapter_ids(value.get("chapter_ids"))
    for key in ("created_time", "updated_time"):
        _chapter_text(value.get(key))
    return _chapter_json_copy(value)


def _chapter_destination(client, deck_id):
    response = client.request("GET", f"/decks/{deck_id}")
    deck = response.get("deck") if isinstance(response, dict) else None
    if (not isinstance(deck, dict) or deck.get("id") != deck_id or deck.get("source") != "SELF"
            or deck.get("status") != "NORMAL" or type(deck.get("is_private")) is not bool):
        raise UploadError("目标必须是状态正常的自建牌组，且隐私状态可核验。")
    _chapter_text(deck.get("name"))
    identifier(deck.get("creator"))
    _chapter_revision(deck.get("revision"))
    deck = {key: deck[key] for key in ("id", "name", "creator", "source", "status", "is_private", "revision")}
    data = client.request("GET", f"/decks/{deck_id}/chapters")
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        raise UploadError("章节列表响应不完整，不能视为空牌组。")
    chapters = [_chapter_record(chapter, deck_id) for chapter in data["chapters"]]
    by_id = {chapter["id"]: chapter for chapter in chapters}
    if len(by_id) != len(chapters):
        raise UploadError("章节列表包含重复 ID，无法核验完整顺序。")
    chapterset = data.get("chapterset")
    if chapterset is None:
        if chapters:
            raise UploadError("非空章节列表缺少章节集与完整排序元数据，已停止。")
        # ListChapters permits an absent chapterset for a new empty deck.
        snapshot = {"chapterset": None, "chapters": []}
    else:
        chapterset = _chapterset_record(chapterset, deck_id)
        if set(chapterset["chapter_ids"]) != set(by_id):
            raise UploadError("章节集顺序与完整章节列表不一致，已停止。")
        snapshot = {"chapterset": chapterset,
                    "chapters": [by_id[item] for item in chapterset["chapter_ids"]]}
    return deck, snapshot


def chapter_receipt_path(repo, deck_id):
    scope = {"repository": str(Path(repo).resolve()), "deck": identifier(deck_id)}
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return outside_git(base / "memo-cards" / ("chapters-" + digest(scope) + ".json"))


def _load_chapter_receipt(path, scope):
    if not path.exists():
        return {"schema": CHAPTER_STATE_SCHEMA, "scope": scope, "chapters": {}}
    try:
        value = json.loads(read_private(path))
    except (OSError, ValueError):
        raise UploadError("章节回执不可读取；请保留文件并检查，不要删除后重试。") from None
    if (not isinstance(value, dict) or set(value) != {"schema", "scope", "chapters"}
            or value["schema"] != CHAPTER_STATE_SCHEMA or value["scope"] != scope
            or not isinstance(value["chapters"], dict)):
        raise UploadError("章节回执结构或仓库／牌组作用域不一致，已停止。")
    known_ids = set()
    for name, entry in value["chapters"].items():
        _chapter_text(name, maximum=MAX_CHAPTER_NAME)
        if (not isinstance(entry, dict) or entry.get("name") != name
                or entry.get("status") not in {"pending", "created", "verified", "rejected"}
                or "chapter_id" not in entry or type(entry.get("order")) is not int or entry["order"] < 0
                or type(entry.get("attempt")) is not int or entry["attempt"] < 0):
            raise UploadError("章节回执条目不完整或无效，已停止。")
        chapter_id = entry["chapter_id"]
        if chapter_id is not None:
            identifier(chapter_id)
            if chapter_id in known_ids:
                raise UploadError("章节回执中的远端 ID 被多个名称重复使用，已停止。")
            known_ids.add(chapter_id)
        if entry["status"] in {"created", "verified"} and chapter_id is None:
            raise UploadError("已创建或已核验的章节回执必须保留远端 ID。")
        if entry["status"] in {"pending", "rejected"} and chapter_id is not None:
            raise UploadError("未确认创建的章节回执不能携带成功创建的 ID。")
        if entry["status"] == "rejected":
            if entry.get("http_status") != 400:
                raise UploadError("已拒绝章节回执必须记录 HTTP 400。")
        elif "http_status" in entry:
            raise UploadError("只有明确拒绝的章节回执可以记录 HTTP 400。")
        if entry["attempt"] or entry["status"] != "verified":
            if entry["attempt"] < 1:
                raise UploadError("章节创建回执缺少有效尝试序号。")
            _chapter_ids(entry.get("before_chapter_ids"))
            for key in ("remote_before_sha256", "preview_digest"):
                if not isinstance(entry.get(key), str) or not memo.DIGEST_RE.fullmatch(entry[key]):
                    raise UploadError("章节创建回执缺少有效的创建前快照摘要。")
    return value


def _chapter_matches(snapshot, name):
    matches = [chapter for chapter in snapshot["chapters"] if chapter["name"] == name]
    if len(matches) > 1:
        raise UploadError("目标牌组存在多个同名章节；请先核对重复项。")
    return matches


def _validate_chapter_receipt_remote(receipt, snapshot):
    by_id = {chapter["id"]: chapter for chapter in snapshot["chapters"]}
    # Validate all recorded names for this deck, including those outside the
    # present batch. Appending another chapter must not discard unresolved work.
    for name, prior in receipt["chapters"].items():
        matches = _chapter_matches(snapshot, name)
        if prior["chapter_id"] is not None:
            found = by_id.get(prior["chapter_id"])
            if found is None:
                raise UploadError("已记录章节的远端 ID 已删除或被同名替代，停止自动重建。")
            if found["name"] != name or not matches or matches[0]["id"] != prior["chapter_id"]:
                raise UploadError("已记录章节已改名或身份发生变化，停止自动处理。")
        elif prior["status"] == "pending":
            if not matches:
                raise UploadError("章节创建结果不确定且远端没有唯一同名新章节，停止重发；请核对回执与远端。")
            if matches[0]["id"] in prior["before_chapter_ids"]:
                raise UploadError("同名章节 ID 已在上次创建前存在，不能用于恢复未知创建结果。")


def prepare_chapters(repo, deck_id, names, client):
    """Read-only, append-only chapter plan for an existing SELF deck."""
    root = memo._repository_root(Path(repo))
    deck_id, names = identifier(deck_id), chapter_names(names)
    scope = {"repository": str(root), "deck": deck_id}
    path = chapter_receipt_path(root, deck_id)
    receipt = _load_chapter_receipt(path, scope)
    deck, snapshot = _chapter_destination(client, deck_id)
    _validate_chapter_receipt_remote(receipt, snapshot)
    actions = []
    resulting_order = [{"id": chapter["id"], "name": chapter["name"]} for chapter in snapshot["chapters"]]
    positions = {chapter["id"]: index for index, chapter in enumerate(snapshot["chapters"])}
    for name in names:
        matches = _chapter_matches(snapshot, name)
        prior = receipt["chapters"].get(name)
        chapter_id = matches[0]["id"] if matches else None
        order = positions[chapter_id] if matches else len(resulting_order)
        actions.append({"name": name, "operation": "skip" if matches else "create", "chapter_id": chapter_id,
                        "order": order, "recovery": bool(prior and prior["status"] in {"pending", "created"})})
        if not matches:
            resulting_order.append({"id": None, "name": name})
    plan = {"schema": CHAPTER_PLAN_SCHEMA, "origin": ORIGIN, "repository": str(root), "deck": deck,
            "names": names, "append_only": True, "snapshot": snapshot, "resulting_order": resulting_order,
            "remote_sha256": digest(snapshot), "receipt_sha256": digest(receipt), "receipt_path": str(path),
            "actions": actions, "required_authorization": "request"}
    plan["preview_digest"] = digest(plan)
    return plan


def _assert_chapter_snapshot(client, deck_id, expected_deck, expected_snapshot):
    deck, snapshot = _chapter_destination(client, deck_id)
    if deck != expected_deck or snapshot != expected_snapshot:
        raise UploadError("章节创建期间牌组或章节列表已变化，停止后续写入；请重新预览。")
    return deck, snapshot


def _assert_chapter_append(before, after, chapter_id):
    old_ids = [chapter["id"] for chapter in before["chapters"]]
    new_ids = [chapter["id"] for chapter in after["chapters"]]
    if chapter_id in old_ids or new_ids != old_ids + [chapter_id] or after["chapters"][:-1] != before["chapters"]:
        raise UploadError("创建后的章节列表不是预期的末尾追加，或原有章节已变化；保留回执并停止。")
    previous_set, current_set = before["chapterset"], after["chapterset"]
    if current_set is None:
        raise UploadError("创建后的非空章节缺少章节集，无法核验追加位置。")
    if previous_set is not None:
        mutable = {"chapter_ids", "revision", "updated_time"}
        if ({k: v for k, v in previous_set.items() if k not in mutable}
                != {k: v for k, v in current_set.items() if k not in mutable}
                or current_set["revision"] < previous_set["revision"]):
            raise UploadError("创建后的章节集身份或版本不一致；保留回执并停止。")


def _read_back_chapter(client, deck_id, chapter_id):
    data = client.request("GET", f"/decks/{deck_id}/chapters/{identifier(chapter_id)}")
    chapter = _chapter_record(data.get("chapter") if isinstance(data, dict) else None, deck_id)
    if chapter["id"] != chapter_id:
        raise UploadError("章节独立读回的 ID 不一致；保留回执并停止。")
    return chapter


def create_chapters(repo, deck_id, names, client, preview_digest, authorization):
    """Append empty chapters, preserving uncertain writes in a private journal."""
    if authorization not in {"request", "confirmed"}:
        raise UploadError("创建章节需要用户明确授权目标牌组和名称列表。")
    if not isinstance(preview_digest, str) or not memo.DIGEST_RE.fullmatch(preview_digest):
        raise UploadError("章节预览摘要无效，请重新预览。")
    root = memo._repository_root(Path(repo))
    deck_id, names = identifier(deck_id), chapter_names(names)
    scope = {"repository": str(root), "deck": deck_id}
    path = chapter_receipt_path(root, deck_id)
    # Shares the existing upload.lock with card uploads, before any network call.
    with upload_lock(path):
        plan = prepare_chapters(root, deck_id, names, client)
        if plan["preview_digest"] != preview_digest:
            raise UploadError("章节名称顺序、牌组、章节列表或回执已变化，请重新展示章节预览。")
        receipt = _load_chapter_receipt(path, scope)
        expected_deck, expected_snapshot = plan["deck"], plan["snapshot"]
        results = []
        for action in plan["actions"]:
            name = action["name"]
            prior = receipt["chapters"].get(name)
            _assert_chapter_snapshot(client, deck_id, expected_deck, expected_snapshot)
            if digest(_load_chapter_receipt(path, scope)) != digest(receipt):
                raise UploadError("章节创建期间回执已变化，停止后续写入。")
            if action["operation"] == "create":
                order = len(expected_snapshot["chapters"])
                entry = {"name": name, "status": "pending", "chapter_id": None, "order": order,
                         "attempt": (prior["attempt"] if prior else 0) + 1,
                         "before_chapter_ids": [chapter["id"] for chapter in expected_snapshot["chapters"]],
                         "remote_before_sha256": digest(expected_snapshot), "preview_digest": preview_digest}
                receipt["chapters"][name] = entry
                atomic_private_json(path, receipt)
                try:
                    data = client.request("POST", f"/decks/{deck_id}/chapters",
                                          {"deck": deck_id, "name": name, "order": order})
                except UploadError as error:
                    if error.http_status == 400:
                        entry.update(status="rejected", http_status=400)
                        atomic_private_json(path, receipt)
                    raise
                created = data.get("chapter") if isinstance(data, dict) else None
                if not isinstance(created, dict):
                    raise UploadError("章节创建响应缺少章节；已保留 pending 回执，请先核对远端。")
                # Record an acknowledged ID before inspecting the rest of the
                # response, so recovery cannot substitute a later same-name ID.
                chapter_id = identifier(created.get("id"))
                entry.update(status="created", chapter_id=chapter_id)
                atomic_private_json(path, receipt)
                created = _chapter_record(created, deck_id)
                response_set = _chapterset_record(data.get("chapterset"), deck_id)
                if created["name"] != name or created["card_ids"]:
                    raise UploadError("创建响应的章节名称或空章节条件不一致；保留回执并停止。")
                observed = _read_back_chapter(client, deck_id, chapter_id)
                deck, snapshot = _chapter_destination(client, deck_id)
                # A successful chapter creation may advance the deck revision.
                # Its identity, name, ownership and privacy must not change.
                if ({k: v for k, v in deck.items() if k != "revision"}
                        != {k: v for k, v in expected_deck.items() if k != "revision"}
                        or deck["revision"] < expected_deck["revision"]):
                    raise UploadError("创建期间目标牌组或隐私状态已变化；保留回执并停止。")
                _assert_chapter_append(expected_snapshot, snapshot, chapter_id)
                if (observed != created or snapshot["chapters"][-1] != observed
                        or snapshot["chapterset"] != response_set):
                    raise UploadError("章节创建后的独立读回、列表或顺序校验不一致；保留回执并停止。")
                expected_deck, expected_snapshot = deck, snapshot
            else:
                chapter_id, order = action["chapter_id"], action["order"]
                observed = _read_back_chapter(client, deck_id, chapter_id)
                _assert_chapter_snapshot(client, deck_id, expected_deck, expected_snapshot)
                if observed != expected_snapshot["chapters"][order] or observed["name"] != name:
                    raise UploadError("已有章节独立读回不一致；保留回执并停止。")
                entry = dict(prior) if prior else {"attempt": 0}
                entry.update(name=name, chapter_id=chapter_id, order=order)
                entry.pop("http_status", None)
            entry["status"] = "verified"
            receipt["chapters"][name] = entry
            atomic_private_json(path, receipt)
            results.append({"name": name, "operation": action["operation"],
                            "chapter_id": chapter_id, "order": order})
        _deck, final = _assert_chapter_snapshot(client, deck_id, expected_deck, expected_snapshot)
        for result in results:
            matches = _chapter_matches(final, result["name"])
            if not matches or matches[0]["id"] != result["chapter_id"]:
                raise UploadError("最终章节成员核验不一致；保留回执，停止重发。")
        return {"verified": True, "created": sum(item["operation"] == "create" for item in results),
                "skipped": sum(item["operation"] == "skip" for item in results), "deck_id": deck_id,
                "receipt_path": str(path), "chapters": results,
                "resulting_order": [{"id": chapter["id"], "name": chapter["name"]} for chapter in final["chapters"]]}


def main(argv=None):
    parser = SafeParser(description="墨墨官方 API：本地凭据、只读预览、可恢复的卡片上传与空章节创建")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-set")
    sub.add_parser("auth-status")
    decks = sub.add_parser("decks")
    decks.add_argument("--offset", type=int, default=0)
    decks.add_argument("--limit", type=int, default=20)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--deck", required=True)
    inspect.add_argument("--chapter")
    for name in ("chapters-prepare", "chapters-create"):
        child = sub.add_parser(name)
        child.add_argument("--repo", type=Path, required=True)
        child.add_argument("--deck", required=True)
        child.add_argument("--name", action="append", required=True,
                           help="章节名称，可重复提供；新章节按此顺序追加，已有同名章节不重排")
        if name == "chapters-create":
            child.add_argument("--preview-digest", required=True)
            child.add_argument("--authorization", choices=("request", "confirmed"), required=True)
    for name in ("prepare", "upload"):
        child = sub.add_parser(name)
        child.add_argument("--repo", type=Path, required=True)
        child.add_argument("--context", type=Path, required=True)
        child.add_argument("--request", type=Path, required=True)
        child.add_argument("--deck", required=True)
        child.add_argument("--chapter", required=True)
        child.add_argument("--grammar-version", type=int, required=True)
        child.add_argument("--logical-id", action="append", help="只上传指定逻辑卡片；可重复提供，省略时使用整个已验证文件集")
        if name == "upload":
            child.add_argument("--preview-digest", required=True)
            child.add_argument("--authorization", choices=("request", "confirmed"), required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "auth-set":
            result = auth_set()
        elif args.command == "auth-status":
            # Check existence only. Never display a token, hash, prefix or suffix.
            result = {"environment_present": bool(os.environ.get(TOKEN_ENV)),
                      "private_file_present": token_path().is_file(), "network_checked": False}
        else:
            client = Client(load_token())
            if args.command == "decks":
                if args.offset < 0 or not 1 <= args.limit <= 100:
                    raise UploadError("offset 不能为负；limit 必须在 1–100 之间。")
                data = client.request("GET", "/decks", query={"offset": args.offset, "limit": args.limit})
                result = {"total": data.get("total"), "offset": args.offset,
                          "decks": [{k: d.get(k) for k in ("id", "name", "is_private", "source", "status")}
                                    for d in data.get("decks", [])]}
            elif args.command == "inspect":
                deck = identifier(args.deck)
                if args.chapter:
                    d, c, cards = destination(client, deck, identifier(args.chapter))
                    result = {"deck": d, "chapter": c, "grammar_versions": sorted({
                        card["grammar_version"] for card in cards if card.get("status") == "NORMAL"})}
                else:
                    data = client.request("GET", f"/decks/{deck}/chapters")
                    result = {"chapters": [{k: c.get(k) for k in ("id", "name", "deck_id")}
                                           for c in data.get("chapters", [])]}
            elif args.command in {"chapters-prepare", "chapters-create"}:
                arguments = (args.repo, identifier(args.deck), args.name, client)
                result = (prepare_chapters(*arguments) if args.command == "chapters-prepare" else
                          create_chapters(*arguments, args.preview_digest, args.authorization))
            else:
                arguments = (args.repo, args.context, args.request, identifier(args.deck),
                             identifier(args.chapter), args.grammar_version, client)
                result = (prepare_upload(*arguments, logical_ids=args.logical_id) if args.command == "prepare" else
                          upload(*arguments, args.preview_digest, args.authorization, logical_ids=args.logical_id))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
        return 0
    except (UploadError, memo.MemoCardsError) as exc:
        # Do not echo an arbitrary server error, request, headers, or stack trace.
        message = str(exc) if isinstance(exc, UploadError) else "本地受管卡片校验失败，请使用 memo_cards.py verify 检查。"
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=True))
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "error": "文件或接口数据异常；已停止，请保留回执检查。"}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
