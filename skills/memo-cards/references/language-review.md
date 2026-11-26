# 完成前语言审查（记忆卡片）

目标：卡片语言**清晰、完整、可独立复习**。不要求口语化或生动；要求学习者在忘记原课堂、乱序看到这张卡时，仍能确定任务、条件和答案。

这是完成前的硬门：没有通过审查，不 `prepare`、不 `publish`、不上传。

## 什么时候审

1. **候选卡片定稿后、`prepare` 之前**：审所有 included 卡片。
2. **卡片内容改动后、`prepare` / `publish` / 上传之前**：只复查改动卡；如果改动影响依赖卡，复查依赖链。
3. **只审 included**；deferred 暂不审，纳入时再补审。blocked 不审，保持原状。

## 怎么审：Gemini 核心直走子 Agent，非 Gemini 宿主远程优先

按下面的前置分流与顺序执行，每一步都不许跳过或假装通过：

### 0. 前置分流（主 Agent 已是 Gemini 核心）

如果当前主 Agent 本身以 **Gemini** 为核心，**不需要调用 ZenMux API**，直接跳到第 2 步使用**宿主只读子 Agent**审查。若由统一脚本调用 `zenmux_review.py`，传 `--host-model gemini` 或设 `VIVID_LANGUAGE_HOST_MODEL=gemini`，脚本会以退出码 2 引导走第 2 步。

### 1. 远程模型（非 Gemini 宿主首选）

1. 当主 Agent 不是 Gemini，调用启用中的 `vivid-language` Skill 的 `scripts/zenmux_review.py`，把候选卡片的正面、答案、边界标签和来源短标签交给它；不要给 XLSX、Markji 语法或整页 HTML：

   ```bash
   python3 <vivid-language>/scripts/zenmux_review.py --kind cards cards.md
   ```

   配置、模型链和隐私说明见该 Skill 的 `references/remote-review.md`。用户没有 `ZENMUX_API_KEY` 时脚本退出码为 2，不要追问 Key，直接进第 2 步。

2. `verdict` 为 `PASS`：记录 `语言审查：PASS（ZenMux / <model>，N 张 included）`，可以继续。
3. `verdict` 为 `REVISE`：先逐卡改 blocking，再把改动卡送一次；`fact_risk` 不为“无”时逐条核对事实、版本和边界。
4. 退出码 2 或 3、脚本不存在、宿主没有 Python：都算跳过或远程不可用，进第 2 步；退出码 1 是输入问题（空、超长、路径错），修输入再跑，不要当成通过。

### 2. 子 Agent（Gemini 宿主首选，或远程不可用兜底）

1. 主 Agent 调宿主提供的子 Agent 工具（如 `subagent`）；子 Agent 只读审查，不改文件。
2. 子 Agent 读 `vivid-language` 的 `references/language-contract.md`（记忆卡片体裁）和 `memo-cards` 的 `references/card-content-layout.md`；读不到时用本文件末尾的 8 条 rubric。
3. 输入是候选卡片的正面、答案、边界标签和来源短标签，不是 XLSX 或 Markji 语法。
4. 子 Agent 返回 `PASS` 或 `REVISE`；`REVISE` 必须逐卡列 blocking，每条给出原文、问题、建议改法，不重写整批卡。
5. 主 Agent 修完 blocking，再把改动卡交给子 Agent 复查；`PASS` 后才能 `prepare` 或 `publish`。
6. 记录 `语言审查：PASS（子 Agent，N 张 included）`。

### 3. 都没有

不要静默跳过，也不要声称“语言审查通过”。按下面的 rubric 自审，明确告诉用户“未独立审查”，并请用户确认是否接受；只有用户明确接受后，才继续 `prepare` / `publish`，且预览里仍要标注“未独立审查”。

## 审查 prompt（子 Agent 用，可直接粘贴）

```text
你是记忆卡片的语言审查子 agent，只审查，不改文件。

先读：
- 启用中的 `vivid-language` Skill 的 `references/language-contract.md`（记忆卡片体裁）
- `memo-cards` 的 `references/card-content-layout.md`

目标：卡片语言清晰、完整、可独立复习；不要求口语化。学习者忘记原课堂、乱序看到这张卡时，仍应能确定任务、条件和答案。

审查对象：
<逐卡粘贴正面、答案、边界标签、来源短标签>

只返回以下结构：
- verdict: PASS 或 REVISE
- blocking: 每条 {卡片, 原文, 问题, 建议改法}
- non_blocking: 同上，可为空
- 事实风险: 改写可能改变的事实、版本或边界（没有就写“无”）

blocking 只放：正面缺场景/条件/任务、多目标混卡、答案缺理由或边界、正面泄题、压成提示词、要求无序回忆超过 3 项、编造事实、纠错卡把正确部分一并判错。
不要因为“可以更口语”就判 blocking。
```

## Rubric（8 条）

- [ ] 只看正面，就知道讨论什么对象、哪个阶段、已知哪些条件、要回答什么？
- [ ] 一张卡只有一个回忆目标？没有多个可独立考查的问号？
- [ ] 答案先直接回答，再有理由/步骤，最后有条件或边界？
- [ ] 完整到能独立复习？没有把 A 卡压成提示词或只给结论？
- [ ] 正面没有写出正在考查的结论、错因或判断方向？
- [ ] 没有要求无序回忆超过 3 项的清单？需要列举时给了结构线索？
- [ ] 事实、数字、版本、边界与来源一致？没有编造经历或未验证行为？
- [ ] 纠错卡保留真实错误原话，只纠错误部分？

## 预览里怎么报

在预览中加一行语言审查结论，三种来源分开写：

- `语言审查：PASS（ZenMux / google/gemini-4-hydrogen，32 张 included）`
- `语言审查：REVISE（子 Agent，3 张 blocking，已修 2 张，1 张待确认）`
- `语言审查：未独立审查（自审，用户已确认接受）`

不能只报卡数或样式名，也不能把“未审”写成“通过”。
