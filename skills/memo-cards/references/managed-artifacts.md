# 受管产物、差异与发布合同

发布、刷新、接管旧产物或处理发布失败时读取本参考。manifest 字段、锁和事务步骤等工具内部实现记录在开发者
文档 `docs/dev/memo-cards-artifacts.md`，Agent 不需要手工执行它们。

## 产物与 inventory

一个受管目标由一个 Markdown 主文件和零到多个同目录 XLSX 组成。Markdown frontmatter 保存工具生成的 manifest：
来源、卡片身份与内容摘要、每个 XLSX 的行映射与哈希。身份和哈希不进入 XLSX 列；相同输入产生逐字节相同的
产物。每张 active 卡恰好对应一个 XLSX 行，`review`／`archived` 卡不导出。

inventory 由工具在运行时扫描授权的 inventory pattern 得到，用于跨文件去重，与 Git 是否跟踪无关：带
memo-cards manifest 的文件必须通过完整校验，其余可读的 Markdown 记为 legacy，链接、特殊文件和非 UTF-8
文件跳过。Agent 不手写 manifest、逻辑 ID 或哈希。

## 预览与授权等级

`prepare` 零写入，展示 included、deferred、blocked、跨文件重复与依赖复核，卡片的增删改，完整 Markdown diff，
每个文件的操作与哈希变化，每个 XLSX 的行级变化，以及所需授权等级和 `preview_digest`。

清晰来源、新目标且没有同名 sidecar 的明确保存请求可以使用 `request` 授权。下列情形必须在用户看到精确变化后
使用 `confirmed`：

- legacy 接管、v1→v2 迁移、人工 Markdown 漂移；
- 未受管同名 XLSX 接管、受管 sidecar 缺失／漂移／删除；
- 来源集合或 fingerprint 变化；
- template registry 或单卡模板升级；
- 依赖漂移、跨文件 dependent review 或 `review_resolution`；
- 卡片删除、生命周期停用或其他既有冲突。

没有任何语义或字节差异时返回 `no-op`，不重写文件；预览之后任一文件变化都会使旧 digest 失效。

## 发布与失败处理

`publish` 用同一 request 与 `preview_digest` 以事务方式一次发布 Markdown 与全部 XLSX；工具在发布前重新执行
完整 prepare，任何漂移都会被拒绝，此时重新预览。

- 发布失败时不重试、不手工修补：报告工具返回的错误与 recovery 详情。
- `verify` 报告 interrupted transaction 或遗留 publication lock 时，停止后续发布，请用户按 recovery 详情人工
  核验，恢复完整的旧产物或完整的新产物；不能把部分结果说成成功。
- 没有 `--force`、`--yes` 或跳过校验的入口，也不要自行实现。
- 同时保存学习记录和制卡时，两者是独立事务；上游失败后不继续消费未生成的结果。本工具不导入 Markji、不提交
  也不推送。

## v1 迁移、渐进接管与跨日复发

- 不批量迁移 legacy 或 artifact v1。v1 缺少 rendered fields，必须由同一目标的新 request 重建 XLSX。
- v1 目标保持可读；定向刷新时显示 `artifact-v1-migration`、Markdown diff 与全部 XLSX 变化，再确认。
- 已存在的派生同名 XLSX 在 v1 中没有所有权；即使字节相同，纳入 v2 仍属于 adoption。
- 同一逻辑卡跨日复发时抑制重复新行，不因当前新日授权修改旧文件。
- 新证据实质改善旧卡时单独预览旧目标；人工修改、来源漂移、模板升级或删除都要求重新确认。
- 软件事实变化时优先建立 `successor_to` 后继卡，不静默改变旧快照含义。
