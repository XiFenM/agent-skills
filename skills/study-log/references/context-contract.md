# Consumer context contract

当消费仓库使用统一 version 2 配置、需要选择结构化学习记录目标或解释
`.agent-skills-context.json` 时读取本参考。它不改变 `study_log.py` 的 CLI、raw archive 或 JSON envelope
schema。

## 公共配置

消费索引 `.agent-skills.json` 的 `config.skills.study-log` 指向一份 Git-tracked 公共配置：

```json
{
  "schema": "agent-skills.study-log/v1",
  "skill": "study-log",
  "structured_targets": [
    {"id": "systems-log", "path": "systems/log"}
  ]
}
```

根对象只允许 `schema`、`skill` 和非空 `structured_targets`。每个 target 只允许唯一的 lowercase-hyphen
`id` 与 portable 仓库相对目录 `path`；绝对路径、盘符、反斜线、逃逸、glob、Windows 不安全组件以及
相同或嵌套 target root 均拒绝。

公共配置不得保存 raw archive root、私有会话目录、source、session、boundary、scratch、output、命令、
privacy 决定或 approval。Raw 私有根继续只来自当次 `--output`／`--archive-root`、
`STUDY_LOG_ARCHIVE_ROOT` 或操作系统用户级配置。

## Materialized context

纯 validator 把每个 target 规范化为：

```json
{
  "id": "systems-log",
  "record_type": "structured-study-log",
  "path": "systems/log",
  "format": "markdown",
  "include_patterns": ["*.md"],
  "filename_policy": "yyyy-mm-dd-topic"
}
```

它返回共享 materializer 要求的四个字段：`context`、`tracked_files`、`tracked_collections`、
`write_paths`。前两项 read allowlist 固定为空；`write_paths` 只列 target roots。因此新目录或空目录可以
配置，materializer 不扫描目标 collection，也不会把其中的 tracked 或未跟踪文件隐式暴露给 Skill。

生成 wrapper 的 `sources.repository` 与 `sources.skill` 只绑定公共配置文件及 digest，不是对话 source。
对话 source、消息 boundary、临时 extract output 与 raw target 仍须由每次 CLI 调用显式给出。

## 授权与消费

静态 `write_paths` 表示消费环境允许考虑的结构化输出范围，不是当次写授权。用户本轮请求仍须选择一个
精确目标；已有文件必须先读取精确目标、展示 diff 并取得 overwrite 确认。不要因为 target root 已配置
就遍历目录、批量更新记录或自动在 Session 结束时写入。

其他 Skill 若要消费同一结构化 collection，必须在自己的公共配置中独立声明读取范围。`study-log`
context 不向 `memo-cards`、`english-coach` 或其他 Skill 传递权限；`[要点]`、`[纠错]` 与 `[遗留]` 的
消费语义继续由中央格式契约决定。

没有 materialized context 时，保持安全降级：可以按用户本轮选择发现、预览和临时提取会话，并在聊天中
形成 structured candidate；默认零仓库写且不猜路径。用户明确给出精确目标时，该指令是一次性授权，
不会被保存成静态配置。
