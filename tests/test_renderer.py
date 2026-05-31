from pr_agent.github.models import PRInfo
from pr_agent.review.renderer import MarkdownRenderer
from pr_agent.review.schema import ReviewFinding, ReviewResult


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
