from pathlib import Path

from pr_agent.github.models import ChangedFile, ReviewTargetInfo
from pr_agent.review.schema import ReviewFinding, ReviewResult, ToolKind, ToolResult, VerificationStatus
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.executor import verify_review_result
from pr_agent.tools.policy import VerificationOptions


def test_static_executor_suppresses_contradicted_missing_test_finding(tmp_path):
    _write(tmp_path / "src/app.py", "def load():\n    return 1\n")
    _write(tmp_path / "tests/test_app.py", "def test_load():\n    assert True\n")
    finding = _finding(
        category="test",
        severity="minor",
        title="No unit tests added for app",
        description="The change has no unit tests.",
    )

    verified = verify_review_result(
        _result([finding]),
        _change_set(),
        tmp_path,
        VerificationOptions(mode="static", workspace=tmp_path, artifacts_dir=tmp_path / "artifacts"),
        max_findings=8,
    )

    assert verified.findings == []
    assert verified.stats["verification"]["evidence_suppressed_findings"] == 1
    assert verified.stats["verification"]["contradicted_suppression_rate"] == 1.0


def test_static_executor_keeps_high_confidence_inconclusive_with_verification(tmp_path):
    _write(tmp_path / "src/app.py", "def load(value):\n    return value\n")
    finding = _finding(confidence=0.9)

    verified = verify_review_result(
        _result([finding]),
        _change_set(),
        tmp_path,
        VerificationOptions(mode="static", workspace=tmp_path, artifacts_dir=tmp_path / "artifacts"),
        max_findings=8,
    )

    assert len(verified.findings) == 1
    assert verified.findings[0].verification is not None
    assert verified.findings[0].verification.status == VerificationStatus.INCONCLUSIVE
    assert (tmp_path / "artifacts" / "F-1" / "tool_result.json").exists()


def test_sandbox_executor_uses_pytest_result_to_support_finding(tmp_path, monkeypatch):
    _write(tmp_path / "src/app.py", "def load(value):\n    return value.name\n")
    _write(tmp_path / "tests/test_app.py", "def test_load():\n    assert False\n")
    finding = _finding(
        test_suggestions=[
            {
                "test_file_path": "tests/test_app.py",
                "test_name": "test_load",
                "scenario": "None input fails.",
            }
        ]
    )

    def fake_pytest(repo_root, test_path, timeout_seconds, artifact_dir=None, executor=None):
        return ToolResult(
            tool=ToolKind.PYTEST,
            success=True,
            exit_code=1,
            summary="pytest failed at src/app.py:1",
            duration_ms=4,
            matched_paths=[test_path],
        )

    monkeypatch.setattr("pr_agent.tools.executor.run_pytest", fake_pytest)
    verified = verify_review_result(
        _result([finding]),
        _change_set(),
        tmp_path,
        VerificationOptions(mode="sandbox", workspace=tmp_path, artifacts_dir=tmp_path / "artifacts"),
        max_findings=8,
    )

    assert verified.findings[0].verification is not None
    assert verified.findings[0].verification.status == VerificationStatus.SUPPORTED
    assert verified.findings[0].confidence == 0.9


def test_executor_records_budget_exhaustion(tmp_path):
    _write(tmp_path / "src/app.py", "def load(value):\n    return value\n")
    findings = [_finding(id="F-1"), _finding(id="F-2")]

    verified = verify_review_result(
        _result(findings),
        _change_set(),
        tmp_path,
        VerificationOptions(mode="static", workspace=tmp_path, budget=1),
        max_findings=8,
    )

    records = verified.stats["verification"]["records"]
    assert records[1]["status"] == "skipped"
    assert "budget exhausted" in records[1]["evidence_summary"].lower()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def _result(findings):
    return ReviewResult(pr=_target(), summary="summary", findings=findings, stats={}, model_info={})


def _target():
    return ReviewTargetInfo(
        source_type="local_diff",
        owner="local",
        repo="repo",
        identifier="local",
        title="Local diff",
        body=None,
        base_branch="main",
        head_branch="working-tree",
        base_sha="base",
        head_sha="head",
        author="alice",
        url="file://repo",
    )


def _change_set():
    return ChangeSet(
        target=_target(),
        files=[ChangedFile(filename="src/app.py", status="modified", additions=1, deletions=0, changes=1, patch="")],
        hunks_by_file={},
    )
