from pr_agent.github.models import PRInfo
from pr_agent.review.renderer import MarkdownRenderer
from pr_agent.review.schema import (
    FindingVerification,
    PatchSuggestion,
    ReviewFinding,
    ReviewResult,
    TestSuggestion as ReviewTestSuggestion,
    ToolKind,
    ToolResult,
    VerificationPlan,
    VerificationStatus,
)


def make_pr() -> PRInfo:
    return PRInfo(
        owner="acme",
        repo="app",
        pull_number=1,
        title="Test",
        body=None,
        base_branch="main",
        head_branch="feature",
        base_sha="base",
        head_sha="head",
        author="alice",
        url="https://github.com/acme/app/pull/1",
    )


def test_renderer_with_no_findings():
    result = ReviewResult(pr=make_pr(), summary="Looks good.", findings=[], stats={}, model_info={})

    report = MarkdownRenderer().render(result)

    assert "# AI PR Review Report" in report
    assert "No high-confidence issues were found." in report


def test_renderer_with_findings():
    result = ReviewResult(
        pr=make_pr(),
        summary="Found one issue.",
        findings=[
            ReviewFinding(
                id="f1",
                file_path="src/app.py",
                line_start=10,
                line_end=10,
                category="test",
                severity="minor",
                confidence=0.8,
                title="Missing edge-case test",
                description="New behavior is not covered.",
                evidence="The diff adds an error path.",
                suggestion="Add a test for the error path.",
                suggested_patch=None,
                reviewer="general",
            )
        ],
        stats={"latency_seconds": 1.2, "total_tokens": 100},
        model_info={"model": "test-model"},
    )

    report = MarkdownRenderer().render(result)

    assert "[Minor][test] Missing edge-case test" in report
    assert "Add a test for the error path." in report
    assert "test-model" in report


def test_renderer_includes_verification_metrics():
    result = ReviewResult(
        pr=make_pr(),
        summary="Looks good.",
        findings=[],
        stats={
            "verification": {
                "candidate_findings": 3,
                "suppressed_findings": 2,
                "published_findings": 1,
            }
        },
        model_info={"model": "test-model"},
    )

    report = MarkdownRenderer().render(result)

    assert "Candidate findings: 3" in report
    assert "Suppressed candidates: 2" in report
    assert "Published findings: 1" in report


def test_renderer_includes_patch_and_test_suggestions():
    result = ReviewResult(
        pr=make_pr(),
        summary="Found one issue.",
        findings=[
            ReviewFinding(
                id="f1",
                file_path="src/app.py",
                line_start=10,
                line_end=10,
                category="bug",
                severity="major",
                confidence=0.9,
                title="None branch can fail",
                description="The new branch returns None.",
                evidence="+ return None",
                suggestion="Return a value or raise.",
                suggested_patch=None,
                patch_suggestion=PatchSuggestion(
                    description="Replace the None return.",
                    suggested_patch="- return None\n+ raise ValueError()",
                    commands=["python -m pytest"],
                ),
                test_suggestions=[
                    ReviewTestSuggestion(
                        test_file_path="tests/test_app.py",
                        test_name="test_none_branch",
                        scenario="Input triggers the None branch.",
                        assertions=["The branch raises a controlled error."],
                    )
                ],
                reviewer="bug",
            )
        ],
        stats={},
        model_info={"model": "test-model"},
    )

    report = MarkdownRenderer().render(result)

    assert "Patch Suggestion" in report
    assert "python -m pytest" in report
    assert "test_none_branch" in report


def test_renderer_includes_finding_verification_details():
    plan = VerificationPlan(
        finding_id="f1",
        goal="Check behavior",
        requested_tools=[ToolKind.REPOSITORY_SEARCH],
        rationale="Use safe tools.",
        risk_level="low",
    )
    result = ReviewResult(
        pr=make_pr(),
        summary="Found one issue.",
        findings=[
            ReviewFinding(
                id="f1",
                file_path="src/app.py",
                line_start=10,
                line_end=10,
                category="bug",
                severity="major",
                confidence=0.9,
                title="None branch can fail",
                description="The new branch returns None.",
                evidence="+ return None",
                suggestion="Return a value or raise.",
                verification=FindingVerification(
                    status=VerificationStatus.SUPPORTED,
                    plan=plan,
                    tool_results=[
                        ToolResult(
                            tool=ToolKind.REPOSITORY_SEARCH,
                            success=True,
                            summary="Found call sites.",
                            duration_ms=5,
                        )
                    ],
                    evidence_summary="Targeted evidence supports the finding.",
                    confidence_before=0.8,
                    confidence_after=0.9,
                    publication_decision="publish",
                ),
                reviewer="bug",
            )
        ],
        stats={},
        model_info={"model": "test-model"},
    )

    report = MarkdownRenderer().render(result)

    assert "Verification: Supported" in report
    assert "Targeted evidence supports the finding." in report
    assert "Reviewer confidence: 0.80 -> 0.90" in report
