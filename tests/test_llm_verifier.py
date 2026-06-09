from pr_agent.diff.models import DiffHunk, DiffLine
from pr_agent.github.models import ChangedFile, PRInfo
from pr_agent.llm.client import LLMClient, LLMJsonResponse
from pr_agent.review.llm_verifier import verify_findings_with_llm
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.targets.models import ChangeSet


class FakeVerifierClient(LLMClient):
    def __init__(self, data):
        self.data = data
        self.prompts = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        self.prompts.append((system_prompt, user_prompt))
        return LLMJsonResponse(
            data=self.data,
            latency_seconds=0.2,
            model="verifier-mini",
            usage={"total_tokens": 12},
        )


class FailingVerifierClient(LLMClient):
    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        raise RuntimeError("verifier unavailable")


def _pr() -> PRInfo:
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


def _finding(finding_id: str, severity: str = "major", confidence: float = 0.9) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        file_path="src/app.py",
        line_start=1,
        line_end=1,
        category="bug",
        severity=severity,
        confidence=confidence,
        title=f"Finding {finding_id}",
        description="The changed branch can fail.",
        evidence="+ return None",
        suggestion="Return a valid value.",
        reviewer="general",
    )


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(
        pr=_pr(),
        summary="summary",
        findings=findings,
        stats={
            "verification": {
                "candidate_findings": len(findings),
                "deterministic_suppressed_findings": 1,
                "suppressed_findings": 1,
                "suppressions": [{"finding_id": "old", "rule": "deterministic"}],
            }
        },
        model_info={"model": "main-model"},
    )


def _change_set() -> ChangeSet:
    return ChangeSet(
        target=_pr(),
        files=[
            ChangedFile(
                filename="src/app.py",
                status="modified",
                additions=1,
                deletions=0,
                changes=1,
                patch="@@ -1 +1 @@\n+return None",
            )
        ],
        hunks_by_file={
            "src/app.py": [
                DiffHunk(
                    filename="src/app.py",
                    old_start=1,
                    old_count=0,
                    new_start=1,
                    new_count=1,
                    section_header=None,
                    lines=[DiffLine(line_type="add", content="return None", old_line_no=None, new_line_no=1)],
                )
            ]
        },
    )


def test_llm_verifier_suppresses_and_downgrades_findings():
    client = FakeVerifierClient(
        {
            "summary": "one suppress, one downgrade",
            "verdicts": [
                {
                    "finding_id": "f1",
                    "decision": "suppress",
                    "reason": "The finding is not supported by the diff.",
                    "severity": None,
                    "confidence": None,
                },
                {
                    "finding_id": "f2",
                    "decision": "downgrade",
                    "reason": "The issue is valid but overstated.",
                    "severity": "minor",
                    "confidence": 0.55,
                },
            ],
        }
    )

    verified = verify_findings_with_llm(_result([_finding("f1"), _finding("f2")]), _change_set(), client, max_findings=8)

    assert [finding.id for finding in verified.findings] == ["f2"]
    assert verified.findings[0].severity == "minor"
    assert verified.findings[0].confidence == 0.55
    assert verified.stats["verification"]["suppressed_findings"] == 2
    assert verified.stats["verification"]["llm_suppressed_findings"] == 1
    assert verified.stats["verification"]["llm_downgraded_findings"] == 1
    assert verified.stats["llm_verifier"]["model"] == "verifier-mini"


def test_llm_verifier_does_not_upgrade_findings():
    client = FakeVerifierClient(
        {
            "summary": "attempted upgrade ignored",
            "verdicts": [
                {
                    "finding_id": "f1",
                    "decision": "downgrade",
                    "reason": "Bad verdict tries to upgrade.",
                    "severity": "critical",
                    "confidence": 0.99,
                }
            ],
        }
    )

    verified = verify_findings_with_llm(_result([_finding("f1", severity="major", confidence=0.8)]), _change_set(), client, max_findings=8)

    assert verified.findings[0].severity == "major"
    assert verified.findings[0].confidence == 0.8
    assert verified.stats["verification"]["llm_downgraded_findings"] == 0


def test_llm_verifier_skips_without_client_and_enforces_limit():
    result = _result([_finding("f1", severity="minor"), _finding("f2", severity="major")])

    verified = verify_findings_with_llm(result, _change_set(), None, max_findings=1, skip_reason="no verifier key")

    assert [finding.id for finding in verified.findings] == ["f2"]
    assert verified.stats["llm_verifier"]["status"] == "skipped"
    assert verified.stats["llm_verifier"]["reason"] == "no verifier key"
    assert verified.stats["verification"]["published_findings"] == 1


def test_llm_verifier_fails_open_on_verifier_error():
    result = _result([_finding("f1")])

    verified = verify_findings_with_llm(result, _change_set(), FailingVerifierClient(), max_findings=8)

    assert [finding.id for finding in verified.findings] == ["f1"]
    assert verified.stats["llm_verifier"]["status"] == "error"
    assert "verifier unavailable" in verified.stats["llm_verifier"]["error"]
