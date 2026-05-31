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
      "suggested_patch": null
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
        "maintainability, and missing-test risks introduced by this PR.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
