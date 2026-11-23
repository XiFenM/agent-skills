# 远程语言审查与改写（ZenMux）

本地模型说不出人话时，加多少规则都可能原地打转。这个 Skill 可以先把正文交给 ZenMux 上更会聊天、更会写中文的模型，拿回 `PASS` / `REVISE` 或一份候选改写；拿不到才退回宿主子 Agent。

远程不是硬依赖。三档顺序固定：

1. **ZenMux 远程模型**（本文件）：配置了 `ZENMUX_API_KEY`，且模型链里有一个能回应。脚本不存在、宿主没有 Python、命令直接报错，也按“远程不可用”处理，不猜、不重试。
2. **宿主子 Agent**：没配置、被关掉，或整条模型链都不回应。
3. **自审 + 明示**：子 Agent 也没有时，按各自 Skill 的 rubric 自审，并写“未独立审查”，不得声称已通过。

## 配置

只需要一个环境变量：

```bash
export ZENMUX_API_KEY="sk-..."     # 必需；在 https://zenmux.ai/platform 创建
```

可选：

| 变量 | 作用 | 默认 |
|---|---|---|
| `ZENMUX_BASE_URL` | OpenAI 兼容端点 | `https://zenmux.ai/api/v1` |
| `VIVID_LANGUAGE_ZENMUX_MODELS` | 模型链，逗号或空格分隔 | 下面四个 |
| `VIVID_LANGUAGE_REMOTE_REVIEW` | 设为 `off` / `0` / `false` 时强制走子 Agent | 不设置 |

默认模型链，按顺序尝试，第一个回应的胜出：

1. `google/gemini-4-neon`
2. `google/gemini-4-hydrogen`
3. `google/gemini-4-carbon`
4. `google/gemini-4-argon`

换成自己的模型链：`--model a/b --model c/d` 或 `VIVID_LANGUAGE_ZENMUX_MODELS="a/b,c/d"`。用户明确指定某个模型时，用 `--model` 覆盖，不要改默认。

还没开通 ZenMux、或不确定 Base URL 怎么填，按启用的 `zenmux-setup` Skill 走；这里只依赖它的 `ZENMUX_API_KEY` 与 OpenAI 兼容端点约定。

**隐私**：正文会以 HTTPS 发到 ZenMux。没配置 Key 就不发；含密钥、客户隐私或未公开事故细节的文本，先用 `VIVID_LANGUAGE_REMOTE_REVIEW=off`，或问用户是否允许外发。

## 什么时候值得用

成篇的页面正文、整批卡片、整篇文章，或用户明确说“这段还是不像人话”，值得跑远程。一两句对话反馈、用户没要求审或改、正文里含密钥或隐私，不必发远程：本地规则更省事，或直接关掉远程。

## 调用

脚本随 Skill 分发，用它的绝对路径或相对当前 Skill 的路径调用；不要假设 Python 包名。

```bash
# 课程网页正文审查
python3 <vivid-language>/scripts/zenmux_review.py --kind page draft.md

# 记忆卡片审查（逐卡粘贴到文件或 stdin）
cat cards.md | python3 <vivid-language>/scripts/zenmux_review.py --kind cards -

# 文章、对话反馈
python3 <vivid-language>/scripts/zenmux_review.py --kind article draft.md
python3 <vivid-language>/scripts/zenmux_review.py --kind conversation reply.txt

# 候选改写：返回改写稿 + 改动说明，由主 Agent 决定采不采用
python3 <vivid-language>/scripts/zenmux_review.py --kind article --mode rewrite draft.md

# 配置是否通：逐个模型 ping 一次
python3 <vivid-language>/scripts/zenmux_review.py --check
```

常用参数：`--model`（可重复，构成模型链）、`--timeout` 单次请求秒数（默认 45）、`--retries` 每个模型最多试几次（默认 2）、`--max-total-seconds` 整条链预算（默认 180）、`--max-input-chars`（默认 24000，超了分段送）、`--rubric-file` 追加本次体裁要求、`--format text` 输出给人看的版本、`--dry-run` 只看将发送的请求。

## 退出码与下一步

