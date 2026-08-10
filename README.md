# Agent Skills

这是三个学习/工作主仓库的 Skill 规范源。第一阶段只做迁移、分类、来源固定和可重复校验；质量评分、功能合并及内容升级会在后续逐项讨论并经确认后进行。

## 当前范围

- 7 个自创 Skill 保存在 [`skills/`](skills/)；迁移时保留原内容。
- 5 个第三方 Skill 从 3 个官方 Git 子模块读取；不在本仓库复制第三方源码。
- PlanA 的 PyTorch、SGLang、vLLM 源码子模块自带 Skill 不迁移、不登记。
- Remotion 只暴露官方聚合入口 `remotion-best-practices`，不再保留功能重复的独立入口。

完整来源、分类、状态和消费仓库记录在 [`catalog.json`](catalog.json)，迁移边界及已知问题记录在 [`docs/migration-baseline.md`](docs/migration-baseline.md)。

## 目录

```text
agent-skills/
├── skills/                    # 自创 Skill 的唯一规范副本
├── vendor/                    # 第三方官方仓库（Git submodule）
├── tools/                     # 清单校验与消费仓库同步工具
├── tests/                     # 仓库级测试
├── catalog.json               # 机器可读的分类与来源清单
└── .agent-skills.example.json # 消费仓库声明示例
```

## 消费方式

后续每个消费仓库把本仓库加入为 `.agent-skills` 子模块，并提交自己的 `.agent-skills.json`：

```json
{
  "version": 1,
  "source": ".agent-skills",
  "skills": {
    "study-companion": ["codex", "claude"]
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
uv run --no-project python tools/validate_catalog.py
uv run --no-project python -m unittest discover -s tests -v
```

第三方版本由 `.gitmodules` 与 Git submodule 指针共同固定。更新第三方来源时，应先审阅上游变更，再更新对应指针和运行校验。
