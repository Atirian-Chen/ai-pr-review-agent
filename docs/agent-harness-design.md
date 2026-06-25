# Agent Harness Design

[中文版本](agent-harness-design_cn.md)

This project can be described as a read-only agent harness for AI code review. The
LLM reviewer is only one component. The surrounding harness controls what the
reviewer sees, how multiple reviewer passes are invoked, how model output is
validated, and how the final result is reported and evaluated.

The current code keeps the existing names such as `runner`, `reviewer`, and
`ChangeSet`. This document explains the harness boundary without requiring code
renaming.

## Harness Boundary

Inside the harness:

- Review target resolution: PR URL, commit URL, compare URL, or local git diff.
- Change normalization: convert every source into a shared `ChangeSet`.
- Diff parsing: convert patches into hunks and changed-line records.
- File filtering: skip generated, lock, binary, removed, and oversized files.
- Context construction: gather diff text, nearby code, README excerpts, and related test candidates.
- Reviewer orchestration: run single-agent or multi-agent review passes.
- Output control: require structured findings and recover JSON when possible.
- Guardrails: validate file paths, line numbers, confidence, evidence, suggestions, and verifier decisions.
- Observability: write `review_result.json`, `review_report.md`, and `trace.jsonl`.
- Evaluation: run labeled cases and score valid finding rate, line hit rate, false positives, fixability, latency, and token use.

Outside the harness:

- It does not execute target repository code.
- It does not apply patches automatically.
- It does not give the model direct shell access.
- It does not maintain long-term autonomous memory.
- It does not claim to be a general-purpose coding agent harness.

This boundary is intentional. The project focuses on safe, reproducible,
repository-aware review rather than autonomous code modification.

## Component Mapping

| Harness role | Current module |
| --- | --- |
| Target parsing | `src/pr_agent/targets/parser.py` |
| Target loading and normalization | `src/pr_agent/targets/loader.py` |
| Shared change model | `src/pr_agent/targets/models.py` |
| Diff parsing | `src/pr_agent/diff/parser.py`, `src/pr_agent/diff/full_parser.py` |
| File filtering | `src/pr_agent/diff/filters.py` |
| Context construction | `src/pr_agent/context/retriever.py` |
| Reviewer orchestration | `src/pr_agent/review/runner.py` |
| Single reviewer | `src/pr_agent/agents/general_reviewer.py` |
| Multi-agent reviewer | `src/pr_agent/agents/multi_agent_reviewer.py` |
| Structured output schema | `src/pr_agent/review/schema.py` |
| Deterministic validation | `src/pr_agent/review/validator.py`, `src/pr_agent/review/verifier.py` |
| Optional LLM verifier | `src/pr_agent/review/llm_verifier.py` |
| Report rendering | `src/pr_agent/review/renderer.py` |
| GitHub Actions entry point | `src/pr_agent/github/actions.py`, `src/pr_agent/cli.py` |
| GitHub summary comments | `src/pr_agent/github/comments.py` |
| Evaluation harness | `src/pr_agent/evaluation/dataset.py`, `src/pr_agent/evaluation/runner.py` |

## Data Flow

```text
Review target
  -> Target parser
  -> ChangeSet loader
  -> Diff parser
  -> File filter
  -> Context retriever
  -> Reviewer orchestration
       -> General reviewer
       -> or Bug/Test/Security/Performance reviewers + coordinator
  -> Schema validation
  -> Deterministic verifier
  -> Optional LLM verifier
  -> Result renderer
  -> Local artifacts and optional GitHub comment
```

The same harness path is reused by local CLI review, GitHub Actions review, and
the executable PR evaluation runner. This is the main architectural point:
different entry points share one review runtime instead of duplicating review
logic.

## Why This Counts as a Harness

In this project, the harness is the controlled runtime around the LLM reviewer.
It provides the task input, retrieves bounded context, invokes reviewer agents,
checks outputs, records traces, and measures quality. That is the layer that
turns a prompt-based reviewer into a repeatable engineering workflow.

The most important harness properties are:

- Bounded action space: the reviewer reads diffs and context but does not execute or modify target code.
- Reusable runtime: CLI, GitHub Actions, and evaluation all call the same review pipeline.
- Machine-checkable output: findings must pass schema and validation gates.
- Traceability: every run emits stable artifacts and trace rows.
- Measurability: labeled cases can score both pipeline behavior and review quality.

This framing keeps the project honest: it is an AI review harness, not a fully
autonomous repair agent.
