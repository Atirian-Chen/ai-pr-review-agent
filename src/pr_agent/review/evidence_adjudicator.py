"""Adjudicate safe-tool evidence for a candidate review finding."""

from __future__ import annotations

import re

from pr_agent.review.schema import (
    FindingVerification,
    ReviewFinding,
    ToolKind,
    ToolResult,
    VerificationPlan,
    VerificationStatus,
)


ABSOLUTE_TEST_GAP_RE = re.compile(
    r"("
    r"\b(no|without|lacks?|lack of|absence of)\b.{0,80}\b(tests?|unit tests?|coverage)\b"
    r"|\b(no|missing)\s+unit\s+tests?\b"
    r"|\bno\s+tests?\s+(were\s+)?(added|included|provided)\b"
    r"|\bunit\s+tests?\s+(were\s+)?not\s+(added|included|provided)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def adjudicate_evidence(
    finding: ReviewFinding,
    plan: VerificationPlan,
    tool_results: list[ToolResult],
) -> FindingVerification:
    confidence_before = finding.confidence
    status, summary = _status_and_summary(finding, tool_results)
    if status == VerificationStatus.SUPPORTED:
        confidence_after = round(min(confidence_before + 0.10, 0.99), 4)
        publication_decision = "publish"
    elif status == VerificationStatus.CONTRADICTED:
        confidence_after = 0.0
        publication_decision = "suppress"
    elif status == VerificationStatus.INCONCLUSIVE:
        confidence_after = round(max(confidence_before - 0.10, 0.0), 4)
        publication_decision = _inconclusive_publication_decision(finding)
    elif status == VerificationStatus.SKIPPED:
        confidence_after = confidence_before
        publication_decision = "publish_with_warning" if finding.severity in {"critical", "major"} else "suppress"
    else:
        confidence_after = round(max(confidence_before - 0.05, 0.0), 4)
        publication_decision = "publish_with_warning" if finding.severity in {"critical", "major"} else "suppress"

    return FindingVerification(
        status=status,
        plan=plan,
        tool_results=tool_results,
        evidence_summary=summary,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        publication_decision=publication_decision,  # type: ignore[arg-type]
    )


def build_skipped_verification(
    finding: ReviewFinding,
    status: VerificationStatus,
    reason: str,
    plan: VerificationPlan | None = None,
) -> FindingVerification:
    return FindingVerification(
        status=status,
        plan=plan,
        tool_results=[],
        evidence_summary=reason,
        confidence_before=finding.confidence,
        confidence_after=finding.confidence,
        publication_decision="publish_with_warning" if finding.severity in {"critical", "major"} else "suppress",
    )


def _status_and_summary(finding: ReviewFinding, tool_results: list[ToolResult]) -> tuple[VerificationStatus, str]:
    if not tool_results:
        return VerificationStatus.SKIPPED, "No verification tools were executed."

    hard_failures = [result for result in tool_results if not result.success]
    if hard_failures and len(hard_failures) == len(tool_results):
        if any(_is_skipped_tool_result(result) for result in hard_failures):
            return VerificationStatus.SKIPPED, "; ".join(result.summary for result in hard_failures[:3])
        return VerificationStatus.ERROR, "; ".join(result.summary for result in hard_failures[:3])

    if _is_absolute_missing_test_claim(finding):
        test_discovery = [result for result in tool_results if result.tool == ToolKind.TEST_DISCOVERY and result.matched_paths]
        pytest_pass = [
            result
            for result in tool_results
            if result.tool == ToolKind.PYTEST and result.success and result.exit_code == 0
        ]
        if test_discovery:
            return (
                VerificationStatus.CONTRADICTED,
                "Related tests were found"
                + (" and the targeted test command passed." if pytest_pass else ".")
                + f" Evidence: {test_discovery[0].summary}",
            )

    failing_execution = [
        result
        for result in tool_results
        if result.tool in {ToolKind.PYTEST, ToolKind.RUFF, ToolKind.MYPY}
        and result.success
        and result.exit_code not in {None, 0}
    ]
    if failing_execution:
        result = failing_execution[0]
        return VerificationStatus.SUPPORTED, result.summary

    if finding.category == "bug" and _call_site_evidence(tool_results):
        return VerificationStatus.INCONCLUSIVE, "Repository search found related code, but no failing targeted check confirmed the issue."

    summaries = [result.summary for result in tool_results[:4]]
    return VerificationStatus.INCONCLUSIVE, "Tool evidence was inconclusive: " + " ".join(summaries)


def _is_absolute_missing_test_claim(finding: ReviewFinding) -> bool:
    text = "\n".join([finding.title, finding.description, finding.evidence, finding.suggestion])
    return bool(ABSOLUTE_TEST_GAP_RE.search(text))


def _call_site_evidence(tool_results: list[ToolResult]) -> bool:
    return any(result.tool == ToolKind.REPOSITORY_SEARCH and len(result.matched_paths) > 1 for result in tool_results)


def _is_skipped_tool_result(result: ToolResult) -> bool:
    text = result.summary.lower()
    return "docker is not available" in text or "timed out" in text or "skipped" in text


def _inconclusive_publication_decision(finding: ReviewFinding) -> str:
    if finding.severity in {"critical", "major"} and finding.confidence >= 0.8:
        return "publish_with_warning"
    return "suppress"
