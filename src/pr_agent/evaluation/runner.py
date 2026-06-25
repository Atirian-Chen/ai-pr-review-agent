"""Executable PR-case evaluation runner."""

from __future__ import annotations

import difflib
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pr_agent.config import AppConfig
from pr_agent.diff.parser import parse_patch
from pr_agent.evaluation.dataset import (
    PRCase,
    PRPredictedFinding,
    PRPredictionRecord,
    build_pr_evaluation_report,
    load_pr_evaluation_cases,
    report_to_json,
)
from pr_agent.github.models import ChangedFile, ReviewTargetInfo
from pr_agent.llm.client import LLMClient, LLMJsonResponse, parse_json_payload
from pr_agent.review.runner import run_review_on_change_set, write_review_outputs
from pr_agent.targets.models import ChangeSet


LLMMode = Literal["deterministic", "live"]


@dataclass(frozen=True)
class EvalRunResult:
    predictions: list[PRPredictionRecord]
    report: dict[str, Any]


def run_pr_evaluation(
    cases_path: Path,
    out: Path,
    cfg: AppConfig,
    llm_mode: LLMMode = "deterministic",
    line_tolerance: int = 3,
) -> EvalRunResult:
    cases = load_pr_evaluation_cases(cases_path)
    runnable_cases = [case for case in cases if case.files]
    if not runnable_cases:
        raise ValueError(f"No runnable PR cases with files were found in {cases_path}")

    out.mkdir(parents=True, exist_ok=True)
    predictions: list[PRPredictionRecord] = []

    with tempfile.TemporaryDirectory(prefix="pr-agent-eval-") as workspace:
        workspace_root = Path(workspace)
        for case in runnable_cases:
            case_started = time.perf_counter()
            case_root = workspace_root / case.id
            change_set = materialize_pr_case(case, case_root)
            llm_client = DeterministicEvalLLMClient() if llm_mode == "deterministic" else None
            review_run = run_review_on_change_set(
                change_set,
                cfg,
                repo_root=case_root,
                llm_client=llm_client,
                verifier_llm_client=None,
                verifier_skip_reason="eval-run deterministic mode" if llm_mode == "deterministic" else None,
            )
            case_out = out / "cases" / case.id
            write_review_outputs(review_run, case_out)
            predictions.append(_prediction_from_review(case.id, review_run.result, time.perf_counter() - case_started))

    predictions_path = out / "pr_predictions.jsonl"
    predictions_path.write_text(
        "\n".join(prediction.model_dump_json() for prediction in predictions) + "\n",
        encoding="utf-8",
    )
    report = build_pr_evaluation_report(runnable_cases, predictions, line_tolerance=line_tolerance)
    (out / "evaluation_report.json").write_text(report_to_json(report) + "\n", encoding="utf-8")
    _write_summary(out / "summary.md", report, predictions_path)
    return EvalRunResult(predictions=predictions, report=report)


def materialize_pr_case(case: PRCase, repo_root: Path) -> ChangeSet:
    _reset_directory(repo_root)
    files: list[ChangedFile] = []
    hunks_by_file = {}

    for case_file in case.files:
        target_path = repo_root / case_file.path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(case_file.head, encoding="utf-8")
        patch = _build_patch(case_file.path, case_file.base, case_file.head)
        changed_file = _changed_file(case_file.path, patch)
        files.append(changed_file)
        hunks_by_file[case_file.path] = parse_patch(case_file.path, patch)

    target = ReviewTargetInfo(
        source_type="local_diff",
        owner="evaluation",
        repo=case.id,
        identifier=case.id,
        title=case.title,
        body=case.description,
        base_branch="base",
        head_branch="head",
        base_sha=f"{case.id}-base",
        head_sha=f"{case.id}-head",
        author="evaluation",
        url=f"evaluation://{case.id}",
    )
    return ChangeSet(target=target, files=files, hunks_by_file=hunks_by_file)


