# Extraction and archive contract

需要运行 `scripts/study_log.py`、解释 JSON 结果或处理安全失败时读取本参考。CLI 是 Agent 的内部工具；不要让用户记忆命令。

## 目录

1. [共同约束](#共同约束)
2. [命令契约](#命令契约)
3. [选择边界](#选择边界)
4. [完整性与写入](#完整性与写入)
5. [隐私决策](#隐私决策)
6. [Raw 生命周期](#raw-生命周期)
7. [JSON 与错误码](#json-与错误码)

## 共同约束

统一入口：

```text
python <skill-dir>/scripts/study_log.py <command> ...
```

- 所有会话命令都显式提供规范化 `--project`，不从脚本当前目录推断项目。
- `--provider auto` 同时发现 Claude Code 和 Codex；也可以限制为 `claude` 或 `codex`。
- `--session` 接受稳定 ID 或无歧义前缀；跨 provider 重名时使用 `provider:id`。`--source` 直接指定 JSONL。两者互斥。
- 发现只接受与 `--project` 精确匹配的根会话，排除 subagent、sidechain、fork 和 compact summary。
- 自动发现默认读取客户端的用户级会话目录；测试时可以分别用 `STUDY_LOG_CODEX_SESSIONS_DIR` 与 `STUDY_LOG_CLAUDE_PROJECTS_DIR` 指向合成数据。

## 命令契约

### `list`

```text
study_log.py list --project <absolute-project> [--provider auto|codex|claude] [--date YYYY-MM-DD]
```

返回根会话候选、source SHA-256、稳定 session ID、首末时间、消息数和已遮盖敏感值的首条用户预览。

### `preview`

```text
study_log.py preview --project <project> (--session <id> | --source <jsonl>)
```

返回稳定 message ID、边界预览、role／phase、隐私风险类别和 source SHA-256。预览永远遮盖检测到的凭据与个人标识值；完整文本只在后续受控输出中出现。

### `extract`

```text
study_log.py extract --project <project> (--session <id> | --source <jsonl>) \
  --source-sha256 <reviewed-hash> [boundary options] [--include-tools] [--output <absolute-scratch>]
```

- 只生成供 `structured` 蒸馏使用的临时 Markdown，不直接生成结构化成品。
- 未给 `--output` 时在操作系统临时目录创建文件；返回 `cleanup_required: true`，调用者用完后删除。
- 显式输出必须是绝对路径且位于项目与其他 Git 工作树之外。
- 最多忽略一个在 UTF-8 多字节或 JSON 语法中被截断的最终非空 JSONL 行，并返回 `truncated_tail_ignored`；中间坏行严格失败。可成功解析但不是 object 的 JSON 值不是截断记录，在任何位置都以 `malformed` 停止。
- `--include-tools` 只生成简短工具摘要，仍不包含工具结果或 reasoning。

### `archive`

```text
study_log.py archive --project <project> (--session <id> | --source <jsonl>) \
  --source-sha256 <reviewed-hash> --start-id <id> --end-id <id> \
  --title <title> --status partial|final --privacy-confirmed \
  [--archive-root <absolute-root> | --output <absolute-target>] \
  [--credential-action block|redact|allow] [--redact-personal] \
  [--proprietary-confirmed] [--allow-repo-output]
```

更新 partial 时增加：

```text
--archive-id <stable-id> --target-sha256 <reviewed-target-hash>
```

不指定 `--output` 的更新会在选定 private root 中按 `archive_id` 定位原文件。Raw 始终严格解析 JSONL；任何坏行都失败且原目标不变。

### `config archive-root`

```text
study_log.py config archive-root get
study_log.py config archive-root set <absolute-private-directory>
```

配置保存在操作系统用户级配置目录，不写入消费仓库。root 解析顺序：单次 `--output`／`--archive-root`、`STUDY_LOG_ARCHIVE_ROOT`、用户级配置；都缺失时以 `safety` 停止。

自动布局为：

```text
<private-root>/<project-name>-<project-path-hash>/<year>/<date>-<title>-<archive-id>.md
```

状态只写入元数据，不写入文件名。

## 选择边界

- 首选 `--start-id` 与 `--end-id`，两端都包含。
- `--start-user` 包含匹配到的用户消息；`--end-before-user` 排除匹配消息。文本片段匹配多个用户消息时返回 `ambiguous`，不得选择第一项。
- `--start-time` 包含，`--end-time` 排除；可与日期或语义区间相交。
- `--date` 按消息时间戳切片。
- `--final-only` 会排除 assistant commentary，并成为 normalization 身份的一部分。Raw 通常不要使用，以免丢失可见过程。

消息 ID 绑定 provider、session、源位置、role、timestamp、phase 和规范化文本。追加会话记录不会改变已有消息 ID；改写文本或只改变 commentary／final phase 都会改变对应 ID，并由 source SHA-256 前置条件再次拦截。

## 完整性与写入

- `extract` 与 `archive` 必须携带 `preview` 返回的 source SHA-256。脚本在读取后及写入前再次检查。
- 更新 raw 必须携带已展示 diff 时审阅的 target SHA-256；目标变化、消失或出现均安全拒绝。
- 写入使用目标同目录临时文件、落盘同步和原子替换；失败时清理临时文件。
- archive root 与目标都解析真实路径并检查 containment；符号链接或 Windows junction 不得把目标引出 root。
- raw 默认拒绝项目或任何 Git 工作树内路径。明确允许仓库内输出时，脚本仍要求目标未跟踪且已经被 Git ignore；不会代改 `.gitignore`。

## 隐私决策

`preview` 只返回类别和计数，不返回命中的秘密值。检测采用可审计的高置信规则集，目的是拦住常见且明确的风险，不是穷尽式敏感信息扫描；没有命中不代表内容不含凭据、个人信息或专有内容，raw 写入前仍需人工完成隐私与所有权检查。

- `credential`：私钥、常见平台令牌和明确赋值的 password／secret／token／API key。默认 `block`；经用户明确选择后可 `redact` 或 `allow` 原样私存。
- `proprietary`：专有标记、内部 host／API 和代码块等需要判断所有权的内容。写入要求 `--proprietary-confirmed`；所有权或适用政策不清楚时不要传入该确认。
- `personal`：电子邮箱、电话号码等。向用户警告；可以用 `--redact-personal` 应用可复现脱敏。

脱敏元数据记录固定策略版本、类别、规则名和替换数。正文使用稳定的 `[REDACTED:<category>:<rule>:<ordinal>]` 标记，不保存秘密摘要，也不手工改写句子。

## Raw 生命周期

- 新建时生成稳定 `archive_id`。每个 provider／project／session／start boundary 至多存在一个 partial；改变 normalization 或脱敏类别也不能绕过这个限制。
- 刷新或终结前，读取当前 archive，在新 preview 中定位原结束消息，向用户展示新增消息 ID 范围、消息数、结束边界与状态变化。只有用户确认这份 diff 后才传入 `archive_id` 和当时目标 SHA-256。
- partial 更新必须保持 archive ID、provider、project fingerprint、source session、起点、normalization，以及脱敏策略版本和类别不变。脚本用旧 `message_count` 与 `visible_content_sha256` 验证当前规范化、脱敏后的消息到旧终点为完整前缀，任何历史改写、插入或删除都拒绝。
- `partial → partial` 必须严格推进结束消息；同一结束消息的刷新拒绝且不写入。`partial → final` 可以在结束消息不变时发生，是一次带 target SHA-256 的原子更新。final 不允许再更新。
- 同 provider／project／session／起止消息／normalization／脱敏身份的 final 只能存在一份。不同终点或不同清洗身份可以创建新的 archive ID。
- 改变起点、normalization 或脱敏身份时新建 archive ID。

## JSON 与错误码

成功：

```json
{"schema_version":1,"ok":true,"command":"preview","data":{},"warnings":[]}
```

失败：

```json
{"schema_version":1,"ok":false,"command":"archive","error":{"code":"safety","message":"...","details":{}}}
```

| 退出码 | `error.code` | 含义 |
| ---: | --- | --- |
| 0 | — | 成功 |
| 2 | `usage` | 参数或调用契约错误 |
| 3 | `not_found` | 会话、消息或 archive 不存在 |
| 4 | `ambiguous` | session 或文本边界不唯一 |
| 5 | `integrity` | source 前置哈希或 I/O 完整性失败 |
| 6 | `safety` | 隐私、路径、项目、Git 或会话类型被安全策略拒绝 |
| 7 | `conflict` | target 前置哈希、目标竞态、生命周期或 archive 身份冲突 |
| 8 | `malformed` | JSONL、配置或 archive 元数据损坏 |
