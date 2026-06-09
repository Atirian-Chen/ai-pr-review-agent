"""LLM-based second-pass verification for review findings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pr_agent.llm.client import LLMClient
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.review.verifier import SEVERITY_RANK
from pr_agent.targets.models import ChangeSet


Decision = Literal["keep", "suppress", "downgrade"]
VALID_DECISIONS = {"keep", "suppress", "downgrade"}
VALID_SEVERITIES = {"critical", "major", "minor", "nit"}
MAX_PATCH_CHARS_PER_FILE = 6000


LLM_VERIFIER_SYSTEM_PROMPT = """
You are a conservative verification reviewer for AI code-review findings.

Your job is NOT to find new issues. Your only job is to verify candidate findings
that another model already produced.

Decision policy:
- keep: the finding is clearly supported by the changed diff/context and has an actionable failure mode.
- suppress: the finding is speculative, contradicted by the diff/context, too generic, purely stylistic, or lacks a concrete failure path.
- downgrade: the finding may be valid, but its severity or confidence is overstated.

Important constraints:
- Do not add new findings.
- Do not upgrade severity or confidence.
- Suppress missing-test findings unless they identify a concrete untested behavior or edge case.
- Suppress findings that depend on assumptions not present in the candidate evidence or diff.
- For docs/tests/evaluation files, prefer downgrade unless there is a concrete user-facing or security impact.

