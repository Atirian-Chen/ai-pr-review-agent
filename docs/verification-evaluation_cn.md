# Verification Evaluation

[English version](verification-evaluation.md)

## 数据集

Verification cases 位于：

```text
evaluation/verification_cases.jsonl
evaluation/fixtures/verification_cases/
```

Fixture index 覆盖：

- 被工具支持的真实 bug
- 被工具反驳的假阳性
- 工具无法证明或否定的 inconclusive finding

汇总数据集：

```powershell
pr-agent eval-verification --cases evaluation/verification_cases.jsonl
```

## 指标

v2.1 在 PR 级评测基础上扩展了：

- `verification_coverage`：eligible findings 中实际执行验证的比例。
- `supported_finding_rate`：被标记为 supported 的 finding 比例。
- `contradicted_suppression_rate`：被反驳后成功抑制的 finding 比例。
- `inconclusive_rate`：工具无法确认或反驳的 finding 比例。
- `sandbox_failure_rate`：Docker、timeout 或 sandbox tool 失败比例。
- `verification_latency_seconds`：验证耗时。
- `tool_cost`：static tool 调用、sandbox tool 调用和 LLM verifier 调用。

## v2 与 v2.1 对比

| Metric | v2 | v2.1 |
| --- | ---: | ---: |
| valid_finding_rate | yes | yes |
| false_positive_rate | yes | yes |
| line_hit_rate | yes | yes |
| fixability_rate | yes | yes |
| verification_coverage | no | yes |
| supported_finding_rate | no | yes |
| contradicted_suppression_rate | no | yes |
| average latency | yes | yes |
| p95 latency | yes | yes |
| token cost | yes | yes |

预期 tradeoff：

- false positives 应该下降
- valid finding rate 应该提升
- latency 会增加
- 如果 optional LLM verifier 没有大量使用，token cost 应该基本相近

## 重要评分规则

测试通过不足以反驳一个 bug finding。反驳必须有证据映射到 finding 的具体断言，例如相关测试覆盖了被声称缺失的行为，或者静态证据证明描述的路径不可能发生。
