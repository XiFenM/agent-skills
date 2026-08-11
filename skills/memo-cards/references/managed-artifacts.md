# 受管产物、差异与发布合同

## 产物与 inventory

每个受管暂存文档在同一 Markdown 的 frontmatter 中保存 JSON（YAML 1.2 子集）。manifest 至少包含：

- artifact schema、Markji adapter／模板 registry 版本；
- 来源摘要、逐来源 SHA-256 与聚合 fingerprint；
- 每张卡的完整身份四元组、逻辑 ID、内容摘要、内容 SHA-256、模板版本与本地生命周期；
- 机制卡与综合口述卡依赖的逻辑 ID 与逐依赖内容 SHA-256；
- 持久 dependency-review 原因，或已确认解除复核的摘要；
- 受管正文 SHA-256。
- 除自身以外完整 manifest payload 的 SHA-256。

身份和 hash 不进入 Markji TSV 列。manifest 不写生成时间；相同 context、来源、候选和模板必须逐字节稳定。

inventory 只从 materializer 展开的 concrete tracked files 中派生，再应用 context 的 inventory pattern。无
manifest 文件保持 legacy，只产生保守重复提醒；未跟踪文件不读取。manifest payload 漂移的文件可以报告
和定向接管，但在重新确认前不参与 canonical 去重。未配置仓库不进入跨库 inventory。

## 预览与风险

`prepare` 必须保持零写入，并展示：

- included、soft-deferred、blocked 和跨文件 duplicate；
- add、change、remove、conflict 与 legacy adoption；
- 完整 Markdown diff、当前目标 SHA-256、候选 SHA-256 和 `preview_digest`；
- 所需授权等级。

清晰来源、新目标和明确“创建／保存”请求可以使用 `request` 授权。下列情形要求用户在看到精确 diff 后再次确认：

- legacy adoption 或检测到人工漂移；
- 来源集合／fingerprint 变化；
- 模板 registry 或单卡模板升级；
- 机制卡／综合口述卡的依赖内容漂移，或发现跨文件 dependent review；
- 用 `review_resolution` 把持久 `review` 恢复为 `active`；
- 删除、事实冲突、目标变化或跨文件刷新。

没有语义或字节差异时返回 `no-op`，不重写文件。

## CAS 与原子发布

`publish` 重新执行完整 prepare，并要求调用方提供相同 `preview_digest`。digest 绑定 context、request、来源、目标、inventory、模板和候选正文；任一项变化都会使旧授权失效。

发布时再次验证目标 SHA-256。新建使用排他创建；更新先把当前目标原子移到唯一 holding 文件，验证被移走
的确是预览版本，再以排他 hard-link 安装候选。若竞争者先占据目标，绝不覆盖它，并在错误详情指出保存旧
字节的 recovery 文件。成功后才清理 holding；失败时清理临时文件，无法安全还原时保留 recovery。没有
`--force`、`--yes` 或跳过 CAS 的入口。

一次请求同时保存学习记录和制卡时，两者仍是独立事务。上游失败后不得继续消费其未生成结果；本工具也不顺带导入 Markji、提交或推送。

## 渐进接管和跨日复发

- 不批量改写 legacy。用户明确刷新某个 legacy 目标时，先展示 adoption diff，再确认。
- 同一逻辑卡跨日复发时抑制重复新行；不因当前新日制卡授权而修改旧文件。
- 新证据确实改善旧卡时，单独预览旧目标的刷新。
- 人工修改、来源漂移、模板升级、拟删除卡片或预览后漂移都停止写入并要求重新预览。
- 软件升级导致事实变化时优先建立 `successor_to` 后继卡，不静默改变旧快照的含义。
