# memo-cards：受管产物与事务实现说明

本文面向维护 `skills/memo-cards/scripts/memo_cards.py` 的开发者，记录 manifest 字段、inventory 规则和多文件
事务的实现细节。Agent 在制卡时只需遵循 Skill 内的
[受管产物合同](../../skills/memo-cards/references/managed-artifacts.md)，不需要手工执行这里的步骤。

## Artifact set 与 manifest

一个受管目标由一个 Markdown 主文件和零到多个同目录 XLSX sidecar 组成。Markdown frontmatter 使用
JSON（YAML 1.2 子集），artifact v2 至少包含：

- Markji adapter 与模板 registry 版本；
- 来源摘要、逐来源 SHA-256 与聚合 fingerprint；
- 每张卡的完整身份、逻辑 ID、内容摘要、内容 SHA-256、模板版本、生命周期与依赖 hash；
- 每个 XLSX 的确定性路径、模板、sheet、字段、行映射、字节数、表格摘要和文件 SHA-256；
- 受管 Markdown 正文 SHA-256、整个正文＋sidecar manifest 的 artifact-set SHA-256；
- 除自身以外完整 manifest payload 的 SHA-256。

身份和 hash 不进入 XLSX 列。manifest 不写生成时间；相同 context、来源、候选和模板必须产生逐字节
相同的 Markdown 与 XLSX。每张 active 卡恰好映射到一个 sidecar 行；`review`／`archived` 不导出。

## Inventory

inventory 从 materializer 展开的 concrete tracked files，以及已授权 output inventory pattern 下当前存在
的 Markdown 候选中筛选主产物。后者覆盖"刚发布、尚未 Git add／materialize"的正常窗口；未跟踪候选
只有通过完整 manifest／sidecar 校验才进入 inventory，任意未跟踪 Markdown 被忽略。XLSX 可以同时作为
tracked collection member 出现在 allowlist，但其所有权和完整性只由 v2 Markdown manifest 确定。v1
manifest 继续参与卡片去重并标记 `migration_required`；manifest payload 漂移不参与 canonical 去重。

## 预览内容

`prepare` 保持零写入并输出：included、soft-deferred、blocked、跨文件 duplicate 与 dependent review；卡片
add／change／remove；完整 Markdown unified diff；artifact set 内每个文件的 role、ownership、
create／update／remove／no-op、当前／候选 SHA-256 与大小；每个 XLSX 的模板、前后行数以及逻辑卡行的
add／change／remove；所需授权等级和绑定完整文件集的 `preview_digest`。二进制 XLSX 不进入 JSON 或 diff 的
base64。

## 多文件 CAS 与事务式发布

`publish` 先在所有已授权 output root 中按稳定顺序取得 publication lock，再重新执行完整 prepare，并
要求相同 `preview_digest`。因此两个不同 Markdown 目标也不能并发或在 materialize 前顺序绕过 inventory
去重，协调文件也不会写出 context 的 write ceiling。随后发布使用目标级 artifact-set lock：

1. 对新旧文件并集执行 SHA-256／不存在性预检；
2. 在目标目录写入并 fsync 全部候选临时文件，同时复核来源仍是 request 中的 UTF-8 字节快照；
3. 写入事务 journal；
4. 把待更新或删除的原文件原子隔离到唯一 holding 路径并复核 hash；
5. 以排他 hard-link 安装 XLSX，最后安装 Markdown 作为提交点；
6. 再次复核来源与全部候选 hash 后，才接受提交并删除 temp、holding 与 journal。

任一步失败时，只删除仍与本次候选 hash 相同的已安装文件，并只在目标为空时恢复 holding。竞争文件永不
被覆盖；无法安全恢复时保留 recovery 文件与 journal 并在错误详情中列出。文件系统不提供真正的跨文件
事务，因此异常进程终止可能留下 journal；`verify` 直接扫描所有受管输出根，不依赖 Markdown 是否仍在，
会报告 interrupted transaction 或遗留 publication lock。出现任一标记时 inventory 暂停读取，后续发布
停止。没有 `--force`、`--yes` 或跳过 CAS 的入口。

## 软目标选择

`selection=selected` 时，工具把新增 active 卡按等级（A 在 B 前）、再按 `rank` 和逻辑 ID 排序，只纳入不超过
`soft_target.maximum` 的数量，其余以 `soft-target-attention-load` 列为 deferred。已纳入卡片依赖的子卡会被
补入，因此结果可能略超上限；`soft_target.above_maximum` 如实报告。既有卡刷新不计入软目标。
