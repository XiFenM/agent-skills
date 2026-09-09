#!/usr/bin/env python3
"""Upload verified memo-cards artifacts through the official Markji OpenAPI.

No token argument, arbitrary API origin, remote overwrite, or automatic POST retry.
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
TOKEN_ENV = "MAIMEMO_API_TOKEN"
TOKEN_FILE_ENV = "MAIMEMO_API_TOKEN_FILE"
MAX_BATCH = 200
MAX_RESPONSE = 16 * 1024 * 1024


class UploadError(Exception):
    """Only fixed, credential-free messages may cross the CLI boundary."""


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
        if not ((method == "GET" and re.fullmatch(get_path, path)) or
                (method == "POST" and re.fullmatch(create_path, path))):
            raise UploadError("操作不在当前已核验的官方接口范围内。")
        url = ORIGIN + BASE_PATH + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        if self._last_request is not None:
            time.sleep(max(0, 1.6 - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()
        request = urllib.request.Request(url, method=method,
            data=None if body is None else memo._canonical_bytes(body),
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
            exc.close()
            if status in (401, 403):
                raise UploadError("认证失败或没有目标权限；检查 token 与自建牌组权限。") from None
            if status == 429:
                raise UploadError("官方限流，已停止；不自动重试创建请求。") from None
            raise UploadError(f"官方接口返回 HTTP {status}，已停止；不输出响应正文或自动重试。") from None
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
            raise UploadError("请求未获得可验证的响应；创建请求的结果可能不确定，请先核对回执与远端。") from None
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
                or item.get("status") not in {"pending", "created", "verified"}
                or not isinstance(item.get("content_sha256"), str)
                or not memo.DIGEST_RE.fullmatch(item["content_sha256"])):
            raise UploadError("上传回执条目异常，请先检查。")
        if item.get("card_id") is not None:
            identifier(item["card_id"])
    return value


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
        if prior and prior["content_sha256"] != card["content_sha256"]:
            raise UploadError("同一逻辑卡片已有上传记录且内容已改变；当前追加工具不会覆盖或创建其重复版本。")
        matches = [item for item in remote if item.get("status") == "NORMAL"
                   and item["content"] == card["content"] and item["grammar_version"] == grammar_version]
        if len(matches) > 1:
            raise UploadError("目标章节中有多张相同内容卡片，请先核对重复项。")
        if prior and not matches:
            raise UploadError("已有上传记录但远端未找到唯一匹配；可能发生中断、移动或人工修改，停止重发。")
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
            "receipt_path": str(path), "actions": actions}
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
                data = client.request("POST", f"/decks/{deck_id}/chapters/{chapter_id}/cards",
                    {"deck": deck_id, "chapter": chapter_id,
                     "card": {"content": action["content"], "grammar_version": grammar_version}})
                created = data.get("card")
                if not isinstance(created, dict):
                    raise UploadError("创建响应缺少卡片；已保留 pending 回执，请先核对远端。")
                entry.update(status="created", card_id=identifier(created.get("id")), root_id=created.get("root_id"))
                atomic_private_json(path, receipt)
            card = client.request("GET", f"/decks/{deck_id}/cards/{identifier(entry['card_id'])}").get("card")
            if (not isinstance(card, dict) or card.get("id") != entry["card_id"] or card.get("deck_id") != deck_id
                    or card.get("status") != "NORMAL" or card.get("content") != action["content"]
                    or card.get("grammar_version") != grammar_version):
                raise UploadError("上传后读回校验不一致；保留回执并停止后续创建。")
            entry.update(status="verified", root_id=card.get("root_id"))
            receipt["cards"][logical_id] = entry
            atomic_private_json(path, receipt)
            results.append({"logical_id": logical_id, "operation": action["operation"],
                            "card_id": entry["card_id"], "root_id": entry["root_id"]})
        _deck, chapter, _cards = destination(client, deck_id, chapter_id)
        if not {item["card_id"] for item in results} <= set(chapter["card_ids"]):
            raise UploadError("最终章节归属核验失败；已保留回执，停止重发。")
        return {"verified": True, "created": sum(item["operation"] == "create" for item in results),
                "skipped": sum(item["operation"] == "skip" for item in results),
                "receipt_path": str(path), "cards": results}


def main(argv=None):
    parser = SafeParser(description="墨墨官方 API：本地凭据、只读预览和可恢复的卡片追加")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-set")
    sub.add_parser("auth-status")
    decks = sub.add_parser("decks")
    decks.add_argument("--offset", type=int, default=0)
    decks.add_argument("--limit", type=int, default=20)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--deck", required=True)
    inspect.add_argument("--chapter")
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
