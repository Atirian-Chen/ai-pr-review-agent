# v2.1 评估摘要

[English version](v2_1_summary.md)

## 范围

这是一次 **small-scale local evaluation（小规模本地评估）**，不是完整 benchmark。

来源 artifact：

- 主跑：`outputs/live-e2e-expanded/case_manifest.json`
- 重试：`outputs/live-e2e-expanded-retry-LIVE017/case_manifest.json`
- 人工报告：`outputs/live-e2e-expanded/manual_judgement_report.md`

运行模式：

```text
--verify static
```

因为这轮使用 static verification，`pytest`、`ruff`、`mypy` 等 sandbox 工具没有执行。因此，大部分 finding 的验证结果保持 `inconclusive` 是符合预期的。

## 运行的测试用例数量

| 项目 | 数量 |
| --- | ---: |
| 定义的 case | 20 |
| 主跑完成 case | 19 |
| 主跑 provider 错误 | 1 |
| 重试 case | 1 |
| 重试后有效完成 case | 20 |

主跑时 `LIVE017` 遇到 provider 断连。之后单独重试该 case，并成功完成。

## Verification Status 分布

分布统计的是 finding 级 verification record，来源为主跑完成的 19 条 case 加上 `LIVE017` 成功重试结果。

| 状态 | 数量 |
| --- | ---: |
| `supported` | 0 |
| `contradicted` | 0 |
| `inconclusive` | 33 |
| `skipped` | 1 |

解释：

- `supported = 0` 是预期结果，因为这轮没有执行 sandbox 测试或静态检查器。
- `contradicted = 0` 表示这轮没有产生直接被工具证据反驳的 finding record。
- `inconclusive = 33` 反映 static 模式的默认特点：工具可以收集上下文，但通常不能证明运行时行为。
- `skipped = 1` 来自 verification budget 或工具适用性限制。

## 延迟统计

Case latency 包含每条 completed case 的 LLM review、validation、verification planning、static tool execution、evidence adjudication 和 report 生成。

| 指标 | 数值 |
| --- | ---: |
| 主跑总耗时（秒） | 1827.8 |
| 重试耗时（秒） | 84.5 |
| 合计耗时（秒） | 1912.3 |
| 平均 case latency（秒） | 93.4 |
| 最小 case latency（秒） | 39.0 |
| p95 case latency（秒） | 142.6 |
| 最大 case latency（秒） | 201.0 |
| 记录到的 verification tool latency（秒） | 0.781 |

说明：verification tool latency 远小于 case latency，因为 static 工具很快；主要耗时来自 LLM review 和 verifier 调用。

## Tool Usage Counts

| 工具 | 次数 |
| --- | ---: |
| `repository_search` | 30 |
| `test_discovery` | 24 |
| `read_file` | 1 |
| `pytest` | 0 |
| `ruff` | 0 |
| `mypy` | 0 |

这轮主要使用 static 工具。由于命令明确使用 `--verify static`，sandbox 工具没有运行。

## 结论

- 这次小规模本地评估覆盖了 20 条 Python 与 C++ live E2E case。
- Static verification 提供了有用的 trace 和 evidence artifact，但通常不会产生 `supported` 决策。
- 这轮最主要的价值是说明 finding 为什么仍然不确定，并暴露发布质量问题，例如重复 finding 和 test-review 噪音。
- 如果后续要更直接衡量 `supported` 和 `contradicted` 行为，需要用 sandbox 模式运行定向测试。
