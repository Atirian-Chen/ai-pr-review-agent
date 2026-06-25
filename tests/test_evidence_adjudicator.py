from pr_agent.review.evidence_adjudicator import adjudicate_evidence, build_skipped_verification
from pr_agent.review.schema import ReviewFinding, ToolKind, ToolResult, VerificationPlan, VerificationStatus


def test_adjudicator_marks_failing_pytest_as_supported():
    finding = _finding(confidence=0.82)
    verification = adjudicate_evidence(
        finding,
        _plan([ToolKind.PYTEST]),
        [
            ToolResult(
                tool=ToolKind.PYTEST,
                success=True,
                exit_code=1,
                summary="pytest failed with AttributeError at src/app.py:1",
                duration_ms=100,
            )
        ],
    )

    assert verification.status == VerificationStatus.SUPPORTED
    assert verification.confidence_after == 0.92
    assert verification.publication_decision == "publish"


def test_adjudicator_suppresses_contradicted_missing_tests_claim():
    finding = _finding(
        category="test",
        title="No unit tests added for app",
        description="The change has no test coverage.",
    )
    verification = adjudicate_evidence(
        finding,
        _plan([ToolKind.TEST_DISCOVERY]),
        [
            ToolResult(
                tool=ToolKind.TEST_DISCOVERY,
                success=True,
                summary="Found 1 candidate test file.",
                duration_ms=3,
                matched_paths=["tests/test_app.py"],
            )
        ],
    )

    assert verification.status == VerificationStatus.CONTRADICTED
    assert verification.confidence_after == 0.0
    assert verification.publication_decision == "suppress"


def test_adjudicator_does_not_refute_specific_edge_case_test_gap_from_file_existence_only():
    finding = _finding(
        category="test",
        title="Missing edge-case test for empty payload",
        description="Add a test for an empty payload.",
        severity="minor",
        confidence=0.7,
    )
    verification = adjudicate_evidence(
        finding,
        _plan([ToolKind.TEST_DISCOVERY]),
        [
            ToolResult(
                tool=ToolKind.TEST_DISCOVERY,
                success=True,
                summary="Found 1 candidate test file.",
                duration_ms=3,
                matched_paths=["tests/test_app.py"],
            )
        ],
    )

    assert verification.status == VerificationStatus.INCONCLUSIVE
    assert verification.confidence_after == 0.6
    assert verification.publication_decision == "suppress"


def test_adjudicator_publishes_high_confidence_inconclusive_with_warning():
    finding = _finding(severity="major", confidence=0.9)
    verification = adjudicate_evidence(
        finding,
        _plan([ToolKind.REPOSITORY_SEARCH]),
        [
            ToolResult(
                tool=ToolKind.REPOSITORY_SEARCH,
                success=True,
                summary="Found related code but no failing check.",
                duration_ms=3,
                matched_paths=["src/app.py"],
            )
        ],
    )

    assert verification.status == VerificationStatus.INCONCLUSIVE
    assert verification.publication_decision == "publish_with_warning"


def test_build_skipped_verification_uses_warning_for_major_findings():
    finding = _finding(severity="major")

    verification = build_skipped_verification(finding, VerificationStatus.SKIPPED, "No Docker.")

    assert verification.status == VerificationStatus.SKIPPED
    assert verification.publication_decision == "publish_with_warning"


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


def _plan(tools):
    return VerificationPlan(
        finding_id="F-1",
        goal="Check behavior",
        requested_tools=tools,
        rationale="Use safe tools.",
        risk_level="low",
    )