Return JSON only with this shape:
{
  "summary": "short verifier summary",
  "verdicts": [
    {
      "finding_id": "same id as input",
      "decision": "keep|suppress|downgrade",
      "reason": "brief reason",
      "severity": "critical|major|minor|nit|null",
      "confidence": 0.0
    }
  ]
}
""".strip()


@dataclass(frozen=True)
class FindingVerdict:
    finding_id: str
    decision: Decision
    reason: str
    severity: str | None = None
    confidence: float | None = None


def verify_findings_with_llm(
    result: ReviewResult,
    change_set: ChangeSet,
    llm_client: LLMClient | None,
    max_findings: int,
    skip_reason: str | None = None,
) -> ReviewResult:
    """Apply an optional LLM verifier, then enforce the final publication limit."""

    if not result.findings:
        return _finalize_without_call(result, max_findings, status="skipped", reason="no candidate findings")

    if llm_client is None:
        return _finalize_without_call(
            result,
            max_findings,
            status="skipped",
            reason=skip_reason or "verifier LLM is not configured",
        )

    try:
        response = llm_client.complete_json(
            system_prompt=LLM_VERIFIER_SYSTEM_PROMPT,
            user_prompt=_build_llm_verifier_user_prompt(result, change_set),
        )
        verdicts = _parse_verdicts(response.data, {finding.id for finding in result.findings})
    except Exception as exc:
        finalized = _limit_findings(result, max_findings)
        stats = _stats_with_llm_verifier(
            finalized,
            status="error",
            error=f"{exc.__class__.__name__}: {exc}",
        )
        return finalized.model_copy(update={"stats": stats})

    findings_by_id = {finding.id: finding for finding in result.findings}
    kept: list[ReviewFinding] = []
    suppressed: list[dict[str, str]] = []
    downgraded_count = 0

    for finding in result.findings:
        verdict = verdicts.get(finding.id)
        if verdict is None:
            kept.append(finding)
            continue
        if verdict.decision == "suppress":
            suppressed.append(_suppression_payload(finding, verdict.reason))
            continue
        if verdict.decision == "downgrade":
            downgraded = _downgrade_finding(finding, verdict)
            if downgraded != finding:
                downgraded_count += 1
            kept.append(downgraded)
            continue
        kept.append(finding)

    kept.sort(key=lambda item: (SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_start or 0))
    published = kept[:max_findings]
    stats = _stats_with_llm_verifier(
        result.model_copy(update={"findings": published}),
        status="completed",
        model=response.model,
        latency_seconds=response.latency_seconds,
        total_tokens=response.usage.get("total_tokens", 0),
        reviewed_findings=len(findings_by_id),
        kept_findings=len(kept),
        suppressed_findings=len(suppressed),
        downgraded_findings=downgraded_count,
        suppressions=suppressed,
        verifier_summary=str(response.data.get("summary") or ""),
    )
    return result.model_copy(update={"findings": published, "stats": stats})


def _build_llm_verifier_user_prompt(result: ReviewResult, change_set: ChangeSet) -> str:
    referenced_files = {finding.file_path for finding in result.findings}
    patches_by_file = {file.filename: file.patch or "" for file in change_set.files if file.filename in referenced_files}
    payload = {
        "target": {
            "source_type": change_set.target.source_type,
            "identifier": change_set.target.identifier,
            "title": change_set.target.title,
            "base_sha": change_set.target.base_sha,
            "head_sha": change_set.target.head_sha,
        },
        "candidate_findings": [_finding_payload(finding) for finding in result.findings],
        "changed_file_patches": [
            {
                "filename": filename,
                "patch": _truncate_patch(patch),
            }
            for filename, patch in patches_by_file.items()
        ],
    }
    return "Verify these candidate review findings against the changed diff.\n\n" + json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )


def _finding_payload(finding: ReviewFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "file_path": finding.file_path,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "category": finding.category,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "title": finding.title,
        "description": finding.description,
        "evidence": finding.evidence,
        "suggestion": finding.suggestion,
        "failure_mode": finding.failure_mode,
        "why_introduced_by_diff": finding.why_introduced_by_diff,
        "false_positive_checks": finding.false_positive_checks,
    }


def _parse_verdicts(data: dict[str, Any], valid_ids: set[str]) -> dict[str, FindingVerdict]:
    raw_verdicts = data.get("verdicts") or []
    if not isinstance(raw_verdicts, list):
        return {}

    verdicts: dict[str, FindingVerdict] = {}
    for raw in raw_verdicts:
        if not isinstance(raw, dict):
            continue
        finding_id = str(raw.get("finding_id") or "")
        decision = str(raw.get("decision") or "").lower()
        if finding_id not in valid_ids or decision not in VALID_DECISIONS:
            continue
        severity = raw.get("severity")
        if severity is not None:
            severity = str(severity).lower()
        if severity not in VALID_SEVERITIES:
            severity = None
        verdicts[finding_id] = FindingVerdict(
            finding_id=finding_id,
            decision=decision,  # type: ignore[arg-type]
            reason=str(raw.get("reason") or "Verifier did not provide a reason.").strip(),
            severity=severity,
            confidence=_optional_confidence(raw.get("confidence")),
        )
    return verdicts


def _downgrade_finding(finding: ReviewFinding, verdict: FindingVerdict) -> ReviewFinding:
    updates: dict[str, Any] = {}
    if verdict.severity and SEVERITY_RANK[verdict.severity] >= SEVERITY_RANK[finding.severity]:
        updates["severity"] = verdict.severity
    if verdict.confidence is not None:
        updates["confidence"] = min(finding.confidence, verdict.confidence)
    if not updates:
        return finding
    return finding.model_copy(update=updates)


def _optional_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= confidence <= 1.0:
        return confidence
    return None


def _suppression_payload(finding: ReviewFinding, reason: str) -> dict[str, str]:
    return {
        "finding_id": finding.id,
        "rule": "llm-verifier",
        "reason": reason,
        "file_path": finding.file_path,
        "title": finding.title,
    }


def _finalize_without_call(result: ReviewResult, max_findings: int, status: str, reason: str) -> ReviewResult:
    finalized = _limit_findings(result, max_findings)
    stats = _stats_with_llm_verifier(finalized, status=status, reason=reason)
    return finalized.model_copy(update={"stats": stats})


def _limit_findings(result: ReviewResult, max_findings: int) -> ReviewResult:
    findings = sorted(
        result.findings,
        key=lambda item: (SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_start or 0),
    )[:max_findings]
    return result.model_copy(update={"findings": findings})


def _stats_with_llm_verifier(
    result: ReviewResult,
    status: str,
    reason: str | None = None,
    error: str | None = None,
    model: str | None = None,
    latency_seconds: float | None = None,
    total_tokens: int | None = None,
    reviewed_findings: int | None = None,
    kept_findings: int | None = None,
    suppressed_findings: int = 0,
    downgraded_findings: int = 0,
    suppressions: list[dict[str, str]] | None = None,
    verifier_summary: str = "",
) -> dict[str, Any]:
    stats = dict(result.stats)
    verification = dict(stats.get("verification") or {})
    existing_suppressions = list(verification.get("suppressions") or [])
    existing_suppressions.extend(suppressions or [])

    deterministic_suppressed = int(verification.get("deterministic_suppressed_findings", verification.get("suppressed_findings", 0)) or 0)
    total_suppressed = deterministic_suppressed + suppressed_findings
    verification.update(
        {
            "published_findings": len(result.findings),
            "suppressed_findings": total_suppressed,
            "llm_reviewed_findings": reviewed_findings if reviewed_findings is not None else 0,
            "llm_suppressed_findings": suppressed_findings,
            "llm_downgraded_findings": downgraded_findings,
            "suppressions": existing_suppressions,
        }
    )
    stats["verification"] = verification

    llm_verifier: dict[str, Any] = {"status": status}
    if reason:
        llm_verifier["reason"] = reason
    if error:
        llm_verifier["error"] = error
    if model:
        llm_verifier["model"] = model
    if latency_seconds is not None:
        llm_verifier["latency_seconds"] = latency_seconds
    if total_tokens is not None:
        llm_verifier["total_tokens"] = total_tokens
    if kept_findings is not None:
        llm_verifier["kept_findings"] = kept_findings
    if verifier_summary:
        llm_verifier["summary"] = verifier_summary
    stats["llm_verifier"] = llm_verifier
    return stats


def _truncate_patch(patch: str) -> str:
    if len(patch) <= MAX_PATCH_CHARS_PER_FILE:
        return patch
    return patch[:MAX_PATCH_CHARS_PER_FILE] + "\n...[truncated]"
