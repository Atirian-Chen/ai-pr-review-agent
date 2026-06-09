from pathlib import Path

from pr_agent.diff.models import DiffHunk, DiffLine
from pr_agent.github.models import ChangedFile, PRInfo
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.review.verifier import verify_findings
from pr_agent.targets.models import ChangeSet


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


def _changed_file(path: str, patch: str = "@@ -1 +1 @@\n+changed") -> ChangedFile:
    return ChangedFile(filename=path, status="modified", additions=1, deletions=0, changes=1, patch=patch)


def _change_set(*paths: str) -> ChangeSet:
    files = [_changed_file(path) for path in paths]
    return ChangeSet(
        target=_pr(),
        files=files,
        hunks_by_file={
            path: [
                DiffHunk(
                    filename=path,
                    old_start=1,
                    old_count=0,
                    new_start=1,
                    new_count=1,
                    section_header=None,
                    lines=[DiffLine(line_type="add", content="changed", old_line_no=None, new_line_no=1)],
                )
            ]
            for path in paths
        },
    )


def _finding(path: str, **overrides) -> ReviewFinding:
    data = {
        "id": "f1",
        "file_path": path,
        "line_start": 1,
        "line_end": 1,
        "category": "bug",
        "severity": "major",
        "confidence": 0.9,
        "title": "Changed branch returns None",
        "description": "The new branch can return None to callers expecting a value.",
        "evidence": "+ return None",
        "suggestion": "Return a valid value or raise an explicit exception.",
        "reviewer": "general",
    }
    data.update(overrides)
    return ReviewFinding.model_validate(data)


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(pr=_pr(), summary="summary", findings=findings, stats={}, model_info={})


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_verifier_suppresses_absolute_missing_tests_when_related_test_exists(tmp_path):
    _write(tmp_path / "src/pr_agent/github/actions.py", "def resolve():\n    return True\n")
    _write(tmp_path / "tests/test_github_actions.py", "def test_resolve():\n    assert True\n")
    finding = _finding(
        "src/pr_agent/github/actions.py",
        category="test",
        severity="major",
        title="No unit tests added for the actions module",
        description="The new workflow resolver has no unit tests.",
        evidence="The diff adds src/pr_agent/github/actions.py.",
        suggestion="Add unit tests for the resolver.",
    )

    verified = verify_findings(_result([finding]), _change_set("src/pr_agent/github/actions.py"), tmp_path, max_findings=8)

    assert verified.findings == []
    assert verified.stats["verification"]["suppressed_findings"] == 1
    assert verified.stats["verification"]["suppressions"][0]["rule"] == "related-tests-exist"


def test_verifier_keeps_specific_edge_case_test_gap_even_when_test_file_exists(tmp_path):
    _write(tmp_path / "src/pr_agent/github/actions.py", "def resolve(event):\n    return event['after']\n")
    _write(tmp_path / "tests/test_github_actions.py", "def test_resolve_push():\n    assert True\n")
    finding = _finding(
        "src/pr_agent/github/actions.py",
        category="test",
        severity="minor",
        title="Missing edge-case test for branch deletion",
        description="The new push resolver should be tested with an all-zero after SHA.",
        evidence="The diff handles push event SHAs.",
        suggestion="Add a branch-deletion push event test.",
    )

    verified = verify_findings(_result([finding]), _change_set("src/pr_agent/github/actions.py"), tmp_path, max_findings=8)

    assert [item.id for item in verified.findings] == ["f1"]


def test_verifier_suppresses_none_claim_for_non_optional_model_field(tmp_path):
    _write(
        tmp_path / "src/app/schema.py",
        "from typing import Any\n"
        "from pydantic import BaseModel, Field\n\n"
        "class ReviewResult(BaseModel):\n"
        "    summary: str\n"
        "    stats: dict[str, Any] = Field(default_factory=dict)\n"
        "    trace_id: str | None = None\n",
    )
    _write(
        tmp_path / "src/app/comments.py",
        "from app.schema import ReviewResult\n\n"
        "def build(result: ReviewResult) -> str:\n"
        "    return result.summary\n",
    )
    finding = _finding(
        "src/app/comments.py",
        title="Potential AttributeError if result.summary is None",
        description="result.summary may be None and strip will fail.",
        evidence="result.summary",
        suggestion="Guard result.summary before using it.",
    )

    verified = verify_findings(_result([finding]), _change_set("src/app/comments.py"), tmp_path, max_findings=8)

    assert verified.findings == []
    assert verified.stats["verification"]["suppressions"][0]["rule"] == "non-optional-field"


def test_verifier_does_not_suppress_none_claim_for_optional_model_field(tmp_path):
    _write(
        tmp_path / "src/app/schema.py",
        "from pydantic import BaseModel\n\n"
        "class ReviewResult(BaseModel):\n"
        "    trace_id: str | None = None\n",
    )
    _write(
        tmp_path / "src/app/comments.py",
        "from app.schema import ReviewResult\n\n"
        "def build(result: ReviewResult) -> str:\n"
        "    return result.trace_id.strip()\n",
    )
    finding = _finding(
        "src/app/comments.py",
        title="Potential AttributeError if result.trace_id is None",
        description="result.trace_id may be None and strip will fail.",
        evidence="result.trace_id.strip()",
        suggestion="Check trace_id before calling strip.",
    )

    verified = verify_findings(_result([finding]), _change_set("src/app/comments.py"), tmp_path, max_findings=8)

    assert [item.id for item in verified.findings] == ["f1"]


def test_verifier_suppresses_existing_cli_command_warning(tmp_path):
    _write(
        tmp_path / "src/pr_agent/cli.py",
        "import typer\n\n"
        "app = typer.Typer()\n\n"
        "@app.command('review-action')\n"
        "def review_action():\n"
        "    pass\n",
    )
    _write(tmp_path / "docs/github-actions.md", "pr-agent review-action --dry-run\n")
    finding = _finding(
        "docs/github-actions.md",
        category="maintainability",
        severity="minor",
        title="Possible incorrect CLI command name",
        description="The dry-run example may use an invalid CLI command.",
        evidence="`pr-agent review-action --dry-run`",
        suggestion="Use the correct command.",
    )

    verified = verify_findings(_result([finding]), _change_set("docs/github-actions.md"), tmp_path, max_findings=8)

    assert verified.findings == []
    assert verified.stats["verification"]["suppressions"][0]["rule"] == "cli-command-exists"


def test_verifier_keeps_supported_bug_candidate(tmp_path):
    _write(tmp_path / "src/app.py", "def load(flag):\n    if flag:\n        return None\n    return 'ok'\n")
    finding = _finding("src/app.py")

    verified = verify_findings(_result([finding]), _change_set("src/app.py"), tmp_path, max_findings=8)

    assert [item.id for item in verified.findings] == ["f1"]
    assert verified.stats["verification"]["suppressed_findings"] == 0


def test_verifier_downgrades_major_doc_findings(tmp_path):
    _write(tmp_path / "README.md", "docs\n")
    finding = _finding(
        "README.md",
        category="bug",
        severity="major",
        title="Documentation statement is inaccurate",
        description="The README describes the wrong command behavior.",
        evidence="+ wrong docs",
        suggestion="Correct the docs.",
    )

    verified = verify_findings(_result([finding]), _change_set("README.md"), tmp_path, max_findings=8)

    assert verified.findings[0].category == "maintainability"
    assert verified.findings[0].severity == "minor"
