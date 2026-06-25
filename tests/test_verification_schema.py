import pytest
from pydantic import ValidationError

from pr_agent.review.schema import (
    FindingVerification,
    ReviewFinding,
    ToolKind,
    ToolResult,
    VerificationIntent,
    VerificationPlan,
    VerificationStatus,
)


def test_tool_kind_and_verification_status_values():
    assert ToolKind.REPOSITORY_SEARCH.value == "repository_search"
    assert ToolKind.PYTEST.value == "pytest"
    assert VerificationStatus.SUPPORTED.value == "supported"
    assert VerificationStatus.CONTRADICTED.value == "contradicted"
    assert VerificationStatus.INCONCLUSIVE.value == "inconclusive"


def test_verification_plan_requires_tools_and_rationale():
    with pytest.raises(ValidationError):
        VerificationPlan(
            finding_id="F-1",
            goal="Check behavior",
            requested_tools=[],
            rationale="Use safe tools.",
            risk_level="low",
        )


def test_verification_plan_deduplicates_tools_and_terms():
    plan = VerificationPlan(
        finding_id="F-1",
        goal="Check behavior",
        requested_tools=[ToolKind.REPOSITORY_SEARCH, ToolKind.REPOSITORY_SEARCH],
        search_terms=["parse_config", "parse_config", ""],
        rationale="Use safe tools.",
        risk_level="low",
    )

    assert plan.requested_tools == [ToolKind.REPOSITORY_SEARCH]
    assert plan.search_terms == ["parse_config", "parse_config"]


def test_review_finding_accepts_verification_intent():
    finding = _finding(
        verification_intent=VerificationIntent(
            preferred_tools=[ToolKind.REPOSITORY_SEARCH],
            search_terms=["parse_config"],
            candidate_test_file="tests/test_config.py",
        )
    )

    assert finding.verification_intent is not None
    assert finding.verification_intent.preferred_tools == [ToolKind.REPOSITORY_SEARCH]


def test_review_finding_accepts_finding_verification():
    plan = VerificationPlan(
        finding_id="F-1",
        goal="Check behavior",
        requested_tools=[ToolKind.REPOSITORY_SEARCH],
        rationale="Use safe tools.",
        risk_level="low",
    )
    verification = FindingVerification(
        status=VerificationStatus.INCONCLUSIVE,
        plan=plan,
        tool_results=[
            ToolResult(
                tool=ToolKind.REPOSITORY_SEARCH,
                success=True,
                summary="Found one call site.",
                duration_ms=2,
                matched_paths=["src/app.py"],
            )
        ],
        evidence_summary="Search was inconclusive.",
        confidence_before=0.8,
        confidence_after=0.7,
        publication_decision="publish_with_warning",
    )

    finding = _finding(verification=verification)

    assert finding.verification is not None
    assert finding.verification.confidence_after == 0.7


def _finding(**overrides):
    data = {
        "id": "F-1",
        "file_path": "src/app.py",
        "line_start": 1,
        "line_end": 1,
        "category": "bug",
        "severity": "major",
        "confidence": 0.8,
        "title": "Possible bug",
        "description": "The changed branch can fail.",
        "evidence": "+ changed",
        "suggestion": "Guard the branch.",
        "reviewer": "bug",
    }
    data.update(overrides)
    return ReviewFinding.model_validate(data)
