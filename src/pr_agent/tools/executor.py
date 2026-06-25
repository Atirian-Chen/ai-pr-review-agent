"""Verification executor that runs policy-approved tools and gates publication."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pr_agent.review.evidence_adjudicator import adjudicate_evidence, build_skipped_verification
from pr_agent.review.schema import FindingVerification, ReviewFinding, ReviewResult, ToolKind, VerificationStatus
from pr_agent.review.verifier import SEVERITY_RANK
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.base import ToolPolicyError, normalize_repo_path, write_json_artifact
from pr_agent.tools.dependency_inspection import inspect_dependencies
from pr_agent.tools.planner import plan_for_finding
from pr_agent.tools.policy import EXECUTION_TOOLS, PolicyDecision, VerificationOptions, validate_plan
from pr_agent.tools.pytest_runner import run_pytest
from pr_agent.tools.read_file import read_repository_file
from pr_agent.tools.repository_search import repository_search
from pr_agent.tools.ruff_runner import run_ruff
from pr_agent.tools.mypy_runner import run_mypy
from pr_agent.tools.test_discovery import discover_tests


def verify_review_result(
    result: ReviewResult,
    change_set: ChangeSet,
    repo_root: Path,
    options: VerificationOptions,
    max_findings: int,
) -> ReviewResult:
    if options.mode == "off":
        return result

    started = time.perf_counter()
    workspace = options.workspace or repo_root
    verified_findings: list[ReviewFinding] = []
    suppressed: list[dict[str, Any]] = []
    verification_records: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    sandbox_tool_count = 0
    eligible = 0
    executed = 0

    for index, finding in enumerate(result.findings):
        plan = plan_for_finding(finding)
        try:
            decision = validate_plan(finding, plan, options, change_set)
        except ToolPolicyError as exc:
            verification = build_skipped_verification(
                finding,
                VerificationStatus.SKIPPED,
                f"Verification plan rejected by policy: {exc}",
                plan,
            )
            verified_findings.append(_apply_verification(finding, verification))
            verification_records.append(_record(finding, verification))
            continue

        if decision.status != VerificationStatus.NOT_REQUESTED or decision.plan is None:
            verification = build_skipped_verification(
                finding,
                decision.status,
                decision.reason or "verification skipped by policy",
                decision.plan,
            )
            verified_findings.append(_apply_verification(finding, verification))
            verification_records.append(_record(finding, verification))
            continue

        eligible += 1
        if executed >= options.budget:
            verification = build_skipped_verification(
                finding,
                VerificationStatus.SKIPPED,
                f"Verification budget exhausted after {options.budget} finding(s).",
                decision.plan,
            )
            verified_findings.append(_apply_verification(finding, verification))
            verification_records.append(_record(finding, verification))
            continue

        finding_artifact_dir = options.artifacts_dir / finding.id if options.artifacts_dir else None
        tool_results = []
        candidate_tests = list(decision.plan.candidate_test_paths)

        for tool in decision.plan.requested_tools:
            result_for_tool = None
            if tool == ToolKind.REPOSITORY_SEARCH:
                result_for_tool = repository_search(workspace, decision.plan.search_terms, finding_artifact_dir)
            elif tool == ToolKind.READ_FILE:
                result_for_tool = read_repository_file(workspace, finding.file_path, finding_artifact_dir)
            elif tool == ToolKind.TEST_DISCOVERY:
                result_for_tool, discovered = discover_tests(
                    workspace,
                    finding,
                    decision.plan.search_terms,
                    finding_artifact_dir,
                )
                candidate_tests.extend(discovered)
            elif tool == ToolKind.DEPENDENCY_INSPECTION:
                result_for_tool = inspect_dependencies(workspace, finding_artifact_dir)
            elif tool == ToolKind.PYTEST:
                test_path = _first_existing_path(workspace, candidate_tests)
                if test_path is None:
                    result_for_tool = _skipped_tool(tool, "No approved candidate test path exists.", candidate_tests)
                else:
                    result_for_tool = run_pytest(workspace, test_path, options.timeout_seconds, finding_artifact_dir)
            elif tool == ToolKind.RUFF:
                result_for_tool = run_ruff(workspace, [finding.file_path], options.timeout_seconds, finding_artifact_dir)
            elif tool == ToolKind.MYPY:
                result_for_tool = run_mypy(workspace, [finding.file_path], options.timeout_seconds, finding_artifact_dir)

            if result_for_tool is None:
                continue
            tool_results.append(result_for_tool)
            tool_counts[result_for_tool.tool.value] = tool_counts.get(result_for_tool.tool.value, 0) + 1
            if result_for_tool.tool in EXECUTION_TOOLS:
                sandbox_tool_count += 1

        executed += 1
        verification = adjudicate_evidence(finding, decision.plan, tool_results)
        _write_finding_artifacts(finding_artifact_dir, verification)
        updated_finding = _apply_verification(finding, verification)
        verification_records.append(_record(finding, verification))
        if verification.publication_decision == "suppress":
            suppressed.append(
                {
                    "finding_id": finding.id,
                    "rule": "evidence-adjudicator",
                    "reason": verification.evidence_summary,
                    "file_path": finding.file_path,
                    "title": finding.title,
                }
            )
            continue
        verified_findings.append(updated_finding)

    verified_findings.sort(key=lambda item: (SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_start or 0))
    published = verified_findings[:max_findings]
    stats = _merge_stats(
        result,
        mode=options.mode,
        eligible=eligible,
        executed=executed,
        suppressed=suppressed,
        records=verification_records,
        tool_counts=tool_counts,
        sandbox_tool_count=sandbox_tool_count,
        latency_seconds=time.perf_counter() - started,
        published_count=len(published),
        publish_policy=options.publish_policy,
    )
    return result.model_copy(update={"findings": published, "stats": stats})


def _apply_verification(finding: ReviewFinding, verification: FindingVerification) -> ReviewFinding:
    return finding.model_copy(update={"verification": verification, "confidence": verification.confidence_after})


def _first_existing_path(repo_root: Path, paths: list[str]) -> str | None:
    for path in list(dict.fromkeys(normalize_repo_path(path) for path in paths)):
        if (repo_root / path).is_file():
            return path
    return None


def _skipped_tool(tool: ToolKind, summary: str, matched_paths: list[str]) -> Any:
    from pr_agent.review.schema import ToolResult

    return ToolResult(
        tool=tool,
        success=False,
        summary=summary,
        duration_ms=0,
        matched_paths=list(dict.fromkeys(matched_paths)),
    )


def _write_finding_artifacts(artifact_dir: Path | None, verification: FindingVerification) -> None:
    if artifact_dir is None:
        return
    write_json_artifact(artifact_dir / "tool_result.json", verification.model_dump(mode="json"))


def _record(finding: ReviewFinding, verification: FindingVerification) -> dict[str, Any]:
    return {
        "finding_id": finding.id,
        "status": verification.status.value,
        "publication_decision": verification.publication_decision,
        "confidence_before": verification.confidence_before,
        "confidence_after": verification.confidence_after,
        "evidence_summary": verification.evidence_summary,
        "tool_results": [tool.model_dump(mode="json") for tool in verification.tool_results],
    }


def _merge_stats(
    result: ReviewResult,
    mode: str,
    eligible: int,
    executed: int,
    suppressed: list[dict[str, Any]],
    records: list[dict[str, Any]],
    tool_counts: dict[str, int],
    sandbox_tool_count: int,
    latency_seconds: float,
    published_count: int,
    publish_policy: str,
) -> dict[str, Any]:
    stats = dict(result.stats)
    verification = dict(stats.get("verification") or {})
    existing_suppressions = list(verification.get("suppressions") or [])
    existing_suppressions.extend(suppressed)
    candidate_count = int(verification.get("candidate_findings", len(result.findings)) or len(result.findings))
    previous_suppressed = int(verification.get("suppressed_findings", 0) or 0)
    verification.update(
        {
            "mode": mode,
            "publish_policy": publish_policy,
            "candidate_findings": candidate_count,
            "eligible_findings": eligible,
            "verified_findings": executed,
            "evidence_suppressed_findings": len(suppressed),
            "suppressed_findings": previous_suppressed + len(suppressed),
            "published_findings": published_count,
            "verification_coverage": executed / eligible if eligible else 0.0,
            "supported_finding_rate": _rate(records, "supported"),
            "contradicted_suppression_rate": _contradicted_suppression_rate(records),
            "inconclusive_rate": _rate(records, "inconclusive"),
            "sandbox_failure_rate": _sandbox_failure_rate(records),
            "verification_latency_seconds": latency_seconds,
            "tool_cost": {
                "static_tool_calls": sum(count for tool, count in tool_counts.items() if tool not in {"pytest", "ruff", "mypy"}),
                "sandbox_tool_calls": sandbox_tool_count,
                "tool_counts": tool_counts,
            },
            "suppressions": existing_suppressions,
            "records": records,
        }
    )
    stats["verification"] = verification
    return stats


def _rate(records: list[dict[str, Any]], status: str) -> float:
    if not records:
        return 0.0
    return sum(1 for record in records if record.get("status") == status) / len(records)


def _contradicted_suppression_rate(records: list[dict[str, Any]]) -> float:
    contradicted = [record for record in records if record.get("status") == "contradicted"]
    if not contradicted:
        return 0.0
    suppressed = [record for record in contradicted if record.get("publication_decision") == "suppress"]
    return len(suppressed) / len(contradicted)


def _sandbox_failure_rate(records: list[dict[str, Any]]) -> float:
    sandbox_results = [
        tool
        for record in records
        for tool in record.get("tool_results", [])
        if tool.get("tool") in {"pytest", "ruff", "mypy"}
    ]
    if not sandbox_results:
        return 0.0
    failures = [tool for tool in sandbox_results if not tool.get("success")]
    return len(failures) / len(sandbox_results)
