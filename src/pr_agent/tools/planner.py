"""Conservative verification planner for candidate findings."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from pr_agent.context.retriever import infer_related_test_files
from pr_agent.review.schema import ReviewFinding, ToolKind, VerificationPlan


IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")
NOISY_TERMS = {
    "add",
    "added",
    "branch",
    "changed",
    "could",
    "error",
    "file",
    "finding",
    "line",
    "missing",
    "none",
    "null",
    "return",
    "test",
    "tests",
    "this",
    "with",
}


def plan_for_finding(finding: ReviewFinding) -> VerificationPlan:
    intent = finding.verification_intent
    if intent and not intent.needs_verification:
        requested_tools = [ToolKind.REPOSITORY_SEARCH]
    elif intent and intent.preferred_tools:
        requested_tools = intent.preferred_tools
    else:
        requested_tools = _default_tools(finding)

    search_terms = []
    if intent:
        search_terms.extend(intent.search_terms)
    search_terms.extend(_extract_search_terms(finding))

    candidate_tests = []
    for suggestion in finding.test_suggestions:
        if suggestion.test_file_path:
            candidate_tests.append(suggestion.test_file_path)
    if intent and intent.candidate_test_file:
        candidate_tests.append(intent.candidate_test_file)
    candidate_tests.extend(infer_related_test_files(finding.file_path))

    goal = f"Collect repository evidence for finding {finding.id}: {finding.title}"
    rationale = f"{finding.category} findings are verified with category-specific read-only tools and, when allowed, minimal sandbox checks."
    return VerificationPlan(
        finding_id=finding.id,
        goal=goal,
        requested_tools=list(dict.fromkeys(requested_tools)),
        search_terms=list(dict.fromkeys(search_terms))[:8],
        candidate_test_paths=list(dict.fromkeys(candidate_tests))[:8],
        rationale=rationale,
        risk_level="medium" if finding.category == "security" else "low",
    )


def _default_tools(finding: ReviewFinding) -> list[ToolKind]:
    if finding.category == "bug":
        tools = [ToolKind.REPOSITORY_SEARCH, ToolKind.READ_FILE, ToolKind.TEST_DISCOVERY]
        if finding.test_suggestions:
            tools.append(ToolKind.PYTEST)
        return tools
    if finding.category == "test":
        return [ToolKind.REPOSITORY_SEARCH, ToolKind.TEST_DISCOVERY, ToolKind.PYTEST]
    if finding.category == "security":
        return [ToolKind.REPOSITORY_SEARCH, ToolKind.READ_FILE, ToolKind.DEPENDENCY_INSPECTION, ToolKind.RUFF]
    if finding.category == "performance":
        return [ToolKind.REPOSITORY_SEARCH, ToolKind.READ_FILE, ToolKind.TEST_DISCOVERY]
    if finding.category == "style":
        return [ToolKind.READ_FILE, ToolKind.RUFF]
    return [ToolKind.REPOSITORY_SEARCH, ToolKind.READ_FILE, ToolKind.TEST_DISCOVERY]


def _extract_search_terms(finding: ReviewFinding) -> list[str]:
    text = "\n".join(
        [
            finding.title,
            finding.description,
            finding.evidence,
            finding.suggestion,
            finding.failure_mode or "",
            finding.why_introduced_by_diff or "",
            PurePosixPath(finding.file_path).stem,
        ]
    )
    terms = []
    for term in IDENTIFIER_RE.findall(text):
        lowered = term.lower()
        if lowered in NOISY_TERMS or len(term) > 80:
            continue
        terms.append(term)
    return list(dict.fromkeys(terms))[:8]
