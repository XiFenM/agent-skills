# Source authority

在使用文档、教程、论文、示例或源码进行教学，核验版本敏感事实，设计实验，或处理多来源冲突时读取
本参考。把教学顺序与事实裁决分开。

## Contents

1. [Record source roles](#record-source-roles)
2. [Match claims to authority](#match-claims-to-authority)
3. [Anchor versions](#anchor-versions)
4. [Supplement minimally](#supplement-minimally)
5. [Resolve conflicts](#resolve-conflicts)
6. [Bound empirical claims](#bound-empirical-claims)
7. [Respect adjacent ownership](#respect-adjacent-ownership)

## Record source roles

优先沿用户选择的资料组织教学，把它标为 **teaching spine**。不要因此把它视为所有 claim 的最高
权威，也不要因为发现另一份更顺手的资料就静默替换。

为每个实际使用的来源保存最小角色记录：

```yaml
- locator: <相对路径、稳定标识或链接>
  role: <teaching-spine | implementation-authority | interface-authority |
         method-authority | empirical-evidence | explanatory-support>
  version_anchor: <commit、tag、版本、发布日期或访问日期>
  scope: <本课使用的章节、文件、claim 或实验范围>
```

允许同一来源承担多个角色，但要分别说明适用范围。不要复制大段正文；保存能重新定位证据的锚点。

角色含义：

- `teaching-spine`：决定本课沿什么顺序和例子推进。
- `implementation-authority`：裁决固定 revision 的具体实现、数据流或控制流。
- `interface-authority`：裁决公开接口、规范和承诺语义。
- `method-authority`：裁决论文或标准所定义的方法、假设和报告结论。
- `empirical-evidence`：只裁决声明环境、输入和测量边界内的观察。
- `explanatory-support`：提供教程、示例、类比或第三方解释，不覆盖相应一手来源。

## Match claims to authority

按 claim 性质选择裁决者：

| Claim | 首选权威 | 不足以单独裁决 |
| --- | --- | --- |
| 某 revision 的实现和控制流 | 固定 commit 或 tag 的源码 | 未固定版本的教程、记忆中的实现 |
| 公开 API 和保证 | 官方文档、规范、发布说明 | 示例代码、偶然运行结果 |
| 论文方法、假设和报告数字 | 论文本身及其补充材料 | 二手摘要、不同实现的 benchmark |
| 当前环境中的行为 | 明确版本与输入下的本地运行 | 另一设备或版本的结果 |
| 性能、设备或资源结论 | 可复现实验和受控比较 | 测试绿灯、一次无边界计时 |
| 教学解释 | 用户选定主线与合适脚手架 | 不能覆盖上列一手事实 |

在回答中区分：

- **来源事实**：权威来源明确声明或代码直接显示的内容；
- **本地观察**：在给定环境实际复现的结果；
- **推断**：由事实和观察推出但未直接裁决的解释；
- **假设**：等待实验或进一步来源验证的主张。

不要把推断写成来源原话，也不要把本地测试通过扩大成通用保证。

## Anchor versions

在结构化 Lesson 激活时记录相关 commit、tag、文档版本、论文版本或日期。版本锚点应足以让后续会话
判断来源是否 drift。

- 对本地源码记录仓库相对路径和 commit；存在未提交修改时补记 worktree 边界。
- 对官方文档记录产品版本或发布日期；只有页面无版本时才使用访问日期。
- 对论文记录版本、发布日期或稳定标识。
- 对实验记录软件、硬件和关键配置，不把教学来源日期当成实验环境。
- 对“当前”“最新”“现在支持”等易变 claim，在回答时重新核验，不沿用旧 mastery 记录作为事实。

不要因为只读恢复而更新时间锚点。只有来源或采用范围实际变化时才做 semantic update。

## Supplement minimally

在以下任一条件成立时主动做最小补充核验：

1. teaching spine 缺少当前节点所需的必要前置；
2. 来源可能过时或与目标版本冲突；
3. 关键结论需要一手事实源裁决；
4. 当前目标明确要求比较、迁移或跨版本解释。

不会改变目标、范围和学习投入的最小事实核验可以直接进行，但须标明来源角色。以下变化先取得用户
确认：

- 替换 teaching spine；
- 纳入体量较大的新资料；
- 扩大 Lesson 目标或 required mastery；
- 明显增加学习投入或引入新依赖；
- 把旁支研究变成新的前台任务。

补充后返回用户选定的主线。不要让资料收集取代教学。

## Resolve conflicts

遇到多来源冲突时按顺序处理：

1. 核对版本、分支、配置、平台、输入和适用条件。
2. 分别写出每个来源能够支持与不能支持的 claim。
3. 依据用户目标版本选择本课采用的行为，不用多数票揉成单一答案。
4. 能用最小一手核验解决时执行并记录角色；不能解决时标为待验证。
5. 只有冲突阻塞当前 Lesson 时扩大调查；否则登记 observation 并返回 teaching spine。

冲突会改变目标、来源范围、责任或唯一下一动作时，让用户选择分支。不要静默修改 Lesson 契约。

## Bound empirical claims

让实证结论包含可复现边界：

- 结果出现前保存预期方向、依据、不确定性和可推翻条件；
- 记录环境、版本、输入、控制变量、命令或方法及测量范围；
- 使用与目标相称的基线或受控比较；
- 将功能正确性与性能测量分开；
- 说明证据支持什么、不能支持什么和剩余不确定性。

测试绿灯只能证明已覆盖行为，不自动成为性能、设备或真实运行 mastery。性能实验还要有独立正确性
证据，并避免同时改变多个因素后归因给单一原因。

本地运行只裁决明确条件下的观察。把跨设备、跨版本或跨工作负载推广标为推断，除非有相应证据。

## Respect adjacent ownership

让本 Skill 只为当前学习目标做最小来源核验。不要直接维护广泛资料候选池、周报、长期课程晋级或
跨模块排序；把这些需求交给 `resource-planning`。

学习中发现的长期资料只做以下之一：

- 在当前 Lesson 授权范围内保存为 observation；
- 向用户提出交接建议；
- 在用户明确启动资料治理后交给相应能力处理。

候选资料不自动改变 teaching spine、稳定学习指引或下一 Lesson，也不构成执行授权。
