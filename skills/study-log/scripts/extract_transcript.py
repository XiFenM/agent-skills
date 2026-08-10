#!/usr/bin/env python3
"""提取 Claude Code / Codex 会话记录（JSONL）为可读的对话 Markdown。

用法：
  extract_transcript.py list --provider auto
  extract_transcript.py extract --latest --provider codex
  extract_transcript.py extract --session d88c65bd --provider claude
  extract_transcript.py extract --latest --date 2026-07-03
  extract_transcript.py extract --latest --tools -o /tmp/dump.md

只保留根会话主链上的 user/assistant 文本；自动剔除 thinking、工具结果、
subagent 侧链、压缩摘要与 harness 注入。--tools 时以单行标注工具调用。
"""
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


COMMON_STRIP_PATTERNS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.S),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.S),
    re.compile(r"<command-message>.*?</command-message>", re.S),
    re.compile(r"<command-args>.*?</command-args>", re.S),
    re.compile(r"<ide_selection>.*?</ide_selection>", re.S),
]
CODEX_STRIP_PATTERNS = [
    re.compile(r"<recommended_plugins>.*?</recommended_plugins>", re.S),
    re.compile(r"<environment_context>.*?</environment_context>", re.S),
    re.compile(
        r"# AGENTS\.md instructions for .*?<INSTRUCTIONS>.*?</INSTRUCTIONS>",
        re.S,
    ),
]
CODEX_INJECTED_PREFIXES = (
    "<recommended_plugins>",
    "# AGENTS.md instructions for ",
    "<environment_context>",
)
COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
PROVIDER_LABELS = {"claude": "Claude Code", "codex": "Codex"}


@dataclass(frozen=True)
class SessionRef:
    provider: str
    path: Path
    session_id: str


def claude_project_dir(cwd: str) -> Path:
    slug = "-" + cwd.strip("/").replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / slug


