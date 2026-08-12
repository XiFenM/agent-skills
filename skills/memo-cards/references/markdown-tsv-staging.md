# Markdown 与 TSV 暂存合同

## Context 配置

运行时只消费 materializer 生成的 `.agent-skills-context.json`。消费配置 schema 为 `agent-skills.memo-cards/v1`，声明：

- `adapter`：固定 `markji`、客户端版本与 profile；
- `input_collections`：带 kind 和安全相对路径 pattern 的允许来源；
- `output_collections`：允许目标 pattern、inventory pattern，以及可选软目标。

输入 pattern 精确指向一个 `.md` 文件时，materializer 只把该文件加入 `tracked_files`；带通配符的输入与
inventory 才保存显式 collection 根目录，并把目录中当次 Git tracked 的普通文件展开为 `tracked_files`。
pattern 本身留在受管 context 中做更窄匹配；来源必须同时命中输入 pattern 和 concrete `tracked_files`，
inventory 也只在 concrete 文件中筛选，绝不重新 glob 文件系统。新增但尚未 tracked／重新 materialize 的
目标仍可由当次明确请求创建或直接刷新，但不参与跨文件 inventory。

静态配置只描述环境事实，不能关闭质量门槛、注入模板／prompt，或预先授权保存、覆盖、导入、提交和推送。中央核心没有消费仓库路径和数量上限。

## Request

Agent 把语义判断写入 UTF-8 JSON，schema 为 `memo-cards.request/v1`：

```json
{
  "schema": "memo-cards.request/v1",
  "output_collection": "review-cards",
  "target": "learning/cards/topic.md",
  "selection": "selected",
  "sources": [
    {
      "id": "source-note",
      "collection": "verified-notes",
      "path": "learning/notes/topic.md",
      "sha256": "<lowercase sha256>",
      "summary": "核验后的主题笔记"
    }
  ],
  "cards": [
    {
      "key": "core-concept",
      "rank": 1,
      "domain": "distributed-systems",
      "recall_target": "解释一个稳定机制及其边界",
      "assessment": "mechanism",
      "layer": "mechanism",
      "fact_scope": {"kind": "evergreen"},
      "quality": "A",
      "fact_status": "verified",
      "lifecycle": "active",
      "priority": 5,
      "template_id": "technical-qa",
      "fields": {
        "问题": "……",
        "答案": "……",
        "锚点": "……",
        "来源": "……"
      },
      "source_ids": ["source-note"],
      "content_summary": "机制与适用边界",
      "depends_on": []
    }
  ]
}
```

`selection=selected` 应用消费环境软目标，但永不截断 A 卡；`complete` 纳入全部合格 A／B 卡。`rank` 表示 Agent 已完成的语义排序，数值越小越优先。

事实范围只允许 `{"kind":"evergreen"}`，或至少提供 product 且带 version／commit 之一的 `snapshot`。原子卡不得声明依赖。机制卡若使用 `depends_on`，只能引用同 request 内 eligible、已核验且 active 的 A／B 原子／机制子卡；综合口述卡必须按相同门槛引用 2–5 张子卡。工具拒绝未知、自依赖、逻辑别名自依赖与依赖环，并把逐依赖内容 SHA-256 写入 manifest。

依赖漂移会先把机制卡／综合口述卡持久置为 `review`；继续提交原来的 `lifecycle=active` request 不会自动恢复，也不会产生重复写入。完成复核后，在要恢复的卡片上显式增加：

```json
"review_resolution": {
  "summary": "已依据更新后的前置卡复核机制、边界与口述评分锚点"
}
```

该字段只用于 `review → active`，必须描述本轮实际复核；不能在发现新依赖漂移的同一次预览中顺带解除。工具把摘要写入 manifest 和 preview，并强制 `confirmed` 授权。已发布的 resolution 会在后续等价 request 中保留，避免元数据抖动；新的依赖漂移会使旧 resolution 失效并重新进入 `review`。

## 字段值与受控内容

普通字段使用单行字符串。需要公式、公共链接或用户明确提供的既有 Markji ID 时，`content` 字段可以使用结构化 parts：

```json
{
  "parts": [
    {"type": "text", "text": "复杂度为 "},
    {"type": "formula", "katex": "O(n\\log n)"},
    {"type": "link", "url": "https://example.org/reference", "label": "来源"}
  ]
}
```

可用 part 为 `text`、`formula`、`link`、`audio`、`image` 和 `card-ref`。媒体与卡片引用只能携带用户已经提供的 ID。不要传入现成 Markji 语法。

## 工具调用

```text
python scripts/memo_cards.py prepare --repo <repo> --context <context> --request <request.json>
python scripts/memo_cards.py publish --repo <repo> --context <context> --request <request.json> --preview-digest <digest> --authorization request|confirmed
python scripts/memo_cards.py verify  --repo <repo> --context <context> --request <request.json>
```

命令输出稳定、ASCII-safe 的 JSON envelope；JSON 解码后仍保留完整 Unicode，不依赖 Windows 终端是否为 GBK。`prepare` 不写仓库；`publish` 只写 request 指定且 context 允许的单一目标。发布后的 `verify` 必须复用同一 request；其 `request_check` 给出 request digest、目标、操作、`would_write` 与 preview digest，`operation=no-op` 且 `would_write=false` 表示无需再次写入；完整复核细节保留在 `preview`。顶层 `managed_artifacts` 仍只来自 materializer 展开的 tracked inventory，因此尚未重新 materialize 的新目标可能只出现在 request 复核结果中；这不是漏检。省略 `--request` 只做 inventory 审计，不构成发布后目标复核。Markdown 正文按使用到的模板分块，每块给出可复制模板和一个带表头的 TSV code block；它是供粘贴进 Markji 下载表格的暂存文档，不是可直接上传的 TSV 文件。
