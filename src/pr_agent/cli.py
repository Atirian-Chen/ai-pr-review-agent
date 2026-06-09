"""CLI 入口：提供 fetch 和 review 两个本地 MVP 命令。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer

from pr_agent.config import load_config
from pr_agent.evaluation.dataset import build_evaluation_report, load_evaluation_cases, load_predictions, report_to_json
from pr_agent.github.actions import GitHubActionSkip, resolve_action_review_target
from pr_agent.github.client import GitHubClient
from pr_agent.github.comments import SUMMARY_COMMENT_MARKER, build_summary_comment
from pr_agent.review.runner import load_change_set, run_review, write_review_outputs
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
) -> None:
    """Run the full MVP review and write JSON, Markdown, and trace files."""
    load_dotenv_file()
    cfg = load_config(config)
    review_run = run_review(target, cfg)
    write_review_outputs(review_run, out)
    typer.echo(f"Wrote review_result.json and review_report.md to {out}")


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

    review_run = run_review(action_target.target, cfg)
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
