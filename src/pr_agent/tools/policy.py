"""Deterministic policy gate for verification plans and modes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pr_agent.review.schema import ReviewFinding, ToolKind, VerificationPlan, VerificationStatus
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.base import ToolPolicyError, is_safe_relative_path, is_sensitive_path, looks_like_raw_command, normalize_repo_path


VerifyMode = Literal["off", "static", "sandbox"]

STATIC_MODE_TOOLS = {
    ToolKind.REPOSITORY_SEARCH,
    ToolKind.READ_FILE,
    ToolKind.TEST_DISCOVERY,
    ToolKind.DEPENDENCY_INSPECTION,
}

EXECUTION_TOOLS = {ToolKind.PYTEST, ToolKind.RUFF, ToolKind.MYPY}

CATEGORY_ALLOWED_TOOLS: dict[str, set[ToolKind]] = {
    "bug": {
        ToolKind.REPOSITORY_SEARCH,
        ToolKind.READ_FILE,
        ToolKind.TEST_DISCOVERY,
        ToolKind.PYTEST,
        ToolKind.RUFF,
        ToolKind.MYPY,
    },
    "test": {
        ToolKind.REPOSITORY_SEARCH,
        ToolKind.TEST_DISCOVERY,
        ToolKind.PYTEST,
    },
    "security": {
        ToolKind.REPOSITORY_SEARCH,
        ToolKind.READ_FILE,
        ToolKind.DEPENDENCY_INSPECTION,
        ToolKind.RUFF,
    },
    "performance": {
        ToolKind.REPOSITORY_SEARCH,
        ToolKind.READ_FILE,
        ToolKind.TEST_DISCOVERY,
    },
    "maintainability": {
        ToolKind.REPOSITORY_SEARCH,
        ToolKind.READ_FILE,
        ToolKind.TEST_DISCOVERY,
        ToolKind.RUFF,
    },
    "style": {
        ToolKind.READ_FILE,
        ToolKind.RUFF,
    },
}


@dataclass(frozen=True)
class VerificationOptions:
    mode: VerifyMode = "off"
    workspace: Path | None = None
    budget: int = 3
    timeout_seconds: int = 45
    artifacts_dir: Path | None = None
    sandbox_allowed_for_remote: bool = False
    publish_policy: str = "verified_or_high_confidence"


@dataclass(frozen=True)
class PolicyDecision:
    status: VerificationStatus
    plan: VerificationPlan | None
    reason: str = ""


def normalize_verify_mode(mode: str) -> VerifyMode:
    normalized = mode.lower().strip()
    if normalized not in {"off", "static", "sandbox"}:
        raise ValueError("--verify/--mode must be one of: off, static, sandbox")
    return normalized  # type: ignore[return-value]


def action_safe_verify_mode(requested_mode: VerifyMode, is_fork_pull_request: bool) -> VerifyMode:
    if requested_mode == "sandbox" and is_fork_pull_request:
        return "static"
    return requested_mode


def validate_plan(
    finding: ReviewFinding,
    plan: VerificationPlan,
    options: VerificationOptions,
    change_set: ChangeSet,
) -> PolicyDecision:
    if options.mode == "off":
        return PolicyDecision(VerificationStatus.NOT_REQUESTED, None, "verification mode is off")
    if options.workspace is None:
        return PolicyDecision(VerificationStatus.NOT_ELIGIBLE, None, "workspace is required for verification")
    if not options.workspace.exists():
        return PolicyDecision(VerificationStatus.NOT_ELIGIBLE, None, f"workspace does not exist: {options.workspace}")
    if options.mode == "sandbox" and not _sandbox_allowed(change_set, options):
        return PolicyDecision(
            VerificationStatus.NOT_ELIGIBLE,
            None,
            "sandbox verification is only allowed for local diffs or explicitly trusted checkout workspaces",
        )

    _reject_unsafe_text(plan.goal, "goal")
    _reject_unsafe_text(plan.rationale, "rationale")
    safe_terms = []
    for term in plan.search_terms:
        _reject_unsafe_text(term, "search term")
        safe_terms.append(term)

    safe_test_paths = []
    for path in plan.candidate_test_paths:
        _validate_repo_path(path)
        safe_test_paths.append(normalize_repo_path(path))

    allowed_tools = set(CATEGORY_ALLOWED_TOOLS.get(finding.category, STATIC_MODE_TOOLS))
    if options.mode == "static":
        allowed_tools &= STATIC_MODE_TOOLS
    requested = [tool for tool in plan.requested_tools if tool in allowed_tools]

    if not requested:
        return PolicyDecision(VerificationStatus.SKIPPED, None, "no requested tools are allowed by policy")

    return PolicyDecision(
        VerificationStatus.NOT_REQUESTED,
        plan.model_copy(
            update={
                "requested_tools": list(dict.fromkeys(requested)),
                "search_terms": list(dict.fromkeys(safe_terms)),
                "candidate_test_paths": list(dict.fromkeys(safe_test_paths)),
            }
        ),
        "",
    )


def validate_execution_path(path: str) -> str:
    _validate_repo_path(path)
    return normalize_repo_path(path)


def _sandbox_allowed(change_set: ChangeSet, options: VerificationOptions) -> bool:
    return change_set.target.source_type == "local_diff" or options.sandbox_allowed_for_remote


def _reject_unsafe_text(value: str, field_name: str) -> None:
    if looks_like_raw_command(value):
        raise ToolPolicyError(f"Raw shell syntax is not allowed in verification {field_name}: {value!r}")


def _validate_repo_path(path: str) -> None:
    if not is_safe_relative_path(path) or is_sensitive_path(path):
        raise ToolPolicyError(f"Unsafe repository path requested: {path!r}")
