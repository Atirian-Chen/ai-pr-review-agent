"""Multi-agent reviewer orchestration for version2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from pr_agent.agents.general_reviewer import _normalize_finding
from pr_agent.context.models import ReviewContext
from pr_agent.llm.client import LLMClient, LLMOutputError
from pr_agent.llm.prompts import build_specialized_review_system_prompt, build_specialized_review_user_prompt
from pr_agent.review.schema import ReviewFinding


@dataclass(frozen=True)
class ReviewerSpec:
    reviewer_id: str
    role_name: str
    focus: str
    allowed_categories: tuple[str, ...]


DEFAULT_REVIEWER_SPECS: tuple[ReviewerSpec, ...] = (
    ReviewerSpec(
        reviewer_id="bug",
        role_name="Bug Reviewer",
        focus="runtime bugs, broken control flow, data loss, incorrect API behavior, edge-case failures",
        allowed_categories=("bug", "maintainability"),
    ),
    ReviewerSpec(
        reviewer_id="test",
        role_name="Test Reviewer",
        focus="missing or weak tests for changed behavior, regression coverage, testability of the patch",
        allowed_categories=("test",),
    ),
    ReviewerSpec(
        reviewer_id="security",
        role_name="Security Reviewer",
        focus="injection, unsafe secrets handling, authorization bypass, unsafe dependencies, exposed credentials",
        allowed_categories=("security",),
    ),
    ReviewerSpec(
        reviewer_id="performance",
        role_name="Performance Reviewer",
        focus="algorithmic regressions, repeated network/file calls, unnecessary expensive work, scalability issues",
        allowed_categories=("performance",),
    ),
)


class MultiAgentReviewer:
    def __init__(self, llm_client: LLMClient, reviewer_specs: tuple[ReviewerSpec, ...] = DEFAULT_REVIEWER_SPECS) -> None:
        self.llm_client = llm_client
        self.reviewer_specs = reviewer_specs

    def review_context(self, context: ReviewContext) -> tuple[str, list[ReviewFinding], dict[str, Any]]:
        all_findings: list[ReviewFinding] = []
        summaries: list[str] = []
        reviewer_stats: dict[str, Any] = {}
        total_tokens = 0
        latency_seconds = 0.0
        model_name = ""

        for spec in self.reviewer_specs:
            summary, findings, stats = self._review_with_spec(context, spec)
            summaries.append(f"{spec.role_name}: {summary}")
            all_findings.extend(findings)
            reviewer_stats[spec.reviewer_id] = stats
            total_tokens += int(stats.get("total_tokens") or 0)
            latency_seconds += float(stats.get("latency_seconds") or 0.0)
            model_name = str(stats.get("model") or model_name)

        coordinated = FindingCoordinator().coordinate(all_findings)
        stats = {
            "latency_seconds": latency_seconds,
            "total_tokens": total_tokens,
            "model": model_name,
            "reviewer_mode": "multi_agent",
            "reviewer_stats": reviewer_stats,
            "coordinator": {
                "input_findings": len(all_findings),
                "output_findings": len(coordinated),
                "reviewers": [spec.reviewer_id for spec in self.reviewer_specs],
            },
        }
        return _merge_role_summaries(summaries, context.file.filename), coordinated, stats

    def _review_with_spec(self, context: ReviewContext, spec: ReviewerSpec) -> tuple[str, list[ReviewFinding], dict[str, Any]]:
        try:
            response = self.llm_client.complete_json(
                system_prompt=build_specialized_review_system_prompt(
                    spec.role_name,
                    spec.focus,
                    list(spec.allowed_categories),
                ),
                user_prompt=build_specialized_review_user_prompt(context, spec.role_name, spec.focus),
            )
        except LLMOutputError as exc:
            return (
                f"{spec.role_name} skipped because the model returned invalid JSON.",
                [],
                {
                    "latency_seconds": 0.0,
                    "usage": {},
                    "total_tokens": 0,
                    "model": "",
                    "findings": 0,
                    "status": "invalid_json",
                    "error": str(exc),
                },
            )
        raw_findings = response.data.get("findings") or []
        if not isinstance(raw_findings, list):
            raw_findings = []

        findings: list[ReviewFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_finding(item, context.file.filename, default_reviewer=spec.reviewer_id)
            if normalized["category"] not in spec.allowed_categories:
                continue
            normalized["reviewer"] = spec.reviewer_id
            try:
                findings.append(ReviewFinding.model_validate(normalized))
            except ValidationError:
                continue

        stats = {
            "latency_seconds": response.latency_seconds,
            "usage": response.usage,
            "total_tokens": response.usage.get("total_tokens", 0),
            "model": response.model,
            "findings": len(findings),
        }
        summary = str(response.data.get("summary") or f"No {spec.reviewer_id} findings for {context.file.filename}.")
        return summary, findings, stats


class FindingCoordinator:
    def coordinate(self, findings: list[ReviewFinding]) -> list[ReviewFinding]:
        by_key: dict[tuple[str, int | None, str, str], ReviewFinding] = {}
        for finding in findings:
            key = (
                finding.file_path,
                finding.line_start,
                finding.category,
                _normalize_title(finding.title),
            )
            existing = by_key.get(key)
            if existing is None or _finding_rank(finding) < _finding_rank(existing):
                by_key[key] = finding

        return sorted(
            by_key.values(),
            key=lambda item: (_severity_rank(item.severity), -item.confidence, item.file_path, item.line_start or 0),
        )


def _finding_rank(finding: ReviewFinding) -> tuple[int, float]:
    return (_severity_rank(finding.severity), -finding.confidence)


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "major": 1, "minor": 2, "nit": 3}.get(severity, 4)


def _normalize_title(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(words[:8])


def _merge_role_summaries(summaries: list[str], filename: str) -> str:
    non_empty = [summary for summary in summaries if summary.strip()]
    if not non_empty:
        return f"Multi-agent review completed for {filename}; no clear issues were found."
    return f"Multi-agent review completed for {filename}. " + " ".join(non_empty[:4])
