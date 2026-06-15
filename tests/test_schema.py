import pytest
from pydantic import ValidationError

from pr_agent.diff.models import DiffHunk, DiffLine
from pr_agent.github.models import PRInfo
from pr_agent.review.schema import PatchSuggestion, ReviewFinding, ReviewResult, TestSuggestion as ReviewTestSuggestion
from pr_agent.review.validator import validate_findings


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


def make_finding(**overrides) -> ReviewFinding:
    data = {
        "id": "f1",
        "file_path": "src/app.py",
        "line_start": 2,
        "line_end": 2,
        "category": "bug",
        "severity": "major",
        "confidence": 0.9,
        "title": "Possible bug",
        "description": "The changed branch can return None unexpectedly.",
        "evidence": "The added line returns None.",
        "suggestion": "Return an explicit error instead.",
        "suggested_patch": None,
        "reviewer": "general",
    }
    data.update(overrides)
    return ReviewFinding.model_validate(data)


def test_review_finding_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        make_finding(confidence=1.5)


def test_review_finding_rejects_invalid_category():
    with pytest.raises(ValidationError):
        make_finding(category="docs")


def test_validate_findings_filters_low_confidence_and_bad_lines():
    result = ReviewResult(
        pr=make_pr(),
        summary="summary",
        findings=[
            make_finding(id="good", line_start=2, confidence=0.9),
            make_finding(id="low", line_start=2, confidence=0.3),
            make_finding(id="bad-line", line_start=99, line_end=99, confidence=0.9),
        ],
    )
    hunk = DiffHunk(
        filename="src/app.py",
        old_start=1,
        old_count=1,
        new_start=1,
        new_count=2,
        section_header=None,
        lines=[
            DiffLine(line_type="context", content="a", old_line_no=1, new_line_no=1),
            DiffLine(line_type="add", content="b", old_line_no=None, new_line_no=2),
        ],
    )

    validated = validate_findings(result, [hunk], confidence_threshold=0.6, max_findings=8)

    assert [finding.id for finding in validated.findings] == ["good"]


def test_review_finding_accepts_patch_and_test_suggestions():
    finding = make_finding(
        patch_suggestion=PatchSuggestion(
            description="Guard the None branch.",
            suggested_patch="- return user.name\n+ return user.name if user else None",
            commands=["python -m pytest tests/test_app.py"],
        ),
        test_suggestions=[
            ReviewTestSuggestion(
                test_file_path="tests/test_app.py",
                test_name="test_missing_user",
                scenario="The endpoint receives a request without a user.",
                assertions=["The response is a 401 instead of a 500."],
            )
        ],
    )

    assert finding.patch_suggestion is not None
    assert finding.test_suggestions[0].test_name == "test_missing_user"
