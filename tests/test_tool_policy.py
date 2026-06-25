from pathlib import Path

import pytest

from pr_agent.github.models import ChangedFile, ReviewTargetInfo
from pr_agent.review.schema import ReviewFinding, ToolKind, VerificationPlan, VerificationStatus
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.base import ToolPolicyError, is_safe_relative_path, is_sensitive_path, safe_join
from pr_agent.tools.policy import VerificationOptions, action_safe_verify_mode, validate_plan


def test_safe_relative_path_rejects_absolute_and_parent_paths():
    assert is_safe_relative_path("src/app.py")
    assert not is_safe_relative_path("../secret.py")
    assert not is_safe_relative_path("/tmp/secret.py")
    assert not is_safe_relative_path("C:\\secret.py")


def test_sensitive_path_detection_catches_secrets():
    assert is_sensitive_path(".env")
    assert is_sensitive_path("keys/service.pem")
    assert is_sensitive_path(".ssh/id_rsa")
    assert not is_sensitive_path("src/app.py")


def test_safe_join_refuses_sensitive_file(tmp_path):
    with pytest.raises(ToolPolicyError):
        safe_join(tmp_path, ".env")


def test_policy_removes_tools_not_allowed_for_test_findings(tmp_path):
    finding = _finding(category="test")
    plan = _plan([ToolKind.RUFF, ToolKind.REPOSITORY_SEARCH])
    decision = validate_plan(finding, plan, VerificationOptions(mode="static", workspace=tmp_path), _change_set())

    assert decision.status == VerificationStatus.NOT_REQUESTED
    assert decision.plan is not None
    assert decision.plan.requested_tools == [ToolKind.REPOSITORY_SEARCH]


def test_policy_rejects_raw_shell_command_in_search_terms(tmp_path):
    finding = _finding()
    plan = _plan([ToolKind.REPOSITORY_SEARCH], search_terms=["python -c 'print(1)'"])

    with pytest.raises(ToolPolicyError):
        validate_plan(finding, plan, VerificationOptions(mode="static", workspace=tmp_path), _change_set())


def test_policy_rejects_unsafe_candidate_test_path(tmp_path):
    finding = _finding()
    plan = _plan([ToolKind.PYTEST], candidate_test_paths=["../tests/test_app.py"])

    with pytest.raises(ToolPolicyError):
        validate_plan(finding, plan, VerificationOptions(mode="sandbox", workspace=tmp_path), _change_set())


def test_static_mode_strips_execution_tools(tmp_path):
    finding = _finding()
    plan = _plan([ToolKind.PYTEST, ToolKind.REPOSITORY_SEARCH])
    decision = validate_plan(finding, plan, VerificationOptions(mode="static", workspace=tmp_path), _change_set())

    assert decision.plan is not None
    assert ToolKind.PYTEST not in decision.plan.requested_tools


def test_remote_sandbox_is_not_eligible_without_trusted_checkout(tmp_path):
    finding = _finding()
    plan = _plan([ToolKind.PYTEST], candidate_test_paths=["tests/test_app.py"])
    change_set = _change_set(source_type="pull_request")
    decision = validate_plan(finding, plan, VerificationOptions(mode="sandbox", workspace=tmp_path), change_set)

    assert decision.status == VerificationStatus.NOT_ELIGIBLE


def test_fork_pr_sandbox_mode_downgrades_to_static():
    assert action_safe_verify_mode("sandbox", is_fork_pull_request=True) == "static"
    assert action_safe_verify_mode("sandbox", is_fork_pull_request=False) == "sandbox"


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


def _plan(tools, search_terms=None, candidate_test_paths=None):
    return VerificationPlan(
        finding_id="F-1",
        goal="Check behavior",
        requested_tools=tools,
        search_terms=search_terms or ["app"],
        candidate_test_paths=candidate_test_paths or [],
        rationale="Use safe tools.",
        risk_level="low",
    )


def _change_set(source_type="local_diff"):
    pr = ReviewTargetInfo(
        source_type=source_type,
        owner="acme",
        repo="app",
        pull_number=1 if source_type == "pull_request" else None,
        title="Test",
        body=None,
        base_branch="main",
        head_branch="feature",
        base_sha="base",
        head_sha="head",
        author="alice",
        url="https://github.com/acme/app/pull/1",
    )
    return ChangeSet(
        target=pr,
        files=[ChangedFile(filename="src/app.py", status="modified", additions=1, deletions=0, changes=1, patch="")],
        hunks_by_file={},
    )
