"""Mypy runner wrapper for the Docker sandbox executor."""

from __future__ import annotations

from pathlib import Path

from pr_agent.review.schema import ToolResult
from pr_agent.tools.sandbox import SandboxExecutor


def run_mypy(
    repo_root: Path,
    paths: list[str],
    timeout_seconds: int,
    artifact_dir: Path | None = None,
    executor: SandboxExecutor | None = None,
) -> ToolResult:
    return (executor or SandboxExecutor()).run_mypy(repo_root, paths, timeout_seconds, artifact_dir)
