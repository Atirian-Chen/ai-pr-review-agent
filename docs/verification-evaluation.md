# Verification Evaluation

[中文版本](verification-evaluation_cn.md)

## Dataset

Verification cases live at:

```text
evaluation/verification_cases.jsonl
evaluation/fixtures/verification_cases/
```

The fixture index covers:

- supported true bugs
- contradicted false positives
- inconclusive findings where tools cannot prove or disprove the claim

Summarize the dataset:

```powershell
pr-agent eval-verification --cases evaluation/verification_cases.jsonl
```

## Metrics

v2.1 extends PR-level evaluation with:

- `verification_coverage`: eligible findings that actually executed verification.
- `supported_finding_rate`: findings marked supported.
- `contradicted_suppression_rate`: contradicted findings that were suppressed.
- `inconclusive_rate`: findings that tools could not confirm or refute.
- `sandbox_failure_rate`: Docker, timeout, or sandbox tool failures.
- `verification_latency_seconds`: verification latency.
- `tool_cost`: static tool calls, sandbox tool calls, and LLM verifier calls.

## v2 Compared With v2.1

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

Expected tradeoff:

- false positives should go down
- valid finding rate should improve
- latency increases
- token cost should remain similar unless the optional LLM verifier is used heavily

## Important Scoring Rule

Passing tests are not enough to contradict a bug finding. A contradiction requires evidence that maps to the finding's concrete assertion, such as a related test covering the claimed missing behavior or static evidence proving the described path cannot occur.
