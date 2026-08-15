# 受管 Markdown 与 XLSX 合同

## 产物形态

一次 request 仍以一个安全的 `.md` 路径作为主目标。工具由这个目标和实际使用到的模板确定性派生同目录
XLSX，例如：

```text
learning/cards/topic.md
learning/cards/topic-correction.xlsx
learning/cards/topic-technical-qa.xlsx
```

Markdown frontmatter 保存受管 manifest，正文只保留模板定义、卡片数量与 XLSX 链接，不复制卡片数据，
也不包含 TSV。每个有 active 卡片的模板恰好对应一个 XLSX；`review` 与 `archived` 卡不导出。每个工作簿
只有首个且唯一的 `cards` sheet，第一行严格使用 registry 字段顺序，后续每行一张卡。用户在 Markji 选择
相应模板后分别上传这些 XLSX；本 Skill 不上传或导入。

## Context 配置

运行时只消费 materializer 生成的 `.agent-skills-context.json`。消费配置 schema 继续为
`agent-skills.memo-cards/v1`，声明：

- `adapter`：固定 `markji`、客户端版本与 profile；
- `input_collections`：带 kind 和安全相对路径 pattern 的允许来源；
- `output_collections`：允许 Markdown 主目标 pattern、inventory pattern，以及可选软目标。

XLSX 路径不由 request 或配置自由指定。工具只可在主目标同目录按
`<markdown-stem>-<template-id>.xlsx` 派生，因此仍受同一 output collection 的 write ceiling 约束。

输入 pattern 精确指向一个 `.md` 文件时，materializer 只把该文件加入 `tracked_files`；带通配符的输入与
inventory 保存显式 collection 根目录，并把目录中当次 Git tracked 的普通文件展开为 `tracked_files`。
collection 可以包含 XLSX 等二进制受管 sidecar；materializer 不把 collection member 当作文本读取，实际
消费方仍须严格验证其格式。来源必须同时命中输入 pattern 和 concrete `tracked_files`，inventory 只在
concrete 文件中筛选 Markdown 主产物，绝不重新 glob 文件系统。

若一个精确文章输入由另一个已配置 Skill 生成，可在 input record 中声明唯一 `producer`。它只允许
`kind: article` 且所有 pattern 都是精确 `.md` 文件；materializer 还会核对 producer 已配置、不是当前
Skill，且该文件位于 producer 的 write ceiling 内。该声明不授予起草、覆盖、发布、提交或推送权限。

## Request

Agent 把语义判断写入 UTF-8 JSON，schema 保持 `memo-cards.request/v1`：
每个 `sources[].path` 本身也必须是已跟踪、哈希匹配的 UTF-8 文本；collection 对 XLSX 的二进制例外不
会放宽来源事实边界。

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

`selection=selected` 应用消费环境软目标，但永不截断 A 卡；`complete` 纳入全部合格 A／B 卡。`rank` 表示
Agent 已完成的语义排序，数值越小越优先。

事实范围只允许 `{"kind":"evergreen"}`，或至少提供 product 且带 version／commit 之一的 `snapshot`。
原子卡不得声明依赖。机制卡若使用 `depends_on`，只能引用同 request 内 eligible、已核验且 active 的
A／B 原子／机制子卡；综合口述卡必须按相同门槛引用 2–5 张子卡。工具拒绝未知、自依赖、逻辑别名
自依赖与依赖环，并把逐依赖内容 SHA-256 写入 manifest。

依赖漂移会先把机制卡／综合口述卡持久置为 `review`。完成复核后，在要恢复的卡片上显式增加：

```json
"review_resolution": {
  "summary": "已依据更新后的前置卡复核机制、边界与口述评分锚点"
}
```

该字段只用于 `review → active`，不能在发现新依赖漂移的同一次预览中顺带解除。工具把摘要写入
manifest 和 preview，并强制 `confirmed` 授权。

## 字段值与工作簿

普通短字段使用单行字符串。占位符精确独占模板一行的 `content` 字段，在需要公式、公共链接或用户
明确提供的既有 Markji ID 时可以使用结构化 `parts`：

```json
{
  "parts": [
    {"type": "text", "text": "需要展开推导时参见 "},
    {"type": "link", "url": "https://example.org/reference", "label": "来源"}
  ]
}
```

复杂答案改用与 `parts` 二选一的 `blocks`，形成受控的结论／要点／边界层级：

