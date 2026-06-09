# Evaluation Dataset

This directory contains a JSONL evaluation dataset for the AI PR Review Agent.

## Files

- `cases.jsonl`: 50 labeled cases covering target parsing, diff parsing, file filtering, GitHub Actions event resolution, summary comment rendering, schema validation, changeset loading, and issue detection.

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
