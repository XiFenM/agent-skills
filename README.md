# Agent Skills

这是三个学习／工作主仓库的 Skill 规范源。中央仓库已经完成第一轮学习核心的评审、合并升级与校验，并发布到公开远端 [`XiFenM/agent-skills`](https://github.com/XiFenM/agent-skills)；消费仓库迁移仍未开始，需要用户另行授权。

## 当前范围

- [`skills/`](skills/) 中保留 8 个 first-party Skill 目录。其中 6 个为 active：`guide-learning`、`study-log`、`english-coach`、`memo-cards`、`resource-planning`、`creator-workflow`。
- `study-companion` 与 `learn-by-practice` 作为 rollback-only 源码保留，统一替代项为 `guide-learning`；新消费配置不能再选择这两个旧入口。
- 5 个 external Skill 从 3 个官方 Git 子模块读取；不在本仓库复制第三方源码。
- PlanA 的 PyTorch、SGLang、vLLM 源码子模块自带 Skill 不迁移、不登记。
- Remotion 只暴露官方聚合入口 `remotion-best-practices`，不再保留功能重复的独立入口。

完整来源、分类、生命周期和消费仓库记录在 [`catalog.json`](catalog.json)。schema v2 还记录替代关系与选择组：materializer 会拒绝 rollback-only 或已退役名称，并提示最终 active 替代项；`primary-learning` 规定一个消费配置跨所有 host 最多选择一个不同的主学习 Skill，同一个 `guide-learning` 同时分发给 Codex 与 Claude 仍然合法。

迁移历史、中央升级结果及当前遗留问题记录在 [`docs/migration-baseline.md`](docs/migration-baseline.md)。学习类 Skill 的 D1–D23 决策、实现设计和后续迁移边界记录在 [`docs/learning-skills-review.md`](docs/learning-skills-review.md)。

## 目录

```text
agent-skills/
├── skills/                    # first-party Skill 的规范源码及回滚源码
├── vendor/                    # 第三方官方仓库（Git submodule）
├── tools/                     # 清单校验与消费仓库同步工具
├── tests/                     # 仓库级测试
├── catalog.json               # 机器可读的分类与来源清单
└── .agent-skills.example.json # 消费仓库声明示例
```

## 消费方式

消费仓库迁移启动后，每个消费仓库将从公开中央远端把本仓库加入为 `.agent-skills` 子模块，并提交自己的 `.agent-skills.json`。M0 已完成中央发布，M1 已从远端复验并将 `learning-core-v1` 对应的 `b2afd92854d57a375fdf990028c31561118cf8ec` 冻结为 M2–M4 的唯一迁移输入；M2–M5 尚未开始。以下是消费迁移获单独授权后的配置形状，不表示现有消费仓库已经切换：

```json
{
  "version": 1,
  "source": ".agent-skills",
  "skills": {
    "guide-learning": ["codex", "claude"],
    "study-log": ["codex", "claude"]
  }
}
```

新 clone 或更新子模块后，先递归初始化中央仓库及其第三方子模块：

```powershell
git submodule update --init --recursive
```

然后生成宿主实际会发现的目录。工具只依赖 Python 标准库；可使用现有 Python，或让 uv 提供 Python：

```powershell
python .agent-skills/tools/materialize_skills.py --repo . --dry-run
python .agent-skills/tools/materialize_skills.py --repo .
python .agent-skills/tools/materialize_skills.py --repo . --check

# 没有全局 Python 时
uv run --no-project python .agent-skills/tools/materialize_skills.py --repo . --check
```

映射固定为：

- `codex` → `.agents/skills/<name>`
- `claude` → `.claude/skills/<name>`

消费仓库应忽略生成物：

```gitignore
/.agents/skills/
/.claude/skills/
/.agent-skills.state.json
/.agent-skills.lock
```

中央子模块必须处于已有提交且工作树干净的状态；工具同时记录中央提交和每个 Skill 的内容摘要。它不会拉取远端、更新子模块、提交、跟随链接，或覆盖未经 state 与目录 marker 共同证明属于它的同名目录。

常用操作：

- `--dry-run`：显示会复制/清理的受管目录，不留下持久文件。
- `--check`：只检查提交版本、内容漂移、孤儿目录和 state；一致时退出码为 0，漂移为 1，配置或安全错误为 2。
- `--config <path>`：指定相对于 `--repo` 的消费声明。
- 把 `skills` 设为 `{}`：安全卸载 state 中最后一批受管 Skill。

生成目录内的手工修改会在下一次同步时被覆盖，不能作为工作副本。若 state 丢失而仍存在带 marker 的生成目录，工具会拒绝猜测所有权；应先恢复 `.agent-skills.state.json`，或人工确认后移除对应生成目录。崩溃遗留 `.agent-skills.lock` 时，也应先确认没有同步进程再删除锁。

生成副本不会自动随 clone 或云端会话出现；每次新 clone、中央子模块更新后都必须执行 materialize。云环境若不能在 Skill 扫描前运行该步骤，需要后续另行选择提交生成副本、setup hook 或插件方案。

## 本仓库校验

```powershell
uv run --cache-dir .uv-cache --no-project python tools/validate_catalog.py
uv run --cache-dir .uv-cache --no-project --with pytest python -m pytest tests skills/study-log/tests skills/learn-by-practice/tests -v
```

第二条命令同时覆盖仓库级测试、`study-log` 单元与安全测试，以及 rollback-only `learn-by-practice` 中仍保留的学习档案初始化器测试。

第三方版本由 `.gitmodules` 与 Git submodule 指针共同固定。更新第三方来源时，应先审阅上游变更，再更新对应指针和运行校验。
