"""Prompt 模板：MVP 使用单个 GeneralReviewer，但要求输出保守、结构化 JSON。"""

from __future__ import annotations

import json

from pr_agent.context.models import ReviewContext


GENERAL_REVIEW_SYSTEM_PROMPT = """
You are a senior software engineer reviewing a GitHub Pull Request.

Review conservatively:
- Only report issues supported by the diff or provided repository context.
- Do not speculate about code that is not shown.
- Every finding should be tied to a changed line or directly affected line when possible.
- Prefer actionable issues over style comments.
- Do not comment on unchanged code unless it is directly affected by the PR.
- Treat every issue as a candidate that must survive false-positive checks.
- Do not report "missing tests" if related tests are shown, changed, or clearly exist in the provided context.
- Do not report a possible None/null AttributeError when the shown schema/model definition makes the field required or gives it a non-null default.
- Do not report an incorrect CLI command unless the provided code or docs contradict the command name.
- For each finding, explain the concrete failure path and why the current diff introduces it.
- If no clear issue is found, return {"summary": "...", "findings": []}.

Return JSON only with this shape:
{
  "summary": "short summary of the review",
  "findings": [
    {
      "file_path": "...",
      "line_start": 123,
      "line_end": 123,
      "category": "bug|security|performance|maintainability|test|style",
      "severity": "critical|major|minor|nit",
      "confidence": 0.85,
      "title": "...",
      "description": "...",
      "evidence": "...",
      "suggestion": "...",
      "suggested_patch": null,
      "failure_mode": "input/state -> changed behavior -> observable failure",
      "why_introduced_by_diff": "which changed line or removed guard makes this possible",
      "false_positive_checks": [
        "related tests/context/schema/CLI definitions checked before reporting"
      ]
    }
  ]
}
""".strip()


def build_general_review_user_prompt(context: ReviewContext) -> str:
    payload = {
        "pr": {
            "title": context.pr.title,
            "body": context.pr.body,
            "base_branch": context.pr.base_branch,
            "head_branch": context.pr.head_branch,
        },
        "changed_file": {
            "filename": context.file.filename,
            "status": context.file.status,
            "additions": context.file.additions,
            "deletions": context.file.deletions,
            "changes": context.file.changes,
        },
        "diff_patch": context.target_file_patch,
        "surrounding_code": context.surrounding_code,
        "related_test_file_candidates": context.related_test_files,
        "repo_readme_excerpt": context.repo_readme_excerpt,
    }
    return (
        "Review the following PR file context. Focus on bug, security, performance, "
        "maintainability, and missing-test risks introduced by this PR. "
        "Before reporting, actively look for context that disproves the issue. "
        "If the issue depends on an assumption not proven by the diff or context, do not report it.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
