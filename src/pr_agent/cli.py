"""CLI 入口：提供 fetch 和 review 两个本地 MVP 命令。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import typer

from pr_agent.agents.general_reviewer import GeneralReviewer
from pr_agent.config import load_config
from pr_agent.context.retriever import ContextRetriever
from pr_agent.diff.filters import should_review_file
from pr_agent.diff.models import DiffHunk
from pr_agent.diff.parser import parse_patch
from pr_agent.github.client import GitHubClient, parse_github_pr_url
from pr_agent.github.models import ChangedFile, PRInfo
from pr_agent.llm.client import OpenAICompatibleLLMClient
from pr_agent.review.renderer import MarkdownRenderer
from pr_agent.review.schema import ReviewFinding, ReviewResult
from pr_agent.review.validator import validate_findings
from pr_agent.utils.env import load_dotenv_file


app = typer.Typer(help="AI PR Review Agent MVP")


@app.command()
def fetch(
    pr_url: str,
    out: Path = typer.Option(Path("outputs/demo"), "--out", "-o", help="Output directory"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
) -> None:
    """Fetch PR metadata and changed files, then parse patch hunks."""
    load_dotenv_file()
    cfg = load_config(config)
    pr, files, hunks_by_file = _fetch_pr_bundle(pr_url, cfg.github.api_base_url, cfg.github.timeout_seconds)

    payload = {
        "pr": pr.model_dump(mode="json"),
        "files": [file.model_dump(mode="json") for file in files],
        "hunks": {
            filename: [hunk.model_dump(mode="json") for hunk in hunks]
            for filename, hunks in hunks_by_file.items()
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "fetch_result.json", payload)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def review(
    pr_url: str,
    out: Path = typer.Option(Path("outputs/demo"), "--out", "-o", help="Output directory"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
) -> None:
    """Run the full MVP review and write JSON, Markdown, and trace files."""
    load_dotenv_file()
    started = time.perf_counter()
    trace_id = str(uuid.uuid4())
    cfg = load_config(config)
    pr, files, hunks_by_file = _fetch_pr_bundle(pr_url, cfg.github.api_base_url, cfg.github.timeout_seconds)
    reviewable_files = [file for file in files if should_review_file(file, cfg)][: cfg.review.max_files]

    github_client = GitHubClient(api_base_url=cfg.github.api_base_url, timeout_seconds=cfg.github.timeout_seconds)
    retriever = ContextRetriever(github_client=github_client, config=cfg)
    llm_client = OpenAICompatibleLLMClient.from_env(cfg.llm)
    reviewer = GeneralReviewer(llm_client)

    all_findings: list[ReviewFinding] = []
    summaries: list[str] = []
    trace_rows: list[dict[str, Any]] = []
    total_tokens = 0
    llm_latency = 0.0
    model_name = ""

    for file in reviewable_files:
        hunks = hunks_by_file.get(file.filename, [])
        context = retriever.build(pr, file, hunks)
        summary, findings, stats = reviewer.review_context(context)
        summaries.append(summary)
        all_findings.extend(findings)
        llm_latency += float(stats.get("latency_seconds", 0.0))
        total_tokens += int(stats.get("total_tokens") or 0)
        model_name = str(stats.get("model") or model_name)
        trace_rows.append({"trace_id": trace_id, "file": file.filename, "summary": summary, "stats": stats})

    raw_result = ReviewResult(
        pr=pr,
        summary=_merge_summaries(summaries, pr, len(reviewable_files)),
        findings=all_findings,
        stats={
            "files_seen": len(files),
            "files_reviewed": len(reviewable_files),
            "latency_seconds": time.perf_counter() - started,
            "llm_latency_seconds": llm_latency,
            "total_tokens": total_tokens,
        },
        model_info={"provider": cfg.llm.provider, "model": model_name or cfg.llm.model},
        trace_id=trace_id,
    )
    all_hunks = [hunk for hunks in hunks_by_file.values() for hunk in hunks]
    result = validate_findings(
        raw_result,
        all_hunks,
        confidence_threshold=cfg.review.confidence_threshold,
        max_findings=cfg.review.max_findings,
    )

    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "review_result.json", result.model_dump(mode="json"))
    (out / "review_report.md").write_text(MarkdownRenderer().render(result), encoding="utf-8")
    _write_trace(out / "trace.jsonl", trace_rows)
    typer.echo(f"Wrote review_result.json and review_report.md to {out}")


def _fetch_pr_bundle(
    pr_url: str,
    api_base_url: str,
    timeout_seconds: float,
) -> tuple[PRInfo, list[ChangedFile], dict[str, list[DiffHunk]]]:
    ref = parse_github_pr_url(pr_url)
    client = GitHubClient(api_base_url=api_base_url, timeout_seconds=timeout_seconds)
    pr = client.get_pull_request(ref.owner, ref.repo, ref.pull_number)
    files = client.list_pull_request_files(ref.owner, ref.repo, ref.pull_number)
    hunks_by_file = {file.filename: parse_patch(file.filename, file.patch) for file in files}
    return pr, files, hunks_by_file


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _merge_summaries(summaries: list[str], pr: PRInfo, files_reviewed: int) -> str:
    if not summaries:
        return f"Reviewed PR #{pr.pull_number} ({pr.title}); no reviewable files were processed."
    return f"Reviewed {files_reviewed} file(s) in PR #{pr.pull_number}: " + " ".join(summaries[:3])
