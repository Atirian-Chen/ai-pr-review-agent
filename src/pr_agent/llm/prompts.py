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
- For missing-test findings, anchor file_path and line_start to the changed source line that needs coverage; put the target test file in test_suggestions.
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
      ],
      "patch_suggestion": {
        "description": "executable fix plan",
        "suggested_patch": "optional unified or focused patch snippet",
        "commands": ["optional command to validate the fix"]
      },
      "test_suggestions": [
        {
          "test_file_path": "tests/test_example.py",
          "test_name": "test_changed_behavior",
          "scenario": "behavior that should be covered",
          "assertions": ["expected assertion"],
          "suggested_test_code": "optional test code snippet"
        }
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


def build_specialized_review_system_prompt(role_name: str, focus: str, allowed_categories: list[str]) -> str:
    categories = "|".join(allowed_categories)
    return (
        GENERAL_REVIEW_SYSTEM_PROMPT
        + "\n\n"
        + f"You are the {role_name}. Focus only on: {focus}.\n"
        + f"Only emit findings whose category is one of: {categories}.\n"
        + "If the file has no issue in your focus area, return an empty findings array.\n"
        + "For every kept finding, include patch_suggestion and/or test_suggestions when a concrete action is possible."
    )


def build_specialized_review_user_prompt(context: ReviewContext, role_name: str, focus: str) -> str:
    return (
        f"Run the {role_name} pass for this file. Focus: {focus}. "
        "Do not duplicate issues outside your role.\n\n"
        + build_general_review_user_prompt(context)
    )
