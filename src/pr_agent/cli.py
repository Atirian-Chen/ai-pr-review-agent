"""CLI 入口：提供 fetch 和 review 两个本地 MVP 命令。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer

from pr_agent.config import load_config
from pr_agent.evaluation.dataset import (
    build_evaluation_report,
    build_pr_evaluation_report,
    load_evaluation_cases,
    load_pr_evaluation_cases,
    load_pr_predictions,
    load_predictions,
    load_verification_cases,
    report_to_json,
    summarize_verification_cases,
)
from pr_agent.evaluation.runner import run_live_e2e, run_pr_evaluation
from pr_agent.github.actions import GitHubActionSkip, resolve_action_review_target
from pr_agent.github.client import GitHubClient
from pr_agent.github.models import ChangedFile
from pr_agent.github.comments import SUMMARY_COMMENT_MARKER, build_summary_comment
from pr_agent.review.renderer import MarkdownRenderer
from pr_agent.review.runner import ReviewRun, load_change_set, run_review, write_review_outputs
from pr_agent.review.schema import ReviewResult
from pr_agent.targets.models import ChangeSet
from pr_agent.tools.executor import verify_review_result
from pr_agent.tools.policy import VerificationOptions, action_safe_verify_mode, normalize_verify_mode
from pr_agent.utils.env import load_dotenv_file


app = typer.Typer(help="AI PR Review Agent MVP")


@app.command()
def fetch(
    target: str,
    out: Path = typer.Option(Path("outputs/demo"), "--out", "-o", help="Output directory"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
) -> None:
    """Fetch target metadata and changed files, then parse patch hunks."""
    load_dotenv_file()
    cfg = load_config(config)
    change_set = load_change_set(target, cfg.github.api_base_url, cfg.github.timeout_seconds)

    payload = {
        "target": change_set.target.model_dump(mode="json"),
        "files": [file.model_dump(mode="json") for file in change_set.files],
        "hunks": {
            filename: [hunk.model_dump(mode="json") for hunk in hunks]
            for filename, hunks in change_set.hunks_by_file.items()
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "fetch_result.json", payload)
    typer.echo(f"Wrote fetch_result.json to {out}")


@app.command()
def review(
    target: str,
    out: Path = typer.Option(Path("outputs/demo"), "--out", "-o", help="Output directory"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
    verify: str = typer.Option("off", "--verify", help="Verification mode: off, static, or sandbox"),
    workspace: Path | None = typer.Option(None, "--workspace", help="Local repository path used by verification tools"),
    verification_budget: int = typer.Option(3, "--verification-budget", help="Maximum findings to verify"),
    verification_timeout: int = typer.Option(45, "--verification-timeout", help="Per sandbox tool timeout in seconds"),
) -> None:
    """Run the full MVP review and write JSON, Markdown, and trace files."""
    load_dotenv_file()
    cfg = load_config(config)
    mode = normalize_verify_mode(verify)
    repo_root = (workspace or Path.cwd()).resolve()
    verification_options = VerificationOptions(
        mode=mode,
        workspace=repo_root if mode != "off" else workspace,
        budget=verification_budget,
        timeout_seconds=verification_timeout,
        artifacts_dir=out / "artifacts" / "verification" if mode != "off" else None,
        publish_policy=os.getenv("PR_AGENT_PUBLISH_POLICY", "verified_or_high_confidence"),
    )
    review_run = run_review(target, cfg, repo_root=repo_root, verification_options=verification_options)
    write_review_outputs(review_run, out)
    typer.echo(f"Wrote review_result.json and review_report.md to {out}")


@app.command()
def verify(
    review_result: Path,
    workspace: Path = typer.Option(Path("."), "--workspace", help="Local repository path used by verification tools"),
    mode: str = typer.Option("static", "--mode", help="Verification mode: off, static, or sandbox"),
    out: Path = typer.Option(Path("outputs/verified_review"), "--out", "-o", help="Output directory"),
    verification_budget: int = typer.Option(3, "--verification-budget", help="Maximum findings to verify"),
    verification_timeout: int = typer.Option(45, "--verification-timeout", help="Per sandbox tool timeout in seconds"),
) -> None:
    """Verify findings from an existing review_result.json file."""
    resolved_mode = normalize_verify_mode(mode)
    result = ReviewResult.model_validate_json(review_result.read_text(encoding="utf-8"))
    repo_root = workspace.resolve()
    change_set = _change_set_from_review_result(result)
    options = VerificationOptions(
        mode=resolved_mode,
        workspace=repo_root if resolved_mode != "off" else None,
        budget=verification_budget,
        timeout_seconds=verification_timeout,
        artifacts_dir=out / "artifacts" / "verification" if resolved_mode != "off" else None,
        publish_policy=os.getenv("PR_AGENT_PUBLISH_POLICY", "verified_or_high_confidence"),
    )
    verified = verify_review_result(result, change_set, repo_root, options, max_findings=len(result.findings))
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "review_result.json", verified.model_dump(mode="json"))
    _write_json(out / "verification_report.json", verified.stats.get("verification") or {})
    (out / "review_report.md").write_text(MarkdownRenderer().render(verified), encoding="utf-8")
    _write_trace(out / "trace.jsonl", [{"stage": "standalone_verification", "stats": verified.stats.get("verification") or {}}])
    typer.echo(f"Wrote verified review outputs to {out}")


@app.command("review-action")
def review_action(
    out: Path = typer.Option(Path("outputs/github-action"), "--out", "-o", help="Output directory"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
    event_path: Path | None = typer.Option(None, "--event-path", help="Override GITHUB_EVENT_PATH for tests"),
    event_name: str | None = typer.Option(None, "--event-name", help="Override GITHUB_EVENT_NAME for tests"),
    publish_comment: bool = typer.Option(True, "--comment/--no-comment", help="Publish the summary comment to GitHub"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run review and render the comment without publishing it"),
) -> None:
    """Resolve the current GitHub Actions event, review it, and publish a summary comment."""
    load_dotenv_file()
    cfg = load_config(config)
    try:
        action_target = resolve_action_review_target(event_name=event_name, event_path=event_path)
    except GitHubActionSkip as exc:
        typer.echo(f"Skipped GitHub Actions review: {exc}")
        return

    requested_mode = normalize_verify_mode(os.getenv("PR_AGENT_VERIFY_MODE", "off"))
    mode = action_safe_verify_mode(requested_mode, action_target.is_fork_pull_request)
    verification_options = VerificationOptions(
        mode=mode,
        workspace=Path.cwd() if mode != "off" else None,
        budget=_env_int("PR_AGENT_VERIFY_MAX_FINDINGS", 3),
        timeout_seconds=_env_int("PR_AGENT_VERIFY_TIMEOUT_SECONDS", 45),
        artifacts_dir=out / "artifacts" / "verification" if mode != "off" else None,
        sandbox_allowed_for_remote=mode == "sandbox" and not action_target.is_fork_pull_request,
        publish_policy=os.getenv("PR_AGENT_PUBLISH_POLICY", "verified_or_high_confidence"),
    )
    review_run = run_review(action_target.target, cfg, repo_root=Path.cwd(), verification_options=verification_options)
    write_review_outputs(review_run, out)
    _write_json(out / "github_action_target.json", asdict(action_target))
    comment_body = build_summary_comment(review_run.result)
    (out / "summary_comment.md").write_text(comment_body, encoding="utf-8")

    if dry_run or not publish_comment:
        typer.echo(f"Wrote review outputs and summary_comment.md to {out}; comment publishing disabled.")
        return

    github_client = GitHubClient(api_base_url=cfg.github.api_base_url, timeout_seconds=cfg.github.timeout_seconds)
    if action_target.comment_target_type == "pull_request":
        github_client.upsert_issue_comment(
            action_target.owner,
            action_target.repo,
            action_target.pull_number or 0,
            comment_body,
            SUMMARY_COMMENT_MARKER,
        )
        typer.echo(f"Published AI review summary to PR #{action_target.pull_number}.")
    else:
        commit_sha = action_target.commit_sha or review_run.result.pr.head_sha
        github_client.create_commit_comment(action_target.owner, action_target.repo, commit_sha, comment_body)
        typer.echo(f"Published AI review summary to commit {commit_sha[:12]}.")


@app.command("eval-dataset")
def eval_dataset(
    dataset: Path = typer.Option(Path("evaluation/cases.jsonl"), "--dataset", help="Evaluation JSONL dataset"),
    predictions: Path | None = typer.Option(None, "--predictions", help="Optional prediction JSONL file"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional path for eval_report.json"),
) -> None:
    """Validate the evaluation dataset and optionally score prediction records."""
    cases = load_evaluation_cases(dataset)
    prediction_rows = load_predictions(predictions) if predictions else None
    report = build_evaluation_report(cases, prediction_rows)
    report_json = report_to_json(report)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_json + "\n", encoding="utf-8")

    typer.echo(report_json)


@app.command("eval-report")
def eval_report(
    cases: Path = typer.Option(Path("evaluation/pr_cases.jsonl"), "--cases", help="PR evaluation JSONL cases"),
    predictions: Path | None = typer.Option(None, "--predictions", help="Optional PR prediction JSONL file"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional path for evaluation_report.json"),
    line_tolerance: int = typer.Option(3, "--line-tolerance", help="Allowed line distance for line_hit_rate"),
) -> None:
    """Build a PR-level evaluation report with validity, false-positive, fixability, latency, and token metrics."""
    pr_cases = load_pr_evaluation_cases(cases)
    prediction_rows = load_pr_predictions(predictions) if predictions else None
    report = build_pr_evaluation_report(pr_cases, prediction_rows, line_tolerance=line_tolerance)
    report_json = report_to_json(report)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_json + "\n", encoding="utf-8")

    typer.echo(report_json)


@app.command("eval-verification")
def eval_verification(
    cases: Path = typer.Option(Path("evaluation/verification_cases.jsonl"), "--cases", help="Verification evaluation JSONL cases"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional path for verification_evaluation_report.json"),
) -> None:
    """Summarize v2.1 verification cases and expected status coverage."""
    verification_cases = load_verification_cases(cases)
    report = summarize_verification_cases(verification_cases)
    report_json = report_to_json(report)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_json + "\n", encoding="utf-8")
    typer.echo(report_json)


@app.command("eval-run")
def eval_run(
    cases: Path = typer.Option(Path("evaluation/runnable_pr_cases.jsonl"), "--cases", help="Runnable PR evaluation JSONL cases"),
    out: Path = typer.Option(Path("examples/evaluation/run"), "--out", "-o", help="Output directory for predictions and reports"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
    llm_mode: str = typer.Option("deterministic", "--llm-mode", help="deterministic or live"),
    line_tolerance: int = typer.Option(3, "--line-tolerance", help="Allowed line distance for line_hit_rate"),
) -> None:
    """Run reviewer over executable PR cases, write predictions, and build the evaluation report."""
    load_dotenv_file()
    cfg = load_config(config)
    if llm_mode not in {"deterministic", "live"}:
        raise typer.BadParameter("--llm-mode must be deterministic or live")
    result = run_pr_evaluation(
        cases_path=cases,
        out=out,
        cfg=cfg,
        llm_mode=llm_mode,  # type: ignore[arg-type]
        line_tolerance=line_tolerance,
    )
    typer.echo(report_to_json(result.report))


@app.command("run-live-e2e")
def run_live_e2e_command(
    cases: Path = typer.Option(Path("evaluation/live_e2e_cases.jsonl"), "--cases", help="Live E2E JSONL cases"),
    out: Path = typer.Option(Path("outputs/live-e2e"), "--out", "-o", help="Output directory for live E2E outputs"),
    config: Path | None = typer.Option(None, "--config", help="Config YAML path"),
    verify: str = typer.Option("static", "--verify", help="Verification mode: off, static, or sandbox"),
    verification_budget: int = typer.Option(3, "--verification-budget", help="Maximum findings to verify per case"),
    verification_timeout: int = typer.Option(45, "--verification-timeout", help="Per sandbox tool timeout in seconds"),
) -> None:
    """Run live LLM E2E cases and write outputs for manual judgement."""
    load_dotenv_file()
    cfg = load_config(config)
    result = run_live_e2e(
        cases_path=cases,
        out=out,
        cfg=cfg,
        verify_mode=verify,
        verification_budget=verification_budget,
        verification_timeout=verification_timeout,
    )
    typer.echo(json.dumps(result.manifest, ensure_ascii=True, indent=2))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _change_set_from_review_result(result: ReviewResult) -> ChangeSet:
    paths = list(dict.fromkeys(finding.file_path for finding in result.findings))
    files = [
        ChangedFile(filename=path, status="modified", additions=0, deletions=0, changes=0, patch="")
        for path in paths
    ]
    return ChangeSet(target=result.pr, files=files, hunks_by_file={path: [] for path in paths})


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
