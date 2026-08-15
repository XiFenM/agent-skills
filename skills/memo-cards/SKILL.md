---
name: memo-cards
description: 将用户明确指定的、已核验且值得反复强化的英语或技术学习素材整理为受管 Markdown 与按模板拆分的 Markji 3.8+ XLSX 导入文件。Use when the user explicitly asks to 制作、预览、保存、刷新或去重墨墨记忆卡，或要求把成熟学习材料转换成 Markji cards；不要因学习结束、上游 bundle 到达或其他 Skill 建议而自动触发。
---

# Memo Cards

把成熟学习证据转成可审阅的 Markji 暂存卡片。始终用自然语言理解用户请求；不要要求用户记忆脚本命令。

## 首次启用时提示用户说明

在当前对话第一次启用本 Skill 时，用一条简短、非阻塞且不带独立标题或卡片的提示建议用户先浏览本
Skill 的 `docs/user-guides/memo-cards.md` 和组合指南 `docs/learning-skills-user-guide.md`；说明它们介绍
交互流程、用户需要参与的环节和授权边界。

定位本地文档时，只按顺序检查三个候选根：当前 `SKILL.md` 所在 Skill 目录的上两级目录、当前工作区
仓库根、当前工作区仓库根下的 `.agent-skills`。把实际存在的文件解析为绝对路径并提供可点击链接，不
搜索其他目录。没有本地文件时，改为提供[本 Skill 公开说明](https://github.com/XiFenM/agent-skills/blob/main/docs/user-guides/memo-cards.md)
和[公开组合指南](https://github.com/XiFenM/agent-skills/blob/main/docs/learning-skills-user-guide.md)。

用户没有要求先暂停阅读时继续处理当前请求；不要求用户确认，不在同一对话重复提示，也不创建文件
记录是否已经提示。同一对话已经提供组合指南时只补本 Skill 说明；同一回复首次启用多个学习 Skill 时
合并为一条提示，并且只列一次组合指南。

## 边界

- 只在用户明确提出制卡、预览、创建或刷新卡片时运行。上游 Skill、bundle、静态配置和学习收尾都不构成触发或授权。
- 默认精选；用户明确要求完整转换时，仍只输出通过质量门槛且完成去重的候选。
- 默认零写入。只看候选时保持预览；清晰来源与新目标的明确保存请求可以授权当次低风险创建。接管 legacy、人工漂移、来源范围变化、模板升级、删除、冲突或跨文件刷新必须先展示精确差异，再取得确认。
- 只生成本地受管 Markdown 与每模板一个 XLSX 导入文件；不上传资产、不导入 Markji、不声称改变远端卡片，也不提交或推送 Git。
- 没有经过 materializer 校验的 `.agent-skills-context.json` 时，只能在对话中讨论候选，不猜测路径或写入。

## 工作流

1. 明确素材边界、目标 collection、目标文件以及用户要精选还是完整转换。只读取受管 context 允许的来源。
2. 评估事实是否稳定、可追溯且值得重复强化；把 raw 对话、遗留问题、猜测、冲突和未核验时效事实留在 blocked preview。按需读取 [卡片质量与身份](references/card-quality-and-identity.md)。
3. 由 Agent 完成语义工作：先拆分单一回忆目标，再按[卡片内容与版式](references/card-content-layout.md)
   撰写短促题面，以及按结论／要点／边界分层的答案；不要用颜色或字号掩盖应该拆卡的内容。判断
   A／B／C、常青／版本快照、原子／机制／综合口述层级。机制卡若声明子卡依赖，必须引用同一 request
   内 eligible、已核验且 active 的原子／机制卡；综合口述卡引用其中 2–5 张。不要手写 Markji 语法、
   逻辑 ID、XLSX、hash 或 manifest。结论与边界标签可按卡片语言覆盖，但必须短促，并在同一
   collection 中保持一致。
4. 按 [受管 Markdown 与 XLSX 合同](references/markdown-xlsx-staging.md) 形成严格 request JSON，调用 `scripts/memo_cards.py prepare`。工具负责模板、身份、inventory、软目标、XLSX、差异和预览摘要。
5. 向用户展示 included 卡片的短题面与内容层级，并列出 deferred、blocked、duplicate／conflict、完整
   Markdown diff、逐 XLSX 的行级与哈希变化、风险原因和 `preview_digest`；不能只报告卡数或样式名。
   依赖漂移触发的 `review` 会持续保留；复核完成后，只有在对应卡片提供可摘要的
   `review_resolution`、展示新 diff 并取得 `confirmed` 授权，才能恢复 `active`。模板及内容语法边界见
   [Markji 3.8 兼容面](references/markji-3.8-compatibility.md)。修改渲染器、核对原始示例或判断精简
   兼容面尚未覆盖的语法时，再读取[随 Skill 固定保存的内容语法 PDF](references/markji-content-syntax.pdf)；
   不把内容语法文档当作表格导入协议。
6. 无写入授权时停在预览。获得足够授权后，用同一 request 和 digest 调用 `publish`，一次发布 Markdown 与全部受管 XLSX；若任何来源、目标、sidecar、模板、候选或 inventory 漂移，重新预览。详细多文件 CAS、迁移与接管规则见 [受管产物合同](references/managed-artifacts.md)。
7. 发布后用同一 request 调用 `verify --request <request.json>`，复核 context、模板、Markdown、全部 XLSX 与受管 inventory；只有返回的 `request_check.operation` 为 `no-op` 且 `would_write=false`，才表示该 request 无需再次写入。这也能复核尚未重新 materialize 进 inventory 的新目标。报告本地写入结果，并说明用户需要在 Markji 选择对应模板后逐个上传 XLSX。

## 职责分工

- Agent 判断知识价值、语义等价、事实范围与教学表达。
- `memo_cards.py` 独占配置校验、逻辑身份、模板字段顺序、受控 Markji 片段、确定性 XLSX、manifest、派生 inventory、多文件 diff、CAS 和事务式发布。
- `guide-learning` 继续验证研究项；`study-log` 只提供 structured 学习过程；`english-coach` 只提供真实错误、主动表达和稳定辨析候选。raw 对话永不直接制卡。