class DeterministicEvalLLMClient(LLMClient):
    """Offline reviewer used to make eval-run reproducible without provider keys."""

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMJsonResponse:
        started = time.perf_counter()
        payload = parse_json_payload(user_prompt)
        role = _role_from_system_prompt(system_prompt)
        findings = _deterministic_findings(role, payload)
        data = {
            "summary": f"{role} deterministic evaluation pass produced {len(findings)} finding(s).",
            "findings": findings,
        }
        token_estimate = max(1, (len(system_prompt) + len(user_prompt) + len(json.dumps(data))) // 4)
        return LLMJsonResponse(
            data=data,
            latency_seconds=time.perf_counter() - started,
            model="deterministic-eval-reviewer",
            usage={"total_tokens": token_estimate},
            raw_text=json.dumps(data),
        )


def _deterministic_findings(role: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    changed_file = payload.get("changed_file") or {}
    filename = str(changed_file.get("filename") or "")
    patch = str(payload.get("diff_patch") or "")
    lower_patch = patch.lower()

    if role == "bug":
        if "return user.display_name" in patch:
            return [_finding(filename, patch, "bug", "major", "User can be None before display_name access", "Guard the unauthenticated branch before reading display_name.", "test_profile_requires_authenticated_user")]
        if "cursor = none" in lower_patch or "page = items[:limit]" in lower_patch:
            return [_finding(filename, patch, "bug", "major", "Cursor parameter is ignored", "Use the supplied cursor when selecting the page window.", "test_next_page_uses_cursor")]
        if "bool(os.getenv" in patch or "return bool(value)" in patch:
            return [_finding(filename, patch, "bug", "major", "String false is parsed as enabled", "Parse boolean strings explicitly instead of relying on truthiness.", "test_false_string_disables_flag")]
        if "datetime.utcnow()" in patch:
            return [_finding(filename, patch, "bug", "major", "Naive UTC timestamp can break comparisons", "Use timezone-aware UTC timestamps.", "test_timezone_aware_cycle_comparison")]
        if "except json.JSONDecodeError" in patch and "return {}" in patch:
            return [_finding(filename, patch, "bug", "major", "Invalid JSON payloads are silently accepted", "Raise a bad-request error instead of returning an empty object.", "test_invalid_json_is_rejected")]
    if role == "security":
        if "f\"select" in lower_patch or "f'select" in lower_patch:
            return [_finding(filename, patch, "security", "critical", "User input is interpolated into SQL", "Use parameterized queries for user-controlled search terms.", "test_search_uses_parameters")]
        if "authorization" in lower_patch and "logger" in lower_patch:
            return [_finding(filename, patch, "security", "critical", "Authorization token can be written to logs", "Redact sensitive headers before logging.", "test_authorization_header_redacted")]
        if "verify_aud" in lower_patch and "false" in lower_patch:
            return [_finding(filename, patch, "security", "critical", "JWT audience validation is disabled", "Require the expected audience when decoding tokens.", "test_rejects_wrong_audience")]
        if "yaml.load" in lower_patch:
            return [_finding(filename, patch, "security", "critical", "Unsafe YAML load can construct objects", "Use yaml.safe_load for untrusted configuration.", "test_yaml_uses_safe_loader")]
        if "requests.get(url" in lower_patch or "httpx.get(url" in lower_patch:
            return [_finding(filename, patch, "security", "critical", "User provided callback URL can trigger SSRF", "Validate scheme and host before fetching callback URLs.", "test_rejects_private_callback_host")]
    if role == "performance":
        if "for project in projects" in lower_patch and "get_owner" in lower_patch:
            return [_finding(filename, patch, "performance", "major", "Per-project owner lookup introduces N+1 calls", "Batch load owners before building dashboard rows.", "test_dashboard_batches_owner_lookup")]
        if "re.compile" in lower_patch and "for line" in lower_patch:
            return [_finding(filename, patch, "performance", "minor", "Regex is compiled inside a hot loop", "Move regex compilation outside the loop.", "test_parser_reuses_compiled_regex")]
        if "for left in rows" in lower_patch and "for right in rows" in lower_patch:
            return [_finding(filename, patch, "performance", "major", "Nested duplicate scan can become quadratic", "Use a set keyed by row identity for duplicate detection.", "test_dedupe_uses_linear_lookup")]
        if "list(queryset)" in lower_patch and ".copy()" in lower_patch:
            return [_finding(filename, patch, "performance", "major", "Large export result is materialized twice", "Stream rows or avoid copying the full list.", "test_export_does_not_copy_all_rows")]
        if "sorted(records)" in lower_patch and "[:limit]" in lower_patch:
            return [_finding(filename, patch, "performance", "major", "Full table is sorted before pagination", "Push sorting and pagination into the query layer.", "test_listing_paginates_before_materializing")]
    if role == "test":
        if "return user.display_name" in patch:
            return [_finding(filename, patch, "test", "minor", "Missing unauthenticated profile regression test", "Add a test covering requests without an authenticated user.", "test_profile_requires_authenticated_user")]
        if "if after == \"0\" * 40" in patch:
            return [_finding(filename, patch, "test", "minor", "Missing branch deletion event regression test", "Add a push event test with an all-zero after SHA.", "test_skips_branch_deletion_push")]
        if "parse_compare_url" in patch or "compare/" in patch:
            return [_finding(filename, patch, "test", "minor", "Missing malformed compare URL parser test", "Add a negative parser test for malformed compare URLs.", "test_rejects_malformed_compare_url")]
        if "role in allowed_roles" in patch:
            return [_finding(filename, patch, "test", "minor", "Missing denied-role permission regression test", "Add a test for users outside the allowed role set.", "test_denies_unlisted_role")]
        if "max_attempts" in patch and "while" in patch:
            return [_finding(filename, patch, "test", "minor", "Missing retry exhaustion test case", "Add a test that exhausts retries and returns the final error.", "test_retry_exhaustion_returns_error")]
    return []


def _finding(filename: str, patch: str, category: str, severity: str, title: str, fix: str, test_name: str) -> dict[str, Any]:
    line = _first_added_line_number(patch)
    return {
        "file_path": filename,
        "line_start": line,
        "line_end": line,
        "category": category,
        "severity": severity,
        "confidence": 0.86,
        "title": title,
        "description": title,
        "evidence": _first_added_line(patch),
        "suggestion": fix,
        "failure_mode": f"changed input path -> {title}",
        "why_introduced_by_diff": "The issue is visible in the added lines of this patch.",
        "false_positive_checks": ["Matched a deterministic evaluation pattern in the changed diff."],
        "patch_suggestion": {
            "description": fix,
            "suggested_patch": None,
            "commands": ["python -m pytest"],
        },
        "test_suggestions": [
            {
                "test_file_path": f"tests/test_{Path(filename).stem}.py",
                "test_name": test_name,
                "scenario": f"Regression coverage for: {title}",
                "assertions": ["The changed behavior fails before the fix and passes after it."],
                "suggested_test_code": None,
            }
        ],
    }


def _prediction_from_review(case_id: str, result, latency_seconds: float) -> PRPredictionRecord:
    findings = [
        PRPredictedFinding(
            category=finding.category,
            file_path=finding.file_path,
            line_start=finding.line_start,
            line_end=finding.line_end,
            severity=finding.severity,
            confidence=finding.confidence,
            title=finding.title,
            has_patch_suggestion=finding.patch_suggestion is not None or bool(finding.suggested_patch),
            has_test_suggestion=bool(finding.test_suggestions),
            verification_status=finding.verification.status.value if finding.verification else None,
            publication_decision=finding.verification.publication_decision if finding.verification else None,
        )
        for finding in result.findings
    ]
    verification = result.stats.get("verification") or {}
    tool_cost = verification.get("tool_cost") or {}
    sandbox_tool_calls = int(tool_cost.get("sandbox_tool_calls") or 0)
    return PRPredictionRecord(
        case_id=case_id,
        findings=findings,
        latency_seconds=latency_seconds,
        verification_latency_seconds=verification.get("verification_latency_seconds"),
        total_tokens=int(result.stats.get("total_tokens") or 0),
        cost_usd=None,
        static_tool_calls=tool_cost.get("static_tool_calls"),
        sandbox_tool_calls=sandbox_tool_calls,
        llm_verifier_calls=1 if (result.stats.get("llm_verifier") or {}).get("status") == "completed" else 0,
        sandbox_failures=int((verification.get("sandbox_failure_rate") or 0) * sandbox_tool_calls),
    )


def _build_patch(path: str, base: str, head: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            base.splitlines(),
            head.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=3,
        )
    )
    for index, line in enumerate(diff_lines):
        if line.startswith("@@ "):
            return "\n".join(diff_lines[index:])
    return ""


def _changed_file(path: str, patch: str) -> ChangedFile:
    additions = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    status = "added" if deletions == 0 else "modified"
    return ChangedFile(filename=path, status=status, additions=additions, deletions=deletions, changes=additions + deletions, patch=patch)


def _first_added_line_number(patch: str) -> int:
    for hunk in parse_patch("file.py", patch):
        for line in hunk.lines:
            if line.line_type == "add" and line.new_line_no is not None:
                return line.new_line_no
    return 1


def _first_added_line(patch: str) -> str:
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            return line
    return "+ changed line"


def _role_from_system_prompt(system_prompt: str) -> str:
    if "Bug Reviewer" in system_prompt:
        return "bug"
    if "Test Reviewer" in system_prompt:
        return "test"
    if "Security Reviewer" in system_prompt:
        return "security"
    if "Performance Reviewer" in system_prompt:
        return "performance"
    return "general"


def _reset_directory(path: Path) -> None:
    if path.exists():
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    path.mkdir(parents=True, exist_ok=True)


def _write_summary(path: Path, report: dict[str, Any], predictions_path: Path) -> None:
    metrics = report.get("metrics") or {}
    lines = [
        "# Evaluation Run Summary",
        "",
        f"- PR cases: {report.get('total_pr_cases', 0)}",
        f"- Expected findings: {report.get('total_expected_findings', 0)}",
        f"- Predictions: `{predictions_path.name}`",
        f"- valid_finding_rate: {metrics.get('valid_finding_rate', 0):.2%}",
        f"- line_hit_rate: {metrics.get('line_hit_rate', 0):.2%}",
        f"- false_positive_rate: {metrics.get('false_positive_rate', 0):.2%}",
        f"- fixability_rate: {metrics.get('fixability_rate', 0):.2%}",
        f"- total_tokens: {(metrics.get('token_cost') or {}).get('total_tokens', 0)}",
        f"- total_latency_seconds: {(metrics.get('latency') or {}).get('total_seconds', 0):.2f}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