def codex_sessions_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def iter_records(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def first_session_meta(path: Path) -> dict:
    for rec in iter_records(path):
        if rec.get("type") == "session_meta":
            payload = rec.get("payload")
            return payload if isinstance(payload, dict) else {}
    return {}


def is_codex_root_session(meta: dict) -> bool:
    if meta.get("agent_path") or meta.get("parent_thread_id") or meta.get("forked_from_id"):
        return False
    source = meta.get("source")
    return not (isinstance(source, dict) and source.get("subagent"))


def claude_sessions(project: str) -> list[SessionRef]:
    pdir = claude_project_dir(project)
    if not pdir.is_dir():
        return []
    return [SessionRef("claude", path, path.stem) for path in pdir.glob("*.jsonl")]


def codex_sessions(project: str) -> list[SessionRef]:
    sessions_root = codex_sessions_dir()
    if not sessions_root.is_dir():
        return []

    sessions = []
    for path in sessions_root.glob("*/*/*/rollout-*.jsonl"):
        meta = first_session_meta(path)
        if meta.get("cwd") != project or not is_codex_root_session(meta):
            continue
        session_id = meta.get("id") or meta.get("session_id")
        if session_id:
            sessions.append(SessionRef("codex", path, str(session_id)))
    return sessions


def safe_mtime(session: SessionRef) -> float:
    try:
        return session.path.stat().st_mtime
    except OSError:
        return 0.0


def discover_sessions(provider: str, project: str) -> list[SessionRef]:
    sessions = []
    if provider in ("auto", "claude"):
        sessions.extend(claude_sessions(project))
    if provider in ("auto", "codex"):
        sessions.extend(codex_sessions(project))
    return sorted(sessions, key=safe_mtime, reverse=True)


def no_sessions_message(provider: str, project: str) -> str:
    checked = []
    if provider in ("auto", "claude"):
        checked.append(f"Claude Code：{claude_project_dir(project)}")
    if provider in ("auto", "codex"):
        checked.append(f"Codex：{codex_sessions_dir()}（仅 cwd 精确匹配的根会话）")
    locations = "\n".join(f"  - {item}" for item in checked)
    return (
        f"未找到 provider={provider}、项目 cwd={project} 的可用会话。\n"
        f"已检查：\n{locations}\n"
        "可尝试显式指定 --provider claude|codex 或用 --project 传入会话记录中的精确 cwd。\n"
        "若客户端没有本地记录，请从当前上下文整理，或让用户粘贴/导出目标对话；不要凭空补全。"
    )


def clean_common_text(text: str) -> str:
    for pat in COMMON_STRIP_PATTERNS:
        text = pat.sub("", text)
    match = COMMAND_NAME_RE.search(text)
    if match:
        text = COMMAND_NAME_RE.sub("", text)
        command = match.group(1).strip()
        rest = text.strip()
        text = f"> ⌨️ 命令：{command}" + (f"\n\n{rest}" if rest else "")
    return text.strip()


def clean_codex_text(text: str) -> str:
    for pat in CODEX_STRIP_PATTERNS:
        text = pat.sub("", text)
    text = text.strip()
    if text.startswith(CODEX_INJECTED_PREFIXES):
        return ""
    return clean_common_text(text)


def brief_input(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value.replace("\n", " ")[:80]
    if isinstance(value, dict):
        for key in (
            "file_path",
            "path",
            "description",
            "skill",
            "pattern",
            "query",
            "command",
            "cmd",
        ):
            if key in value:
                return str(value[key]).replace("\n", " ")[:80]
    return ""


def claude_tool_brief(block: dict) -> str:
    name = block.get("name", "?")
    detail = brief_input(block.get("input") or {})
    return f"{name}({detail})" if detail else name


def codex_tool_brief(payload: dict) -> str:
    name = payload.get("name") or payload.get("namespace") or "?"
    detail = brief_input(payload.get("input") or payload.get("arguments") or {})
    return f"{name}({detail})" if detail else str(name)


def claude_message_text(rec: dict, include_tools: bool) -> str:
    msg = rec.get("message") or {}
    content = msg.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(block.get("text", ""))
            elif block_type == "tool_use" and include_tools:
                parts.append(f"> 🔧 {claude_tool_brief(block)}")
            # thinking / tool_result / image 一律跳过
    return clean_common_text("\n\n".join(part for part in parts if part and part.strip()))


def codex_message_text(payload: dict) -> str:
    content = payload.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("input_text", "output_text", "text"):
                parts.append(block.get("text", ""))
    return clean_codex_text("\n\n".join(part for part in parts if part and part.strip()))


def iter_claude_dialogue(session: SessionRef, include_tools: bool):
    for rec in iter_records(session.path):
        role = rec.get("type")
        if role not in ("user", "assistant"):
            continue
        if rec.get("isSidechain") or rec.get("isMeta") or rec.get("isCompactSummary"):
            continue
        text = claude_message_text(rec, include_tools)
        if text:
            yield rec.get("timestamp") or "", role, text


def iter_codex_dialogue(session: SessionRef, include_tools: bool):
    for rec in iter_records(session.path):
        if rec.get("type") != "response_item":
            continue
        payload = rec.get("payload") or {}
        payload_type = payload.get("type")
        timestamp = rec.get("timestamp") or ""

        if payload_type == "message" and payload.get("role") in ("user", "assistant"):
            text = codex_message_text(payload)
            if text:
                yield timestamp, payload.get("role"), text
        elif include_tools and payload_type in ("function_call", "custom_tool_call"):
            yield timestamp, "tool", f"> 🔧 {codex_tool_brief(payload)}"


def iter_dialogue(session: SessionRef, include_tools: bool = False):
    if session.provider == "claude":
        yield from iter_claude_dialogue(session, include_tools)
    else:
        yield from iter_codex_dialogue(session, include_tools)


def first_user_snippet(session: SessionRef) -> str:
    for _timestamp, role, text in iter_dialogue(session):
        if role == "user" and not text.startswith("> ⌨️"):
            return text.replace("\n", " ")[:60]
    return "(无用户消息)"


def time_range(session: SessionRef):
    first = last = None
    for rec in iter_records(session.path):
        timestamp = rec.get("timestamp")
        if timestamp:
            first = first or timestamp
            last = timestamp
    return first, last


def format_time(timestamp: str | None) -> str:
    return (timestamp or "?")[:16].replace("T", " ")


def cmd_list(sessions: list[SessionRef]):
    print(f"{'来源':<12} {'SESSION':<10} {'开始':<17} {'结束':<17} {'大小':>7}  首条用户消息")
    for session in sessions:
        first, last = time_range(session)
        try:
            size_kb = session.path.stat().st_size // 1024
        except OSError:
            size_kb = 0
        provider = PROVIDER_LABELS[session.provider]
        print(
            f"{provider:<12} {session.session_id[:8]:<10} "
            f"{format_time(first):<17} {format_time(last):<17} "
            f"{size_kb:>6}K  {first_user_snippet(session)}"
        )


def select_session(sessions: list[SessionRef], prefix: str | None) -> SessionRef:
    if not prefix:
        return sessions[0]

    matches = [session for session in sessions if session.session_id.startswith(prefix)]
    if not matches:
        sys.exit(f"没有 ID 以 {prefix} 开头的会话；请先运行 list 查看候选。")
    if len(matches) > 1:
        candidates = []
        for session in matches:
            first, _last = time_range(session)
            candidates.append(
                f"  - {session.provider}:{session.session_id}（{format_time(first)}）"
            )
        sys.exit(
            f"会话前缀 {prefix} 匹配到 {len(matches)} 个候选，请使用更长前缀：\n"
            + "\n".join(candidates)
        )
    return matches[0]


def cmd_extract(sessions: list[SessionRef], args):
    target = select_session(sessions, args.session)
    provider = PROVIDER_LABELS[target.provider]
    out_lines = [f"# 会话提取 · {target.provider}:{target.session_id[:8]}", ""]
    first, last = time_range(target)
    out_lines.append(
        f"> 来源：{provider} · 时间范围：{first} → {last}"
        + (f" · 仅保留 {args.date}" if args.date else "")
    )
    out_lines.append("")

    n_msgs = 0
    role_names = {"user": "用户", "assistant": "AI", "tool": "工具"}
    for timestamp, role, message in iter_dialogue(target, include_tools=args.tools):
        if args.date and not timestamp.startswith(args.date):
            continue
        out_lines += [f"## [{timestamp[11:16]}] {role_names[role]}", "", message, ""]
        n_msgs += 1

    result = "\n".join(out_lines)
    if args.output:
        output = Path(args.output).expanduser()
        output.write_text(result, encoding="utf-8")
        print(f"已写入 {output}（{n_msgs} 条消息，{len(result) // 1024}K 字符）")
    else:
        print(result)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=["list", "extract"])
    parser.add_argument(
        "--provider",
        choices=["auto", "claude", "codex"],
        default="auto",
        help="会话来源；auto 同时检查 Claude Code 与 Codex（默认）",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--session", help="session id 前缀")
    target.add_argument("--latest", action="store_true", help="取最近会话（extract 默认行为）")
    parser.add_argument("--date", help="只保留该日期（YYYY-MM-DD）的消息")
    parser.add_argument("--tools", action="store_true", help="以单行标注工具调用")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印 stdout）")
    parser.add_argument("--project", help="项目根目录（默认当前目录）", default=os.getcwd())
    args = parser.parse_args()

    project = str(Path(args.project).expanduser().resolve())
    sessions = discover_sessions(args.provider, project)
    if not sessions:
        sys.exit(no_sessions_message(args.provider, project))

    if args.mode == "list":
        cmd_list(sessions)
    else:
        cmd_extract(sessions, args)


if __name__ == "__main__":
    main()
