"""Reusable review pipeline shared by CLI commands and GitHub Actions."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pr_agent.agents.general_reviewer import GeneralReviewer
from pr_agent.agents.multi_agent_reviewer import DEFAULT_REVIEWER_SPECS, MultiAgentReviewer
from pr_agent.config import AppConfig
from pr_agent.context.retriever import ContextRetriever
from pr_agent.diff.filters import should_review_file
from pr_agent.github.client import GitHubClient
from pr_agent.github.models import ChangedFile
from pr_agent.llm.client import LLMClient, OpenAICompatibleLLMClient
from pr_agent.review.llm_verifier import verify_findings_with_llm
from pr_agent.review.renderer import MarkdownRenderer
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.review.validator import validate_findings
from pr_agent.review.verifier import verify_findings
from pr_agent.targets.loader import ChangeSetLoader
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.executor import verify_review_result
from pr_agent.tools.policy import VerificationOptions


@dataclass(frozen=True)
class ReviewRun:
    result: ReviewResult
    change_set: ChangeSet
    reviewable_files: list[ChangedFile]
    trace_rows: list[dict[str, Any]]


def load_change_set(
    target: str,
    api_base_url: str,
    timeout_seconds: float,
    repo_root: Path | None = None,
) -> ChangeSet:
    client = GitHubClient(api_base_url=api_base_url, timeout_seconds=timeout_seconds)
    return ChangeSetLoader(github_client=client, repo_root=repo_root or Path.cwd()).load(target)


def run_review(
    target: str,
    cfg: AppConfig,
    repo_root: Path | None = None,
    verification_options: VerificationOptions | None = None,
) -> ReviewRun:
    root = repo_root or Path.cwd()
    change_set = load_change_set(target, cfg.github.api_base_url, cfg.github.timeout_seconds, root)
    return run_review_on_change_set(change_set, cfg, repo_root=root, verification_options=verification_options)


def run_review_on_change_set(
    change_set: ChangeSet,
    cfg: AppConfig,
    repo_root: Path | None = None,
    llm_client: LLMClient | None = None,
    verifier_llm_client: LLMClient | None = None,
    verifier_skip_reason: str | None = None,
    verification_options: VerificationOptions | None = None,
) -> ReviewRun:
    started = time.perf_counter()
    trace_id = str(uuid.uuid4())
    root = repo_root or Path.cwd()
    reviewable_files = [file for file in change_set.files if should_review_file(file, cfg)][: cfg.review.max_files]

    github_client = GitHubClient(api_base_url=cfg.github.api_base_url, timeout_seconds=cfg.github.timeout_seconds)
    retriever = ContextRetriever(github_client=github_client, config=cfg, repo_root=root)
    active_llm_client = llm_client or OpenAICompatibleLLMClient.from_env(cfg.llm)
    reviewer = _build_reviewer(active_llm_client, cfg)

    all_findings: list[ReviewFinding] = []
    summaries: list[str] = []
    trace_rows: list[dict[str, Any]] = []
    total_tokens = 0
    llm_latency = 0.0
    model_name = ""

    for file in reviewable_files:
        hunks = change_set.hunks_by_file.get(file.filename, [])
        context = retriever.build(change_set.target, file, hunks)
        summary, findings, stats = reviewer.review_context(context)
        summaries.append(summary)
        all_findings.extend(findings)
        llm_latency += float(stats.get("latency_seconds", 0.0))
        total_tokens += int(stats.get("total_tokens") or 0)
        model_name = str(stats.get("model") or model_name)
        trace_rows.append({"trace_id": trace_id, "file": file.filename, "summary": summary, "stats": stats})

    raw_result = ReviewResult(
        pr=change_set.target,
        summary=_merge_summaries(summaries, change_set, len(reviewable_files)),
        findings=all_findings,
        stats={
            "target_type": change_set.target.source_type,
            "files_seen": len(change_set.files),
            "files_reviewed": len(reviewable_files),
            "latency_seconds": time.perf_counter() - started,
            "llm_latency_seconds": llm_latency,
            "total_tokens": total_tokens,
        },
        model_info={"provider": cfg.llm.provider, "model": model_name or cfg.llm.model},
        trace_id=trace_id,
    )
    all_hunks = [hunk for hunks in change_set.hunks_by_file.values() for hunk in hunks]
    structurally_valid_result = validate_findings(
        raw_result,
        all_hunks,
        confidence_threshold=cfg.review.confidence_threshold,
        max_findings=max(cfg.review.max_findings * 4, 32),
    )
    deterministic_result = verify_findings(
        structurally_valid_result,
        change_set,
        root,
        max_findings=max(cfg.review.max_findings * 4, 32),
    )
    evidence_result = deterministic_result
    if verification_options is not None and verification_options.mode != "off":
        evidence_result = verify_review_result(
            deterministic_result,
            change_set,
            root,
            verification_options,
            max_findings=max(cfg.review.max_findings * 4, 32),
        )
        trace_rows.append(
            {
                "trace_id": trace_id,
                "stage": "evidence_verification",
                "stats": (evidence_result.stats.get("verification") or {}),
            }
        )
    if verifier_llm_client is None and verifier_skip_reason is None:
        verifier_llm_client, verifier_skip_reason = _build_verifier_llm_client(cfg)
    result = verify_findings_with_llm(
        evidence_result,
        change_set,
        verifier_llm_client,
        max_findings=cfg.review.max_findings,
        skip_reason=verifier_skip_reason,
    )
    return ReviewRun(result=result, change_set=change_set, reviewable_files=reviewable_files, trace_rows=trace_rows)


def write_review_outputs(run: ReviewRun, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "review_result.json", run.result.model_dump(mode="json"))
    if run.result.stats.get("verification"):
        _write_json(out / "verification_report.json", run.result.stats.get("verification"))
    (out / "review_report.md").write_text(MarkdownRenderer().render(run.result), encoding="utf-8")
    _write_trace(out / "trace.jsonl", run.trace_rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _merge_summaries(summaries: list[str], change_set: ChangeSet, files_reviewed: int) -> str:
    target = change_set.target
    if not summaries:
        return f"Reviewed {target.source_type} target {target.identifier}; no reviewable files were processed."
    return f"Reviewed {files_reviewed} file(s) in {target.source_type} target {target.identifier}: " + " ".join(summaries[:3])


def _build_verifier_llm_client(cfg: AppConfig) -> tuple[OpenAICompatibleLLMClient | None, str | None]:
    if not cfg.verifier_llm.enabled:
        return None, "verifier_llm.enabled is false"
    if not os.getenv("VERIFIER_OPENAI_API_KEY"):
        return None, "VERIFIER_OPENAI_API_KEY is not configured"
    try:
        return OpenAICompatibleLLMClient.from_env(cfg.verifier_llm, env_prefix="VERIFIER_OPENAI"), None
    except Exception as exc:
        return None, f"verifier LLM setup failed: {exc.__class__.__name__}: {exc}"


def _build_reviewer(llm_client: LLMClient, cfg: AppConfig) -> GeneralReviewer | MultiAgentReviewer:
    if cfg.review.reviewer_mode == "single":
        return GeneralReviewer(llm_client)

    enabled = set(cfg.review.enabled_reviewers)
    specs = tuple(spec for spec in DEFAULT_REVIEWER_SPECS if spec.reviewer_id in enabled)
    if not specs:
        return GeneralReviewer(llm_client)
    return MultiAgentReviewer(llm_client, reviewer_specs=specs)
