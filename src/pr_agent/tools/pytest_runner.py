"""Pytest runner wrapper for the Docker sandbox executor."""

from __future__ import annotations

from pathlib import Path

from pr_agent.review.schema import ToolResult
from pr_agent.tools.sandbox import SandboxExecutor


def run_pytest(
    repo_root: Path,
    test_path: str,
    timeout_seconds: int,
    artifact_dir: Path | None = None,
    executor: SandboxExecutor | None = None,
) -> ToolResult:
    return (executor or SandboxExecutor()).run_pytest(repo_root, test_path, timeout_seconds, artifact_dir)

