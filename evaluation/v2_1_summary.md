# v2.1 Evaluation Summary

[中文版本](v2_1_summary_cn.md)

## Scope

This is a **small-scale local evaluation**, not a full benchmark.

Source artifacts:

- Main run: `outputs/live-e2e-expanded/case_manifest.json`
- Retry run: `outputs/live-e2e-expanded-retry-LIVE017/case_manifest.json`
- Manual report: `outputs/live-e2e-expanded/manual_judgement_report.md`

Run mode:

```text
--verify static
```

Because this run used static verification, sandbox tools such as `pytest`, `ruff`, and `mypy` were not executed. Most findings are therefore expected to remain `inconclusive`.

## Test Cases Run

| Item | Count |
| --- | ---: |
| Cases defined | 20 |
| Main-run completed cases | 19 |
| Main-run provider errors | 1 |
| Retried cases | 1 |
| Effective completed cases after retry | 20 |

The main run hit a provider disconnect on `LIVE017`. A single-case retry completed successfully.

## Verification Status Distribution

Distribution is counted over finding-level verification records from the 19 completed main-run cases plus the successful `LIVE017` retry.

| Status | Count |
| --- | ---: |
| `supported` | 0 |
| `contradicted` | 0 |
| `inconclusive` | 33 |
| `skipped` | 1 |

Interpretation:

- `supported = 0` is expected for this run because no sandbox tests or static checkers were executed.
- `contradicted = 0` means this run did not produce a direct evidence-based contradiction record.
- `inconclusive = 33` reflects the default static-mode behavior: tools can gather context but usually cannot prove runtime behavior.
- `skipped = 1` came from verification budget or tool applicability limits.

## Latency Stats

Case latency includes LLM review, validation, verification planning, static tool execution, evidence adjudication, and reporting for each completed case.

| Metric | Value |
| --- | ---: |
| Main-run total elapsed seconds | 1827.8 |
| Retry elapsed seconds | 84.5 |
| Combined elapsed seconds | 1912.3 |
| Average case latency seconds | 93.4 |
| Minimum case latency seconds | 39.0 |
| p95 case latency seconds | 142.6 |
| Maximum case latency seconds | 201.0 |
| Recorded verification-tool latency seconds | 0.781 |

Note: recorded verification-tool latency is much smaller than case latency because static tools are fast; most time is spent in LLM review and verifier calls.

## Tool Usage Counts

| Tool | Count |
| --- | ---: |
| `repository_search` | 30 |
| `test_discovery` | 24 |
| `read_file` | 1 |
| `pytest` | 0 |
| `ruff` | 0 |
| `mypy` | 0 |

Static tools dominated this run. Sandbox tools were not used because the run was explicitly executed with `--verify static`.

## Takeaways

- This small-scale local evaluation covered 20 live E2E cases across Python and C++.
- Static verification produced useful traceability and evidence artifacts, but did not usually produce `supported` decisions.
- The main practical value in this run was explaining why findings remained uncertain and exposing publication-quality issues such as duplicate findings or test-review noise.
- A future sandbox run with targeted tests is needed to measure `supported` and `contradicted` behavior more directly.
