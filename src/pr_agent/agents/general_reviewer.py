"""GeneralReviewer：MVP 的单 Agent reviewer，后续可拆成多个 specialized reviewers。"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import ValidationError

from pr_agent.context.models import ReviewContext
from pr_agent.llm.client import LLMClient
from pr_agent.llm.prompts import GENERAL_REVIEW_SYSTEM_PROMPT, build_general_review_user_prompt
from pr_agent.review.schema import ReviewFinding


class GeneralReviewer:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def review_context(self, context: ReviewContext) -> tuple[str, list[ReviewFinding], dict[str, Any]]:
        response = self.llm_client.complete_json(
            system_prompt=GENERAL_REVIEW_SYSTEM_PROMPT,
            user_prompt=build_general_review_user_prompt(context),
        )
        summary = str(response.data.get("summary") or f"Reviewed {context.file.filename}.")
        raw_findings = response.data.get("findings") or []
        if not isinstance(raw_findings, list):
            raw_findings = []

        findings: list[ReviewFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_finding(item, context.file.filename)
            try:
                findings.append(ReviewFinding.model_validate(normalized))
            except ValidationError:
                # 单条 finding 结构坏了就丢弃，避免一个坏结果拖垮整次 review。
                continue

        stats = {
            "latency_seconds": response.latency_seconds,
            "usage": response.usage,
            "total_tokens": response.usage.get("total_tokens", 0),
            "model": response.model,
        }
        return summary, findings, stats


def _normalize_finding(item: dict[str, Any], fallback_file_path: str, default_reviewer: str = "general") -> dict[str, Any]:
    file_path = item.get("file_path") or fallback_file_path
    title = str(item.get("title") or "Untitled finding")
    category = item.get("category") or "maintainability"
    line_start = item.get("line_start")
    false_positive_checks = item.get("false_positive_checks") or []
    if isinstance(false_positive_checks, str):
        false_positive_checks = [false_positive_checks]
    elif not isinstance(false_positive_checks, list):
        false_positive_checks = []
    patch_suggestion = _normalize_patch_suggestion(item)
    test_suggestions = _normalize_test_suggestions(item)
    fingerprint = hashlib.sha1(f"{file_path}:{category}:{line_start}:{title}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": item.get("id") or f"finding-{fingerprint}",
        "file_path": file_path,
        "line_start": line_start,
        "line_end": item.get("line_end"),
        "category": category,
        "severity": item.get("severity") or "minor",
        "confidence": item.get("confidence", 0.0),
        "title": title,
        "description": item.get("description") or item.get("why_it_matters") or "",
        "evidence": item.get("evidence") or "",
        "suggestion": item.get("suggestion") or "",
        "suggested_patch": item.get("suggested_patch"),
        "failure_mode": item.get("failure_mode"),
        "why_introduced_by_diff": item.get("why_introduced_by_diff"),
        "false_positive_checks": false_positive_checks,
        "patch_suggestion": patch_suggestion,
        "test_suggestions": test_suggestions,
        "reviewer": item.get("reviewer") or default_reviewer,
    }


def _normalize_patch_suggestion(item: dict[str, Any]) -> dict[str, Any] | None:
    raw = item.get("patch_suggestion")
    if isinstance(raw, dict):
        return {
            "description": raw.get("description") or item.get("suggestion") or "Apply the suggested fix.",
            "suggested_patch": raw.get("suggested_patch") or item.get("suggested_patch"),
            "commands": _string_list(raw.get("commands")),
        }
    if item.get("suggested_patch"):
        return {
            "description": item.get("suggestion") or "Apply the suggested patch.",
            "suggested_patch": item.get("suggested_patch"),
            "commands": [],
        }
    return None


def _normalize_test_suggestions(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw = item.get("test_suggestions") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    suggestions: list[dict[str, Any]] = []
    for suggestion in raw:
        if not isinstance(suggestion, dict):
            continue
        suggestions.append(
            {
                "test_file_path": suggestion.get("test_file_path"),
                "test_name": suggestion.get("test_name") or "test_new_behavior",
                "scenario": suggestion.get("scenario") or suggestion.get("description") or "Cover the changed behavior.",
                "assertions": _string_list(suggestion.get("assertions")),
                "suggested_test_code": suggestion.get("suggested_test_code"),
            }
        )
    return suggestions


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]