| 退出码 | 含义 | 主 Agent 下一步 |
|---|---|---|
| 0 | 有模型回应并解析成功 | 用结果；`REVISE` 先改 blocking 再复查 |
| 2 | 没配置：缺 `ZENMUX_API_KEY`，或 `VIVID_LANGUAGE_REMOTE_REVIEW=off` | 走子 Agent；不要重试，不要问用户要 Key |
| 3 | 配了但不可用：四个模型都没回应、401、全部 403、超预算 | 走子 Agent；把失败原因用一句话告诉用户 |
| 1 | 输入问题：空文本、超长、文件读不到 | 修输入再跑，不要当“审查通过” |

退出码 2/3 都**不是**语言审查通过。页面与卡片的完成门仍然有效：换成子 Agent 重审，子 Agent 也没有就自审并标“未独立审查”。

## 输出

默认 JSON：

```json
{
  "status": "ok",
  "provider": "zenmux",
  "model": "google/gemini-4-hydrogen",
  "mode": "review",
  "kind": "page",
  "verdict": "REVISE",
  "blocking": [{"原文": "...", "问题": "...", "建议改法": "..."}],
  "non_blocking": [],
  "fact_risk": "无",
  "attempts": [{"model": "...", "attempt": 1, "outcome": "ok", "detail": ""}],
  "usage": {"total_tokens": 1234}
}
```

`mode=rewrite` 时，`verdict` 换成 `rewrite` 和 `changes`（原文 → 改成，为什么）。模型没按 JSON 返回时，脚本会尽量保留纯文本候选稿，并标 `"parsed_json": false`；`finish_reason=length` 时标 `"truncated": true`，改写稿不可直接采用。

`attempts` 是排障用的：谁超时、谁 429、谁返回了解析不了的文本，都记在里面。用户问“为什么没用上远程”时看这里。

## 审查与改写怎么落地

**审查（review）**

1. 把**可见正文**交给脚本，不要给整页 HTML、脚本或样式。
2. `PASS`：记录“语言审查：PASS（ZenMux / <model>）”。
3. `REVISE`：先改 `blocking`，再只把改动段送一次复查。`non_blocking` 可以让用户决定。
4. `fact_risk` 不为“无”时，逐条核对数字、版本、引用；远程模型不许替作者改事实。

**改写（rewrite）**

1. 远程稿是**候选**，不是终稿。主 Agent 对照原文逐段核事实，再决定采用、部分采用，还是自己重写。
2. 采用时保留 `changes` 做“改了什么/为什么”的交付；不要把远程稿和原文混着贴给用户而不说明。
3. 用户没要求改写时不要用 rewrite 模式改他的文字；诊断仍按 `diagnose` 交付。

## 失败与排障

- **401**：Key 无效或过期。脚本立即停止，不再换模型试；提示用户检查 `ZENMUX_API_KEY`。
- **403**：通常是这把 Key 没有该模型权限。脚本把它算作该模型失败，换下一个；四个都被拒才按远程不可用处理。
- **404 / model not found**：该模型不在账号或拼错。脚本换下一个模型；`--check` 能一次看清哪些可用。
- **429 / 5xx / 超时**：脚本按退避重试同一个模型，再换下一个；整条链超过 `--max-total-seconds` 就停。
- **返回不是 JSON**：先重试同一模型，再换下一个；都失败就按退出码 3 走子 Agent，不要猜模型想说什么。只认单独出现的 `PASS`／`REVISE`，正文里顺带提到两个词的散文不算结论。
- **结论自相矛盾**：`REVISE` 却没列 blocking，或 `PASS` 却带 blocking，都按解析失败处理：重试同一模型，再换下一个。
- **400 请求不合法**：多半是 `--max-tokens` 太大或输入过长；调小或分段重试，不要原样重发。
- **输出被截断**：缩短输入或提高 `--max-tokens`；不要采用半截改写稿。

不要自己拼 curl 去请求 ZenMux：重试、模型降级、JSON 解析和退出码都在脚本里，手写只会绕开它们。脚本本身跑不起来（缺 Python、Skill 没被材料化、路径不对）时，直接按退出码 2/3 处理，转子 Agent。