```json
{
  "blocks": [
    {
      "type": "lead",
      "parts": [{"type": "text", "text": "先直接回答问题的结论"}]
    },
    {
      "type": "point",
      "label": "机制",
      "parts": [{"type": "text", "text": "只保留支持结论的必要步骤"}]
    },
    {
      "type": "display",
      "parts": [{"type": "formula", "katex": "O(n\\log n)"}]
    },
    {
      "type": "boundary",
      "parts": [{"type": "text", "text": "说明适用条件或失效边界"}]
    }
  ]
}
```

`blocks` 推荐包含 2–6 个对象，绝对上限为 8。`lead` 必须位于首位，可用 `label` 覆盖默认的“结论”；
`point` 必须提供短 `label`；`display` 只使用 `type` 和 `parts`；`boundary` 必须位于末位，可用 `label`
覆盖默认的“边界”。所有 block 标签都不超过 20 个字符，并拒绝原始 Markji 语法；可以按卡片语言
覆盖 lead 与 boundary 标签，但同一 collection 应保持同一套语义标签。每个 block 的 `parts` 从
`text`、`formula`、`link`、`audio`、`image` 和 `card-ref` 中受控组合。

工具把 lead 编译为 `[T#B,!36b59d#<lead label>]：…`，在其后生成空行；point 编译为
`• [T#B#<point label>]：…`；boundary 前生成空行，并编译为
`[T#B,!c47f17#<boundary label>]：…`。未覆盖时，lead 与 boundary 分别显示“结论”和“边界”。只有
短标签进入 `T`，正文 part 不会被样式包裹。

PDF 把公式 `E` 与图片 `Pic` 定义为整行元素。因此 lead、point 与 boundary 只允许行内 part；
`display` 必须包含恰好一个 `formula`，或一个／多个 `image`。顶层 `{"parts": [...]}` 若包含公式或
图片，也必须是单个 formula 或纯 images，不能与 text、link 等行内 part 混排。工具生成的整行元素不
嵌入 `T`。媒体与卡片引用只能携带用户已经提供的 ID。不要在字符串、part 或 block label 中传入现成
Markji 语法；详细内容层级见[卡片内容与版式](card-content-layout.md)。

结构化能力还受模板占位上下文约束。只有占位符独占模板一行的 `content` 字段可以使用 blocks、display
或其他受控 Markji part；例如技术问答的“答案”和选择题的“解析”。被外层 `T`／`P` 包裹、位于
Choice 选项行，或与图标等前缀共享一行的 `content` 字段，只接受单行字符串或纯 `text` parts；例如
纠错卡的“正确／错误”、技术问答的“锚点”和选择题的选项。工具从 registry 模板机械判定，不允许把
多行 block、公式、图片、链接或媒体嵌入另一个 Markji 元素。

XLSX 使用标准库生成的最小 SpreadsheetML，所有单元格均为 inline string。以 `=`、`+`、`-` 或 `@`
开头的内容也保持文本，不生成公式节点。工具固定 sheet、列序、行序、ZIP member、时间戳和存储方式，
并限制 XML 字符、Excel 行列与 32767 UTF-16 code units 的保守单元格上限。相同输入必须得到相同字节
和 SHA-256。

## 工具调用与结果

```text
python scripts/memo_cards.py prepare --repo <repo> --context <context> --request <request.json>
python scripts/memo_cards.py publish --repo <repo> --context <context> --request <request.json> --preview-digest <digest> --authorization request|confirmed
python scripts/memo_cards.py verify  --repo <repo> --context <context> --request <request.json>
```

命令输出稳定、ASCII-safe 的 JSON envelope。`prepare` 不写仓库；它返回完整 Markdown diff、每个文件的
create／update／remove／no-op、XLSX 行级变化、当前与候选哈希，以及绑定整个 artifact set 的 preview
digest，不把二进制内容塞进 JSON。`publish` 一次事务式发布 Markdown 与全部 XLSX。`verify --request`
只有在整个文件集 `operation=no-op` 且 `would_write=false` 时才表示无需再次写入。

`memo-cards.artifact/v1` 的旧 Markdown 继续可读并参与 inventory；它没有足够字段离线重建 XLSX，因此
只能在用户提供同一目标的新 request、看过迁移 diff 并给出 `confirmed` 后定向升级到 v2。现有同名但
未受管的 XLSX 也必须作为 adoption 显示当前与候选哈希，不得静默覆盖。
