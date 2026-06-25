# Agent Harness 设计

[English version](agent-harness-design.md)

这个项目可以理解为一个面向 AI 代码审查的只读 agent harness。LLM reviewer 只是其中一个组件。外层 harness 负责控制 reviewer 看到什么、多个 reviewer pass 如何运行、模型输出如何校验，以及最终结果如何报告和评测。

当前代码仍然保留 `runner`、`reviewer`、`ChangeSet` 等已有命名。本文解释 harness 边界，不要求重命名代码。

## Harness 边界

Harness 内部负责：

- Review target 解析：PR URL、commit URL、compare URL 或本地 git diff。
- Change 规范化：把不同来源统一成 `ChangeSet`。
- Diff 解析：把 patch 转成 hunk 和 changed-line record。
- 文件过滤：跳过生成文件、lock 文件、二进制文件、删除文件和过大的文件。
- 上下文构造：收集 diff、周边代码、README 摘要和相关测试候选。
- Reviewer 编排：运行单 agent 或多 agent 审查。
- 输出控制：要求结构化 finding，并尽可能恢复 JSON。
- Guardrail：校验文件路径、行号、置信度、证据、建议和 verifier 决策。
- 可观测性：写出 `review_result.json`、`review_report.md` 和 `trace.jsonl`。
- 评测：运行标签 case，统计有效 finding、行命中、假阳性、可修复性、延迟和 token 使用。

Harness 外部不做：

- 不执行目标仓库代码。
- 不自动应用 patch。
- 不给模型直接 shell 权限。
- 不维护长期 autonomous memory。
- 不声称是通用自动编码 agent harness。

这个边界是刻意设计的。项目重点是安全、可复现、理解仓库上下文的代码审查，而不是自动修改代码。

## 组件映射

| Harness 角色 | 当前模块 |
| --- | --- |
| Target 解析 | `src/pr_agent/targets/parser.py` |
| Target 加载与规范化 | `src/pr_agent/targets/loader.py` |
| 共享 change 模型 | `src/pr_agent/targets/models.py` |
| Diff 解析 | `src/pr_agent/diff/parser.py`, `src/pr_agent/diff/full_parser.py` |
| 文件过滤 | `src/pr_agent/diff/filters.py` |
| 上下文构造 | `src/pr_agent/context/retriever.py` |
| Reviewer 编排 | `src/pr_agent/review/runner.py` |
| 单 reviewer | `src/pr_agent/agents/general_reviewer.py` |
| 多 agent reviewer | `src/pr_agent/agents/multi_agent_reviewer.py` |
| 结构化输出 schema | `src/pr_agent/review/schema.py` |
| 确定性校验 | `src/pr_agent/review/validator.py`, `src/pr_agent/review/verifier.py` |
| 可选 LLM verifier | `src/pr_agent/review/llm_verifier.py` |
| 报告渲染 | `src/pr_agent/review/renderer.py` |
| GitHub Actions 入口 | `src/pr_agent/github/actions.py`, `src/pr_agent/cli.py` |
| GitHub summary comment | `src/pr_agent/github/comments.py` |
| 评测 harness | `src/pr_agent/evaluation/dataset.py`, `src/pr_agent/evaluation/runner.py` |

## 数据流

```text
Review target
  -> Target parser
  -> ChangeSet loader
  -> Diff parser
  -> File filter
  -> Context retriever
  -> Reviewer orchestration
       -> General reviewer
       -> 或 Bug/Test/Security/Performance reviewers + coordinator
  -> Schema validation
  -> Deterministic verifier
  -> Optional LLM verifier
  -> Result renderer
  -> Local artifacts and optional GitHub comment
```

本地 CLI review、GitHub Actions review 和可执行 PR 评测 runner 都复用同一条 harness 路径。这是架构重点：不同入口共享同一个 review runtime，而不是复制多套 review 逻辑。

## 为什么它算 Harness

在这个项目中，harness 是 LLM reviewer 外面的受控运行时。它提供任务输入、检索有限上下文、调用 reviewer agent、检查输出、记录 trace 并衡量质量。正是这一层把 prompt-based reviewer 变成可重复的工程流程。

最重要的 harness 特性：

- 有界 action space：reviewer 读 diff 和上下文，但不执行或修改目标代码。
- 可复用 runtime：CLI、GitHub Actions 和 evaluation 调用同一条 pipeline。
- 机器可校验输出：finding 必须通过 schema 和 validation gate。
- 可追踪性：每次运行都输出稳定 artifact 和 trace row。
- 可度量性：标签 case 可以衡量 pipeline 行为和 review 质量。

这个定位让项目保持诚实：它是 AI review harness，而不是完全自动修复 agent。
