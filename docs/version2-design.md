# Version2 Design Report

## Goals

Version2 adds three review-quality capabilities:

- Multi-Agent Reviewer: Bug Reviewer, Test Reviewer, Security Reviewer, Performance Reviewer, and a Coordinator.
- Structured Patch Suggestion and Test Suggestion fields in each finding.
- PR-level Evaluation Report for valid finding rate, line hit rate, false positive rate, fixability rate, latency, and token cost.

## Multi-Agent Reviewer

The primary LLM now runs multiple specialized passes when `review.reviewer_mode` is `multi_agent`:

- `bug`: runtime bugs, data loss, API behavior, edge cases.
- `test`: missing regression tests and weak test coverage.
- `security`: injection, secrets, auth, unsafe parsing, SSRF, unsafe dependencies.
- `performance`: N+1 calls, algorithmic regressions, repeated expensive work, memory growth.

The Coordinator is deterministic. It does not create new findings. It deduplicates by file, line, category, and normalized title, then keeps the highest-severity/highest-confidence candidate. This keeps the multi-agent system from adding a second source of hallucinated findings.

## Patch and Test Suggestions

Each `ReviewFinding` can now include:

- `patch_suggestion`: a fix plan, optional patch snippet, and validation commands.
- `test_suggestions`: target test file, test name, scenario, assertions, and optional test code.

The older `suggestion` and `suggested_patch` fields remain supported for backward compatibility.

## Evaluation Report

The new PR evaluation dataset lives at:

```text
evaluation/pr_cases.jsonl
```

It contains 25 simulated PR cases with ground-truth expected findings across bug, security, performance, and test categories.

Run a report without predictions:

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl
```

Run the executable benchmark. This materializes runnable cases, invokes the reviewer, writes predictions, and then builds the report:

```powershell
pr-agent eval-run --cases evaluation/runnable_pr_cases.jsonl --out examples/evaluation/run --llm-mode deterministic
```

Use `--llm-mode live` to call the configured provider-backed Multi-Agent Reviewer instead of the deterministic offline reviewer.

Run a scored report from an existing predictions file:

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl --predictions evaluation/pr_predictions.example.jsonl --out outputs/evaluation_report.json
```

Metrics:

- `valid_finding_rate`: predicted findings that match expected findings.
- `line_hit_rate`: expected line-level findings hit within the configured tolerance.
- `false_positive_rate`: predicted findings that do not match any expected finding.
- `fixability_rate`: matched fixable findings that include patch or test suggestions.
- `latency`: average, p95, and total latency.
- `token_cost`: average tokens, total tokens, and optional total cost.
