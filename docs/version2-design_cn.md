# Version2 设计报告

[English version](version2-design.md)

## 目标

Version2 增加了三类 review 质量能力：

- Multi-Agent Reviewer：Bug Reviewer、Test Reviewer、Security Reviewer、Performance Reviewer 和 Coordinator。
- 每个 finding 中加入结构化 Patch Suggestion 和 Test Suggestion 字段。
- PR 级 Evaluation Report：统计 valid finding rate、line hit rate、false positive rate、fixability rate、latency 和 token cost。

## Multi-Agent Reviewer

当 `review.reviewer_mode` 为 `multi_agent` 时，主 LLM 会运行多个专门 pass：

- `bug`：运行时 bug、数据丢失、API 行为、边界条件。
- `test`：缺少回归测试和测试覆盖薄弱。
- `security`：注入、secret、权限、unsafe parsing、SSRF、不安全依赖。
- `performance`：N+1 调用、算法复杂度退化、重复昂贵操作、内存增长。

Coordinator 是确定性的。它不会创建新的 finding。它按文件、行、类别和规范化标题去重，并保留 severity/confidence 更高的候选。这避免多 agent 系统引入第二个 hallucination 来源。

## Patch 和 Test Suggestions

每个 `ReviewFinding` 可以包含：

- `patch_suggestion`：修复计划、可选 patch 片段和验证命令。
- `test_suggestions`：目标测试文件、测试名、场景、断言和可选测试代码。

旧的 `suggestion` 和 `suggested_patch` 字段仍然保留，用于向后兼容。

## Evaluation Report

新的 PR 评测数据集位于：

```text
evaluation/pr_cases.jsonl
```

它包含 25 个模拟 PR case，覆盖 bug、security、performance 和 test 类别的 ground truth finding。

不带 predictions 运行报告：

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl
```

运行可执行 benchmark。它会物化 runnable case，调用 reviewer，写出 predictions，然后生成报告：

```powershell
pr-agent eval-run --cases evaluation/runnable_pr_cases.jsonl --out examples/evaluation/run --llm-mode deterministic
```

使用 `--llm-mode live` 可以调用配置的 provider-backed Multi-Agent Reviewer，而不是 deterministic offline reviewer。

从已有 predictions 文件生成评分报告：

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl --predictions evaluation/pr_predictions.example.jsonl --out outputs/evaluation_report.json
```

指标：

- `valid_finding_rate`：预测 finding 中匹配 expected finding 的比例。
- `line_hit_rate`：期望的行级 finding 在配置 tolerance 内命中的比例。
- `false_positive_rate`：预测 finding 中不匹配任何 expected finding 的比例。
- `fixability_rate`：匹配且 fixable 的 finding 中包含 patch 或 test suggestion 的比例。
- `latency`：平均、p95 和总延迟。
- `token_cost`：平均 token、总 token 和可选总成本。
