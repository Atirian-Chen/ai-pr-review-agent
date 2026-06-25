# Evaluation Dataset

This directory contains a JSONL evaluation dataset for the AI PR Review Agent.

## Files

- `cases.jsonl`: 50 labeled cases covering target parsing, diff parsing, file filtering, GitHub Actions event resolution, summary comment rendering, schema validation, changeset loading, and issue detection.
- `pr_cases.jsonl`: 25 PR-level simulated cases with expected findings for bug, security, performance, and test review quality.
- `runnable_pr_cases.jsonl`: 20 executable simulated cases with base/head file content.
- `pr_predictions.example.jsonl`: Example PR prediction records for `eval-report`.
- `verification_cases.jsonl`: v2.1 verification cases covering supported, contradicted, and inconclusive evidence outcomes.
- `fixtures/verification_cases/`: Small repositories used by verification cases.

## Run

```powershell
pr-agent eval-dataset --dataset evaluation/cases.jsonl
```

To score model or pipeline predictions, provide a JSONL file with one record per case:

```json
{"case_id":"ID001","predicted_categories":["bug"]}
{"case_id":"TP001","passed":true}
```

Then run:

```powershell
pr-agent eval-dataset --dataset evaluation/cases.jsonl --predictions evaluation/predictions.jsonl --out outputs/eval_report.json
```

The report includes dataset coverage plus optional accuracy, issue-category precision, recall, and F1.

## PR-Level Evaluation Report

Run the reviewer over executable cases and build a real report:

```powershell
pr-agent eval-run --cases evaluation/runnable_pr_cases.jsonl --out examples/evaluation/run --llm-mode deterministic
```

This writes:

- `examples/evaluation/run/pr_predictions.jsonl`
- `examples/evaluation/run/evaluation_report.json`
- per-case review outputs under `examples/evaluation/run/cases/`

Run the PR-level report without predictions:

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl
```

Run it with predictions:

```powershell
pr-agent eval-report --cases evaluation/pr_cases.jsonl --predictions evaluation/pr_predictions.example.jsonl --out outputs/pr_evaluation_report.json
```

Each prediction record contains the case id, predicted findings, latency, tokens, and optional cost:

```json
{"case_id":"PR001","findings":[{"category":"bug","file_path":"src/api/profile.py","line_start":42,"title":"Unauthenticated branch can dereference a missing user","has_patch_suggestion":true,"has_test_suggestion":true}],"latency_seconds":12.4,"total_tokens":8200,"cost_usd":0.012}
```

The PR-level report includes:

- `valid_finding_rate`
- `line_hit_rate`
- `false_positive_rate`
- `fixability_rate`
- latency average/p95/total
- token total/average and optional cost
- v2.1 verification metrics: coverage, supported rate, contradicted suppression rate, inconclusive rate, sandbox failure rate, and tool cost

## Verification Evaluation

Summarize v2.1 verification cases:

```powershell
pr-agent eval-verification --cases evaluation/verification_cases.jsonl --out outputs/verification_evaluation_report.json
```

The expected statuses are:

- `supported`: tool evidence supports the finding.
- `contradicted`: tool evidence refutes the finding and the finding should be suppressed.
- `inconclusive`: tools could not confirm or refute the finding.
