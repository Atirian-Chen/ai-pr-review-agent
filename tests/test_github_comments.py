from pr_agent.github.comments import SUMMARY_COMMENT_MARKER, build_summary_comment
from pr_agent.github.models import PRInfo
from pr_agent.review.schema import ReviewFinding, ReviewResult


def _pr():
    return PRInfo(
        owner="acme",
        repo="app",
        pull_number=1,
        identifier="#1",
        title="Test",
        body=None,
        base_branch="main",
        head_branch="feature",
        base_sha="base",
        head_sha="head",
        author="alice",
        url="https://github.com/acme/app/pull/1",
    )


def _finding(index=1):
    return ReviewFinding(
        id=f"f{index}",
        file_path="src/app.py",
        line_start=10,
        line_end=10,
        category="test",
        severity="minor",
        confidence=0.8,
        title=f"Missing edge-case test {index}",
        description="New behavior is not covered.",
        evidence="The diff adds an error path.",
        suggestion="Add a test for the error path.",
        suggested_patch=None,
        reviewer="general",
    )


def test_build_summary_comment_includes_marker_and_location():
    result = ReviewResult(
        pr=_pr(),
        summary="Found one issue.",
        findings=[_finding()],
        stats={"files_seen": 2, "files_reviewed": 1},
        model_info={"model": "test-model"},
        trace_id="trace-1",
    )

    comment = build_summary_comment(result)

    assert SUMMARY_COMMENT_MARKER in comment
    assert "`src/app.py:10`" in comment
    assert "Minor / test" in comment
    assert "trace-1" in comment


def test_build_summary_comment_reports_no_findings():
    result = ReviewResult(
        pr=_pr(),
        summary="Looks good.",
        findings=[],
        stats={"files_seen": 1, "files_reviewed": 1},
        model_info={"model": "test-model"},
    )

    comment = build_summary_comment(result)

    assert "Risk: None" in comment
    assert "No high-confidence issues were found." in comment


def test_build_summary_comment_truncates_findings():
    result = ReviewResult(
        pr=_pr(),
        summary="Many issues.",
        findings=[_finding(index) for index in range(1, 6)],
        stats={"files_seen": 5, "files_reviewed": 5},
        model_info={"model": "test-model"},
    )

    comment = build_summary_comment(result, max_findings=2)

    assert "3 additional finding(s) omitted" in comment
