---
name: study-log
description: 从 Claude Code 或 Codex 原始对话记录（JSONL）提取技术学习过程，筛选后整理成结构化学习记录，写入 {module}/log/。产出是 memo-cards 技术制卡的过程素材（文章是结果素材，学习记录是过程素材）。Use when the user asks 整理学习记录 / 提取对话记录 / 把今天的学习对话存档.
---

# 学习记录提取（AI 对话 → 结构化学习记录）

把陪学/技术讨论会话中真正的**学习过程**——问答、我的回答、纠错、关键讲解——从原始对话里蒸馏出来，存成可回查、可制卡的学习记录。定位：**文章是学习的结果，学习记录是学习的过程**；两者都是 memo-cards 的素材源，但学习记录额外保住了"我当时怎么错的"这类文章里不会全留的细节。

## 流程（四步）

### 1. 定位会话（脚本）

```bash
python3 <skill-dir>/scripts/extract_transcript.py list --provider auto
```

`<skill-dir>` 指当前被加载的 `study-log` 技能目录，例如 `.claude/skills/study-log` 或 `.agents/skills/study-log`。列出本项目全部可用会话（新→旧，含客户端、起止时间和首条用户消息）。`auto` 同时检查 Claude Code 与 Codex；也可显式传 `--provider claude` 或 `--provider codex`。Codex 只列出 `cwd` 与当前项目精确匹配的根会话，不混入 subagent 会话。默认目标 = 用户点名的日期/主题；没点名就取当天。

若脚本提示没有可用数据源：先按提示确认客户端与项目路径；若目标对话仍完整存在当前上下文，可直接从当前上下文整理，并把来源标为“当前会话上下文（无原始日志）”；否则请用户粘贴或导出目标对话，绝不凭空补全。

### 2. 提取对话（脚本）

```bash
python3 <skill-dir>/scripts/extract_transcript.py extract \
  --provider auto --session <id前缀> --date YYYY-MM-DD -o <scratchpad>/dump.md
```

脚本输出纯净的用户/AI 文本轮次（已剔除 thinking、工具调用、subagent 侧链、压缩摘要，以及推荐插件、`AGENTS.md`、环境上下文、system-reminder 等 harness 注入）。跨天的长会话务必用 `--date` 切片；需要看改了哪些文件时加 `--tools`。会话 ID 前缀匹配到多个候选时，脚本会列出候选，必须改用更长前缀再执行。

### 3. 筛选技术学习过程（判断）

读提取稿，只保留学习内容本身：

- **保留**：讲解的关键要点；带练的问答（问题 + 我的回答 + 判定）；**纠错与错位**（我怎么说错的 → 正确表述 → 为什么，含金量最高）；我给出的实战经验/war story；当场挖的坑和遗留问题。
- **丢弃**：金库维护/SOP 执行/git 操作等机械轮次；工作流和元讨论（比如"怎么建 skill"）；英语反馈块（那是 `英语/log/` 的辖区，english-coach 已单独落盘）；寒暄、菜单选择、确认性短消息。

### 4. 写学习记录

输出到 `{module}/log/YYYY-MM-DD-<主题slug>.md`（目录不存在就创建；模块从内容判断，默认当前主攻模块）。格式见 [references/log-format.md](references/log-format.md)，条目用三种标签：

- `[要点]` — 学到的可自问自答的知识点（问题式表述 + 2–4 句要点 + 来源锚点）
- `[纠错]` — 我的错误表述 → 正确表述 + 为什么（写明当时场景）
- `[遗留]` — 当场没解决、挂账的问题（标注已挂到哪里：文章 §后续预告 / `进度.md` / 断点）

直接写入并报告；用户要预览时先出草稿。同一天同主题重复执行时**覆盖重写**（幂等，和 memo-cards 同款约定）。

## 与 memo-cards 的衔接

学习记录是 memo-cards「输入二：技术学习素材」的正式来源之一：`[要点]` / `[纠错]` → 技术Q&A卡（纠错条目把"我怎么错的"写进答案，是最抗遗忘的卡）；`[遗留]` 不制卡。用户说"把这份学习记录制卡"时调 memo-cards。

## 边界

- 对话记录（Claude Code 的 `~/.claude/projects/…/*.jsonl`、Codex 的 `~/.codex/sessions/…/*.jsonl`）**只读**；本 skill 只新建/覆盖 `{module}/log/` 下自己的文件。
- 不碰 `进度.md`、文章、断点——那些是 study-companion 收尾三 Stage 的辖区；学习记录是独立的第四类产物，不参与收尾契约。
- 提取稿（dump）放 scratchpad，不进仓库。
- 机械任务：执行中不附加英语反馈。
